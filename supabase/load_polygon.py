#!/usr/bin/env python3
"""
GeoJSON → Supabase zone_polygons Loader
Adamson Group Real Estate Data Pipeline

Loads polygon boundaries drawn in geojson.io (or any GeoJSON tool) into
the Supabase zone_polygons table. Idempotent: re-running with the same
zone_name replaces the existing polygon so you can refine boundaries
and re-load without duplicates.

After loading, call fn_reenrich_all_listings() (or run with --reenrich)
to recompute detected_area on all existing listings.

Requirements:
    pip install psycopg2-binary

Usage:
    # Single polygon, properties set via CLI
    python load_polygon.py bird-key.geojson \\
        --area-slug bird-key \\
        --zone-name "Bird Key" \\
        --zone-type island \\
        --reenrich

    # Multi-feature GeoJSON where each feature has area_slug/zone_name/zone_type
    # in its `properties` block (drawn in geojson.io with the property editor)
    python load_polygon.py zones.geojson --reenrich

    # Dry run — show what would be loaded without writing
    python load_polygon.py bird-key.geojson --area-slug bird-key --dry-run

GeoJSON expectations:
    - Either a FeatureCollection or a single Feature
    - Geometry type: Polygon (outer ring only; inner rings / holes ignored)
    - MultiPolygon is supported; each ring loaded as a separate zone_polygons row
    - Coordinates in WGS84 (lng, lat) — geojson.io default

Property resolution order (per feature):
    1. Feature.properties.area_slug / zone_name / zone_type
    2. CLI flags (--area-slug / --zone-name / --zone-type)
    3. Error if still missing area_slug or zone_name
"""

import argparse
import json
import os
import sys
import logging
from pathlib import Path

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_FILE = PROJECT_ROOT / ".env"


def load_env(env_path):
    """Minimal .env loader."""
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


load_env(ENV_FILE)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "polygons.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("polygon_loader")


# ---------------------------------------------------------------------------
# GeoJSON parsing
# ---------------------------------------------------------------------------

def iter_features(geojson):
    """Normalize input to a list of features."""
    t = geojson.get("type")
    if t == "FeatureCollection":
        return geojson.get("features", [])
    if t == "Feature":
        return [geojson]
    raise ValueError(
        f"Unsupported top-level GeoJSON type: {t!r}. "
        "Expected Feature or FeatureCollection."
    )


def polygon_rings_to_wkt(outer_ring):
    """
    Convert a single polygon outer ring (list of [lng, lat] pairs) to a
    PostGIS WKT POLYGON string.

    Ignores inner rings / holes. geojson.io rarely produces those for area
    boundaries. If we need them later we can extend this.
    """
    # Ensure the ring is closed (first == last)
    if outer_ring[0] != outer_ring[-1]:
        outer_ring = outer_ring + [outer_ring[0]]
    coord_strs = [f"{lng} {lat}" for lng, lat in outer_ring]
    return "POLYGON((" + ", ".join(coord_strs) + "))"


def extract_polygons(feature, defaults):
    """
    Return a list of (zone_name, zone_type, area_slug, wkt) tuples from a
    feature. Handles Polygon and MultiPolygon geometries. A MultiPolygon
    produces one row per ring with '(part N)' appended to zone_name.
    """
    geom = feature.get("geometry") or {}
    gtype = geom.get("type")
    props = feature.get("properties") or {}

    area_slug = props.get("area_slug") or defaults.get("area_slug")
    zone_name = props.get("zone_name") or defaults.get("zone_name")
    zone_type = props.get("zone_type") or defaults.get("zone_type")

    if not area_slug:
        raise ValueError(
            "Missing area_slug. Provide via --area-slug CLI flag or "
            "feature.properties.area_slug in the GeoJSON."
        )
    if not zone_name:
        raise ValueError(
            "Missing zone_name. Provide via --zone-name CLI flag or "
            "feature.properties.zone_name in the GeoJSON."
        )

    out = []
    if gtype == "Polygon":
        outer = geom["coordinates"][0]
        out.append((zone_name, zone_type, area_slug, polygon_rings_to_wkt(outer)))
    elif gtype == "MultiPolygon":
        for idx, poly in enumerate(geom["coordinates"], start=1):
            outer = poly[0]
            suffix = f" (part {idx})" if len(geom["coordinates"]) > 1 else ""
            out.append(
                (
                    f"{zone_name}{suffix}",
                    zone_type,
                    area_slug,
                    polygon_rings_to_wkt(outer),
                )
            )
    else:
        raise ValueError(
            f"Unsupported geometry type: {gtype!r}. "
            "Expected Polygon or MultiPolygon."
        )
    return out


# ---------------------------------------------------------------------------
# Database ops
# ---------------------------------------------------------------------------

def verify_area_slug_exists(conn, area_slug):
    """Fail fast if area_slug doesn't match a row in areas table (FK would reject)."""
    with conn.cursor() as cur:
        cur.execute("SELECT slug FROM areas WHERE slug = %s", (area_slug,))
        if not cur.fetchone():
            cur.execute("SELECT slug FROM areas ORDER BY slug")
            available = [r[0] for r in cur.fetchall()]
            raise ValueError(
                f"area_slug {area_slug!r} not found in areas table. "
                f"Available slugs: {available}"
            )


def upsert_polygon(conn, zone_name, zone_type, area_slug, wkt):
    """
    Idempotent insert: delete any existing polygons with the same zone_name
    (under the same area_slug), then insert the new one. This makes re-running
    the loader safe when polygons are being refined.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM zone_polygons
            WHERE area_slug = %s AND zone_name = %s
            """,
            (area_slug, zone_name),
        )
        deleted = cur.rowcount

        cur.execute(
            """
            INSERT INTO zone_polygons (area_slug, zone_name, zone_type, boundary)
            VALUES (%s, %s, %s, ST_GeogFromText('SRID=4326;' || %s))
            RETURNING id
            """,
            (area_slug, zone_name, zone_type, wkt),
        )
        new_id = cur.fetchone()[0]
        return deleted, new_id


def reenrich_all_listings(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT fn_reenrich_all_listings()")
        return cur.fetchone()[0]


def area_counts(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM vw_area_listing_counts")
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Load GeoJSON polygons into Supabase zone_polygons."
    )
    parser.add_argument(
        "geojson_file",
        type=Path,
        help="Path to GeoJSON file (Feature or FeatureCollection).",
    )
    parser.add_argument(
        "--area-slug",
        help="Default area_slug if feature properties don't set one. "
             "Must match a row in the areas table.",
    )
    parser.add_argument(
        "--zone-name",
        help="Default zone_name if feature properties don't set one. "
             "Used as the idempotency key with area_slug.",
    )
    parser.add_argument(
        "--zone-type",
        help="Default zone_type (e.g. 'island', 'beachfront', 'bayside'). Optional.",
    )
    parser.add_argument(
        "--reenrich",
        action="store_true",
        help="After loading, call fn_reenrich_all_listings() so detected_area "
             "refreshes on all existing raw_listings rows.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate without writing to the database.",
    )
    args = parser.parse_args()

    if not DATABASE_URL:
        sys.exit("Missing DATABASE_URL in .env file.")

    if not args.geojson_file.exists():
        sys.exit(f"File not found: {args.geojson_file}")

    with open(args.geojson_file) as f:
        geojson = json.load(f)

    features = iter_features(geojson)
    log.info(f"Parsed {len(features)} feature(s) from {args.geojson_file}")

    defaults = {
        "area_slug": args.area_slug,
        "zone_name": args.zone_name,
        "zone_type": args.zone_type,
    }

    # Extract all polygons up front so we fail fast on validation errors
    # before opening a connection.
    polygons = []
    for feat in features:
        polygons.extend(extract_polygons(feat, defaults))

    log.info(f"Extracted {len(polygons)} polygon ring(s) to load:")
    for zone_name, zone_type, area_slug, wkt in polygons:
        vertex_count = wkt.count(",") + 1
        log.info(
            f"  - {area_slug} / {zone_name} "
            f"(type={zone_type or '—'}, {vertex_count} vertices)"
        )

    if args.dry_run:
        log.info("Dry run — no database writes.")
        return

    conn = psycopg2.connect(DATABASE_URL)
    try:
        # Verify all area_slugs exist before any inserts
        seen_slugs = {p[2] for p in polygons}
        for slug in seen_slugs:
            verify_area_slug_exists(conn, slug)

        total_deleted = 0
        for zone_name, zone_type, area_slug, wkt in polygons:
            deleted, new_id = upsert_polygon(
                conn, zone_name, zone_type, area_slug, wkt
            )
            total_deleted += deleted
            action = "replaced" if deleted else "inserted"
            log.info(f"  {action}: {area_slug} / {zone_name} (id={new_id})")

        conn.commit()
        log.info(
            f"Loaded {len(polygons)} polygon(s); "
            f"{total_deleted} existing replaced."
        )

        if args.reenrich:
            log.info("Re-enriching all raw_listings rows...")
            updated = reenrich_all_listings(conn)
            conn.commit()
            log.info(f"Re-enriched {updated} listings.")

            log.info("Current area breakdown:")
            for row in area_counts(conn):
                log.info(
                    f"  {row['area_slug']:25s}  "
                    f"total={row['listing_count']:4d}  "
                    f"active={row['active_count']:4d}  "
                    f"sold={row['sold_count']:4d}"
                )
        else:
            log.info(
                "Skipped re-enrichment. Run with --reenrich "
                "(or call SELECT fn_reenrich_all_listings(); in SQL) "
                "to update detected_area on existing rows."
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()

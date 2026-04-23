#!/usr/bin/env python3
"""
Supabase → src/data/<area-slug>-stats.json

Queries raw_listings for an area's Sold + Pending listings and computes the
6 metrics rendered on the area page's detailed stats table:

    - avg_price          (current_price)
    - avg_price_per_sqft (current_price / living_area)
    - avg_year_built     (year_built)
    - avg_living_sqft    (living_area, the "heated" sqft)
    - avg_lot_sqft       (lot_size_square_feet)
    - avg_dom            (days_on_market)

Also includes counts broken down by status so the page can show
"N sold, M pending" context.

Usage:
    python scripts/fetch_area_stats.py bird-key
    python scripts/fetch_area_stats.py lido-key --output src/data/lido-key-stats.json

Requires DATABASE_URL in AG_website/.env (same one ingest_mls.py uses).
Safe to run anytime — writes a single JSON file atomically.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_FILE = PROJECT_ROOT / ".env"


def load_env(env_path):
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


load_env(ENV_FILE)
DATABASE_URL = os.environ.get("DATABASE_URL", "")


STATS_QUERY = """
WITH target AS (
    SELECT *
    FROM raw_listings
    WHERE detected_area = %(slug)s
      AND mls_status IN ('Sold', 'Pending')
)
SELECT
    COUNT(*) AS total_count,
    COUNT(*) FILTER (WHERE mls_status = 'Sold') AS sold_count,
    COUNT(*) FILTER (WHERE mls_status = 'Pending') AS pending_count,
    AVG(current_price) FILTER (WHERE current_price IS NOT NULL) AS avg_price,
    AVG(CASE WHEN living_area > 0 THEN current_price / living_area END) AS avg_price_per_sqft,
    AVG(year_built) FILTER (WHERE year_built IS NOT NULL) AS avg_year_built,
    AVG(living_area) FILTER (WHERE living_area > 0) AS avg_living_sqft,
    AVG(lot_size_square_feet) FILTER (WHERE lot_size_square_feet > 0) AS avg_lot_sqft,
    AVG(days_on_market) FILTER (WHERE days_on_market IS NOT NULL) AS avg_dom,
    MIN(current_price) FILTER (WHERE current_price IS NOT NULL) AS min_price,
    MAX(current_price) FILTER (WHERE current_price IS NOT NULL) AS max_price
FROM target;
"""


def as_currency(n):
    if n is None:
        return None
    return f"${int(round(float(n))):,}"


def as_int(n):
    if n is None:
        return None
    return int(round(float(n)))


def as_sqft(n):
    if n is None:
        return None
    return f"{int(round(float(n))):,}"


def compute(slug, conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(STATS_QUERY, {"slug": slug})
        row = cur.fetchone()

    if not row or row["total_count"] == 0:
        return {
            "areaSlug": slug,
            "source": "supabase",
            "status": "no_data",
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "counts": {"sold": 0, "pending": 0, "total": 0},
            "metrics": {},
        }

    return {
        "areaSlug": slug,
        "source": "supabase",
        "status": "ok",
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "sold": row["sold_count"],
            "pending": row["pending_count"],
            "total": row["total_count"],
        },
        "metrics": {
            "avgPrice": as_currency(row["avg_price"]),
            "avgPricePerSqFt": as_currency(row["avg_price_per_sqft"]),
            "avgYearBuilt": as_int(row["avg_year_built"]),
            "avgLivingSqFt": as_sqft(row["avg_living_sqft"]),
            "avgLotSqFt": as_sqft(row["avg_lot_sqft"]),
            "avgDom": as_int(row["avg_dom"]),
        },
        "range": {
            "minPrice": as_currency(row["min_price"]),
            "maxPrice": as_currency(row["max_price"]),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch area sold+pending stats from Supabase.")
    parser.add_argument("slug", help="Area slug (e.g. 'bird-key', 'lido-key'). Must match raw_listings.detected_area.")
    parser.add_argument(
        "--output",
        help="Output path. Defaults to src/data/<slug>-stats.json relative to project root.",
    )
    args = parser.parse_args()

    if not DATABASE_URL:
        sys.exit("Missing DATABASE_URL in .env")

    out_path = Path(args.output) if args.output else PROJECT_ROOT / "src" / "data" / f"{args.slug}-stats.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = psycopg2.connect(DATABASE_URL)
    try:
        data = compute(args.slug, conn)
    finally:
        conn.close()

    # Atomic write
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(out_path)

    print(f"Wrote {out_path}")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()

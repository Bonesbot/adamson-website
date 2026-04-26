#!/usr/bin/env python3
"""
Supabase -> src/data/<area-slug>-stats.json (ENRICHED)

Comprehensive market summary for an area, structured for AEO consumption.
Backwards compatible with DetailedMarketTable.astro (preserves the original
counts/metrics/range fields) and adds extra fields consumed by the new
AreaMarketSummary.astro component.

Extra fields:
    - active.{count, medianPrice, medianPricePerSqFt, waterfrontCount, newConstructionCount}
    - sold.{count, medianPrice, medianDom, saleToListRatio}
    - fees.{medianMonthlyAssociation, medianMonthlyCondoFee}
    - priceBands (active inventory split into 4 bands)
    - propertyTypes (active inventory by property_type)
    - buildingClasses (active inventory by building_class)
    - recentSoldComps (top 5 most recent sold listings)

Usage:
    python scripts/fetch_area_summary.py lido-key
    python scripts/fetch_area_summary.py downtown-sarasota
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


def fmt_currency(n):
    if n is None: return None
    return f"${int(round(float(n))):,}"

def fmt_int(n):
    if n is None: return None
    return int(round(float(n)))

def fmt_sqft(n):
    if n is None: return None
    return f"{int(round(float(n))):,}"

def fmt_pct(n, digits=1):
    if n is None: return None
    return f"{float(n) * 100:.{digits}f}%"


HEADLINE_QUERY = """
WITH t AS (
    SELECT * FROM raw_listings WHERE detected_area = %(slug)s
)
SELECT
    COUNT(*) FILTER (WHERE mls_status = 'Active')                                     AS active_count,
    COUNT(*) FILTER (WHERE mls_status = 'Pending')                                    AS pending_count,
    COUNT(*) FILTER (WHERE mls_status = 'Sold')                                       AS sold_count,
    COUNT(*)                                                                           AS total_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)
        FILTER (WHERE mls_status = 'Active' AND current_price IS NOT NULL)            AS active_median_price,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY (current_price / NULLIF(living_area,0)))
        FILTER (WHERE mls_status = 'Active' AND living_area > 0)                      AS active_median_psf,
    AVG(current_price) FILTER (WHERE mls_status IN ('Sold','Pending') AND current_price IS NOT NULL) AS avg_price,
    AVG(CASE WHEN living_area > 0 THEN current_price / living_area END)
        FILTER (WHERE mls_status IN ('Sold','Pending'))                               AS avg_psf,
    AVG(year_built) FILTER (WHERE mls_status IN ('Sold','Pending') AND year_built IS NOT NULL) AS avg_year_built,
    AVG(living_area) FILTER (WHERE mls_status IN ('Sold','Pending') AND living_area > 0) AS avg_living_sqft,
    AVG(lot_size_square_feet) FILTER (WHERE mls_status IN ('Sold','Pending') AND lot_size_square_feet > 0) AS avg_lot_sqft,
    AVG(days_on_market) FILTER (WHERE mls_status IN ('Sold','Pending') AND days_on_market IS NOT NULL) AS avg_dom,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)
        FILTER (WHERE mls_status = 'Sold' AND current_price IS NOT NULL)              AS sold_median_price,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days_on_market)
        FILTER (WHERE mls_status = 'Sold' AND days_on_market IS NOT NULL)             AS sold_median_dom,
    AVG(current_price / NULLIF(original_list_price, 0))
        FILTER (WHERE mls_status = 'Sold' AND original_list_price > 0)                AS sale_to_list_ratio,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY monthly_association_cost)
        FILTER (WHERE monthly_association_cost > 0)                                   AS median_monthly_assoc,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY monthly_condo_fee_amount)
        FILTER (WHERE monthly_condo_fee_amount > 0)                                   AS median_monthly_condo_fee,
    MIN(current_price) FILTER (WHERE current_price IS NOT NULL)                        AS min_price,
    MAX(current_price) FILTER (WHERE current_price IS NOT NULL)                        AS max_price,
    COUNT(*) FILTER (WHERE is_waterfront = TRUE)                                       AS waterfront_count,
    COUNT(*) FILTER (WHERE is_waterfront = TRUE AND mls_status = 'Active')             AS active_waterfront_count,
    COUNT(*) FILTER (WHERE year_built >= 2020)                                         AS new_construction_count,
    COUNT(*) FILTER (WHERE year_built >= 2020 AND mls_status = 'Active')               AS active_new_construction_count
FROM t;
"""

PRICE_BAND_QUERY = """
SELECT
    COUNT(*) FILTER (WHERE current_price < 900000)                              AS under_900k,
    COUNT(*) FILTER (WHERE current_price >= 900000 AND current_price < 1500000) AS band_900k_1_5m,
    COUNT(*) FILTER (WHERE current_price >= 1500000 AND current_price < 3000000) AS band_1_5m_3m,
    COUNT(*) FILTER (WHERE current_price >= 3000000)                            AS band_3m_plus
FROM raw_listings
WHERE detected_area = %(slug)s AND mls_status = 'Active' AND current_price IS NOT NULL;
"""

PROPERTY_TYPE_QUERY = """
SELECT property_type, COUNT(*) AS cnt
FROM raw_listings
WHERE detected_area = %(slug)s AND mls_status = 'Active'
GROUP BY property_type
ORDER BY cnt DESC;
"""

BUILDING_CLASS_QUERY = """
SELECT building_class, COUNT(*) AS cnt
FROM raw_listings
WHERE detected_area = %(slug)s AND mls_status = 'Active' AND building_class IS NOT NULL
GROUP BY building_class
ORDER BY cnt DESC;
"""

TOP_SOLD_COMPS_QUERY = """
SELECT
    listing_id,
    unparsed_address,
    subdivision_name,
    current_price,
    close_date,
    bedrooms_total,
    bathrooms_full,
    bathrooms_half,
    living_area,
    year_built,
    property_type,
    is_waterfront
FROM raw_listings
WHERE detected_area = %(slug)s
  AND mls_status = 'Sold'
  AND close_date IS NOT NULL
ORDER BY close_date DESC, current_price DESC NULLS LAST
LIMIT 5;
"""


def compute_summary(slug, conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(HEADLINE_QUERY, {"slug": slug})
        head = cur.fetchone()
        cur.execute(PRICE_BAND_QUERY, {"slug": slug})
        bands = cur.fetchone() or {}
        cur.execute(PROPERTY_TYPE_QUERY, {"slug": slug})
        prop_types = cur.fetchall()
        cur.execute(BUILDING_CLASS_QUERY, {"slug": slug})
        bldg_classes = cur.fetchall()
        cur.execute(TOP_SOLD_COMPS_QUERY, {"slug": slug})
        comps = cur.fetchall()

    if not head or head["total_count"] == 0:
        return {
            "areaSlug": slug,
            "source": "supabase",
            "status": "no_data",
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "counts": {"active": 0, "pending": 0, "sold": 0, "total": 0},
            "metrics": {},
        }

    return {
        "areaSlug": slug,
        "source": "supabase",
        "status": "ok",
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "sold": head["sold_count"],
            "pending": head["pending_count"],
            "active": head["active_count"],
            "total": head["sold_count"] + head["pending_count"],
        },
        "metrics": {
            "avgPrice": fmt_currency(head["avg_price"]),
            "avgPricePerSqFt": fmt_currency(head["avg_psf"]),
            "avgYearBuilt": fmt_int(head["avg_year_built"]),
            "avgLivingSqFt": fmt_sqft(head["avg_living_sqft"]),
            "avgLotSqFt": fmt_sqft(head["avg_lot_sqft"]),
            "avgDom": fmt_int(head["avg_dom"]),
        },
        "range": {
            "minPrice": fmt_currency(head["min_price"]),
            "maxPrice": fmt_currency(head["max_price"]),
        },
        "active": {
            "count": head["active_count"],
            "medianPrice": fmt_currency(head["active_median_price"]),
            "medianPricePerSqFt": fmt_currency(head["active_median_psf"]),
            "waterfrontCount": head["active_waterfront_count"],
            "newConstructionCount": head["active_new_construction_count"],
        },
        "sold": {
            "count": head["sold_count"],
            "medianPrice": fmt_currency(head["sold_median_price"]),
            "medianDom": fmt_int(head["sold_median_dom"]),
            "saleToListRatio": fmt_pct(head["sale_to_list_ratio"]),
        },
        "fees": {
            "medianMonthlyAssociation": fmt_currency(head["median_monthly_assoc"]),
            "medianMonthlyCondoFee": fmt_currency(head["median_monthly_condo_fee"]),
        },
        "priceBands": {
            "under900k": bands.get("under_900k", 0),
            "band900kTo1_5m": bands.get("band_900k_1_5m", 0),
            "band1_5mTo3m": bands.get("band_1_5m_3m", 0),
            "band3mPlus": bands.get("band_3m_plus", 0),
        },
        "propertyTypes": [
            {"type": r["property_type"] or "Unknown", "count": r["cnt"]}
            for r in prop_types
        ],
        "buildingClasses": [
            {"class": r["building_class"], "count": r["cnt"]}
            for r in bldg_classes
        ],
        "recentSoldComps": [
            {
                "listingId": c["listing_id"],
                "address": c["unparsed_address"],
                "subdivision": c["subdivision_name"],
                "soldPrice": fmt_currency(c["current_price"]),
                "soldDate": c["close_date"].isoformat() if c["close_date"] else None,
                "bedrooms": c["bedrooms_total"],
                "bathrooms": (c["bathrooms_full"] or 0) + 0.5 * (c["bathrooms_half"] or 0),
                "livingSqFt": fmt_sqft(c["living_area"]),
                "yearBuilt": c["year_built"],
                "propertyType": c["property_type"],
                "isWaterfront": bool(c["is_waterfront"]),
            }
            for c in comps
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    parser.add_argument("--output")
    args = parser.parse_args()
    if not DATABASE_URL: sys.exit("Missing DATABASE_URL")
    out_path = Path(args.output) if args.output else PROJECT_ROOT / "src" / "data" / f"{args.slug}-stats.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    conn = psycopg2.connect(DATABASE_URL)
    try:
        data = compute_summary(args.slug, conn)
    finally:
        conn.close()
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

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
    - fees.{medianMonthlyAssociation, medianMonthlyCondoFee, minMonthlyCondoFee, maxMonthlyCondoFee, condoFeeRange}
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
    COUNT(*) FILTER (WHERE mls_status = 'Sold' AND close_date >= CURRENT_DATE - INTERVAL '90 days') AS sold90_count,
    COUNT(*) FILTER (WHERE mls_status = 'Sold' AND close_date >= CURRENT_DATE - INTERVAL '365 days') AS sold365_count,
    COUNT(*) FILTER (WHERE mls_status = 'Sold' AND close_date >= CURRENT_DATE - INTERVAL '365 days' AND property_sub_type = 'Condominium') AS sold365_condo,
    COUNT(*) FILTER (WHERE mls_status = 'Sold' AND close_date >= CURRENT_DATE - INTERVAL '365 days' AND property_sub_type IN ('Single Family Residence','Villa','Townhouse')) AS sold365_sfhv,
    COUNT(*) FILTER (WHERE mls_status = 'Active' AND property_sub_type = 'Condominium') AS active_condo,
    COUNT(*) FILTER (WHERE mls_status = 'Active' AND property_sub_type IN ('Single Family Residence','Villa','Townhouse')) AS active_sfhv,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)
        FILTER (WHERE mls_status = 'Sold' AND current_price IS NOT NULL AND close_date >= CURRENT_DATE - INTERVAL '90 days') AS sold90_median_price,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days_on_market)
        FILTER (WHERE mls_status = 'Sold' AND days_on_market IS NOT NULL AND close_date >= CURRENT_DATE - INTERVAL '90 days') AS sold90_median_dom,
    AVG(current_price / NULLIF(original_list_price, 0))
        FILTER (WHERE mls_status = 'Sold' AND original_list_price > 0 AND close_date >= CURRENT_DATE - INTERVAL '90 days') AS sold90_sale_to_list,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY monthly_association_cost)
        FILTER (WHERE monthly_association_cost > 0)                                   AS median_monthly_assoc,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY monthly_condo_fee_amount)
        FILTER (WHERE monthly_condo_fee_amount > 0)                                   AS median_monthly_condo_fee,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY monthly_condo_fee_amount)
        FILTER (WHERE monthly_condo_fee_amount >= 100)                               AS median_condo_fee_floored,
    MIN(monthly_condo_fee_amount) FILTER (WHERE monthly_condo_fee_amount >= 100)      AS min_monthly_condo_fee,
    MAX(monthly_condo_fee_amount) FILTER (WHERE monthly_condo_fee_amount >= 100)      AS max_monthly_condo_fee,
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
  AND close_date >= CURRENT_DATE - INTERVAL '90 days'
ORDER BY close_date DESC, current_price DESC NULLS LAST
LIMIT 5;
"""


CONDO_TIER_QUERY = """
WITH t AS (
    SELECT
        CASE
            WHEN year_built < 1990 THEN 'pre1990'
            WHEN year_built BETWEEN 1990 AND 2005 THEN '1990to2005'
            WHEN year_built BETWEEN 2006 AND 2019 THEN '2006to2019'
            WHEN year_built >= 2020 THEN '2020plus'
            ELSE 'unknown'
        END AS tier,
        current_price, living_area, days_on_market
    FROM raw_listings
    WHERE detected_area = %(slug)s
      AND mls_status = 'Active'
      AND property_sub_type IN ('Condominium','Villa','Townhouse')
)
SELECT
    tier,
    COUNT(*) AS active_count,
    AVG(current_price)                              FILTER (WHERE current_price IS NOT NULL) AS avg_price,
    AVG(current_price / NULLIF(living_area,0))      FILTER (WHERE living_area > 0)           AS avg_psf,
    AVG(living_area)                                FILTER (WHERE living_area > 0)           AS avg_living,
    AVG(days_on_market)                             FILTER (WHERE days_on_market IS NOT NULL) AS avg_dom
FROM t
GROUP BY tier;
"""

CONDO_TIER_DEFS = [
    ('pre1990',    'Pre-1990',           'before 1990'),
    ('1990to2005', '1990 \u2013 2005',  '1990 through 2005'),
    ('2006to2019', '2006 \u2013 2019',  '2006 through 2019'),
    ('2020plus',   '2020 & Newer',       '2020 or newer'),
]


def compute_condo_tiers(slug, conn):
    """Active condo/villa/townhouse inventory, grouped by construction era.
    Returns (tiers_list, scope_dict). Empty list if the area has no condos."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(CONDO_TIER_QUERY, {"slug": slug})
        by_tier = {r['tier']: r for r in cur.fetchall()}
    if not any(r.get('active_count') for r in by_tier.values()):
        return [], None
    out = []
    for key, label, range_label in CONDO_TIER_DEFS:
        r = by_tier.get(key) or {}
        out.append({
            'tier': key,
            'label': label,
            'rangeLabel': range_label,
            'activeCount': int(r.get('active_count') or 0),
            'avgPrice': fmt_currency(r.get('avg_price')),
            'avgPricePerSqFt': fmt_currency(r.get('avg_psf')),
            'avgLivingSqFt': fmt_sqft(r.get('avg_living')),
            'avgDom': fmt_int(r.get('avg_dom')),
        })
    scope = {'propertySubTypes': ['Condominium', 'Villa', 'Townhouse'], 'status': 'Active'}
    return out, scope


# ---- Extended groupings: waterfront segments, market balance, property-type split, living FAQ ----
WF_SEGMENT_QUERY = """
WITH t AS (
  SELECT *,
    CASE
      WHEN waterfront_features ILIKE '%%Gulf%%' OR waterfront_features ILIKE '%%Beach%%' OR waterfront_features ILIKE '%%Ocean%%' THEN 'gulf_beachfront'
      WHEN waterfront_features ILIKE '%%Bay%%' OR waterfront_features ILIKE '%%Canal%%' OR waterfront_features ILIKE '%%Intracoastal%%' OR waterfront_features ILIKE '%%Bayou%%' OR waterfront_features ILIKE '%%Lagoon%%' OR waterfront_features ILIKE '%%Marina%%' THEN 'bay_canal'
      WHEN waterfront_yn = TRUE THEN 'other_wf'
      WHEN water_view_yn = TRUE THEN 'waterview'
      ELSE 'none'
    END AS seg
  FROM raw_listings WHERE detected_area = %(slug)s
)
SELECT seg,
  COUNT(*) FILTER (WHERE mls_status='Active') AS active_n,
  COUNT(*) FILTER (WHERE mls_status='Sold')   AS sold_n,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY close_price_by_calculated_sqft)
    FILTER (WHERE mls_status='Sold' AND close_price_by_calculated_sqft IS NOT NULL) AS sold_psf,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)
    FILTER (WHERE mls_status='Sold' AND current_price IS NOT NULL) AS sold_price
FROM t GROUP BY seg;
"""

PTYPE_SPLIT_QUERY = """
WITH t AS (
  SELECT *,
    CASE
      WHEN property_sub_type ILIKE '%%Single Family%%' OR property_type ILIKE '%%Single Family%%' THEN 'single_family'
      WHEN property_sub_type ILIKE '%%Condo%%' OR property_sub_type ILIKE '%%Villa%%' OR property_sub_type ILIKE '%%Townhouse%%' THEN 'condo'
      ELSE 'other'
    END AS ptype
  FROM raw_listings WHERE detected_area = %(slug)s
)
SELECT ptype,
  COUNT(*) FILTER (WHERE mls_status='Active') AS active_n,
  COUNT(*) FILTER (WHERE mls_status='Sold')   AS sold_n,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)
    FILTER (WHERE mls_status='Sold' AND current_price IS NOT NULL) AS sold_price,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY close_price_by_calculated_sqft)
    FILTER (WHERE mls_status='Sold' AND close_price_by_calculated_sqft IS NOT NULL) AS sold_psf
FROM t GROUP BY ptype;
"""

WF_SEGMENT_QUERY_90 = """
WITH t AS (
  SELECT *,
    CASE
      WHEN waterfront_features ILIKE '%%Gulf%%' OR waterfront_features ILIKE '%%Beach%%' OR waterfront_features ILIKE '%%Ocean%%' THEN 'gulf_beachfront'
      WHEN waterfront_features ILIKE '%%Bay%%' OR waterfront_features ILIKE '%%Canal%%' OR waterfront_features ILIKE '%%Intracoastal%%' OR waterfront_features ILIKE '%%Bayou%%' OR waterfront_features ILIKE '%%Lagoon%%' OR waterfront_features ILIKE '%%Marina%%' THEN 'bay_canal'
      WHEN waterfront_yn = TRUE THEN 'other_wf'
      WHEN water_view_yn = TRUE THEN 'waterview'
      ELSE 'none'
    END AS seg
  FROM raw_listings
  WHERE detected_area = %(slug)s
    AND mls_status = 'Sold'
    AND close_date >= CURRENT_DATE - INTERVAL '90 days'
)
SELECT seg,
  COUNT(*) AS sold_n,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY close_price_by_calculated_sqft)
    FILTER (WHERE close_price_by_calculated_sqft IS NOT NULL) AS sold_psf,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)
    FILTER (WHERE current_price IS NOT NULL) AS sold_price
FROM t GROUP BY seg;
"""

PTYPE_SPLIT_QUERY_90 = """
WITH t AS (
  SELECT *,
    CASE
      WHEN property_sub_type ILIKE '%%Single Family%%' OR property_type ILIKE '%%Single Family%%' THEN 'single_family'
      WHEN property_sub_type ILIKE '%%Condo%%' OR property_sub_type ILIKE '%%Villa%%' OR property_sub_type ILIKE '%%Townhouse%%' THEN 'condo'
      ELSE 'other'
    END AS ptype
  FROM raw_listings
  WHERE detected_area = %(slug)s
    AND mls_status = 'Sold'
    AND close_date >= CURRENT_DATE - INTERVAL '90 days'
)
SELECT ptype,
  COUNT(*) AS sold_n,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)
    FILTER (WHERE current_price IS NOT NULL) AS sold_price,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY close_price_by_calculated_sqft)
    FILTER (WHERE close_price_by_calculated_sqft IS NOT NULL) AS sold_psf
FROM t GROUP BY ptype;
"""

BOATING_QUERY = """
SELECT
  COUNT(*) FILTER (WHERE mls_status='Active' AND has_dock = TRUE) AS active_dock,
  COUNT(*) FILTER (WHERE mls_status='Active' AND is_waterfront = TRUE) AS active_wf
FROM raw_listings WHERE detected_area = %(slug)s;
"""

SEG_LABELS = {"gulf_beachfront":"Gulf / Beachfront","bay_canal":"Bay / Canal-front",
              "waterview":"Water view (not waterfront)","other_wf":"Other waterfront","none":"No water"}
SEG_ORDER = ["gulf_beachfront","bay_canal","waterview","other_wf","none"]
MIN_N = 8  # suppress noisy segments

# ---- Per-area customization of the generated market-FAQ block ----
# Areas NOT listed fall back to DEFAULT_FAQ_CONFIG (current behavior, unchanged),
# so adding/altering an area is a few declarative lines here -- not a fork of the
# generator. Per area you may set:
#   drop   : set of generic facets to suppress {waterfront,balance,type,range,speed,boating,fees}
#   rename : {facet: replacement question text}  (answer text is left untouched)
#   cost   : ordered list of breakdown dimensions for a consolidated
#            "What do properties cost on <Area>?" question, computed over the
#            trailing 90 days of closed sales. Supported: 'property_type', 'waterfront'.
DEFAULT_FAQ_CONFIG = {"drop": set(), "rename": {}, "cost": None}

AREA_MARKET_FAQ = {
    "longboat-key": {
        "drop": {"waterfront", "type", "range"},
        "rename": {"balance": "Is it a good time to buy on Longboat Key?"},
        "cost": ["property_type", "waterfront"],
    },
}

def _faq_config(slug):
    cfg = dict(DEFAULT_FAQ_CONFIG)
    cfg.update(AREA_MARKET_FAQ.get(slug, {}))
    return cfg


COST_NUANCE = ("These are blended medians \u2014 actual value varies widely with a property's "
               "build era, specific views, amenities and level of updating. For a precise "
               "valuation on an investment this significant, lean on Ryan Adamson's local "
               "market guidance.")


def build_cost_question(name, sold90_count, cost_dims, pts90, segs90):
    """Consolidated, spoken-sentence cost answer over the trailing 90 days of closed
    sales, segmented by the area-specific value drivers in cost_dims.
    Returns (question_dict_or_None, structured_breakdown_dict)."""
    def _norm(r):
        if not r or not r.get("sold_n"):
            return None
        return {"soldCount": int(r["sold_n"]),
                "soldMedianPrice": fmt_currency(r.get("sold_price")),
                "soldMedianPricePerSqFt": fmt_currency(r.get("sold_psf"))}

    breakdown = {"windowDays": 90, "soldCount": int(sold90_count or 0)}
    frags = []

    if "property_type" in cost_dims:
        sf = pts90.get("single_family"); co = pts90.get("condo")
        breakdown["byPropertyType"] = {"condo": _norm(co), "single_family": _norm(sf)}
        if (sf and co and sf.get("sold_n", 0) >= MIN_N and co.get("sold_n", 0) >= MIN_N
                and sf.get("sold_price") and co.get("sold_price")):
            frags.append(
                f"By property type, condos, villas and townhouses closed at a median "
                f"{fmt_currency(co['sold_price'])} ({fmt_currency(co['sold_psf'])}/sq ft), "
                f"while single-family homes closed around {fmt_currency(sf['sold_price'])} "
                f"({fmt_currency(sf['sold_psf'])}/sq ft)")

    if "waterfront" in cost_dims:
        g = segs90.get("gulf_beachfront"); b = segs90.get("bay_canal")
        breakdown["byWaterfront"] = {"gulf_beachfront": _norm(g), "bay_canal": _norm(b)}
        # Compare by price-per-sq-ft, not raw median price: each location bucket mixes
        # condos and single-family homes, so a per-location median price is confounded
        # by property-type mix (beachfront skews to condos, bayfront to large SFHs).
        # Per-sq-ft is the mix-robust signal. Phrased neutrally so it stays correct
        # regardless of which side leads in a given 90-day window.
        if (g and b and g.get("sold_n", 0) >= MIN_N and b.get("sold_n", 0) >= MIN_N
                and g.get("sold_psf") and b.get("sold_psf")):
            frags.append(
                f"By location, Gulf-front and beachfront properties closed at a median "
                f"{fmt_currency(g['sold_psf'])} per square foot, compared with "
                f"{fmt_currency(b['sold_psf'])} for bay- and canal-front homes")

    if not frags:
        return None, breakdown
    lead = (f"Over the past 90 days, {int(sold90_count)} properties have closed on {name}. "
            if sold90_count else "")
    answer = lead + ". ".join(frags) + ". " + COST_NUANCE
    return {"facet": "cost", "q": f"What do properties cost on {name}?", "a": answer}, breakdown


def compute_extras(slug, conn, head):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(WF_SEGMENT_QUERY, {"slug": slug}); segs = {r["seg"]: r for r in cur.fetchall()}
        cur.execute(PTYPE_SPLIT_QUERY, {"slug": slug}); pts = {r["ptype"]: r for r in cur.fetchall()}
        cur.execute(BOATING_QUERY, {"slug": slug}); boat = cur.fetchone() or {}
        cur.execute(WF_SEGMENT_QUERY_90, {"slug": slug}); segs90 = {r["seg"]: r for r in cur.fetchall()}
        cur.execute(PTYPE_SPLIT_QUERY_90, {"slug": slug}); pts90 = {r["ptype"]: r for r in cur.fetchall()}

    # waterfront segments (suppress sold $/sqft when n < MIN_N)
    wf = []
    for k in SEG_ORDER:
        r = segs.get(k)
        if not r or (r["active_n"]==0 and r["sold_n"]==0): continue
        enough = r["sold_n"] and r["sold_n"] >= MIN_N
        wf.append({"segment":k,"label":SEG_LABELS[k],"activeCount":r["active_n"],"soldCount":r["sold_n"],
                   "soldMedianPricePerSqFt": fmt_currency(r["sold_psf"]) if enough else None,
                   "soldMedianPrice": fmt_currency(r["sold_price"]) if enough else None,
                   "lowSample": not enough})

    # market balance (months of supply from trailing-12mo sold, segmented by property class)
    active_n = head["active_count"] or 0; sold90 = head["sold90_count"] or 0
    sold365 = head["sold365_count"] or 0
    def _mos(a, s):
        return round(a / (s / 12.0), 1) if s else None
    mos = _mos(active_n, sold365)
    mos_condo = _mos(head["active_condo"] or 0, head["sold365_condo"] or 0)
    mos_sfhv = _mos(head["active_sfhv"] or 0, head["sold365_sfhv"] or 0)
    label = None
    if mos is not None:
        label = "seller's market" if mos < 5 else ("buyer's market" if mos > 7 else "balanced market")
    balance = {"monthsOfSupply": mos, "monthsOfSupplyCondo": mos_condo,
               "monthsOfSupplySfhVilla": mos_sfhv, "label": label,
               "activeCount": active_n, "sold365Count": sold365, "sold90Count": sold90,
               "method": "active / (trailing-12mo closed / 12)"}

    # property-type split
    ptype = {}
    for k in ("single_family","condo"):
        r = pts.get(k)
        if r and r["sold_n"]:
            ptype[k] = {"soldCount":r["sold_n"],"activeCount":r["active_n"],
                        "soldMedianPrice": fmt_currency(r["sold_price"]),
                        "soldMedianPricePerSqFt": fmt_currency(r["sold_psf"])}

    boating = {"activeWithDock": boat.get("active_dock"), "activeWaterfront": boat.get("active_wf")}

    # ---- living FAQ (generated from data; only questions we can answer) ----
    name = slug.replace("-"," ").title()
    q = []
    g = segs.get("gulf_beachfront"); bc = segs.get("bay_canal")
    if g and bc and g["sold_n"]>=MIN_N and bc["sold_n"]>=MIN_N and g["sold_psf"] and bc["sold_psf"]:
        prem = round((g["sold_psf"]/bc["sold_psf"]-1)*100)
        q.append({"facet":"waterfront","q":f"How much more does beachfront cost than bayfront on {name}?",
                  "a":f"Gulf-front / beachfront homes sell at a median {fmt_currency(g['sold_psf'])} per sq ft versus {fmt_currency(bc['sold_psf'])} for bay- or canal-front — about a {prem}% waterfront premium (Stellar MLS, recent closed sales)."})
    if mos is not None:
        q.append({"facet":"balance","q":f"Is {name} a buyer's or seller's market right now?",
                  "a":f"With {active_n} active listings and roughly {round(sold365/12.0)} closed sales a month (trailing 12 months), {name} has about {mos} months of supply — a {label} (under 5 favors sellers, over 7 favors buyers)."})
    if "single_family" in ptype and "condo" in ptype:
        q.append({"facet":"type","q":f"What does a single-family home cost versus a condo on {name}?",
                  "a":f"Single-family homes sell around {ptype['single_family']['soldMedianPrice']} ({ptype['single_family']['soldMedianPricePerSqFt']}/sq ft), while condos, villas and townhouses sell around {ptype['condo']['soldMedianPrice']} ({ptype['condo']['soldMedianPricePerSqFt']}/sq ft)."})
    if head.get("min_price") and head.get("max_price") and head.get("active_median_price"):
        q.append({"facet":"range","q":f"What's the price range on {name}?",
                  "a":f"Active listings run from {fmt_currency(head['min_price'])} to {fmt_currency(head['max_price'])}, with a median asking price of {fmt_currency(head['active_median_price'])}."})
    if head.get("sold90_median_dom") is not None and head.get("sold90_sale_to_list"):
        q.append({"facet":"speed","q":f"How quickly do homes sell on {name}?",
                  "a":f"Recently sold homes took a median {fmt_int(head['sold90_median_dom'])} days on market and closed at {fmt_pct(head['sold90_sale_to_list'])} of original list price (trailing 90 days)."})
    if boating.get("activeWaterfront"):
        q.append({"facet":"boating","q":f"Can I keep a boat — how many {name} homes have a dock?",
                  "a":f"Of {boating['activeWaterfront']} active waterfront listings, {boating.get('activeWithDock') or 0} include a private dock; bay- and canal-front homes with a dock and lift command a clear premium over those without."})
    if head.get("median_monthly_condo_fee") or head.get("median_monthly_assoc"):
        q.append({"facet":"fees","q":f"What are typical HOA and condo fees on {name}?",
                  "a":f"The median monthly condo fee is {fmt_currency(head.get('median_monthly_condo_fee'))} and the median monthly association fee is {fmt_currency(head.get('median_monthly_assoc'))}."})

    # ---- per-area customization: drop / rename generic questions, prepend cost question ----
    cfg = _faq_config(slug)
    if cfg["drop"]:
        q = [it for it in q if it["facet"] not in cfg["drop"]]
    for it in q:
        if it["facet"] in cfg["rename"]:
            it["q"] = cfg["rename"][it["facet"]]
    cost_bd = None
    if cfg["cost"]:
        cost_item, cost_bd = build_cost_question(name, head.get("sold90_count") or 0, cfg["cost"], pts90, segs90)
        if cost_item:
            q.insert(0, cost_item)

    return {"waterfrontSegments": wf, "marketBalance": balance, "propertyTypeSplit": ptype,
            "boating": boating, "marketQuestions": q, "costBreakdown90": cost_bd}


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

    condo_tiers_list, condo_tiers_scope = compute_condo_tiers(slug, conn)

    result = {
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
            "count": head["sold90_count"],
            "medianPrice": fmt_currency(head["sold90_median_price"]),
            "medianDom": fmt_int(head["sold90_median_dom"]),
            "saleToListRatio": fmt_pct(head["sold90_sale_to_list"]),
            "windowDays": 90,
        },
        "monthsOfSupply": {
            "condo": (round(head["active_condo"] / (head["sold365_condo"] / 12.0), 1) if head["sold365_condo"] else None),
            "sfhVilla": (round(head["active_sfhv"] / (head["sold365_sfhv"] / 12.0), 1) if head["sold365_sfhv"] else None),
            "blended": (round(head["active_count"] / (head["sold365_count"] / 12.0), 1) if head["sold365_count"] else None),
            "method": "active / (trailing-12mo closed / 12)",
            "windowDays": 365,
        },
        "fees": {
            "medianMonthlyAssociation": fmt_currency(head["median_monthly_assoc"]),
            "medianMonthlyCondoFee": fmt_currency(head["median_monthly_condo_fee"]),
            "minMonthlyCondoFee": fmt_currency(head["min_monthly_condo_fee"]),
            "maxMonthlyCondoFee": fmt_currency(head["max_monthly_condo_fee"]),
            "condoFeeRange": ({
                "min": fmt_int(head["min_monthly_condo_fee"]),
                "median": fmt_int(head["median_condo_fee_floored"]),
                "max": fmt_int(head["max_monthly_condo_fee"]),
            } if (head.get("min_monthly_condo_fee") and head.get("max_monthly_condo_fee")) else None),
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
        "condoTiers": condo_tiers_list,
        "condoTiersScope": condo_tiers_scope,
    }

    # _condo_heavy_trim: when this submarket has meaningful condo inventory,
    # suppress two fields that produce misleading or duplicative content on
    # the area page. avgLotSqFt sums whole-tower lots into a single number;
    # buildingClasses is replaced conceptually by the CondoTiersTable.
    if condo_tiers_list and any(t['activeCount'] for t in condo_tiers_list):
        if 'metrics' in result:
            result['metrics']['avgLotSqFt'] = None
        result['buildingClasses'] = []

    result.update(compute_extras(slug, conn, head))
    return result


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

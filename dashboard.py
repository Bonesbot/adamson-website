"""
Adamson Group — Sarasota Luxury Market Dashboard
Streamlit app connected to Supabase Postgres

Run: streamlit run dashboard.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Adamson Group — Market Dashboard",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load .env
ENV_FILE = Path(__file__).resolve().parent / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

# Prefer env var (local), fall back to st.secrets (Streamlit Cloud)
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    try:
        DATABASE_URL = st.secrets["DATABASE_URL"]
    except Exception:
        DATABASE_URL = ""

# Brand colors — CB Color Palette from brand guidelines
NAVY = "#2D4280"          # Subtle CB Blue (favorite)
DARK_BLUE = "#012169"     # Rich dark blue
BLUE_LIGHT = "#52a8ff"    # Celestial Blue 1 (fav coastal)
BLUE_COASTAL = "#418fde"  # Celestial Blue 2
GOLD = "#C5A55A"          # Adamson Group gold accent
PIANO_BLACK = "#2d2926"   # Matte black
COOL_GRAY = "#343d45"     # Muted gray
GRAY = "#a7a9ac"          # Standard gray
PEWTER = "#b7b9ba"        # Lighter gray
COLORS = [NAVY, GOLD, BLUE_LIGHT, COOL_GRAY, DARK_BLUE, BLUE_COASTAL, "#D4A84B"]

# Logo paths
LOGO_DIR = Path(__file__).resolve().parent / "assets" / "logos"
AG_LOGO = LOGO_DIR / "ag_logo_1.png"
CB_LOGO = LOGO_DIR / "cb_global_luxury.jpg"

# ---------------------------------------------------------------------------
# Currency formatter
# ---------------------------------------------------------------------------

def fmt_currency(val):
    """Format a number as $1,234,567 (no decimals)."""
    if val is None or pd.isna(val):
        return "$0"
    return f"${int(val):,}"

def currency_col(df, cols):
    """Format specific DataFrame columns as currency strings for display."""
    df = df.copy()
    for c in cols:
        if c in df.columns:
            df[c] = df[c].apply(fmt_currency)
    return df

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

@st.cache_resource
def get_connection():
    return psycopg2.connect(DATABASE_URL)

@st.cache_data(ttl=300)  # Cache for 5 minutes
def run_query(sql):
    conn = get_connection()
    try:
        return pd.read_sql(sql, conn)
    except Exception as e:
        # Reconnect on stale connection
        st.cache_resource.clear()
        conn = get_connection()
        return pd.read_sql(sql, conn)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Georgia&display=swap');
    .block-container { padding-top: 1rem; }
    h1 { color: #2D4280; font-family: Georgia, 'Times New Roman', serif; letter-spacing: 0.02em; }
    h2 { color: #C5A55A; border-bottom: 2px solid #C5A55A; padding-bottom: 0.3rem; font-family: Georgia, 'Times New Roman', serif; }
    h3 { color: #012169; font-family: Georgia, 'Times New Roman', serif; }
    .stMetric label { font-size: 0.85rem !important; color: #343d45 !important; }
    .stMetric [data-testid="stMetricValue"] { font-size: 1.8rem !important; color: #2D4280 !important; }
    section[data-testid="stSidebar"] { background-color: #012169; }
    section[data-testid="stSidebar"] * { color: #ffffff !important; }
    section[data-testid="stSidebar"] .stRadio label span { color: #b7b9ba !important; }
    section[data-testid="stSidebar"] .stRadio label[data-checked="true"] span { color: #C5A55A !important; font-weight: bold; }
    section[data-testid="stSidebar"] .stMultiSelect { color: #012169 !important; }
    .stDivider { border-color: #C5A55A; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

if AG_LOGO.exists():
    st.sidebar.image(str(AG_LOGO), use_column_width=True)
else:
    st.sidebar.title("Adamson Group")
st.sidebar.caption("Sarasota Luxury Real Estate")

page = st.sidebar.radio("Navigate", [
    "Pipeline Health",
    "Market Overview",
    "Lifestyle Search",
    "Subdivisions",
])

# Area filter (global)
areas_df = run_query("SELECT DISTINCT COALESCE(a.name, rl.detected_area, 'Unknown') AS area FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug ORDER BY area")
all_areas = areas_df["area"].tolist()
selected_areas = st.sidebar.multiselect("Filter by Area", all_areas, default=all_areas)

# Status filter
all_statuses = run_query("SELECT DISTINCT mls_status FROM raw_listings WHERE mls_status IS NOT NULL ORDER BY mls_status")["mls_status"].tolist()
selected_statuses = st.sidebar.multiselect("Filter by Status", all_statuses, default=[s for s in all_statuses if s in ("Active", "Active Under Contract", "Sold", "Pending")])

# Build WHERE clause
def area_filter():
    if not selected_areas:
        return "1=1"
    escaped = ", ".join(f"'{a}'" for a in selected_areas)
    return f"COALESCE(a.name, rl.detected_area, 'Unknown') IN ({escaped})"

def status_filter():
    if not selected_statuses:
        return "1=1"
    escaped = ", ".join(f"'{s}'" for s in selected_statuses)
    return f"rl.mls_status IN ({escaped})"

# ---------------------------------------------------------------------------
# Page: Market Overview
# ---------------------------------------------------------------------------

if page == "Market Overview":
    st.title("Sarasota Luxury Market Dashboard")

    # KPI row
    kpi = run_query(f"""
        SELECT
            count(*) AS total,
            count(*) FILTER (WHERE rl.mls_status IN ('Active', 'Active Under Contract')) AS active,
            count(*) FILTER (WHERE rl.mls_status = 'Sold') AS sold,
            ROUND(AVG(rl.current_price) FILTER (WHERE rl.current_price IS NOT NULL)) AS avg_price,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rl.current_price) FILTER (WHERE rl.current_price IS NOT NULL)) AS median_price,
            ROUND(AVG(rl.days_on_market) FILTER (WHERE rl.days_on_market IS NOT NULL)) AS avg_dom
        FROM raw_listings rl
        LEFT JOIN areas a ON rl.detected_area = a.slug
        WHERE {area_filter()} AND {status_filter()}
    """)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total Listings", f"{int(kpi['total'].iloc[0]):,}")
    c2.metric("Active", f"{int(kpi['active'].iloc[0]):,}")
    c3.metric("Sold", f"{int(kpi['sold'].iloc[0]):,}")
    c4.metric("Avg Price", fmt_currency(kpi['avg_price'].iloc[0]))
    c5.metric("Median Price", fmt_currency(kpi['median_price'].iloc[0]))
    c6.metric("Avg DOM", f"{int(kpi['avg_dom'].iloc[0] or 0)}")

    st.divider()

    # Market by area
    st.subheader("Market by Area")
    area_stats = run_query(f"""
        SELECT
            COALESCE(a.name, rl.detected_area, 'Unknown') AS area,
            count(*) AS listings,
            count(*) FILTER (WHERE rl.mls_status IN ('Active', 'Active Under Contract')) AS active,
            count(*) FILTER (WHERE rl.mls_status = 'Sold') AS sold,
            ROUND(AVG(rl.current_price) FILTER (WHERE rl.current_price IS NOT NULL)) AS avg_price,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rl.current_price) FILTER (WHERE rl.current_price IS NOT NULL)) AS median_price,
            ROUND(AVG(rl.days_on_market) FILTER (WHERE rl.days_on_market IS NOT NULL)) AS avg_dom,
            ROUND(AVG(CASE WHEN rl.living_area > 0 THEN rl.current_price / rl.living_area END)) AS avg_ppsf
        FROM raw_listings rl
        LEFT JOIN areas a ON rl.detected_area = a.slug
        WHERE {area_filter()} AND {status_filter()}
        GROUP BY COALESCE(a.name, rl.detected_area, 'Unknown')
        ORDER BY listings DESC
    """)

    col1, col2 = st.columns(2)
    with col1:
        fig = px.bar(
            area_stats, x="area", y="median_price",
            title="Median Price by Area",
            color_discrete_sequence=[NAVY],
            labels={"median_price": "Median Price", "area": ""},
        )
        fig.update_layout(yaxis_tickformat="$,.0f")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = px.bar(
            area_stats, x="area", y="avg_dom",
            title="Average Days on Market",
            color_discrete_sequence=[GOLD],
            labels={"avg_dom": "Avg DOM", "area": ""},
        )
        st.plotly_chart(fig, use_container_width=True)

    area_display = currency_col(area_stats, ["avg_price", "median_price", "avg_ppsf"])
    st.dataframe(
        area_display.rename(columns={
            "area": "Area", "listings": "Total", "active": "Active",
            "sold": "Sold", "avg_price": "Avg Price", "median_price": "Median Price",
            "avg_dom": "Avg DOM", "avg_ppsf": "Avg $/SqFt"
        }),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    # Price distribution
    st.subheader("Price Distribution")
    prices = run_query(f"""
        SELECT
            CASE
                WHEN current_price < 500000 THEN '1. Under $500K'
                WHEN current_price < 1000000 THEN '2. $500K - $1M'
                WHEN current_price < 2000000 THEN '3. $1M - $2M'
                WHEN current_price < 3000000 THEN '4. $2M - $3M'
                WHEN current_price < 5000000 THEN '5. $3M - $5M'
                ELSE '6. $5M+'
            END AS price_range,
            count(*) AS listings
        FROM raw_listings rl
        LEFT JOIN areas a ON rl.detected_area = a.slug
        WHERE rl.current_price IS NOT NULL AND {area_filter()} AND {status_filter()}
        GROUP BY price_range
        ORDER BY price_range
    """)
    prices["price_range"] = prices["price_range"].str[3:]  # Strip sort prefix

    fig = px.bar(
        prices, x="price_range", y="listings",
        title="Listings by Price Range",
        color_discrete_sequence=[NAVY],
        labels={"price_range": "", "listings": "Listings"},
    )
    st.plotly_chart(fig, use_container_width=True)

    # Property type breakdown
    st.subheader("Property Types")
    ptypes = run_query(f"""
        SELECT
            COALESCE(rl.property_sub_type, 'Unknown') AS type,
            count(*) AS listings,
            ROUND(AVG(rl.current_price)) AS avg_price,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rl.current_price) FILTER (WHERE rl.current_price IS NOT NULL)) AS median_price
        FROM raw_listings rl
        LEFT JOIN areas a ON rl.detected_area = a.slug
        WHERE {area_filter()} AND {status_filter()}
        GROUP BY rl.property_sub_type
        ORDER BY listings DESC
    """)

    col1, col2 = st.columns(2)
    with col1:
        fig = px.pie(
            ptypes, names="type", values="listings",
            title="Listings by Property Type",
            color_discrete_sequence=COLORS,
        )
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        ptypes_display = currency_col(ptypes, ["avg_price", "median_price"])
        st.dataframe(
            ptypes_display.rename(columns={
                "type": "Type", "listings": "Count",
                "avg_price": "Avg Price", "median_price": "Median Price"
            }),
            use_container_width=True,
            hide_index=True,
        )

# ---------------------------------------------------------------------------
# Page: Lifestyle Search
# ---------------------------------------------------------------------------

elif page == "Lifestyle Search":
    st.title("Lifestyle & Amenity Search")
    st.caption("The searches Zillow can't do — powered by enriched MLS data")

    # Amenity counts
    amenities = run_query(f"""
        SELECT
            'Waterfront' AS amenity, count(*) FILTER (WHERE rl.is_waterfront) AS active_listings FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        UNION ALL SELECT 'Gated Community', count(*) FILTER (WHERE rl.is_gated) FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        UNION ALL SELECT 'Golf Community', count(*) FILTER (WHERE rl.has_golf) FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        UNION ALL SELECT 'Dog Park', count(*) FILTER (WHERE rl.has_dog_park) FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        UNION ALL SELECT 'Fitness Center', count(*) FILTER (WHERE rl.has_fitness_center) FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        UNION ALL SELECT 'Tennis', count(*) FILTER (WHERE rl.has_tennis) FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        UNION ALL SELECT 'Pickleball', count(*) FILTER (WHERE rl.has_pickleball) FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        UNION ALL SELECT 'Community Pool', count(*) FILTER (WHERE rl.has_pool_community) FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        UNION ALL SELECT 'Restaurant On-Site', count(*) FILTER (WHERE rl.has_restaurant) FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        UNION ALL SELECT 'Natural Gas', count(*) FILTER (WHERE rl.has_natural_gas) FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        UNION ALL SELECT 'Elevator Building', count(*) FILTER (WHERE rl.has_elevator) FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        UNION ALL SELECT 'Dock/Boating', count(*) FILTER (WHERE rl.has_dock) FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        UNION ALL SELECT 'Turnkey/Furnished', count(*) FILTER (WHERE rl.is_turnkey) FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        UNION ALL SELECT 'Big Dog Friendly (50lb+)', count(*) FILTER (WHERE rl.big_dog_friendly) FROM raw_listings rl LEFT JOIN areas a ON rl.detected_area = a.slug WHERE rl.mls_status IN ('Active', 'Active Under Contract') AND {area_filter()}
        ORDER BY active_listings DESC
    """)

    fig = px.bar(
        amenities, x="active_listings", y="amenity",
        orientation="h",
        title="Active Listings by Lifestyle Amenity",
        color_discrete_sequence=[GOLD],
        labels={"active_listings": "Active Listings", "amenity": ""},
    )
    fig.update_layout(height=500, yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Amenity filter explorer
    st.subheader("Explore Listings by Amenity")

    amenity_filter = st.selectbox("Select an amenity to explore", [
        "Waterfront", "Gated Community", "Golf Community", "Dog Park",
        "Dock/Boating", "Turnkey/Furnished", "Natural Gas", "Elevator Building",
        "Big Dog Friendly", "Pickleball", "Tennis", "Fitness Center",
    ])

    amenity_col_map = {
        "Waterfront": "is_waterfront", "Gated Community": "is_gated",
        "Golf Community": "has_golf", "Dog Park": "has_dog_park",
        "Dock/Boating": "has_dock", "Turnkey/Furnished": "is_turnkey",
        "Natural Gas": "has_natural_gas", "Elevator Building": "has_elevator",
        "Big Dog Friendly": "big_dog_friendly", "Pickleball": "has_pickleball",
        "Tennis": "has_tennis", "Fitness Center": "has_fitness_center",
    }
    col_name = amenity_col_map[amenity_filter]

    detail = run_query(f"""
        SELECT
            rl.subdivision_name AS subdivision,
            COALESCE(a.name, 'Unknown') AS area,
            rl.unparsed_address AS address,
            rl.mls_status AS status,
            rl.current_price AS price,
            rl.bedrooms_total AS beds,
            rl.bathrooms_full AS baths,
            rl.living_area AS sqft,
            rl.days_on_market AS dom,
            rl.property_sub_type AS type
        FROM raw_listings rl
        LEFT JOIN areas a ON rl.detected_area = a.slug
        WHERE rl.{col_name} = true
          AND rl.mls_status IN ('Active', 'Active Under Contract')
          AND {area_filter()}
        ORDER BY rl.current_price DESC
    """)

    st.write(f"**{len(detail)} active listings** with {amenity_filter}")
    detail_display = currency_col(detail, ["price"])
    st.dataframe(detail_display, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Page: Subdivisions
# ---------------------------------------------------------------------------

elif page == "Subdivisions":
    st.title("Subdivision Analysis")
    st.caption("Active vs Sold/Pending split — so overpriced active listings don't skew closed numbers")

    min_listings = st.slider("Minimum listings to show", 1, 20, 2)

    # --- SOLD / PENDING stats (actual market reality) ---
    subs_sold = run_query(f"""
        SELECT
            COALESCE(rl.canonical_subdivision, rl.subdivision_name) AS subdivision,
            COALESCE(a.name, 'Unknown') AS area,
            count(*) AS sold_count,
            ROUND(AVG(rl.current_price) FILTER (WHERE rl.current_price IS NOT NULL)) AS sold_avg_price,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rl.current_price) FILTER (WHERE rl.current_price IS NOT NULL)) AS sold_median_price,
            ROUND(AVG(rl.days_on_market) FILTER (WHERE rl.days_on_market IS NOT NULL)) AS sold_avg_dom,
            ROUND(AVG(CASE WHEN rl.living_area > 0 THEN rl.current_price / rl.living_area END)) AS sold_avg_ppsf
        FROM raw_listings rl
        LEFT JOIN areas a ON rl.detected_area = a.slug
        WHERE rl.subdivision_name IS NOT NULL
          AND rl.mls_status IN ('Sold', 'Pending')
          AND {area_filter()}
        GROUP BY COALESCE(rl.canonical_subdivision, rl.subdivision_name), COALESCE(a.name, 'Unknown')
    """)

    # --- ACTIVE stats (what's listed now) ---
    subs_active = run_query(f"""
        SELECT
            COALESCE(rl.canonical_subdivision, rl.subdivision_name) AS subdivision,
            COALESCE(a.name, 'Unknown') AS area,
            count(*) AS active_count,
            ROUND(AVG(rl.current_price) FILTER (WHERE rl.current_price IS NOT NULL)) AS active_avg_price,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rl.current_price) FILTER (WHERE rl.current_price IS NOT NULL)) AS active_median_price,
            ROUND(AVG(rl.days_on_market) FILTER (WHERE rl.days_on_market IS NOT NULL)) AS active_avg_dom,
            ROUND(AVG(CASE WHEN rl.living_area > 0 THEN rl.current_price / rl.living_area END)) AS active_avg_ppsf,
            string_agg(DISTINCT rl.property_sub_type, ', ') AS types
        FROM raw_listings rl
        LEFT JOIN areas a ON rl.detected_area = a.slug
        WHERE rl.subdivision_name IS NOT NULL
          AND rl.mls_status IN ('Active', 'Active Under Contract')
          AND {area_filter()}
        GROUP BY COALESCE(rl.canonical_subdivision, rl.subdivision_name), COALESCE(a.name, 'Unknown')
    """)

    # Merge into one view
    subs = pd.merge(
        subs_active, subs_sold,
        on=["subdivision", "area"], how="outer"
    ).fillna(0)
    subs["total"] = subs["active_count"].astype(int) + subs["sold_count"].astype(int)
    subs = subs[subs["total"] >= min_listings].sort_values("total", ascending=False)

    st.write(f"**{len(subs)} subdivisions** with {min_listings}+ listings")

    # Search
    search = st.text_input("Search subdivisions", "")
    if search:
        subs = subs[subs["subdivision"].str.contains(search, case=False, na=False)]

    # --- Charts: Sold/Pending median vs Active median side by side ---
    st.subheader("Sold/Pending vs Active — Median Price")
    top20 = subs.head(20).copy()
    top20_chart = pd.DataFrame({
        "subdivision": list(top20["subdivision"]) * 2,
        "Median Price": list(top20["sold_median_price"]) + list(top20["active_median_price"]),
        "Status": ["Sold/Pending"] * len(top20) + ["Active"] * len(top20),
    })
    fig = px.bar(
        top20_chart, x="Median Price", y="subdivision",
        orientation="h", color="Status",
        barmode="group",
        color_discrete_map={"Sold/Pending": NAVY, "Active": BLUE_LIGHT},
        labels={"subdivision": ""},
    )
    fig.update_layout(height=600, yaxis=dict(autorange="reversed"), xaxis_tickformat="$,.0f")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Days on Market — Sold/Pending vs Active")
    col1, col2 = st.columns(2)
    with col1:
        top20_sold_dom = subs[subs["sold_count"] > 0].head(20).sort_values("sold_avg_dom", ascending=True)
        fig = px.bar(
            top20_sold_dom, x="sold_avg_dom", y="subdivision",
            orientation="h",
            title="Sold/Pending — Avg DOM",
            color_discrete_sequence=[NAVY],
            labels={"sold_avg_dom": "Avg DOM", "subdivision": ""},
        )
        fig.update_layout(height=500, yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        top20_active_dom = subs[subs["active_count"] > 0].head(20).sort_values("active_avg_dom", ascending=True)
        fig = px.bar(
            top20_active_dom, x="active_avg_dom", y="subdivision",
            orientation="h",
            title="Active — Avg DOM",
            color_discrete_sequence=[BLUE_LIGHT],
            labels={"active_avg_dom": "Avg DOM", "subdivision": ""},
        )
        fig.update_layout(height=500, yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)

    # --- Data table with split columns ---
    st.subheader("Full Data")
    subs_display = currency_col(subs, [
        "sold_avg_price", "sold_median_price", "sold_avg_ppsf",
        "active_avg_price", "active_median_price", "active_avg_ppsf",
    ])
    st.dataframe(
        subs_display[[
            "subdivision", "area", "total",
            "active_count", "active_median_price", "active_avg_ppsf", "active_avg_dom",
            "sold_count", "sold_median_price", "sold_avg_ppsf", "sold_avg_dom",
            "types",
        ]].rename(columns={
            "subdivision": "Subdivision", "area": "Area", "total": "Total",
            "active_count": "Active #", "active_median_price": "Active Median",
            "active_avg_ppsf": "Active $/SqFt", "active_avg_dom": "Active DOM",
            "sold_count": "Sold #", "sold_median_price": "Sold Median",
            "sold_avg_ppsf": "Sold $/SqFt", "sold_avg_dom": "Sold DOM",
            "types": "Property Types",
        }),
        use_container_width=True,
        hide_index=True,
    )

# ---------------------------------------------------------------------------
# Page: Pipeline Health
# ---------------------------------------------------------------------------

elif page == "Pipeline Health":
    st.title("Data Pipeline Health")

    # KPIs
    totals = run_query("""
        SELECT
            count(*) AS total_listings,
            count(DISTINCT import_batch_id) AS batches,
            MAX(imported_at) AS last_import
        FROM raw_listings
    """)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Listings", f"{int(totals['total_listings'].iloc[0]):,}")
    c2.metric("Import Batches", f"{int(totals['batches'].iloc[0]):,}")
    c3.metric("Last Import", str(totals["last_import"].iloc[0])[:19])

    st.divider()

    # Freshness
    st.subheader("Data Freshness by Area")
    freshness = run_query("""
        SELECT
            COALESCE(a.name, 'Unknown') AS area,
            count(rl.id) AS listings,
            MAX(ib.imported_at) AS last_import,
            EXTRACT(DAY FROM (CURRENT_TIMESTAMP - MAX(ib.imported_at)))::integer AS days_since_update,
            CASE
                WHEN MAX(ib.imported_at) >= CURRENT_TIMESTAMP - INTERVAL '1 day' THEN 'Fresh'
                WHEN MAX(ib.imported_at) >= CURRENT_TIMESTAMP - INTERVAL '3 days' THEN 'Stale'
                ELSE 'Critical'
            END AS status
        FROM raw_listings rl
        JOIN import_batches ib ON rl.import_batch_id = ib.id
        LEFT JOIN areas a ON rl.detected_area = a.slug
        WHERE ib.status = 'completed'
        GROUP BY COALESCE(a.name, 'Unknown')
        ORDER BY last_import DESC
    """)

    st.dataframe(freshness, use_container_width=True, hide_index=True)

    st.divider()

    # Batch history
    st.subheader("Import Batch History")
    batches = run_query("""
        SELECT
            imported_at,
            detected_submarket AS submarket,
            total_rows,
            rows_inserted AS inserted,
            rows_updated AS updated,
            rows_unchanged AS unchanged,
            stat
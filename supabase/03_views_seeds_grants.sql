-- ================================================================
-- PART 3: VIEWS, SEED DATA, AND GRANTS
-- Run this THIRD in Supabase SQL Editor
-- ================================================================

-- Market statistics grouped by submarket
CREATE OR REPLACE VIEW vw_market_stats_by_area AS
SELECT
    COALESCE(detected_area, 'Unknown') AS area,
    COUNT(*) AS listing_count,
    COUNT(*) FILTER (WHERE mls_status IN ('Active', 'Active Under Contract')) AS active_listings,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)
        FILTER (WHERE current_price IS NOT NULL) AS median_price,
    AVG(current_price) FILTER (WHERE current_price IS NOT NULL) AS avg_price,
    MIN(current_price) FILTER (WHERE current_price IS NOT NULL) AS min_price,
    MAX(current_price) FILTER (WHERE current_price IS NOT NULL) AS max_price,
    AVG(days_on_market) FILTER (WHERE days_on_market IS NOT NULL) AS avg_dom,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days_on_market)
        FILTER (WHERE days_on_market IS NOT NULL) AS median_dom,
    AVG(CASE
        WHEN living_area > 0 THEN current_price / living_area
        ELSE NULL
    END) AS avg_price_per_sqft,
    COUNT(*) FILTER (WHERE mls_status IN ('Active', 'Active Under Contract', 'Pending'))
        AS total_inventory,
    AVG(year_built) FILTER (WHERE year_built IS NOT NULL) AS avg_year_built
FROM raw_listings
WHERE mls_status NOT IN ('Withdrawn', 'Expired', 'Contingent', 'Pending')
GROUP BY detected_area
ORDER BY listing_count DESC;

COMMENT ON VIEW vw_market_stats_by_area IS 'Active/pending market snapshot by area';

-- Sold listings statistics (last 12 months)
CREATE OR REPLACE VIEW vw_market_stats_sold AS
SELECT
    COALESCE(detected_area, 'Unknown') AS area,
    COUNT(*) AS sold_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)
        FILTER (WHERE current_price IS NOT NULL) AS median_sold_price,
    AVG(current_price) FILTER (WHERE current_price IS NOT NULL) AS avg_sold_price,
    AVG(days_to_contract) FILTER (WHERE days_to_contract IS NOT NULL) AS avg_days_to_contract,
    AVG(close_price_by_calculated_list_price_ratio)
        FILTER (WHERE close_price_by_calculated_list_price_ratio IS NOT NULL) AS avg_close_price_ratio,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY
        CASE WHEN living_area > 0 THEN current_price / living_area ELSE NULL END
    ) AS median_price_per_sqft
FROM raw_listings
WHERE mls_status = 'Sold'
  AND close_date IS NOT NULL
  AND close_date >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY detected_area
ORDER BY sold_count DESC;

COMMENT ON VIEW vw_market_stats_sold IS 'Sold listings stats for last 12 months by area';

-- Market statistics by geospatial zone
CREATE OR REPLACE VIEW vw_market_stats_by_zone AS
SELECT
    z.zone_name,
    z.zone_type,
    COUNT(l.id) AS listing_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY l.current_price)
        FILTER (WHERE l.current_price IS NOT NULL) AS median_price,
    AVG(l.current_price) FILTER (WHERE l.current_price IS NOT NULL) AS avg_price,
    AVG(CASE
        WHEN l.living_area > 0 THEN l.current_price / l.living_area
        ELSE NULL
    END) AS avg_price_per_sqft
FROM zone_polygons z
LEFT JOIN raw_listings l ON ST_Within(l.location::geometry, z.boundary::geometry)
  AND l.mls_status NOT IN ('Withdrawn', 'Expired')
GROUP BY z.id, z.zone_name, z.zone_type
ORDER BY listing_count DESC;

COMMENT ON VIEW vw_market_stats_by_zone IS 'Market stats within geospatial zones';

-- Subdivision-level aggregations
CREATE OR REPLACE VIEW vw_subdivision_stats AS
SELECT
    COALESCE(canonical_subdivision, subdivision_name) AS canonical_subdivision,
    detected_area,
    COUNT(*) AS listing_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)
        FILTER (WHERE current_price IS NOT NULL) AS median_price,
    AVG(current_price) FILTER (WHERE current_price IS NOT NULL) AS avg_price,
    AVG(days_on_market) FILTER (WHERE days_on_market IS NOT NULL) AS avg_dom,
    string_agg(DISTINCT property_sub_type, ', ') AS property_sub_types
FROM raw_listings
WHERE mls_status NOT IN ('Withdrawn', 'Expired')
GROUP BY canonical_subdivision, subdivision_name, detected_area
ORDER BY listing_count DESC;

COMMENT ON VIEW vw_subdivision_stats IS 'Market metrics by subdivision';

-- Monthly market trends
CREATE OR REPLACE VIEW vw_market_trends_monthly AS
SELECT
    DATE_TRUNC('month', imported_at)::date AS month,
    detected_area AS area,
    COUNT(*) FILTER (WHERE imported_at >= DATE_TRUNC('month', imported_at)) AS new_listings,
    COUNT(*) FILTER (WHERE mls_status = 'Sold' AND close_date >= DATE_TRUNC('month', imported_at)) AS sold_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)
        FILTER (WHERE current_price IS NOT NULL) AS median_price,
    AVG(days_on_market) FILTER (WHERE days_on_market IS NOT NULL) AS avg_dom,
    COUNT(*) FILTER (WHERE mls_status IN ('Active', 'Active Under Contract', 'Pending')) AS inventory
FROM raw_listings
GROUP BY DATE_TRUNC('month', imported_at), detected_area
ORDER BY month DESC, area;

COMMENT ON VIEW vw_market_trends_monthly IS 'Market activity trends by month and area';

-- Data freshness monitoring
CREATE OR REPLACE VIEW vw_data_freshness_by_area AS
SELECT
    COALESCE(a.name, 'Unknown') AS area,
    MAX(ib.imported_at) AS last_import_at,
    COUNT(rl.id) AS listings_count,
    EXTRACT(DAY FROM (CURRENT_TIMESTAMP - MAX(ib.imported_at)))::integer AS days_since_update,
    CASE
        WHEN MAX(ib.imported_at) >= CURRENT_TIMESTAMP - INTERVAL '1 day' THEN 'fresh'
        WHEN MAX(ib.imported_at) >= CURRENT_TIMESTAMP - INTERVAL '3 days' THEN 'stale'
        ELSE 'critical'
    END AS freshness_status
FROM raw_listings rl
JOIN import_batches ib ON rl.import_batch_id = ib.id
LEFT JOIN areas a ON rl.detected_area = a.slug
WHERE ib.status = 'completed'
GROUP BY COALESCE(a.name, 'Unknown')
ORDER BY last_import_at DESC;

COMMENT ON VIEW vw_data_freshness_by_area IS 'Monitoring view for data staleness; alerts on 3+ day gaps';

-- Import batch dashboard
CREATE OR REPLACE VIEW vw_import_batch_summary AS
SELECT
    id AS batch_id,
    imported_at,
    detected_submarket,
    total_rows,
    rows_inserted,
    rows_updated,
    rows_unchanged,
    status,
    (rows_inserted + rows_updated + rows_unchanged)::integer AS total_processed,
    error_message,
    created_at
FROM import_batches
ORDER BY imported_at DESC;

COMMENT ON VIEW vw_import_batch_summary IS 'Admin dashboard: import batch history and stats';

-- ===== Seed Data =====
INSERT INTO areas (name, slug, zip_codes, description) VALUES
    ('Longboat Key', 'longboat-key', ARRAY['34228'], 'Barrier island luxury community, beachfront and bayside'),
    ('Downtown Sarasota', 'downtown-sarasota', ARRAY['34236'], 'Urban core, high-rise condos, vibrant cultural scene'),
    ('Lido Key', 'lido-key', ARRAY['34236'], 'Beach community with family appeal'),
    ('Siesta Key', 'siesta-key', ARRAY['34242'], 'Famous white-sand beach, mixed residential and resort'),
    ('St. Armands', 'st-armands', ARRAY['34236'], 'Upscale shopping and dining, beachfront estates'),
    ('Bird Key', 'bird-key', ARRAY['34236'], 'Exclusive gated island community with golf course')
ON CONFLICT (name) DO NOTHING;

-- ===== Grants =====
GRANT SELECT ON ALL TABLES IN SCHEMA public TO authenticated;
GRANT INSERT, UPDATE, DELETE ON import_batches, raw_listings, areas, zone_polygons,
    subdivision_aliases, unmatched_subdivisions, audit_log TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;

COMMENT ON SCHEMA public IS 'MLS Luxury Real Estate Data Warehouse for Sarasota, FL';

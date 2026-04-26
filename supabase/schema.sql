-- ================================================================
-- MLS Real Estate Data Warehouse Schema
-- Sarasota, FL Luxury Market
-- Production-ready Supabase/PostgreSQL schema
-- ================================================================

-- ================================================================
-- PART 1: EXTENSIONS
-- ================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ================================================================
-- PART 2: DROP EXISTING OBJECTS (for idempotent re-runs)
-- ================================================================

DROP VIEW IF EXISTS vw_import_batch_summary CASCADE;
DROP VIEW IF EXISTS vw_data_freshness_by_area CASCADE;
DROP VIEW IF EXISTS vw_market_trends_monthly CASCADE;
DROP VIEW IF EXISTS vw_subdivision_stats CASCADE;
DROP VIEW IF EXISTS vw_market_stats_by_zone CASCADE;
DROP VIEW IF EXISTS vw_market_stats_sold CASCADE;
DROP VIEW IF EXISTS vw_market_stats_by_area CASCADE;
DROP TRIGGER IF EXISTS trg_raw_listings_compute_enrichments ON raw_listings;
DROP FUNCTION IF EXISTS fn_compute_enrichments();
DROP TABLE IF EXISTS unmatched_subdivisions CASCADE;
DROP TABLE IF EXISTS subdivision_aliases CASCADE;
DROP TABLE IF EXISTS zone_polygons CASCADE;
DROP TABLE IF EXISTS areas CASCADE;
DROP TABLE IF EXISTS raw_listings CASCADE;
DROP TABLE IF EXISTS import_batches CASCADE;
DROP TABLE IF EXISTS audit_log CASCADE;

-- ================================================================
-- PART 3: CORE TABLES
-- ================================================================

-- Track every CSV import batch
CREATE TABLE import_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    imported_at timestamptz DEFAULT now() NOT NULL,
    source_file_hash text NOT NULL,
    detected_submarket text,
    area_breakdown jsonb,
    total_rows integer NOT NULL,
    rows_inserted integer DEFAULT 0,
    rows_updated integer DEFAULT 0,
    rows_unchanged integer DEFAULT 0,
    status text DEFAULT 'processing' NOT NULL,
    error_message text,
    created_at timestamptz DEFAULT now() NOT NULL
);

COMMENT ON TABLE import_batches IS 'Audit trail for all CSV imports; enables idempotent replay and freshness monitoring';
COMMENT ON COLUMN import_batches.source_file_hash IS 'SHA-256 of CSV for duplicate detection';
COMMENT ON COLUMN import_batches.detected_submarket IS 'Auto-detected: Longboat Key, Downtown Sarasota, Siesta Key, Mixed';
COMMENT ON COLUMN import_batches.area_breakdown IS 'e.g. {"34228": {"area": "Longboat Key", "count": 203}}';
COMMENT ON COLUMN import_batches.status IS 'processing, completed, failed, skipped_duplicate';
CREATE INDEX idx_import_batches_hash ON import_batches(source_file_hash);
CREATE INDEX idx_import_batches_status ON import_batches(status);
CREATE INDEX idx_import_batches_created_at ON import_batches(created_at DESC);

-- Main listings table with all MLS columns and enrichments
CREATE TABLE raw_listings (
    -- Primary key & metadata
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    import_batch_id uuid NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,

    -- ===== MLS CSV Columns (snake_case) =====
    listing_key_numeric bigint,
    property_type text,
    state_or_province text,
    listing_id text UNIQUE NOT NULL,
    county_or_parish text,
    city text,
    mls_area_major text,
    postal_code text,
    subdivision_name text,
    property_sub_type text,
    unparsed_address text,
    mls_status text,
    standard_status text,
    special_listing_conditions text,
    current_price numeric,
    lot_size_square_feet numeric,
    lot_size_acres numeric,
    flood_zone_code text,
    builder_name text,
    year_built integer,
    projected_completion_date timestamptz,
    monthly_condo_fee_amount numeric,
    construction_materials text,
    property_condition text,
    furnished text,
    association_fee_frequency text,
    association_fee_requirement text,
    calculated_list_price_by_calculated_sqft numeric,
    close_price_by_calculated_sqft numeric,
    close_price_by_calculated_list_price_ratio numeric,
    buyer_financing text,
    days_to_contract integer,
    days_on_market integer,
    cumulative_days_on_market integer,
    pool_private_yn boolean,
    bedrooms_total integer,
    bathrooms_full integer,
    bathrooms_half integer,
    pool text,
    living_area numeric,
    roof text,
    floor_number text,
    lease_restrictions_yn boolean,
    num_of_own_years_prior_to_lse integer,
    minimum_lease text,
    lease_term text,
    monthly_hoa_amount numeric,
    total_annual_fees numeric,
    association_fee numeric,
    close_date date,
    pet_restrictions text,
    pets_allowed text,
    number_of_pets text,
    max_pet_weight numeric,
    street_name text,
    expected_closing_date timestamptz,
    garage_spaces numeric,
    utilities text,
    community_features text,
    elementary_school text,
    middle_or_junior_school text,
    high_school text,
    lot_features text,
    stories_total integer,
    building_elevator_yn boolean,
    water_view text,
    water_view_yn boolean,
    waterfront_yn boolean,
    water_access_yn boolean,
    water_source text,
    water_access text,
    water_extras text,
    water_extras_yn boolean,
    waterfront_features text,
    waterfront_feet_total numeric,
    tax_annual_amount numeric,
    dock_descrip text,
    dock_dimensions text,
    dock_lift_cap numeric,
    dock_yn boolean,
    tax_year integer,
    cdd_yn boolean,
    tax_other_annual_assessment_amount numeric,
    list_agent_full_name text,
    list_office_name text,
    list_agent_mls_id text,
    list_office_mls_id text,
    buyer_agent_full_name text,
    buyer_agent_mls_id text,
    buyer_office_name text,
    buyer_office_mls_id text,
    status_change_timestamp timestamptz,
    price_change_timestamp timestamptz,
    original_list_price numeric,
    purchase_contract_date date,
    listing_contract_date date,
    latitude numeric,
    longitude numeric,
    "view" text,
    parcel_number text,

    -- ===== Geospatial & Raw Data =====
    location geography(Point, 4326),
    raw_mls_data jsonb,

    -- ===== Pipeline Tracking =====
    imported_at timestamptz DEFAULT now() NOT NULL,
    first_seen_at timestamptz DEFAULT now() NOT NULL,
    data_hash text,
    change_count integer DEFAULT 0,
    detected_area text,

    -- ===== Computed/Enriched Columns =====
    canonical_subdivision text,
    monthly_association_cost numeric,
    has_natural_gas boolean,
    has_elevator boolean,
    is_gated boolean,
    gate_type text,
    has_dog_park boolean,
    has_golf boolean,
    has_fitness_center boolean,
    has_tennis boolean,
    has_pickleball boolean,
    has_pool_community boolean,
    has_restaurant boolean,
    has_dock boolean,
    is_waterfront boolean,
    is_turnkey boolean,
    big_dog_friendly boolean,
    building_class text,

    -- ===== Parsed Arrays from Comma-Separated Fields =====
    community_features_array text[],
    water_extras_array text[],
    water_view_array text[],
    waterfront_features_array text[],
    lot_features_array text[],
    utilities_array text[],
    construction_materials_array text[],
    pets_allowed_array text[]
);

COMMENT ON COLUMN raw_listings.listing_id IS 'Dedup key from MLS';
COMMENT ON COLUMN raw_listings.floor_number IS 'Can be "15+" for 15 or more';
COMMENT ON COLUMN raw_listings.number_of_pets IS 'Can be "10+" for 10 or more';
COMMENT ON COLUMN raw_listings.location IS 'Computed from latitude/longitude';
COMMENT ON COLUMN raw_listings.raw_mls_data IS 'All 100 original CSV fields for future-proofing';
COMMENT ON COLUMN raw_listings.data_hash IS 'Hash of all MLS fields to detect changes';
COMMENT ON COLUMN raw_listings.detected_area IS 'Assigned from PostGIS or zip code rules';
COMMENT ON COLUMN raw_listings.canonical_subdivision IS 'Normalized subdivision from subdivision_aliases';
COMMENT ON COLUMN raw_listings.monthly_association_cost IS 'TotalAnnualFees / 12';
COMMENT ON COLUMN raw_listings.has_natural_gas IS 'Parsed from Utilities field';
COMMENT ON COLUMN raw_listings.has_elevator IS 'From BuildingElevatorYN';
COMMENT ON COLUMN raw_listings.is_gated IS 'Parsed from CommunityFeatures';
COMMENT ON COLUMN raw_listings.gate_type IS 'guarded, unguarded, or null';
COMMENT ON COLUMN raw_listings.has_dock IS 'From DockYN';
COMMENT ON COLUMN raw_listings.is_waterfront IS 'From WaterfrontYN';
COMMENT ON COLUMN raw_listings.is_turnkey IS 'Furnished IN (Furnished, Turnkey)';
COMMENT ON COLUMN raw_listings.big_dog_friendly IS 'MaxPetWeight >= 50 OR 999';
COMMENT ON COLUMN raw_listings.building_class IS 'low-rise (1-4), mid-rise (5-9), high-rise (10+)';

COMMENT ON TABLE raw_listings IS 'Master listings table: all MLS data + enrichments + geospatial. Updated via import batches.';

-- Create indexes for query performance
CREATE UNIQUE INDEX idx_raw_listings_listing_id ON raw_listings(listing_id);
CREATE INDEX idx_raw_listings_mls_status ON raw_listings(mls_status);
CREATE INDEX idx_raw_listings_mls_area_major ON raw_listings(mls_area_major);
CREATE INDEX idx_raw_listings_postal_code ON raw_listings(postal_code);
CREATE INDEX idx_raw_listings_current_price ON raw_listings(current_price DESC);
CREATE INDEX idx_raw_listings_subdivision_name ON raw_listings(subdivision_name);
CREATE INDEX idx_raw_listings_canonical_subdivision ON raw_listings(canonical_subdivision);
CREATE INDEX idx_raw_listings_detected_area ON raw_listings(detected_area);
CREATE INDEX idx_raw_listings_location ON raw_listings USING GIST(location);
CREATE INDEX idx_raw_listings_waterfront ON raw_listings(waterfront_yn);
CREATE INDEX idx_raw_listings_furnished ON raw_listings(furnished);
CREATE INDEX idx_raw_listings_flood_zone ON raw_listings(flood_zone_code);
CREATE INDEX idx_raw_listings_building_class ON raw_listings(building_class);
CREATE INDEX idx_raw_listings_has_natural_gas ON raw_listings(has_natural_gas);
CREATE INDEX idx_raw_listings_is_gated ON raw_listings(is_gated);
CREATE INDEX idx_raw_listings_has_dock ON raw_listings(has_dock);
CREATE INDEX idx_raw_listings_is_turnkey ON raw_listings(is_turnkey);
CREATE INDEX idx_raw_listings_big_dog_friendly ON raw_listings(big_dog_friendly);
CREATE INDEX idx_raw_listings_import_batch_id ON raw_listings(import_batch_id);
CREATE INDEX idx_raw_listings_imported_at ON raw_listings(imported_at DESC);

-- GIN indexes for array/jsonb searches
CREATE INDEX idx_raw_listings_community_features_array ON raw_listings USING GIN(community_features_array);
CREATE INDEX idx_raw_listings_water_extras_array ON raw_listings USING GIN(water_extras_array);
CREATE INDEX idx_raw_listings_water_view_array ON raw_listings USING GIN(water_view_array);
CREATE INDEX idx_raw_listings_utilities_array ON raw_listings USING GIN(utilities_array);
CREATE INDEX idx_raw_listings_raw_mls_data ON raw_listings USING GIN(raw_mls_data);

-- Geospatial areas (Sarasota submarkets)
CREATE TABLE areas (
    id serial PRIMARY KEY,
    name text NOT NULL UNIQUE,
    slug text NOT NULL UNIQUE,
    zip_codes text[] NOT NULL,
    description text,
    created_at timestamptz DEFAULT now() NOT NULL
);

COMMENT ON TABLE areas IS 'Sarasota submarkets: Longboat Key, Downtown, Siesta Key, etc.';

-- Geospatial zone boundaries (beachfront, bayside, golf, downtown)
CREATE TABLE zone_polygons (
    id serial PRIMARY KEY,
    area_slug text NOT NULL REFERENCES areas(slug) ON DELETE RESTRICT,
    zone_name text NOT NULL,
    zone_type text,
    boundary geography(Polygon, 4326) NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL
);

COMMENT ON TABLE zone_polygons IS 'Geographic boundaries within areas for spatial queries';
COMMENT ON COLUMN zone_polygons.zone_type IS 'beachfront, bayside, golf_course, downtown, etc.';
CREATE INDEX idx_zone_polygons_boundary ON zone_polygons USING GIST(boundary);
CREATE INDEX idx_zone_polygons_area_slug ON zone_polygons(area_slug);

-- Subdivision name normalization (MLS name → canonical name)
CREATE TABLE subdivision_aliases (
    id serial PRIMARY KEY,
    mls_name text NOT NULL UNIQUE,
    canonical_name text NOT NULL,
    confidence numeric DEFAULT 1.0,
    matched_by text,
    created_at timestamptz DEFAULT now() NOT NULL
);

COMMENT ON TABLE subdivision_aliases IS 'Normalize messy MLS subdivision names to canonical form';
COMMENT ON COLUMN subdivision_aliases.confidence IS '1.0 = manual/exact, <1.0 = fuzzy';
COMMENT ON COLUMN subdivision_aliases.matched_by IS 'manual, exact, trigram, claude';
CREATE INDEX idx_subdivision_aliases_canonical_name ON subdivision_aliases(canonical_name);
CREATE INDEX idx_subdivision_aliases_mls_name_trgm ON subdivision_aliases USING GIN(mls_name gin_trgm_ops);

-- Track unmatched subdivisions for manual resolution
CREATE TABLE unmatched_subdivisions (
    id serial PRIMARY KEY,
    mls_name text NOT NULL,
    best_candidate text,
    similarity_score numeric,
    status text DEFAULT 'pending',
    resolved_to text,
    created_at timestamptz DEFAULT now() NOT NULL
);

COMMENT ON TABLE unmatched_subdivisions IS 'Subdivisions not yet matched to canonical names; target for manual review';
COMMENT ON COLUMN unmatched_subdivisions.status IS 'pending, resolved, ignored';
CREATE INDEX idx_unmatched_subdivisions_status ON unmatched_subdivisions(status);

-- Audit log for all operations
CREATE TABLE audit_log (
    id serial PRIMARY KEY,
    event_type text NOT NULL,
    event_detail jsonb,
    created_at timestamptz DEFAULT now() NOT NULL
);

COMMENT ON TABLE audit_log IS 'System audit trail for data operations';
COMMENT ON COLUMN audit_log.event_type IS 'import, sync, rebuild, error';
CREATE INDEX idx_audit_log_event_type ON audit_log(event_type);
CREATE INDEX idx_audit_log_created_at ON audit_log(created_at DESC);

-- ================================================================
-- PART 4: TRIGGER FUNCTION FOR ENRICHMENTS
-- ================================================================

CREATE OR REPLACE FUNCTION fn_compute_enrichments()
RETURNS TRIGGER AS $$
BEGIN
    -- ===== Geospatial =====
    IF NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
        NEW.location := ST_GeogFromText(
            'SRID=4326;POINT(' || NEW.longitude || ' ' || NEW.latitude || ')'
        );
    END IF;

    -- ===== Association costs =====
    IF NEW.total_annual_fees IS NOT NULL THEN
        NEW.monthly_association_cost := NEW.total_annual_fees / 12;
    END IF;

    -- ===== Utilities parsing =====
    NEW.has_natural_gas := CASE
        WHEN NEW.utilities ILIKE '%Natural Gas%' THEN true
        ELSE false
    END;
    NEW.utilities_array := CASE
        WHEN NEW.utilities IS NOT NULL
        THEN string_to_array(trim(NEW.utilities), ',')::text[]
        ELSE ARRAY[]::text[]
    END;

    -- ===== Community features parsing =====
    NEW.community_features_array := CASE
        WHEN NEW.community_features IS NOT NULL
        THEN string_to_array(trim(NEW.community_features), ',')::text[]
        ELSE ARRAY[]::text[]
    END;

    NEW.is_gated := CASE
        WHEN NEW.community_features ILIKE '%Gated Community%' THEN true
        ELSE false
    END;

    NEW.gate_type := CASE
        WHEN NEW.community_features ILIKE '%Gated Community - Guard%' AND NEW.community_features NOT ILIKE '%Gated Community - No Guard%' THEN 'guarded'
        WHEN NEW.community_features ILIKE '%Gated Community - No Guard%' THEN 'unguarded'
        WHEN NEW.community_features ILIKE '%Gated Community%' THEN 'guarded'
        ELSE NULL
    END;

    NEW.has_dog_park := CASE
        WHEN NEW.community_features ILIKE '%Dog Park%' THEN true
        ELSE false
    END;

    NEW.has_golf := CASE
        WHEN NEW.community_features ILIKE '%Golf%' THEN true
        ELSE false
    END;

    NEW.has_fitness_center := CASE
        WHEN NEW.community_features ILIKE '%Fitness%' OR NEW.community_features ILIKE '%Gym%' THEN true
        ELSE false
    END;

    NEW.has_tennis := CASE
        WHEN NEW.community_features ILIKE '%Tennis%' THEN true
        ELSE false
    END;

    NEW.has_pickleball := CASE
        WHEN NEW.community_features ILIKE '%Pickleball%' THEN true
        ELSE false
    END;

    NEW.has_pool_community := CASE
        WHEN NEW.community_features ILIKE '%Pool%' THEN true
        ELSE false
    END;

    NEW.has_restaurant := CASE
        WHEN NEW.community_features ILIKE '%Restaurant%' THEN true
        ELSE false
    END;

    -- ===== Building and structure =====
    NEW.has_elevator := COALESCE(NEW.building_elevator_yn, false);

    NEW.building_class := CASE
        WHEN NEW.stories_total IS NULL THEN NULL
        WHEN NEW.stories_total <= 4 THEN 'low-rise'
        WHEN NEW.stories_total <= 9 THEN 'mid-rise'
        ELSE 'high-rise'
    END;

    -- ===== Dock and waterfront =====
    NEW.has_dock := COALESCE(NEW.dock_yn, false);
    NEW.is_waterfront := COALESCE(NEW.waterfront_yn, false);

    -- ===== Water features arrays =====
    NEW.water_extras_array := CASE
        WHEN NEW.water_extras IS NOT NULL
        THEN string_to_array(trim(NEW.water_extras), ',')::text[]
        ELSE ARRAY[]::text[]
    END;

    NEW.water_view_array := CASE
        WHEN NEW.water_view IS NOT NULL
        THEN string_to_array(trim(NEW.water_view), ',')::text[]
        ELSE ARRAY[]::text[]
    END;

    NEW.waterfront_features_array := CASE
        WHEN NEW.waterfront_features IS NOT NULL
        THEN string_to_array(trim(NEW.waterfront_features), ',')::text[]
        ELSE ARRAY[]::text[]
    END;

    -- ===== Pets =====
    NEW.pets_allowed_array := CASE
        WHEN NEW.pets_allowed IS NOT NULL
        THEN string_to_array(trim(NEW.pets_allowed), ',')::text[]
        ELSE ARRAY[]::text[]
    END;

    NEW.big_dog_friendly := CASE
        WHEN NEW.max_pet_weight IS NULL THEN false
        WHEN NEW.max_pet_weight >= 50 THEN true
        WHEN NEW.max_pet_weight = 999 THEN true
        ELSE false
    END;

    -- ===== Furnished / turnkey =====
    NEW.is_turnkey := CASE
        WHEN NEW.furnished IN ('Furnished', 'Turnkey') THEN true
        ELSE false
    END;

    -- ===== Construction materials =====
    NEW.construction_materials_array := CASE
        WHEN NEW.construction_materials IS NOT NULL
        THEN string_to_array(trim(NEW.construction_materials), ',')::text[]
        ELSE ARRAY[]::text[]
    END;

    -- ===== Lot features =====
    NEW.lot_features_array := CASE
        WHEN NEW.lot_features IS NOT NULL
        THEN string_to_array(trim(NEW.lot_features), ',')::text[]
        ELSE ARRAY[]::text[]
    END;

    -- ===== Subdivision normalization (lookup canonical name) =====
    IF NEW.subdivision_name IS NOT NULL THEN
        SELECT canonical_name INTO NEW.canonical_subdivision
        FROM subdivision_aliases
        WHERE mls_name = NEW.subdivision_name
        LIMIT 1;
    END IF;

    -- ===== Area detection from postal code =====
    IF NEW.postal_code IS NOT NULL AND NEW.detected_area IS NULL THEN
        SELECT slug INTO NEW.detected_area
        FROM areas
        WHERE postal_code = ANY(zip_codes)
        LIMIT 1;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_compute_enrichments() IS 'Auto-populate enriched/derived columns before insert or update';

CREATE TRIGGER trg_raw_listings_compute_enrichments
BEFORE INSERT OR UPDATE ON raw_listings
FOR EACH ROW
EXECUTE FUNCTION fn_compute_enrichments();

-- ================================================================
-- PART 5: VIEWS FOR REPORTING & ANALYTICS
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

-- ================================================================
-- PART 6: SEED DATA
-- ================================================================

INSERT INTO areas (name, slug, zip_codes, description) VALUES
    ('Longboat Key', 'longboat-key', ARRAY['34228'], 'Barrier island luxury community, beachfront and bayside'),
    ('Downtown Sarasota', 'downtown-sarasota', ARRAY['34236'], 'Urban core, high-rise condos, vibrant cultural scene'),
    ('Lido Key', 'lido-key', ARRAY['34236'], 'Beach community with family appeal'),
    ('Siesta Key', 'siesta-key', ARRAY['34242'], 'Famous white-sand beach, mixed residential and resort'),
    ('St. Armands', 'st-armands', ARRAY['34236'], 'Upscale shopping and dining, beachfront estates'),
    ('Bird Key', 'bird-key', ARRAY['34236'], 'Exclusive gated island community with golf course')
ON CONFLICT (name) DO NOTHING;

-- ================================================================
-- PART 7: GRANTS (adjust role names to your Supabase setup)
-- ================================================================

-- Grant appropriate permissions to authenticated users
GRANT SELECT ON ALL TABLES IN SCHEMA public TO authenticated;

-- Grant insert/update/delete to service role (backend processes)
GRANT INSERT, UPDATE, DELETE ON import_batches, raw_listings, areas, zone_polygons,
    subdivision_aliases, unmatched_subdivisions, audit_log TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;

-- ================================================================
-- PART 8: FINAL VALIDATION COMMENTS
-- ================================================================

COMMENT ON SCHEMA public IS 'MLS Luxury Real Estate Data Warehouse for Sarasota, FL';

-- End of schema file

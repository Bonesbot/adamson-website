-- ================================================================
-- PART 1: EXTENSIONS, CLEANUP, AND TABLES
-- Run this FIRST in Supabase SQL Editor
-- ================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Drop everything for clean slate
DROP VIEW IF EXISTS vw_import_batch_summary CASCADE;
DROP VIEW IF EXISTS vw_data_freshness_by_area CASCADE;
DROP VIEW IF EXISTS vw_market_trends_monthly CASCADE;
DROP VIEW IF EXISTS vw_subdivision_stats CASCADE;
DROP VIEW IF EXISTS vw_market_stats_by_zone CASCADE;
DROP VIEW IF EXISTS vw_market_stats_sold CASCADE;
DROP VIEW IF EXISTS vw_market_stats_by_area CASCADE;
DROP FUNCTION IF EXISTS fn_compute_enrichments() CASCADE;
DROP TABLE IF EXISTS unmatched_subdivisions CASCADE;
DROP TABLE IF EXISTS subdivision_aliases CASCADE;
DROP TABLE IF EXISTS zone_polygons CASCADE;
DROP TABLE IF EXISTS areas CASCADE;
DROP TABLE IF EXISTS raw_listings CASCADE;
DROP TABLE IF EXISTS import_batches CASCADE;
DROP TABLE IF EXISTS audit_log CASCADE;

-- ===== Table: import_batches =====
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

COMMENT ON TABLE import_batches IS 'Audit trail for all CSV imports';
COMMENT ON COLUMN import_batches.source_file_hash IS 'SHA-256 of CSV for duplicate detection';
COMMENT ON COLUMN import_batches.detected_submarket IS 'Auto-detected: Longboat Key, Downtown Sarasota, Siesta Key, Mixed';
COMMENT ON COLUMN import_batches.area_breakdown IS 'e.g. {"34228": {"area": "Longboat Key", "count": 203}}';
COMMENT ON COLUMN import_batches.status IS 'processing, completed, failed, skipped_duplicate';
CREATE INDEX idx_import_batches_hash ON import_batches(source_file_hash);
CREATE INDEX idx_import_batches_status ON import_batches(status);
CREATE INDEX idx_import_batches_created_at ON import_batches(created_at DESC);

-- ===== Table: raw_listings =====
CREATE TABLE raw_listings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    import_batch_id uuid NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
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
    listing_view text,
    parcel_number text,
    location geography(Point, 4326),
    raw_mls_data jsonb,
    imported_at timestamptz DEFAULT now() NOT NULL,
    first_seen_at timestamptz DEFAULT now() NOT NULL,
    data_hash text,
    change_count integer DEFAULT 0,
    detected_area text,
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
    community_features_array text[],
    water_extras_array text[],
    water_view_array text[],
    waterfront_features_array text[],
    lot_features_array text[],
    utilities_array text[],
    construction_materials_array text[],
    pets_allowed_array text[]
);

COMMENT ON TABLE raw_listings IS 'Master listings table: all MLS data plus enrichments plus geospatial';
COMMENT ON COLUMN raw_listings.listing_id IS 'Dedup key from MLS';
COMMENT ON COLUMN raw_listings.floor_number IS 'Can be 15+ for 15 or more';
COMMENT ON COLUMN raw_listings.number_of_pets IS 'Can be 10+ for 10 or more';
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
CREATE INDEX idx_raw_listings_community_features_array ON raw_listings USING GIN(community_features_array);
CREATE INDEX idx_raw_listings_water_extras_array ON raw_listings USING GIN(water_extras_array);
CREATE INDEX idx_raw_listings_water_view_array ON raw_listings USING GIN(water_view_array);
CREATE INDEX idx_raw_listings_utilities_array ON raw_listings USING GIN(utilities_array);
CREATE INDEX idx_raw_listings_raw_mls_data ON raw_listings USING GIN(raw_mls_data);

-- ===== Table: areas =====
CREATE TABLE areas (
    id serial PRIMARY KEY,
    name text NOT NULL UNIQUE,
    slug text NOT NULL UNIQUE,
    zip_codes text[] NOT NULL,
    description text,
    created_at timestamptz DEFAULT now() NOT NULL
);

COMMENT ON TABLE areas IS 'Sarasota submarkets: Longboat Key, Downtown, Siesta Key, etc.';

-- ===== Table: zone_polygons =====
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

-- ===== Table: subdivision_aliases =====
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

-- ===== Table: unmatched_subdivisions =====
CREATE TABLE unmatched_subdivisions (
    id serial PRIMARY KEY,
    mls_name text NOT NULL,
    best_candidate text,
    similarity_score numeric,
    status text DEFAULT 'pending',
    resolved_to text,
    created_at timestamptz DEFAULT now() NOT NULL
);

COMMENT ON TABLE unmatched_subdivisions IS 'Subdivisions not yet matched to canonical names';
COMMENT ON COLUMN unmatched_subdivisions.status IS 'pending, resolved, ignored';
CREATE INDEX idx_unmatched_subdivisions_status ON unmatched_subdivisions(status);

-- ===== Table: audit_log =====
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

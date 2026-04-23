-- ================================================================
-- PART 4: POLYGON-FIRST AREA DETECTION
-- Run this AFTER 01, 02, 03 are deployed.
--
-- Changes:
--   1. Rewrites fn_compute_enrichments() so detected_area is set via
--      ST_Within() against zone_polygons FIRST, then falls back to
--      zip code lookup if no polygon match.
--   2. Removes the `detected_area IS NULL` short-circuit so re-running
--      the trigger on existing rows (e.g. via UPDATE ... SET id=id)
--      actually reassigns detected_area based on current polygons.
--   3. If multiple polygons contain the point (overlapping zones),
--      picks the SMALLEST polygon (most specific / finest-grained zone).
--
-- Safe to re-run. Replaces the function in place.
-- ================================================================

CREATE OR REPLACE FUNCTION fn_compute_enrichments()
RETURNS TRIGGER AS $$
DECLARE
    polygon_area_slug text;
BEGIN
    -- Geospatial: build PostGIS point from lat/long
    IF NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
        NEW.location := ST_GeogFromText(
            'SRID=4326;POINT(' || NEW.longitude || ' ' || NEW.latitude || ')'
        );
    END IF;

    -- Association costs: annual / 12
    IF NEW.total_annual_fees IS NOT NULL THEN
        NEW.monthly_association_cost := NEW.total_annual_fees / 12;
    END IF;

    -- Natural gas detection
    NEW.has_natural_gas := CASE
        WHEN NEW.utilities ILIKE '%Natural Gas%' THEN true
        ELSE false
    END;
    NEW.utilities_array := CASE
        WHEN NEW.utilities IS NOT NULL
        THEN string_to_array(trim(NEW.utilities), ',')::text[]
        ELSE ARRAY[]::text[]
    END;

    -- Community features parsing
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
        WHEN NEW.community_features ILIKE '%Gated Community - Guard%'
             AND NEW.community_features NOT ILIKE '%Gated Community - No Guard%'
            THEN 'guarded'
        WHEN NEW.community_features ILIKE '%Gated Community - No Guard%'
            THEN 'unguarded'
        WHEN NEW.community_features ILIKE '%Gated Community%'
            THEN 'guarded'
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
        WHEN NEW.community_features ILIKE '%Fitness%'
          OR NEW.community_features ILIKE '%Gym%' THEN true
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

    -- Building and structure
    NEW.has_elevator := COALESCE(NEW.building_elevator_yn, false);

    NEW.building_class := CASE
        WHEN NEW.stories_total IS NULL THEN NULL
        WHEN NEW.stories_total <= 4 THEN 'low-rise'
        WHEN NEW.stories_total <= 9 THEN 'mid-rise'
        ELSE 'high-rise'
    END;

    -- Dock and waterfront
    NEW.has_dock := COALESCE(NEW.dock_yn, false);
    NEW.is_waterfront := COALESCE(NEW.waterfront_yn, false);

    -- Water features arrays
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

    -- Pets
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

    -- Furnished / turnkey
    NEW.is_turnkey := CASE
        WHEN NEW.furnished IN ('Furnished', 'Turnkey') THEN true
        ELSE false
    END;

    -- Construction materials
    NEW.construction_materials_array := CASE
        WHEN NEW.construction_materials IS NOT NULL
        THEN string_to_array(trim(NEW.construction_materials), ',')::text[]
        ELSE ARRAY[]::text[]
    END;

    -- Lot features
    NEW.lot_features_array := CASE
        WHEN NEW.lot_features IS NOT NULL
        THEN string_to_array(trim(NEW.lot_features), ',')::text[]
        ELSE ARRAY[]::text[]
    END;

    -- Subdivision normalization lookup
    IF NEW.subdivision_name IS NOT NULL THEN
        SELECT canonical_name INTO NEW.canonical_subdivision
        FROM subdivision_aliases
        WHERE mls_name = NEW.subdivision_name
        LIMIT 1;
    END IF;

    -- =============================================================
    -- AREA DETECTION (polygon-first, zip fallback)
    -- =============================================================
    -- Step 1: If we have a location, try PostGIS containment.
    --         If multiple polygons contain the point, pick the
    --         smallest (most specific / finest-grained zone).
    polygon_area_slug := NULL;

    IF NEW.location IS NOT NULL THEN
        SELECT area_slug INTO polygon_area_slug
        FROM zone_polygons
        WHERE ST_Within(NEW.location::geometry, boundary::geometry)
        ORDER BY ST_Area(boundary::geometry) ASC
        LIMIT 1;
    END IF;

    -- Step 2: If polygon match found, use it. Otherwise fall back to zip.
    IF polygon_area_slug IS NOT NULL THEN
        NEW.detected_area := polygon_area_slug;
    ELSIF NEW.postal_code IS NOT NULL THEN
        SELECT slug INTO NEW.detected_area
        FROM areas
        WHERE NEW.postal_code = ANY(zip_codes)
        LIMIT 1;
    ELSE
        NEW.detected_area := NULL;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_compute_enrichments() IS
    'Auto-populate enriched/derived columns before insert or update. '
    'detected_area uses polygon containment first (smallest polygon wins '
    'for overlaps), then falls back to zip code lookup.';

-- =================================================================
-- RE-ENRICHMENT HELPER
-- =================================================================
-- Call this after loading/updating polygons to re-run the trigger
-- across all existing listings and recompute detected_area.
--
-- Usage:  SELECT fn_reenrich_all_listings();
--
-- Returns the number of rows updated.
-- =================================================================
CREATE OR REPLACE FUNCTION fn_reenrich_all_listings()
RETURNS integer AS $$
DECLARE
    row_count integer;
BEGIN
    -- Touching listing_id triggers fn_compute_enrichments on each row.
    -- listing_id is UNIQUE NOT NULL so assigning to itself is a no-op
    -- at the data level but fires the BEFORE UPDATE trigger.
    UPDATE raw_listings SET listing_id = listing_id;
    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_reenrich_all_listings() IS
    'Re-run enrichment trigger on all raw_listings rows. '
    'Call after loading new polygons so detected_area is refreshed.';

-- =================================================================
-- CONVENIENCE VIEW: area counts before/after
-- =================================================================
CREATE OR REPLACE VIEW vw_area_listing_counts AS
SELECT
    COALESCE(detected_area, '(unassigned)') AS area_slug,
    COUNT(*) AS listing_count,
    COUNT(*) FILTER (WHERE mls_status IN ('Active', 'Active Under Contract')) AS active_count,
    COUNT(*) FILTER (WHERE mls_status = 'Sold') AS sold_count
FROM raw_listings
GROUP BY detected_area
ORDER BY listing_count DESC;

COMMENT ON VIEW vw_area_listing_counts IS
    'Quick visibility into how listings are bucketed by detected_area. '
    'Useful for verifying polygon loads.';

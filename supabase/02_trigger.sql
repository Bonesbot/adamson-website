-- ================================================================
-- PART 2: TRIGGER FUNCTION FOR ENRICHMENTS
-- Run this SECOND in Supabase SQL Editor
-- ================================================================

CREATE OR REPLACE FUNCTION fn_compute_enrichments()
RETURNS TRIGGER AS $$
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

    -- Area detection from postal code
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

-- AG Buildings: internal condo field guide (/mkt/buildings/). Applied 2026-10-08 via the
-- Supabase MCP (migrations condo_buildings_field_tool, condo_buildings_view_fix_modes,
-- condo_buildings_view_token_features). Kept here for repo completeness; re-runnable.
--
-- One row per street address. condo_building_key() strips the unit from unparsed_address so
-- every spelling of a building collapses to one key. v_condo_buildings rolls raw_listings up
-- per key (closed-24-month stats, HOA, pets, lease, parking, amenities) and joins the team
-- override row and note count. The Netlify function netlify/functions/buildings.js is the
-- only reader (service role); the page never touches Supabase directly.

create or replace function public.condo_building_key(addr text) returns text
language sql immutable as $$
  select nullif(trim(regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(
      regexp_replace(upper(coalesce(addr,'')), '\s*(#|\sUNIT\s|\sAPT\.?\s|\sSTE\.?\s|\sSUITE\s|\sPH\s*[0-9]).*$', ''),
      '\s+', ' ', 'g'),
      '\mDRIVE\M', 'DR', 'g'),
      '\mBOULEVARD\M', 'BLVD', 'g'),
      '\mAVENUE\M', 'AVE', 'g'),
      '\mSTREET\M', 'ST', 'g'),
      '\mBENJAMIN FRANKLIN\M', 'BEN FRANKLIN', 'g')), '')
$$;

create or replace function public.condo_building_slug(k text) returns text
language sql immutable as $$
  select trim(both '-' from regexp_replace(lower(coalesce(k,'')), '[^a-z0-9]+', '-', 'g'))
$$;

create table if not exists public.condo_buildings (
  building_key text primary key,
  display_name text,
  photo_url text,
  pets_override text,
  rental_override text,
  parking_override text,
  amenities_override text,
  hidden boolean not null default false,
  updated_by text,
  updated_at timestamptz not null default now()
);

create table if not exists public.condo_building_notes (
  id bigserial primary key,
  building_key text not null,
  note text not null,
  author text,
  created_at timestamptz not null default now()
);
create index if not exists condo_building_notes_key_idx on public.condo_building_notes(building_key);

alter table public.condo_buildings enable row level security;
alter table public.condo_building_notes enable row level security;

create or replace view public.v_condo_buildings as
with base as (
  select r.*,
         public.condo_building_key(r.unparsed_address) as bkey,
         coalesce(r.monthly_association_cost, r.monthly_condo_fee_amount, r.monthly_hoa_amount,
                  case when r.association_fee_frequency ilike 'month%' then r.association_fee
                       when r.association_fee_frequency ilike 'quarter%' then r.association_fee/3
                       when r.association_fee_frequency ilike 'annual%' then r.association_fee/12 end,
                  case when r.total_annual_fees > 0 then r.total_annual_fees/12 end) as fee_mo,
         case when r.standard_status='Closed' and r.close_date >= (current_date - interval '24 months') then true else false end as closed24
  from public.raw_listings r
  where r.property_sub_type ilike '%condo%'
    and r.unparsed_address is not null
    and r.latitude is not null and r.longitude is not null
),
feat as (
  select bkey, string_agg(distinct tok, ', ') as community_features_raw
  from base, unnest(string_to_array(community_features, ',')) t(tok0), lateral (select trim(tok0) as tok) x
  where bkey is not null and trim(tok0) <> ''
  group by bkey
),
ext as (
  select bkey, string_agg(distinct tok, ', ') as exterior_features_raw
  from base, unnest(string_to_array(exterior_features, ',')) t(tok0), lateral (select trim(tok0) as tok) x
  where bkey is not null and trim(tok0) <> ''
  group by bkey
),
agg as (
  select bkey,
    public.condo_building_slug(bkey) as slug,
    max(postal_code) as postal_code,
    max(city) as city,
    mode() within group (order by coalesce(canonical_subdivision, subdivision_name)) as subdivision,
    array_remove(array_agg(distinct subdivision_name), null) as subdivision_names,
    percentile_cont(0.5) within group (order by latitude) as lat,
    percentile_cont(0.5) within group (order by longitude) as lng,
    mode() within group (order by year_built) filter (where year_built > 1900) as year_built,
    mode() within group (order by stories_total) filter (where stories_total > 0) as stories,
    count(*) as listings_total,
    max(coalesce(close_date, listing_contract_date::date)) as last_activity,
    count(*) filter (where standard_status='Active') as active_count,
    min(current_price) filter (where standard_status='Active') as active_min,
    max(current_price) filter (where standard_status='Active') as active_max,
    count(*) filter (where closed24) as closed24_count,
    min(current_price) filter (where closed24) as closed24_min,
    max(current_price) filter (where closed24) as closed24_max,
    percentile_cont(0.5) within group (order by current_price) filter (where closed24) as closed24_median,
    percentile_cont(0.5) within group (order by coalesce(close_price_by_calculated_sqft, case when living_area>0 then current_price/living_area end)) filter (where closed24) as closed24_median_ppsf,
    percentile_cont(0.5) within group (order by living_area) filter (where closed24 and living_area>0) as closed24_median_size,
    percentile_cont(0.5) within group (order by living_area) filter (where living_area>0) as all_median_size,
    percentile_cont(0.5) within group (order by current_price) filter (where standard_status='Closed') as all_closed_median,
    count(*) filter (where standard_status='Closed') as all_closed_count,
    percentile_cont(0.5) within group (order by fee_mo) filter (where fee_mo > 0 and coalesce(close_date, listing_contract_date::date) >= current_date - interval '24 months') as hoa_mo_24,
    percentile_cont(0.5) within group (order by fee_mo) filter (where fee_mo > 0) as hoa_mo_all,
    mode() within group (order by pets_allowed) filter (where pets_allowed is not null) as pets_allowed,
    mode() within group (order by pet_restrictions) filter (where pet_restrictions is not null) as pet_restrictions,
    max(max_pet_weight) filter (where max_pet_weight < 900) as max_pet_weight,
    mode() within group (order by number_of_pets) filter (where number_of_pets is not null) as number_of_pets,
    mode() within group (order by minimum_lease) filter (where minimum_lease is not null) as minimum_lease,
    bool_or(lease_restrictions_yn) as lease_restrictions,
    max(num_of_own_years_prior_to_lse) as own_years_before_lease,
    mode() within group (order by garage_spaces) filter (where garage_spaces > 0) as garage_spaces_max,
    count(*) filter (where garage_spaces > 0) as garage_listings,
    bool_or(coalesce(building_elevator_yn, has_elevator, false)) as elevator,
    bool_or(coalesce(waterfront_yn, is_waterfront, false)) as waterfront,
    bool_or(waterfront_features ilike '%gulf%' or waterfront_features ilike '%beach%') as gulf_front,
    bool_or(waterfront_features ilike '%bay%' or waterfront_features ilike '%harbor%' or waterfront_features ilike '%intracoastal%' or waterfront_features ilike '%canal%') as bay_front,
    string_agg(distinct waterfront_features, ' | ') as waterfront_features,
    string_agg(distinct water_view, ' | ') as water_views
  from base
  where bkey is not null
  group by bkey
),
agg2 as (
  select bkey,
    bool_or(coalesce(has_pool_community,false)) as has_pool,
    bool_or(coalesce(has_fitness_center,false)) as has_fitness,
    bool_or(coalesce(has_tennis,false)) as has_tennis,
    bool_or(coalesce(has_pickleball,false)) as has_pickleball,
    bool_or(coalesce(has_dock,false)) as has_dock,
    bool_or(coalesce(is_gated,false)) as gated,
    bool_or(coalesce(has_restaurant,false)) as has_restaurant,
    bool_or(coalesce(big_dog_friendly,false)) as big_dog_friendly,
    mode() within group (order by building_class) filter (where building_class is not null) as building_class
  from base where bkey is not null group by bkey
)
select a.*, f.community_features_raw, e.exterior_features_raw,
  g.has_pool, g.has_fitness, g.has_tennis, g.has_pickleball, g.has_dock, g.gated, g.has_restaurant, g.big_dog_friendly, g.building_class,
  coalesce(a.hoa_mo_24, a.hoa_mo_all) as hoa_mo,
  coalesce(a.closed24_median_size, a.all_median_size) as median_size,
  b.display_name, b.photo_url, b.pets_override, b.rental_override, b.parking_override, b.amenities_override,
  coalesce(b.hidden,false) as hidden, b.updated_by, b.updated_at,
  (select count(*) from public.condo_building_notes n where n.building_key = a.bkey) as note_count
from agg a
left join feat f on f.bkey = a.bkey
left join ext e on e.bkey = a.bkey
left join agg2 g on g.bkey = a.bkey
left join public.condo_buildings b on b.building_key = a.bkey;

grant select on public.v_condo_buildings to service_role;

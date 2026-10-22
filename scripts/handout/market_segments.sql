-- Segment stats behind the handout's "How's the market?" card. Run against Supabase (MLS-Data).
-- Trailing-12-month closed condos; months of supply = active / (closed12 / 12).
with base as (
 select *,
  case when year_built>=2024 then 'developer-era (2024+, mostly pre-construction; MoS not meaningful)' when year_built>=2015 then 'new resale (2015-2023)' when year_built>=1995 then 'mid (1995-2014)' else 'older (pre-1995)' end era,
  case when coalesce(waterfront_features,'') ilike '%Gulf%' or coalesce(waterfront_features,'') ilike '%Beach%' then 'Beachfront (Gulf)'
       when coalesce(waterfront_features,'') ilike '%Bay%' or coalesce(waterfront_features,'') ilike '%Intracoastal%' or coalesce(waterfront_features,'') ilike '%Canal%' then 'Bayfront'
       when coalesce(water_view,'') <> '' then 'Water view, not on water' else 'No water view' end seg
 from raw_listings where detected_area in ('longboat-key','st-armands-lido','downtown-sarasota') and property_sub_type='Condominium'),
closed as (select * from base where standard_status='Closed' and close_date >= current_date - interval '365 days'),
active as (select * from base where standard_status='Active')
select 'era' dim, c.era k, count(*) closed12,
 round(percentile_cont(0.5) within group (order by c.close_price_by_calculated_sqft)) med_ppsf,
 round(avg(c.close_price_by_calculated_list_price_ratio)::numeric,3) sp_lp,
 round((select count(*) from active a where a.era=c.era)/(count(*)/12.0),1) months_supply
from closed c group by c.era
union all
select 'water', c.seg, count(*),
 round(percentile_cont(0.5) within group (order by c.close_price_by_calculated_sqft)),
 round(avg(c.close_price_by_calculated_list_price_ratio)::numeric,3),
 round((select count(*) from active a where a.seg=c.seg)/(count(*)/12.0),1)
from closed c where c.detected_area in ('longboat-key','st-armands-lido') group by c.seg
order by 1,2;

-- Five-year arc behind the card (InfoSparks rolling-12, condos, each September)
select geo_key, metric, period, round(value::numeric,1) v from market_series
where geo_type='zip' and geo_key in ('34228','34236') and property_type='condo' and calc='r12'
  and metric in ('median_sales_price','median_price_per_sqft','months_supply','median_cdom','closed_sales')
  and extract(month from period)=9 and period >= '2019-01-01'
order by metric, geo_key, period;

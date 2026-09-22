-- Zillow ZIP-level Home Value Forecast, written by netlify/functions/zhvf-refresh.js
-- (1st and 15th). Read by cma-adjustments.js ?action=forecast&zip=. Run once in the SQL editor.
create table if not exists public.forecast_zip (
  source         text        not null,          -- 'zillow_zhvf'
  zip            text        not null,
  base_date      date        not null,          -- Zillow BaseDate
  horizon_months int         not null,          -- 1, 3, 12
  pct_change     numeric     not null,          -- forecast % change from base
  city           text,
  county         text,
  metro          text,
  state          text,
  fetched_at     timestamptz not null default now(),
  primary key (source, zip, base_date, horizon_months)
);
create index if not exists forecast_zip_zip_idx on public.forecast_zip (zip, base_date desc);
alter table public.forecast_zip enable row level security;
-- no policies: only the service role (Netlify functions) reads and writes this table.

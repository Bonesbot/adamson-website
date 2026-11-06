-- competition_sets: the "Active competition" roster for a listing landing page.
-- One row per page. listing_ids come from whatever MLS saved search Ryan ran
-- (any mix of geography and parameters); active-comps.js resolves them live
-- against raw_listings. seed_rows carries a snapshot for any MLS number that is
-- outside the daily import geography so the table is never missing a row; the
-- page labels those as "as of <seeded_at>".

create table if not exists public.competition_sets (
  set_key      text primary key,
  title        text not null,
  criteria     text,
  preset       text not null default 'condo',          -- 'condo' | 'sfh'
  listing_ids  text[] not null default '{}',
  seed_rows    jsonb not null default '[]'::jsonb,     -- same shape as the function's row output
  seeded_at    date,
  notes        jsonb not null default '{}'::jsonb,     -- { "<mls#>": "one-line note shown under the address" }
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

alter table public.competition_sets enable row level security;
-- read by the Netlify function with the service role; no anon access needed.

insert into public.competition_sets (set_key, title, criteria, preset, listing_ids, seed_rows, seeded_at)
values (
  '4539-bay-club',
  'True waterfront condos: Bradenton, Sarasota, Longboat Key',
  'Waterfront condos, 1,500+ sq ft, garage or carport, under $1MM',
  'condo',
  array['A4707843','A4711413','A4660592','A4709314','A4708451','A4679944','TB8550356','A4709278',
        'A4679886','A4652757','A4703911','A4674328','A4703351','A4710787','A4709355','A4669912','A4609759'],
  '[
    {"id":"A4679886","address":"395 Aruba Cir #303","city":"Bradenton","subdivision":"Marina Walk On One Particular Harbour 2","status":"Active","yearBuilt":2016,"sqft":1664,"beds":3,"baths":3,"garage":0,"hoaMonthly":1518,"floor":"3","water":"Bay view","listPrice":685000,"pricePerSqft":412,"dom":282,"cdom":282,"originalListPrice":749000,"listOffice":"Premier Sotheby''s International Realty","postalCode":"34209"},
    {"id":"A4703911","address":"384 Aruba Cir #102","city":"Bradenton","subdivision":"Marina Walk On One Particular Harbour 2","status":"Active","yearBuilt":2017,"sqft":1664,"beds":3,"baths":3,"garage":0,"hoaMonthly":1518,"floor":"1","water":"Bay view","listPrice":724999,"pricePerSqft":436,"dom":71,"cdom":71,"originalListPrice":734999,"listOffice":"Dalton Wade Inc","postalCode":"34209"},
    {"id":"A4710787","address":"226 Sapphire Lake Dr #201","city":"Bradenton","subdivision":"Harbour Isle Ph 9 & Mangrove Walk Phase II","status":"Active","yearBuilt":2014,"sqft":1994,"beds":3,"baths":3,"garage":0,"hoaMonthly":1208,"floor":"2","water":"Lake front, bay view","listPrice":835000,"pricePerSqft":419,"dom":8,"cdom":8,"originalListPrice":835000,"listOffice":"Keller Williams On The Water","postalCode":"34209"},
    {"id":"A4709355","address":"291 Compass Point Dr #201","city":"Bradenton","subdivision":"Edgewater Walk II On Harbour Isle","status":"Active","yearBuilt":2017,"sqft":1994,"beds":2,"baths":2,"garage":2,"hoaMonthly":1206,"floor":"1","water":"Intracoastal view","listPrice":849000,"pricePerSqft":426,"dom":20,"cdom":20,"originalListPrice":849000,"listOffice":"Dalton Wade Inc","postalCode":"34209"}
  ]'::jsonb,
  date '2026-11-06'
)
on conflict (set_key) do update set
  title = excluded.title, criteria = excluded.criteria, preset = excluded.preset,
  listing_ids = excluded.listing_ids, seed_rows = excluded.seed_rows, seeded_at = excluded.seeded_at,
  updated_at = now();

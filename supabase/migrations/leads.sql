-- public.leads — THE core lead queue for adamsonfl.com and every landing page.
--
-- One table, one `source` flag. Every capture form (community landing pages,
-- SRQmap gate, listing pages, off-market registry, dream-home wishlist) writes
-- here. Adding the 30th community landing page requires NO schema change and NO
-- plumbing — the page just posts a new `source` string and appears in the queue.
--
-- Source convention:  <page-slug>:<intent>
--   gulf-and-bay-club-bayside:seller     community landing page, seller tile
--   gulf-and-bay-club-beachfront:buyer   community landing page, buyer tile
--   find-my-dream-home:buyer             wishlist form
--   off-market:seller                    off-market registry
--   srqmap-gate                          SRQmap lead gate (no intent split)
--   listing:1738-siesta-dr               per-listing enquiry
--
-- Form-specific extras (wishlist budget/areas/must-haves, off-market price
-- thresholds) go in `details` jsonb — GIN indexed, so the Phase 2b matching
-- engine can still query them.
--
-- Idempotent: safe to re-run.

create table if not exists public.leads (
  id           uuid        primary key default gen_random_uuid(),
  created_at   timestamptz not null default now(),
  status       text        not null default 'new',   -- new | contacted | qualified | dead
  source       text        not null,                 -- '<page-slug>:<intent>'
  lead_type    text,                                 -- 'Buyer' | 'Seller' | null
  first_name   text,
  last_name    text,
  email        text        not null,
  phone        text,
  community    text,                                 -- e.g. 'Gulf & Bay Club Bayside'
  page         text,                                 -- request path the form sat on
  message      text,
  details      jsonb,                                -- per-form typed extras
  raw_payload  jsonb,                                -- verbatim submission
  zoho_lead_id text,
  zoho_sync    text,                                 -- null = not yet pushed to Zoho
  zoho_error   text,
  idx_lead_id  text,
  idx_sync     text
);

create index if not exists leads_created_idx on public.leads (created_at desc);
create index if not exists leads_email_idx   on public.leads (email);
create index if not exists leads_source_idx  on public.leads (source);
create index if not exists leads_status_idx  on public.leads (status);
create index if not exists leads_zoho_idx    on public.leads (zoho_sync) where zoho_sync is null;
create index if not exists leads_details_idx on public.leads using gin (details);

alter table public.leads enable row level security;

-- Mirror the existing Command-Center read policy exactly (srqmap_leads_cc_read).
-- Netlify functions write with the service role, which bypasses RLS.
drop policy if exists leads_cc_read on public.leads;
create policy leads_cc_read on public.leads
  for select to authenticated
  using (cc_role() is not null);

drop policy if exists leads_cc_update on public.leads;
create policy leads_cc_update on public.leads
  for update to authenticated
  using (cc_role() is not null);

grant select, insert, update on public.leads to authenticated;
grant all on public.leads to service_role;

-- ── Compatibility shim ────────────────────────────────────────────────────────
-- The deployed Command Center's Leads tab queries `srqmap_leads`. Rather than
-- redeploy that app from this spoke (its local source has known drift), replace
-- the old table with a view over `leads` exposing the legacy column shape plus a
-- few useful additions. The dashboard picks up the unified queue with no change.
--
-- security_invoker = true so the querying role's RLS on `leads` still applies —
-- without it the view would run as owner and bypass RLS entirely.
--
-- TODO (Command-Center spoke): point the Leads tab at `leads` directly, surface
-- `source` / `lead_type` / `status`, then `drop view public.srqmap_leads`.

drop table if exists public.srqmap_leads;      -- contained only dummy test rows
drop view if exists public.srqmap_leads;

create view public.srqmap_leads with (security_invoker = true) as
  select id, created_at, first_name, last_name, email, phone, source,
         idx_lead_id, idx_sync, raw_payload, zoho_sync, zoho_lead_id,
         lead_type, community, status
    from public.leads;

grant select on public.srqmap_leads to authenticated;
grant all    on public.srqmap_leads to service_role;

notify pgrst, 'reload schema';

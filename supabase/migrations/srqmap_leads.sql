-- SRQmap gate lead capture — durable source of truth for map registrations.
-- Run once in Supabase SQL editor (or via CLI). Idempotent.

create table if not exists public.srqmap_leads (
  id          uuid        primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  first_name  text,
  last_name   text,
  email       text        not null,
  phone       text,
  source      text        default 'srqmap-gate',
  idx_lead_id text,                 -- IDX Broker Engage lead id, if the API sync succeeded
  idx_sync    text,                 -- 'ok' | 'skipped' | 'error_<code>' | 'exception'
  raw_payload jsonb
);

create index if not exists srqmap_leads_email_idx   on public.srqmap_leads (email);
create index if not exists srqmap_leads_created_idx  on public.srqmap_leads (created_at desc);

-- Service-role inserts (Netlify function) bypass RLS; enable RLS so the
-- anon/public key cannot read this table.
alter table public.srqmap_leads enable row level security;

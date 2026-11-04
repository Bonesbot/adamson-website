-- Applied 2026-11-04 via Supabase MCP. Last-good copy of each Home Platform
-- (Compass) CMA share page, normalized by netlify/functions/cma-live.js.
-- Read only when the live fetch of the /v/latest share URL fails.
create table if not exists public.cma_snapshots (
  cma_id       text primary key,
  version      text,
  title        text,
  fetched_at   timestamptz not null default now(),
  published_at timestamptz,
  payload      jsonb not null
);
alter table public.cma_snapshots enable row level security;

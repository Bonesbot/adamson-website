# AG_website — project context for Claude

## Related automation: the `mls-export` scheduled task (READ FIRST)

This website **shares a codebase** with a Claude/Cowork **scheduled task named `mls-export`**
(defined at `C:\Users\Bones\Documents\Claude\Scheduled\mls-export\SKILL.md`, with a companion
`mls-export-watchdog` task). The two are halves of one system: this repo is where the site is
built and hand-refined; the job runs the daily MLS extract and data prep that feeds it. They
continually overlap, so when working here, know the job exists.

What the `mls-export` job does each morning: logs into Stellar MLS, extracts the
`000 - Market Update` saved search, combines + de-dupes to one CSV, ingests to Supabase,
regenerates the per-area `src/data/*-stats.json` files, and publishes changes to GitHub
(one bundled commit, self-throttled to ~every 3 days) which triggers the Netlify build.

### Shared files this job owns — edit with care
These scripts are run by the job (fetched canonically from `origin/main` into `/tmp` on every
run, to dodge FUSE-mount truncation). If you change any of them here, **commit to `main`** — the
job ignores un-committed local working-tree edits.

**You no longer need to manually rotate `EXPECTED_HASHES.json` after changing a tracked script.**
As of the self-healing integrity gate (June 2026): when the daily runner fetches a tracked
script from `main` whose hash differs from the manifest, it checks whether the file is valid
(parses as Python / non-empty). If valid, it *adopts* your change — auto-rotates the manifest to
match `main` and pushes the corrected manifest back (`[skip ci]`, so Netlify is not rebuilt) —
and records it under `manifest_heal` in `last-run.json`. Only a genuinely corrupt script
(missing, or a `.py` that won't parse) still hard-fails with `failed_step="integrity_check"`.
Net effect: just commit your script change to `main`; the runner stays in sync on its own.

- `scripts/combine_mls_export.py` — combine batch CSVs + de-dupe
- `scripts/fetch_area_summary.py` — `compute_summary()` builds one area's stats from Postgres
- `scripts/refresh_all_areas.py` — regenerates ALL areas (reads `src/data/areas.json`) + publishes
- `scripts/push_to_github.py` — legacy per-file publisher (superseded by refresh_all_areas)
- `scripts/_integrity_check.py` + `scripts/EXPECTED_HASHES.json` — self-heal integrity gate
- `supabase/ingest_mls.py` — Postgres upsert with per-batch hash dedupe

### Machine-generated — do not hand-edit
- `src/data/*-stats.json` — regenerated every run; hand edits are overwritten. To change what a
  page shows, change the generator (`fetch_area_summary.py` → `compute_summary`), not the JSON.
- `mls-imports/market-update_*.csv` — the job's extract drop folder (gitignored).

### Source of truth for areas
- `src/data/areas.json` lists which areas exist (9 today: longboat-key, st-armands-lido,
  siesta-key, downtown-sarasota, west-of-trail-core, west-of-trail-north, west-of-trail-south,
  bird-key, palmer-ranch). `refresh_all_areas.py` reads it — there is no hardcoded slug list.
  Add/rename areas here. (`lido-key` and `st-armands` are retired dead slugs — use the combined
  `st-armands-lido`.)

### Methodology notes (so site numbers stay defensible)
- Months of supply lives in each stats file's `marketBalance` block, computed as
  `active / (trailing-12-month closed / 12)`, segmented condo vs SFH/villa. It is intentionally
  NOT the 90-day window (that runs seasonally hot and understated supply).
- The 90-day window is still used for recent median price / DOM / sale-to-list — that's correct.

When in doubt, the job's `SKILL.md` (path above) documents the full pipeline end to end.

## SRQmap "Events This Week" (daily scheduled task: `srqmap-events`)

The SRQmap guide map (`src/pages/SRQmap.astro`) has an auto-maintained **Events This Week**
category, refreshed by the Cowork scheduled task `srqmap-events`
(`C:\Users\Bones\Documents\Claude\Scheduled\srqmap-events\SKILL.md`).

- `src/data/srqmap-events.json` — **machine-generated, do not hand-edit.** The task researches
  local events (Your Observer, Sarasota Magazine, VisitSarasota, ABC7/Mysuncoast), picks the
  top 3-4 within the next 7 days, and publishes via
  `scripts/events/publish_srqmap_events.py` (validates schema + Sarasota-area lat/lng bounds,
  prunes events whose end_date < today, pushes via Contents API only when the set changed —
  each push triggers a Netlify rebuild so expired events disappear).
- `SRQmap.astro` also drops past events at build time as a safety net.
- Gate note: the SRQmap soft lead gate has a `GATE_ENABLED` kill-switch in `SRQmap.astro`
  (set to `false` on 2026-07-05 for testing — flip back to `true` to restore the 3-pin wall).

## Feature-listing landing pages (/listings)

941props.com-style single-property marketing pages, data-driven:
- `src/data/listings/<slug>.json` — one file per listing; every field maps to a page
  section. Create/hydrate/push via `scripts/listings/new_listing.py` (`--mls <id>` pulls
  price/beds/baths/sqft/garage from Supabase raw_listings; blank scaffold for off-market).
- `src/pages/listings/[slug].astro` — the template (hero, stat bar, features, tours,
  floor plan, map, photo lightbox, inquiry form). `/listings` index auto-lists everything
  except status:"off-market".
- Leads POST to the existing `srqmap-lead` function with `source: "listing:<slug>"`
  (message lands in raw_payload). No new table needed.
- Full workflow: `LISTINGS_PLAYBOOK.md`.

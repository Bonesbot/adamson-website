# CMA System (v2): repeatable condo + SFH CMAs on adamsonfl.com

Supersedes the v1 workbench notes that lived in this file. One system, cloneable per
listing with zero code changes. Everything hangs off four pieces:

| Piece | URL / path | Access |
|---|---|---|
| Admin GUI | `adamsonfl.com/mkt/admin/` | login (edit key) |
| Workbench (per CMA) | `/mkt/<slug>/workbench.html` | login (redirects to admin if not signed in) |
| Client page (per CMA) | `/mkt/<slug>/` | public, shareable, no password, noindex |
| Backend | `/.netlify/functions/cma-adjustments` | every write requires the edit key |

## The data model (why refreshes never eat your judgment)

| Store | Holds | Rewritten by |
|---|---|---|
| `public/mkt/<slug>/data.json` | comp FACTS from the saved-search export | Refresh Comps (git commit, one rebuild) |
| Supabase `cma_adjustments` | your LIVE judgment overlay + multiplier tweaks, keyed by MLS # | every workbench Save, instantly, no rebuild |
| `public/mkt/<slug>/adjustments.json` | committed snapshot of the overlay | Freeze to git, on demand |
| Supabase `cma_pages` | registry: slug, profile, address, saved search | Create + automatic touches |
| `public/mkt/_template/` | THE master index.html + workbench.html | you, deliberately; every new CMA copies them |

Overlay entries are keyed by MLS #. When an export has no MLS column (Stellar's
compact "Comp Template" shape), Refresh re-keys rows by address match against the
deployed data.json, so reviewed and frozen comps stay attached either way.

meta.profile ("condo" | "sfh") drives everything profile-specific: comps-table columns,
subject facts, auto-adjustment set (condo: age/rooms/size/fee/time; sfh adds garage and
lot), and the default judgment buckets. Buckets themselves live per-CMA in the overlay,
so any property can have custom ones.

## One-time setup

1) Supabase SQL editor:

```sql
create table if not exists public.cma_adjustments (
  slug        text        primary key,
  adjustments jsonb       not null,
  rev         integer     not null default 1,
  updated_at  timestamptz not null default now()
);
create table if not exists public.cma_pages (
  slug         text        primary key,
  profile      text        not null,
  address      text,
  saved_search text,
  status       text        not null default 'draft',
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
alter table public.cma_adjustments enable row level security;
alter table public.cma_pages       enable row level security;
-- no policies: only the function's service role key reaches these tables

-- register the pre-existing CMA so it appears in the admin list:
insert into public.cma_pages (slug, profile, address, saved_search)
values ('6116-43rd-305d-cma','condo','6116 43rd St W #305D','AAAA - 6116 43rd St W 305D - CMA')
on conflict (slug) do nothing;
```

2) Netlify env vars: `CMA_EDIT_KEY` (your login/passphrase), `GITHUB_TOKEN`
(fine-grained PAT, Contents:write), optional `GITHUB_REPO` / `GITHUB_BRANCH`
(default Bonesbot/adamson-website @ main). `SUPABASE_URL` and
`SUPABASE_SERVICE_ROLE_KEY` are already set from the off-market form.

Note: create / refresh / freeze now need `GITHUB_TOKEN`; plain saves do not.

## The repeatable process per listing

1. **Admin → New CMA.** Pick profile, fill the subject, optionally attach the comp CSV.
   Slug and saved-search name derive from the address ("AAAA - <address> - CMA": that
   name is the contract; create the saved search under it in the MLS / Home Platform).
   Create commits 4 files from the master templates; pages live in 1 to 2 minutes.
2. **Workbench.** Enter bucket adjustments, notes, client notes. Save = instant, from
   any device. Tick Rev when a comp is reviewed, Frz when it is final (locks inputs).
3. **Refresh Comps** whenever you re-run the saved search: export CSV, Admin → Refresh,
   commit. Facts update; overlay untouched.
4. **Freeze to git** when a CMA is final: versioned backup + offline fallback.
5. **Share** the client page URL: no password, hides everything internal, and the DRAFT
   banner disappears once every included comp is marked reviewed.

## Data sources and automation

Adapters live in `public/mkt/admin/index.html` (`MAPS`): Stellar full export and
Stellar compact ("Comp Template") auto-detect by header. **Home Platform (Compass):**
rolled out to Coldwell Banker July 2026; Compass exposes no public/agent API, so the
adapter approach stands: export CSV from Home Platform, drop it in Refresh, and the
first time an export is in hand we add its column map (one small object; nothing else
changes). Longer-term automation: a scheduled Cowork task drives the browser to run the
saved search, export, and call Refresh: the saved-search name stored per CMA is what
makes that automatable.

## Security model, stated plainly

Writes are enforced server-side by CMA_EDIT_KEY (constant-time compare, rev-locked
against concurrent overwrites). The login page gates the admin and workbench UI so
nobody stumbles into the tooling, but the static workbench HTML and each CMA's
data.json / adjustments.json are still fetchable by anyone who knows the exact URL:
acceptable per Ryan's call (client pages are meant to be shared; slugs are unguessable
enough), revisit if a CMA ever contains something genuinely sensitive.

## Updating the look or logic later

Edit `public/mkt/_template/*.html` and push: NEW CMAs pick it up automatically.
Existing CMAs keep their copied version until you re-copy the template over their two
HTML files (data and adjustments are untouched by that). Old v1 pages (e.g. the
Featherstone CMA under `cma-7333-featherstone/`) keep working as-is; migrate one by
creating it fresh in the admin and porting the overlay, or leave it alone.

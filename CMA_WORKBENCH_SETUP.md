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

## Market Update table + Zillow Zip Code Forecast (added 2026-09-22)

Both live in the overlay (Supabase `cma_adjustments.adjustments`, jsonb), so they save
with the workbench Save button and need no rebuild. New keys: `include{marketUpdate,
zillowForecast}`, `forecastZip`, `marketUpdate{title,subtitle,asOf,link,rows[]}`.

Workbench, "Market Update" card: Import MLS CSV (any Stellar export; rows merge by MLS #,
sort by price low to high), a one-line note per row that prints LEFT of the row on the
client page, Bold and Highlight (green / yellow / gray) per row, Min / Median / Average /
Max footer, a "See the properties referenced" link, and the two "Client page & PDF
sections" checkboxes. The client page shows the sections only when checked.

Zillow forecast, one-time setup:
1. Run `supabase/sql/2026-09-22_forecast_zip.sql` in the Supabase SQL editor.
2. `node scripts/seed_zhvf.cjs` from `AG_website/` loads today's Florida rows (about
   2,600). After that the Netlify scheduled function `zhvf-refresh` (netlify.toml,
   1st and 15th, 12:00 UTC) keeps it current. Free public CSV, no key.
3. The client page reads `?action=forecast&zip=` from `cma-adjustments`. ZIP comes from
   `data.json subject.zip`, or type one in the workbench.

## Client page controls (added 2026-09-22, evening)

Workbench card "Client Page: Sections, Titles & Fields", all saved in the overlay:
- `include{...}`: untick a section (Your Residence, Comparable Sales, Currently on the Market,
  Up Close, Pricing Ladder, Comp Locations, Market Update, Zillow forecast, Online Estimates)
  and it leaves the client page and the PDF.
- `titles{...}`: retitle any section for the client (blank = default).
- `hidden{subject:[], comps:[], mu:[]}`: per-field hides (subject facts, comp columns, Market
  Update columns). Hidden items go grey and struck through in the workbench, including the
  matching columns in the adjustment grid and the Market Update grid.
- Comparable Sales now has a Status column on both pages. The grid's Status box overrides the
  MLS status per comp (`overlay[mls].statusLabel`), for failed listings shown as comps:
  "Withdrawn (WDC)", "Canceled (CAN)", "Coming Soon" and so on. Non-sales carry their last
  asking price in `price`, and the client page says "asking" on their Up Close card.
- Subject facts include Garage / Parking (`subject.parking` free text, else `subject.garage`).
- Market Update gets a Dist (mi) column (haversine from `subject.lat/lng` to the row's MLS
  Latitude/Longitude, captured by the CSV importer; rows imported before this need a re-import).
- Online Estimates: `avms[{name,value,asOf,url}]`. No AVM has a public API for agents, so
  "Open lookup pages" opens Zillow, Redfin, Realtor.com and Homes.com searches for the subject
  in new tabs and you type the numbers in. The section renders only when a value is entered.
- Section order: drag the handle in the Sections card; saved as `order[]`. Ladder and map are
  now independent cards so they can move like everything else.
- Client summaries: `summaries{comps, marketUpdate}` free text, shown under the comparables
  table and under the Market Update table (blank = not shown).
- Print (2026-09-22 evening): dedicated print stylesheet, whole-dollar $/sq ft everywhere, bold
  sale/ask price, DOM and sq ft averages in the comparables totals row, comps subheader and the
  fine print under the table removed, Market Update starts a new page.
- Non-sales in the comparables table carry an asterisk on the comp number, address and price,
  with a one-line note under the table. Comp numbers are plain outlined boxes; addresses are
  larger. Comparables subheader is editable (`titles.compsSub`, `{ppsf}` inserts the current
  per-sq-ft rate; a single space hides it). "Top tiles" is a section toggle (`include.strip`)
  and hides itself when the list price is 0; the "vs. Current List" figure goes with it.
  Notes card sits directly under the Adjustment Grid.
- Your Residence editor is the first card in the workbench: every subject fact is editable
  (`subjectOverride`, wins over data.json and feeds the adjustment math) with a show/hide box
  per row. Sections card adds "Cover page" (off by default) and "Indicated value range box".
- Cover page (`cover{photo, kicker, address, agentName, agentEmail, agentPhone, headshot,
  preparedOn}`): full-page hero photo behind a white card, in the Home Platform style; prints
  as page 1. Upload resizes in the browser to 1800 px JPEG and POSTs `?action=cover-photo` to
  `cma-adjustments`, which stores it in the public Storage bucket `cma-assets` (created on
  first use) and returns the URL. Headshot defaults to /images/ryan-adamson-square.jpg.
- Comparables totals: "Averages of all N comps above" plus "Averages of N Sold comps" when the
  set mixes sales and non-sales. Forecast summary text (`summaries.forecast`) under Zillow.

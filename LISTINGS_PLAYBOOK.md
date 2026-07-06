# Feature-Listing Landing Pages — Launch & Management Playbook

The 941props.com single-property format, rebuilt on adamsonfl.com: dark/gold AdamsonFL
design, AEO/SEO schema baked in, lead capture wired to the Supabase + IDX pipeline.

## How it works (30-second version)

- **One JSON file per listing** → `src/data/listings/<slug>.json`
- **Template** → `src/pages/listings/[slug].astro` renders every section from the JSON:
  hero → stat bar → 6 key features → price/CTA → virtual tour → video tour → floor plan
  → map → photo tour (lightbox) → private-inquiry form
- **Index** → `/listings` lists every listing except `status: "off-market"` ones
  (off-market pages are link-only teasers and default to `noindex: true`)
- **Leads** → form POSTs to `/.netlify/functions/srqmap-lead` with
  `source: "listing:<slug>"` → Supabase `srqmap_leads` (message saved in `raw_payload`)
  → best-effort IDX Engage sync. Filter in Supabase: `source like 'listing:%'`
- Commit the JSON to `main` → Netlify builds → page is live in ~1 minute.

## Launching a new listing

**A. Off-market / pre-MLS (manual entry — the "simple form" is the JSON):**
```
python scripts/listings/new_listing.py --slug 123-ocean-dr --address "123 Ocean Dr" \
  --city Sarasota --zip 34236 --neighborhood "Lido Shores" --price 4500000 \
  --status off-market --local
```
Edit `src/data/listings/123-ocean-dr.json` (or hand the fields to Claude/BonesBot in a
Cowork session — "spin up a listing page for 123 Ocean Dr, here are the bullets/photos"),
then publish: `python scripts/listings/new_listing.py --slug 123-ocean-dr --push-only`

**B. Already live in MLS (auto-pull key stats):**
```
python scripts/listings/new_listing.py --slug 123-ocean-dr --mls A4650001
```
Pulls price, heated sq ft, beds, baths, garage, year built, lat/lng from Supabase
`raw_listings` (fed by the daily `mls-export` job). Then fill tagline, 6 features,
photos, tour URLs and re-push with `--push-only`.

**Going live on MLS later?** Flip `"status": "off-market"` → `"active"`, set
`"noindex": false`, add the `mls_id`, re-push. Same URL keeps all its link equity.

## Field cheat-sheet (everything optional except slug/address/price)

| Field | Drives |
|---|---|
| `tagline` | Hero eyebrow ("One-Acre Privacy") |
| `status` | Badge + price prefix + schema availability: active / coming-soon / off-market / pending / sold |
| `stats[]` | The big number bar (any 4-6 value/label pairs) |
| `features[]` | Key Features cards (aim for 6, title + 2-3 sentences) |
| `open_house` | Gold banner in hero + price section ("Open Sunday (9/7) — 1 to 4 PM"); clear it after |
| `virtual_tour` / `video_tour` | Embeds (Ricoh360, Matterport, YouTube embed URLs) |
| `floor_plan` | Floor-plan image section |
| `photos[]` | Photo tour grid + lightbox + og/schema images |
| `faq[]` | FAQPage schema (AEO gold — 2-4 buyer questions with factual answers) |
| `noindex` | Keep search engines away from quiet off-market teasers |

## Photos

Photo URLs can be hotlinked (current Lindrick page hotlinks 941props.com) but the
durable path is self-hosting: drop images in `public/images/listings/<slug>/` and
reference `/images/listings/<slug>/01.jpg`. **Migrate before retiring 941props.com.**

## AEO/SEO checklist (template does this automatically)

- JSON-LD: RealEstateListing + SingleFamilyResidence (geo, floorSize, beds/baths,
  yearBuilt) + Offer + BreadcrumbList + FAQPage
- Semantic HTML, all content server-rendered, unique title/meta/canonical/og:image
- After each launch: request indexing in Search Console, add the property to the
  relevant area page if it's in one of the 9 covered areas, and run the AEO audit
  ritual if the template itself changed.

## Retiring 941props.com (when ready)

Set 301 redirects at SiteGround/WordPress: `/lindricklane/ → adamsonfl.com/listings/8361-lindrick-lane`
(one per legacy landing page), migrate any hotlinked photos first.

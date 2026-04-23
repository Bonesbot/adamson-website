# Ryan Adamson — Luxury Real Estate Website
## Project Specification & Session Context

> **Purpose**: This file is the "project memory" for BonesBot/Claude sessions. Drop it into any new Cowork session to restore full context.

---

## Overview

**Agent**: Ryan Adamson, Coldwell Banker St. Armands  
**Domain**: Luxury residential real estate — Sarasota, Lido Key, Longboat Key, Siesta Key, St. Armands Circle, Bird Key, and surrounding barrier islands  
**Primary Goal**: Build an AEO-first (AI Engine Optimization) website that positions Ryan as the authoritative source for luxury real estate data in the Sarasota coastal market  
**Built By**: BonesBot (dedicated Claude instance on Windows mini-PC)

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Framework** | Astro 5 (SSG mode) | Clean static HTML = best for AI crawlers. Island architecture for interactive widgets later. |
| **Styling** | Tailwind CSS 4 | Utility-first, fast iteration, luxury design tokens |
| **Language** | TypeScript | Type safety across components and data pipelines |
| **CMS** | Sanity v3 (Studio) | WordPress-level editing UX, structured content, free tier, API for automation |
| **Data Warehouse** | Supabase (Postgres) | Full SQL, visual table editor, REST API, free tier. Replaces BigQuery — simpler, cheaper, more accessible. |
| **Hosting** | Netlify | Auto-deploy from GitHub, free SSL, forms, edge functions, scheduled rebuilds. Site deploys to Netlify CDN (global edge). Custom domain (e.g. adamsonfl.com or new domain) pointed via DNS. |
| **Version Control** | GitHub | Standard git workflow, triggers Netlify builds |

---

## AEO Strategy (AI Engine Optimization)

AEO is the primary differentiator. Every architectural decision serves this goal.

### Core Principles
1. **Clean semantic HTML** — No JS-rendered content. AI crawlers (ChatGPT, Perplexity, Gemini, Copilot) parse raw HTML. Astro SSG guarantees this.
2. **Question-answer content architecture** — Pages structured around real questions people ask AI about the Sarasota luxury market.
3. **JSON-LD structured data on every page** — Schema.org types: `RealEstateAgent`, `FAQPage`, `LocalBusiness`, `Place`, `WebPage`, `Article`, `Dataset`.
4. **llms.txt** — AI discovery file at site root telling AI crawlers what the site is about and where to find key content.
5. **AI-friendly robots.txt** — Explicitly allows GPTBot, Google-Extended, Anthropic, PerplexityBot, etc.
6. **Data-rich content** — Real MLS-sourced numbers (median price, DOM, inventory, YoY changes) baked into HTML at build time. AI engines cite authoritative data.
7. **Topical authority clustering** — Interlinked neighborhood pages, market reports, and guides create a content web that signals expertise to AI.

### AEO Content Types
- **Market Q&A pages**: "What is the average home price on Longboat Key?" with real data, updated at each build
- **Neighborhood guides**: Deep, structured profiles with demographics, price ranges, lifestyle info
- **Monthly market reports**: Auto-generated from BigQuery data, published as blog posts with structured data
- **FAQ sections**: On every page, marked up with `FAQPage` schema

---

## Site Map & Page Architecture

### Phase 1 (Launch)
```
/                           → Homepage (hero, value prop, featured areas, CTA)
/about                      → Ryan Adamson bio, credentials, Coldwell Banker affiliation
/areas/                     → Area index page
/areas/sarasota             → Sarasota market page (AEO Q&A + data)
/areas/longboat-key         → Longboat Key market page
/areas/lido-key             → Lido Key market page
/areas/siesta-key           → Siesta Key market page
/areas/st-armands           → St. Armands Circle market page
/areas/bird-key             → Bird Key market page
/market-reports/            → Blog-style market report index
/market-reports/[slug]      → Individual monthly/quarterly reports
/contact                    → Contact form (Netlify Forms)
/llms.txt                   → AI discovery file
/robots.txt                 → AI-friendly crawler rules
/sitemap.xml                → Auto-generated
```

### Phase 2 (Post-Launch)
```
/listings/                  → IDX integration or custom listing pages
/listings/[mls-id]          → Individual property pages
/chat                       → AI chatbot widget (site-wide overlay)
/resources/                 → Buyer/seller guides, mortgage calculator
```

---

## Data Pipeline

**Architecture**: AEO-first — every data decision serves the goal of giving AI engines authoritative, structured, citable answers about the Sarasota luxury market.

```
Stellar MLS → [CSV/API Export] → Supabase (Postgres)
                                      ↓
                              SQL Views (aggregation by area)
                                      ↓
                              Supabase REST API
                                      ↓
                              Push script → Sanity CMS (market stats fields)
                                      ↓
                              Sanity webhook → Netlify rebuild
                                      ↓
                              Astro generates static HTML with real data
                                      ↓
                              JSON-LD + FAQ schemas + clean semantic HTML
                                      ↓
                              AI engines cite your data as authoritative source
```

### Supabase Tables (Planned)

**Core Tables:**
- `raw_listings` — Raw MLS listing data (active + sold), includes `location` column as PostGIS `geography(Point, 4326)` for lat/long
- `areas` — Area definitions (name, slug, zip codes)
- `zone_polygons` — Geospatial zone boundaries (drawn in geojson.io, stored as PostGIS `geography(Polygon, 4326)`)
- `subdivision_aliases` — Maps MLS subdivision name variants to canonical names (see Subdivision Normalization below)
- `unmatched_subdivisions` — Queue for low-confidence fuzzy matches needing manual review
- `audit_log` — Track when data was last updated and by what process

**SQL Views:**
- `vw_market_stats_by_area` — Aggregated stats per area (median price, DOM, inventory, volume, YoY)
- `vw_market_stats_by_zone` — Aggregated stats per geospatial zone (beachfront, bayside, etc.)
- `vw_beachfront_stats` — Gulf-front properties only, per area
- `vw_bayside_stats` — Bay-side properties only, per area
- `vw_market_trends_monthly` — Monthly trend data for charts/reports
- `vw_subdivision_stats` — Stats by normalized subdivision name

**Required Postgres Extensions:**
- `postgis` — Geospatial queries (ST_Within, ST_Contains, geography types)
- `pg_trgm` — Trigram-based fuzzy text matching for subdivision normalization

---

### Geospatial Zone Segmentation (PostGIS)

**Purpose:** Segment listings into hyper-specific geographic zones beyond just "Longboat Key" — distinguishing Gulf-front from bayside, north end from south end, village-adjacent from remote, etc. This enables the most granular, authoritative market data on the web for these areas.

**Architecture:**
1. Enable PostGIS extension in Supabase (one-click in dashboard)
2. Each listing in `raw_listings` stores lat/long as a PostGIS `geography(Point, 4326)` column
3. Zone boundaries are drawn using [geojson.io](https://geojson.io) — a free tool where you draw polygons on a map and export GeoJSON coordinates
4. Polygons are stored in `zone_polygons` table with fields: `id`, `area_slug`, `zone_name` (e.g. "Longboat Key Gulf-Front"), `zone_type` (e.g. "beachfront", "bayside", "golf_course"), `boundary` (PostGIS geography)
5. Segmentation queries use `ST_Within()`:
   ```sql
   SELECT * FROM raw_listings
   WHERE ST_Within(
     location,
     (SELECT boundary FROM zone_polygons WHERE zone_name = 'Longboat Key Gulf-Front')
   );
   ```
6. Aggregation views (`vw_beachfront_stats`, `vw_bayside_stats`, `vw_market_stats_by_zone`) auto-compute stats per zone using JOINs against `zone_polygons`

**AEO Benefit:** Enables hyper-specific answers no competitor can provide:
- "What is the median price for Gulf-front homes on Longboat Key?" → `vw_beachfront_stats`
- "How do bayside condos compare to beachfront on Lido Key?" → `vw_bayside_stats` vs `vw_beachfront_stats`
- "What's the average price per sq ft for waterfront on Bird Key?" → zone-filtered aggregation

These granular answers get baked into area pages as FAQ schema, making Ryan's site the definitive source AI engines cite for Sarasota sub-market data.

---

### Subdivision Name Normalization

**Problem:** MLS data contains inconsistent subdivision names. The same community appears under multiple spellings, abbreviations, and typos — e.g., "Ritz Carlton Residences Ph 2", "Ritz-Carlton Res.", "Ritz Carlton Condo" are all the same place. Without normalization, aggregation queries fragment data across these variants, producing inaccurate stats and weakening AEO authority.

**Architecture:**

**`subdivision_aliases` table:**
| Column | Type | Description |
|--------|------|-------------|
| `id` | serial | Primary key |
| `mls_name` | text | Exact string from MLS data (the variant) |
| `canonical_name` | text | Normalized/official name |
| `confidence` | numeric | Match confidence (1.0 = exact/manual, 0.0–0.99 = fuzzy) |
| `matched_by` | text | How this alias was created: 'manual', 'exact', 'trigram', 'claude' |
| `created_at` | timestamptz | When the alias was added |

**`unmatched_subdivisions` table:**
| Column | Type | Description |
|--------|------|-------------|
| `id` | serial | Primary key |
| `mls_name` | text | The unmatched subdivision string |
| `best_candidate` | text | Closest trigram match found |
| `similarity_score` | numeric | pg_trgm similarity score of best candidate |
| `status` | text | 'pending', 'resolved', 'ignored' |
| `resolved_to` | text | Canonical name if manually resolved |
| `created_at` | timestamptz | When first encountered |

**Normalization Flow (runs on insert via Postgres trigger):**
1. New listing arrives in `raw_listings` with an MLS subdivision name
2. Trigger function `fn_normalize_subdivision()` fires:
   a. **Exact match** — Check `subdivision_aliases` for exact `mls_name` match → use `canonical_name` (confidence: 1.0)
   b. **Fuzzy match** — If no exact match, use `pg_trgm` `similarity()` function against known canonical names:
      ```sql
      SELECT canonical_name, similarity(mls_name, canonical_name) AS score
      FROM (SELECT DISTINCT canonical_name FROM subdivision_aliases) AS names
      WHERE similarity(mls_name, canonical_name) > 0.6
      ORDER BY score DESC
      LIMIT 1;
      ```
   c. **High confidence (score > 0.8)** — Auto-assign canonical name, add to `subdivision_aliases` with `matched_by = 'trigram'`
   d. **Low confidence (score 0.6–0.8)** — Insert into `unmatched_subdivisions` queue with the best candidate for human review
   e. **No match (score < 0.6)** — Insert into `unmatched_subdivisions` with `best_candidate = NULL`
3. The `raw_listings` row gets a `canonical_subdivision` column populated by the trigger

**Canonical Name Source of Truth:**
- The canonical name list lives in Supabase — NOT in application code
- Queryable, auditable, and maintainable via SQL or Supabase's visual table editor
- Ryan or BonesBot can add/edit canonical names directly in the dashboard

**AI-Assisted Cleanup (Optional):**
- A periodic script reads the `unmatched_subdivisions` queue
- Sends batch to Claude API with context: "Given these MLS subdivision name variants and this list of known canonical names, suggest the best match for each"
- Claude's suggestions are inserted into `subdivision_aliases` with `matched_by = 'claude'` and reviewed confidence scores
- Human reviews and approves via Supabase dashboard or a simple admin UI

**AEO Benefit:** Clean, normalized subdivision data means accurate per-subdivision stats. The site can authoritatively answer questions like "What is the average home price in Ritz Carlton Residences on Lido Key?" without data being fragmented across 5 different MLS spellings of the same community.

---

### AEO Data Strategy

The data pipeline exists to answer the questions AI engines ask:
- "What is the average home price on Longboat Key?" → median price from vw_market_stats_by_area
- "What do Gulf-front homes cost on Longboat Key vs bayside?" → vw_beachfront_stats vs vw_bayside_stats
- "How has the Siesta Key market changed this year?" → YoY from vw_market_trends_monthly
- "How many homes are for sale in Sarasota?" → active inventory from vw_market_stats_by_area
- "What is the average price in Ritz Carlton Residences?" → vw_subdivision_stats (normalized)

Every stat gets baked into:
1. Visible HTML text (human-readable)
2. JSON-LD structured data (machine-readable)
3. FAQ schema answers (AI-extractable)

### Data Flow
1. MLS data → Supabase `raw_listings` table (manual CSV upload or API)
2. Insert trigger normalizes subdivision names via `fn_normalize_subdivision()`
3. PostGIS assigns listings to geographic zones via `ST_Within()`
4. SQL views auto-aggregate by area, zone, and subdivision
5. `scripts/sync-market-data.ts` — Reads Supabase views, pushes stats to Sanity via API
6. Sanity webhook triggers Netlify rebuild
7. Astro pages render fresh data as static HTML with full schema markup
8. Scheduled runs (daily/weekly) keep everything current
9. Periodic Claude pass cleans up unmatched subdivision queue

---

## Design System

### Luxury Aesthetic Direction
- **Clean, editorial feel** — Think Architectural Digest meets modern web
- **Generous whitespace** — Let content breathe
- **Typography-forward** — Strong serif headings, clean sans-serif body
- **Muted luxury palette** — Deep navy/charcoal anchors, warm gold accents, soft whites
- **High-quality imagery** — Full-bleed hero sections, area photography
- **Subtle animations** — Fade-ins, parallax hints — nothing flashy

### Color Tokens (Tailwind)
```
BLACK BASE (dominant):
  Black:         #000000    (primary backgrounds)
  Black Soft:    #0A0A0A    (body background)
  Black Card:    #111111    (elevated cards)
  Dark:          #1A1A1A    (elevated surfaces)

CBGL BRAND BLUES:
  CBGL Blue:       #2D4280  (Coldwell Banker Global Luxury primary)
  CBGL Blue Light: #52a8ff  (CBGL secondary / accent / links)

LEGACY NAVY (kept for flexibility):
  Navy:          #1B2A4A
  Charcoal:      #2C3E50

GOLD ACCENT:
  Gold:          #C5A55A    (CTAs, luxury warmth)
  Gold Light:    #E8D5A3
  Gold Pale:     #F5EDD6

LIGHT (used sparingly as contrast breaks):
  Warm White:    #FAFAF8
  Pure White:    #FFFFFF
```

### Design Reference
- **Existing site**: www.AdamsonFL.com — dark-dominant, video hero, bold uppercase section headers, image cards with dark overlays, dual logo placement (Adamson Group + CB Realty)
- **Approach**: Dark-first design (black backgrounds), CBGL blue accents, gold for CTAs, light sections only as contrast breaks. Sharp, confident, luxury.

### Typography
- **Headings**: `Playfair Display` (serif — luxury, editorial)
- **Body**: `Inter` or `DM Sans` (clean, modern, readable)
- **Accent/Labels**: `Montserrat` or body font with letter-spacing

---

## Folder Structure

```
AG_website/
├── PROJECT_SPEC.md              ← This file (session context)
├── astro.config.mjs
├── tailwind.config.mjs
├── tsconfig.json
├── package.json
├── public/
│   ├── robots.txt
│   ├── llms.txt
│   └── images/
├── scripts/
│   └── fetch-market-data.ts     ← BigQuery → JSON pipeline
├── src/
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Header.astro
│   │   │   ├── Footer.astro
│   │   │   └── Navigation.astro
│   │   ├── ui/
│   │   │   ├── Button.astro
│   │   │   ├── Card.astro
│   │   │   └── ContactForm.astro
│   │   ├── seo/
│   │   │   ├── JsonLd.astro
│   │   │   ├── Meta.astro
│   │   │   └── FAQSchema.astro
│   │   └── market/
│   │       ├── MarketStats.astro
│   │       ├── PriceChart.astro  ← Astro island (client-side)
│   │       └── AreaCard.astro
│   ├── content/
│   │   ├── areas/               ← MDX files for each area
│   │   └── market-reports/      ← MDX files for reports
│   ├── data/
│   │   ├── market-stats.json    ← Generated by build script
│   │   └── areas.json
│   ├── layouts/
│   │   ├── BaseLayout.astro
│   │   ├── AreaLayout.astro
│   │   └── BlogLayout.astro
│   ├── pages/
│   │   ├── index.astro
│   │   ├── about.astro
│   │   ├── contact.astro
│   │   ├── areas/
│   │   │   └── [slug].astro     ← Dynamic area pages
│   │   └── market-reports/
│   │       ├── index.astro
│   │       └── [slug].astro
│   └── styles/
│       └── global.css
└── sanity/                      ← Sanity Studio (Phase 1.5)
    ├── schemas/
    └── sanity.config.ts
```

---

## Build Phases & Milestones

### Phase 1A — Foundation (Current)
- [x] Define tech stack and architecture
- [ ] Scaffold Astro project with Tailwind + TypeScript
- [ ] Create base layout, design tokens, typography
- [ ] Build Header, Footer, Navigation components
- [ ] Create homepage with hero and area cards
- [ ] Build area page template with AEO structure

### Phase 1B — Content & AEO
- [ ] Create all area pages (Sarasota, Longboat Key, Lido Key, Siesta Key, St. Armands, Bird Key)
- [ ] Implement JSON-LD structured data components
- [ ] Create llms.txt and AI-friendly robots.txt
- [ ] Build FAQ sections with schema markup
- [ ] About page and contact form
- [ ] Sitemap generation

### Phase 1C — Data Pipeline
- [ ] BigQuery connection script
- [ ] Market stats JSON generation
- [ ] Market report template with auto-populated data
- [ ] Scheduled rebuild configuration on Netlify

### Phase 1.5 — CMS Integration
- [x] Set up Sanity Studio (project ID: l8q8hky0, org: Adamson-Group)
- [x] Define content schemas (area, marketReport, siteSettings)
- [x] Create Sanity client + GROQ queries (src/lib/sanity.ts)
- [x] Migrate static JSON content into Sanity (fallback still in place)
- [x] Switch Astro pages to fetch from Sanity (with static JSON fallback)
- [x] Netlify build hook created
- [x] Sanity webhook → Netlify auto-deploy on publish

### Phase 2 — Enhanced Features
- [ ] IDX integration (listings search)
- [ ] AI chatbot widget
- [ ] Interactive market charts (Astro islands)
- [ ] Buyer/seller resource guides
- [ ] Mortgage calculator widget

---

## Key Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-22 | Astro 5 over Next.js/Gatsby | Pure SSG, zero JS by default, best AEO. No need for SSR or app-like features. |
| 2026-04-22 | Sanity over WordPress/Decap | Better editing UX, structured content, API for automation. Free tier sufficient. |
| 2026-04-22 | BigQuery as data warehouse | Existing MLS pipeline work. Build-time queries keep static site fast. |
| 2026-04-22 | Netlify over Vercel | Native form handling, simpler scheduled builds, generous free tier. |
| 2026-04-22 | AEO-first over SEO-first | AI search is growing faster than traditional search for RE queries. Position ahead of competition. |
| 2026-04-22 | Dark-first design w/ CBGL colors | Matches AdamsonFL.com feel. Black base (#000/#0A0A0A), CBGL blue (#2D4280/#52a8ff), gold accents. Sharp, confident luxury. |
| 2026-04-22 | Video hero banner | Carry over the video banner from existing site for hero section. |
| 2026-04-22 | Dual logo placement | Adamson Group logo + Coldwell Banker logo side-by-side in header/hero (matches existing site). |
| 2026-04-22 | Supabase over BigQuery | BigQuery was overkill and had API issues. Supabase = full Postgres, visual editor, REST API, free tier. Better fit for 6-area market aggregation. |

---

## Session Handoff Notes

*Updated each session with what was accomplished and what's next.*

### Session 1 — 2026-04-22
- Defined complete tech stack and architecture
- Created this PROJECT_SPEC.md
- Scaffolded Astro project with Tailwind 4 and TypeScript
- Built all Phase 1 pages: homepage (video hero), 6 area pages, about, contact, market reports index
- Built AEO layer: JSON-LD schemas, FAQSchema component, llms.txt, AI-friendly robots.txt
- Reviewed AdamsonFL.com for design reference
- Updated design system: dark-first (black base), CBGL blue (#2D4280 / #52a8ff), gold accents, video hero support
- Updated header with dual logo placement (Adamson Group + CB Realty)
- Added section patterns: dark-section, light-section, cbgl-section
- Wired all design assets from design_assets/ into public/images/logos/ and public/videos/
- **Assets now in place**:
  - `adamson-group-black.png` — Adamson Group logo (black, CSS inverted for dark bg; TODO: get native white version)
  - `cb-full-horz-white.png` / `cb-horz-white.png` — CB white logos for dark backgrounds
  - `cb-full-horz-dark.png` / `cb-horz-dark.png` — CB dark logos for light backgrounds
  - `cbgl-seal.jpeg` / `cbgl-hz-stacked-black.png` / `cbgl-vert-black.png` — CBGL Global Luxury marks
  - `cb-square.png` / `cb-white-block.png` — Additional CB logo variants
  - `hero-banner.webm` — Video placeholder for hero section (TODO: replace with Ryan's actual aerial/waterfront video)
- **Still needed**: Area photography (Longboat Key, Lido Key, etc.), Ryan's headshot, actual hero video from AdamsonFL.com, white version of Adamson Group logo
- Wired all design assets from design_assets/ into public/
- Fixed Tailwind v3 compatibility, got site running locally
- Deployed to Netlify via GitHub (bonesbot/adamson-website)
- Set up Sanity CMS (project ID: l8q8hky0, org: Adamson-Group)
- Built schemas: area, marketReport, siteSettings
- Deployed Sanity Studio to adamson-website.sanity.studio
- Switched Astro pages to fetch from Sanity with static JSON fallback
- Set up Netlify build hook + Sanity webhook for auto-deploy on publish
- **Full loop working**: Edit in Sanity → auto-deploy → live site updated
- **Next session**: Supabase data pipeline → Sanity, populate all 6 areas in Sanity, about page with real bio, area photography, custom domain setup

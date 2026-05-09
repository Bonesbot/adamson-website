# /new-construction — PROTOTYPE (NOT PUBLISHED)

Built from the spec in the "New Dev Site Plan" Google Doc. **Nothing here is wired into the live site nav.** It is a clickable scaffold for Ryan to fill in.

---

## How it stays unpublished

Three layers of gating:

1. **`noIndex: true`** on every page in `src/pages/new-construction/` — emits `<meta name="robots" content="noindex, nofollow">` via `BaseLayout`. AI crawlers and Google honor this.
2. **Sitemap exclusion** — `astro.config.mjs` `sitemap()` integration has a filter that drops any URL containing `/new-construction/`. Won't appear in `/sitemap-index.xml`.
3. **No nav link** — `Header.astro` is unchanged. The pages only exist if someone types the URL.

A persistent orange `DRAFT — PROTOTYPE` banner renders at the top of every page so Ryan can never confuse a prototype URL with a live page.

### To flip live (when Ryan is ready)
1. Remove `noIndex={true}` from every page in `src/pages/new-construction/`.
2. Remove the `/new-construction/` filter line from `astro.config.mjs`.
3. Delete every `<DraftBanner />` import and usage.
4. Add the "New Construction" mega-menu item to `src/components/layout/Header.astro` per spec §3.
5. Submit updated sitemap to Google Search Console + Bing Webmaster Tools.

---

## File map

```
src/
  pages/
    new-construction/
      index.astro                   Hub page (10 sections from spec §4)
      downtown-sarasota.astro       Single-area pillar (spec §6a)
      barrier-islands.astro         Multi-area pillar with #lido-key, #longboat-key, #siesta-key (spec §6b)
      [slug].astro                  Dynamic project page — full or stub depending on build_depth in projects.json
  components/
    newconstruction/
      DraftBanner.astro             Orange banner, every prototype page
      Hero.astro                    Full-bleed hero with image, headline, dual CTAs, optional trust strip
      TrustBar.astro                Credentials/logos strip
      ProjectMap.astro              PLACEHOLDER for Mapbox interactive map
      ProjectCard.astro             Card for grids and carousels
      ProjectComparisonTable.astro  Sortable table — critical AEO surface
      AreaSection.astro             Hub-page area block (header + intro + 3 cards)
      IslandSubSection.astro        Per-island sub-block on Barrier Islands page
      IdxListingGrid.astro          STUB with placeholder listings — wires to /idx-wrapper/ later
      MarketDataKpis.astro          3-tile KPI row (Median $/sf, Avg DOM, Inventory)
      MarketTrendChart.astro        PLACEHOLDER chart shell
      QuickFactsPanel.astro         Project page sticky right rail (all spec fields)
      FloorPlanViewer.astro         PLACEHOLDER floor-plan gallery
      AmenitiesGrid.astro           Icon grid + descriptions
      SchedulerEmbed.astro          PLACEHOLDER for Calendly/Cal.com/TidyCal
      VipForm.astro                 VIP list email capture (Netlify Forms ready)
      StickyMobileCta.astro         Persistent mobile bottom CTA
      RelatedContent.astro          3 most recent blog posts tagged "new-construction"
      BreadcrumbNav.astro           Auto-from-URL trail
      DisclosureFooter.astro        Fair housing + IDX attribution + accuracy disclaimer
      PhotoGallery.astro            Project photo gallery with provenance support
      LocationBlock.astro           Embedded map + walk-to/drive-to callouts
      ComparableProjects.astro      Auto-generated similar-project row
      ProjectStubBody.astro         Lightweight body for stub project pages
  data/
    newconstruction/
      projects.json                 All 8 Phase-1 projects with FILL-IN markers
      islands.json                  Lido / Longboat / Siesta MLS area + zip mappings
      faq.json                      Hub-level FAQ stems from spec §4
PROTOTYPE_NEW_CONSTRUCTION_README.md   This file
```

---

## What's stubbed vs what's real

| Element | Status | Notes |
|---|---|---|
| Page structure & section order | **Done** | Matches spec §4, §5, §6a, §6b exactly |
| Brand styling | **Done** | Reuses existing `dark-section` / `light-section` / `cbgl-section` patterns, gold + CBGL blue tokens, Playfair + Inter + Montserrat |
| `noIndex` + sitemap exclusion + draft banner | **Done** | Triple-gated against accidental publication |
| JSON-LD schema (CollectionPage, Place, RealEstateAgent, FAQPage, BreadcrumbList) | **Done** | Per spec §13 |
| Hub FAQ (16 question stems) | **Done — answers FILL-IN** | Stems from spec §4. Ryan writes the answers. |
| 8 project pages | **Done — content FILL-IN** | 3 full template pages (Owen, Ritz-Carlton Residences, Rosewood Lido), 5 stubs (Amara, Edge, Gallery, Mira Mar, Six88) per spec §7 |
| IDX listing grid | **Stubbed** | 4 hardcoded mock listings per grid. Wire to `/idx-wrapper/` when ready — see "Wiring IDX" below. |
| Interactive map | **Stubbed** | Static SVG-style map with pin coordinates from `projects.json`. Swap to Mapbox later. |
| Market data KPI tiles | **Stubbed** | Hardcoded numbers. Wire to existing Supabase pipeline (`vw_market_stats_by_area`) when ready. |
| Market trend chart | **Stubbed** | Placeholder card. Drop in Chart.js or Recharts later. |
| Scheduler embed | **Stubbed** | Placeholder card with "wire your Calendly/Cal.com/TidyCal here" note. |
| Project images | **Placeholders** | `/images/new-construction/[slug]-hero.jpg` referenced. Per spec §11, every image needs full provenance metadata before publish. Owned shoots recommended for the 3 full-build projects. |

---

## What needs Ryan's input ("FILL-IN" markers)

Search the prototype for the string **`FILL_IN`** to find every blank. The big ones:

- `src/data/newconstruction/projects.json` — every project has `address`, `developer`, `architect`, `total_residences`, `floors`, `residence_types`, `price_range`, `sqft_range`, `estimated_completion`, `reservation_deposit_pct`, `hoa_fee_range`, `pet_policy`, `short_term_rental_policy`, `flood_zone`, `hurricane_impact`, `construction_type`, `mls_subdivision`, `developer_url`, `lat`, `lng` as `FILL_IN`. The 5 stubs only need address + price range to render usefully. The 3 full pages need all of it.
- `src/data/newconstruction/faq.json` — 16 hub FAQ answers (50–120 words each, in Ryan's voice per spec).
- Project editorial overviews (300–500 words) on the 3 full project pages — Ryan's voice. There's a `<!-- FILL_IN: editorial overview -->` marker in each.
- Per-island editorial paragraphs (250–400 words) on the Barrier Islands pillar — markers in `barrier-islands.astro`.
- Area pillar overviews (400–600 words) — markers in both pillar pages.
- Project FAQs (5–8 per project) — markers in projects.json.

---

## One open question for Ryan (spec §16, FILL IN #2)

The spec lists The Ritz-Carlton Residences twice — once as `the-ritz-carlton-residences-sarasota` (Downtown) and once as `…-longboat-key`. **The prototype currently treats it as Downtown** (Sarasota slug, area: downtown-sarasota). If it's actually the Longboat Key project, change in `projects.json`:
- `area` from `"downtown-sarasota"` to `"barrier-islands"`
- `island` from `null` to `"longboat-key"`
- slug consideration: rename file/key from `the-ritz-carlton-residences-sarasota` to `the-ritz-carlton-residences-longboat-key`

---

## Wiring IDX (when ready)

`IdxListingGrid.astro` accepts `subdivisions: string[]` and `island: string | null` props. Today it returns hardcoded mock data. To wire it to your existing IDX:

1. The site already has `/idx-wrapper/` (Astro page) and a Netlify proxy `/idx/* → adamsonfl.idxbroker.com`.
2. Replace the mock array in `IdxListingGrid.astro` with a fetch that filters Stellar MLS by `BuildingName` / `Subdivision` matching the project's `mls_subdivision` value.
3. Or render the IDX Broker dynamic widget inside the slot if you want IDX Broker's rendering instead of custom cards.

---

## Verification commands

```bash
cd C:\Users\Bones\automation\AG_website
npx astro check        # type-check Astro components
npm run build          # full build — confirm /new-construction/ pages compile
npm run dev            # local preview at http://localhost:4321/new-construction
```

After build, confirm `/new-construction/` URLs **do NOT** appear in `dist/sitemap-0.xml`.

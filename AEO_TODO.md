# AEO To-Do List — adamsonfl.com

> Generated from independent AEO audit on **2026-04-25**.
> Process for running future audits: see [AEO_AUDIT_PLAYBOOK.md](./AEO_AUDIT_PLAYBOOK.md).
> Update this file after each post-deploy audit — close completed items, add new findings.
>
> **Last audited: 2026-07-05 (BonesBot, quick post-deploy audit of `8952db1`). Overall grade: A−.**

---

## New findings — 2026-07-05 quick audit (post imagery + market-reports deploy)

> Quick post-deploy audit of `8952db1` (deploy `6a496307`): imagery fill (8 area photos, 4 specialties tiles, og-default, fallbacks), `/market-reports/` rebuild, new `/photo-credits`. All 12 checked pages return 200 with canonical, twitter card, parsing JSON-LD, zero placeholder leaks, zero `<!-- TODO -->` in production HTML; robots allow-list intact; llms.txt current; all three playbook query sims now ground with same-day (July 5) data. Grade holds **A−**.

- [ ] **🟡 `/market-reports/` schema is thin relative to its new content.** The rebuilt page has gold-standard *visible* freshness ("Latest data refresh: July 5, 2026") and 9 live per-area cards, but its JSON-LD is a bare `CollectionPage` — no machine-readable `dateModified` (wire from newest stats `lastUpdated`) and no `ItemList` of the 9 area reports. Cheap fix; mirrors what area pages already emit.
- [ ] **🟢 Swap CC stock photography for Ryan's own photos as they become available.** The 8 area photos + 4 specialties tiles shipped 2026-07-04 are licensed Wikimedia Commons images, attributed on `/photo-credits` (footer-linked — that page must stay while the images remain). Authentic drone/listing/neighborhood photography at the same file paths is the authenticity upgrade; prune `/photo-credits` entries as swapped.

---

## New findings — 2026-06-30 audit (post LBK market-FAQ deploy)

> Cold audit via cache-proof deploy permalink (deploy `6a43dadd`, commit `01940d30`). Overall grade **A−**. Area pages are A-grade, gold-standard citable assets; remaining gaps are the `/market-reports/` stub, the shared OG image, a missing `aggregateRating`, and the thin `/about/` bio.

- [ ] **🟡 Add `aggregateRating` to the `RealEstateAgent` schema (homepage + `/about/`).** Both pages show a visible "5.0 · 25 reviews" block, but neither `RealEstateAgent` JSON-LD node carries `aggregateRating`. Free AEO / rich-result win, and the single fix that pushes the "who is the top barrier-island agent?" query from PARTIAL to full grounding — an engine could cite a corroborated rating instead of a self-asserted superlative. Wire `aggregateRating` (ratingValue 5.0, reviewCount 25, bestRating 5) aligned with the visible block. (Data already on file: 5.0★/25 Google reviews.)
- [ ] **🟢 Sitemap emits both `/srq-map/` and `/SRQmap/`** — case-duplicate of the same map page (Netlify lowercases URLs, so the mixed-case entry is a dupe). De-dupe so only the canonical lowercase URL is in the sitemap.
- [ ] **🟢 robots.txt — optionally add the 4 newer AI agents** (OAI-SearchBot, Applebot-Extended, Amazonbot, Meta-ExternalAgent). Already crawled under `User-agent: *`, but explicit listing matches the file's existing convention.
- [x] **~~🟡 "Data as of" / freshness date for AEO strength — CONFIRMED HANDLED on the data pages.~~** ✅ Verified 2026-06-30. Longboat Key exposes freshness to BOTH the reader ("Last updated June 30, 2026", "Data through June 30, 2026", and "As of June 30, 2026…" inside the cost FAQ answer) AND the crawler (`dateModified`, re-stamped daily, on the `Dataset` JSON-LD nodes). This is the 2026 AEO gold standard (visible date + aligned schema `dateModified`; pages refreshed within ~6 months earn the large majority of AI citations). No action needed on area pages. Replicate the visible-date + `dateModified` pattern when `/market-reports/` and the static About/Contact pages get dated content.

---

## New findings — 2026-06-06 audit (do these first)

- [x] **~~🔴 Homepage + Contact serve a STALE area set — fix and rebuild.~~** ✅ **RESOLVED (verified 2026-06-12).** Verified against the unique deploy permalink (cache-proof): homepage renders all 9 area cards with current names and live median prices. The 2026-06-06 'stale' view was almost certainly Netlify CDN / fetcher cache — `web_fetch` still served week-old homepage HTML on 2026-06-12 while Chrome and the deploy permalink showed current content. **Audit rule going forward: verify via the deploy permalink URL, never a cached fetch.**
  Every page EXCEPT the homepage and `/contact/` shows the current footer/area list (Downtown, West of Trail ×3, Longboat, St. Armands and Lido, Siesta, Bird Key). The **homepage and contact page still show the OLD list** (separate "Lido Key" + "St. Armands" with pre-merge slugs). Worse, the homepage **"Areas We Serve" section renders only ONE card** — "Lido Key" with broken draft copy ("powder sand beaches steps fine dining and shopping") — instead of the 9 areas in `areas.json`. The homepage is the entity anchor an AI lands on first; right now it looks half-built. Likely a stale CDN cache or a page that didn't rebuild. **Action:** trigger a clean Netlify rebuild + cache purge, then re-fetch `/` and `/contact/` to confirm they match the rest of the site; if still wrong, the homepage `AreaCard` data source needs fixing.

- [x] **~~🔴 Stale hardcoded numbers in area-page FAQ prose contradict the live MLS tables.~~** ✅ **DONE 2026-06-12 (option a, permanent fix).** `areas.json` FAQ answers now embed `{{stats}}` placeholders (e.g. `{{active.medianPrice}}`, `{{asOf}}`) that `[slug].astro` resolves from the daily-refreshed `<slug>-stats.json` at build time. Since the daily stats commit triggers a Netlify rebuild, FAQ numbers re-sync with the tables every day automatically. FAQs with unresolvable tokens are suppressed rather than rendered with gaps. 26 answers across 9 areas converted; point-in-time facts (e.g. record sales, comps) re-anchored with explicit dates so they stay permanently true.
  Example: Longboat Key's first FAQ answer says "the median home price on Longboat Key is approximately **$1,250,000** … year-over-year increase of about 4.2%" while the live table on the same page shows **$1,073,750 median sold / $1,095,000 median list**, updated June 6 2026. An AI engine may quote the stale FAQ figure. Audit all area-page FAQ answers (these come from `areas.json` `faqs[]`) and either (a) wire the numbers from the live stats JSON or (b) restate them as undated ranges so they don't go stale.

- [x] **~~🟡 `llms.txt` links a dead page and omits a live one.~~** ✅ **DONE 2026-06-12.** Regenerated: dead `/areas/sarasota` removed; added Downtown Sarasota, Palmer Ranch, the three `/new-construction/` pages, and `/find-my-dream-home`; intro now carries license + CWS credential and documents the daily MLS refresh + PostGIS verification. (Build-time auto-generation from `areas.json` remains a nice-to-have.)
  It points crawlers to `https://adamsonfl.com/areas/sarasota` (returns empty/404 — no `sarasota` slug exists) and **omits Palmer Ranch** (which is live). Regenerate `llms.txt` from `areas.json` so the page list always matches reality. Consider auto-generating it at build time.

- [x] **~~🟢 `/areas/` hub shows "From TBD" for the three West of Trail pages~~** ✅ **DONE 2026-06-12.** Homepage and `/areas/` cards now read `active.medianPrice` from the daily stats JSONs (label changed "From" → "Median" to match what is shown). West of Trail North (`status: no_data`) gracefully omits its price line. Original finding:, even though those pages now carry live median data (e.g. West of Trail median list $2,795,000, updated May 20). The hub "From" price reads `areas.json marketStats.medianPrice` ("TBD"); wire it from the live `<slug>-stats.json` instead.

---

## Priority 1 — Highest AEO impact

- [ ] **Build `/market-reports/` as a luxury-buyer hub targeting $900k+ search intent.**
  **MATERIALLY ADVANCED 2026-07-04 (commit `8952db1`) — the "Coming Soon" stub is GONE.** `/market-reports/` now renders live per-area report cards for all 9 areas (median active price, median $/sq ft, active count, visible "Latest data refresh" date), driven by the daily `*-stats.json` pipeline — no hand-entered numbers. Verified live 2026-07-05: the broad "what's the Sarasota market doing?" query now grounds with same-day data. **Still open:** the full hub spec below — cross-area $900k+ summary, insurance/hurricane reality, tax mechanics, comparison content, monthly narrative, pulse-page fan-out.
  *(2026-06-06 status, superseded: page was literally still "Coming Soon" in production — then the single biggest gap.)*
  *(Full strategic spec retained below from 2026-04-25.)*

  **Target buyer:** $900k+ buyers searching Downtown Sarasota, Lido Key, Siesta Key, Longboat Key, and Sarasota mainland in zips 34239 (West of Trail / Southside / Harbor Acres / Cherokee Park) and 34231 (Oyster Bay / Gulf Gate / South Trail luxury pockets). Three personas: out-of-state relocator (biggest cohort post-2024), move-up local, second-home buyer comparing Sarasota vs Naples/Charleston/Hilton Head.

  **Architecture:** Don't build one page — build a hub that fans out into pulse pages. Hub shows cross-area summary at the $900k+ filter; each pulse page is a deep, dated, sourced market dashboard structured around the actual questions luxury buyers type into AI.

  **Question hierarchy each pulse page must answer (order matters):**
  1. *"Where am I in the cycle?"* — list-to-sale ratio, YoY/2yr/peak comparisons, charts or `Dataset` schema with dated quarterly points.
  2. *"What does $900k / $1.5M / $3M+ actually buy here?"* — 3–5 representative recent sold comps per band. (NOTE: the area pages already do this well now — reuse that component.)
  3. *"Insurance + hurricane reality"* — flood zone (AE/VE/X), 2026 insurance ranges, post-Helene/Milton behavior. Cite FEMA, Citizens, FloodFactor. Biggest AEO arbitrage — competitors duck it.
  4. *"New construction tracker"* — The Owen, The Edge, Ritz-Carlton Residences, Epoch, Rosewood, etc. (Note: a `/new-construction/` section now exists in the repo — wire it in.)
  5. *"Lifestyle / comparison"* — explicit "Lido vs Longboat," "34239 vs Bird Key vs Lakewood Ranch."
  6. *"Financial mechanics"* — property tax on $1.5M with current millage, homestead, Save Our Homes, CDD/HOA ranges.

  **Don'ts:** no generic "Sarasota market overview" prose; not a blog; not gated; no rental/vacation data.
  **Freshness:** monthly minimum; `dateModified` machine-readable in JSON-LD.

- [x] **~~Bring all five remaining area pages to Longboat Key parity.~~** ✅ **DONE / EXCEEDED (verified 2026-06-06).**
  Area pages are now the strongest AEO asset on the site. Live, dated, MLS-sourced pages with sold/pending snapshot, active inventory, price bands, recent sold comps (address/bd/ba/sqft/built/date), typical monthly costs, FAQ (dual microdata + `FAQPage` JSON-LD), "last updated" date, and Stellar MLS attribution now exist for: **Longboat Key, St. Armands and Lido, Siesta Key, Downtown Sarasota, Bird Key, Palmer Ranch, West of Trail (Core/North/South)**. The original "sarasota / lido-key / st-armands" pages were superseded by the merge to `st-armands-lido` and the area expansion. *(See "Active Condos by Construction Era" note in audit history.)*

- [ ] **Replace the placeholder bio in `/about/` with Ryan's real bio.**
  **PARTIAL as of 2026-07-05 — the `<!-- TODO -->` comment is no longer in `src/pages/about.astro`, and the page carries strong E-E-A-T schema (license, phone, CWS credential, 9-profile sameAs).** The bio is generic marketing prose with zero citable specifics (no years in business, no transaction volume, no specializations beyond "waterfront"). Get Ryan's real bio.

- [x] **~~Strengthen E-E-A-T signals in Ryan's `RealEstateAgent` schema.~~** ✅ **DONE (verified live 2026-06-12).** Homepage + `/about/` schema now carry `telephone`, FL license SL3457783 (`identifier`, plus visible text on About), CWS `hasCredential`, and a 9-profile `sameAs` (Google, Facebook, cbmoxi, Zillow, coldwellbankerhomes, coldwellbanker.com, CB Global Luxury, homes.com, adamson-group.com — all URL-verified 2026-06-12). Schema `image` URLs made absolute. Remaining nice-to-have: years of experience / production volume. Original ask:
  **(2026-06-06 status, superseded):** Homepage schema has `telephone: ''` (literally empty) and no `sameAs`; `/about/` `RealEstateAgent` node has no telephone, no license, no `sameAs`. Add:
  - `telephone` (visible + schema)
  - Florida real estate license number (visible text + schema)
  - `sameAs`: LinkedIn, Realtor.com, Zillow, Coldwell Banker agent page
  - Years of experience / year started
  - Defensible awards / production volume
  This is why "who is the top agent on the barrier islands?" grounds only weakly — there's no third-party corroboration for an AI to lean on.

- [ ] **Integrate Mapme map UX from SRQmap.com to humanize the geography for out-of-state buyers.**
  *(No map detected on live pages as of 2026-06-06 — still open. Full spec retained from 2026-04-25.)*
  **Core rule (non-negotiable):** Map is a presentation layer, not a content layer. AI crawlers cannot read iframe content, and srqmap.com is blocked from AI bots via Cloudflare robots.txt. Therefore every POI/label/blurb inside the map MUST also exist as plain HTML + JSON-LD (`Place`/`Restaurant`/`School`/`LandmarksOrHistoricalBuildings`) on the parent Astro page. Placements in priority order: (1) `/areas/` hub orientation map, (2) per-area maps on each pulse page, (3) optional `/discover/` guided tour. Use Astro client-only island, lazy-load below fold, Lighthouse before/after, test brand-chrome fit (fallback: native MapLibre/Mapbox GL).

---

## Priority 2 — High-leverage additions

- [ ] **Add a homepage FAQ block with `FAQPage` JSON-LD.** STILL OPEN — homepage has no FAQ. The `FAQSchema.astro` component already emits correct dual markup; just feed it 4–6 cross-cutting questions: "Who is Ryan Adamson?", "What areas does the Adamson Group cover?", "Where is Ryan's office?", "What's the Sarasota luxury market doing in 2026?", "How do I contact Ryan?", "Difference between Lido, Longboat, and Siesta?"

- [ ] **Add an "at a glance" data block to the homepage below the fold.** STILL OPEN. The homepage currently carries ZERO citable facts — it's all marketing prose ("Real-time data", "Deep knowledge"). Add 4–6 factual sentences with current numbers + a "last updated" date so the homepage has something to be cited for.

- [x] **~~Create `llms.txt` at site root.~~** ✅ **DONE — exists and is well-structured.** *(But has stale content — see New Findings 🟡 above: dead `/areas/sarasota` link + missing Palmer Ranch.)*

- [x] **~~Add `datePublished` and `dateModified` to all `WebPage` / `ProfilePage` JSON-LD nodes.~~** ✅ **DONE for area pages 2026-06-12** — `WebPage` nodes now emit `dateModified` from the pipeline `lastUpdated` (machine-readable freshness, re-stamped daily). `datePublished` deliberately omitted on area pages: wiring it to `lastUpdated` would falsely move the publish date daily. Market-data `Dataset` nodes already carried `dateModified`. Still open for static pages (About/Contact) if ever worth it.
  STILL OPEN. Area pages show a visible "Last updated" date and the FAQ/Dataset schema is rich, but the top-level `WebPage` JSON-LD node still has no machine-readable `dateModified`, and `/about/`'s `ProfilePage` has none. Wire `lastUpdated` from the stats JSON into the page schema at build time.

---

## Priority 3 — Polish & technical hygiene

- [ ] **Per-page Open Graph images.** STILL OPEN but UNBLOCKED 2026-07-04: `/images/og-default.jpg` previously did not exist on disk (every social share site-wide rendered a broken preview); a branded default (AG logo over the Sarasota bayfront, 1200×630) now serves 200. Next step is now cheap: every area has a hero at `/images/areas/<slug>.jpg` to compose per-area OG images with the area name baked in.

- [x] **~~Fix Lido Key homepage card copy.~~** ✅ **RESOLVED (verified live 2026-07-05).** The broken pre-merge copy is gone; all 9 cards render current names, clean taglines, live medians — and, as of `8952db1`, photos (8 cards previously rendered as empty charcoal blocks because their images did not exist).

- [x] **~~Fix duplicate `invert` class on the Adamson Group logo `<img>`.~~** ✅ **DONE 2026-06-12** — redundant `invert brightness-0 invert` utilities removed; the inline `filter` style already handles inversion.

- [ ] **Strengthen H1/H2 entity statements.** STILL OPEN. Homepage H1 is the tagline "Luxury Real Estate on Sarasota's Barrier Islands"; add a visible H2 like "Ryan Adamson — Coldwell Banker Realty, St. Armands Circle" so the entity is in headline text, not just JSON-LD. Same on `/about/` (H1 is just "Ryan Adamson" with no headline-level credential/entity line).

- [ ] **Audit `alt` attributes site-wide.** Not re-verified this cycle.

- [x] **~~Add `BreadcrumbList` schema to area pages.~~** ✅ **DONE 2026-06-12** — `[slug].astro` now emits Home → Areas → <Area> `BreadcrumbList` in the JSON-LD graph (verified live on Longboat Key).

---

## Standing items (do every release)

- [ ] **Run AEO_AUDIT_PLAYBOOK.md after every Netlify deploy.** ✅ Ran 2026-06-06.

- [x] **Re-verify AI-bot allow-list in `robots.txt`.** ✅ Confirmed 2026-06-06 — `User-agent: *` allowed plus explicit Allow for GPTBot, Google-Extended, anthropic-ai, ClaudeBot, PerplexityBot, Bytespider, CCBot. Sitemap referenced. *(Optional enhancement: add OAI-SearchBot, Applebot-Extended, Amazonbot, Meta-ExternalAgent.)*

---

## Audit history

| Date | Auditor | Grade | New findings | Closed |
|------|---------|-------|--------------|--------|
| 2026-04-25 | BonesBot (initial audit) | B- | 14 items above | — |
| 2026-04-25 | BonesBot (strategy session) | — | P1#1 rewritten with luxury-buyer hub direction + 6-area architecture | — |
| 2026-04-25 | BonesBot (strategy session) | — | Added P1#5: Mapme map UX integration with HTML+schema duplication rule | — |
| 2026-06-06 | BonesBot (post-deploy audit) | B | 4 (stale homepage/contact; stale FAQ numbers vs live tables; llms.txt dead link + missing Palmer Ranch; areas-hub "From TBD" for WoT) | 2 (area-page parity exceeded; llms.txt created) |
| 2026-06-12 | BonesBot (low-hanging-fruit sprint + post-deploy verification) | B+ | 1 (cached fetches can masquerade as stale pages — audit via deploy permalink) | 8 (FAQ↔stats interpolation system; card medians from stats / From-TBD; llms.txt regen; E-E-A-T schema verified + sameAs ×9; dateModified on area WebPage; BreadcrumbList on area pages; absolute og:image; duplicate invert) |
| 2026-06-30 | BonesBot (post LBK market-FAQ deploy audit) | A− | 2 (no `aggregateRating` despite visible 5.0/25 reviews; sitemap `/srq-map/` vs `/SRQmap/` case-dupe) | 0 (LBK FAQ consolidation + freshness verified; "data as of" question confirmed handled) |
| 2026-07-05 | BonesBot (quick post-deploy audit of `8952db1`) | A− | 2 (`/market-reports/` schema thin — no dateModified/ItemList; CC stock photos → replace with Ryan's photography over time) | 2 (market-reports "Coming Soon" stub → live per-area data cards; Lido card copy) — plus og-default 404 fixed, all missing imagery filled, About TODO comment gone |

> **2026-07-05 deploy context:** Deploy `6a496307` (commit `8952db1`) filled every missing image on the site — 8 area card/hero photos (Wikimedia Commons CC, attributed on new `/photo-credits`), 4 homepage specialties tiles, branded `og-default.jpg` (previously a 404 → broken social previews site-wide), and both fallback images — and replaced the `/market-reports/` "Coming Soon" stub with live per-area report cards driven by the daily stats JSONs. Query sims: LBK median grounds ($1,187,500, "updated July 5, 2026"); agent identity grounds (license + sameAs ×9; still no `aggregateRating` — see 06-30 finding); current-market grounds on /market-reports with same-day medians for 9 areas. Grade holds **A−**; remaining gaps to A: homepage FAQ + at-a-glance citable facts, `aggregateRating`, market-reports hub content + schema depth, per-area OG images, real bio specifics.
>
> **2026-06-30 deploy context:** Deploy `6a43dadd` (commit `01940d30`, published in 16s; only `areas/longboat-key/index.html` changed) shipped the per-area market-FAQ registry (`AREA_MARKET_FAQ` in `scripts/fetch_area_summary.py`). Longboat Key now LEADS its FAQ with a consolidated, trailing-90-day **"What do properties cost on Longboat Key?"** answer — condo vs SFH by median + $/sqft, beachfront vs bayside by mix-robust $/sqft (per-location median price deliberately omitted because the buckets mix property types), closed by a valuation-nuance line pointing to Ryan. Retired: the granular beachfront-premium / SFH-vs-condo / price-range market Qs and the editorial "best neighborhoods" Q; buyer/seller Q renamed "Is it a good time to buy on Longboat Key?". Other 8 area pages untouched (safe-default registry). Grade up to **A−**: area pages are A-grade citable assets with gold-standard visible+schema freshness; held off a full A by (1) `/market-reports/` still a "Coming Soon" stub — no consolidated month/quarter narrative for the "what's the Sarasota luxury market doing?" query; (2) one shared `og-default.jpg` across all 9 pages; (3) thin `/about/` bio (TODO comment still open); (4) missing `aggregateRating` despite a visible 5.0/25-review block.

> **2026-06-06 deploy context:** Removed the "Active Condos by Construction Era" table from Palmer Ranch (Bird Key was already empty). That table now renders only on Downtown Sarasota, Longboat Key, Siesta Key, and St. Armands and Lido — per Ryan's instruction.
>
> **2026-06-12 deploy context:** 10 commits via Contents API (deploy `6a2bfe7e`, commit `3e97e46`). Headline change: FAQ answers in `areas.json` are now templates resolved against the daily pipeline stats at build time — on-page numbers can no longer contradict the market tables. Verified live via deploy permalink: 0 unresolved tokens, FAQ cites $1,097,000 / June 12 matching the Longboat table, breadcrumbs + `dateModified: 2026-06-12` in the graph, og:image absolute, all 9 homepage cards showing live medians. Grade to **B+**: homepage still lacks FAQ/at-a-glance citable facts, `/market-reports/` still "Coming Soon", bio still thin — those are the remaining gaps to A.
>
> **2026-06-06 grade rationale:** Area pages are A-grade, highly citable AEO assets (dated, MLS-sourced, sold comps, dual-markup FAQs) — a big jump from 2026-04-25 when only Longboat had data. Held to **B** overall by: (1) homepage is the weakest page yet the most-landed-on — stale area list + single broken card + zero citable facts + empty `telephone`; (2) `/market-reports/` still "Coming Soon"; (3) thin agent E-E-A-T (no license/phone/sameAs, placeholder bio); (4) stale FAQ numbers that contradict the live tables.

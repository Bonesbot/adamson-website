# AEO To-Do List — adamsonfl.com

> Generated from independent AEO audit on **2026-04-25**.
> Process for running future audits: see [AEO_AUDIT_PLAYBOOK.md](./AEO_AUDIT_PLAYBOOK.md).
> Update this file after each post-deploy audit — close completed items, add new findings.

---

## Priority 1 — Highest AEO impact (do these first)

- [ ] **Build `/market-reports/` as a luxury-buyer hub targeting $900k+ search intent.**
  *(Strategic direction set 2026-04-25 — supersedes the original "fill in Coming Soon" framing.)*

  **Target buyer:** $900k+ buyers searching Downtown Sarasota, Lido Key, Siesta Key, Longboat Key, and Sarasota mainland in zips 34239 (West of Trail / Southside / Harbor Acres / Cherokee Park) and 34231 (Oyster Bay / Gulf Gate / South Trail luxury pockets). Three personas: out-of-state relocator (biggest cohort post-2024), move-up local, second-home buyer comparing Sarasota vs Naples/Charleston/Hilton Head.

  **Architecture:** Don't build one page — build a hub that fans out into six pulse pages (Downtown Sarasota, Lido Key, Siesta Key, Longboat Key, 34239, 34231). Hub shows cross-area summary at the $900k+ filter; each pulse page is a deep, dated, sourced market dashboard structured around the actual questions luxury buyers type into AI. Keep 34239 and 34231 as separate pages — their buyers, school districts, and value propositions differ enough that merging dilutes entity match.

  **Question hierarchy each pulse page must answer (order matters):**
  1. *"Where am I in the cycle?"* — list-to-sale ratio, YoY/2yr/peak comparisons, charts or `Dataset` schema with dated quarterly points. Not "the market is strong" prose.
  2. *"What does $900k / $1.5M / $3M+ actually buy here?"* — 3–5 representative recent sold comps per band per page, with bed/bath/sqft/waterfront. Sold comps with dates are the highest-citation-value content type that exists.
  3. *"Insurance + hurricane reality"* — sober factual block per coastal page: flood zone (AE vs VE vs X), 2026 insurance cost ranges, post-Helene/Milton market behavior, elevation/storm-surge facts. Cite FEMA, Citizens, FloodFactor. Honesty here is the single biggest AEO arbitrage opportunity — most competitors duck this question.
  4. *"New construction tracker"* — current list with status: The Owen, The Edge, Ritz-Carlton Residences, Epoch, Rosewood, etc. for downtown; teardowns/permits/builder activity on the islands. Updated monthly. Highest-intent, lowest-supply content category in the Sarasota luxury market.
  5. *"Lifestyle / comparison"* — explicit "Lido Key vs Longboat Key," "34239 vs Bird Key vs Lakewood Ranch" comparisons. Maps 1:1 to AI queries and gives interlink fuel.
  6. *"Financial mechanics"* — property tax on $1.5M with current millage cited, homestead exemption, Save Our Homes cap, CDD/HOA ranges.

  **Don'ts:** no generic "Sarasota market overview" (that battle is already lost to Zillow/Redfin); not a blog; not gated; no rental/vacation data mixed in (different buyer, dilutes signal).

  **Freshness mechanic:** monthly updates minimum. `dateModified` must be machine-readable in JSON-LD, not just visible text. Wire `lastUpdated` from the MLS pipeline into the schema at build time.

  **Ship-first target (this quarter):** the **Downtown Sarasota pulse page**, fully fleshed out — sold comps in three price bands, new construction tracker, insurance/elevation block, three FAQ entries ("is it a good time to buy downtown Sarasota?" / "what's the price per sqft for luxury condos downtown?" / "what new condos are launching in 2026?"). Use it as the template for the other five.

  *Blocked by:* MLS pipeline → Supabase → per-area JSON reaching this page. New construction tracker may need a manual data source until automated.

- [ ] **Bring all five remaining area pages to Longboat Key parity.**
  Pages affected: `/areas/sarasota/`, `/areas/lido-key/`, `/areas/siesta-key/`, `/areas/st-armands/`, `/areas/bird-key/`.
  Each needs: stat grid (median, $/sqft, DOM, active, sold-90d, YoY%), 3-question FAQ block with both microdata and JSON-LD `FAQPage`, "last updated" date, Stellar MLS attribution.
  *Pattern:* See area page rollout — draw polygon → fetch_area_stats.py → commit `<slug>-stats.json` → Netlify rebuild.

- [ ] **Replace the `<!-- TODO: Replace with Ryan's actual bio copy -->` comment in `/about/` with real bio.**
  This comment is in production HTML right now. Get Ryan's actual bio.

- [ ] **Strengthen E-E-A-T signals in Ryan's `RealEstateAgent` schema.**
  Currently empty `telephone`, no license number, no `sameAs` links. Add:
  - `telephone`
  - Florida real estate license number (in visible text + schema)
  - `sameAs`: LinkedIn, Realtor.com profile, Zillow profile, Coldwell Banker agent page
  - Years of experience or year started in real estate
  - Any awards / production volume claim that's defensible

- [ ] **Integrate Mapme map UX from SRQmap.com to humanize the geography for out-of-state buyers.**
  *(Strategic direction set 2026-04-25.)*

  **Why:** Luxury buyers in Connecticut/California cannot intuit from text alone how Lido sits relative to Longboat, or that 34239 is a 12-minute drive from St. Armands. A map closes that gap instantly. SRQmap.com is BonesBot's existing pet project built on Mapme — Ryan can edit POIs himself, no-code.

  **Core rule (non-negotiable):** Map is a presentation layer, not a content layer. AI crawlers cannot read iframe content, and Mapme content served from `srqmap.com` is blocked from every AI bot by Cloudflare's managed robots.txt (`ClaudeBot`, `GPTBot`, `Google-Extended`, `Applebot-Extended`, `Bytespider`, `CCBot` all disallowed). Therefore: **every POI description, area label, marker caption, or lifestyle blurb that lives inside the map MUST also exist as plain HTML on the parent Astro page.** The map gives humans the visual story; the HTML gives AI engines the citable story. Duplication is intentional.

  **Three placements (in priority order):**
  1. **Site-wide orientation map on `/areas/` hub** — all six target areas (Downtown, Lido, Siesta, Longboat, 34239, 34231) with hover popovers and links to pulse pages. Highest-impact placement; serves the "give me a sense of the geography" need.
  2. **Per-area maps embedded into each pulse page** — zoomed in, pinned with new-construction projects, restaurants, beach access, marinas, top schools, landmarks. Directly serves the "what's it like to live here" question driving the $900k+ buyer.
  3. **Optional guided-tour `/discover/` landing page** — 10-minute Sarasota walkthrough for the visitor who hasn't picked an area yet. Each step funnels into a pulse page. Save for last; most fun, least immediately commercial.

  **Schema opportunity (the move nobody else makes):** Every POI pinned on the map should also exist as a `Place` / `Restaurant` / `School` / `LandmarksOrHistoricalBuildings` entity in JSON-LD on the page. Same content, dual audience: AI engines pick up the schema; humans see the map.

  **Implementation notes:**
  - Use Astro's client-only island pattern so Mapme JS hydrates after static HTML ships to crawlers.
  - Lazy-load below the fold; Mapme iframe can drag chunky JS, third-party fonts, tracking.
  - Lighthouse before/after on a pulse page once one is embedded.
  - Test brand-chrome conflict early — Mapme's default UI may not blend with Coldwell Banker palette + Playfair Display. If white-labeling is too limited, consider going native (MapLibre / Mapbox GL JS) — loses no-code editing, gains full visual control.

  **Ship-first target:** the `/areas/` hub orientation map as a single proof point. Validate page load speed, brand fit, and the HTML+schema duplication build pattern. Once solid, roll out to the six pulse pages. Guided tour last.

---

## Priority 2 — High-leverage additions

- [ ] **Add a homepage FAQ block with `FAQPage` JSON-LD.**
  4–6 cross-cutting questions:
  - "Who is Ryan Adamson?"
  - "What areas does the Adamson Group cover?"
  - "Where is Ryan's office?"
  - "What's the Sarasota luxury market doing in 2026?"
  - "How do I contact Ryan Adamson?"
  - "What's the difference between Lido Key, Longboat Key, and Siesta Key?"

- [ ] **Add an "at a glance" data block to the homepage below the fold.**
  4–6 factual sentences with current numbers and a "last updated" date. Gives the homepage *something* to be cited for.

- [ ] **Create `llms.txt` at site root.**
  Curated map of the site's important content for AI crawlers — paralleling robots.txt. Should reference area pages, market reports, about page, and a one-paragraph site summary.

- [ ] **Add `datePublished` and `dateModified` to all `WebPage` JSON-LD nodes.**
  Visible "last updated" text exists on Longboat Key but isn't in the schema. Freshness needs to be machine-readable. Wire this into the area-page generator so it picks up the JSON file's mtime or a `lastUpdated` field.

---

## Priority 3 — Polish & technical hygiene

- [ ] **Per-page Open Graph images.**
  All pages currently share `/images/og-default.jpg`. At minimum, give each area page its own OG image with the area name baked in.

- [ ] **Fix Lido Key homepage card copy.**
  Current text: "Lido Key - powder sand beaches steps fine dining and shopping" — reads like incomplete draft copy (missing words/punctuation).

- [ ] **Fix duplicate `invert` class on the Adamson Group logo `<img>`.**
  In the header: `class="h-12 w-auto invert brightness-0 invert"` — `invert` appears twice. Cosmetic but sloppy.

- [ ] **Strengthen H1/H2 entity statements.**
  Hero H1 is a tagline ("Luxury Real Estate on Sarasota's Barrier Islands"). Consider an additional visible H2 like "Ryan Adamson — Coldwell Banker Realty, St. Armands Circle" so the entity is in headline-level text, not just JSON-LD.

- [ ] **Audit `alt` attributes site-wide.**
  Several decorative-only alts spotted; ensure every meaningful image has descriptive alt text (helps both AEO and accessibility).

- [ ] **Add `BreadcrumbList` schema to area pages.**
  Site → Areas → Longboat Key. Improves how AI assistants describe site structure.

---

## Standing items (do every release)

- [ ] **Run AEO_AUDIT_PLAYBOOK.md after every Netlify deploy.**
  Compare results against this TODO file. Close items as they ship; log any new findings.

- [ ] **Re-verify AI-bot allow-list in `robots.txt` after any robots.txt change.**
  Currently allow-lists GPTBot, ClaudeBot, anthropic-ai, PerplexityBot, Google-Extended, Bytespider, CCBot. Don't lose this.

---

## Audit history

| Date | Auditor | Grade | New findings | Closed |
|------|---------|-------|--------------|--------|
| 2026-04-25 | BonesBot (initial audit) | B- | 14 items above | — |
| 2026-04-25 | BonesBot (strategy session) | — | P1#1 rewritten with luxury-buyer hub direction + 6-area architecture | — |
| 2026-04-25 | BonesBot (strategy session) | — | Added P1#5: Mapme map UX integration with HTML+schema duplication rule | — |

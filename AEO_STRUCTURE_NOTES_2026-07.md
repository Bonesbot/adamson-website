# AEO Structure Pass — July 1, 2026 (overnight build)

Quick structural audit alongside the New Construction + Buyer's Guide launch.
Reconcile against AEO_TODO.md; run AEO_AUDIT_PLAYBOOK.md cold after this deploy.

## Shipped tonight (AEO-relevant)

1. **/new-construction de-drafted and indexed.** noIndex removed from hub, both
   pillars, and all 8 project pages. Each project page now carries a real
   editorial answer block, date-stamped FAQPage schema, Place + BreadcrumbList,
   and a filled QuickFacts entity panel (developer, architect, pricing,
   completion). The comparison table is populated — AI engines lift tables.
2. **16-question hub FAQ** written to stand alone when quoted (deposit law,
   escrow via FS 718.202, SB 4-D reserves, flood zones, tax mechanics).
3. **/buyers-guide launched** with FAQPage + ItemList schema, crawlable
   methodology prose, and per-area entity links. The quiz itself is JS, but all
   nine area tiles + live stats render statically — nothing content-critical is
   client-only.
4. **llms.txt expanded**: buyers-guide, all 8 project URLs, srqmap.
5. **Header nav** now exposes New Construction + Buyer's Guide site-wide
   (internal-link equity + crawl discovery).
6. **Live-data provenance lines** ("Stellar MLS via Adamson Group data
   pipeline, as of <date>") on KPI blocks — freshness signals engines reward.

## Structural gaps to address next (priority order)

1. **Cross-linking mesh, areas ↔ new-construction ↔ buyers-guide.** Area pages
   (/areas/[slug]) don't yet link to matching new-construction projects or the
   Buyer's Guide. Add a "New construction in <area>" block to the area template
   fed from projects.json (match on area/island), and a Buyer's Guide CTA.
   This is the single highest-value internal-linking win available.
2. **Sitemap lastmod.** @astrojs/sitemap emits no <lastmod>. Set serialize()
   in astro.config to stamp stats-driven pages with the pipeline lastUpdated
   date — freshness signal for retrieval engines at near-zero cost.
3. **Project-page speakable + Offer caution.** Consider schema.org speakable on
   editorial_overview. Do NOT add Offer/price schema on projects — prices are
   "from" ranges sourced from developers; keep prices in FAQ text where they're
   date-stamped prose, not structured commitments.
4. **Entity page for Ryan.** /about should carry full RealEstateAgent schema w/
   license SL3457783, sameAs profile set, and review markup (5.0★/25 reviews)
   per the E-E-A-T asset list — currently only the NC hub emits agent schema.
5. **Stats freshness on buyers-guide.** Page bakes stats at build; publish
   throttle means up to ~3 days lag. Acceptable — the as-of date is printed.
   If throttle lengthens, consider a small client-side fetch of lastUpdated.
6. **Netlify forms check.** Two new forms (buyers-guide-match; existing
   new-construction-vip now on indexed pages). Verify they appear in Netlify
   Forms after this deploy and notifications route to Ryan.
7. **Renderings provenance.** All project imagery is developer renderings with
   visible "Courtesy of <developer>" credits (hero overlay + card chip + JSON
   image_credit). When buildings complete, replace with owned photography and
   add ImageObject schema with creditText at that point.

## Watchouts

- projects.json is now hand-curated live data (not pipeline-generated). Prices/
  statuses are date-stamped 2026-07-01; set a monthly re-verify reminder.
- The map components load Leaflet from cdnjs on 4 pages; if CSP is ever added,
  allow cdnjs + basemaps.cartocdn.com.
- lido-key/st-armands are retired slugs — new pages only reference
  st-armands-lido. Buyer's Guide traits keyed to areas.json slugs.

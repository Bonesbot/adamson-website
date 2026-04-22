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
| **Data Warehouse** | Google BigQuery | MLS extract pipeline already in progress. Build-time queries → JSON → Astro pages |
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

```
Stellar MLS → [Manual/Automated Export] → Google BigQuery
                                              ↓
                                    Build-time Node script
                                              ↓
                                    JSON data files in /src/data/
                                              ↓
                                    Astro pages consume JSON at build
                                              ↓
                                    Static HTML with real market data
```

### BigQuery Tables (Expected)
- `listings_active` — Current active listings
- `listings_sold` — Recently sold (comps, trends)
- `market_stats` — Aggregated stats by area/month (median price, DOM, inventory, volume)

### Build-Time Data Flow
1. `scripts/fetch-market-data.ts` — Queries BigQuery, writes JSON to `src/data/`
2. Astro pages import JSON and render at build time
3. Netlify scheduled builds (daily or weekly) keep data fresh

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
- [ ] Set up Sanity Studio
- [ ] Define content schemas (areas, reports, pages)
- [ ] Migrate static content to Sanity
- [ ] Webhook-triggered builds on content change

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
- **Next**: Get logos/video/images from existing site, npm install + local dev server, connect BigQuery pipeline

# AEO Audit Playbook — adamsonfl.com

> **Purpose:** A repeatable, deploy-triggered AEO audit. Any Claude session can run this playbook from scratch and produce comparable findings.
> **When to run:** After every Netlify deploy that changes public-facing content, schema, robots/sitemaps, or page templates.
> **Output:** Update `AEO_TODO.md` — close shipped items, log new findings in the audit history table.

---

## Mental framing — run this audit AS A FRESH AGENT

The whole point of this audit is to simulate what happens when an AI answer engine (Perplexity, ChatGPT, Google AI Overviews, Claude, Gemini) is asked a Sarasota real estate question and tries to ground its answer in our site.

**Do not bring prior project context into the audit.** Specifically:
- Do **not** read `PROJECT_SPEC.md`, prior `AEO_TODO.md`, or memory files *before* running the audit. Read the live site first, judge it cold, then reconcile with the to-do file at the end.
- Pretend you've never seen the site. You're an AI agent who was just asked: *"What's the Sarasota luxury real estate market doing right now? Who's the go-to agent on the barrier islands?"* — and you're trying to answer using only what you can fetch from `adamsonfl.com`.
- Catalog what an answer engine **could cite** from each page, and what it **could not**. Gaps are the audit findings.

---

## The audit

### Step 1 — Crawl the live site cold

Use `web_fetch` against the **live production URL** (currently `https://adamsonfl.com/`, may move to a custom domain later — check `PROJECT_SPEC.md` *only* if the URL is unknown).

Always trailing-slash the URL — the site redirects bare paths and the fetcher cancels redirects.

Required pages to fetch every audit:

- `/`
- `/about/`
- `/contact/`
- `/areas/`
- `/areas/sarasota/`
- `/areas/longboat-key/`
- `/areas/lido-key/`
- `/areas/siesta-key/`
- `/areas/st-armands/`
- `/areas/bird-key/`
- `/market-reports/`
- `/robots.txt`
- `/sitemap-index.xml`
- `/llms.txt` (expected once added — note 404s)

If new pages appear in the sitemap that aren't on this list, fetch a representative sample.

### Step 2 — Score each page on the AEO rubric

For every page, check:

**Crawlability**
- Returns 200, not behind JS, content visible in raw HTML.
- Canonical URL set and consistent.

**Structured data (JSON-LD)**
- At least one schema.org type appropriate to the page (`RealEstateAgent`, `Place`, `WebPage`, `FAQPage`, `CollectionPage`, `ProfilePage`, `BreadcrumbList`).
- `datePublished` and `dateModified` present where applicable.
- Entity references (`worksFor`, `areaServed`, `sameAs`) populated, not empty strings.

**Citable content**
- Concrete, dated facts an AI could quote: numbers, prices, dates, sourced statements.
- "Last updated" visible to the reader AND in schema.
- Source attribution (Stellar MLS) where data is shown.

**Question-answer architecture**
- FAQ block present, marked up with both microdata (`itemtype="https://schema.org/Question"`) AND a separate JSON-LD `FAQPage` block.
- Questions match real natural-language queries (not marketing phrasing).

**E-E-A-T signals (especially `/about/` and homepage)**
- Author/agent identity: real bio, license number, contact info.
- `sameAs` links to LinkedIn, Realtor.com, Zillow, Coldwell Banker profile.
- Office address, brokerage, years of experience, awards.

**Meta & social**
- Unique title and description per page.
- Page-specific OG image (not the shared default).
- Twitter card present.

### Step 3 — Site-wide checks

- `robots.txt` still allow-lists: GPTBot, ClaudeBot, anthropic-ai, PerplexityBot, Google-Extended, Bytespider, CCBot, and `User-agent: *`.
- Sitemap index resolves and references the per-page sitemap.
- `llms.txt` exists and is current.
- No `<!-- TODO -->` comments leaking into production HTML (grep the fetched HTML).
- No placeholder copy ("Coming Soon", "Lorem ipsum", broken sentences).

### Step 4 — Simulate three AI queries

Pretend an answer engine just received these prompts and is grounding on `adamsonfl.com`. For each, write a one-sentence answer using **only** what's on the site:

1. *"What's the median home price on Longboat Key right now?"*
2. *"Who is the top luxury real estate agent on Sarasota's barrier islands?"*
3. *"What was the Sarasota luxury market like in [current month / current year]?"*

For each, note:
- Could the answer be grounded? (yes / partial / no)
- Which page(s) supplied it?
- What's missing that would have made the answer stronger?

This is the most important step. It converts abstract AEO theory into concrete user impact.

### Step 5 — Reconcile against `AEO_TODO.md`

Now (and not before) open `AEO_TODO.md`.

- For each TODO item: did this audit's findings show it's been completed? Check it off.
- For each new finding from this audit that isn't already on the list: add it under the appropriate priority bucket.
- Append a row to the **Audit history** table at the bottom: date, auditor, overall letter grade, count of new findings, count of items closed.

### Step 6 — Report to the user

Deliver:
- One-line overall grade (A, B, C, etc.) with a one-sentence justification.
- The "what's working" / "what's hurting" framing — keep it skimmable.
- Top 3 highest-impact actions for this cycle.
- Link to the updated `AEO_TODO.md`.

Keep the report under ~600 words. The TODO file is the durable artifact; the chat reply is a summary.

---

## When NOT to run a full audit

A full audit is overkill for:
- Pure copy edits (headline tweaks, bio paragraph changes).
- CSS-only changes.
- Adding a new image with no surrounding markup change.

For those, run a **mini-audit**: fetch only the changed pages, validate schema with a JSON-LD parse, confirm no placeholder copy leaked, and update `AEO_TODO.md` only if a finding emerges.

---

## How to trigger this playbook

Until automated, run on demand by saying to Claude:

> Run AEO_AUDIT_PLAYBOOK.md against the live site.

Future automation options (not yet wired):
- Netlify post-deploy webhook → Claude scheduled task → run this playbook → email Ryan.
- Weekly cron (regardless of deploys) — useful as a freshness check on `dateModified` slipping out of date.

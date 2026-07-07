# BonesBot Automation Harness — Design Spec

**Written 2026-07-07 by Claude Fable 5 (Cowork), for a future Opus implementation session.**
**Read this whole document before writing code. It encodes a week of loaded context and
several hard-won landmines that are NOT obvious from the repo alone.**

## 0. Mission & constraints

Ryan (BonesBot mini-PC, Windows, Cowork) runs 4 daily scheduled Claude tasks. Measured
from real session transcripts on 2026-07-07 (API-equivalent, Sonnet-class w/ caching):

| Task | Schedule | Shape of a run | Est./run | Est./mo |
|---|---|---|---|---|
| `mls-export` | 6:38 AM | 150–250 agent turns; Chrome-drives Stellar Matrix, 4×500-record batch exports, Supabase ingest retry loops, stats refresh, email | $2.00–4.50 | **$60–135** |
| `sarasota-briefing` | morning | ~45 turns web research → Gmail draft | $0.30–0.80 | $9–24 |
| `srqmap-events` | 7:06 AM | ~30–50 turns search/verify/geocode/publish | $0.30–0.80 | $9–24 |
| `mls-export-watchdog` | 7:36 AM | 2 turns: one bash heartbeat check | ~$0.05 | ~$1.50 |

Total ≈ **$80–185/mo equivalent; mls-export is ~70%**. Target after this project: **$15–35/mo**,
with reliability equal or better. Hardware: mini-PC upgrading 16GB → **32GB RAM**; assume
CPU-only inference until an iGPU/NPU is verified usable.

**Prime directive:** the model is the *exception handler*, not the *executor*. Every phase
moves deterministic work into plain Python and reserves LLM calls (local or Claude) for
judgment, drift recovery, and prose.

**Failure philosophy:** fail LOUD and fail UPWARD. A local model that fails validation must
escalate to Claude or alert Ryan — never silently ship degraded output. This codebase's
history is a war against silent corruption (see FUSE saga, integrity gate); do not add a
new silent-failure vector.

## 1. Known landmines (violate any of these and the build will hurt)

1. **NEVER write to the AG_website working tree** from the Cowork sandbox (Edit/Write tools
   or bash) — the FUSE mount corrupts `.git/index` AND file contents; bash *reads* of
   working-tree files are also unreliable. All repo mutations go through the **GitHub
   Contents API** (token in repo `.env`). Scripts that must run canonically are fetched
   from `origin/main` into `/tmp` first (mls-export already does this). A native Windows
   harness (Phase 1+) is NOT under the FUSE mount and may use normal git — but commit to
   `main` because the Cowork-side jobs fetch canonical from origin.
2. **45-second bash ceiling** in Cowork sandbox; no cwd/env carry-over between calls; nohup'd
   background processes DIE when the call ends. The Supabase ingest already handles this
   with per-batch commits + a retry loop. The native Windows harness escapes this ceiling —
   one of its main benefits.
3. **Stale `/tmp` artifacts owned by `nobody`** accumulate across sandbox runs and can be
   unremovable/undeletable; the 2026-07-07 mls-export run hit a *silent write-denial* that
   briefly substituted a 2-day-old export file. Any harness must use fresh timestamped dirs
   and verify file mtimes/sizes after every download.
4. **Integrity gate:** `scripts/_integrity_check.py` + `EXPECTED_HASHES.json` self-heals from
   `main` (commit `5e85dbf73`) — never hand-rotate hashes; just commit script changes to main.
5. **Publish throttle:** site builds ~every 3 days (`daily-heartbeat.json` tracks
   `action: throttled|published`, build #, next-eligible date). The watchdog keys off the
   heartbeat **date**, never off git commits and never off Netlify builds.
6. **Netlify:** out-of-credit pushes show "Skipped" and must be re-triggered after topping up.
   `[skip ci]` in commit messages suppresses builds (used for multi-file pushes).
7. **Supabase:** use the Session pooler (IPv4). Column is `current_price` NOT `list_price`;
   there is no `public_remarks` column. Creds in repo `.env` (`DATABASE_URL`).
8. **Stellar/Matrix specifics** (from the working SKILL.md + transcripts): SSO cookie survives
   between days (job checks before re-login); saved search `000 - Market Update` (~1,600
   records currently); Matrix lists 100/page; select-all is per-page; exports cap at 500 →
   batches of 5 pages; export downloads need a *baseline snapshot* of the download dir before
   clicking and polling for the new file after; the CSV is 100 RESO-standard columns.
9. **Gmail:** the jobs create *drafts* (`create_draft`); a Google Apps Script auto-sender
   delivers drafts within ~1 minute. Keep this pattern — it's the send mechanism AND the
   human-approval escape hatch.
10. **Duplicate scheduled runs:** observed 2026-07-07, three concurrent "Sarasota morning
    briefing" sessions (missed runs firing as a backlog when the app wakes). The harness
    must be **idempotent per (task, local-date)**: write a per-task daily lockfile/heartbeat
    and no-op if today's already succeeded. Also fix/flag the Cowork-side duplicates.

## 2. Phased plan

### Phase 0 — De-LLM the watchdog (zero model; ~1 hour; do first)
Rewrite `mls-export-watchdog` as pure Python on **Windows Task Scheduler** (7:36 AM):
read `AG_website/logs/daily-heartbeat.json` (native path, no FUSE issue from Windows),
compare `date` to today (America/New_York), on mismatch send alert email. Email via the
existing Gmail-draft+AppsScript path (Gmail API refresh token) or plain SMTP app password —
implementer's choice, but reuse the existing HTML alert copy from the current SKILL.md.
Keep the Cowork scheduled task **disabled but not deleted** for 2 weeks as fallback.
*Acceptance: simulate a stale heartbeat → email arrives; fresh heartbeat → silence; runs
<5 s; survives PC reboot (Task Scheduler "run if missed" enabled).*

### Phase 1 — Playwright-ize the mls-export extraction (biggest win; no local model)
Build `harness/tasks/mls_export.py` (native Windows Python + Playwright, persistent browser
profile for the SSO cookie):
1. **Deterministic path:** login-check → open saved search → read total count → loop pages,
   select, export in ≤500 batches → verify each download (new file, today's mtime, >0 rows,
   header matches 100 cols) → run the existing canonical scripts *unchanged*
   (`combine_mls_export.py`, `supabase/ingest_mls.py`, `refresh_all_areas.py`) as
   subprocesses (no 45 s ceiling → no retry-loop gymnastics) → reconciliation email draft.
2. **Escalation path:** ANY assertion failure (selector missing, count mismatch, download
   timeout, row-count reconciliation failure) → write `harness/logs/<date>-mls-export.fail.json`
   with a screenshot + DOM snapshot + step name, email Ryan "pipeline needs an agent run
   today", and (optionally) leave the Cowork `mls-export` scheduled task enabled at 7:15 AM
   with a first step of "exit immediately if today's heartbeat already exists" — so Claude
   automatically picks up only the failed days. That inversion (script first, agent as
   fallback) is the core of the design.
3. Keep writing `logs/daily-heartbeat.json` in the exact current schema — the watchdog,
   throttle bookkeeping, and reconciliation email all key off it.
*Acceptance: 5 consecutive green days incl. one >1,600-record day; one forced-failure drill
(rename a selector via devtools or kill network mid-export) produces the fail-bundle +
email + successful Claude fallback run; Supabase reconciliation (inserted+updated+unchanged
= extracted) exact every day.*
Est. effort: the script is a day; the *debugging is iterative across mornings* — plan a week
of supervised runs. This phase alone cuts total spend ~60–70%.

### Phase 2 — Local-model harness for briefing + events (needs the 32GB installed)
**Runtime:** Ollama on Windows. **Models (verify current state-of-the-art at build time —
this list is from mid-2025 knowledge + may be stale):**
- Primary: **Qwen3-30B-A3B, Q4_K_M (~18–19GB)** — MoE with ~3B active params; the best
  CPU-only tool-calling/quality per token-second as of this writing (~10–20 tok/s decode).
  Requires the 32GB upgrade; leaves ~10GB for OS+Chrome+Cowork. Enable Ollama keep-alive.
- Fallback/fast lane: Qwen3-14B Q4 (~9GB) or Llama-3.1-8B (fits today's 16GB).
- **CPU prefill is the bottleneck** (tens of tok/s): design every local step for **<8k-token
  contexts**. Feed the model *pre-fetched* text (Python does RSS/HTTP), never let it browse.
**Harness core** (`harness/` in the AG_website repo or a sibling repo — implementer's call):
- `runner.py` invoked by Task Scheduler; per-task YAML in `harness/tasks/*.yaml`:
  ```yaml
  task: sarasota-briefing
  schedule: "07:00"            # informational; Task Scheduler owns timing
  idempotency: daily            # skip if today's success marker exists
  steps:
    - python: fetch_sources.py  # deterministic: RSS/HTTP pulls, cleaned text to JSON
    - llm:                      # local by default
        engine: ollama:qwen3-30b-a3b
        prompt: briefing.md     # template; context budget enforced by runner
        max_context: 8000
        output_schema: briefing.schema.json   # jsonschema-validated
        retries: 1
    - python: render_and_draft_email.py
  escalation:
    on_llm_invalid: claude      # leave breadcrumb file + enable Cowork fallback task
    on_python_error: email_ryan
  ```
- **Validation contracts are the safety net.** Events already has one:
  `scripts/events/publish_srqmap_events.py` (schema, SW-FL lat/lng bounds 26.9–27.8 /
  −83.0–−82.2, date-window, dedupe, no-change skip, prunes past events). The local model's
  ONLY job for srqmap-events is: given pre-fetched event-page text, emit candidates JSON.
  The publisher accepts or rejects; rejection → Claude fallback. Do NOT let the local model
  push to GitHub directly.
- **Briefing** is the lowest-risk pilot (private consumption): Python fetches sources →
  local model summarizes per-source → composes email → draft. Ship this first, run it
  side-by-side with the Claude briefing for a week, let Ryan A/B the two emails, then cut over.
- Per-task success markers + a tiny `harness/logs/status.json` the (Phase 0) watchdog can
  also read → one watchdog watches everything.
*Acceptance: briefing A/B week passes Ryan's taste test; events: 10 consecutive days where
local candidates pass the publisher with ≤2 escalations; zero silent-failure days (every
day ends in exactly one of: success marker / escalation breadcrumb / alert email).*

### Phase 3 (optional) — expand
Move srqmap-events geocoding fully into Python (Census/Photon, already proven), add new
cheap local tasks (lead-summary digests, market-FAQ freshness checks). Revisit hosted-Haiku
routing for anything the local model keeps failing — a `claude-haiku` engine in the same
YAML router is ~10 lines.

## 3. Explicitly out of scope for local models
- Anything that **publishes prose to adamsonfl.com** without a validation contract (AEO/brand voice).
- Driving the live MLS UI (tool-call reliability + long contexts; that's Phase 1's Playwright
  or Claude-fallback territory).
- The `srqmap-events` *editorial* fallback and any pipeline-drift diagnosis → Claude.

## 4. Checkpoint for a frontier model (one session, later)
After Phase 1 survives its first week: bring the fail-bundle log + this spec back to a
frontier model for a design review (escalation thresholds, whether the Cowork fallback
tasks can be retired, Phase 2 go/no-go). Everything else here is Opus-implementable.

## 5. Pointers
- Task SKILL.mds: `C:\Users\Bones\Documents\Claude\Scheduled\{mls-export, mls-export-watchdog, srqmap-events, ...}\SKILL.md`
- Pipeline docs: repo `CLAUDE.md`, `PROJECT_SPEC.md`, `LISTINGS_PLAYBOOK.md`
- Heartbeat: `logs/daily-heartbeat.json` · Events publisher: `scripts/events/publish_srqmap_events.py`
- Secrets: repo `.env` (GITHUB_TOKEN, DATABASE_URL, SUPABASE_*, HEYGEN) — never commit
- Cost baseline (this doc §0) — re-measure after each phase via Cowork session transcripts

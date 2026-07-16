#!/usr/bin/env python3
"""
Gulf & Bay Club landing pages -> src/pages/siesta-key/*.astro

Emits THREE pages from live Supabase MLS data:
  • gulf-and-bay-club-beachfront.astro   (Phases 1-6, Gulf-front association)
  • gulf-and-bay-club-bayside.astro      (Bayside association)
  • gulf-and-bay-club.astro              (hub — preserves the indexed URL, links to both)

These are BAKED STATIC snapshots (like the page they replace) — re-run this script
to refresh. They are NOT part of the daily refresh_all_areas.py pipeline.

Usage:
    python scripts/gen_gulf_bay_pages.py
"""

import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median

import psycopg2
import psycopg2.extras

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_FILE = PROJECT_ROOT / ".env"
OUT_DIR = PROJECT_ROOT / "src" / "pages" / "siesta-key"

HEADLINE_WINDOW_DAYS = 180   # headline stat grid (unchanged from the original page)
LEDGER_WINDOW_DAYS = 365     # transaction ledger — wider so the filters have data to bite on


def load_env(env_path):
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


load_env(ENV_FILE)
DATABASE_URL = os.environ.get("DATABASE_URL", "")


# ── Formatting helpers ────────────────────────────────────────────────────────

def esc(s):
    """Escape for HTML text context inside an .astro template."""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#x27;"))


def repr_js(s):
    """Single-quoted JS string literal."""
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ") + "'"


def money(n):
    if n is None:
        return "—"
    return f"${int(round(float(n))):,}"


def pct(n):
    if n is None:
        return "—"
    v = float(n)
    return f"{v * 100:.1f}%" if v <= 2 else f"{v:.1f}%"


def nice_date(d):
    if d is None:
        return "—"
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def bedbath(r):
    full = r["bathrooms_full"] or 0
    half = r["bathrooms_half"] or 0
    ba = f"{full}.5" if half else f"{full}"
    bd = r["bedrooms_total"]
    if bd is None:
        return "—"
    return f"{bd} bd / {ba} ba"


# Stellar's export mangles "Gulf/Ocean - Full" into "GulfFull"; unmangle for display.
WV_FIX = [(r"\bGulfFull\b", "Gulf/Ocean - Full")]


def water_view(r):
    wv = (r["water_view"] or "").strip()
    if not wv:
        return None
    for pat, rep in WV_FIX:
        wv = re.sub(pat, rep, wv)
    parts = [p.strip() for p in wv.split(",") if p.strip()]
    seen, out = set(), []
    for p in parts:
        if p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return ", ".join(out)


# ── Config ────────────────────────────────────────────────────────────────────

SIDES = {
    "beachfront": {
        "slug": "gulf-and-bay-club-beachfront",
        "name": "Gulf & Bay Club Beachfront",
        "short": "Beachfront",
        "label": "Beachfront &middot; Phases 1&ndash;6",
        "where": "subdivision_name ILIKE '%%GULF%%BAY%%CLUB%%' AND subdivision_name NOT ILIKE '%%BAYSIDE%%'",
        "blurb": "The flagship 32-acre Gulf-front community on Midnight Pass Road, spanning Phases 1&ndash;6 directly on Siesta Key&rsquo;s white quartz sand.",
        "about": "Set on 32 beachfront acres along Midnight Pass Road, Gulf &amp; Bay Club is one of Siesta Key&rsquo;s most established condominium communities &mdash; known for lush tropical landscaping, tennis, pools, and direct access to the #1-rated Siesta Key Beach. Units are predominantly two-bedroom plans in the 1,300&ndash;1,500 sq ft range, with a handful of larger corner and penthouse residences. This page tracks the real closed-sale market, straight from the MLS.",
        "street": "5740-5790 Midnight Pass Road",
        "chips": ["Gulf-Front", "Siesta Key Beach", "Tennis &amp; Pools", "Gated", "1-Month Minimum Lease"],
        "hero": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9f/SARASOTA_SUNSET._SIESTA_KEY_-_panoramio_-_JOHN_SIMPSON.jpg/1920px-SARASOTA_SUNSET._SIESTA_KEY_-_panoramio_-_JOHN_SIMPSON.jpg",
        "sister_slug": "gulf-and-bay-club-bayside",
        "sister_name": "Gulf & Bay Club Bayside",
    },
    "bayside": {
        "slug": "gulf-and-bay-club-bayside",
        "name": "Gulf & Bay Club Bayside",
        "short": "Bayside",
        "label": "Bayside &middot; Intracoastal Side",
        "where": "subdivision_name ILIKE '%%GULF%%BAY%%CLUB%%BAYSIDE%%'",
        "blurb": "The separate bayside association across Midnight Pass Road &mdash; intracoastal-side condos, a lower price of entry into the Gulf &amp; Bay Club name, and a weekly minimum lease.",
        "about": "Gulf &amp; Bay Club Bayside sits across Midnight Pass Road from its Gulf-front sister association, on the intracoastal side of Siesta Key. It is a distinct condominium association with its own fees, rules, and market. Two points matter most to buyers: the price of entry is materially lower than the beachfront, and the association permits a <strong>one-week minimum lease</strong> &mdash; versus one month on the beachfront &mdash; which makes Bayside the more flexible of the two for rental income. This page tracks its real closed-sale market, straight from the MLS.",
        "street": "1223-1311 Siesta Bayside Drive",
        "chips": ["Bayside", "Weekly Rentals Allowed", "Pond &amp; Bay Views", "Heated Pool", "Lower Entry Price"],
        "hero": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/Siesta_key_sunset%2C_Sarasota._-_panoramio.jpg/1920px-Siesta_key_sunset%2C_Sarasota._-_panoramio.jpg",
        "sister_slug": "gulf-and-bay-club-beachfront",
        "sister_name": "Gulf & Bay Club Beachfront",
    },
}

# Same placeholder CC photo set on both pages, per spec.
GALLERY = [
    ("https://upload.wikimedia.org/wikipedia/commons/thumb/a/aa/Siesta_Key_Beach._Sarasota_-_panoramio.jpg/1920px-Siesta_Key_Beach._Sarasota_-_panoramio.jpg", "Siesta Key Beach near Gulf & Bay Club", "gbc-fig-tall"),
    ("https://upload.wikimedia.org/wikipedia/commons/thumb/9/94/Red_Lifeguard_Stand_at_Siesta_Key_Beach.jpg/1920px-Red_Lifeguard_Stand_at_Siesta_Key_Beach.jpg", "Red lifeguard stand on Siesta Key Beach", ""),
    ("https://upload.wikimedia.org/wikipedia/commons/thumb/7/7d/Siesta_Key_Public_Beach_-_panoramio.jpg/1920px-Siesta_Key_Public_Beach_-_panoramio.jpg", "Siesta Key public beach", ""),
    ("https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/Siesta_key_sunset%2C_Sarasota._-_panoramio.jpg/1920px-Siesta_key_sunset%2C_Sarasota._-_panoramio.jpg", "Siesta Key sunset over the Gulf", "gbc-fig-wide"),
]


# ── Data ──────────────────────────────────────────────────────────────────────

def fetch(cur, where, days):
    cur.execute(f"""
        SELECT unparsed_address, close_date, current_price, bedrooms_total,
               bathrooms_full, bathrooms_half, living_area, water_view,
               minimum_lease, close_price_by_calculated_sqft,
               cumulative_days_on_market,
               close_price_by_calculated_list_price_ratio AS sp_lp
          FROM raw_listings
         WHERE {where}
           AND standard_status = 'Closed'
           AND close_date IS NOT NULL
           AND close_date >= %s
         ORDER BY close_date DESC
    """, (date.today() - timedelta(days=days),))
    return cur.fetchall()


def lease_consensus(cur, where):
    """Modal minimum_lease across ALL listings (not just closed) for this side."""
    cur.execute(f"""
        SELECT minimum_lease, COUNT(*) n
          FROM raw_listings
         WHERE {where} AND minimum_lease IS NOT NULL AND minimum_lease <> ''
         GROUP BY 1 ORDER BY n DESC
    """, ())
    rows = cur.fetchall()
    if not rows:
        return None, 0, 0
    total = sum(r["n"] for r in rows)
    return rows[0]["minimum_lease"], rows[0]["n"], total


def quarters(cur, where):
    cur.execute(f"""
        SELECT to_char(close_date, 'YYYY"-Q"Q') AS period,
               COUNT(*) n,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY current_price) AS med,
               AVG(close_price_by_calculated_sqft) AS psf
          FROM raw_listings
         WHERE {where} AND standard_status='Closed' AND close_date >= %s
         GROUP BY 1 ORDER BY 1
    """, (date.today() - timedelta(days=365),))
    return cur.fetchall()


# ── Rendering ─────────────────────────────────────────────────────────────────

def stat(value, label, sub=""):
    sub_html = f'<div class="gbc-stat-sub">{sub}</div>' if sub else ""
    return f'''<div class="gbc-stat">
        <div class="gbc-stat-value">{value}</div>
        <div class="gbc-stat-label">{label}</div>
        {sub_html}
      </div>'''


def render_stats(rows, lease, lease_n, lease_total):
    prices = [float(r["current_price"]) for r in rows if r["current_price"] is not None]
    psf = [float(r["close_price_by_calculated_sqft"]) for r in rows if r["close_price_by_calculated_sqft"] is not None]
    cdom = [r["cumulative_days_on_market"] for r in rows if r["cumulative_days_on_market"] is not None]
    splp = [float(r["sp_lp"]) for r in rows if r["sp_lp"] is not None]

    share = round(100 * lease_n / lease_total) if lease_total else 0
    lease_sub = f"{share}% of {lease_total} MLS records" if lease else "not reported"

    tiles = [
        stat(len(rows), "Closed Sales"),
        stat(money(min(prices)) if prices else "—", "Min Sale Price"),
        stat(money(mean(prices)) if prices else "—", "Avg Sale Price"),
        stat(money(max(prices)) if prices else "—", "Max Sale Price"),
        stat(f"${int(round(mean(psf))):,}" if psf else "—", "Avg Price / SqFt"),
        stat(str(round(mean(cdom))) if cdom else "—", "Avg CDOM", "days on market"),
        stat(f"{mean(splp) * 100:.1f}%" if splp else "—", "Avg Sale-to-List"),
        stat(esc(lease) if lease else "—", "Minimum Lease Period", lease_sub),
    ]
    return '<div class="gbc-stat-grid">' + "\n".join(tiles) + "</div>"


def render_filters(rows, uid):
    sqfts = [int(r["living_area"]) for r in rows if r["living_area"]]
    if sqfts:
        lo = (min(sqfts) // 50) * 50
        hi = -(-max(sqfts) // 50) * 50
    else:
        lo, hi = 0, 3000
    return f'''<div class="gbc-filter" data-filter="{uid}">
        <div class="gbc-filter-head">Filter Data</div>
        <div class="gbc-filter-grid">
          <div class="gbc-filter-ctl">
            <label for="{uid}-bed">Bedrooms <span class="gbc-filter-val" data-out="bed">Any</span></label>
            <input id="{uid}-bed" type="range" min="0" max="4" step="1" value="0" data-role="bed" />
            <div class="gbc-filter-scale"><span>Any</span><span>1</span><span>2</span><span>3</span><span>4+</span></div>
          </div>
          <div class="gbc-filter-ctl">
            <label for="{uid}-min">Approx Sq Ft <span class="gbc-filter-val" data-out="sqft">{lo:,} &ndash; {hi:,}</span></label>
            <div class="gbc-dual">
              <input id="{uid}-min" type="range" min="{lo}" max="{hi}" step="50" value="{lo}" data-role="sqmin" aria-label="Minimum square feet" />
              <input id="{uid}-max" type="range" min="{lo}" max="{hi}" step="50" value="{hi}" data-role="sqmax" aria-label="Maximum square feet" />
            </div>
            <div class="gbc-filter-scale"><span>{lo:,}</span><span>{hi:,}</span></div>
          </div>
          <div class="gbc-filter-meta">
            <span data-out="count">{len(rows)}</span> of {len(rows)} sales
            <button type="button" class="gbc-filter-reset" data-role="reset">Reset</button>
          </div>
        </div>
      </div>'''


def render_ledger(rows, uid):
    trs = []
    for r in rows:
        wv = water_view(r)
        sf = int(r["living_area"]) if r["living_area"] else None
        cdom = r["cumulative_days_on_market"]
        trs.append(f'''<tr data-bed="{r['bedrooms_total'] or 0}" data-sqft="{sf or 0}">
        <td class="gbc-addr">{esc(r['unparsed_address'])}</td>
        <td>{bedbath(r)}</td>
        <td class="gbc-num">{f"{sf:,}" if sf else "—"}</td>
        <td class="gbc-num">{money(r['current_price'])}</td>
        <td class="gbc-num">{money(r['close_price_by_calculated_sqft'])}</td>
        <td>{nice_date(r['close_date'])}</td>
        <td class="gbc-num">{cdom if cdom is not None else "—"}</td>
        <td class="gbc-num">{pct(r['sp_lp'])}</td>
        <td class="gbc-wv">{esc(wv) if wv else '<span class="gbc-wv-none">No water view</span>'}</td>
      </tr>''')
    body = "\n".join(trs) if trs else '<tr><td colspan="9" class="gbc-empty">No closings recorded in this window.</td></tr>'
    return f'''<div class="gbc-table-wrap">
      <table class="gbc-table" data-table="{uid}">
        <thead>
          <tr>
            <th>Address &amp; Unit</th>
            <th>Bed / Bath</th>
            <th class="gbc-num">Sq Ft</th>
            <th class="gbc-num">Sale Price</th>
            <th class="gbc-num">$ / SqFt</th>
            <th>Closed</th>
            <th class="gbc-num">CDOM</th>
            <th class="gbc-num">SP/LP</th>
            <th>Water View</th>
          </tr>
        </thead>
        <tbody>
{body}
        </tbody>
      </table>
      <p class="gbc-noresults" data-out="empty" hidden>No sales match these filters.</p>
    </div>'''


def render_trend(qs):
    if not qs:
        return ""
    cols = []
    for q in qs:
        psf = int(round(float(q["psf"]))) if q["psf"] else 0
        cols.append(f'''<div class="gbc-trend-col">
          <div class="gbc-trend-period">{q['period']}</div>
          <div class="gbc-trend-price">{money(q['med'])}</div>
          <div class="gbc-trend-meta">{q['n']} sold &middot; ${psf:,}/sf</div>
        </div>''')
    return '<div class="gbc-trend-grid">' + "\n".join(cols) + "</div>"


def render_forms(cfg):
    community = cfg["name"]
    slug = cfg["slug"]
    return f'''
  <section class="section light-section">
    <div class="container">
      <p class="section-label mb-3">Two Ways In</p>
      <h2 class="accent-underline mb-6">Work With Us on {esc(cfg["short"])}</h2>
      <div class="gbc-tiles">

        <div class="gbc-tile gbc-tile-seller">
          <span class="gbc-tile-eyebrow">For Owners</span>
          <h3 class="gbc-tile-title">Reach out for a private consult</h3>
          <p class="gbc-tile-copy">Curious what your unit would bring today? We&rsquo;ll walk the real closed-sale data above against your floor plan, view, and condition &mdash; privately, with no obligation and no listing pressure.</p>
          <form class="gbc-form" data-lead-type="Seller" data-community="{esc(community)}"
                name="gbc-lead-seller" method="POST" data-netlify="true" netlify-honeypot="bot-field">
            <input type="hidden" name="form-name" value="gbc-lead-seller" />
            <input type="hidden" name="lead_type" value="Seller" />
            <input type="hidden" name="community" value="{esc(community)}" />
            <p class="gbc-hp"><label>Don&rsquo;t fill this out: <input name="bot-field" /></label></p>
            <div class="gbc-field"><label for="s-name-{slug}">Name</label>
              <input id="s-name-{slug}" name="name" type="text" required autocomplete="name" /></div>
            <div class="gbc-field"><label for="s-email-{slug}">Email</label>
              <input id="s-email-{slug}" name="email" type="email" required autocomplete="email" /></div>
            <div class="gbc-field"><label for="s-phone-{slug}">Phone</label>
              <input id="s-phone-{slug}" name="phone" type="tel" autocomplete="tel" /></div>
            <button type="submit" class="gbc-btn gbc-btn-gold gbc-btn-full">Request a Private Consult</button>
            <p class="gbc-form-status" data-out="status" role="status" aria-live="polite"></p>
          </form>
        </div>

        <div class="gbc-tile gbc-tile-buyer">
          <span class="gbc-tile-eyebrow">For Buyers</span>
          <h3 class="gbc-tile-title">Add me to the coming-soon list</h3>
          <p class="gbc-tile-copy">{esc(cfg["short"])} turns over a handful of units a year, and the best ones often trade before they reach the MLS. Get on the list and we&rsquo;ll reach out first on available and off-market units.</p>
          <form class="gbc-form" data-lead-type="Buyer" data-community="{esc(community)}"
                name="gbc-lead-buyer" method="POST" data-netlify="true" netlify-honeypot="bot-field">
            <input type="hidden" name="form-name" value="gbc-lead-buyer" />
            <input type="hidden" name="lead_type" value="Buyer" />
            <input type="hidden" name="community" value="{esc(community)}" />
            <p class="gbc-hp"><label>Don&rsquo;t fill this out: <input name="bot-field" /></label></p>
            <div class="gbc-field"><label for="b-name-{slug}">Name</label>
              <input id="b-name-{slug}" name="name" type="text" required autocomplete="name" /></div>
            <div class="gbc-field"><label for="b-email-{slug}">Email</label>
              <input id="b-email-{slug}" name="email" type="email" required autocomplete="email" /></div>
            <div class="gbc-field"><label for="b-phone-{slug}">Phone</label>
              <input id="b-phone-{slug}" name="phone" type="tel" autocomplete="tel" /></div>
            <button type="submit" class="gbc-btn gbc-btn-navy gbc-btn-full">Notify Me First</button>
            <p class="gbc-form-status" data-out="status" role="status" aria-live="polite"></p>
          </form>
        </div>

      </div>
    </div>
  </section>'''


STYLES = r'''<style is:global>
  .gbc-hero { position:relative; padding-top:9rem; padding-bottom:7rem; overflow:hidden; }
  .gbc-hero-bg { position:absolute; inset:0; background-size:cover; background-position:center; background-color:var(--color-black); }
  .gbc-hero-overlay { position:absolute; inset:0; background:linear-gradient(to bottom, rgba(0,0,0,0.55), rgba(0,0,0,0.45) 40%, rgba(0,0,0,0.9)); }
  .gbc-hero-tag { font-size:1.15rem; color:rgba(255,255,255,0.8); max-width:44rem; line-height:1.7; }
  .gbc-sister { margin-top:1.75rem; font-family:var(--font-accent); font-size:0.78rem; text-transform:uppercase; letter-spacing:0.08em; color:rgba(255,255,255,0.6); }
  .gbc-sister a { color:var(--color-gold); border-bottom:1px solid rgba(197,165,90,0.5); padding-bottom:2px; }
  .gbc-sister a:hover { color:var(--color-gold-light); }
  .gbc-about { color:var(--color-text-muted); line-height:1.8; font-size:1.05rem; }
  .gbc-chip { display:inline-block; background:rgba(45,66,128,0.1); color:var(--color-cbgl-blue); font-family:var(--font-accent); font-size:0.72rem; text-transform:uppercase; letter-spacing:0.08em; padding:0.45rem 1rem; border-radius:9999px; border:1px solid rgba(45,66,128,0.2); }
  .gbc-fig { position:relative; overflow:hidden; border-radius:0.6rem; aspect-ratio:4/3; margin:0; }
  .gbc-fig img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; transition:transform .7s; }
  .gbc-fig:hover img { transform:scale(1.05); }
  .gbc-fig-tall { grid-row:span 2; aspect-ratio:3/4; }
  .gbc-fig-wide { aspect-ratio:16/9; }
  .gbc-blurb { color:rgba(255,255,255,0.72); max-width:46rem; line-height:1.7; margin-bottom:0.4rem; }
  .gbc-window { color:rgba(255,255,255,0.45); font-family:var(--font-accent); font-size:0.75rem; text-transform:uppercase; letter-spacing:0.08em; margin-bottom:1.25rem; }
  .gbc-subhead { margin-top:3rem; margin-bottom:0.35rem; color:#fff; font-size:1.4rem; }
  .gbc-note { color:var(--color-gold-light); font-size:0.85rem; margin-top:0.75rem; font-style:italic; }
  .gbc-stat-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:0.9rem; margin-top:0.5rem; }
  @media (min-width:640px){ .gbc-stat-grid{ grid-template-columns:repeat(4,1fr);} }
  .gbc-stat { background:var(--color-black-card); border:1px solid rgba(255,255,255,0.1); border-radius:0.7rem; padding:1.3rem 1.1rem; }
  .gbc-stat-value { font-family:var(--font-display); font-size:1.55rem; color:#fff; line-height:1.1; }
  .gbc-stat-label { font-family:var(--font-accent); font-size:0.68rem; text-transform:uppercase; letter-spacing:0.09em; color:var(--color-cbgl-blue-light); margin-top:0.5rem; }
  .gbc-stat-sub { font-size:0.68rem; color:rgba(255,255,255,0.4); margin-top:0.15rem; }

  /* ── Filter Data ───────────────────────────────────────────── */
  .gbc-filter { margin-top:1.5rem; background:var(--color-black-card); border:1px solid rgba(255,255,255,0.1); border-radius:0.7rem; padding:1.1rem 1.25rem 1.25rem; }
  .gbc-filter-head { font-family:var(--font-accent); font-size:0.68rem; text-transform:uppercase; letter-spacing:0.12em; color:rgba(255,255,255,0.4); margin-bottom:1rem; }
  .gbc-filter-grid { display:grid; grid-template-columns:1fr; gap:1.5rem; align-items:end; }
  @media (min-width:820px){ .gbc-filter-grid { grid-template-columns:1fr 1fr auto; gap:2.25rem; } }
  .gbc-filter-ctl label { display:flex; justify-content:space-between; align-items:baseline; gap:1rem; font-family:var(--font-accent); font-size:0.72rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--color-cbgl-blue-light); margin-bottom:0.7rem; }
  .gbc-filter-val { font-family:var(--font-display); text-transform:none; letter-spacing:0; font-size:0.95rem; color:#fff; }
  .gbc-filter-scale { display:flex; justify-content:space-between; margin-top:0.45rem; font-size:0.65rem; color:rgba(255,255,255,0.3); font-variant-numeric:tabular-nums; }
  .gbc-filter input[type=range] { -webkit-appearance:none; appearance:none; width:100%; height:2px; background:rgba(255,255,255,0.18); border-radius:2px; outline:none; margin:0; }
  .gbc-filter input[type=range]::-webkit-slider-thumb { -webkit-appearance:none; appearance:none; width:15px; height:15px; border-radius:50%; background:var(--color-gold); cursor:pointer; border:none; box-shadow:0 0 0 4px rgba(197,165,90,0.15); transition:box-shadow .15s, transform .15s; }
  .gbc-filter input[type=range]::-webkit-slider-thumb:hover { box-shadow:0 0 0 7px rgba(197,165,90,0.25); transform:scale(1.08); }
  .gbc-filter input[type=range]::-moz-range-thumb { width:15px; height:15px; border-radius:50%; background:var(--color-gold); cursor:pointer; border:none; box-shadow:0 0 0 4px rgba(197,165,90,0.15); }
  .gbc-filter input[type=range]:focus-visible::-webkit-slider-thumb { box-shadow:0 0 0 7px rgba(197,165,90,0.4); }
  .gbc-dual { position:relative; height:15px; }
  .gbc-dual input[type=range] { position:absolute; top:6px; left:0; pointer-events:none; background:none; }
  .gbc-dual::before { content:""; position:absolute; top:6px; left:0; right:0; height:2px; background:rgba(255,255,255,0.18); border-radius:2px; }
  .gbc-dual input[type=range]::-webkit-slider-thumb { pointer-events:auto; }
  .gbc-dual input[type=range]::-moz-range-thumb { pointer-events:auto; }
  .gbc-filter-meta { font-family:var(--font-accent); font-size:0.72rem; text-transform:uppercase; letter-spacing:0.08em; color:rgba(255,255,255,0.5); white-space:nowrap; }
  .gbc-filter-meta [data-out=count] { color:var(--color-gold); font-weight:600; }
  .gbc-filter-reset { display:block; margin-top:0.5rem; background:none; border:none; padding:0; color:rgba(255,255,255,0.45); font-family:var(--font-accent); font-size:0.68rem; text-transform:uppercase; letter-spacing:0.08em; cursor:pointer; border-bottom:1px solid rgba(255,255,255,0.2); }
  .gbc-filter-reset:hover { color:#fff; }

  .gbc-table-wrap { margin-top:0.75rem; max-height:520px; overflow:auto; border:1px solid rgba(255,255,255,0.1); border-radius:0.7rem; }
  .gbc-table { width:100%; border-collapse:collapse; font-size:0.86rem; color:rgba(255,255,255,0.85); min-width:900px; }
  .gbc-table thead th { position:sticky; top:0; background:var(--color-dark); color:var(--color-cbgl-blue-light); font-family:var(--font-accent); font-size:0.68rem; text-transform:uppercase; letter-spacing:0.07em; text-align:left; padding:0.8rem 0.9rem; border-bottom:1px solid rgba(255,255,255,0.14); z-index:1; white-space:nowrap; }
  .gbc-table tbody td { padding:0.75rem 0.9rem; border-bottom:1px solid rgba(255,255,255,0.06); vertical-align:top; }
  .gbc-table tbody tr:hover { background:rgba(82,168,255,0.06); }
  .gbc-num { text-align:right; font-variant-numeric:tabular-nums; }
  .gbc-addr { font-weight:600; color:#fff; white-space:nowrap; }
  .gbc-wv { font-size:0.78rem; color:rgba(255,255,255,0.65); max-width:15rem; }
  .gbc-wv-none { color:rgba(255,255,255,0.3); font-style:italic; }
  .gbc-empty, .gbc-noresults { padding:2rem; text-align:center; color:rgba(255,255,255,0.4); font-style:italic; font-size:0.85rem; }
  .gbc-noresults { margin:0; }

  .gbc-trend-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:0.9rem; margin-top:0.5rem; }
  @media (min-width:640px){ .gbc-trend-grid{ grid-template-columns:repeat(4,1fr);} }
  .gbc-trend-col { background:var(--color-black-card); border:1px solid rgba(255,255,255,0.1); border-radius:0.7rem; padding:1.1rem; border-left:3px solid var(--color-gold); }
  .gbc-trend-period { font-family:var(--font-accent); font-size:0.72rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--color-cbgl-blue-light); }
  .gbc-trend-price { font-family:var(--font-display); font-size:1.35rem; color:#fff; margin-top:0.35rem; }
  .gbc-trend-meta { font-size:0.72rem; color:rgba(255,255,255,0.5); margin-top:0.25rem; }

  /* ── Lead tiles ────────────────────────────────────────────── */
  .gbc-tiles { display:grid; grid-template-columns:1fr; gap:1.5rem; }
  @media (min-width:900px){ .gbc-tiles { grid-template-columns:1fr 1fr; gap:2rem; } }
  .gbc-tile { border-radius:0.8rem; padding:2rem 1.9rem; border:1px solid rgba(0,0,0,0.08); background:#fff; box-shadow:0 1px 3px rgba(0,0,0,0.04); }
  .gbc-tile-seller { border-top:3px solid var(--color-gold); }
  .gbc-tile-buyer  { border-top:3px solid var(--color-cbgl-blue); }
  .gbc-tile-eyebrow { font-family:var(--font-accent); font-size:0.68rem; text-transform:uppercase; letter-spacing:0.12em; color:var(--color-text-muted); }
  .gbc-tile-title { font-family:var(--font-display); font-size:1.5rem; margin:0.6rem 0 0.75rem; color:var(--color-black); }
  .gbc-tile-copy { color:var(--color-text-muted); line-height:1.7; font-size:0.94rem; margin-bottom:1.5rem; }
  .gbc-field { margin-bottom:0.9rem; }
  .gbc-field label { display:block; font-family:var(--font-accent); font-size:0.68rem; text-transform:uppercase; letter-spacing:0.09em; color:var(--color-text-muted); margin-bottom:0.35rem; }
  .gbc-field input { width:100%; padding:0.7rem 0.85rem; border:1px solid rgba(0,0,0,0.14); border-radius:0.35rem; font-size:0.95rem; background:#fff; color:var(--color-black); transition:border-color .15s, box-shadow .15s; }
  .gbc-field input:focus { outline:none; border-color:var(--color-gold); box-shadow:0 0 0 3px rgba(197,165,90,0.15); }
  .gbc-hp { position:absolute; left:-9999px; }
  .gbc-form-status { margin-top:0.8rem; font-size:0.85rem; min-height:1.2em; }
  .gbc-form-status.is-ok { color:#1d7a4c; }
  .gbc-form-status.is-err { color:#b3261e; }

  .gbc-cta-text { color:rgba(255,255,255,0.85); max-width:40rem; margin:0 auto 2rem; line-height:1.7; }
  .gbc-team { display:flex; justify-content:center; gap:3rem; margin:0 auto 2.25rem; flex-wrap:wrap; }
  .gbc-member { margin:0; text-align:center; }
  .gbc-avatar { width:112px; height:112px; border-radius:50%; object-fit:cover; display:block; margin:0 auto 0.85rem; border:2px solid rgba(197,165,90,0.55); box-shadow:0 6px 20px rgba(0,0,0,0.35); }
  @media (min-width:640px){ .gbc-avatar { width:132px; height:132px; } }
  .gbc-member-name { display:block; font-family:var(--font-display); font-size:1.02rem; color:#fff; }
  .gbc-team-brokerage { font-family:var(--font-accent); font-size:0.68rem; text-transform:uppercase; letter-spacing:0.16em; color:var(--color-gold); margin:-0.4rem auto 2.25rem; display:flex; align-items:center; justify-content:center; gap:1rem; }
  .gbc-team-brokerage::before, .gbc-team-brokerage::after { content:""; height:1px; width:2.5rem; background:rgba(197,165,90,0.4); }
  .gbc-cta-btns { display:flex; gap:1rem; justify-content:center; flex-wrap:wrap; }
  .gbc-btn { display:inline-flex; align-items:center; justify-content:center; font-family:var(--font-accent); text-transform:uppercase; letter-spacing:0.08em; font-size:0.8rem; font-weight:600; padding:1rem 2rem; border-radius:0.35rem; transition:all .2s; border:none; cursor:pointer; }
  .gbc-btn-gold { background:var(--color-gold); color:#000; }
  .gbc-btn-gold:hover { background:var(--color-gold-light); }
  .gbc-btn-navy { background:var(--color-cbgl-blue); color:#fff; }
  .gbc-btn-navy:hover { filter:brightness(1.15); }
  .gbc-btn-outline { border:2px solid #fff; color:#fff; }
  .gbc-btn-outline:hover { background:#fff; color:#000; }
  .gbc-btn-full { width:100%; }
  .gbc-btn[disabled] { opacity:0.55; cursor:default; }
  .gbc-disc { color:rgba(255,255,255,0.55); font-size:0.82rem; line-height:1.7; }
  .gbc-credit { margin-top:1rem; color:rgba(255,255,255,0.4); font-size:0.75rem; }
</style>'''


SCRIPTS = r'''<script is:inline>
  // ── Ledger filters ──────────────────────────────────────────────
  document.querySelectorAll('[data-filter]').forEach((panel) => {
    const uid   = panel.getAttribute('data-filter');
    const table = document.querySelector('[data-table="' + uid + '"]');
    if (!table) return;
    const rows   = Array.from(table.querySelectorAll('tbody tr[data-bed]'));
    const bed    = panel.querySelector('[data-role=bed]');
    const sqMin  = panel.querySelector('[data-role=sqmin]');
    const sqMax  = panel.querySelector('[data-role=sqmax]');
    const outBed = panel.querySelector('[data-out=bed]');
    const outSq  = panel.querySelector('[data-out=sqft]');
    const outCnt = panel.querySelector('[data-out=count]');
    const empty  = table.parentElement.querySelector('[data-out=empty]');
    const reset  = panel.querySelector('[data-role=reset]');
    const n = (v) => Number(v);
    const fmt = (v) => n(v).toLocaleString();

    function apply() {
      // Keep the dual handles from crossing.
      if (n(sqMin.value) > n(sqMax.value)) {
        if (document.activeElement === sqMin) sqMax.value = sqMin.value;
        else sqMin.value = sqMax.value;
      }
      const b = n(bed.value), lo = n(sqMin.value), hi = n(sqMax.value);
      outBed.textContent = b === 0 ? 'Any' : (b === 4 ? '4+' : String(b));
      outSq.textContent  = fmt(lo) + ' – ' + fmt(hi);

      let shown = 0;
      rows.forEach((tr) => {
        const rb = n(tr.dataset.bed), rs = n(tr.dataset.sqft);
        const okBed  = b === 0 || (b === 4 ? rb >= 4 : rb === b);
        const okSqft = rs === 0 || (rs >= lo && rs <= hi);
        const ok = okBed && okSqft;
        tr.hidden = !ok;
        if (ok) shown++;
      });
      if (outCnt) outCnt.textContent = String(shown);
      if (empty) empty.hidden = shown !== 0;
    }

    [bed, sqMin, sqMax].forEach((el) => el && el.addEventListener('input', apply));
    if (reset) reset.addEventListener('click', () => {
      bed.value = 0; sqMin.value = sqMin.min; sqMax.value = sqMax.max; apply();
    });
    apply();
  });

  // ── Lead forms ──────────────────────────────────────────────────
  document.querySelectorAll('form.gbc-form').forEach((form) => {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const status = form.querySelector('[data-out=status]');
      const btn    = form.querySelector('button[type=submit]');
      const fd     = new FormData(form);
      const data   = Object.fromEntries(fd.entries());

      if (data['bot-field']) return;               // honeypot
      status.className = 'gbc-form-status';
      status.textContent = 'Sending…';
      btn.disabled = true;

      try {
        const res = await fetch('/.netlify/functions/community-lead', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: data.name, email: data.email, phone: data.phone,
            lead_type: form.dataset.leadType,
            community: form.dataset.community,
            page: window.location.pathname,
          }),
        });
        if (!res.ok) throw new Error('bad status ' + res.status);

        // Mirror to Netlify Forms so the built-in email notification fires too.
        fetch('/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams(fd).toString(),
        }).catch(() => {});

        form.reset();
        status.className = 'gbc-form-status is-ok';
        status.textContent = 'Thank you — we’ll be in touch shortly.';
      } catch (err) {
        console.error(err);
        status.className = 'gbc-form-status is-err';
        status.textContent = 'Something went wrong. Please call (941) 713-9234.';
        btn.disabled = false;
      }
    });
  });
</script>'''


def render_page(cfg, headline, ledger, lease, lease_n, lease_total, qs, as_of):
    uid = cfg["slug"]
    prices = [float(r["current_price"]) for r in headline if r["current_price"]]
    avg = money(mean(prices)) if prices else "—"
    description = (f"{cfg['name']}, Siesta Key (34242) condo market: {len(headline)} closed sales in the last "
                   f"{HEADLINE_WINDOW_DAYS} days, average {avg}, {lease or 'n/a'} minimum lease period, plus price "
                   f"per sqft, CDOM and sale-to-list ratios from live Stellar MLS data.")

    chips = "\n            ".join(f'<span class="gbc-chip">{c}</span>' for c in cfg["chips"])
    figs = "\n          ".join(
        f'<figure class="gbc-fig {cls}"><img src="{src}" alt="{esc(alt)}" loading="lazy" /></figure>'
        for src, alt, cls in GALLERY)

    if lease:
        lease_a = (f"The MLS reports a {lease} minimum lease for {cfg['name']} on {lease_n} of {lease_total} "
                   f"listings. Always confirm current rental rules with the association before purchasing — "
                   f"condo documents change.")
    else:
        lease_a = ("The MLS does not consistently report a minimum lease period for this association. "
                   "Confirm directly with the association.")
    faq = [
        (f"What is the minimum lease period at {cfg['name']}?", lease_a),
        (f"How many units have sold recently at {cfg['name']}?",
         f"{len(headline)} units closed in the {HEADLINE_WINDOW_DAYS} days ending {as_of}, averaging {avg}."),
    ]
    faq_json = ",\n      ".join(
        "{ '@type': 'Question', name: %s, acceptedAnswer: { '@type': 'Answer', text: %s } }"
        % (repr_js(q), repr_js(a)) for q, a in faq)

    plain_blurb = (cfg["blurb"].replace("&amp;", "&").replace("&mdash;", "—")
                   .replace("&rsquo;", "’").replace("&ndash;", "–"))
    thin_note = ('<p class="gbc-note">A small but real sample — this association closes few units per period, '
                 'so single sales move the averages. Figures update from live MLS data.</p>') if len(headline) < 4 else ''
    ph_note = "s (Phases 1–6)" if cfg["short"] == "Beachfront" else ""

    return f'''---
// GENERATED by scripts/gen_gulf_bay_pages.py — baked static snapshot of Supabase MLS data.
// Re-run that script to refresh. Hand edits will be overwritten.
import BaseLayout from '@/layouts/BaseLayout.astro';

const description = {repr_js(description)};

const jsonLd = [
  {{
    '@type': 'Place',
    name: {repr_js(cfg["name"])},
    description: {repr_js(plain_blurb)},
    address: {{
      '@type': 'PostalAddress',
      streetAddress: {repr_js(cfg["street"])},
      addressLocality: 'Siesta Key',
      addressRegion: 'FL',
      postalCode: '34242',
      addressCountry: 'US',
    }},
  }},
  {{
    '@type': 'WebPage',
    name: {repr_js(cfg["name"] + " Condo Market — Siesta Key")},
    description: description,
    url: 'https://adamsonfl.com/siesta-key/{uid}',
    dateModified: '{date.today().isoformat()}',
    author: {{
      '@type': 'RealEstateAgent',
      name: 'Ryan Adamson',
      worksFor: {{ '@type': 'Organization', name: 'Coldwell Banker Realty — St. Armands' }},
    }},
  }},
  {{
    '@type': 'FAQPage',
    mainEntity: [
      {faq_json}
    ],
  }},
  {{
    '@type': 'BreadcrumbList',
    itemListElement: [
      {{ '@type': 'ListItem', position: 1, name: 'Home', item: 'https://adamsonfl.com/' }},
      {{ '@type': 'ListItem', position: 2, name: 'Siesta Key', item: 'https://adamsonfl.com/areas/siesta-key' }},
      {{ '@type': 'ListItem', position: 3, name: 'Gulf & Bay Club', item: 'https://adamsonfl.com/siesta-key/gulf-and-bay-club' }},
      {{ '@type': 'ListItem', position: 4, name: {repr_js(cfg["short"])}, item: 'https://adamsonfl.com/siesta-key/{uid}' }},
    ],
  }},
];
---

<BaseLayout title={repr_js(cfg["name"] + " Condos — Siesta Key")} description={{description}} jsonLd={{jsonLd}}>

  <section class="gbc-hero">
    <div class="gbc-hero-bg" style="background-image:url('{cfg["hero"]}');"></div>
    <div class="gbc-hero-overlay"></div>
    <div class="relative z-10 container">
      <p class="section-label text-cbgl-blue-light mb-3">Siesta Key &middot; 34242 &middot; {cfg["label"]}</p>
      <h1 class="font-display text-white mb-4">{esc(cfg["name"])}</h1>
      <p class="gbc-hero-tag">{cfg["blurb"]}</p>
      <p class="gbc-sister">Looking for the other association? <a href="/siesta-key/{cfg["sister_slug"]}">{esc(cfg["sister_name"])} &rarr;</a></p>
    </div>
  </section>

  <section class="section light-section">
    <div class="container">
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-10 lg:gap-12 items-start">
        <div>
          <h2 class="accent-underline mb-6">About {esc(cfg["short"])}</h2>
          <p class="gbc-about">{cfg["about"]}</p>
          <div class="flex flex-wrap gap-3 mt-6">
            {chips}
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3 lg:gap-4">
          {figs}
        </div>
      </div>
    </div>
  </section>

  <section class="section dark-section">
    <div class="container">
      <p class="section-label text-cbgl-blue-light mb-3">{cfg["short"]}</p>
      <h2 class="font-display mb-3">Closed Market Snapshot</h2>
      <p class="gbc-window">Closed sales &middot; past {HEADLINE_WINDOW_DAYS} days &middot; as of {as_of}</p>
      {render_stats(headline, lease, lease_n, lease_total)}
      {thin_note}

      <h3 class="font-display gbc-subhead">Transaction Ledger</h3>
      <p class="gbc-window">Every recorded closing in the last {LEDGER_WINDOW_DAYS // 30} months, most recent first.</p>
      {render_filters(ledger, uid)}
      {render_ledger(ledger, uid)}

      <h3 class="font-display gbc-subhead">Trailing 12-Month Trend</h3>
      <p class="gbc-window">Median closed price by quarter — a fuller read on where values are heading.</p>
      {render_trend(qs)}
    </div>
  </section>
{render_forms(cfg)}
  <section class="cbgl-section py-20">
    <div class="container text-center">
      <p class="section-label text-white/70 mb-3">Your Gulf &amp; Bay Club Team</p>
      <h2 class="font-display text-white mb-4" style="font-size:clamp(1.8rem,3.5vw,2.6rem);">Let&rsquo;s Talk Gulf &amp; Bay Club</h2>
      <p class="gbc-cta-text">Thinking about buying or selling in {esc(cfg["short"])}? <strong>Kelli and Ryan</strong> work this community together — they can pull current availability, share off-market opportunities, and give you a no-obligation valuation grounded in the real closed-sale data above.</p>
      <div class="gbc-team">
        <figure class="gbc-member">
          <img class="gbc-avatar" src="/images/kelli-eggen.jpg" width="800" height="800" alt="Kelli Eggen, Coldwell Banker Global Luxury" loading="lazy" decoding="async" />
          <figcaption>
            <span class="gbc-member-name">Kelli Eggen</span>
          </figcaption>
        </figure>
        <figure class="gbc-member">
          <img class="gbc-avatar" src="/images/ryan-adamson-square.jpg" width="800" height="800" alt="Ryan Adamson, Coldwell Banker Global Luxury" loading="lazy" decoding="async" />
          <figcaption>
            <span class="gbc-member-name">Ryan Adamson</span>
          </figcaption>
        </figure>
      </div>
      <p class="gbc-team-brokerage">Coldwell Banker Global Luxury</p>
      <div class="gbc-cta-btns">
        <a href="/contact" class="gbc-btn gbc-btn-gold">Contact the Team</a>
        <a href="/siesta-key/{cfg["sister_slug"]}" class="gbc-btn gbc-btn-outline">{esc(cfg["sister_name"])}</a>
      </div>
    </div>
  </section>

  <section class="section-sm dark-section">
    <div class="container-narrow">
      <p class="gbc-disc"><strong>Methodology &amp; data.</strong> Figures reflect closed transactions in the MLS for the {esc(cfg["name"])} subdivision{ph_note}, sourced from Stellar MLS via the Adamson Group data pipeline. "CDOM" is cumulative days on market; "SP/LP" is sale price to list price. The headline snapshot uses a {HEADLINE_WINDOW_DAYS}-day window; the transaction ledger and quarterly trend use trailing 12 months, computed as of {as_of}. "Minimum Lease Period" is the value most frequently reported on MLS listings in this association and is <em>not</em> a substitute for the condo documents — confirm current rental rules with the association before purchasing. Small communities close few units per quarter, so single sales can move averages meaningfully. Data is provided for informational purposes and is not a guarantee of value.</p>
      <p class="gbc-disc gbc-credit">Photography (placeholder — to be replaced): Siesta Key beach imagery via Wikimedia Commons — "Sarasota Sunset, Siesta Key" &amp; "Siesta Key sunset" by John Simpson and contributors (CC BY 3.0), "Siesta Key Beach" (CC BY 3.0), "Red Lifeguard Stand at Siesta Key Beach" (CC0). Not photographs of the {esc(cfg["short"])} buildings themselves.</p>
    </div>
  </section>

{STYLES}
{SCRIPTS}
</BaseLayout>
'''


HUB = '''---
// GENERATED by scripts/gen_gulf_bay_pages.py
// Hub for the two Gulf & Bay Club associations — preserves the originally indexed URL.
import BaseLayout from '@/layouts/BaseLayout.astro';

const description = 'Gulf & Bay Club on Siesta Key is two separate condo associations — the Gulf-front community on Midnight Pass Road (one-month minimum lease) and Gulf & Bay Club Bayside across the road (one-week minimum lease). Compare both markets with live Stellar MLS data.';

const jsonLd = [
  {
    '@type': 'WebPage',
    name: 'Gulf & Bay Club — Siesta Key Condo Market',
    description: description,
    url: 'https://adamsonfl.com/siesta-key/gulf-and-bay-club',
    dateModified: '%(today)s',
    author: { '@type': 'RealEstateAgent', name: 'Ryan Adamson', worksFor: { '@type': 'Organization', name: 'Coldwell Banker Realty — St. Armands' } },
  },
  {
    '@type': 'FAQPage',
    mainEntity: [
      {
        '@type': 'Question',
        name: 'What is the difference between Gulf & Bay Club and Gulf & Bay Club Bayside?',
        acceptedAnswer: { '@type': 'Answer', text: 'They are two separate condominium associations on Siesta Key, facing each other across Midnight Pass Road. Gulf & Bay Club (Phases 1-6) sits on 32 Gulf-front acres and carries a one-month minimum lease. Gulf & Bay Club Bayside sits on the intracoastal side, is materially less expensive per square foot, and permits a one-week minimum lease — making it the more rental-flexible of the two.' },
      },
    ],
  },
  {
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: 'https://adamsonfl.com/' },
      { '@type': 'ListItem', position: 2, name: 'Siesta Key', item: 'https://adamsonfl.com/areas/siesta-key' },
      { '@type': 'ListItem', position: 3, name: 'Gulf & Bay Club', item: 'https://adamsonfl.com/siesta-key/gulf-and-bay-club' },
    ],
  },
];

const sides = [
  {
    slug: 'gulf-and-bay-club-beachfront',
    eyebrow: 'Phases 1\\u20136 \\u00b7 Gulf-Front',
    name: 'Gulf & Bay Club Beachfront',
    copy: 'The flagship 32-acre Gulf-front community on Midnight Pass Road, directly on Siesta Key\\u2019s white quartz sand.',
    facts: %(bf_facts)s,
    img: 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/aa/Siesta_Key_Beach._Sarasota_-_panoramio.jpg/1920px-Siesta_Key_Beach._Sarasota_-_panoramio.jpg',
  },
  {
    slug: 'gulf-and-bay-club-bayside',
    eyebrow: 'Bayside \\u00b7 Intracoastal',
    name: 'Gulf & Bay Club Bayside',
    copy: 'The separate bayside association across the road \\u2014 a lower price of entry and a one-week minimum lease.',
    facts: %(bs_facts)s,
    img: 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/Siesta_key_sunset%%2C_Sarasota._-_panoramio.jpg/1920px-Siesta_key_sunset%%2C_Sarasota._-_panoramio.jpg',
  },
];
---

<BaseLayout title="Gulf & Bay Club Condos — Siesta Key" description={description} jsonLd={jsonLd}>
  <section class="gbc-hero">
    <div class="gbc-hero-bg" style="background-image:url('https://upload.wikimedia.org/wikipedia/commons/thumb/9/9f/SARASOTA_SUNSET._SIESTA_KEY_-_panoramio_-_JOHN_SIMPSON.jpg/1920px-SARASOTA_SUNSET._SIESTA_KEY_-_panoramio_-_JOHN_SIMPSON.jpg');"></div>
    <div class="gbc-hero-overlay"></div>
    <div class="relative z-10 container">
      <p class="section-label text-cbgl-blue-light mb-3">Siesta Key &middot; 34242 &middot; Condo Community</p>
      <h1 class="font-display text-white mb-4">Gulf &amp; Bay Club</h1>
      <p class="gbc-hero-tag">Gulf &amp; Bay Club is really <strong>two</strong> condominium associations facing each other across Midnight Pass Road — with different price points, different views, and different rental rules. Pick a side for its live sold-market data.</p>
    </div>
  </section>

  <section class="section light-section">
    <div class="container">
      <div class="gbc-hub-grid">
        {sides.map((s) => (
          <a href={`/siesta-key/${s.slug}`} class="gbc-hub-card">
            <div class="gbc-hub-img"><img src={s.img} alt={s.name} loading="lazy" /></div>
            <div class="gbc-hub-body">
              <span class="gbc-hub-eyebrow">{s.eyebrow}</span>
              <h2 class="gbc-hub-title">{s.name}</h2>
              <p class="gbc-hub-copy">{s.copy}</p>
              <ul class="gbc-hub-facts">
                {s.facts.map((f: string) => <li>{f}</li>)}
              </ul>
              <span class="gbc-hub-cta">View the market data &rarr;</span>
            </div>
          </a>
        ))}
      </div>
    </div>
  </section>

  <style is:global>
    .gbc-hero { position:relative; padding-top:9rem; padding-bottom:7rem; overflow:hidden; }
    .gbc-hero-bg { position:absolute; inset:0; background-size:cover; background-position:center; background-color:var(--color-black); }
    .gbc-hero-overlay { position:absolute; inset:0; background:linear-gradient(to bottom, rgba(0,0,0,0.55), rgba(0,0,0,0.45) 40%%, rgba(0,0,0,0.9)); }
    .gbc-hero-tag { font-size:1.15rem; color:rgba(255,255,255,0.8); max-width:44rem; line-height:1.7; }
    .gbc-hub-eyebrow { font-family:var(--font-accent); font-size:0.68rem; text-transform:uppercase; letter-spacing:0.12em; color:var(--color-text-muted); }
    .gbc-hub-grid { display:grid; grid-template-columns:1fr; gap:2rem; }
    @media (min-width:900px){ .gbc-hub-grid { grid-template-columns:1fr 1fr; } }
    .gbc-hub-card { display:block; border:1px solid rgba(0,0,0,0.08); border-radius:0.8rem; overflow:hidden; background:#fff; transition:transform .25s, box-shadow .25s; }
    .gbc-hub-card:hover { transform:translateY(-4px); box-shadow:0 12px 32px rgba(0,0,0,0.1); }
    .gbc-hub-img { aspect-ratio:16/9; overflow:hidden; }
    .gbc-hub-img img { width:100%%; height:100%%; object-fit:cover; transition:transform .7s; }
    .gbc-hub-card:hover .gbc-hub-img img { transform:scale(1.05); }
    .gbc-hub-body { padding:1.75rem 1.9rem 2rem; }
    .gbc-hub-title { font-family:var(--font-display); font-size:1.6rem; margin:0.5rem 0 0.7rem; color:var(--color-black); }
    .gbc-hub-copy { color:var(--color-text-muted); line-height:1.7; font-size:0.94rem; }
    .gbc-hub-facts { list-style:none; padding:0; margin:1.25rem 0 1.5rem; }
    .gbc-hub-facts li { font-size:0.85rem; color:var(--color-text-muted); padding:0.4rem 0 0.4rem 1.1rem; border-bottom:1px solid rgba(0,0,0,0.05); position:relative; }
    .gbc-hub-facts li::before { content:"\\2014"; position:absolute; left:0; color:var(--color-gold); }
    .gbc-hub-cta { font-family:var(--font-accent); font-size:0.75rem; text-transform:uppercase; letter-spacing:0.1em; color:var(--color-gold); font-weight:600; }
  </style>
</BaseLayout>
'''


def main():
    if not DATABASE_URL:
        sys.exit("DATABASE_URL not set (expected in .env)")
    as_of = date.today().strftime("%B ") + str(date.today().day) + ", " + str(date.today().year)
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    facts = {}
    for key, cfg in SIDES.items():
        headline = fetch(cur, cfg["where"], HEADLINE_WINDOW_DAYS)
        ledger = fetch(cur, cfg["where"], LEDGER_WINDOW_DAYS)
        lease, lease_n, lease_total = lease_consensus(cur, cfg["where"])
        qs = quarters(cur, cfg["where"])

        page = render_page(cfg, headline, ledger, lease, lease_n, lease_total, qs, as_of)
        out = OUT_DIR / f"{cfg['slug']}.astro"
        out.write_text(page, encoding="utf-8")
        print(f"  wrote {out.relative_to(PROJECT_ROOT)}  "
              f"({len(headline)} headline / {len(ledger)} ledger / lease={lease} {lease_n}/{lease_total})")

        prices = [float(r["current_price"]) for r in ledger if r["current_price"]]
        psf = [float(r["close_price_by_calculated_sqft"]) for r in ledger if r["close_price_by_calculated_sqft"]]
        facts[key] = [
            f"{len(ledger)} closed sales in the last 12 months",
            (f"Median {money(median(prices))} · ${int(round(mean(psf))):,}/sq ft") if prices and psf else "Market data below",
            f"{lease} minimum lease period" if lease else "Lease period not reported",
        ]

    hub = HUB % {
        "today": date.today().isoformat(),
        "bf_facts": "[" + ", ".join(repr_js(f) for f in facts["beachfront"]) + "]",
        "bs_facts": "[" + ", ".join(repr_js(f) for f in facts["bayside"]) + "]",
    }
    (OUT_DIR / "gulf-and-bay-club.astro").write_text(hub, encoding="utf-8")
    print("  wrote src/pages/siesta-key/gulf-and-bay-club.astro (hub)")

    cur.close()
    conn.close()
    print("done.")


if __name__ == "__main__":
    main()

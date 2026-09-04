#!/usr/bin/env python3
"""
Country Club Shores landing page -> src-lll/pages/country-club-shores.astro

Single-family, waterfront-segmented community page on longboatlido.com. Until
2026-09-04 this page was a hand-baked snapshot (numbers from a one-off query,
"as of August 27, 2026") that no job ever touched. It now regenerates the same
way the Gulf & Bay pages do: refresh_all_areas.py imports this module, calls
build_payload(conn), diffs the MATERIAL stats JSON against origin, and ships
the page + JSON in the daily commit only when the numbers actually moved.

Layout: the page markup lives in scripts/templates/country-club-shores.astro.tmpl
(copy edits go THERE, never in the generated .astro), with @@TOKEN@@ slots for
every data-driven block. This file only computes numbers and renders those
blocks. Segment rule (verified 2026-09-04 against the Aug 27 bake, 22/2/1):
  waterfront_features contains "Bay/Harbor" -> Open Bayfront (point lots)
  waterfront_features contains "Canal"      -> Canal Front
  otherwise                                 -> Garden (interior / GMD side)

  python scripts/gen_ccs_page.py            # write page + JSON
  python scripts/gen_ccs_page.py --dry-run  # print the stats, write nothing
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_FILE = PROJECT_ROOT / ".env"

SLUG = "country-club-shores"
REL_PAGE = f"src-lll/pages/{SLUG}.astro"
REL_DATA = "src/data/communities"
REL_TEMPLATE = f"scripts/templates/{SLUG}.astro.tmpl"

WHERE = ("subdivision_name ILIKE 'COUNTRY CLUB SHORES%%' "
         "AND property_sub_type = 'Single Family Residence'")
HEADLINE_WINDOW_DAYS = 180
LEDGER_WINDOW_DAYS = 365
THIN_N = 3

SEGMENTS = [
    ("canal",  "Canal Front",   "~90% of Country Club Shores"),
    ("bay",    "Open Bayfront", "the point lots"),
    ("garden", "Garden",        "interior / GMD side"),
]
SEG_LABEL = {k: v for k, v, _ in SEGMENTS}
LEDGER_LABEL = {"canal": "Canal Front", "bay": "Open Bayfront", "garden": "Garden (interior)"}


def load_env(path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env(ENV_FILE)

# ---------------------------------------------------------------- formatting
def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#x27;"))


def money(n):
    return "—" if n is None else f"${round(float(n)):,}"


def psf(n):
    return "—" if n is None else f"${round(float(n))}"


def pct1(n):
    # Decimal so a tie like 0.9405 rounds half-even to 94.0, matching the original bake
    from decimal import Decimal, ROUND_HALF_EVEN
    return "—" if n is None else f"{(Decimal(str(round(float(n), 6))) * 100).quantize(Decimal('0.1'), ROUND_HALF_EVEN)}%"


def pct0(n):
    return "—" if n is None else f"{round(float(n) * 100)}%"


def num(n):
    return "—" if n is None else f"{round(float(n))}"


def long_date(d):
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def short_date(d):
    return d.strftime("%m/%d/%y")


def bedbath(r):
    bf = r.get("bathrooms_full") or 0
    bh = r.get("bathrooms_half") or 0
    ba = bf + (0.5 if bh else 0)   # MLS convention: any half baths show as .5
    ba_s = f"{ba:g}"
    return f"{r.get('bedrooms_total') or 0} bd / {ba_s} ba"


def _f(x):
    return None if x is None else float(x)


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# --------------------------------------------------------------------- data
def segment(r):
    wf = r.get("waterfront_features") or ""
    if "Bay/Harbor" in wf:
        return "bay"
    if "Canal" in wf:
        return "canal"
    return "garden"


def fetch(cur, days, as_of):
    cur.execute(f"""
        SELECT listing_id, unparsed_address, close_date, current_price,
               bedrooms_total, bathrooms_full, bathrooms_half, living_area,
               waterfront_features, water_view, subdivision_name,
               close_price_by_calculated_sqft,
               cumulative_days_on_market,
               close_price_by_calculated_list_price_ratio AS sp_lp
          FROM raw_listings
         WHERE {WHERE}
           AND standard_status = 'Closed'
           AND close_date IS NOT NULL
           AND close_date >= %s AND close_date <= %s
         ORDER BY close_date DESC
    """, (as_of - timedelta(days=days), as_of))
    return [dict(r) for r in cur.fetchall()]


def dedupe_closed(rows):
    """Same sale under two listing_ids (see gen_gulf_bay_pages): address+price key,
    earliest close wins. Returns (rows, n_removed)."""
    seen, out, removed = set(), [], 0
    for r in sorted(rows, key=lambda x: (x["close_date"] or date.min)):
        addr = re.sub(r"\s+", "", (r["unparsed_address"] or "")).upper()
        key = (addr, None if r["current_price"] is None else round(float(r["current_price"])))
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        out.append(r)
    out.sort(key=lambda x: (x["close_date"] or date.min), reverse=True)
    return out, removed


def quarters(rows, as_of):
    by = {}
    for r in rows:
        d = r["close_date"]
        q = f"{d.year}-Q{(d.month - 1) // 3 + 1}"
        by.setdefault(q, []).append(r)
    cur_q = f"{as_of.year}-Q{(as_of.month - 1) // 3 + 1}"
    out = []
    for q in sorted(by):
        rs = by[q]
        out.append({"q": q, "n": len(rs),
                    "md": median([_f(r["current_price"]) for r in rs]),
                    "psf": median([_f(r["close_price_by_calculated_sqft"]) for r in rs]),
                    "toDate": q == cur_q})
    return out


def actives(cur):
    cur.execute(f"""
        SELECT COUNT(*) n,
               AVG(cumulative_days_on_market) avg_dom,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY cumulative_days_on_market) med_dom,
               MIN(current_price) min_p, MAX(current_price) max_p,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY current_price) med_p
          FROM raw_listings
         WHERE {WHERE} AND standard_status = 'Active'
    """)
    r = cur.fetchone()
    return {k: (_f(v) if k != "n" else int(v or 0)) for k, v in dict(r).items()} if r else {}


def compute(conn, as_of=None):
    import psycopg2.extras
    as_of = as_of or date.today()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ledger, dropped = dedupe_closed(fetch(cur, LEDGER_WINDOW_DAYS, as_of))
    for r in ledger:
        r["seg"] = segment(r)
    head_from = as_of - timedelta(days=HEADLINE_WINDOW_DAYS)
    headline = [r for r in ledger if r["close_date"] >= head_from]

    prices = [_f(r["current_price"]) for r in headline]
    # Headline tiles report MEDIANS (Ryan, 2026-09-04): matches the mailer and the
    # industry convention (Redfin, Realtor.com, Altos, NAR), and a single point-lot
    # sale cannot drag them. Means stay in the JSON as *_avg for anything still
    # reading them; the page does not print them.
    snap = {
        "n": len(headline),
        "mn": min(prices) if prices else None,
        "md": median(prices),
        "mx": max(prices) if prices else None,
        "psf": median([_f(r["close_price_by_calculated_sqft"]) for r in headline]),
        "cdom": median([_f(r["cumulative_days_on_market"]) for r in headline]),
        "splp": median([_f(r["sp_lp"]) for r in headline]),
        "price_avg": mean(prices),
        "psf_avg": mean([_f(r["close_price_by_calculated_sqft"]) for r in headline]),
        "cdom_avg": mean([_f(r["cumulative_days_on_market"]) for r in headline]),
        "splp_avg": mean([_f(r["sp_lp"]) for r in headline]),
    }
    segs = {}
    for key, _, _ in SEGMENTS:
        rs = [r for r in ledger if r["seg"] == key]
        ps = [_f(r["current_price"]) for r in rs]
        segs[key] = {
            "n": len(rs),
            "mn": min(ps) if ps else None, "md": median(ps), "mx": max(ps) if ps else None,
            "psf": median([_f(r["close_price_by_calculated_sqft"]) for r in rs]),
            "cdom": median([_f(r["cumulative_days_on_market"]) for r in rs]),
            "splp": median([_f(r["sp_lp"]) for r in rs]),
        }
    led = [{
        "addr": r["unparsed_address"], "bed": r["bedrooms_total"],
        "bf": r["bathrooms_full"], "bh": r["bathrooms_half"],
        "sqft": int(r["living_area"]) if r["living_area"] is not None else None,
        "price": _f(r["current_price"]), "psf": _f(r["close_price_by_calculated_sqft"]),
        "close": r["close_date"].isoformat(), "cdom": r["cumulative_days_on_market"],
        "splp": _f(r["sp_lp"]), "seg": r["seg"], "view": r["water_view"], "sub": r["subdivision_name"],
    } for r in ledger]
    stats = {
        "slug": SLUG, "name": "Country Club Shores", "asOf": as_of.isoformat(),
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "headlineWindowDays": HEADLINE_WINDOW_DAYS, "ledgerWindowDays": LEDGER_WINDOW_DAYS,
        "snap": snap, "segments": segs, "ledger": led, "dedupedRows": dropped,
        "trend": quarters(ledger, as_of), "actives": actives(cur),
    }
    return stats


VOLATILE_KEYS = ("asOf", "generatedAt")


def material(d):
    return {k: v for k, v in d.items() if k not in VOLATILE_KEYS}


# ------------------------------------------------------------------ render
def stat(value, label, sub=""):
    sub_html = f'<div class="gbc-stat-sub">{sub}</div>' if sub else ""
    return f'''<div class="gbc-stat">
        <div class="gbc-stat-value">{value}</div>
        <div class="gbc-stat-label">{label}</div>
        {sub_html}
      </div>'''


def render_stats(s):
    snap, segs = s["snap"], s["segments"]
    total = len(s["ledger"])
    canal_n = segs["canal"]["n"]
    share = f"{round(canal_n / total * 100)}%" if total else "—"
    tiles = [
        stat(snap["n"], "Closed Sales"),
        stat(money(snap["mn"]), "Min Sale Price"),
        stat(money(snap["md"]), "Median Sale Price"),
        stat(money(snap["mx"]), "Max Sale Price"),
        stat(psf(snap["psf"]), "Median Price / SqFt"),
        stat(num(snap["cdom"]), "Median Mkt Days", "cumulative"),
        stat(pct1(snap["splp"]), "Median Sale-to-List"),
        stat(share, "Canal-Front Share", f"{canal_n} of {total} sales, past 12 months"),
    ]
    return '<div class="gbc-stat-grid">' + "\n".join(tiles) + "\n</div>"


def render_segments(s):
    out = []
    for key, label, street in SEGMENTS:
        g = s["segments"][key]
        thin = ('<span class="gbc-bld-thin" title="Small sample: fewer than 3 closed sales in this window">*</span>'
                if 0 < g["n"] < THIN_N else "")
        out.append(f'''<tr>
        <td class="gbc-bld-id"><span class="gbc-bld-letter">{label}</span><span class="gbc-bld-street">{street}</span></td>
        <td class="gbc-num">{g["n"]}{thin}</td>
        <td class="gbc-num">{money(g["mn"])}</td>
        <td class="gbc-num gbc-bld-key">{money(g["md"])}</td>
        <td class="gbc-num">{money(g["mx"])}</td>
        <td class="gbc-num">{psf(g["psf"])}</td>
        <td class="gbc-num">{num(g["cdom"])}</td>
        <td class="gbc-num">{pct1(g["splp"])}</td>
      </tr>''')
    return "\n".join(out)


def render_ledger(s):
    out = []
    for r in s["ledger"]:
        sq = r["sqft"] or 0
        out.append(f'''<tr data-bed="{r["bed"] or 0}" data-sqft="{sq}">
        <td class="gbc-addr">{esc(r["addr"] or "")}</td>
        <td>{bedbath({"bedrooms_total": r["bed"], "bathrooms_full": r["bf"], "bathrooms_half": r["bh"]})}</td>
        <td class="gbc-num">{sq:,}</td>
        <td class="gbc-num">{money(r["price"])}</td>
        <td class="gbc-num">{psf(r["psf"])}</td>
        <td>{short_date(date.fromisoformat(r["close"]))}</td>
        <td class="gbc-num">{num(r["cdom"])}</td>
        <td class="gbc-num">{pct0(r["splp"])}</td>
        <td class="gbc-wv">{LEDGER_LABEL[r["seg"]]}</td>
      </tr>''')
    return "\n".join(out)


def render_trend(s):
    cols = []
    for q in s["trend"]:
        label = q["q"] + (" (to date)" if q.get("toDate") else "")
        cols.append(f'''<div class="gbc-trend-col">
          <div class="gbc-trend-period">{label}</div>
          <div class="gbc-trend-price">{money(q["md"])}</div>
          <div class="gbc-trend-meta">{q["n"]} sold &middot; {psf(q["psf"])}/sf</div>
        </div>''')
    return '<div class="gbc-trend-grid">' + "\n".join(cols) + "\n</div>"


def sq_range(s):
    sq = [r["sqft"] for r in s["ledger"] if r["sqft"]]
    if not sq:
        return 1000, 5000
    lo = (min(sq) // 100) * 100
    hi = -(-max(sq) // 100) * 100
    return int(lo), int(hi)


def _gh_raw(rel):
    tok = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPO", "Bonesbot/adamson-website")
    br = os.environ.get("GITHUB_BRANCH", "main")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/contents/{rel}?ref={br}",
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github.raw",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "agw/1.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8")


def load_template():
    """Local template first; otherwise the runner is executing a partial /tmp
    tree, so pull the template from origin (same source the runner uses)."""
    local = PROJECT_ROOT / REL_TEMPLATE
    if local.exists():
        return local.read_text(encoding="utf-8")
    return _gh_raw(REL_TEMPLATE)


def render_page(s, template=None):
    tpl = template or load_template()
    as_of = date.fromisoformat(s["asOf"])
    snap, segs = s["snap"], s["segments"]
    total = len(s["ledger"])
    lo, hi = sq_range(s)
    description = (f"Country Club Shores, Longboat Key (34228) single-family market: {snap['n']} closed sales "
                   f"in the last 180 days, median {money(snap['md'])}, with canal-front, open-bayfront and "
                   f"interior homes tracked separately, plus price per sqft, days on market and sale-to-list "
                   f"ratios from live Stellar MLS data.")
    faq_share = (f"Most of the neighborhood sits on deep-water canals: {segs['canal']['n']} of the {total} "
                 f"single-family closings in the 12 months ending {long_date(as_of)} were canal-front homes, "
                 f"with a small number of open-bayfront point lots and interior homes along Gulf of Mexico Drive.")
    faq_median = (f"Canal-front homes closed at a median of {money(segs['canal']['md'])} over the 12 months "
                  f"ending {long_date(as_of)}, while the rare open-bayfront homes commanded far more. "
                  f"See the on-page table for the full segment breakdown.")
    tokens = {
        "GENERATED_NOTE": (f"// GENERATED by scripts/gen_ccs_page.py on {s['generatedAt'][:10]} from the Supabase MLS "
                           f"snapshot as of {s['asOf']}. DO NOT hand-edit: copy changes go in "
                           f"scripts/templates/{SLUG}.astro.tmpl, then re-run the generator."),
        "DESCRIPTION": description.replace("'", "\\'"),
        "DATE_ISO": s["asOf"],
        "FAQ_CANAL_SHARE": faq_share.replace("'", "\\'"),
        "FAQ_CANAL_MEDIAN": faq_median.replace("'", "\\'"),
        "ASOF_LONG": long_date(as_of),
        "STAT_GRID": render_stats(s),
        "SEGMENT_ROWS": render_segments(s),
        "SQ_MIN": str(lo), "SQ_MAX": str(hi),
        "SQ_MIN_FMT": f"{lo:,}", "SQ_MAX_FMT": f"{hi:,}",
        "LEDGER_COUNT": str(total),
        "LEDGER_ROWS": render_ledger(s),
        "TREND_GRID": render_trend(s),
    }
    out = tpl
    for k, v in tokens.items():
        out = out.replace(f"@@{k}@@", v)
    left = re.findall(r"@@[A-Z_]+@@", out)
    if left:
        raise RuntimeError(f"unfilled template tokens: {sorted(set(left))}")
    return out


def build_payload(conn):
    """Contract shared with gen_gulf_bay_pages: ({repo_path: text}, {slug: stats})."""
    s = compute(conn)
    files = {
        REL_PAGE: render_page(s),
        f"{REL_DATA}/{SLUG}-stats.json": json.dumps(s, indent=1, default=str),
    }
    return files, {SLUG: s}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--as-of", help="YYYY-MM-DD, for reproducing an older bake")
    args = ap.parse_args()
    import psycopg2
    db = os.environ.get("DATABASE_URL", "")
    if not db:
        sys.exit("Missing DATABASE_URL")
    conn = psycopg2.connect(db)
    try:
        as_of = date.fromisoformat(args.as_of) if args.as_of else None
        s = compute(conn, as_of)
    finally:
        conn.close()
    print(f"as of {s['asOf']}: {s['snap']['n']} closed (180d), {len(s['ledger'])} in ledger, "
          f"segments " + ", ".join(f"{k}={v['n']}" for k, v in s["segments"].items())
          + (f", {s['dedupedRows']} duplicate row(s) dropped" if s["dedupedRows"] else ""))
    if args.dry_run:
        print(json.dumps(material(s)["snap"], indent=1, default=str))
        return
    page = render_page(s)
    (PROJECT_ROOT / REL_PAGE).write_text(page, encoding="utf-8")
    (PROJECT_ROOT / REL_DATA).mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / REL_DATA / f"{SLUG}-stats.json").write_text(json.dumps(s, indent=1, default=str), encoding="utf-8")
    print(f"wrote {REL_PAGE} and {REL_DATA}/{SLUG}-stats.json")


if __name__ == "__main__":
    main()

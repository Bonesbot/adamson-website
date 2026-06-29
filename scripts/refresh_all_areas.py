#!/usr/bin/env python3
"""
Self-throttling area-stats publisher.

Regenerates every area's stats JSON from Supabase, but only PUBLISHES to GitHub
(= triggers a Netlify build) when BOTH: (a) it's been >= --min-days since the
last publish, and (b) the data actually changed. All changed files go in ONE
commit (Git Trees API) = exactly one Netlify build per publish.

Designed to be called by the daily mls-export job: it runs daily but builds the
website only every few days, so Netlify build minutes aren't burned daily.

It records the last build number + date in a local state file (not pushed) and
patches the run status JSON with a `publish` block (build number, date, next
eligible date, email line) the daily email renders.

  python scripts/refresh_all_areas.py --status-out /path/last-run.json
  python scripts/refresh_all_areas.py --dry-run
  python scripts/refresh_all_areas.py --force          # publish now regardless of cadence

Reads DATABASE_URL + GITHUB_TOKEN/REPO/BRANCH from .env at repo root.
"""
import argparse, base64, datetime as dt, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
ENV = ROOT / ".env"
for line in (ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())

import psycopg2
from fetch_area_summary import compute_summary

DATABASE_URL = os.environ.get("DATABASE_URL", "")
TOK = os.environ.get("GITHUB_TOKEN", ""); REPO = os.environ.get("GITHUB_REPO", "Bonesbot/adamson-website"); BR = os.environ.get("GITHUB_BRANCH", "main")
DATA_DIR = ROOT / "src" / "data"
STATE_DEFAULT = ROOT / "logs" / "publish-state.json"

def slugs():
    return [a["slug"] for a in json.loads((DATA_DIR / "areas.json").read_text(encoding="utf-8"))["areas"]]

def material(d):
    return {k: v for k, v in d.items() if k != "lastUpdated"}

def load_state(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return {"buildNumber": 0, "lastBuildDate": None}

def save_state(p, st):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(st, indent=2), encoding="utf-8")

def patch_status(status_out, publish):
    if not status_out: return
    try:
        d = json.loads(Path(status_out).read_text(encoding="utf-8")) if Path(status_out).exists() else {}
    except Exception:
        d = {}
    d["publish"] = publish
    try: Path(status_out).write_text(json.dumps(d, indent=2, default=str), encoding="utf-8")
    except Exception as e: print(f"[WARN] could not patch status: {e}", file=sys.stderr)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status-out"); ap.add_argument("--state", default=str(STATE_DEFAULT))
    ap.add_argument("--min-days", type=int, default=3)
    ap.add_argument("--force", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not DATABASE_URL: sys.exit("Missing DATABASE_URL")

    today = dt.date.today()
    st = load_state(args.state)
    last_date = None
    if st.get("lastBuildDate"):
        try: last_date = dt.date.fromisoformat(st["lastBuildDate"])
        except Exception: last_date = None
    days_since = (today - last_date).days if last_date else 9999
    next_eligible = (last_date + dt.timedelta(days=args.min_days)).isoformat() if last_date else today.isoformat()

    # detect material changes (in memory; do NOT write to disk unless we publish)
    conn = psycopg2.connect(DATABASE_URL)
    changed = {}
    try:
        for slug in slugs():
            data = compute_summary(slug, conn)
            path = DATA_DIR / f"{slug}-stats.json"
            old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            if old is None or material(old) != material(data):
                changed[f"src/data/{slug}-stats.json"] = json.dumps(data, indent=2)
    finally:
        conn.close()

    throttled = (not args.force) and days_since < args.min_days
    build_no = st.get("buildNumber", 0)

    if not changed:
        action = "no_changes"
        line = f"Website: no data changes today — no build (last build #{build_no} on {st.get('lastBuildDate') or 'n/a'})."
    elif throttled:
        action = "throttled"
        line = f"Website: {len(changed)} area(s) changed but holding for the {args.min_days}-day cadence — last build #{build_no} on {st.get('lastBuildDate')}, next eligible {next_eligible}."
    else:
        action = "publish"  # will publish below
        line = f"Website: would publish {len(changed)} area(s) now (build #{build_no+1})."

    print(f"days_since_last={days_since} changed={len(changed)} action={action}")
    for rel in changed: print("  CHANGED:", rel.split('/')[-1])

    if args.dry_run or action in ("no_changes", "throttled"):
        publish = {"action": action, "buildNumber": build_no, "lastBuildDate": st.get("lastBuildDate"),
                   "nextEligibleDate": next_eligible, "daysSinceLast": days_since,
                   "areasPending": [r.split('/')[-1].replace('-stats.json','') for r in changed], "commit": None, "emailLine": line}
        patch_status(args.status_out, publish)
        print(line); return

    # ---- PUBLISH: write changed files + single bundled commit (one build) ----
    for rel, text in changed.items():
        (ROOT / rel).write_text(text, encoding="utf-8")
    import requests
    if not TOK: sys.exit("Missing GITHUB_TOKEN")
    s = requests.Session(); s.headers.update({"Authorization": f"Bearer {TOK}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "agw/1.0"})
    api = f"https://api.github.com/repos/{REPO}"
    base_sha = s.get(f"{api}/git/ref/heads/{BR}", timeout=20).json()["object"]["sha"]
    base_tree = s.get(f"{api}/git/commits/{base_sha}", timeout=20).json()["tree"]["sha"]
    tree = []
    for rel, text in changed.items():
        blob = s.post(f"{api}/git/blobs", json={"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"}, timeout=30).json()
        tree.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    new_tree = s.post(f"{api}/git/trees", json={"base_tree": base_tree, "tree": tree}, timeout=30).json()["sha"]
    build_no += 1
    msg = f"Daily MLS refresh {today.isoformat()} — area stats build #{build_no} ({len(changed)} areas)"
    commit = s.post(f"{api}/git/commits", json={"message": msg, "tree": new_tree, "parents": [base_sha]}, timeout=30).json()
    s.patch(f"{api}/git/refs/heads/{BR}", json={"sha": commit["sha"]}, timeout=30)
    sha7 = commit["sha"][:7]

    st = {"buildNumber": build_no, "lastBuildDate": today.isoformat(), "lastCommit": sha7}
    save_state(args.state, st)
    line = f"Website: published build #{build_no} ({today.isoformat()}), {len(changed)} areas updated, commit {sha7} — Netlify rebuilding (next build no earlier than {(today + dt.timedelta(days=args.min_days)).isoformat()})."
    publish = {"action": "published", "buildNumber": build_no, "buildDate": today.isoformat(),
               "nextEligibleDate": (today + dt.timedelta(days=args.min_days)).isoformat(),
               "areasUpdated": [r.split('/')[-1].replace('-stats.json','') for r in changed], "commit": sha7, "emailLine": line}
    patch_status(args.status_out, publish)
    print(f"Published 1 commit {sha7} ({len(changed)} files) = ONE build. build #{build_no}.")

if __name__ == "__main__":
    main()

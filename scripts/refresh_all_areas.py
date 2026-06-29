#!/usr/bin/env python3
"""
Self-throttling, remote-aware area-stats publisher.

Generates each area's stats JSON from Supabase and compares against the REMOTE
(GitHub) copy — correct even when run from /tmp (FUSE-bypass) or when the local
clone is stale. Publishes ALL changed files in ONE commit (Git Trees API = one
Netlify build) but only when it's been >= --min-days since the last build AND
data actually changed. Remembers the last build number + date in --state.

Patches --status-out with a `publish` block (build number, date, next-eligible,
emailLine) for the daily reconciliation email.

  python scripts/refresh_all_areas.py --status-out <last-run.json> --state <persistent path>
  python scripts/refresh_all_areas.py --dry-run
  python scripts/refresh_all_areas.py --force
"""
import argparse, base64, datetime as dt, json, os, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
for cand in [ROOT / ".env", Path(__file__).resolve().parent / ".env"]:
    if cand.exists():
        for line in cand.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
        break

import psycopg2
from fetch_area_summary import compute_summary

DB = os.environ.get("DATABASE_URL", ""); TOK = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPO", "Bonesbot/adamson-website"); BR = os.environ.get("GITHUB_BRANCH", "main")
API = f"https://api.github.com/repos/{REPO}"
H = {"Authorization": f"Bearer {TOK}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "agw/1.0"}

def gh(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, method=method, headers=dict(H))
    if data: req.add_header("Content-Type", "application/json")
    return json.load(urllib.request.urlopen(req, data=data, timeout=40))

def gh_raw(path):
    req = urllib.request.Request(f"{API}/contents/{path}?ref={BR}", headers={**H, "Accept": "application/vnd.github.raw"})
    try: return urllib.request.urlopen(req, timeout=30).read().decode()
    except Exception: return None

def slugs():
    local = ROOT / "src" / "data" / "areas.json"
    txt = local.read_text() if local.exists() else gh_raw("src/data/areas.json")
    return [a["slug"] for a in json.loads(txt)["areas"]]

material = lambda d: {k: v for k, v in d.items() if k != "lastUpdated"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status-out"); ap.add_argument("--state", default=str(ROOT / "logs" / "publish-state.json"))
    ap.add_argument("--min-days", type=int, default=3); ap.add_argument("--force", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--heartbeat", default=str(ROOT / "logs" / "daily-heartbeat.json"))
    args = ap.parse_args()
    if not DB: sys.exit("Missing DATABASE_URL")
    if not TOK: sys.exit("Missing GITHUB_TOKEN")

    today = dt.date.today()
    try: st = json.loads(Path(args.state).read_text())
    except Exception: st = {"buildNumber": 0, "lastBuildDate": None}
    last = None
    if st.get("lastBuildDate"):
        try: last = dt.date.fromisoformat(st["lastBuildDate"])
        except Exception: pass
    days_since = (today - last).days if last else 9999
    next_elig = (last + dt.timedelta(days=args.min_days)).isoformat() if last else today.isoformat()
    build_no = st.get("buildNumber", 0)

    conn = psycopg2.connect(DB); changed = {}
    try:
        for slug in slugs():
            data = compute_summary(slug, conn)
            remote = gh_raw(f"src/data/{slug}-stats.json")
            robj = json.loads(remote) if remote else None
            if robj is None or material(robj) != material(data):
                changed[f"src/data/{slug}-stats.json"] = json.dumps(data, indent=2)
    finally:
        conn.close()

    throttled = (not args.force) and days_since < args.min_days
    if not changed:
        action, line = "no_changes", f"Website: no data changes — no build (last build #{build_no} on {st.get('lastBuildDate') or 'n/a'})."
    elif throttled:
        action, line = "throttled", f"Website: {len(changed)} area(s) changed but holding for the {args.min_days}-day cadence — last build #{build_no} on {st.get('lastBuildDate')}, next eligible {next_elig}."
    else:
        action, line = "publish", f"Website: would publish {len(changed)} area(s) (build #{build_no+1})."

    print(f"days_since={days_since} changed={len(changed)} action={action}")
    for r in changed: print("  CHANGED:", r.split('/')[-1])

    def patch(pub):
        if not args.status_out: return
        try: d = json.loads(Path(args.status_out).read_text()) if Path(args.status_out).exists() else {}
        except Exception: d = {}
        d["publish"] = pub
        try: Path(args.status_out).write_text(json.dumps(d, indent=2, default=str))
        except Exception as e: print(f"[WARN] status patch failed: {e}", file=sys.stderr)

    def heartbeat(act):
        if args.dry_run: return
        try:
            Path(args.heartbeat).parent.mkdir(parents=True, exist_ok=True)
            Path(args.heartbeat).write_text(json.dumps({"date": today.isoformat(), "action": act, "buildNumber": build_no, "nextEligibleDate": next_elig}, indent=2))
        except Exception as e: print(f"[WARN] heartbeat write failed: {e}", file=sys.stderr)

    if args.dry_run or action in ("no_changes", "throttled"):
        heartbeat(action)
        patch({"action": action, "buildNumber": build_no, "lastBuildDate": st.get("lastBuildDate"), "nextEligibleDate": next_elig,
               "daysSinceLast": days_since, "areasPending": [r.split('/')[-1].replace('-stats.json','') for r in changed], "commit": None, "emailLine": line})
        print(line); return

    # ---- PUBLISH: one bundled commit = one Netlify build ----
    base = gh("GET", f"/git/ref/heads/{BR}")["object"]["sha"]
    btree = gh("GET", f"/git/commits/{base}")["tree"]["sha"]
    tree = []
    for rel, text in changed.items():
        blob = gh("POST", "/git/blobs", {"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"})
        tree.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    nt = gh("POST", "/git/trees", {"base_tree": btree, "tree": tree})["sha"]
    build_no += 1
    msg = f"Daily MLS refresh {today.isoformat()} — area stats build #{build_no} ({len(changed)} areas)"
    commit = gh("POST", "/git/commits", {"message": msg, "tree": nt, "parents": [base]})
    gh("PATCH", f"/git/refs/heads/{BR}", {"sha": commit["sha"]}); sha7 = commit["sha"][:7]
    Path(args.state).parent.mkdir(parents=True, exist_ok=True)
    Path(args.state).write_text(json.dumps({"buildNumber": build_no, "lastBuildDate": today.isoformat(), "lastCommit": sha7}, indent=2))
    heartbeat("published")
    line = f"Website: published build #{build_no} ({today.isoformat()}), {len(changed)} areas, commit {sha7} — Netlify rebuilding (next build no earlier than {(today + dt.timedelta(days=args.min_days)).isoformat()})."
    patch({"action": "published", "buildNumber": build_no, "buildDate": today.isoformat(), "nextEligibleDate": (today + dt.timedelta(days=args.min_days)).isoformat(),
           "areasUpdated": [r.split('/')[-1].replace('-stats.json','') for r in changed], "commit": sha7, "emailLine": line})
    print(line)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Self-throttling, remote-aware publisher for area stats AND community pages.

Generates each area's stats JSON from Supabase and compares against the REMOTE
(GitHub) copy — correct even when run from /tmp (FUSE-bypass) or when the local
clone is stale. Publishes ALL changed files in ONE commit (Git Trees API = one
Netlify build) but only when it's been >= --min-days since the last build AND
data actually changed. Remembers the last build number + date in --state.

As of 2026-08-09 this also republishes the Gulf & Bay community pages via
gen_gulf_bay_pages.build_payload(). Community change detection compares the
*material* stats JSON (as-of date excluded) so a day with no new sales produces
no commit and therefore no Netlify build — the point being that daily freshness
should cost credits only on days the market actually moved.

Everything still lands in ONE commit = ONE Netlify build, and --min-days now
defaults to 1 (Netlify Pro bills a flat ~15 credits per production deploy, so a
daily build is ~465 credits/month against a 3,000 allowance; the old 3-day
cadence was guarding a budget that was running at 30% utilisation).

After pushing, the deploy is verified against the Netlify API (needs
NETLIFY_AUTH_TOKEN; degrades to "unverified" without it) and the outcome is
written into the publish block + emailLine for the daily reconciliation email.

Patches --status-out with a `publish` block (build number, date, next-eligible,
emailLine) for the daily reconciliation email.

  python scripts/refresh_all_areas.py --status-out <last-run.json> --state <persistent path>
  python scripts/refresh_all_areas.py --dry-run
  python scripts/refresh_all_areas.py --force
"""
import argparse, base64, datetime as dt, json, os, sys, time, urllib.request
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
# The community generator is imported, not inlined. The daily runner executes
# this file from a /tmp copy fetched from origin/main, and the set of files it
# fetches is defined in the job's SKILL.md — outside this repo. If
# gen_gulf_bay_pages.py is not among them, a plain import fails and community
# pages would silently stop publishing. That silent-skip is exactly what left the
# Gulf & Bay pages 19 days stale, so this does NOT rely on the runner: on import
# failure it fetches the canonical script from origin/main itself (same source
# the runner uses) and loads it. `communities_via` records which path was taken
# and is reported in the publish block.
communities = None
communities_via = None
try:
    import gen_gulf_bay_pages as communities
    communities_via = "local"
except Exception as _e:
    print(f"[INFO] community generator not on path ({_e}); fetching from origin/{BR}", file=sys.stderr)

DB = os.environ.get("DATABASE_URL", ""); TOK = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPO", "Bonesbot/adamson-website"); BR = os.environ.get("GITHUB_BRANCH", "main")
NETLIFY_TOKEN = os.environ.get("NETLIFY_AUTH_TOKEN", "")
NETLIFY_SITE = os.environ.get("NETLIFY_SITE_ID", "15e01fe1-523b-40a8-86ad-4f6521fa87a8")  # bonesbot -> adamsonfl.com
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

def _load_communities_from_main():
    """Fetch scripts/gen_gulf_bay_pages.py from origin/<BR> and load it.

    Fallback for when the runner's /tmp tree does not include the generator.
    Returns (module|None, how). Never raises — area stats must publish regardless.
    """
    import importlib.util, tempfile
    try:
        src = gh_raw("scripts/gen_gulf_bay_pages.py")
        if not src:
            return None, "unavailable: not found on origin"
        tmp = Path(tempfile.mkdtemp(prefix="agw_comm_")) / "gen_gulf_bay_pages.py"
        tmp.write_text(src, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("gen_gulf_bay_pages", tmp)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["gen_gulf_bay_pages"] = mod
        spec.loader.exec_module(mod)
        # the generator resolves output paths from its own __file__; point it at
        # this repo instead of the throwaway temp dir
        mod.PROJECT_ROOT = ROOT
        return mod, "origin"
    except Exception as e:
        print(f"[WARN] could not load community generator from origin: {e}", file=sys.stderr)
        return None, f"unavailable: {type(e).__name__}"


def verify_netlify(sha, timeout_s=420, poll_s=15):
    """Poll Netlify for the deploy triggered by `sha` and report the outcome.

    Returns a dict always — this must never raise, because a reporting failure
    must not turn a successful publish into a failed run. Without a token it
    reports state="unverified" rather than pretending success.
    """
    out = {"state": "unverified", "deployId": None, "url": None, "seconds": None,
           "error": None, "adminUrl": f"https://app.netlify.com/projects/bonesbot/deploys"}
    if not NETLIFY_TOKEN:
        out["error"] = "NETLIFY_AUTH_TOKEN not set"
        return out
    api = f"https://api.netlify.com/api/v1/sites/{NETLIFY_SITE}/deploys?per_page=20"
    hdr = {"Authorization": f"Bearer {NETLIFY_TOKEN}", "User-Agent": "agw/1.0"}
    started = time.time()
    try:
        while time.time() - started < timeout_s:
            req = urllib.request.Request(api, headers=hdr)
            deploys = json.load(urllib.request.urlopen(req, timeout=30))
            match = next((d for d in deploys
                          if (d.get("commit_ref") or "").startswith(sha)), None)
            if match:
                out["deployId"] = match.get("id")
                out["url"] = match.get("deploy_ssl_url") or match.get("deploy_url")
                state = match.get("state")
                if state in ("ready", "error", "rejected", "skipped"):
                    out["state"] = state
                    out["seconds"] = int(time.time() - started)
                    if state != "ready":
                        out["error"] = (match.get("error_message") or "")[:300]
                    return out
                out["state"] = state or "building"
            time.sleep(poll_s)
        out["state"] = "timeout"
        out["error"] = f"still building after {timeout_s}s"
    except Exception as e:
        out["state"] = "unverified"
        out["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return out


def slugs():
    local = ROOT / "src" / "data" / "areas.json"
    txt = local.read_text() if local.exists() else gh_raw("src/data/areas.json")
    return [a["slug"] for a in json.loads(txt)["areas"]]

material = lambda d: {k: v for k, v in d.items() if k != "lastUpdated"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status-out"); ap.add_argument("--state", default=str(ROOT / "logs" / "publish-state.json"))
    ap.add_argument("--min-days", type=int, default=1); ap.add_argument("--force", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--heartbeat", default=str(ROOT / "logs" / "daily-heartbeat.json"))
    ap.add_argument("--skip-communities", action="store_true", help="area stats only")
    ap.add_argument("--no-verify", action="store_true", help="do not wait on the Netlify deploy")
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

    conn = psycopg2.connect(DB); changed = {}; community_changed = []
    try:
        for slug in slugs():
            data = compute_summary(slug, conn)
            remote = gh_raw(f"src/data/{slug}-stats.json")
            robj = json.loads(remote) if remote else None
            if robj is None or material(robj) != material(data):
                changed[f"src/data/{slug}-stats.json"] = json.dumps(data, indent=2)

        # ---- community landing pages (Gulf & Bay today; the registry is SIDES) ----
        global communities, communities_via
        if communities is None and not args.skip_communities:
            communities, communities_via = _load_communities_from_main()
        # One .astro page bakes its numbers in, so we cannot diff it directly —
        # the as-of date alone would differ every day and force a build. Diff the
        # MATERIAL stats JSON instead, and only ship the pages when it moved.
        if communities is not None and not args.skip_communities:
            try:
                files, stats = communities.build_payload(conn)
                for slug, data in stats.items():
                    rel_json = f"{communities.REL_DATA}/{slug}-stats.json"
                    remote = gh_raw(rel_json)
                    robj = json.loads(remote) if remote else None
                    if robj is None or communities.material(robj) != communities.material(data):
                        community_changed.append(slug)
                if community_changed:
                    # ship the whole community payload together (pages + hub + json)
                    # so the hub's summary facts can never disagree with the pages
                    changed.update(files)
            except Exception as e:
                communities_via = f"failed: {type(e).__name__}: {str(e)[:120]}"
                print(f"[WARN] community refresh failed, continuing with areas: {e}", file=sys.stderr)
    finally:
        conn.close()

    throttled = (not args.force) and days_since < args.min_days
    if not changed:
        action, line = "no_changes", f"Website: no data changes — no build (last build #{build_no} on {st.get('lastBuildDate') or 'n/a'})."
    elif throttled:
        action, line = "throttled", f"Website: {len(changed)} file(s) changed but holding for the {args.min_days}-day cadence — last build #{build_no} on {st.get('lastBuildDate')}, next eligible {next_elig}."
    else:
        action, line = "publish", f"Website: would publish {len(changed)} file(s) (build #{build_no+1})."

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
               "daysSinceLast": days_since, "communitiesVia": communities_via, "areasPending": [r.split('/')[-1].replace('-stats.json','') for r in changed], "commit": None, "emailLine": line})
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
    n_areas = sum(1 for r in changed if r.startswith("src/data/") and "/communities/" not in r)
    parts = [f"{n_areas} areas"] + ([f"{len(community_changed)} communities"] if community_changed else [])
    msg = f"Daily MLS refresh {today.isoformat()} — build #{build_no} ({', '.join(parts)})"
    commit = gh("POST", "/git/commits", {"message": msg, "tree": nt, "parents": [base]})
    gh("PATCH", f"/git/refs/heads/{BR}", {"sha": commit["sha"]}); sha7 = commit["sha"][:7]
    Path(args.state).parent.mkdir(parents=True, exist_ok=True)
    Path(args.state).write_text(json.dumps({"buildNumber": build_no, "lastBuildDate": today.isoformat(), "lastCommit": sha7}, indent=2))
    heartbeat("published")

    # ---- confirm Netlify actually built it (the commit is not the outcome) ----
    nl = {"state": "skipped", "error": None, "deployId": None, "url": None, "seconds": None}
    if not args.no_verify:
        print(f"waiting on Netlify deploy for {sha7} ...")
        nl = verify_netlify(commit["sha"])
        print(f"netlify: state={nl['state']} deploy={nl.get('deployId')} secs={nl.get('seconds')}")

    verdict = {
        "ready":      lambda: f"Netlify build SUCCEEDED in {nl['seconds']}s (deploy {str(nl.get('deployId'))[:8]}) — live on adamsonfl.com.",
        "error":      lambda: f"Netlify build FAILED — {nl.get('error') or 'no message'}. Site still serving the previous deploy. {nl.get('adminUrl','https://app.netlify.com/projects/bonesbot/deploys')}",
        "rejected":   lambda: f"Netlify build REJECTED — {nl.get('error') or 'no message'}. {nl.get('adminUrl','https://app.netlify.com/projects/bonesbot/deploys')}",
        "skipped":    lambda: "Netlify build not verified (verification disabled).",
        "timeout":    lambda: f"Netlify build still running after {nl.get('error')} — check {nl.get('adminUrl','https://app.netlify.com/projects/bonesbot/deploys')}.",
        "unverified": lambda: f"Netlify build NOT VERIFIED ({nl.get('error')}) — commit pushed, outcome unknown. {nl.get('adminUrl','https://app.netlify.com/projects/bonesbot/deploys')}",
    }.get(nl["state"], lambda: f"Netlify state '{nl['state']}' — {nl.get('adminUrl','https://app.netlify.com/projects/bonesbot/deploys')}")()

    scope = f"{n_areas} area(s)" + (f" + {len(community_changed)} community page(s) ({', '.join(community_changed)})" if community_changed else "")
    line = (f"Website: published build #{build_no} ({today.isoformat()}), {scope}, commit {sha7}. {verdict} "
            f"Next build no earlier than {(today + dt.timedelta(days=args.min_days)).isoformat()}.")
    patch({"action": "published", "buildNumber": build_no, "buildDate": today.isoformat(),
           "nextEligibleDate": (today + dt.timedelta(days=args.min_days)).isoformat(),
           "areasUpdated": [r.split('/')[-1].replace('-stats.json','') for r in changed
                            if r.startswith("src/data/") and "/communities/" not in r],
           "communitiesUpdated": community_changed, "communitiesVia": communities_via,
           "filesPublished": sorted(changed.keys()),
           "commit": sha7, "netlify": nl, "buildOk": nl["state"] == "ready",
           "emailLine": line})
    if communities_via is None or str(communities_via).startswith(("unavailable", "failed")):
        line += f" WARNING: community pages did NOT refresh ({communities_via}) — Gulf & Bay is going stale."
    print(line)
    # a failed Netlify build is a failed publish — make the run reflect it
    if nl["state"] in ("error", "rejected"):
        sys.exit(2)

if __name__ == "__main__":
    main()

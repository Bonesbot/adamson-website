#!/usr/bin/env python3
"""
SRQmap "Events This Week" publisher.

Used by the daily `srqmap-events` scheduled task (and safe to run by hand).
Contract:
  * The agent researches local events and writes a CANDIDATES file — a JSON
    array of event objects (the full desired set for the coming week).
  * This script validates them, drops anything already past, dedupes,
    compares against what's live on origin/main, and — only if changed —
    PUTs src/data/srqmap-events.json back via the GitHub Contents API
    (which triggers a Netlify rebuild).
  * The SRQmap page also drops past events at build time, so a missed run
    degrades gracefully.

Event object schema (all strings unless noted):
  name*, venue, address, lat* (float), lng* (float),
  start_date* (YYYY-MM-DD), end_date (YYYY-MM-DD, default start_date),
  dates_label, hours_label, blurb*, website*,
  photos (list of URLs, may be empty), photo_credit, source, added

Usage:
  python publish_srqmap_events.py --candidates events.json [--dry-run]
Env (or --env FILE, default: repo .env):
  GITHUB_TOKEN, GITHUB_REPO (Bonesbot/adamson-website), GITHUB_BRANCH (main)

NEVER edit src/data/srqmap-events.json by hand or via working-tree writes —
this file is machine-owned and pushed via the Contents API only
(see PROJECT_SPEC.md FUSE-corruption rules).
"""
import argparse, base64, datetime, json, os, re, sys, urllib.request

PATH = "src/data/srqmap-events.json"
MAX_EVENTS = 5
LAT_RANGE = (26.9, 27.8)
LNG_RANGE = (-83.0, -82.2)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REQUIRED = ("name", "lat", "lng", "start_date", "blurb", "website")

def today_et():
    return (datetime.datetime.utcnow() - datetime.timedelta(hours=5)).date()

def load_env(path):
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

def gh(url, token, data=None, method="GET"):
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "srqmap-events/1.0",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def validate(e, today):
    errs = []
    for k in REQUIRED:
        if not e.get(k) and e.get(k) != 0:
            errs.append("missing " + k)
    try:
        lat, lng = float(e["lat"]), float(e["lng"])
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LNG_RANGE[0] <= lng <= LNG_RANGE[1]):
            errs.append("lat/lng outside Sarasota area: %s,%s" % (lat, lng))
    except Exception:
        errs.append("bad lat/lng")
    sd, ed = e.get("start_date", ""), e.get("end_date") or e.get("start_date", "")
    for d in (sd, ed):
        if not DATE_RE.match(d or ""):
            errs.append("bad date: %r" % d)
    if not errs:
        s = datetime.date.fromisoformat(sd); en = datetime.date.fromisoformat(ed)
        if en < s:
            errs.append("end_date before start_date")
        if s > today + datetime.timedelta(days=7):
            errs.append("starts more than 7 days out")
        if en < today:
            errs.append("already past")
    if e.get("photos") and not isinstance(e["photos"], list):
        errs.append("photos must be a list")
    return errs

def normalize(e):
    out = {
        "name": e["name"].strip(),
        "venue": (e.get("venue") or "").strip(),
        "address": (e.get("address") or "").strip(),
        "lat": round(float(e["lat"]), 5),
        "lng": round(float(e["lng"]), 5),
        "start_date": e["start_date"],
        "end_date": e.get("end_date") or e["start_date"],
        "dates_label": (e.get("dates_label") or "").strip(),
        "hours_label": (e.get("hours_label") or "").strip(),
        "blurb": e["blurb"].strip(),
        "website": e["website"].strip(),
        "photos": [p for p in (e.get("photos") or []) if isinstance(p, str) and p.strip()],
        "photo_credit": (e.get("photo_credit") or "").strip(),
        "source": (e.get("source") or "").strip(),
        "added": e.get("added") or today_et().isoformat(),
    }
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--env", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_env(args.env or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO", "Bonesbot/adamson-website")
    branch = os.environ.get("GITHUB_BRANCH", "main")
    if not token:
        sys.exit("GITHUB_TOKEN not set (pass --env pointing at the repo .env)")

    today = today_et()
    cands = json.load(open(args.candidates, encoding="utf-8"))
    if not isinstance(cands, list):
        sys.exit("candidates file must be a JSON array")

    events, rejected = [], []
    seen = set()
    for e in cands:
        errs = validate(e, today)
        if errs:
            rejected.append((e.get("name", "?"), errs)); continue
        n = normalize(e)
        key = (n["name"].lower(), n["start_date"])
        if key in seen:
            continue
        seen.add(key); events.append(n)
    events.sort(key=lambda x: (x["start_date"], x["name"]))
    events = events[:MAX_EVENTS]

    for name, errs in rejected:
        print("REJECTED: %s — %s" % (name, "; ".join(errs)))
    if len(events) < 3:
        print("WARNING: only %d valid events (target 3-4)" % len(events))
    if not events:
        sys.exit("refusing to publish an empty events list")

    api = "https://api.github.com/repos/%s/contents/%s" % (repo, PATH)
    cur = None
    try:
        cur = gh(api + "?ref=" + branch, token)
    except Exception as ex:
        print("note: could not fetch current file (%s) — will create" % ex)

    new_body = json.dumps(events, ensure_ascii=False, indent=2) + "\n"
    if cur and base64.b64decode(cur["content"]).decode("utf-8").strip() == new_body.strip():
        print("NO CHANGE — %d events already live; skipping push" % len(events))
        return

    if args.dry_run:
        print("DRY RUN — would publish %d events:" % len(events))
        for e in events:
            print("  %s  %s (%s)" % (e["start_date"], e["name"], e["venue"]))
        return

    payload = {
        "message": "srqmap events: refresh %s (%d events)" % (today.isoformat(), len(events)),
        "content": base64.b64encode(new_body.encode("utf-8")).decode(),
        "branch": branch,
    }
    if cur:
        payload["sha"] = cur["sha"]
    res = gh(api, token, data=json.dumps(payload).encode(), method="PUT")
    print("PUBLISHED %d events — commit %s" % (len(events), res["commit"]["sha"][:10]))
    for e in events:
        print("  %s  %s (%s)" % (e["start_date"], e["name"], e["venue"]))

if __name__ == "__main__":
    main()

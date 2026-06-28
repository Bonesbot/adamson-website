#!/usr/bin/env python3
"""
SRQmap pin photo ingestion.

Workflow:
  1. Drop photos into  assets/SRQmap/  named after the place, e.g.
        lido-key-beach.jpg          (single hero)
        lido-key-beach-1.jpg        (gallery order 1)
        lido-key-beach-2.jpg        (gallery order 2)
     The prefix is the place's slug (see assets/SRQmap/_PHOTO-NAMING-GUIDE.md).
  2. Run:  python scripts/build_srqmap_photos.py        (add --no-push to skip deploy)

What it does:
  - matches each file to a pin (by slugified name, then pin id),
  - copies matches to  public/images/srqmap/<pin-id>-<n>.<ext>  (web-served),
  - writes the photos[] array into src/data/srqmap-pins.json,
  - pushes changed files to GitHub via the Contents API (Netlify rebuilds).

Up to 6 photos per pin; the SRQmap detail panel shows them as a swipe gallery.
"""
import argparse, base64, json, os, re, shutil, sys, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR  = ROOT / "assets" / "SRQmap"
PUB_DIR  = ROOT / "public" / "images" / "srqmap"
PINS     = ROOT / "src" / "data" / "srqmap-pins.json"
ENV_FILE = ROOT / ".env"
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PER_PIN = 6

def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

def parse_name(stem: str):
    """Return (base_slug, order) from a filename stem like 'lido-key-beach-2'."""
    m = re.match(r"^(.*?)[\s_\-]*\(?(\d+)\)?$", stem)
    if m and m.group(1):
        return slug(m.group(1)), int(m.group(2))
    return slug(stem), 1

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true", help="process locally, do not deploy")
    args = ap.parse_args()

    if not SRC_DIR.exists():
        sys.exit(f"Drop folder not found: {SRC_DIR}")
    pins = json.loads(PINS.read_text(encoding="utf-8"))

    # lookup: slug -> pin
    by_key = {}
    for p in pins:
        for k in {slug(p["name"]), p["id"], re.sub(r"^curated-", "", p["id"])}:
            by_key.setdefault(k, p)

    files = sorted(f for f in SRC_DIR.iterdir() if f.suffix.lower() in EXTS)
    if not files:
        print(f"No images in {SRC_DIR}. Drop some photos there first.")
        return

    PUB_DIR.mkdir(parents=True, exist_ok=True)
    assigned, unmatched = {}, []
    for f in files:
        base, order = parse_name(f.stem)
        pin = by_key.get(base)
        if not pin:
            cands = [k for k in by_key if k.startswith(base)] if base else []
            uniq = {by_key[k]["id"] for k in cands}
            pin = by_key[cands[0]] if len(uniq) == 1 else None
        if not pin:
            unmatched.append(f.name); continue
        assigned.setdefault(pin["id"], []).append((order, f))

    changed_paths = []
    pin_by_id = {p["id"]: p for p in pins}
    for pid, items in assigned.items():
        items.sort(key=lambda t: t[0])
        urls = []
        for n, (_order, f) in enumerate(items[:MAX_PER_PIN], start=1):
            dest = PUB_DIR / f"{pid}-{n}{f.suffix.lower()}"
            shutil.copyfile(f, dest)
            rel = f"public/images/srqmap/{dest.name}"
            changed_paths.append(rel)
            urls.append("/" + rel.split("public/", 1)[1])
        pin_by_id[pid]["photos"] = urls
        print(f"  {pid}: {len(urls)} photo(s)")

    PINS.write_text(json.dumps(pins, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    changed_paths.append("src/data/srqmap-pins.json")

    print(f"\nMatched {len(assigned)} pin(s); {sum(len(v) for v in assigned.values())} photo(s).")
    if unmatched:
        print("UNMATCHED (rename to a valid slug — see _PHOTO-NAMING-GUIDE.md):")
        for u in unmatched: print("  -", u)

    if args.no_push:
        print("\n--no-push: skipped deploy. Files staged in public/images/srqmap and pins json updated.")
        return

    # --- push via Contents API ---
    if not ENV_FILE.exists(): sys.exit("ERROR: .env missing; cannot push.")
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
    try:
        import requests
    except ImportError:
        sys.exit("ERROR: pip install requests (or rerun with --no-push and push manually).")
    TOK = os.environ.get("GITHUB_TOKEN"); REPO = os.environ.get("GITHUB_REPO", "Bonesbot/adamson-website"); BR = os.environ.get("GITHUB_BRANCH", "main")
    if not TOK: sys.exit("ERROR: GITHUB_TOKEN missing from .env")
    s = requests.Session(); s.headers.update({"Authorization": f"Bearer {TOK}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "agw/1.0"})
    print(f"\nPushing {len(changed_paths)} file(s) to {REPO}@{BR} ...")
    ok = 0
    for rel in changed_paths:
        api = f"https://api.github.com/repos/{REPO}/contents/{rel}"
        sha = s.get(api, params={"ref": BR}, timeout=20).json().get("sha")
        body = {"message": "SRQmap: add/update pin hero photos", "content": base64.b64encode((ROOT / rel).read_bytes()).decode(), "branch": BR}
        if sha: body["sha"] = sha
        r = s.put(api, json=body, timeout=40)
        if r.status_code in (200, 201): ok += 1; print(f"  OK  {rel}")
        else: print(f"  FAIL {rel}: {r.status_code} {r.text[:120]}")
    print(f"\nDone: {ok}/{len(changed_paths)} pushed. Netlify rebuilds in ~60s.")

if __name__ == "__main__":
    main()

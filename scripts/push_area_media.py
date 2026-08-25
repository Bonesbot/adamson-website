#!/usr/bin/env python3
"""Push area-page media (imagery + the code that renders it) to GitHub via the Contents API.

Supersedes push_siesta_media.py, which did the same job for one hardcoded slug. Any area
built by build_area_media.py is handled here, so a second area does not mean a second script.

Same pattern as scripts/push_srqmap_groom.py: reads GITHUB_TOKEN / GITHUB_REPO /
GITHUB_BRANCH from .env, one commit per file, bytes pushed verbatim.

Image lists are derived from src/data/area-media.json rather than by globbing the image
folders, so only files a page actually references get pushed. Superseded frames left
behind by an earlier build stay local and are reported as unreferenced instead of
silently shipping.

    python scripts/push_area_media.py                      # every area that has media
    python scripts/push_area_media.py --slug siesta-key    # just one
    python scripts/push_area_media.py --dry-run            # show the manifest, push nothing
"""
import argparse
import base64
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("ERROR: 'requests' not installed. Run: pip install requests")

ROOT = Path(__file__).resolve().parent.parent
MEDIA_JSON = ROOT / "src/data/area-media.json"

env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPO", "Bonesbot/adamson-website")
BRANCH = os.environ.get("GITHUB_BRANCH", "main")

# The code that renders area media. Pushed once regardless of how many slugs are selected.
CODE_FILES = [
    "src/pages/areas/[slug].astro",
    "src/pages/index.astro",
    "src/pages/photo-credits.astro",
    "src/pages/areas/index.astro",
    "src/components/market/AreaCard.astro",
    "src/components/market/AreaMarketSummary.astro",
    "src/components/market/DetailedMarketTable.astro",
    "src/components/market/CondoTiersTable.astro",
    "src/data/area-media.json",
    "src/data/areas.json",
    "scripts/build_area_media.py",
    "scripts/push_area_media.py",
    "public/images/specialties/new-build-consulting.jpg",
]


def load_media() -> dict:
    return json.loads(MEDIA_JSON.read_text(encoding="utf-8"))


def entry_images(entry: dict) -> list[str]:
    """Every image path an area entry points at, as repo-relative paths."""
    urls = [entry[k] for k in ("cardImage", "cardWebp", "heroImage", "heroWebp")
            if entry.get(k)]
    for g in entry.get("gallery", []):
        urls += [g[k] for k in ("src", "webp") if g.get(k)]
    # "/images/..." on the page maps to "public/images/..." in the repo
    return ["public" + u for u in urls]


def is_pipeline_built(entry: dict) -> bool:
    """True for areas built by build_area_media.py. `heroImage` is the marker: only this
    pipeline sets it, so hand-assembled entries (Longboat Key today) are left alone unless
    named explicitly with --slug."""
    return bool(entry.get("heroImage"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", action="append", default=[],
                    help="area slug to push. Repeatable. Default: every area built by "
                         "build_area_media.py.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    media = load_media()
    slugs = args.slug or [s for s, e in media.items() if is_pipeline_built(e)]

    unknown = [s for s in slugs if s not in media]
    if unknown:
        sys.exit(f"ERROR: unknown slug(s) in area-media.json: {', '.join(unknown)}")
    if not slugs:
        print("No areas have been built by build_area_media.py yet.")
        return 1

    files, missing, orphan_report = [], [], []

    for rel in CODE_FILES:
        (files if (ROOT / rel).is_file() else missing).append(rel)

    for slug in slugs:
        refs = entry_images(media[slug])
        for rel in refs:
            (files if (ROOT / rel).is_file() else missing).append(rel)

        img_dir = ROOT / "public" / "images" / "areas" / slug
        if img_dir.is_dir():
            wanted = {(ROOT / r).resolve() for r in refs}
            orphans = sorted(p.name for p in img_dir.iterdir()
                             if p.is_file() and p.resolve() not in wanted)
            if orphans:
                orphan_report.append((slug, orphans))

    for rel in missing:
        print(f"  MISSING {rel}")
    for slug, orphans in orphan_report:
        print(f"\n  {len(orphans)} unreferenced file(s) in areas/{slug}/ "
              f"(NOT pushed, safe to delete):")
        for o in orphans:
            print(f"    {o}")

    if missing:
        print("\nRefusing to push with missing files. Run build_area_media.py first.")
        return 1

    msg = ("Area media: own photography for "
           + ", ".join(slugs)
           + " (hero, gallery, home/areas card), WebP throughout, "
             "per-area hero scrim and crop")

    total_kb = sum((ROOT / f).stat().st_size for f in files) / 1024
    print(f"\n{len(files)} file(s), {total_kb:,.0f} KB -> {REPO}@{BRANCH}")
    print(f"areas: {', '.join(slugs)}\n")
    for f in files:
        print(f"    {f:<62} {(ROOT / f).stat().st_size / 1024:>8,.0f} KB")

    if args.dry_run:
        print("\n--dry-run: nothing pushed.")
        return 0

    if not TOKEN:
        sys.exit("\nERROR: GITHUB_TOKEN missing from .env")

    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })

    print()
    ok = 0
    for path in files:
        local = ROOT / path
        api = f"https://api.github.com/repos/{REPO}/contents/{path}"
        r = s.get(api, params={"ref": BRANCH}, timeout=20)
        sha = r.json().get("sha") if r.status_code == 200 else None
        body = {"message": msg,
                "content": base64.b64encode(local.read_bytes()).decode(),
                "branch": BRANCH}
        if sha:
            body["sha"] = sha
        r2 = s.put(api, json=body, timeout=60)
        if r2.status_code in (200, 201):
            print(f"  OK   {path} -> {r2.json()['commit']['sha'][:7]}")
            ok += 1
        else:
            print(f"  FAIL {path}: HTTP {r2.status_code} {r2.text[:200]}")

    print(f"\nDone: {ok}/{len(files)} pushed.")
    print("Netlify rebuilds automatically (~90s). Then check:")
    for slug in slugs:
        print(f"  https://adamsonfl.com/areas/{slug}/")
    print("  https://adamsonfl.com/  and  https://adamsonfl.com/areas/  (cards)")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())

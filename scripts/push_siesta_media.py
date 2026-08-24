#!/usr/bin/env python3
"""Push the Siesta Key area-page media work to GitHub via the Contents API.

Same pattern as scripts/push_srqmap_groom.py: reads GITHUB_TOKEN / GITHUB_REPO /
GITHUB_BRANCH from .env, one commit per file, bytes pushed verbatim.

The image list is derived from src/data/area-media.json rather than by globbing the
image folder, so only files the page actually references get pushed. Superseded frames
left behind by an earlier build stay local and are reported as unreferenced instead of
silently shipping.

Usage:
    python scripts/push_siesta_media.py [--dry-run]
"""
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
SLUG = "siesta-key"

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
DRY = "--dry-run" in sys.argv

CODE_FILES = [
    "src/pages/areas/[slug].astro",
    "src/data/area-media.json",
    "scripts/build_area_media.py",
    "scripts/push_siesta_media.py",
]

MSG = ("Siesta Key area page: own photography, WebP gallery, editorial summary, "
       "tunable hero scrim and crop, em dash cleanup")


def referenced_images():
    """Every image path the siesta-key entry points at, repo-relative."""
    media = json.loads((ROOT / "src/data/area-media.json").read_text(encoding="utf-8"))
    entry = media.get(SLUG, {})
    urls = []
    for key in ("heroImage", "heroWebp"):
        if entry.get(key):
            urls.append(entry[key])
    for g in entry.get("gallery", []):
        for key in ("src", "webp"):
            if g.get(key):
                urls.append(g[key])
    # "/images/..." in the page maps to "public/images/..." in the repo
    return ["public" + u for u in urls]


def main() -> int:
    files, missing = [], []

    for rel in CODE_FILES:
        (files if (ROOT / rel).is_file() else missing).append(rel)

    refs = referenced_images()
    for rel in refs:
        (files if (ROOT / rel).is_file() else missing).append(rel)

    # Anything sitting in the image folder that the page no longer points at.
    img_dir = ROOT / "public" / "images" / "areas" / SLUG
    orphans = []
    if img_dir.is_dir():
        wanted = {(ROOT / r).resolve() for r in refs}
        orphans = sorted(
            p.name for p in img_dir.iterdir()
            if p.is_file() and p.resolve() not in wanted
        )

    for rel in missing:
        print(f"  MISSING {rel}")
    if orphans:
        print(f"\n  {len(orphans)} unreferenced file(s) in {img_dir.name}/ "
              f"(NOT pushed, safe to delete):")
        for o in orphans:
            print(f"    {o}")

    if missing:
        print("\nRefusing to push with missing files. Run build_area_media.py first.")
        return 1
    if not files:
        print("Nothing to push.")
        return 1

    total_kb = sum((ROOT / f).stat().st_size for f in files) / 1024
    print(f"\n{len(files)} file(s), {total_kb:,.0f} KB -> {REPO}@{BRANCH}")
    for f in files:
        print(f"    {f:<58} {(ROOT / f).stat().st_size / 1024:>8,.0f} KB")

    if DRY:
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
        body = {
            "message": MSG,
            "content": base64.b64encode(local.read_bytes()).decode(),
            "branch": BRANCH,
        }
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
    print("  https://adamsonfl.com/areas/siesta-key/")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())

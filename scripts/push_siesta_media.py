#!/usr/bin/env python3
"""Push the Siesta Key area-page media work to GitHub via the Contents API.

Same pattern as scripts/push_srqmap_groom.py: reads GITHUB_TOKEN / GITHUB_REPO /
GITHUB_BRANCH from .env, one commit per file, bytes pushed verbatim.

Pushes two groups:
  1. Code + copy: the area template, area-media.json, and this build tooling.
  2. Imagery: everything under public/images/areas/siesta-key/, if it exists.

Group 2 is discovered at run time, so this script is safe to run BEFORE the photos
have been processed (it just pushes group 1) and again AFTER (it picks up the
frames). Files that do not exist locally are skipped with a note, never an error.

Usage:
    python scripts/push_siesta_media.py [--dry-run]
"""
import base64
import mimetypes
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("ERROR: 'requests' not installed. Run: pip install requests")

ROOT = Path(__file__).resolve().parent.parent

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

IMAGE_DIR = "public/images/areas/siesta-key"

MSG = ("Siesta Key area page: own photography, WebP gallery, editorial summary, "
       "hero override, em dash cleanup")


def collect():
    files, missing = [], []
    for rel in CODE_FILES:
        (files if (ROOT / rel).is_file() else missing).append(rel)

    img_dir = ROOT / IMAGE_DIR
    if img_dir.is_dir():
        for p in sorted(img_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".webp", ".png", ".avif"}:
                files.append(p.relative_to(ROOT).as_posix())
    return files, missing


def main() -> int:
    files, missing = collect()

    for rel in missing:
        print(f"  SKIP {rel} (not present locally)")

    if not files:
        print("Nothing to push.")
        return 1

    total_kb = sum((ROOT / f).stat().st_size for f in files) / 1024
    print(f"\n{len(files)} file(s), {total_kb:,.0f} KB -> {REPO}@{BRANCH}")
    for f in files:
        kb = (ROOT / f).stat().st_size / 1024
        print(f"    {f:<58} {kb:>8,.0f} KB")

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

#!/usr/bin/env python3
"""
Push refreshed src/data/<slug>-stats.json files to GitHub via the
Contents API. No local git operations — sidesteps stale .git/index.lock,
HTTPS credential prompts, and working-tree drift.

Each changed file becomes its own commit. The Contents API uses
SHA-based optimistic locking, so concurrent pushes either win cleanly
or return 409 (we retry once with a fresh GET).

Inputs (from .env):
    GITHUB_TOKEN      fine-grained PAT, Contents:write on the repo
    GITHUB_REPO       e.g. "Bonesbot/adamson-website" (default)
    GITHUB_BRANCH     default "main"

Status output: patches the orchestrator's last-run.json with a
"netlify" block:

    {
      "status": "pushed" | "no_changes" | "partial" | "failed" | "dry_run",
      "commits": [{"file": "...", "sha": "...", "html_url": "..."}, ...],
      "pushed_files": [...],
      "unchanged_files": [...],
      "failed_files": [{"file": "...", "error": "..."}],
      "notes": "..."
    }

Usage:
    python3 scripts/push_to_github.py \
        --slugs longboat-key,lido-key,siesta-key,downtown-sarasota,st-armands,bird-key \
        --status-out /path/to/last-run.json
"""

import argparse
import base64
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_FILE = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "src" / "data"

API_ROOT = "https://api.github.com"
TIMEOUT = 20  # seconds per HTTP call


def load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def gh_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "adamson-website-bonesbot/1.0",
    })
    return s


def get_remote(session, repo, branch, path):
    """GET current file from GitHub. Returns (sha, b64_content) or (None, None) if 404."""
    url = f"{API_ROOT}/repos/{repo}/contents/{path}"
    r = session.get(url, params={"ref": branch}, timeout=TIMEOUT)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    j = r.json()
    return j["sha"], j["content"].replace("\n", "")


def put_remote(session, repo, branch, path, b64_content, sha, message):
    """PUT new content. sha=None creates a new file. Returns (commit_sha, html_url)."""
    url = f"{API_ROOT}/repos/{repo}/contents/{path}"
    body = {"message": message, "content": b64_content, "branch": branch}
    if sha:
        body["sha"] = sha
    r = session.put(url, json=body, timeout=TIMEOUT)
    r.raise_for_status()
    j = r.json()
    return j["commit"]["sha"], j["commit"].get("html_url", "")


def push_one_file(session, repo, branch, slug, today_iso, dry_run=False):
    """Push a single <slug>-stats.json. Returns a dict describing the outcome."""
    local_path = DATA_DIR / f"{slug}-stats.json"
    if not local_path.exists():
        return {"slug": slug, "status": "missing_local",
                "error": f"{local_path} not found"}

    remote_repo_path = f"src/data/{slug}-stats.json"
    local_b64 = base64.b64encode(local_path.read_bytes()).decode("ascii")

    # Two-pass loop: GET, compare, PUT. Retry once on 409 (someone committed
    # between our GET and PUT).
    for attempt in (1, 2):
        try:
            sha, remote_b64 = get_remote(session, repo, branch, remote_repo_path)
        except requests.HTTPError as e:
            if e.response.status_code == 401:
                return {"slug": slug, "status": "auth_failed",
                        "error": "401 from GitHub — PAT missing/expired/insufficient scope"}
            return {"slug": slug, "status": "get_failed", "error": str(e)}
        except requests.RequestException as e:
            return {"slug": slug, "status": "get_failed", "error": str(e)}

        if remote_b64 is not None and remote_b64 == local_b64:
            return {"slug": slug, "status": "unchanged"}

        if dry_run:
            return {"slug": slug, "status": "would_push",
                    "action": "create" if sha is None else "update"}

        msg = f"Daily MLS refresh {today_iso} — {slug}-stats.json"
        try:
            commit_sha, html_url = put_remote(
                session, repo, branch, remote_repo_path, local_b64, sha, msg
            )
            return {"slug": slug, "status": "pushed",
                    "commit_sha": commit_sha[:7], "html_url": html_url,
                    "action": "create" if sha is None else "update"}
        except requests.HTTPError as e:
            if e.response.status_code == 409 and attempt == 1:
                time.sleep(1)
                continue
            if e.response.status_code == 401:
                return {"slug": slug, "status": "auth_failed",
                        "error": "401 from GitHub — PAT missing/expired/insufficient scope"}
            body_excerpt = ""
            try:
                body_excerpt = e.response.text[:200]
            except Exception:
                pass
            return {"slug": slug, "status": "put_failed",
                    "error": f"{e.response.status_code}: {body_excerpt}"}
        except requests.RequestException as e:
            return {"slug": slug, "status": "put_failed", "error": str(e)}

    return {"slug": slug, "status": "put_failed", "error": "exhausted retries on 409"}


def patch_status_json(status_path: Path, netlify_block: dict) -> None:
    if not status_path.exists():
        return
    try:
        with open(status_path) as f:
            d = json.load(f)
    except json.JSONDecodeError:
        return
    d["netlify"] = netlify_block
    with open(status_path, "w") as f:
        json.dump(d, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slugs", required=True,
                    help="Comma-separated list, e.g. longboat-key,lido-key,...")
    ap.add_argument("--status-out", type=Path,
                    help="last-run.json to patch with netlify block")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't PUT anything; just report what would change")
    args = ap.parse_args()

    load_env(ENV_FILE)
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPO", "Bonesbot/adamson-website")
    branch = os.environ.get("GITHUB_BRANCH", "main")
    slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
    today_iso = date.today().isoformat()

    if not token:
        netlify = {
            "status": "failed", "commits": [],
            "pushed_files": [], "unchanged_files": [], "failed_files": [],
            "notes": "GITHUB_TOKEN not set in .env — see scripts/PAT_SETUP.md",
        }
        if args.status_out:
            patch_status_json(args.status_out, netlify)
        print(json.dumps(netlify, indent=2))
        sys.exit(2)

    session = gh_session(token)
    results = [push_one_file(session, repo, branch, slug, today_iso, args.dry_run)
               for slug in slugs]

    pushed    = [r for r in results if r["status"] == "pushed"]
    would     = [r for r in results if r["status"] == "would_push"]
    unchanged = [r for r in results if r["status"] == "unchanged"]
    failed    = [r for r in results if r["status"] not in
                 ("pushed", "unchanged", "would_push")]

    if args.dry_run:
        status = "dry_run"
    elif failed and not pushed and not unchanged:
        status = "failed"
    elif failed and (pushed or unchanged):
        status = "partial"
    elif pushed:
        status = "pushed"
    else:
        status = "no_changes"

    notes_parts = []
    if status == "pushed":
        notes_parts.append(f"{len(pushed)} file(s) pushed; Netlify rebuild triggered")
    elif status == "no_changes":
        notes_parts.append("All area JSONs identical to remote — site already current")
    elif status == "partial":
        notes_parts.append(f"{len(pushed)} pushed, {len(failed)} failed")
    elif status == "failed":
        notes_parts.append("All pushes failed; site not updated")
    elif status == "dry_run":
        notes_parts.append(f"would push {len(would)}; {len(unchanged)} unchanged")

    if any(r["status"] == "auth_failed" for r in failed):
        notes_parts.append("Auth issue — check PAT in .env")

    netlify = {
        "status": status,
        "commits": [{"file": r["slug"] + "-stats.json",
                     "sha": r.get("commit_sha"),
                     "html_url": r.get("html_url")} for r in pushed],
        "pushed_files": [r["slug"] + "-stats.json" for r in pushed],
        "unchanged_files": [r["slug"] + "-stats.json" for r in unchanged],
        "failed_files": [{"file": r["slug"] + "-stats.json",
                          "error": r.get("error", "")} for r in failed],
        "would_push_files": [r["slug"] + "-stats.json" for r in would],
        "notes": " | ".join(notes_parts),
    }

    if args.status_out:
        patch_status_json(args.status_out, netlify)

    print(json.dumps(netlify, indent=2))
    if status == "failed":
        sys.exit(2)
    if status == "partial":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

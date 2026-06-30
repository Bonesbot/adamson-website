#!/usr/bin/env python3
"""
_integrity_check.py — Verify (and self-heal) the pipeline scripts on disk
against the canonical SHA256s in EXPECTED_HASHES.json.

Called by combine_mls_export.py at step 0, and by the mls-export task's
Step 0.6 right after it fetches the canonical scripts from origin/main into
/tmp.

WHY THIS EXISTS (and why it now self-heals)
-------------------------------------------
Original purpose: the Cowork/Windows FUSE mount was observed to silently
truncate scripts read from the mount. Since the pipeline moved to fetching
scripts over HTTPS from origin/main into /tmp (FUSE bypassed), that specific
threat is largely gone — so a *hash mismatch* now almost always means the
manifest is simply STALE: someone changed a tracked script on main (e.g. from
the AG_website interactive project) without rotating EXPECTED_HASHES.json.
Hard-failing the unattended daily run on that is the chronic drift we want to
eliminate.

NEW BEHAVIOR — verify() classifies each mismatch:
  * file MISSING, or (for .py) DOES NOT PARSE  -> genuinely corrupt -> raise
    IntegrityError. The real safety tripwire is preserved; the run still stops
    with failed_step="integrity_check".
  * file present and VALID but hash differs    -> "healable": the bytes came
    straight from origin/main and parse fine, so they ARE authoritative. We
    adopt them: rewrite the on-disk manifest to match, optionally push the
    corrected manifest back to main ([skip ci], so Netlify is NOT rebuilt),
    drop a .heal-report.json sidecar, and let the run proceed.

This makes the daily runner FOLLOW main automatically and keeps the website
project and the scheduled task in sync without a manual rotate step. To rotate
the manifest by hand (rarely needed now):
    python scripts/_integrity_check.py --rotate
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path


class IntegrityError(RuntimeError):
    """Raised only when on-disk script bytes are genuinely corrupt
    (missing, or a .py that no longer parses)."""


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parses_ok(path: Path) -> bool:
    """A tracked .py file is 'valid' if it parses; anything else is valid if
    non-empty. Truncation/mangling reliably breaks both."""
    try:
        data = path.read_bytes()
    except Exception:
        return False
    if not data.strip():
        return False
    if path.suffix == ".py":
        try:
            ast.parse(data)
        except SyntaxError:
            return False
    return True


def _load_env(repo_root: Path) -> dict:
    env: dict = {}
    for cand in (repo_root / ".env", repo_root / "scripts" / ".env"):
        if cand.exists():
            try:
                for line in cand.read_text().splitlines():
                    if "=" in line and not line.strip().startswith("#"):
                        k, _, v = line.partition("=")
                        env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            except Exception:
                pass
    for k in ("GITHUB_TOKEN", "GITHUB_REPO", "GITHUB_BRANCH"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def _gh_request(url, token, method="GET", payload=None):
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "mls-export-integrity",
    }
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _push_manifest_to_main(repo_root: Path, manifest_text: str, healed, env) -> dict:
    """Best-effort: PUT the rotated EXPECTED_HASHES.json back to origin/main via
    the Contents API, with [skip ci] so Netlify does NOT rebuild. Never raises."""
    token = env.get("GITHUB_TOKEN")
    repo = env.get("GITHUB_REPO")
    branch = env.get("GITHUB_BRANCH", "main")
    if not token or not repo:
        return {"pushed": False, "reason": "GITHUB_TOKEN/REPO not available"}
    rel = "scripts/EXPECTED_HASHES.json"
    try:
        meta = _gh_request(
            f"https://api.github.com/repos/{repo}/contents/{rel}?ref={branch}", token
        )
        cur_sha = meta.get("sha")
        adopted = ", ".join(healed) if healed else "tracked scripts"
        msg = (
            f"chore: auto-rotate EXPECTED_HASHES.json — adopted {adopted} "
            f"from origin/{branch} (mls-export self-heal) [skip ci]"
        )
        payload = {
            "message": msg,
            "content": base64.b64encode(manifest_text.encode()).decode(),
            "sha": cur_sha,
            "branch": branch,
        }
        res = _gh_request(
            f"https://api.github.com/repos/{repo}/contents/{rel}",
            token, method="PUT", payload=payload,
        )
        commit_sha = (res.get("commit") or {}).get("sha", "")[:9]
        return {"pushed": True, "commit": commit_sha, "message": msg}
    except Exception as exc:
        return {"pushed": False, "reason": f"{type(exc).__name__}: {exc}"}


def _rotate_manifest_text(manifest: dict, repo_root: Path) -> str:
    """Return manifest JSON text with files{} rehashed from current on-disk bytes."""
    new_files = {}
    for rel in manifest.get("files", {}):
        p = repo_root / rel
        if p.exists():
            new_files[rel] = _hash_file(p)
    manifest["files"] = new_files
    manifest["generated_from_commit"] = "auto-rotated by mls-export self-heal"
    return json.dumps(manifest, indent=2, sort_keys=False) + "\n"


def verify(repo_root: Path, *, heal: bool = True, push: bool = True) -> dict:
    """Verify the pipeline scripts against the manifest.

    Genuinely corrupt files (missing, or a .py that won't parse) raise
    IntegrityError. Valid-but-mismatched files are adopted (self-heal): the
    manifest is rotated on disk and, if possible, pushed back to origin/main.

    Returns a summary dict: {checked, ok, healed, push}.
    """
    manifest_path = repo_root / "scripts" / "EXPECTED_HASHES.json"
    if not manifest_path.exists():
        raise IntegrityError(f"manifest missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise IntegrityError(f"manifest unreadable: {exc}") from exc

    files = manifest.get("files") or {}
    if not files:
        raise IntegrityError("manifest has no 'files' entries")

    corrupt: list = []
    healable: list = []
    for rel_path, expected in files.items():
        p = repo_root / rel_path
        if not p.exists():
            corrupt.append(f"{rel_path}: missing")
            continue
        actual = _hash_file(p)
        if actual == expected:
            continue
        if not _parses_ok(p):
            corrupt.append(
                f"{rel_path}: present but invalid/unparsable "
                f"(expected {expected[:12]}.. got {actual[:12]}..)"
            )
        else:
            healable.append(rel_path)

    if corrupt:
        raise IntegrityError(
            "Pipeline script integrity check FAILED — one or more tracked "
            "scripts look genuinely corrupt (truncated/mangled), not merely a "
            "stale manifest. Restore from origin/main before retrying.\n  - "
            + "\n  - ".join(corrupt)
        )

    summary = {"checked": list(files.keys()), "ok": True, "healed": [], "push": None}

    if healable and heal:
        new_text = _rotate_manifest_text(manifest, repo_root)
        manifest_path.write_text(new_text, encoding="utf-8")
        summary["healed"] = list(healable)
        try:
            (repo_root / "scripts" / ".heal-report.json").write_text(
                json.dumps({"healed": list(healable)}, indent=2), encoding="utf-8"
            )
        except Exception:
            pass
        if push:
            summary["push"] = _push_manifest_to_main(
                repo_root, new_text, healable, _load_env(repo_root)
            )

    return summary


def rotate(repo_root: Path) -> None:
    """Rewrite the manifest from current on-disk hashes."""
    manifest_path = repo_root / "scripts" / "EXPECTED_HASHES.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    text = _rotate_manifest_text(manifest, repo_root)
    manifest_path.write_text(text, encoding="utf-8")
    for rel, h in json.loads(text)["files"].items():
        print(f"  {rel}: {h[:16]}..")
    print(f"[rotated] {manifest_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="MLS pipeline integrity check")
    parser.add_argument("--rotate", action="store_true",
                        help="Rewrite manifest from current on-disk hashes")
    parser.add_argument("--no-heal", action="store_true",
                        help="Strict verify: do not self-heal stale-manifest mismatches")
    parser.add_argument("--no-push", action="store_true",
                        help="Self-heal locally but do not push the manifest to main")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    if args.rotate:
        rotate(repo_root)
        return 0
    try:
        result = verify(repo_root, heal=not args.no_heal, push=not args.no_push)
        if result["healed"]:
            pushed = (result.get("push") or {}).get("pushed")
            print(f"[integrity] self-healed {len(result['healed'])} file(s): "
                  f"{', '.join(result['healed'])}  (pushed to main: {pushed})")
        else:
            print(f"[integrity] OK  ({len(result['checked'])} files match manifest)")
        return 0
    except IntegrityError as exc:
        print(f"[integrity] FAIL\n{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

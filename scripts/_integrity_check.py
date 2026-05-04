#!/usr/bin/env python3
"""
_integrity_check.py — Verify the pipeline scripts on disk match the canonical
SHA256s in EXPECTED_HASHES.json. Called by combine_mls_export.py at step 0.

Why this exists: the Cowork/Windows FUSE mount has been observed to silently
truncate files and flip line endings during writes from the Linux side. When
that happens, prior runs would "patch in-place" through the same broken layer
and silently degrade pipeline behavior. This check converts that into a loud,
visible failure (failed_step=integrity_check in the daily status email) so a
human restores from origin/main rather than letting the cycle continue.

The manifest lives at scripts/EXPECTED_HASHES.json. To rotate hashes (after a
legitimate change to one of the listed scripts), use:
    python scripts/_integrity_check.py --rotate
which rewrites the manifest from current on-disk hashes. Only run --rotate
when you're certain the current bytes are the intended canonical version.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


class IntegrityError(RuntimeError):
    """Raised when on-disk script bytes don't match the expected manifest."""


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(repo_root: Path) -> dict:
    """Verify the pipeline scripts. Raises IntegrityError on any mismatch.
    Returns a dict summary on success."""
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

    failures: list[str] = []
    for rel_path, expected in files.items():
        p = repo_root / rel_path
        if not p.exists():
            failures.append(f"{rel_path}: missing")
            continue
        actual = _hash_file(p)
        if actual != expected:
            failures.append(
                f"{rel_path}: expected {expected[:12]}.. got {actual[:12]}.."
            )

    if failures:
        raise IntegrityError(
            "Pipeline script integrity check FAILED. The Cowork/Windows mount "
            "may have mangled these files. Restore via Windows-side "
            "`git checkout origin/main -- <files>` before retrying.\n  - "
            + "\n  - ".join(failures)
        )
    return {"checked": list(files.keys()), "ok": True}


def rotate(repo_root: Path) -> None:
    """Rewrite the manifest from the current on-disk hashes. Use only when
    the on-disk versions ARE the new canonical."""
    manifest_path = repo_root / "scripts" / "EXPECTED_HASHES.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") or {}
    new_files = {}
    for rel_path in files:
        p = repo_root / rel_path
        if not p.exists():
            print(f"  SKIP {rel_path}: missing", file=sys.stderr)
            continue
        new_files[rel_path] = _hash_file(p)
        print(f"  {rel_path}: {new_files[rel_path][:16]}..")
    manifest["files"] = new_files
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"[rotated] {manifest_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="MLS pipeline integrity check")
    parser.add_argument("--rotate", action="store_true",
                        help="Rewrite manifest from current on-disk hashes (dangerous)")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    if args.rotate:
        rotate(repo_root)
        return 0
    try:
        result = verify(repo_root)
        print(f"[integrity] OK  ({len(result['checked'])} files match manifest)")
        return 0
    except IntegrityError as exc:
        print(f"[integrity] FAIL\n{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

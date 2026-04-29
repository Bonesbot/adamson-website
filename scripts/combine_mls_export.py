#!/usr/bin/env python3
"""
combine_mls_export.py — Combine MLS export batches → website project → Supabase ingestion.

Runs at the end of the daily Cowork mls-export scheduled task. Picks up
batch_*.csv files produced by the Matrix browser automation, stitches them
into one deduped CSV, drops it in the website project's mls-imports/ watch
folder, and (unless --skip-ingest) chains into supabase/ingest_mls.py.

Always writes a structured status JSON (--status-out) on both success and
failure so the orchestrating Claude task can compose an appropriate email
draft regardless of which step failed.

Usage:
    python combine_mls_export.py \
        --staging /path/to/MLS-Exports/staging \
        --target-dir /path/to/AG_website/mls-imports \
        --status-out /path/to/MLS-Exports/last-run.json \
        --expected-total 1175 \
        --search-name "000 - Market Update" \
        [--skip-ingest] \
        [--ingest-script /path/to/AG_website/supabase/ingest_mls.py] \
        [--row-count-tolerance 5]

Exit codes: 0 = full pipeline success, non-zero = failure (see status JSON).
"""

import argparse
import csv
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import traceback
from collections import Counter
from pathlib import Path


SCHEMA_VERSION = 1
TZ = None  # set in main() based on --tz arg, defaults to America/New_York
DEDUPE_KEY_PRIMARY = "ListingKeyNumeric"
DEDUPE_KEY_FALLBACK = "ListingId"
STATUS_COL_CANDIDATES = ("MlsStatus", "StandardStatus")


def now_iso_local() -> str:
    """ISO 8601 timestamp in the configured TZ (defaults to local)."""
    if TZ is not None:
        return dt.datetime.now(TZ).isoformat(timespec="seconds")
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def write_status(status: dict, path: Path) -> None:
    """Atomic-ish write of the status JSON. Best-effort — never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2, default=str)
        os.replace(tmp, path)
    except Exception as exc:
        print(f"[WARN] failed to write status JSON to {path}: {exc}", file=sys.stderr)


def fail(status, status_path, step, message, exit_code=1):
    """Mark status as failed, write JSON, and exit."""
    status["success"] = False
    status["failed_step"] = step
    status["error_message"] = message
    status["ended_at"] = now_iso_local()
    if status.get("started_epoch") is not None:
        status["duration_seconds"] = round(
            dt.datetime.now().timestamp() - status["started_epoch"], 2
        )
    write_status(status, status_path)
    print(f"[FAIL] {step}: {message}", file=sys.stderr)
    sys.exit(exit_code)


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--staging", required=True, type=Path,
                   help="Folder containing batch_*.csv files (typically MLS-Exports/staging)")
    p.add_argument("--target-dir", required=True, type=Path,
                   help="Folder where the combined CSV is written (typically AG_website/mls-imports)")
    p.add_argument("--status-out", required=True, type=Path,
                   help="Path to status JSON written on every run, success or failure")
    p.add_argument("--expected-total", type=int, default=None,
                   help="Total records Matrix reported. If set, asserts combined rows match within --row-count-tolerance.")
    p.add_argument("--search-name", default="000 - Market Update",
                   help="Saved-search name (recorded in status JSON for the email)")
    p.add_argument("--row-count-tolerance", type=int, default=5,
                   help="Allowed delta between rows_out and expected_total (default 5)")
    p.add_argument("--skip-ingest", action="store_true",
                   help="Skip subprocess call to supabase/ingest_mls.py (combine only)")
    p.add_argument("--ingest-script", type=Path, default=None,
                   help="Path to supabase/ingest_mls.py. If omitted, inferred relative to --target-dir.")
    p.add_argument("--ingest-timeout", type=int, default=600,
                   help="Seconds to wait for ingest_mls.py (default 600)")
    p.add_argument("--filename-template", default="market-update_{date}.csv",
                   help="Combined-file name template; {date} substituted (default market-update_<YYYY-MM-DD>.csv)")
    p.add_argument("--tz", default="America/New_York",
                   help="IANA timezone for date stamps and timestamps (default America/New_York)")
    return p.parse_args()


def main():
    global TZ
    args = parse_args()

    try:
        from zoneinfo import ZoneInfo
        TZ = ZoneInfo(args.tz)
    except Exception:
        TZ = None  # fall back to system local

    started_dt = dt.datetime.now(TZ) if TZ else dt.datetime.now()
    today = started_dt.date().isoformat()

    status = {
        "schema_version": SCHEMA_VERSION,
        "started_at": started_dt.isoformat(timespec="seconds") if started_dt.tzinfo else started_dt.astimezone().isoformat(timespec="seconds"),
        "started_epoch": started_dt.timestamp(),
        "ended_at": None,
        "duration_seconds": None,
        "success": False,
        "failed_step": None,
        "error_message": None,
        "search_name": args.search_name,
        "expected_total": args.expected_total,
        "batches": [],
        "rows_in": 0,
        "rows_dupe": 0,
        "rows_out": 0,
        "header_columns": 0,
        "dedupe_key": None,
        "combined_csv_path": None,
        "combined_csv_size_bytes": None,
        "archived_to": None,
        "ingest": {"ran": False, "exit_code": None, "log_excerpt": None, "skipped_reason": None},
        "status_distribution": {},
    }

    staging = args.staging
    target = args.target_dir
    status_path = args.status_out

    # --- Step 1: discover batches ---
    if not staging.is_dir():
        fail(status, status_path, "discover_batches",
             f"staging folder not found: {staging}")

    batches = sorted(staging.glob("batch_*.csv"))
    if not batches:
        fail(status, status_path, "discover_batches",
             f"no batch_*.csv files found in {staging}")

    # --- Step 2: combine + dedupe ---
    target.mkdir(parents=True, exist_ok=True)
    out_name = args.filename_template.format(date=today)
    out_path = target / out_name

    seen = set()
    header = None
    dedupe_key = None
    n_in = n_dupe = n_out = 0
    status_counter = Counter()

    try:
        with open(out_path, "w", newline="", encoding="utf-8") as fout:
            writer = None
            for b in batches:
                with open(b, "r", encoding="utf-8", newline="") as fin:
                    reader = csv.DictReader(fin)
                    if header is None:
                        header = reader.fieldnames or []
                        if not header:
                            fail(status, status_path, "combine",
                                 f"first batch {b.name} has no header row")
                        if DEDUPE_KEY_PRIMARY in header:
                            dedupe_key = DEDUPE_KEY_PRIMARY
                        elif DEDUPE_KEY_FALLBACK in header:
                            dedupe_key = DEDUPE_KEY_FALLBACK
                        else:
                            fail(status, status_path, "combine",
                                 f"neither {DEDUPE_KEY_PRIMARY} nor {DEDUPE_KEY_FALLBACK} found in header")
                        status["header_columns"] = len(header)
                        status["dedupe_key"] = dedupe_key
                        writer = csv.DictWriter(fout, fieldnames=header, quoting=csv.QUOTE_ALL)
                        writer.writeheader()
                    elif reader.fieldnames != header:
                        fail(status, status_path, "combine",
                             f"header mismatch in {b.name}: expected {len(header)} cols, got {len(reader.fieldnames or [])}")

                    rows_this_batch = 0
                    for row in reader:
                        n_in += 1
                        rows_this_batch += 1
                        key = row.get(dedupe_key, "")
                        if key and key in seen:
                            n_dupe += 1
                            continue
                        if key:
                            seen.add(key)
                        writer.writerow(row)
                        n_out += 1
                        for col in STATUS_COL_CANDIDATES:
                            v = row.get(col)
                            if v:
                                status_counter[v] += 1
                                break

                    status["batches"].append({"file": b.name, "rows": rows_this_batch})
    except SystemExit:
        raise
    except Exception as exc:
        fail(status, status_path, "combine",
             f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")

    status["rows_in"] = n_in
    status["rows_dupe"] = n_dupe
    status["rows_out"] = n_out
    status["combined_csv_path"] = str(out_path)
    status["combined_csv_size_bytes"] = out_path.stat().st_size
    status["status_distribution"] = dict(status_counter)

    # --- Step 3: row-count assertion ---
    if args.expected_total is not None:
        delta = abs(n_out - args.expected_total)
        if delta > args.row_count_tolerance:
            fail(status, status_path, "row_count_assertion",
                 f"combined rows ({n_out}) differs from expected_total ({args.expected_total}) by {delta}, "
                 f"exceeds tolerance {args.row_count_tolerance}. Per-batch: {status['batches']}")

    # --- Step 4: archive batches ---
    archive_dir = staging / "archive" / today
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        for b in batches:
            dest = archive_dir / b.name
            if dest.exists():
                dest = archive_dir / f"{b.stem}_{started_dt.strftime('%H%M%S')}{b.suffix}"
            shutil.move(str(b), str(dest))
        status["archived_to"] = str(archive_dir)
    except Exception as exc:
        # Archival failure is non-fatal
        status["archived_to"] = None
        existing_err = status.get("error_message") or ""
        status["error_message"] = (existing_err + "\n" if existing_err else "") + f"archival warning: {exc}"

    # --- Step 5: chain ingest_mls.py ---
    if args.skip_ingest:
        status["ingest"]["ran"] = False
        status["ingest"]["skipped_reason"] = "--skip-ingest flag"
    else:
        ingest_script = args.ingest_script
        if ingest_script is None:
            ingest_script = target.parent / "supabase" / "ingest_mls.py"
        if not ingest_script.is_file():
            status["ingest"]["ran"] = False
            status["ingest"]["skipped_reason"] = f"ingest script not found at {ingest_script}"
        else:
            try:
                proc = subprocess.run(
                    [sys.executable, str(ingest_script), str(out_path)],
                    capture_output=True, text=True,
                    timeout=args.ingest_timeout,
                    cwd=str(ingest_script.parent.parent),
                )
                status["ingest"]["ran"] = True
                status["ingest"]["exit_code"] = proc.returncode
                combined_log = (proc.stdout or "")
                if proc.stderr:
                    combined_log += "\n--- stderr ---\n" + proc.stderr
                status["ingest"]["log_excerpt"] = combined_log[-2048:].strip()
                if proc.returncode != 0:
                    fail(status, status_path, "ingest",
                         f"ingest_mls.py exited with code {proc.returncode}. See log_excerpt in status JSON.")
            except subprocess.TimeoutExpired:
                fail(status, status_path, "ingest",
                     f"ingest_mls.py exceeded {args.ingest_timeout}s timeout")
            except SystemExit:
                raise
            except Exception as exc:
                fail(status, status_path, "ingest",
                     f"failed to invoke ingest_mls.py: {type(exc).__name__}: {exc}")

    # --- Done ---
    status["success"] = True
    status["ended_at"] = now_iso_local()
    status["duration_seconds"] = round(dt.datetime.now().timestamp() - status["started_epoch"], 2)
    write_status(status, status_path)

    print(f"[OK] combined {n_out} rows ({n_dupe} dupes) -> {out_path}")
    if status["ingest"]["ran"]:
        print(f"[OK] ingest_mls.py exit={status['ingest']['exit_code']}")
    else:
        print(f"[INFO] ingest skipped: {status['ingest']['skipped_reason']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        crash_status = {
            "schema_version": SCHEMA_VERSION,
            "started_at": now_iso_local(),
            "ended_at": now_iso_local(),
            "success": False,
            "failed_step": "uncaught_exception",
            "error_message": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
        }
        try:
            so = None
            for i, a in enumerate(sys.argv):
                if a == "--status-out" and i + 1 < len(sys.argv):
                    so = sys.argv[i + 1]
                    break
            if so:
                write_status(crash_status, Path(so))
        except Exception:
            pass
        print(f"[CRASH] {exc}", file=sys.stderr)
        sys.exit(2)

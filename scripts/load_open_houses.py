#!/usr/bin/env python3
"""
load_open_houses.py: load the daily Matrix open-house scrape into Supabase.

Source: Matrix saved search "000 - Open House Search" (polygon over Ryan's market,
types Public + MLS Wide). Matrix will not export that grid, so the scheduled task
scrapes it in the browser and writes compact records, one per open-house event:

    LISTING_ID,MMDD,HHMM_START,HHMM_END,TYPE,SHOWING_AGENT_MLS_ID
    A4702902,0926,1300,1600,P,281523720

Records may be separated by newlines or semicolons; a header line is ignored.
TYPE is P (Public) or M (MLS Wide / broker). Times are 24h.

Cleanup:
  * Agents often key 1:00AM when they mean 1:00PM. A start before 7:00 that still
    ends before the end time once shifted +12h is corrected and flagged time_suspect.
  * start >= end (e.g. 12:00PM-12:00PM) is kept but flagged time_suspect.
  * Year is inferred: the date is assumed to be within the next ~11 months.

Usage (repo root, DATABASE_URL in .env):
    python3 scripts/load_open_houses.py mls-imports/open_houses_YYYYMMDD.txt
    python3 scripts/load_open_houses.py FILE --dry-run
"""
import argparse
import os
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras

REPO_ROOT = Path(__file__).resolve().parent.parent
MIN_EXPECTED = 50   # a normal day has 150-300 events; fewer means the scrape broke

DDL = """
CREATE TABLE IF NOT EXISTS open_houses (
  listing_id            text NOT NULL,
  oh_date               date NOT NULL,
  start_time            time,
  end_time              time,
  oh_type               text NOT NULL,
  showing_agent_mls_id  text,
  time_suspect          boolean NOT NULL DEFAULT false,
  raw_start             text,
  raw_end               text,
  first_seen_at         timestamptz NOT NULL DEFAULT now(),
  last_seen_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (listing_id, oh_date, oh_type, raw_start)
);
CREATE INDEX IF NOT EXISTS idx_open_houses_date ON open_houses (oh_date);
"""

UPSERT = """
INSERT INTO open_houses (listing_id, oh_date, start_time, end_time, oh_type,
                         showing_agent_mls_id, time_suspect, raw_start, raw_end)
VALUES %s
ON CONFLICT (listing_id, oh_date, oh_type, raw_start) DO UPDATE SET
  start_time = EXCLUDED.start_time, end_time = EXCLUDED.end_time, raw_end = EXCLUDED.raw_end,
  showing_agent_mls_id = EXCLUDED.showing_agent_mls_id,
  time_suspect = EXCLUDED.time_suspect, last_seen_at = now()
"""

REC = re.compile(r"^([A-Z]{1,3}\d{5,})\s*,\s*(\d{4})\s*,\s*(\d{4})\s*,\s*(\d{4})\s*,\s*([PM])\s*,\s*(\d*)$")


def load_env():
    env = {}
    p = REPO_ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return {**env, **os.environ}


def fix_times(start, end):
    s_h, s_m, e_h, e_m = int(start[:2]), int(start[2:]), int(end[:2]), int(end[2:])
    suspect = False
    if s_h < 7 and (s_h + 12) * 60 + s_m < e_h * 60 + e_m:
        s_h += 12
        suspect = True
    if (s_h, s_m) >= (e_h, e_m) or s_h < 7:
        suspect = True
    return time(s_h % 24, s_m), time(e_h % 24, e_m), suspect


def infer_date(mmdd, today):
    m, d = int(mmdd[:2]), int(mmdd[2:])
    cand = date(today.year, m, d)
    if cand < today - timedelta(days=30):      # e.g. scraping in December, event in January
        cand = date(today.year + 1, m, d)
    return cand


def parse(text, today):
    rows, bad = [], []
    for raw in re.split(r"[;\n]+", text):
        raw = raw.strip()
        if not raw or raw.lower().startswith("listing_id"):
            continue
        m = REC.match(raw)
        if not m:
            bad.append(raw)
            continue
        lid, mmdd, st, en, typ, agent = m.groups()
        s, e, sus = fix_times(st, en)
        rows.append((lid, infer_date(mmdd, today), s, e, "Public" if typ == "P" else "MLS Wide",
                     agent or None, sus, st, en))
    # de-dupe on the primary key (Matrix sometimes repeats a row verbatim)
    uniq = {(r[0], r[1], r[4], r[7]): r for r in rows}
    return list(uniq.values()), bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    text = Path(a.file).read_text(encoding="utf-8")
    # tolerate the CSV-with-header form written on 2026-09-25
    text = re.sub(r"^listing_id,mmdd.*$", "", text, flags=re.M)
    rows, bad = parse(text, date.today())
    n_sus = sum(1 for r in rows if r[6])
    print(f"Parsed {len(rows)} events across {len({r[0] for r in rows})} listings "
          f"({n_sus} time_suspect, {len(bad)} unparseable)")
    for b in bad[:5]:
        print("  unparseable:", b[:80])
    if len(rows) < MIN_EXPECTED:
        sys.exit(f"ABORT: only {len(rows)} events parsed (expected >= {MIN_EXPECTED}); scrape likely incomplete")
    if a.dry_run:
        return

    conn = psycopg2.connect(load_env()["DATABASE_URL"])
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
            psycopg2.extras.execute_values(cur, UPSERT, rows, page_size=500)
            conn.commit()
            cur.execute("""select count(*), count(*) filter (where unparsed_address is null),
                                  count(*) filter (where oh_date between current_date and current_date + 7)
                           from vw_open_houses_upcoming""")
            total, unmatched, week = cur.fetchone()
        print(f"Upserted {len(rows)} events. Upcoming in view: {total} "
              f"(next 7 days: {week}; no matching listing in raw_listings: {unmatched})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

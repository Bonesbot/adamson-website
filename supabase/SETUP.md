# MLS Data Pipeline — Setup & Deployment Guide

## Prerequisites

- Supabase project (already provisioned): `qfcbtytjidvpczejwwtj.supabase.co`
- Python 3.10+ on the Windows mini-PC
- The `.env` file in the project root (already created)

---

## Step 1: Deploy the Database Schema

The sandbox can't reach Supabase directly, so this is a manual paste:

1. Open [Supabase Dashboard → SQL Editor](https://supabase.com/dashboard/project/qfcbtytjidvpczejwwtj/sql/new)
2. Open `supabase/schema.sql` in a text editor
3. **Select All** → **Copy** the entire file (696 lines)
4. Paste into the SQL Editor
5. Click **Run**

You should see output confirming creation of:
- 7 tables: `import_batches`, `raw_listings`, `areas`, `zone_polygons`, `subdivision_aliases`, `unmatched_subdivisions`, `audit_log`
- 1 trigger function: `fn_compute_enrichments()`
- 7 views: `vw_market_stats_by_area`, `vw_market_stats_sold`, etc.
- 6 seeded areas: Longboat Key, Downtown Sarasota, Lido Key, Siesta Key, St. Armands, Bird Key
- 40+ indexes

If you get an error about `postgis` or `pg_trgm`, enable those extensions first:
- Dashboard → Database → Extensions → search "postgis" → Enable
- Dashboard → Database → Extensions → search "pg_trgm" → Enable

Then re-run the schema SQL.

---

## Step 2: Install Python Dependencies on Mini-PC

```bash
pip install requests python-dotenv
```

(The script has a built-in `.env` loader so `python-dotenv` is optional but nice to have.)

---

## Step 3: Set Up the Watch Folder

Create this folder structure on the mini-PC:

```
AG_website/
├── .env                          ← already exists
├── supabase/
│   ├── schema.sql                ← already exists
│   └── ingest_mls.py             ← the ingest script
├── mls_imports/                  ← DROP CSV FILES HERE
│   └── processed/                ← auto-created; files move here after ingest
└── logs/
    └── ingest.log                ← auto-created
```

---

## Step 4: Initial Data Load

1. Download both CSV files from Google Drive to `mls_imports/`:
   - "AAAA - Data Analytics Export - new format test.csv" (221 rows)
   - "AAAA - Data Analytics Export - new format test 2.csv" (500 rows)

2. Run the ingest:
```bash
cd AG_website
python supabase/ingest_mls.py
```

Expected output:
```
Processing: AAAA - Data Analytics Export - new format test.csv
  File hash: a1b2c3d4...
  Parsed 221 rows
  Detected submarket: Sarasota Market (Mixed)
    ZIP 34236 (downtown-sarasota): 178 rows
    ZIP 34228 (longboat-key): 43 rows
  Created import batch: <uuid>
  COMPLETED — inserted: 221, updated: 0, unchanged: 0

Processing: AAAA - Data Analytics Export - new format test 2.csv
  ...
  COMPLETED — inserted: 500, updated: 0, unchanged: 0
```

3. **Dedup test:** Run the same command again. Both files are now in `processed/`, so nothing happens. If you copy them back and run again, they'll be detected as duplicate files (matching SHA-256 hash) and skipped.

---

## Step 5: Verify in Supabase

Open [Table Editor](https://supabase.com/dashboard/project/qfcbtytjidvpczejwwtj/editor) and check:

- `raw_listings` — should have 721 rows
- `import_batches` — should have 2 completed batches
- Check enriched columns: `has_natural_gas`, `is_gated`, `monthly_association_cost`, `building_class`, etc.

---

## Daily Workflow

1. Run your saved MLS search in Stellar MLS
2. Export CSV (≤500 rows)
3. Drop it in `mls_imports/`
4. Run `python supabase/ingest_mls.py`

The script handles everything:
- Skips duplicate files automatically
- Upserts by ListingId (never creates duplicates)
- Detects changed data via SHA-256 hash comparison
- Tracks insert/update/unchanged counts per batch
- Archives processed files with timestamp

---

## Optional: Dry Run

Preview what would happen without writing to Supabase:

```bash
python supabase/ingest_mls.py --dry-run
```

## Optional: Process a Specific File

```bash
python supabase/ingest_mls.py "C:\path\to\specific\file.csv"
```

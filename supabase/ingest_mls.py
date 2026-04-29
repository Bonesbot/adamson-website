#!/usr/bin/env python3
"""
MLS CSV → Supabase Ingest Script (Direct Postgres)
Adamson Group Real Estate Data Pipeline

Reads CSV files from a local folder, computes dedup hashes, creates import
batch records, and upserts into Supabase via direct Postgres connection.

Designed to run on the BonesBot Windows mini-PC.

Requirements:
    pip install psycopg2-binary

Usage:
    python ingest_mls.py                      # Process all CSVs in the watch folder
    python ingest_mls.py path/to/file.csv     # Process a specific CSV file
    python ingest_mls.py --dry-run             # Preview without writing to Supabase
"""

import csv
import hashlib
import json
import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from collections import Counter

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_FILE = PROJECT_ROOT / ".env"

def load_env(env_path):
    """Minimal .env loader."""
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())

load_env(ENV_FILE)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

WATCH_FOLDER = os.environ.get(
    "MLS_WATCH_FOLDER",
    str(PROJECT_ROOT / "mls-imports")
)

ARCHIVE_FOLDER = os.environ.get(
    "MLS_ARCHIVE_FOLDER",
    str(PROJECT_ROOT / "mls-imports" / "processed")
)

BATCH_SIZE = 150

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "ingest.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("mls_ingest")

# ---------------------------------------------------------------------------
# CSV Column → DB Column Mapping
# ---------------------------------------------------------------------------

CSV_TO_DB = {
    "ListingKeyNumeric": "listing_key_numeric",
    "PropertyType": "property_type",
    "StateOrProvince": "state_or_province",
    "ListingId": "listing_id",
    "CountyOrParish": "county_or_parish",
    "City": "city",
    "MLSAreaMajor": "mls_area_major",
    "PostalCode": "postal_code",
    "SubdivisionName": "subdivision_name",
    "PropertySubType": "property_sub_type",
    "UnparsedAddress": "unparsed_address",
    "MlsStatus": "mls_status",
    "StandardStatus": "standard_status",
    "SpecialListingConditions": "special_listing_conditions",
    "CurrentPrice": "current_price",
    "LotSizeSquareFeet": "lot_size_square_feet",
    "LotSizeAcres": "lot_size_acres",
    "FloodZoneCode": "flood_zone_code",
    "BuilderName": "builder_name",
    "YearBuilt": "year_built",
    "ProjectedCompletionDate": "projected_completion_date",
    "MonthlyCondoFeeAmount": "monthly_condo_fee_amount",
    "ConstructionMaterials": "construction_materials",
    "PropertyCondition": "property_condition",
    "Furnished": "furnished",
    "AssociationFeeFrequency": "association_fee_frequency",
    "AssociationFeeRequirement": "association_fee_requirement",
    "CalculatedListPriceByCalculatedSqFt": "calculated_list_price_by_calculated_sqft",
    "ClosePriceByCalculatedSqFt": "close_price_by_calculated_sqft",
    "ClosePriceByCalculatedListPriceRatio": "close_price_by_calculated_list_price_ratio",
    "BuyerFinancing": "buyer_financing",
    "DaystoContract": "days_to_contract",
    "DaysOnMarket": "days_on_market",
    "CumulativeDaysOnMarket": "cumulative_days_on_market",
    "PoolPrivateYN": "pool_private_yn",
    "BedroomsTotal": "bedrooms_total",
    "BathroomsFull": "bathrooms_full",
    "BathroomsHalf": "bathrooms_half",
    "Pool": "pool",
    "LivingArea": "living_area",
    "Roof": "roof",
    "FloorNumber": "floor_number",
    "LeaseRestrictionsYN": "lease_restrictions_yn",
    "NumOfOwnYearsPriorToLse": "num_of_own_years_prior_to_lse",
    "MinimumLease": "minimum_lease",
    "LeaseTerm": "lease_term",
    "MonthlyHOAAmount": "monthly_hoa_amount",
    "TotalAnnualFees": "total_annual_fees",
    "AssociationFee": "association_fee",
    "CloseDate": "close_date",
    "PetRestrictions": "pet_restrictions",
    "PetsAllowed": "pets_allowed",
    "NumberOfPets": "number_of_pets",
    "MaxPetWeight": "max_pet_weight",
    "StreetName": "street_name",
    "ExpectedClosingDate": "expected_closing_date",
    "GarageSpaces": "garage_spaces",
    "Utilities": "utilities",
    "CommunityFeatures": "community_features",
    "ElementarySchool": "elementary_school",
    "MiddleOrJuniorSchool": "middle_or_junior_school",
    "HighSchool": "high_school",
    "LotFeatures": "lot_features",
    "StoriesTotal": "stories_total",
    "BuildingElevatorYN": "building_elevator_yn",
    "WaterView": "water_view",
    "WaterViewYN": "water_view_yn",
    "WaterfrontYN": "waterfront_yn",
    "WaterAccessYN": "water_access_yn",
    "WaterSource": "water_source",
    "WaterAccess": "water_access",
    "WaterExtras": "water_extras",
    "WaterExtrasYN": "water_extras_yn",
    "WaterfrontFeatures": "waterfront_features",
    "WaterfrontFeetTotal": "waterfront_feet_total",
    "TaxAnnualAmount": "tax_annual_amount",
    "DockDescrip": "dock_descrip",
    "DockDimensions": "dock_dimensions",
    "DockLiftCap": "dock_lift_cap",
    "DockYN": "dock_yn",
    "TaxYear": "tax_year",
    "CDDYN": "cdd_yn",
    "TaxOtherAnnualAssessmentAmount": "tax_other_annual_assessment_amount",
    "ListAgentFullName": "list_agent_full_name",
    "ListOfficeName": "list_office_name",
    "ListAgentMlsId": "list_agent_mls_id",
    "ListOfficeMlsId": "list_office_mls_id",
    "BuyerAgentFullName": "buyer_agent_full_name",
    "BuyerAgentMlsId": "buyer_agent_mls_id",
    "BuyerOfficeName": "buyer_office_name",
    "BuyerOfficeMlsId": "buyer_office_mls_id",
    "StatusChangeTimestamp": "status_change_timestamp",
    "PriceChangeTimestamp": "price_change_timestamp",
    "OriginalListPrice": "original_list_price",
    "PurchaseContractDate": "purchase_contract_date",
    "ListingContractDate": "listing_contract_date",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "View": "listing_view",
    "ParcelNumber": "parcel_number",
}

NUMERIC_COLS = {
    "listing_key_numeric", "current_price", "lot_size_square_feet",
    "lot_size_acres", "year_built", "monthly_condo_fee_amount",
    "calculated_list_price_by_calculated_sqft",
    "close_price_by_calculated_sqft",
    "close_price_by_calculated_list_price_ratio",
    "days_to_contract", "days_on_market", "cumulative_days_on_market",
    "bedrooms_total", "bathrooms_full", "bathrooms_half",
    "living_area", "num_of_own_years_prior_to_lse",
    "monthly_hoa_amount", "total_annual_fees", "association_fee",
    "max_pet_weight", "garage_spaces", "stories_total",
    "waterfront_feet_total", "tax_annual_amount", "dock_lift_cap",
    "tax_year", "tax_other_annual_assessment_amount",
    "original_list_price", "latitude", "longitude",
}

BOOLEAN_COLS = {
    "pool_private_yn", "lease_restrictions_yn",
    "building_elevator_yn", "water_view_yn", "waterfront_yn",
    "water_access_yn", "water_extras_yn", "dock_yn", "cdd_yn",
}

DATE_COLS = {
    "close_date", "purchase_contract_date", "listing_contract_date",
}

TIMESTAMP_COLS = {
    "projected_completion_date", "expected_closing_date",
    "status_change_timestamp", "price_change_timestamp",
}

# The columns we INSERT into raw_listings (all mapped MLS cols + pipeline cols)
# Enriched/computed columns are handled by the trigger function
INSERT_COLS = sorted(CSV_TO_DB.values()) + [
    "import_batch_id", "raw_mls_data", "data_hash",
]

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_bool(val):
    if val is None or val == "":
        return None
    return val.strip().upper() in ("YES", "TRUE", "Y", "1")

def parse_numeric(val):
    if val is None or val.strip() == "":
        return None
    cleaned = val.strip().replace(",", "").replace("$", "")
    try:
        if "." in cleaned:
            return float(cleaned)
        return int(cleaned)
    except ValueError:
        return None

def parse_date(val):
    if val is None or val.strip() == "":
        return None
    val = val.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return val

def parse_timestamp(val):
    if val is None or val.strip() == "":
        return None
    val = val.strip()
    for fmt in (
        "%m/%d/%Y %H:%M:%S %p", "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S", "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(val, fmt).isoformat()
        except ValueError:
            continue
    return val

def parse_csv_row(csv_row):
    """Convert a CSV row dict into a DB-ready dict + raw_mls_data."""
    db_row = {}
    raw_mls = {}

    for csv_col, value in csv_row.items():
        raw_mls[csv_col] = value
        db_col = CSV_TO_DB.get(csv_col)
        if db_col is None:
            continue

        if isinstance(value, str):
            value = value.strip()
            if value == "":
                value = None

        if value is not None:
            if db_col in BOOLEAN_COLS:
                value = parse_bool(value)
            elif db_col in NUMERIC_COLS:
                value = parse_numeric(str(value))
            elif db_col in DATE_COLS:
                value = parse_date(str(value))
            elif db_col in TIMESTAMP_COLS:
                value = parse_timestamp(str(value))

        db_row[db_col] = value

    return db_row, raw_mls

# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------

def file_hash(filepath):
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()

def row_data_hash(row_dict):
    hash_data = {k: row_dict.get(k, "") for k in sorted(CSV_TO_DB.values())}
    return hashlib.sha256(
        json.dumps(hash_data, sort_keys=True, default=str).encode()
    ).hexdigest()

# ---------------------------------------------------------------------------
# Submarket detection
# ---------------------------------------------------------------------------

ZIP_TO_AREA = {
    "34228": "longboat-key",
    "34236": "downtown-sarasota",
    "34242": "siesta-key",
}

def detect_submarket(rows):
    zip_counts = Counter()
    for row in rows:
        zc = str(row.get("postal_code", "") or "").strip()
        if zc:
            zip_counts[zc] += 1

    area_breakdown = {}
    area_slugs = set()
    for zc, count in zip_counts.items():
        slug = ZIP_TO_AREA.get(zc, "unknown")
        area_slugs.add(slug)
        area_breakdown[zc] = {"area": slug, "count": count}

    if len(area_slugs) == 0:
        submarket = "Unknown"
    elif len(area_slugs) == 1:
        submarket = list(area_slugs)[0].replace("-", " ").title()
    else:
        submarket = "Sarasota Market (Mixed)"

    return submarket, area_breakdown

# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def get_connection():
    """Create a direct Postgres connection to Supabase."""
    return psycopg2.connect(DATABASE_URL)

def check_duplicate_file(cur, file_hash_val):
    """Check if this exact file has already been loaded successfully."""
    cur.execute(
        "SELECT id, imported_at, total_rows FROM import_batches "
        "WHERE source_file_hash = %s AND status = 'completed'",
        (file_hash_val,)
    )
    return cur.fetchall()

def create_import_batch(cur, file_hash_val, submarket, area_breakdown, total_rows):
    """Create a new import batch record and return its UUID."""
    cur.execute(
        "INSERT INTO import_batches (source_file_hash, detected_submarket, area_breakdown, total_rows, status) "
        "VALUES (%s, %s, %s, %s, 'processing') RETURNING id",
        (file_hash_val, submarket, json.dumps(area_breakdown), total_rows)
    )
    return cur.fetchone()[0]

def finalize_batch(cur, batch_id, rows_inserted, rows_updated, rows_unchanged, status="completed"):
    """Update the import batch with final counts."""
    cur.execute(
        "UPDATE import_batches SET rows_inserted=%s, rows_updated=%s, "
        "rows_unchanged=%s, status=%s WHERE id=%s",
        (rows_inserted, rows_updated, rows_unchanged, status, batch_id)
    )

def upsert_listings(cur, rows, batch_id):
    """
    Upsert rows into raw_listings using ON CONFLICT with change detection.
    The trigger fn_compute_enrichments() fires automatically on insert/update.
    """
    inserted = 0
    updated = 0
    unchanged = 0

    # Build the upsert SQL dynamically from INSERT_COLS
    cols = INSERT_COLS
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)

    # For the ON CONFLICT UPDATE, exclude id, listing_id, first_seen_at
    update_cols = [c for c in cols if c not in ("listing_id",)]
    update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

    upsert_sql = (
        f"INSERT INTO raw_listings ({col_list}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (listing_id) DO UPDATE SET {update_set}, "
        f"change_count = raw_listings.change_count + 1 "
        f"RETURNING (xmax = 0) AS is_insert"
    )

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]

        # First, check existing hashes for this batch
        listing_ids = [r["listing_id"] for r in batch if r.get("listing_id")]
        cur.execute(
            "SELECT listing_id, data_hash FROM raw_listings WHERE listing_id = ANY(%s)",
            (listing_ids,)
        )
        existing = {row[0]: row[1] for row in cur.fetchall()}

        batch_inserted = 0
        batch_updated = 0
        batch_unchanged = 0

        for row in batch:
            lid = row.get("listing_id")
            if not lid:
                log.warning("Skipping row with no listing_id")
                continue

            new_hash = row.get("data_hash", "")
            old_hash = existing.get(lid)

            if old_hash == new_hash and old_hash is not None:
                batch_unchanged += 1
                continue

            # Build values tuple in INSERT_COLS order
            values = []
            for col in cols:
                if col == "import_batch_id":
                    values.append(str(batch_id))
                elif col == "raw_mls_data":
                    values.append(json.dumps(row.get("raw_mls_data", {})))
                elif col == "data_hash":
                    values.append(row.get("data_hash", ""))
                else:
                    values.append(row.get(col))

            cur.execute(upsert_sql, values)
            result = cur.fetchone()
            if result[0]:  # is_insert = True means xmax was 0 (new row)
                batch_inserted += 1
            else:
                batch_updated += 1

        inserted += batch_inserted
        updated += batch_updated
        unchanged += batch_unchanged

        # Commit per-batch so partial runs are durable. If the process is killed
        # mid-ingest (e.g. by a workspace bash timeout), the next run's
        # existing-hash check above will mark already-loaded listings as
        # unchanged and skip them, letting the work resume rather than starting
        # over from row 0.
        cur.connection.commit()

        log.info(
            f"  Batch {i // BATCH_SIZE + 1}: "
            f"+{batch_inserted} new, ~{batch_updated} updated, "
            f"={batch_unchanged} unchanged"
        )

    return inserted, updated, unchanged

# ---------------------------------------------------------------------------
# Main ingest pipeline
# ---------------------------------------------------------------------------

def ingest_csv(filepath, conn, dry_run=False):
    """
    Full ingest pipeline for a single CSV file.
    1. Compute file hash → check for duplicate
    2. Parse all rows → compute data hashes
    3. Detect submarket
    4. Create import batch
    5. Upsert rows with change detection
    6. Finalize batch
    7. Archive the file
    """
    filepath = Path(filepath)
    log.info(f"{'[DRY RUN] ' if dry_run else ''}Processing: {filepath.name}")

    # Step 1: File-level dedup
    fhash = file_hash(filepath)
    log.info(f"  File hash: {fhash[:16]}...")

    cur = conn.cursor()

    if not dry_run:
        dupes = check_duplicate_file(cur, fhash)
        if dupes:
            dupe = dupes[0]
            log.info(
                f"  SKIPPED — identical file already loaded on "
                f"{dupe[1]} ({dupe[2]} rows)"
            )
            cur.close()
            return {"status": "skipped_duplicate", "file": filepath.name}

    # Step 2: Parse CSV
    log.info(f"  Reading CSV...")
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        parsed_rows = []
        for csv_row in reader:
            db_row, raw_mls = parse_csv_row(csv_row)
            db_row["raw_mls_data"] = raw_mls
            db_row["data_hash"] = row_data_hash(db_row)
            parsed_rows.append(db_row)

    total_rows = len(parsed_rows)
    log.info(f"  Parsed {total_rows} rows")

    if total_rows == 0:
        log.warning(f"  Empty CSV — skipping")
        cur.close()
        return {"status": "empty", "file": filepath.name}

    # Step 3: Detect submarket
    submarket, area_breakdown = detect_submarket(parsed_rows)
    log.info(f"  Detected submarket: {submarket}")
    for zc, info in area_breakdown.items():
        log.info(f"    ZIP {zc} ({info['area']}): {info['count']} rows")

    if dry_run:
        log.info(f"  [DRY RUN] Would create batch and upsert {total_rows} rows")
        cur.close()
        return {
            "status": "dry_run", "file": filepath.name,
            "total_rows": total_rows, "submarket": submarket,
        }

    # Step 4: Create import batch
    batch_id = create_import_batch(cur, fhash, submarket, area_breakdown, total_rows)
    conn.commit()
    log.info(f"  Created import batch: {batch_id}")

    # Step 5: Upsert with change detection
    try:
        inserted, updated, unchanged = upsert_listings(cur, parsed_rows, batch_id)
        conn.commit()

        # Step 6: Finalize batch
        finalize_batch(cur, batch_id, inserted, updated, unchanged, "completed")
        conn.commit()

        log.info(
            f"  COMPLETED — "
            f"inserted: {inserted}, updated: {updated}, unchanged: {unchanged}"
        )

        # Step 7: Archive the file
        archive_dir = Path(ARCHIVE_FOLDER)
        archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"{timestamp}_{filepath.name}"
        archive_path = archive_dir / archive_name
        filepath.rename(archive_path)
        log.info(f"  Archived to: {archive_path}")

        cur.close()
        return {
            "status": "completed", "file": filepath.name,
            "batch_id": str(batch_id), "total_rows": total_rows,
            "inserted": inserted, "updated": updated,
            "unchanged": unchanged, "submarket": submarket,
        }

    except Exception as e:
        conn.rollback()
        try:
            finalize_batch(cur, batch_id, 0, 0, 0, "failed")
            conn.commit()
        except Exception:
            conn.rollback()
        cur.close()
        log.error(f"  FAILED: {e}")
        raise

def ingest_all(folder=None, dry_run=False):
    """Process all CSV files in the watch folder."""
    folder = Path(folder or WATCH_FOLDER)

    if not folder.exists():
        log.info(f"Creating watch folder: {folder}")
        folder.mkdir(parents=True, exist_ok=True)
        log.info(f"Drop MLS CSV exports into: {folder}")
        return []

    csv_files = sorted(folder.glob("*.csv"))
    if not csv_files:
        log.info(f"No CSV files found in {folder}")
        return []

    log.info(f"Found {len(csv_files)} CSV file(s) in {folder}")

    conn = get_connection()
    log.info(f"  Connected to Postgres")
    results = []

    for csv_file in csv_files:
        try:
            result = ingest_csv(csv_file, conn, dry_run=dry_run)
            results.append(result)
        except Exception as e:
            log.error(f"Failed to process {csv_file.name}: {e}")
            results.append({"status": "error", "file": csv_file.name, "error": str(e)})

    conn.close()

    # Summary
    log.info("\n" + "=" * 60)
    log.info("INGEST SUMMARY")
    log.info("=" * 60)
    for r in results:
        icon = {
            "completed": "OK", "skipped_duplicate": "SKIP",
            "dry_run": "DRY", "empty": "EMPTY", "error": "FAIL",
        }.get(r["status"], "??")
        log.info(f"  [{icon}] {r['file']}: {r['status']}")
        if r["status"] == "completed":
            log.info(
                f"        +{r['inserted']} new, "
                f"~{r['updated']} updated, "
                f"={r['unchanged']} unchanged"
            )

    return results

# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    if not DATABASE_URL:
        log.error(
            "Missing DATABASE_URL in .env file.\n"
            f"Expected .env location: {ENV_FILE}"
        )
        sys.exit(1)

    log.info(f"MLS Ingest Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'configured'}")

    dry_run = "--dry-run" in sys.argv
    if dry_run:
        log.info("*** DRY RUN MODE — no data will be written ***")

    file_args = [a for a in sys.argv[1:] if a != "--dry-run" and not a.startswith("-")]

    if file_args:
        conn = get_connection()
        for fpath in file_args:
            ingest_csv(fpath, conn, dry_run=dry_run)
        conn.close()
    else:
        ingest_all(dry_run=dry_run)

if __name__ == "__main__":
    main()

-- Migration: add raw_listings.expiration_date
-- Context: 2026-07-12 MLS export format change (v2). Stellar "Data Analytics
-- Export - new fields and status" dropped the TaxYear column and added
-- ExpirationDate (last column). ingest_mls.py CSV_TO_DB now maps
-- ExpirationDate -> expiration_date, so the column must exist before the next
-- ingest or the INSERT will fail.
--
-- Idempotent: safe to run whether or not the column already exists.
-- Run this against the live Supabase DB BEFORE the first v2-format ingest.

ALTER TABLE raw_listings
    ADD COLUMN IF NOT EXISTS expiration_date date;

COMMENT ON COLUMN raw_listings.expiration_date IS
    'Listing agreement expiration date from MLS ExpirationDate (v2 export, 2026-07-12). Keys Stale-Seller Packet Lane A expiry triggers.';

-- Note: tax_year is intentionally left in place. The v2 CSV no longer supplies
-- TaxYear, so the ingest map no longer writes it; existing values are retained.
-- No DROP is performed (non-destructive).

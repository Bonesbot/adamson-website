-- ============================================================
-- Migration: off_market_leads
-- Purpose  : Confidential seller intent registry for the
--            /off-market page on AdamsonFL.com.
--
-- Populated by: netlify/functions/off-market-lead.js
--
-- Run this ONCE in the Supabase SQL Editor (Dashboard →
-- SQL Editor → New query → paste → Run).
-- Safe to re-run — all statements use IF NOT EXISTS.
-- ============================================================


-- ── Table ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.off_market_leads (

  -- Internal identity
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at  timestamptz NOT NULL    DEFAULT now(),

  -- Seller contact
  first_name  text,
  last_name   text,
  email       text NOT NULL,            -- required; used to de-dup and follow up
  phone       text,                     -- optional

  -- Property details (free-form; sellers type what they know)
  neighborhood_subdivision  text,       -- e.g. "Bird Key", "Harbor Acres", "Prestancia"

  -- Property Type: array of chip values from the form
  --   valid values: 'single-family' | 'condo' | 'townhome' |
  --                 'waterfront-dockage' | 'beachfront' | 'estate-acreage'
  property_types  text[],

  -- Approximate Size: dropdown value from the form
  --   valid values: 'under-1500' | '1500-2500' | '2500-4000' |
  --                 '4000-6000' | '6000-plus'
  approx_size  text,

  -- Bedrooms: pill selector value
  --   valid values: '1-2' | '3' | '4' | '5-plus'
  bedrooms  text,

  -- Price Threshold: the slider value(s) in whole USD
  --   price_threshold_min = "the number that would get your attention"
  --   price_threshold_max = reserved for future range selector (null for now)
  price_threshold_min  bigint,
  price_threshold_max  bigint,

  -- Timeline: pill selector value
  --   valid values: 'right-now' | '6-12-months' | '1-2-years' | 'exploring'
  timeline  text,

  -- Optional free-text from seller
  notes   text,

  -- Source tag — always 'off-market-page' from this form
  source  text NOT NULL DEFAULT 'off-market-page',

  -- Full raw JSON payload from the Netlify function (debugging + future fields)
  raw_payload  jsonb

);


-- ── Indexes ─────────────────────────────────────────────────

-- Fast lookup by email (de-dup checks, follow-up queries)
CREATE INDEX IF NOT EXISTS off_market_leads_email_idx
  ON public.off_market_leads (email);

-- Most-recent-first default sort for Ryan's review dashboard
CREATE INDEX IF NOT EXISTS off_market_leads_created_idx
  ON public.off_market_leads (created_at DESC);

-- Array-aware index on property_types (GIN supports @>, &&, etc.)
CREATE INDEX IF NOT EXISTS off_market_leads_property_types_idx
  ON public.off_market_leads USING GIN (property_types);

-- Price range lookups (match sellers to active buyer budgets)
CREATE INDEX IF NOT EXISTS off_market_leads_price_idx
  ON public.off_market_leads (price_threshold_min)
  WHERE price_threshold_min IS NOT NULL;


-- ── Row Level Security ──────────────────────────────────────
-- Enabled so future policies can be layered on without a
-- schema change. The service-role key used by the Netlify
-- function bypasses RLS, so inserts work without a policy.

ALTER TABLE public.off_market_leads ENABLE ROW LEVEL SECURITY;


-- ── Helpful view: recent leads for quick review ─────────────

CREATE OR REPLACE VIEW public.vw_off_market_leads_recent AS
SELECT
  id,
  created_at,
  first_name || ' ' || COALESCE(last_name, '')  AS full_name,
  email,
  phone,
  neighborhood_subdivision,
  property_types,
  approx_size,
  bedrooms,
  price_threshold_min,
  timeline,
  LEFT(notes, 120)  AS notes_preview,
  source
FROM public.off_market_leads
ORDER BY created_at DESC;

COMMENT ON VIEW public.vw_off_market_leads_recent IS
  'Quick-review view: recent off-market seller registrations, newest first.';

-- ── Done ────────────────────────────────────────────────────

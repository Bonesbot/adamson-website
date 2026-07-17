// netlify/functions/off-market-lead.js
//
// Captures off-market seller interest registrations into Supabase public.off_market_leads.
//
// ── Supabase table DDL (run once in Supabase SQL editor) ──────────────────────────
//
//   create table if not exists public.off_market_leads (
//     id                       uuid        primary key default gen_random_uuid(),
//     created_at               timestamptz not null default now(),
//     first_name               text,
//     last_name                text,
//     email                    text        not null,
//     phone                    text,
//     neighborhood_subdivision text,
//     property_types           text[],
//     approx_size              text,
//     bedrooms                 text,
//     price_threshold_min      bigint,
//     price_threshold_max      bigint,
//     timeline                 text,
//     notes                    text,
//     source                   text        default 'off-market-page',
//     raw_payload              jsonb
//   );
//
//   create index if not exists off_market_leads_email_idx
//     on public.off_market_leads (email);
//   create index if not exists off_market_leads_created_idx
//     on public.off_market_leads (created_at desc);
//   alter table public.off_market_leads enable row level security;
//
// ─────────────────────────────────────────────────────────────────────────────────
//
// Env vars (Netlify dashboard): SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
// No npm deps — uses global fetch (Netlify Node 18+)

exports.handler = async (event) => {
  // CORS preflight
  if (event.httpMethod === 'OPTIONS') {
    return {
      statusCode: 200,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
      },
      body: '',
    };
  }

  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: 'Method Not Allowed' };
  }

  try {
    const body = JSON.parse(event.body || '{}');

    // Honeypot — silently discard bots
    if (body['bot-field']) {
      return { statusCode: 200, body: JSON.stringify({ success: true }) };
    }

    const SUPABASE_URL = process.env.SUPABASE_URL;
    const KEY          = process.env.SUPABASE_SERVICE_ROLE_KEY;

    if (!SUPABASE_URL || !KEY) {
      console.error('off-market-lead: missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY');
      return {
        statusCode: 500,
        body: JSON.stringify({ error: 'Server configuration error' }),
      };
    }

    // ── Helpers ────────────────────────────────────────────────────
    const toArr = (v) =>
      Array.isArray(v)
        ? v.filter(Boolean)
        : typeof v === 'string' && v.trim()
        ? v.split(',').map((s) => s.trim()).filter(Boolean)
        : [];

    const toInt = (v) => {
      const n = parseInt(String(v ?? '').replace(/[^0-9]/g, ''), 10);
      return Number.isNaN(n) ? null : n;
    };

    // ── Validate ───────────────────────────────────────────────────
    if (!body.email || !body.email.trim()) {
      return {
        statusCode: 400,
        body: JSON.stringify({ error: 'Email is required' }),
      };
    }

    // ── Build row ──────────────────────────────────────────────────
    const row = {
      first_name:  (body.first_name || '').trim() || null,
      last_name:   (body.last_name  || '').trim() || null,
      email:       body.email.trim(),
      phone:       (body.phone      || '').trim() || null,
      source:      'off-market:seller',
      lead_type:   'Seller',
      page:        (body.page || '/off-market').trim(),
      message:     (body.notes || '').trim() || null,
      // Form-specific fields live in details jsonb (GIN indexed) — the core
      // queue stays the same shape for every form.
      details: {
        neighborhood_subdivision: (body.neighborhood_subdivision || '').trim() || null,
        property_types:           toArr(body.property_types),
        approx_size:              (body.approx_size || '').trim() || null,
        bedrooms:                 (body.bedrooms    || '').trim() || null,
        price_threshold_min:      toInt(body.price_threshold_min),
        price_threshold_max:      toInt(body.price_threshold_max),
        timeline:                 (body.timeline    || '').trim() || null,
      },
      raw_payload: body,
    };

    // ── Insert into Supabase ───────────────────────────────────────
    const res = await fetch(`${SUPABASE_URL}/rest/v1/leads`, {
      method: 'POST',
      headers: {
        apikey:         KEY,
        Authorization:  `Bearer ${KEY}`,
        'Content-Type': 'application/json',
        Prefer:         'return=minimal',
      },
      body: JSON.stringify(row),
    });

    if (!res.ok) {
      const text = await res.text();
      console.error('off-market-lead: Supabase insert failed', res.status, text);
      return {
        statusCode: 500,
        body: JSON.stringify({ error: 'Failed to save registration' }),
      };
    }

    console.log('off-market-lead: registration stored for', row.email);
    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ success: true }),
    };

  } catch (err) {
    console.error('off-market-lead: unexpected error', err);
    return {
      statusCode: 500,
      body: JSON.stringify({ error: 'Internal server error' }),
    };
  }
};

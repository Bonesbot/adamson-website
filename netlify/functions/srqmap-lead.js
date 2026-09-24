// netlify/functions/srqmap-lead.js
//
// SRQmap gate lead capture. Writes to public.leads (THE core lead queue — see
// supabase/migrations/leads.sql). Durable source of truth, so the
// client base survives even if IDX Broker is ever dropped) AND forwards the lead
// to IDX Broker Engage via the API. The IDX call is time-bounded so a slow/down
// IDX can never block the Supabase save; if it fails the lead is still stored
// (idx_sync records the outcome).
//
// ── Supabase table: see supabase/migrations/srqmap_leads.sql ──
// Env vars (Netlify): SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (required),
//                     IDX_API_KEY (optional — enables Engage sync).
// No npm deps — global fetch (Netlify Node 18+).

import { assessSpam, logBlocked, spamDetails } from './_lib/spam.js';

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

export const handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 200, headers: CORS, body: '' };
  if (event.httpMethod !== 'POST') return { statusCode: 405, headers: CORS, body: 'Method Not Allowed' };

  try {
    const body = JSON.parse(event.body || '{}');


    const SUPABASE_URL = process.env.SUPABASE_URL;
    const KEY          = process.env.SUPABASE_SERVICE_ROLE_KEY;
    if (!SUPABASE_URL || !KEY) {
      console.error('srqmap-lead: missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY');
      return { statusCode: 500, headers: CORS, body: JSON.stringify({ error: 'Server configuration error' }) };
    }

    const email = (body.email || '').trim();
    const first = (body.first_name || '').trim();
    const last  = (body.last_name  || '').trim();
    const phone = (body.phone      || '').trim();
    if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      return { statusCode: 400, headers: CORS, body: JSON.stringify({ error: 'A valid email is required' }) };
    }


    // ── Spam gate (see _lib/spam.js) ──
    let verdict = null;
    try {
      verdict = await assessSpam({ body, event, headers: event.headers, source: (body.source || 'srqmap-gate'),
        fields: { name: [first, last].filter(Boolean).join(' '), email: email, phone: phone, message: (body.message || body.notes || '') } });
    } catch (e) { console.error('srqmap-lead: spam check failed (treated as ok):', String(e.message || e)); }
    if (verdict && verdict.kind === 'bot') {
      await logBlocked(verdict, { body, event, headers: event.headers, source: (body.source || 'srqmap-gate') });
      return { statusCode: 200, headers: { ...CORS, 'Content-Type': 'application/json' }, body: JSON.stringify({ success: true }) };
    }
    const flagged = Boolean(verdict && verdict.spam);

    // ── IDX Engage sync (best-effort, time-bounded) ──
    let idxLeadId = null;
    let idxSync   = 'skipped';
    const IDX_API_KEY = process.env.IDX_API_KEY;
    if (IDX_API_KEY && !flagged) {
      const ctrl  = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 6000);
      try {
        const form = new URLSearchParams();
        form.set('email', email);
        if (first) form.set('firstName', first);
        if (last)  form.set('lastName', last);
        const payload = form.toString();
        const idxRes = await fetch('https://api.idxbroker.com/leads/lead', {
          method: 'PUT',
          headers: {
            'Content-Type':   'application/x-www-form-urlencoded',
            'Content-Length': String(Buffer.byteLength(payload)),
            accesskey:        IDX_API_KEY,
            outputtype:       'json',
            apiversion:       '1.8.0',
          },
          body: payload,
          signal: ctrl.signal,
        });
        const txt = await idxRes.text();
        if (idxRes.ok) {
          try { const j = JSON.parse(txt); idxLeadId = j.newID || j.id || (j.lead && j.lead.id) || null; } catch (_) {}
          idxSync = 'ok';
        } else {
          idxSync = `error_${idxRes.status}`;
          console.error('srqmap-lead: IDX forward failed', idxRes.status, txt.slice(0, 200));
        }
      } catch (e) {
        idxSync = (e && e.name === 'AbortError') ? 'timeout' : 'exception';
        console.error('srqmap-lead: IDX forward', idxSync, e && e.message);
      } finally {
        clearTimeout(timer);
      }
    }

    // ── Persist to Supabase (source of truth) ──
    const row = {
      first_name:  first || null,
      last_name:   last  || null,
      email,
      phone:       phone || null,
      source:      (body.source || 'srqmap-gate').trim() || 'srqmap-gate',
      idx_lead_id: idxLeadId ? String(idxLeadId) : null,
      idx_sync:    idxSync,
      ...(flagged ? { status: 'spam', zoho_sync: 'skipped:spam' } : {}),
      details: verdict ? spamDetails(verdict) : null,
      raw_payload: body,
    };
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
      console.error('srqmap-lead: Supabase insert failed', res.status, text);
      return { statusCode: 500, headers: CORS, body: JSON.stringify({ error: 'Failed to save registration' }) };
    }

    console.log('srqmap-lead: stored', email, '| idx:', idxSync);
    return { statusCode: 200, headers: { ...CORS, 'Content-Type': 'application/json' },
             body: JSON.stringify({ success: true }) };

  } catch (err) {
    console.error('srqmap-lead: unexpected error', err);
    return { statusCode: 500, headers: CORS, body: JSON.stringify({ error: 'Internal server error' }) };
  }
};

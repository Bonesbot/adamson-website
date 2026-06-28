// netlify/functions/srqmap-lead.js
//
// SRQmap gate lead capture. Writes to Supabase FIRST (durable source of truth,
// so the client base survives even if IDX Broker is ever dropped), THEN forwards
// the lead to IDX Broker Engage via the API as a best-effort secondary sync.
//
// ── Supabase table DDL (see supabase/migrations/srqmap_leads.sql) ──
//   public.srqmap_leads (id, created_at, first_name, last_name, email,
//                        phone, source, idx_lead_id, idx_sync, raw_payload)
//
// Env vars (Netlify dashboard):
//   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY   (required — already set for other forms)
//   IDX_API_KEY                                (optional — enables Engage sync)
// No npm deps — uses global fetch (Netlify Node 18+).

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 200, headers: CORS, body: '' };
  if (event.httpMethod !== 'POST') return { statusCode: 405, headers: CORS, body: 'Method Not Allowed' };

  try {
    const body = JSON.parse(event.body || '{}');

    // Honeypot — silently accept & discard bots
    if (body['bot-field']) return { statusCode: 200, headers: CORS, body: JSON.stringify({ success: true }) };

    const SUPABASE_URL = process.env.SUPABASE_URL;
    const KEY          = process.env.SUPABASE_SERVICE_ROLE_KEY;
    if (!SUPABASE_URL || !KEY) {
      console.error('srqmap-lead: missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY');
      return { statusCode: 500, headers: CORS, body: JSON.stringify({ error: 'Server configuration error' }) };
    }

    // ── Validate ──
    const email = (body.email || '').trim();
    const first = (body.first_name || '').trim();
    const last  = (body.last_name  || '').trim();
    const phone = (body.phone      || '').trim();
    if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      return { statusCode: 400, headers: CORS, body: JSON.stringify({ error: 'A valid email is required' }) };
    }

    // ── 1) Forward to IDX Engage (best-effort, before insert so we can record the id) ──
    let idxLeadId = null;
    let idxSync   = 'skipped';
    let idxDetail = null; // TEMP debug
    const IDX_API_KEY = process.env.IDX_API_KEY;
    if (IDX_API_KEY) {
      // Bounded so a slow/down IDX can never stall the function or block the Supabase save.
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 6000);
      try {
        const form = new URLSearchParams();
        form.set('email', email);
        if (first) form.set('firstName', first);
        if (last)  form.set('lastName', last);
        const idxRes = await fetch('https://api.idxbroker.com/leads/lead', {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            accesskey:   IDX_API_KEY,
            outputtype:  'json',
            apiversion:  '1.7.0',
          },
          body: form.toString(),
          signal: ctrl.signal,
        });
        const txt = await idxRes.text();
        if (idxRes.ok) {
          try { const j = JSON.parse(txt); idxLeadId = j.newID || j.id || (j.lead && j.lead.id) || null; } catch (_) {}
          idxSync = 'ok';
        } else {
          idxSync = `error_${idxRes.status}`;
          idxDetail = txt.slice(0, 300); // TEMP debug
          console.error('srqmap-lead: IDX forward failed', idxRes.status, txt.slice(0, 200));
        }
      } catch (e) {
        idxSync = (e && e.name === 'AbortError') ? 'timeout' : 'exception';
        console.error('srqmap-lead: IDX forward', idxSync, e && e.message);
      } finally {
        clearTimeout(timer);
      }
    }

    // ── 2) Insert into Supabase (source of truth) ──
    const row = {
      first_name:  first || null,
      last_name:   last  || null,
      email,
      phone:       phone || null,
      source:      (body.source || 'srqmap-gate').trim() || 'srqmap-gate',
      idx_lead_id: idxLeadId ? String(idxLeadId) : null,
      idx_sync:    idxSync,
      raw_payload: body,
    };
    const res = await fetch(`${SUPABASE_URL}/rest/v1/srqmap_leads`, {
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
             body: JSON.stringify({ success: true, idx: idxSync, idxDetail }) };

  } catch (err) {
    console.error('srqmap-lead: unexpected error', err);
    return { statusCode: 500, headers: CORS, body: JSON.stringify({ error: 'Internal server error' }) };
  }
};

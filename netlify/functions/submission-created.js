// netlify/functions/submission-created.js
//
// Mirrors Netlify Forms submissions into Supabase public.leads (master queue):
//   • "Find My Dream Home" wishlists  (direct AJAX call from the page)
//   • "contact" page form             (via the Netlify submission-created event)
//
// The form submits TWO ways on purpose:
//   • Direct AJAX POST to this function  -> Supabase insert (guaranteed record)
//   • Netlify Forms POST                 -> Netlify sends the email notification
//                                           (and also invokes this function via
//                                            the "submission-created" event)
//
// To avoid a duplicate row, this function ONLY inserts for the DIRECT call.
// On the Netlify event it simply acknowledges (the email is sent by Netlify's
// own notification config, independent of this function).
//
// Env vars (Netlify dashboard): SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.
// No npm deps — global fetch (Netlify Node 18+).

exports.handler = async (event) => {
  try {
    const body = JSON.parse(event.body || '{}');

    let d;
    if (body.direct && body.data) {
      d = body.data;
    } else {
      const payload = body.payload || {};
      if (payload.form_name === 'contact') {
        // Contact form has no direct call — the event fires exactly once per
        // verified submission, so mirroring here cannot duplicate.
        return await storeContactLead(payload);
      }
      if (payload.form_name !== 'wishlist') {
        return { statusCode: 200, body: 'ignored (unhandled form)' };
      }
      // Netlify Forms event — email handled by Netlify; Supabase handled by the
      // form's direct call. Skip to avoid a duplicate insert.
      return { statusCode: 200, body: 'netlify event acknowledged (supabase handled by direct call)' };
    }

    // Honeypot — silently ignore bots.
    if (d['bot-field']) {
      return { statusCode: 200, body: 'ignored (honeypot)' };
    }

    const SUPABASE_URL = process.env.SUPABASE_URL;
    const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
    if (!SUPABASE_URL || !KEY) {
      console.error('submission-created: missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY');
      return { statusCode: 500, body: 'missing supabase env vars' };
    }

    const toArr = (v) =>
      Array.isArray(v)
        ? v
        : typeof v === 'string' && v.trim().length
        ? v.split(',').map((s) => s.trim()).filter(Boolean)
        : [];
    const num = (v) => {
      const n = parseFloat(String(v == null ? '' : v).replace(/[^0-9.]/g, ''));
      return Number.isNaN(n) ? null : n;
    };
    const intOf = (v) => {
      const n = parseInt(String(v == null ? '' : v).replace(/[^0-9]/g, ''), 10);
      return Number.isNaN(n) ? null : n;
    };

    const preferredAreas = toArr(d['areas']);
    const areasOther = (d['areas-other'] || '').trim();
    if (areasOther) preferredAreas.push(areasOther);

    const mustHaves = toArr(d['must-haves']);
    const mustOther = (d['must-haves-other'] || '').trim();
    if (mustOther) mustHaves.push(mustOther);

    const nameParts = String(d.name || '').trim().split(/\s+/).filter(Boolean);
    const row = {
      first_name: nameParts.length > 1 ? nameParts.slice(0, -1).join(' ') : null,
      last_name:  nameParts.length ? nameParts[nameParts.length - 1] : null,
      email: d.email || null,
      phone: d.phone || null,
      source: 'find-my-dream-home:buyer',
      lead_type: 'Buyer',
      page: '/find-my-dream-home',
      message: d.message || null,
      // The wishlist's typed fields move into details jsonb. GIN indexed, so the
      // Phase 2b matching engine can still query budget / areas / must-haves.
      details: {
        timeline: d.timeline || null,
        budget_usd: num(d.budget),
        property_types: toArr(d['property-type']),
        preferred_areas: preferredAreas,
        size_min_sqft: intOf(d['size-min']),
        size_max_sqft: intOf(d['size-max']),
        bedrooms_min: intOf(d['bedrooms']),
        bathrooms_min: intOf(d['bathrooms']),
        must_have_features: mustHaves,
      },
      raw_payload: d,
    };

    const res = await fetch(`${SUPABASE_URL}/rest/v1/leads`, {
      method: 'POST',
      headers: {
        apikey: KEY,
        Authorization: `Bearer ${KEY}`,
        'Content-Type': 'application/json',
        Prefer: 'return=minimal',
      },
      body: JSON.stringify(row),
    });

    if (!res.ok) {
      const text = await res.text();
      console.error('submission-created: Supabase insert failed', res.status, text);
      return { statusCode: 500, body: 'supabase insert failed' };
    }

    console.log('submission-created: wishlist stored for', row.email);
    return { statusCode: 200, body: 'wishlist stored' };
  } catch (err) {
    console.error('submission-created: error', err);
    return { statusCode: 500, body: 'error' };
  }
};

// ── Contact page form → public.leads ──────────────────────────────────────────
// source 'contact:<intent>' keeps the site-wide `<page-slug>:<intent>` tagging
// so the Command Center + cc-queue-poller treat it like every other lead.
async function storeContactLead(payload) {
  const d = payload.data || {};
  if (d['bot-field']) return { statusCode: 200, body: 'ignored (honeypot)' };
  if (!d.email) return { statusCode: 200, body: 'ignored (no email)' };

  const SUPABASE_URL = process.env.SUPABASE_URL;
  const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!SUPABASE_URL || !KEY) {
    console.error('submission-created: missing supabase env vars (contact)');
    return { statusCode: 500, body: 'missing supabase env vars' };
  }

  const interest = String(d.interest || '').toLowerCase();
  const intent = interest === 'buying' ? 'buyer' : interest === 'selling' ? 'seller' : 'general';
  const nameParts = String(d.name || '').trim().split(/\s+/).filter(Boolean);

  const row = {
    first_name: nameParts.length > 1 ? nameParts.slice(0, -1).join(' ') : null,
    last_name: nameParts.length ? nameParts[nameParts.length - 1] : null,
    email: d.email,
    phone: d.phone || null,
    source: 'contact:' + intent,
    lead_type: intent === 'buyer' ? 'Buyer' : intent === 'seller' ? 'Seller' : null,
    page: '/contact',
    message: d.message || null,
    details: { interest: d.interest || null, referrer: payload.referrer || null },
    raw_payload: d,
  };

  const res = await fetch(`${SUPABASE_URL}/rest/v1/leads`, {
    method: 'POST',
    headers: {
      apikey: KEY,
      Authorization: `Bearer ${KEY}`,
      'Content-Type': 'application/json',
      Prefer: 'return=minimal',
    },
    body: JSON.stringify(row),
  });
  if (!res.ok) {
    console.error('submission-created: contact insert failed', res.status, await res.text());
    return { statusCode: 500, body: 'supabase insert failed' };
  }
  console.log('submission-created: contact lead stored for', row.email);
  return { statusCode: 200, body: 'contact lead stored' };
}

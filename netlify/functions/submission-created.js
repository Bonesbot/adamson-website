// netlify/functions/submission-created.js
//
// Captures "Find My Dream Home" wishlists into Supabase (public.buyer_wishlists).
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
      if (payload.form_name !== 'wishlist') {
        return { statusCode: 200, body: 'ignored (not the wishlist form)' };
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

    const row = {
      full_name: d.name || null,
      email: d.email || null,
      phone: d.phone || null,
      timeline: d.timeline || null,
      budget_usd: num(d.budget),
      property_types: toArr(d['property-type']),
      preferred_areas: preferredAreas,
      size_min_sqft: intOf(d['size-min']),
      size_max_sqft: intOf(d['size-max']),
      bedrooms_min: intOf(d['bedrooms']),
      bathrooms_min: intOf(d['bathrooms']),
      must_have_features: mustHaves,
      dream_notes: d.message || null,
      source: 'find-my-dream-home',
      raw_payload: d,
    };

    const res = await fetch(`${SUPABASE_URL}/rest/v1/buyer_wishlists`, {
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

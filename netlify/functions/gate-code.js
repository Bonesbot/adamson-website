// netlify/functions/gate-code.js
//
// Open-house gate code, served only inside its time window. The code itself lives in
// Supabase public.gate_codes (RLS on, service role only), never in this public repo.
// GET /.netlify/functions/gate-code?id=5654 -> { open, code?, opens_at, closes_at }
// Outside the window, or with no code set, the code is never sent to the browser.

const H = { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex, nofollow' };

export const handler = async (event) => {
  const id = String((event.queryStringParameters || {}).id || '').replace(/[^a-z0-9-]/gi, '').slice(0, 40);
  const url = process.env.SUPABASE_URL, key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!id || !url || !key) return { statusCode: 200, headers: H, body: JSON.stringify({ open: false }) };
  try {
    const r = await fetch(`${url}/rest/v1/gate_codes?id=eq.${id}&select=code,opens_at,closes_at`, {
      headers: { apikey: key, Authorization: `Bearer ${key}` },
    });
    const row = (await r.json())[0];
    if (!row) return { statusCode: 200, headers: H, body: JSON.stringify({ open: false }) };
    const now = Date.now(), a = Date.parse(row.opens_at), b = Date.parse(row.closes_at);
    const open = Boolean(row.code) && now >= a && now <= b;
    return { statusCode: 200, headers: H, body: JSON.stringify({
      open, code: open ? row.code : undefined, opens_at: row.opens_at, closes_at: row.closes_at, ended: now > b,
    }) };
  } catch (err) {
    console.error('gate-code:', String(err && err.message || err));
    return { statusCode: 200, headers: H, body: JSON.stringify({ open: false }) };
  }
};

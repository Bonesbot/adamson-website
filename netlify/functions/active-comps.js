// netlify/functions/active-comps.js
//
// "What is on the market right now" grid for owner landing pages: the active and
// pending single-family listings in one subdivision, straight from the daily
// Stellar MLS import in Supabase (raw_listings), with a lot-location label that
// Home Platform's CMA cannot show (Canal / Open Bay / Garden).
//
//   GET /.netlify/functions/active-comps?subdivision=COUNTRY%20CLUB%20SHORES
//       [&status=Active,Pending] [&type=Single Family Residence]
//   -> { ok, asOf, subdivision, rows: [{ address, lot, yearBuilt, sqft, beds, pool,
//        listPrice, pricePerSqft, dom, cdom, originalListPrice, status, lat, lng }] }
//
// Field notes (Ryan, 2026-11-04):
//   yearBuilt is the MLS "Year Built" (YearBuilt), never the effective year.
//   sqft is heated living area (living_area).
//   dom is Stellar's current-listing clock; cdom is cumulative across relists.
//   Lot location comes from the MLS waterfront fields, not geometry:
//     Open Bay  = frontage on Bay/Harbor or the Intracoastal
//     Canal     = any canal frontage
//     Garden    = no water frontage (the interior/garden homes)
//   A listing with no frontage flag but a canal *view* is labeled "Canal (view)"
//   and flagged so Ryan can check it by eye.

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Content-Type': 'application/json',
};
const out = (code, body, extra) => ({ statusCode: code, headers: { ...CORS, ...(extra || {}) }, body: JSON.stringify(body) });

function sb() {
  const url = process.env.SUPABASE_URL, key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  return { url: url.replace(/\/$/, ''), headers: { apikey: key, Authorization: `Bearer ${key}` } };
}

const num = (v) => { const n = typeof v === 'string' ? parseFloat(v.replace(/,/g, '')) : v; return typeof n === 'number' && isFinite(n) ? n : null; };
const tokens = (s) => (s || '').split(',').map((t) => t.trim().toLowerCase()).filter(Boolean);

function lotLocation(r) {
  const wf = tokens(r.waterfront_features), wv = tokens(r.water_view);
  const has = (list, re) => list.some((t) => re.test(t));
  if (has(wf, /bay\/harbor|bay front|intracoastal|gulf/)) return { lot: 'Open Bay', lotNote: null };
  if (has(wf, /canal/)) return { lot: 'Canal', lotNote: null };
  if (r.waterfront_yn === true) return { lot: 'Waterfront', lotNote: (r.waterfront_features || '').trim() || null };
  if (has(wv, /canal/)) return { lot: 'Canal (view)', lotNote: 'MLS shows a canal view but no waterfront flag; verify' };
  return { lot: 'Garden', lotNote: null };
}

function titleCase(s) {
  return (s || '').toLowerCase().replace(/\b([a-z])/g, (m) => m.toUpperCase()).replace(/\b(Ln|Dr|Ct|Rd|St|Ave|Blvd|Way|Cir|Pl)\b/g, (m) => m);
}

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 204, headers: CORS, body: '' };
  if (event.httpMethod !== 'GET') return out(405, { error: 'GET only' });
  const q = event.queryStringParameters || {};
  const subdivision = (q.subdivision || '').trim().toUpperCase();
  if (!/^[A-Z0-9 .'&\/-]{3,60}$/.test(subdivision)) return out(400, { error: 'subdivision required' });
  const statuses = (q.status || 'Active,Pending').split(',').map((s) => s.trim()).filter((s) => /^[A-Za-z ]{3,20}$/.test(s));
  const type = (q.type || 'Single Family Residence').trim();

  const db = sb();
  if (!db) return out(500, { error: 'no supabase' });

  const p = new URLSearchParams({
    select: 'listing_id,unparsed_address,standard_status,property_sub_type,year_built,living_area,bedrooms_total,bathrooms_full,pool_private_yn,current_price,original_list_price,days_on_market,cumulative_days_on_market,listing_contract_date,waterfront_yn,waterfront_features,water_view,latitude,longitude,status_change_timestamp,imported_at',
    subdivision_name: `ilike.${subdivision}*`,
    standard_status: `in.(${statuses.join(',')})`,
    property_sub_type: `ilike.*${type}*`,
    order: 'current_price.asc',
    limit: '200',
  });

  try {
    const r = await fetch(`${db.url}/rest/v1/raw_listings?${p}`, { headers: db.headers });
    if (!r.ok) throw new Error(`supabase ${r.status}: ${(await r.text()).slice(0, 200)}`);
    const data = await r.json();
    // "As of" is the newest completed daily MLS import, not the row's first-seen date.
    let asOf = null;
    try {
      const b = await fetch(`${db.url}/rest/v1/import_batches?select=imported_at&status=eq.completed&order=imported_at.desc&limit=1`, { headers: db.headers });
      const bj = b.ok ? await b.json() : [];
      asOf = (bj[0] && bj[0].imported_at) || null;
    } catch { /* label only */ }
    const rows = data.map((x) => {
      const sqft = num(x.living_area), price = num(x.current_price);
      return {
        id: x.listing_id,
        address: titleCase(x.unparsed_address),
        status: x.standard_status,
        ...lotLocation(x),
        yearBuilt: num(x.year_built),
        sqft, beds: num(x.bedrooms_total), baths: num(x.bathrooms_full),
        pool: x.pool_private_yn === true,
        listPrice: price,
        pricePerSqft: price && sqft ? Math.round(price / sqft) : null,
        dom: num(x.days_on_market), cdom: num(x.cumulative_days_on_market),
        originalListPrice: num(x.original_list_price),
        listedDate: x.listing_contract_date || null,
        lat: num(x.latitude), lng: num(x.longitude),
      };
    });
    return out(200, { ok: true, asOf, subdivision, statuses, rows }, { 'Cache-Control': 'public, max-age=900, stale-while-revalidate=3600' });
  } catch (err) {
    return out(502, { ok: false, error: err.message });
  }
};

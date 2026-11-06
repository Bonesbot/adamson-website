// netlify/functions/active-comps.js
//
// "What is on the market right now" grid for owner landing pages, straight from
// the daily Stellar MLS import in Supabase (raw_listings).
//
// Two ways to define the competition set:
//
//   A) One subdivision (the 501 Gunwale pattern):
//      GET /.netlify/functions/active-comps?subdivision=COUNTRY%20CLUB%20SHORES
//          [&status=Active,Pending] [&type=Single Family Residence]
//
//   B) An explicit roster of MLS numbers, from whatever saved search Ryan ran
//      (any mix of geography and parameters). Membership is the list; the data
//      is live. Either from the query string or from the competition_sets table:
//      GET /.netlify/functions/active-comps?ids=A4707843,A4711413,...
//      GET /.netlify/functions/active-comps?set=4539-bay-club
//      MLS numbers that are not in raw_listings (outside the import geography)
//      come back in `missing` so the page can fall back to a dated snapshot.
//
//   -> { ok, asOf, mode, rows: [{ id, idxUrl, address, city, subdivision, status,
//        lot, lotNote, water, floor, yearBuilt, sqft, beds, baths, garage, pool,
//        hoaMonthly, listPrice, pricePerSqft, dom, cdom, originalListPrice,
//        pctOfOriginal, listedDate, listOffice, lat, lng }], missing: [] }
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
// Condo notes (2026-11-06):
//   hoaMonthly prefers monthly_association_cost (TotalAnnualFees / 12), the same
//   number the Listing Signals digest shows, then the monthly condo fee.
//   idxUrl is the on-domain IDX Broker detail page keyed by MLS number, the same
//   pattern listing_signals.py uses (d003 = Stellar MLS on IDX Broker).
//   listOffice is returned for the IDX "courtesy of" attribution on public pages.

const IDX_BASE = 'https://adamsonfl.com/idx/details/listing/d003';

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

// Short water label for condos: frontage first, then view. "Bay front", "Bay view", "Intracoastal view".
function waterLabel(r) {
  const wf = tokens(r.waterfront_features), wv = tokens(r.water_view);
  const name = (t) => /bay\/harbor|bay front|^bay/.test(t) ? 'Bay' : /intracoastal/.test(t) ? 'Intracoastal' : /gulf/.test(t) ? 'Gulf' : /canal/.test(t) ? 'Canal' : /lake|pond/.test(t) ? 'Lake' : null;
  const first = (list) => { for (const t of list) { const n = name(t); if (n) return n; } return null; };
  const f = first(wf), v = first(wv);
  if (f) return `${f} front`;
  if (v) return `${v} view`;
  return r.waterfront_yn === true ? 'Waterfront' : null;
}

function hoaMonthly(r) {
  const m = num(r.monthly_association_cost);
  if (m != null && m > 0) return Math.round(m);
  const a = num(r.total_annual_fees);
  if (a != null && a > 0) return Math.round(a / 12);
  const c = num(r.monthly_condo_fee_amount);
  if (c != null && c > 0) return Math.round(c);
  const h = num(r.monthly_hoa_amount);
  if (h != null && h > 0) return Math.round(h);
  return null;
}

function titleCase(s) {
  return (s || '').toLowerCase().replace(/\b([a-z])/g, (m) => m.toUpperCase()).replace(/\b(Ln|Dr|Ct|Rd|St|Ave|Blvd|Way|Cir|Pl)\b/g, (m) => m);
}

const SELECT = [
  'listing_id', 'unparsed_address', 'city', 'postal_code', 'subdivision_name', 'standard_status', 'property_sub_type',
  'year_built', 'living_area', 'bedrooms_total', 'bathrooms_full', 'pool_private_yn', 'garage_spaces', 'floor_number',
  'current_price', 'original_list_price', 'days_on_market', 'cumulative_days_on_market', 'listing_contract_date',
  'waterfront_yn', 'waterfront_features', 'water_view',
  'monthly_association_cost', 'total_annual_fees', 'monthly_condo_fee_amount', 'monthly_hoa_amount',
  'list_office_name', 'latitude', 'longitude', 'status_change_timestamp', 'imported_at',
].join(',');

function shape(x) {
  const sqft = num(x.living_area), price = num(x.current_price), orig = num(x.original_list_price);
  return {
    id: x.listing_id,
    idxUrl: x.listing_id ? `${IDX_BASE}/${encodeURIComponent(x.listing_id)}` : null,
    address: titleCase(x.unparsed_address),
    city: titleCase(x.city),
    postalCode: x.postal_code || null,
    subdivision: titleCase(x.subdivision_name),
    status: x.standard_status,
    ...lotLocation(x),
    water: waterLabel(x),
    floor: x.floor_number || null,
    yearBuilt: num(x.year_built),
    sqft, beds: num(x.bedrooms_total), baths: num(x.bathrooms_full),
    garage: num(x.garage_spaces),
    pool: x.pool_private_yn === true,
    hoaMonthly: hoaMonthly(x),
    listPrice: price,
    pricePerSqft: price && sqft ? Math.round(price / sqft) : null,
    dom: num(x.days_on_market), cdom: num(x.cumulative_days_on_market),
    originalListPrice: orig,
    pctOfOriginal: price && orig ? Math.round((price / orig) * 1000) / 10 : null,
    listedDate: x.listing_contract_date || null,
    listOffice: x.list_office_name ? titleCase(x.list_office_name) : null,
    lat: num(x.latitude), lng: num(x.longitude),
  };
}

async function asOfDate(db) {
  // "As of" is the newest completed daily MLS import, not the row's first-seen date.
  try {
    const b = await fetch(`${db.url}/rest/v1/import_batches?select=imported_at&status=eq.completed&order=imported_at.desc&limit=1`, { headers: db.headers });
    const bj = b.ok ? await b.json() : [];
    return (bj[0] && bj[0].imported_at) || null;
  } catch { return null; }
}

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 204, headers: CORS, body: '' };
  if (event.httpMethod !== 'GET') return out(405, { error: 'GET only' });
  const q = event.queryStringParameters || {};
  const db = sb();
  if (!db) return out(500, { error: 'no supabase' });

  const idOk = (s) => /^[A-Z0-9]{5,14}$/.test(s);
  let ids = (q.ids || '').split(',').map((s) => s.trim().toUpperCase()).filter(idOk);
  let setMeta = null;

  // Mode B2: named set from the competition_sets table (if it exists).
  if (!ids.length && q.set) {
    const key = String(q.set).trim().toLowerCase();
    if (!/^[a-z0-9-]{3,60}$/.test(key)) return out(400, { error: 'bad set' });
    try {
      const s = await fetch(`${db.url}/rest/v1/competition_sets?select=set_key,title,criteria,preset,listing_ids,seed_rows,seeded_at,notes&set_key=eq.${key}&limit=1`, { headers: db.headers });
      const sj = s.ok ? await s.json() : [];
      if (!sj[0]) return out(404, { ok: false, error: `no competition set "${key}"` });
      setMeta = sj[0];
      ids = (setMeta.listing_ids || []).map((s2) => String(s2).toUpperCase()).filter(idOk);
    } catch (err) {
      return out(502, { ok: false, error: err.message });
    }
  }

  try {
    let data, mode, extra = {};
    if (ids.length) {
      mode = setMeta ? 'set' : 'ids';
      const p = new URLSearchParams({ select: SELECT, listing_id: `in.(${ids.join(',')})`, order: 'current_price.asc', limit: '200' });
      const r = await fetch(`${db.url}/rest/v1/raw_listings?${p}`, { headers: db.headers });
      if (!r.ok) throw new Error(`supabase ${r.status}: ${(await r.text()).slice(0, 200)}`);
      data = await r.json();
      const found = new Set(data.map((x) => x.listing_id));
      let rows = data.map(shape);
      const missing = ids.filter((id) => !found.has(id));
      // Seed rows from the set cover MLS numbers outside the import geography.
      if (setMeta && Array.isArray(setMeta.seed_rows)) {
        const seeds = setMeta.seed_rows.filter((s) => missing.includes(String(s.id || '').toUpperCase()))
          .map((s) => ({ ...s, idxUrl: s.idxUrl || (s.id ? `${IDX_BASE}/${encodeURIComponent(s.id)}` : null), snapshot: true, snapshotAsOf: setMeta.seeded_at || null }));
        rows = rows.concat(seeds).sort((a, b) => (a.listPrice || 0) - (b.listPrice || 0));
      }
      extra = { ids, missing, set: setMeta ? { key: setMeta.set_key, title: setMeta.title, criteria: setMeta.criteria, preset: setMeta.preset, notes: setMeta.notes || {}, seededAt: setMeta.seeded_at || null } : null };
      const asOf = await asOfDate(db);
      return out(200, { ok: true, asOf, mode, rows, ...extra }, { 'Cache-Control': 'public, max-age=900, stale-while-revalidate=3600' });
    }

    // Mode A: one subdivision.
    mode = 'subdivision';
    const subdivision = (q.subdivision || '').trim().toUpperCase();
    if (!/^[A-Z0-9 .'&\/-]{3,60}$/.test(subdivision)) return out(400, { error: 'subdivision, set or ids required' });
    const statuses = (q.status || 'Active,Pending').split(',').map((s) => s.trim()).filter((s) => /^[A-Za-z ]{3,20}$/.test(s));
    const type = (q.type || 'Single Family Residence').trim();
    const p = new URLSearchParams({
      select: SELECT,
      subdivision_name: `ilike.${subdivision}*`,
      standard_status: `in.(${statuses.join(',')})`,
      property_sub_type: `ilike.*${type}*`,
      order: 'current_price.asc',
      limit: '200',
    });
    const r = await fetch(`${db.url}/rest/v1/raw_listings?${p}`, { headers: db.headers });
    if (!r.ok) throw new Error(`supabase ${r.status}: ${(await r.text()).slice(0, 200)}`);
    data = await r.json();
    const asOf = await asOfDate(db);
    return out(200, { ok: true, asOf, mode, subdivision, statuses, rows: data.map(shape) }, { 'Cache-Control': 'public, max-age=900, stale-while-revalidate=3600' });
  } catch (err) {
    return out(502, { ok: false, error: err.message });
  }
};

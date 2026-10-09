// netlify/functions/buildings.js
//
// API for the internal condo field tool at /mkt/buildings/ (Adamson Group agents only).
// One row per condo building (street address) with stats rolled up from public.raw_listings
// by the Supabase view v_condo_buildings, plus team overrides (condo_buildings) and shared
// field notes (condo_building_notes).
//
//   GET  ?zips=all | ?zips=34236,34228          building list + overrides + notes (needs key)
//   GET  ?action=photo&key=<building_key>       Street View photo of the building (proxied,
//                                              server-side GOOGLE_MAPS_KEY; 404 until the key
//                                              exists so the page can show a placeholder)
//   POST ?action=verify                         login gate (same edit key as the CMA workbench)
//   POST ?action=note      {building_key, note, author}
//   POST ?action=delnote   {id}
//   POST ?action=override  {building_key, display_name?, pets_override?, rental_override?,
//                           parking_override?, amenities_override?, hidden?, author}
//
// Every call except the photo requires header x-cma-key == env CMA_EDIT_KEY (decision
// 2026-10-08: reuse the CMA key rather than mint a second one). Photos are keyed by building
// and cached for a week at the CDN; the Google key never reaches the browser.
//
// Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, CMA_EDIT_KEY, GOOGLE_MAPS_KEY (optional).
// No npm deps: global fetch (Netlify Node 20).

const json = (statusCode, obj, extra) => ({
  statusCode,
  headers: {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-store',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type, x-cma-key',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    ...(extra || {}),
  },
  body: JSON.stringify(obj),
});

function keyMatches(given, expected) {
  if (typeof given !== 'string' || typeof expected !== 'string') return false;
  if (given.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < given.length; i++) diff |= given.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

function sb() {
  const url = process.env.SUPABASE_URL, key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  return { url: url.replace(/\/$/, ''), headers: { apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' } };
}

async function rest(db, path, init) {
  const r = await fetch(`${db.url}/rest/v1/${path}`, { ...init, headers: { ...db.headers, ...((init && init.headers) || {}) } });
  const text = await r.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!r.ok) throw new Error(`supabase ${r.status}: ${typeof body === 'string' ? body : JSON.stringify(body)}`);
  return body;
}

const BKEY_RE = /^[A-Z0-9][A-Z0-9 .'&\/-]{2,80}$/;
const clean = (s, max) => (typeof s === 'string' ? s.trim().slice(0, max || 500) : null) || null;

// ── Street View ──────────────────────────────────────────────────────────────
function bearing(lat1, lng1, lat2, lng2) {
  const toRad = (d) => (d * Math.PI) / 180, toDeg = (r) => (r * 180) / Math.PI;
  const dLng = toRad(lng2 - lng1);
  const y = Math.sin(dLng) * Math.cos(toRad(lat2));
  const x = Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) - Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(dLng);
  return (toDeg(Math.atan2(y, x)) + 360) % 360;
}

async function photo(db, bkey) {
  const gkey = process.env.GOOGLE_MAPS_KEY;
  if (!gkey) return { statusCode: 404, headers: { 'Cache-Control': 'public, max-age=3600' }, body: 'no GOOGLE_MAPS_KEY' };
  const rows = await rest(db, `v_condo_buildings?select=lat,lng,stories,photo_url&bkey=eq.${encodeURIComponent(bkey)}&limit=1`);
  const b = rows && rows[0];
  if (!b) return { statusCode: 404, body: 'unknown building' };
  if (b.photo_url) return { statusCode: 302, headers: { Location: b.photo_url, 'Cache-Control': 'public, max-age=86400' }, body: '' };

  const loc = `${b.lat},${b.lng}`;
  // Metadata call: finds the nearest outdoor pano so we can aim the camera at the building
  // and tilt up for towers. Free (no quota cost).
  let heading = null, pitch = 10;
  try {
    const m = await fetch(`https://maps.googleapis.com/maps/api/streetview/metadata?location=${loc}&radius=120&source=outdoor&key=${gkey}`).then((r) => r.json());
    if (m && m.status === 'OK' && m.location) {
      heading = Math.round(bearing(m.location.lat, m.location.lng, b.lat, b.lng));
      const st = Number(b.stories) || 3;
      pitch = st >= 12 ? 25 : st >= 6 ? 18 : 10;
    } else if (m && m.status !== 'OK') {
      return { statusCode: 404, headers: { 'Cache-Control': 'public, max-age=86400' }, body: `no pano: ${m.status}` };
    }
  } catch { /* fall through with auto heading */ }

  const params = new URLSearchParams({ size: '640x420', location: loc, fov: '85', pitch: String(pitch), radius: '120', source: 'outdoor', key: gkey });
  if (heading !== null) params.set('heading', String(heading));
  const r = await fetch(`https://maps.googleapis.com/maps/api/streetview?${params}`);
  if (!r.ok) return { statusCode: 404, body: `streetview ${r.status}` };
  const buf = Buffer.from(await r.arrayBuffer());
  return {
    statusCode: 200,
    headers: { 'Content-Type': r.headers.get('content-type') || 'image/jpeg', 'Cache-Control': 'public, max-age=604800, s-maxage=604800' },
    body: buf.toString('base64'),
    isBase64Encoded: true,
  };
}

// ── handler ──────────────────────────────────────────────────────────────────
exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return json(204, {});
  const q = event.queryStringParameters || {};
  const action = q.action || '';
  const db = sb();
  if (!db) return json(500, { error: 'Supabase env missing' });

  try {
    if (event.httpMethod === 'GET' && action === 'photo') {
      const bkey = clean(q.key, 100);
      if (!bkey || !BKEY_RE.test(bkey)) return json(400, { error: 'bad key' });
      return await photo(db, bkey);
    }

    const expected = process.env.CMA_EDIT_KEY;
    if (!expected) return json(500, { error: 'Server configuration error' });
    const given = event.headers['x-cma-key'] || event.headers['X-Cma-Key'] || '';
    if (!keyMatches(given, expected)) return json(401, { error: 'bad edit key' });

    if (event.httpMethod === 'GET') {
      // zips=all (the page default since 2026-10-08) returns every zip the import covers;
      // a comma list narrows it.
      const all = !q.zips || q.zips === 'all';
      const zips = all ? [] : String(q.zips).split(',').map((z) => z.trim()).filter((z) => /^\d{5}$/.test(z)).slice(0, 20);
      if (!all && !zips.length) return json(400, { error: 'zips required' });
      const sel = [
        'bkey', 'slug', 'postal_code', 'city', 'subdivision', 'subdivision_names', 'lat', 'lng', 'year_built', 'stories',
        'listings_total', 'last_activity', 'active_count', 'active_min', 'active_max',
        'closed24_count', 'closed24_min', 'closed24_max', 'closed24_median', 'closed24_median_ppsf',
        'all_closed_median', 'all_closed_count', 'median_size', 'hoa_mo',
        'pets_allowed', 'pet_restrictions', 'max_pet_weight', 'number_of_pets', 'big_dog_friendly',
        'minimum_lease', 'lease_restrictions', 'own_years_before_lease',
        'garage_spaces_max', 'garage_listings', 'elevator', 'waterfront', 'gulf_front', 'bay_front',
        'waterfront_features', 'water_views', 'community_features_raw', 'exterior_features_raw',
        'has_pool', 'has_fitness', 'has_tennis', 'has_pickleball', 'has_dock', 'gated', 'has_restaurant', 'building_class',
        'display_name', 'photo_url', 'pets_override', 'rental_override', 'parking_override', 'amenities_override', 'hidden',
        'updated_by', 'updated_at', 'note_count',
      ].join(',');
      const where = all ? '' : `&postal_code=in.(${zips.join(',')})`;
      // PostgREST caps a response at 1,000 rows (Supabase max-rows), so page through.
      const buildings = [];
      for (let off = 0; off < 10000; off += 1000) {
        const page = await rest(db, `v_condo_buildings?select=${sel}${where}&order=listings_total.desc,bkey.asc&limit=1000&offset=${off}`);
        buildings.push(...page);
        if (page.length < 1000) break;
      }
      // Trim payload for phones: percentile_cont returns 15-digit doubles; nobody needs those.
      for (const b of buildings) {
        for (const k of Object.keys(b)) {
          const v = b[k];
          if (v === null || v === undefined) continue;
          if (k === 'lat' || k === 'lng') b[k] = Math.round(Number(v) * 1e6) / 1e6;
          else if (typeof v === 'number' && !Number.isInteger(v)) b[k] = Math.round(v);
          else if (typeof v === 'string' && /^-?\d+(\.\d+)?$/.test(v) && !['bkey', 'slug', 'postal_code'].includes(k)) b[k] = Math.round(Number(v));
        }
      }
      // Notes table is small and internal: pull it whole and let the page join by building_key
      // (an in.(...) filter over 475 keys blew past the URL/header limit).
      const keys = new Set(buildings.map((b) => b.bkey));
      const allNotes = await rest(db, 'condo_building_notes?select=id,building_key,note,author,created_at&order=created_at.desc&limit=10000');
      const notes = allNotes.filter((n) => keys.has(n.building_key));
      const payload = { ok: true, zips: all ? 'all' : zips, generated_at: new Date().toISOString(), buildings, notes, photos: !!process.env.GOOGLE_MAPS_KEY };
      // ~1,400 buildings is a couple of MB raw; gzip it when the browser accepts (always).
      const accept = String(event.headers['accept-encoding'] || event.headers['Accept-Encoding'] || '');
      if (/gzip/.test(accept)) {
        const gz = require('zlib').gzipSync(Buffer.from(JSON.stringify(payload)));
        return { statusCode: 200, headers: { 'Content-Type': 'application/json', 'Content-Encoding': 'gzip', 'Cache-Control': 'no-store', 'Access-Control-Allow-Origin': '*' }, body: gz.toString('base64'), isBase64Encoded: true };
      }
      return json(200, payload);
    }

    if (event.httpMethod !== 'POST') return json(405, { error: 'method' });
    let body = {};
    try { body = JSON.parse(event.body || '{}'); } catch { return json(400, { error: 'bad json' }); }

    if (action === 'verify') return json(200, { ok: true });

    if (action === 'note') {
      const building_key = clean(body.building_key, 100), note = clean(body.note, 2000), author = clean(body.author, 40);
      if (!building_key || !BKEY_RE.test(building_key) || !note) return json(400, { error: 'building_key and note required' });
      const rows = await rest(db, 'condo_building_notes', { method: 'POST', headers: { Prefer: 'return=representation' }, body: JSON.stringify({ building_key, note, author }) });
      return json(200, { ok: true, note: rows[0] });
    }

    if (action === 'delnote') {
      const id = Number(body.id);
      if (!Number.isInteger(id) || id <= 0) return json(400, { error: 'id required' });
      await rest(db, `condo_building_notes?id=eq.${id}`, { method: 'DELETE' });
      return json(200, { ok: true });
    }

    if (action === 'override') {
      const building_key = clean(body.building_key, 100);
      if (!building_key || !BKEY_RE.test(building_key)) return json(400, { error: 'building_key required' });
      const row = { building_key, updated_by: clean(body.author, 40), updated_at: new Date().toISOString() };
      for (const f of ['display_name', 'pets_override', 'rental_override', 'parking_override', 'amenities_override', 'photo_url']) {
        if (f in body) row[f] = clean(body[f], f === 'photo_url' ? 1000 : 400);
      }
      if ('hidden' in body) row.hidden = !!body.hidden;
      const rows = await rest(db, 'condo_buildings?on_conflict=building_key', { method: 'POST', headers: { Prefer: 'resolution=merge-duplicates,return=representation' }, body: JSON.stringify(row) });
      return json(200, { ok: true, building: rows[0] });
    }

    return json(400, { error: `unknown action ${action}` });
  } catch (e) {
    console.error('buildings:', e);
    return json(500, { error: String(e.message || e) });
  }
};

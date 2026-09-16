// netlify/functions/str-comps.js
//
// Comparable short-term rentals for a subject property, two sources:
//
//   GET ?mode=airroi&lat&lon&bedrooms&baths&guests&radius[&refresh=1]   (refresh needs x-cma-key)
//       AirROI GET /listings/comparables. Cached in public.str_api_cache under a key built from the
//       rounded coordinates and the search parameters, so re-opening a property costs nothing.
//       Response: { source:'cache'|'live'|'none', fetched_at, comps:[...normalized...], raw_count }
//
//   GET ?mode=mls&lat&lon&radius&beds&sqft_min&sqft_max&year_min&year_max&pool&status
//       Sold and active single-family comps from public.raw_listings (bounding box on lat/lon,
//       distance computed here). Free; no cache needed.
//
// Normalized AirROI comp: { id, name, url, room_type, bedrooms, baths, guests, pool, amenities_n,
//   lat, lon, distance_mi, rating, reviews, superhost, pro_managed, min_nights, cleaning_fee,
//   ttm: { occupancy, adr, revpar, revenue, available_days, reserved_days, los },
//   l90d: { occupancy, adr, revpar, revenue } }
//
// No npm deps — global fetch (Netlify Node 18+).

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type, x-cma-key",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Content-Type": "application/json",
  "Cache-Control": "no-store"
};
const API = "https://api.airroi.com";
const COST = { "listings/comparables": 0.50 }; // Standard tier list price band midpoint ($0.10 to $1.00)
const out = (code, obj) => ({ statusCode: code, headers: CORS, body: JSON.stringify(obj) });
function num(v) { return v == null || v === "" || isNaN(Number(v)) ? null : Number(v); }
function pct(v) { const n = num(v); return n == null ? null : (n > 1 ? n / 100 : n); }
function distMi(lat1, lon1, lat2, lon2) {
  const R = 3958.8, dLat = (lat2 - lat1) * Math.PI / 180, dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}
function sb() {
  const url = process.env.SUPABASE_URL, key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  const h = { apikey: key, Authorization: "Bearer " + key, "Content-Type": "application/json" };
  return {
    get: async (path) => { const r = await fetch(url + "/rest/v1/" + path, { headers: h }); return r.ok ? r.json() : null; },
    upsert: async (table, row) => { await fetch(url + "/rest/v1/" + table + "?on_conflict=cache_key", { method: "POST", headers: Object.assign({ Prefer: "resolution=merge-duplicates,return=minimal" }, h), body: JSON.stringify(row) }); },
    insert: async (table, row) => { await fetch(url + "/rest/v1/" + table, { method: "POST", headers: Object.assign({ Prefer: "return=minimal" }, h), body: JSON.stringify(row) }); }
  };
}

// AirROI nests listing details and performance under sub-objects in some responses. Flatten up to
// three levels so the documented field names resolve wherever they sit (first occurrence wins).
function flatten(obj, depth, acc) {
  acc = acc || {}; depth = depth == null ? 3 : depth;
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return acc;
  for (const k of Object.keys(obj)) { const v = obj[k]; if (!(k in acc) && (v == null || typeof v !== "object" || Array.isArray(v))) acc[k] = v; }
  if (depth > 0) for (const k of Object.keys(obj)) { const v = obj[k]; if (v && typeof v === "object" && !Array.isArray(v)) flatten(v, depth - 1, acc); }
  return acc;
}
function normalize(raw, lat, lon) {
  const L = flatten(raw);
  const am = Array.isArray(L.amenities) ? L.amenities.map(String) : (typeof L.amenities === "string" ? L.amenities.split(/[,|;]/) : []);
  const pool = am.some((a) => /\bpool\b/i.test(a) && !/table|hot tub/i.test(a));
  const la = num(L.latitude), lo = num(L.longitude);
  return {
    id: L.listing_id || L.id, name: L.listing_name || L.name || "",
    url: L.listing_id ? "https://www.airbnb.com/rooms/" + String(L.listing_id).replace(/^air/i, "") : null,
    room_type: L.room_type, listing_type: L.listing_type,
    bedrooms: num(L.bedrooms), baths: num(L.baths), guests: num(L.guests), beds: num(L.beds),
    pool, amenities_n: am.length, amenities: am.slice(0, 60),
    lat: la, lon: lo, distance_mi: la != null && lo != null && lat != null ? Math.round(distMi(lat, lon, la, lo) * 100) / 100 : null,
    exact_location: L.exact_location == null ? null : !!L.exact_location,
    rating: num(L.rating_overall), reviews: num(L.num_reviews), superhost: !!L.superhost, pro_managed: !!L.professional_management,
    min_nights: num(L.min_nights), cleaning_fee: num(L.cleaning_fee), photo: L.cover_photo_url || null,
    ttm: { occupancy: pct(L.ttm_occupancy), adj_occupancy: pct(L.ttm_adjusted_occupancy), adr: num(L.ttm_avg_rate), revpar: num(L.ttm_revpar), revenue: num(L.ttm_revenue),
           available_days: num(L.ttm_available_days), reserved_days: num(L.ttm_days_reserved), blocked_days: num(L.ttm_blocked_days), los: num(L.ttm_avg_length_of_stay) },
    l90d: { occupancy: pct(L.l90d_occupancy), adr: num(L.l90d_avg_rate), revpar: num(L.l90d_revpar), revenue: num(L.l90d_revenue) }
  };
}

exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers: CORS, body: "" };
  const q = event.queryStringParameters || {};
  const given = event.headers["x-cma-key"] || event.headers["X-Cma-Key"] || "";
  const authed = !!process.env.CMA_EDIT_KEY && given === process.env.CMA_EDIT_KEY;
  const lat = num(q.lat), lon = num(q.lon);
  if (lat == null || lon == null) return out(400, { error: "lat/lon required" });

  try {
    if (q.mode === "mls") {
      const s = sb(); if (!s) return out(200, { comps: [], note: "no supabase" });
      const radius = Math.min(10, Math.max(0.25, num(q.radius) || 1));
      const dLat = radius / 69, dLon = radius / (69 * Math.cos(lat * Math.PI / 180));
      const p = new URLSearchParams({
        select: "listing_id,standard_status,unparsed_address,subdivision_name,property_sub_type,bedrooms_total,bathrooms_full,bathrooms_half,living_area,lot_size_square_feet,year_built,pool_private_yn,current_price,original_list_price,close_date,cumulative_days_on_market,buyer_financing,minimum_lease,latitude,longitude,detected_area,list_agent_full_name",
        latitude: "gte." + (lat - dLat), longitude: "gte." + (lon - dLon), limit: "400", order: "close_date.desc.nullslast"
      });
      p.append("latitude", "lte." + (lat + dLat)); p.append("longitude", "lte." + (lon + dLon));
      const st = (q.status || "Closed,Active,Pending").split(",").map((x) => x.trim()).filter(Boolean);
      p.append("standard_status", "in.(" + st.join(",") + ")");
      const type = q.type || "Single Family Residence";
      if (type !== "any") p.append("property_sub_type", "eq." + type);
      if (num(q.beds) != null) { const b = num(q.beds); p.append("bedrooms_total", "gte." + Math.max(0, b - (num(q.beds_tol) ?? 1))); p.append("bedrooms_total", "lte." + (b + (num(q.beds_tol) ?? 1))); }
      if (num(q.sqft_min) != null) p.append("living_area", "gte." + num(q.sqft_min));
      if (num(q.sqft_max) != null) p.append("living_area", "lte." + num(q.sqft_max));
      if (num(q.year_min) != null) p.append("year_built", "gte." + num(q.year_min));
      if (num(q.year_max) != null) p.append("year_built", "lte." + num(q.year_max));
      if (q.pool === "1") p.append("pool_private_yn", "is.true");
      if (q.pool === "0") p.append("pool_private_yn", "is.false");
      if (q.closed_since) p.append("or", "(standard_status.neq.Closed,close_date.gte." + q.closed_since + ")");
      const rows = (await s.get("raw_listings?" + p.toString())) || [];
      const comps = rows.map((r) => Object.assign({}, r, { distance_mi: Math.round(distMi(lat, lon, Number(r.latitude), Number(r.longitude)) * 100) / 100 }))
        .filter((r) => r.distance_mi <= radius).sort((a, b) => a.distance_mi - b.distance_mi);
      return out(200, { source: "warehouse", count: comps.length, comps });
    }

    // ---- AirROI comparables ----
    const bedrooms = Math.max(0, Math.round(num(q.bedrooms) ?? 3));
    const baths = Math.max(0, num(q.baths) ?? 2);
    const guests = Math.max(1, Math.round(num(q.guests) ?? bedrooms * 2));
    const radius = Math.min(10, Math.max(1, num(q.radius) || 3));
    const roomType = q.room_type || "entire_home";
    const cacheKey = "comps:" + lat.toFixed(3) + "," + lon.toFixed(3) + ":b" + bedrooms + ":ba" + baths + ":g" + guests + ":r" + radius + ":" + roomType;
    if (q.refresh !== "1") {
      const c = await (sb() ? sb().get("str_api_cache?cache_key=eq." + encodeURIComponent(cacheKey) + "&select=payload,fetched_at") : null);
      if (!c || !c[0]) return out(200, { source: "none", cache_key: cacheKey, params: { bedrooms, baths, guests, radius, roomType }, note: "No cached comps for these parameters. Run a live API call." });
      return out(200, Object.assign({ source: "cache", fetched_at: c[0].fetched_at, cache_key: cacheKey }, c[0].payload));
    }
    if (!authed) return out(401, { error: "edit key required for a live API call" });
    const key = process.env.AIRROI_API_KEY; if (!key) return out(200, { source: "none", note: "AIRROI_API_KEY not set" });
    const u = API + "/listings/comparables?latitude=" + lat + "&longitude=" + lon + "&bedrooms=" + bedrooms + "&baths=" + baths + "&guests=" + guests + "&radius=" + radius + "&room_type=" + encodeURIComponent(roomType) + "&currency=usd";
    const r = await fetch(u, { headers: { "X-API-KEY": key } });
    const s = sb(); if (s) s.insert("api_usage", { service: "airroi", endpoint: "listings/comparables", est_cost: COST["listings/comparables"], note: lat.toFixed(4) + "," + lon.toFixed(4) + " b" + bedrooms });
    const text = await r.text();
    if (!r.ok) return out(200, { source: "error", note: "airroi comparables " + r.status + " " + text.slice(0, 200) });
    // Airbnb listing ids exceed 2^53; quote them before JSON.parse so the last digits survive.
    const j = JSON.parse(text.replace(/"listing_id":\s*(\d{15,})/g, '"listing_id":"$1"'));
    let list = Array.isArray(j) ? j : (j.comparables || j.listings || j.entries || j.results || j.data || []);
    if (!Array.isArray(list)) list = [];
    const comps = list.map((L) => normalize(L, lat, lon));
    const sample = list[0] ? JSON.stringify(list[0], (k, v) => (k === "description" || k === "photo_urls" || k === "amenities") ? undefined : v).slice(0, 4000) : null;
    const topKeys = Array.isArray(j) ? ["<array>"] : Object.keys(j);
    const payload = { params: { bedrooms, baths, guests, radius, roomType }, raw_count: list.length, comps, subject: j.subject || null, as_of: new Date().toISOString().slice(0, 10), est_cost: COST["listings/comparables"], raw_top_keys: topKeys, raw_sample: sample };
    if (q.debug === "1") payload.debug = JSON.stringify(j).slice(0, 3000);
    if (s) await s.upsert("str_api_cache", { cache_key: cacheKey, kind: "comps", label: bedrooms + "bd/" + baths + "ba/" + guests + "g r" + radius + " @ " + lat.toFixed(3) + "," + lon.toFixed(3), payload, fetched_at: new Date().toISOString() });
    return out(200, Object.assign({ source: "live", fetched_at: new Date().toISOString(), cache_key: cacheKey }, payload));
  } catch (e) {
    return out(200, { source: "error", note: String(e.message || e) });
  }
};

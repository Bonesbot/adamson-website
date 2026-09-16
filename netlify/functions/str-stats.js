// netlify/functions/str-stats.js
//
// AirROI market stats for the STR dashboard, ON DEMAND ONLY. Every read is served from the
// Supabase cache (public.str_api_cache); AirROI is only called when the page sends refresh=1
// together with the edit key (header x-cma-key == env CMA_EDIT_KEY), so nobody can spend
// credits by loading the page.
//
//   GET ?market=<key>                     cached summary+bands for a configured submarket
//   GET ?lat=..&lon=..                    cached summary+bands for the market containing a point
//   GET ...&refresh=1  (x-cma-key)        call AirROI (lookup/search + summary + metrics), cache, return
//   GET ?mode=usage                       estimated spend from public.api_usage + balance setting
//   POST ?mode=setbalance (x-cma-key)     body { deposit: 10, since: "2026-09-16" }
//
// Response (market): { source: 'cache'|'live'|'none', fetched_at, market, market_key, summary:{...},
//                      bands:{...}, note }
//
// AirROI API (docs: https://www.airroi.com/api/documentation), header X-API-KEY:
//   GET  /markets/search?query=..   -> { entries:[{ full_name, country, region, locality, district, active_listings_count }] }
//   GET  /markets/lookup?lat&lng    -> market object for a point
//   POST /markets/summary           -> { occupancy, average_daily_rate, rev_par, revenue, booking_lead_time, length_of_stay, min_nights, active_listings_count }
//   POST /markets/metrics/all       -> { results:[ { date, occupancy:{avg,p25,p50,p75,p90}, average_daily_rate:{..}, revpar:{..}, revenue:{..}, ... } ] }
//
// Usage ledger: each upstream call inserts a row into public.api_usage at the published Standard
// list price. AirROI has no balance endpoint; the developer dashboard is the source of truth.
// No npm deps — global fetch (Netlify Node 18+).

const MARKETS = {
  "siesta-key":       { label: "Siesta Key", zip: "34242", queries: ["Siesta Key, Florida", "Siesta Key"] },
  "city-of-sarasota": { label: "City of Sarasota", zip: "34236", queries: ["Sarasota, Florida", "Sarasota"] },
  "longboat-key":     { label: "Longboat Key", zip: "34228", queries: ["Longboat Key, Florida", "Longboat Key"] },
  "lido-key":         { label: "Lido Key / St Armands", zip: "34236", queries: ["Lido Key, Florida", "Lido Key"] }
};

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type, x-cma-key",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Content-Type": "application/json",
  "Cache-Control": "no-store"
};
const API = "https://api.airroi.com";
const COST = { "markets/search": 0.01, "markets/lookup": 0.01, "markets/summary": 0.10, "markets/metrics/all": 0.25 };

const out = (code, obj) => ({ statusCode: code, headers: CORS, body: JSON.stringify(obj) });
function num(v) { return v == null || v === "" || isNaN(Number(v)) ? null : Number(v); }
function pct(v) { const n = num(v); return n == null ? null : (n > 1 ? n / 100 : n); }

/* ---------- Supabase helpers ---------- */
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
async function logUsage(endpoint, note) { const s = sb(); if (!s) return; try { await s.insert("api_usage", { service: "airroi", endpoint, est_cost: COST[endpoint] || 0, note: note || null }); } catch (e) {} }
async function cacheGet(key) { const s = sb(); if (!s) return null; const rows = await s.get("str_api_cache?cache_key=eq." + encodeURIComponent(key) + "&select=payload,fetched_at,label"); return rows && rows[0] ? rows[0] : null; }
async function cachePut(key, kind, label, payload) { const s = sb(); if (!s) return; await s.upsert("str_api_cache", { cache_key: key, kind, label, payload, fetched_at: new Date().toISOString() }); }

/* ---------- AirROI ---------- */
async function searchMarket(key, query) {
  const r = await fetch(API + "/markets/search?query=" + encodeURIComponent(query), { headers: { "X-API-KEY": key } });
  logUsage("markets/search", query);
  if (!r.ok) throw new Error("airroi search " + r.status);
  const j = await r.json();
  const entries = Array.isArray(j.entries) ? j.entries : [];
  if (!entries.length) return null;
  const isFL = (e) => /florida/i.test(String(e.region || "") + " " + String(e.full_name || ""));
  const want = query.split(",")[0].trim().toLowerCase();
  return entries.find((e) => String(e.full_name || "").toLowerCase().indexOf(want) >= 0 && isFL(e)) || entries.find(isFL) || entries[0];
}
async function lookupMarket(key, lat, lon) {
  const r = await fetch(API + "/markets/lookup?lat=" + encodeURIComponent(lat) + "&lng=" + encodeURIComponent(lon), { headers: { "X-API-KEY": key } });
  logUsage("markets/lookup", lat + "," + lon);
  if (!r.ok) throw new Error("airroi lookup " + r.status);
  const j = await r.json();
  const m = j && (j.market || j.entry || j);
  if (!m || !m.locality) return null;
  return { country: m.country, region: m.region, locality: m.locality, district: m.district || null,
           full_name: m.full_name || [m.district, m.locality, m.region, m.country].filter(Boolean).join(", "), active_listings_count: m.active_listings_count };
}
function marketBody(entry) {
  const market = { country: entry.country, region: entry.region, locality: entry.locality };
  if (entry.district) market.district = entry.district;
  return { market, currency: "usd", num_months: 12 };
}
async function postJSON(key, path, body) {
  const r = await fetch(API + path, { method: "POST", headers: { "X-API-KEY": key, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  logUsage(path.replace(/^\//, ""), body && body.market ? body.market.locality : null);
  if (!r.ok) throw new Error("airroi " + path + " " + r.status);
  return r.json();
}
function summarize(s, entry) {
  const occ = pct(s.occupancy), adr = num(s.average_daily_rate);
  const revpar = num(s.rev_par) != null ? num(s.rev_par) : (occ != null && adr != null ? adr * occ : null);
  return { occupancy: occ, adr, revpar, active_listings: num(s.active_listings_count) != null ? Math.round(num(s.active_listings_count)) : num(entry.active_listings_count),
           est_annual_revenue: revpar != null ? Math.round(revpar * 365) : (occ != null && adr != null ? Math.round(adr * 365 * occ) : null),
           revenue_reported: num(s.revenue), booking_lead_time: num(s.booking_lead_time), length_of_stay: num(s.length_of_stay), min_nights: num(s.min_nights) };
}
function bandify(raw) {
  const months = Array.isArray(raw.results) ? raw.results : [];
  const KEYS = ["avg", "p25", "p50", "p75", "p90"];
  const agg = (metric, sum) => {
    const o = {}; KEYS.forEach((k) => { o[k] = []; });
    months.forEach((m) => { const v = m && m[metric]; if (v && typeof v === "object") KEYS.forEach((k) => { const n = num(v[k]); if (n != null) o[k].push(n); }); });
    const r = {}; KEYS.forEach((k) => { r[k] = o[k].length ? (sum ? o[k].reduce((s, x) => s + x, 0) : o[k].reduce((s, x) => s + x, 0) / o[k].length) : null; });
    return r;
  };
  const P = (o) => ({ avg: pct(o.avg), p25: pct(o.p25), p50: pct(o.p50), p75: pct(o.p75), p90: pct(o.p90) });
  return { months: months.length, occupancy: P(agg("occupancy")), adr: agg("average_daily_rate"), revpar: agg("revpar"), revenue_annual: agg("revenue", true),
           length_of_stay: agg("length_of_stay"), booking_lead_time: agg("booking_lead_time"), min_nights: agg("min_nights"),
           active_listings: months.length ? Math.round(months.reduce((s, m) => s + (num(m.active_listings_count) || 0), 0) / months.length) : null,
           monthly: months.map((m) => ({ date: m.date, occ: num(m.occupancy && m.occupancy.avg), adr: num(m.average_daily_rate && m.average_daily_rate.avg), revpar: num(m.revpar && m.revpar.avg), listings: num(m.active_listings_count) })) };
}

/* ---------- handler ---------- */
exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers: CORS, body: "" };
  const q = event.queryStringParameters || {};
  const given = event.headers["x-cma-key"] || event.headers["X-Cma-Key"] || "";
  const authed = !!process.env.CMA_EDIT_KEY && given === process.env.CMA_EDIT_KEY;

  try {
    if (q.mode === "usage") {
      const s = sb(); if (!s) return out(200, { error: "no supabase" });
      const setting = await cacheGet("setting:airroi_balance");
      const since = setting && setting.payload && setting.payload.since ? setting.payload.since : "2026-09-16";
      const rows = await s.get("api_usage?service=eq.airroi&ts=gte." + encodeURIComponent(since) + "&select=est_cost,ts,endpoint&order=ts.desc&limit=5000");
      const calls = rows || [];
      const spent = calls.reduce((a, r) => a + Number(r.est_cost || 0), 0);
      const deposit = setting && setting.payload ? Number(setting.payload.deposit || 10) : 10;
      return out(200, { since, deposit, calls: calls.length, est_spent: Math.round(spent * 100) / 100, est_remaining: Math.round((deposit - spent) * 100) / 100, last_call: calls[0] ? calls[0].ts : null, last_endpoint: calls[0] ? calls[0].endpoint : null });
    }
    if (q.mode === "setbalance") {
      if (!authed) return out(401, { error: "edit key required" });
      let body = {}; try { body = JSON.parse(event.body || "{}"); } catch (e) {}
      await cachePut("setting:airroi_balance", "setting", "AirROI balance", { deposit: Number(body.deposit || 10), since: body.since || new Date().toISOString().slice(0, 10) });
      return out(200, { ok: true });
    }

    const lat = num(q.lat), lon = num(q.lon), byCoord = lat != null && lon != null;
    const mk = MARKETS[q.market] ? q.market : (byCoord ? null : "siesta-key");
    const cacheKey = byCoord ? "market:ll:" + lat.toFixed(3) + "," + lon.toFixed(3) : "market:" + mk;
    const refresh = q.refresh === "1";

    if (!refresh) {
      const c = await cacheGet(cacheKey);
      if (!c) return out(200, { source: "none", cache_key: cacheKey, note: "No cached AirROI data for this market yet. Run a live API call." });
      return out(200, Object.assign({ source: "cache", fetched_at: c.fetched_at, cache_key: cacheKey }, c.payload));
    }
    if (!authed) return out(401, { error: "edit key required for a live API call" });
    const key = process.env.AIRROI_API_KEY;
    if (!key) return out(200, { source: "none", note: "AIRROI_API_KEY not set" });

    let entry = null;
    if (byCoord) entry = await lookupMarket(key, lat, lon);
    if (!entry && mk) for (const query of MARKETS[mk].queries) { entry = await searchMarket(key, query); if (entry) break; }
    if (!entry) return out(200, { source: "none", note: byCoord ? "AirROI has no market at " + lat + "," + lon : "no market match" });
    const name = entry.full_name || [entry.locality, entry.region].filter(Boolean).join(", ");
    const [s, m] = await Promise.all([postJSON(key, "/markets/summary", marketBody(entry)), postJSON(key, "/markets/metrics/all", marketBody(entry))]);
    const payload = { market: name, market_key: mk || "by-coordinates", zip: mk ? MARKETS[mk].zip : (entry.district && /^\d{5}$/.test(entry.district) ? entry.district : null),
                      market_object: marketBody(entry).market, summary: summarize(s, entry), bands: bandify(m), window_months: 12, as_of: new Date().toISOString().slice(0, 7), est_cost: COST["markets/summary"] + COST["markets/metrics/all"] + (byCoord ? COST["markets/lookup"] : COST["markets/search"]) };
    await cachePut(cacheKey, "market", name, payload);
    return out(200, Object.assign({ source: "live", fetched_at: new Date().toISOString(), cache_key: cacheKey }, payload));
  } catch (e) {
    return out(200, { source: "error", note: String(e.message || e) });
  }
};

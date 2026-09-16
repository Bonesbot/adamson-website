// netlify/functions/str-stats.js
//
// Server-side proxy for AirROI short-term-rental market stats. Keeps the AirROI API key OFF the
// client. Returns normalized JSON the STR dashboard renders.
//
//   GET /.netlify/functions/str-stats                  -> 12-month market summary (default market)
//   GET /.netlify/functions/str-stats?mode=bands       -> p25 / p50 / p75 bands for occupancy + ADR
//   GET /.netlify/functions/str-stats?market=<key>     -> another configured submarket (see MARKETS)
//   GET ...&debug=1                                    -> include a trimmed raw upstream sample
//
// Activation: set env var AIRROI_API_KEY in the Netlify dashboard (Site settings > Env vars,
// scope Functions, context Production). Until then this returns clearly-labeled placeholder
// sample data so the page still works.
//
// AirROI API (docs: https://www.airroi.com/api/documentation), header X-API-KEY:
//   GET  /markets/search?query=...
//        -> { entries: [{ full_name, country, region, locality, district, native_currency, active_listings_count }] }
//   POST /markets/summary        body { market, currency, num_months }
//        -> { occupancy (0-1), average_daily_rate, rev_par, revenue, booking_lead_time, length_of_stay,
//             min_nights, active_listings_count }
//   POST /markets/metrics/all    body { market, currency, num_months }
//        -> monthly time series with percentile distributions (p25 / p50 / p75 / p90)
//
// Usage ledger: every upstream call inserts a row into public.api_usage (Supabase, service role)
// with the published list price so the page can show an ESTIMATED spend. AirROI exposes no
// balance endpoint; the developer dashboard is the source of truth.
//
// 2026-09-16: rewritten to the real AirROI response shape; bands mode + usage ledger added.
// No npm deps — global fetch (Netlify Node 18+).

const MARKETS = {
  "siesta-key":      { label: "Siesta Key", zip: "34242", queries: ["Siesta Key, Florida", "Siesta Key", "Sarasota, Florida"] },
  "city-of-sarasota":{ label: "City of Sarasota", zip: "34236", queries: ["Sarasota, Florida", "Sarasota"] },
  "longboat-key":    { label: "Longboat Key", zip: "34228", queries: ["Longboat Key, Florida", "Longboat Key", "Sarasota, Florida"] },
  "lido-key":        { label: "Lido Key / St Armands", zip: "34236", queries: ["Lido Key, Florida", "Lido Key", "Sarasota, Florida"] }
};

const PLACEHOLDER = {
  source: "placeholder",
  zip: "34242",
  market: "Siesta Key (sample)",
  occupancy: 0.62,
  adr: 415,
  revpar: 257,
  active_listings: 480,
  est_annual_revenue: 95000,
  as_of: null
};

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type",
  "Content-Type": "application/json",
  "Cache-Control": "public, max-age=21600" // 6h
};

const API = "https://api.airroi.com";
// Published Standard-tier list prices (airroi.com/api/pricing), used for the ESTIMATED ledger only.
const COST = { "markets/search": 0.01, "markets/summary": 0.10, "markets/metrics/all": 0.25 };

function num(v) { return v == null || v === "" || isNaN(Number(v)) ? null : Number(v); }
function pct(v) { const n = num(v); return n == null ? null : (n > 1 ? n / 100 : n); }

/* ---------- usage ledger (best effort, never blocks the response) ---------- */
async function logUsage(endpoint, note) {
  const url = process.env.SUPABASE_URL, key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return;
  try {
    await fetch(url + "/rest/v1/api_usage", {
      method: "POST",
      headers: { apikey: key, Authorization: "Bearer " + key, "Content-Type": "application/json", Prefer: "return=minimal" },
      body: JSON.stringify({ service: "airroi", endpoint, est_cost: COST[endpoint] || 0, note: note || null })
    });
  } catch (e) { /* ignore */ }
}

/* ---------- AirROI calls ---------- */
async function searchMarket(key, query) {
  const r = await fetch(API + "/markets/search?query=" + encodeURIComponent(query), { headers: { "X-API-KEY": key } });
  logUsage("markets/search", query);
  if (!r.ok) throw new Error("airroi search " + r.status);
  const j = await r.json();
  const entries = Array.isArray(j.entries) ? j.entries : (Array.isArray(j.markets) ? j.markets : []);
  if (!entries.length) return null;
  const isFL = (e) => /florida|^fl$/i.test(String(e.region || "")) || /florida/i.test(String(e.full_name || ""));
  const want = query.split(",")[0].trim().toLowerCase();
  return entries.find((e) => String(e.full_name || "").toLowerCase().indexOf(want) >= 0 && isFL(e))
      || entries.find(isFL)
      || entries[0];
}

function marketBody(entry) {
  const market = { country: entry.country, region: entry.region, locality: entry.locality };
  if (entry.district) market.district = entry.district;
  return { market, currency: "usd", num_months: 12 };
}

async function postJSON(key, path, body) {
  const r = await fetch(API + path, {
    method: "POST",
    headers: { "X-API-KEY": key, "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  logUsage(path.replace(/^\//, ""), body && body.market ? body.market.locality : null);
  if (!r.ok) throw new Error("airroi " + path + " " + r.status);
  return r.json();
}

/* ---------- percentile extraction (shape-tolerant) ---------- */
// Walks the metrics payload looking for a metric named like "occupancy" / "average_daily_rate" and
// collects any p25 / p50 / p75 / p90 values it finds (arrays are averaged over the months).
function findMetric(obj, names) {
  if (!obj || typeof obj !== "object") return null;
  for (const k of Object.keys(obj)) {
    const lk = k.toLowerCase();
    if (names.some((n) => lk === n || lk.indexOf(n) >= 0)) return obj[k];
  }
  for (const k of Object.keys(obj)) {
    const v = obj[k];
    if (v && typeof v === "object") { const f = findMetric(v, names); if (f) return f; }
  }
  return null;
}
function collectPercentiles(m) {
  const acc = { p25: [], p50: [], p75: [], p90: [], mean: [] };
  const push = (o) => {
    if (!o || typeof o !== "object") return;
    for (const k of Object.keys(o)) {
      const lk = k.toLowerCase().replace(/[^a-z0-9]/g, "");
      const v = num(o[k]);
      if (v == null) continue;
      if (/^(p|percentile)?25(th)?$/.test(lk)) acc.p25.push(v);
      else if (/^(p|percentile)?50(th)?$|^median$/.test(lk)) acc.p50.push(v);
      else if (/^(p|percentile)?75(th)?$/.test(lk)) acc.p75.push(v);
      else if (/^(p|percentile)?90(th)?$/.test(lk)) acc.p90.push(v);
      else if (/^(mean|avg|average|value)$/.test(lk)) acc.mean.push(v);
    }
  };
  if (Array.isArray(m)) m.forEach((row) => { push(row); if (row && typeof row === "object") Object.values(row).forEach(push); });
  else if (m && typeof m === "object") { push(m); Object.values(m).forEach((v) => { if (Array.isArray(v)) v.forEach(push); else push(v); }); }
  const avg = (a) => a.length ? a.reduce((s, x) => s + x, 0) / a.length : null;
  return { p25: avg(acc.p25), p50: avg(acc.p50), p75: avg(acc.p75), p90: avg(acc.p90), mean: avg(acc.mean), n: acc.p50.length || acc.mean.length };
}

/* ---------- handler ---------- */
exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers: CORS, body: "" };
  const q = event.queryStringParameters || {};
  const mk = MARKETS[q.market] ? q.market : "siesta-key";
  const M = MARKETS[mk];
  const mode = q.mode === "bands" ? "bands" : "summary";
  const debug = q.debug === "1";
  const ph = Object.assign({}, PLACEHOLDER, { market_key: mk, zip: M.zip });

  const key = process.env.AIRROI_API_KEY;
  if (!key) return { statusCode: 200, headers: CORS, body: JSON.stringify(Object.assign({}, ph, { note: "AIRROI_API_KEY not set" })) };

  try {
    let entry = null;
    for (const query of M.queries) { entry = await searchMarket(key, query); if (entry) break; }
    if (!entry) return { statusCode: 200, headers: CORS, body: JSON.stringify(Object.assign({}, ph, { note: "no market match for " + M.queries.join(" | ") })) };
    const name = entry.full_name || [entry.locality, entry.region].filter(Boolean).join(", ");

    if (mode === "bands") {
      const raw = await postJSON(key, "/markets/metrics/all", marketBody(entry));
      // Observed shape (2026-09): { market, results: [ { date, occupancy:{avg,p25,p50,p75,p90},
      //   average_daily_rate:{...}, revpar:{...}, revenue:{...} (per listing, per month),
      //   booking_lead_time, length_of_stay, min_nights, active_listings_count }, ... ] }
      const months = Array.isArray(raw.results) ? raw.results : (Array.isArray(raw) ? raw : []);
      const KEYS = ["avg", "p25", "p50", "p75", "p90"];
      const agg = (metric, sum) => {
        const o = {}; KEYS.forEach((k) => { o[k] = []; });
        months.forEach((m) => { const v = m && m[metric]; if (v && typeof v === "object") KEYS.forEach((k) => { const n = num(v[k]); if (n != null) o[k].push(n); }); });
        const out = {}; KEYS.forEach((k) => { out[k] = o[k].length ? (sum ? o[k].reduce((s, x) => s + x, 0) : o[k].reduce((s, x) => s + x, 0) / o[k].length) : null; });
        out.n = o.p50.length; return out;
      };
      let occ, adr, rev, revpar, los, lead, minn;
      if (months.length) {
        occ = agg("occupancy"); adr = agg("average_daily_rate"); revpar = agg("revpar");
        rev = agg("revenue", true); los = agg("length_of_stay"); lead = agg("booking_lead_time"); minn = agg("min_nights");
      } else { // fallback to the shape-tolerant walker
        const c = (x) => Object.assign({ avg: x.mean, n: x.n }, x);
        occ = c(collectPercentiles(findMetric(raw, ["occupancy"]))); adr = c(collectPercentiles(findMetric(raw, ["average_daily_rate", "adr"])));
        rev = c(collectPercentiles(findMetric(raw, ["revenue"]))); revpar = los = lead = minn = { avg: null, p25: null, p50: null, p75: null, p90: null, n: 0 };
      }
      const P = (o) => ({ avg: pct(o.avg), p25: pct(o.p25), p50: pct(o.p50), p75: pct(o.p75), p90: pct(o.p90) });
      const D = (o) => ({ avg: o.avg, p25: o.p25, p50: o.p50, p75: o.p75, p90: o.p90 });
      const out = {
        source: occ.p50 != null ? "live" : "partial",
        market_key: mk, market: name, zip: M.zip, window_months: months.length || 12, months_used: occ.n,
        occupancy: P(occ), adr: D(adr), revpar: D(revpar),
        revenue_annual: D(rev), // sum of the monthly per-listing bands
        length_of_stay: D(los), booking_lead_time: D(lead), min_nights: D(minn),
        active_listings: months.length ? Math.round(months.reduce((s, m) => s + (num(m.active_listings_count) || 0), 0) / months.length) : null,
        monthly: months.map((m) => ({ date: m.date, occ: num(m.occupancy && m.occupancy.avg), adr: num(m.average_daily_rate && m.average_daily_rate.avg), revpar: num(m.revpar && m.revpar.avg), listings: num(m.active_listings_count) })),
        as_of: new Date().toISOString().slice(0, 7)
      };
      if (debug) out.debug = JSON.stringify(raw).slice(0, 4000);
      return { statusCode: 200, headers: CORS, body: JSON.stringify(out) };
    }

    const s = await postJSON(key, "/markets/summary", marketBody(entry));
    const occ = pct(s.occupancy);
    const adr = num(s.average_daily_rate);
    const revpar = num(s.rev_par) != null ? num(s.rev_par) : (occ != null && adr != null ? adr * occ : null);
    if (occ == null || adr == null) {
      const o = Object.assign({}, ph, { note: "summary missing occupancy/adr", market: name });
      if (debug) o.debug = JSON.stringify(s).slice(0, 2000);
      return { statusCode: 200, headers: CORS, body: JSON.stringify(o) };
    }
    const revenue = num(s.revenue);
    const out = {
      source: "live",
      market_key: mk,
      zip: M.zip,
      market: name,
      occupancy: occ,
      adr: adr,
      revpar: revpar,
      active_listings: num(s.active_listings_count) != null ? Math.round(num(s.active_listings_count)) : num(entry.active_listings_count),
      est_annual_revenue: revenue != null ? Math.round(revenue) : (revpar != null ? Math.round(revpar * 365) : Math.round(adr * 365 * occ)),
      booking_lead_time: num(s.booking_lead_time),
      length_of_stay: num(s.length_of_stay),
      min_nights: num(s.min_nights),
      window_months: 12,
      as_of: new Date().toISOString().slice(0, 7)
    };
    return { statusCode: 200, headers: CORS, body: JSON.stringify(out) };
  } catch (e) {
    return { statusCode: 200, headers: CORS, body: JSON.stringify(Object.assign({}, ph, { note: String(e.message || e) })) };
  }
};

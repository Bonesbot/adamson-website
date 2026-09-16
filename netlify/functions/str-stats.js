// netlify/functions/str-stats.js
//
// Server-side proxy for AirROI short-term-rental market stats (ZIP 34242 / Siesta Key).
// Keeps the AirROI API key OFF the client. Returns normalized JSON the STR dashboard renders.
//
// Activation: set env var AIRROI_API_KEY in the Netlify dashboard (Site settings > Env vars,
// scope Functions, context Production). Until then this returns clearly-labeled placeholder
// sample data so the page still works.
//
// AirROI API (docs: https://www.airroi.com/api/documentation), header X-API-KEY:
//   GET  https://api.airroi.com/markets/search?query=...
//        -> { entries: [{ full_name, country, region, locality, district, native_currency, active_listings_count }] }
//   POST https://api.airroi.com/markets/summary
//        body { market: { country, region, locality, district? }, currency: "usd", num_months: 12 }
//        -> { market, occupancy (0-1), average_daily_rate, rev_par, revenue, booking_lead_time,
//             length_of_stay, min_nights, active_listings_count }
//
// 2026-09-16: rewritten to the real AirROI response shape. The first version expected
// { markets: [{ avg_occupancy, avg_daily_rate, ... }] } from /markets/search, which the API never
// returns, so it silently fell back to placeholder even with a valid key.
//
// No npm deps — global fetch (Netlify Node 18+).

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
const QUERIES = ["Siesta Key, Florida", "Siesta Key", "Sarasota, Florida"];

function num(v) { return v == null || v === "" || isNaN(Number(v)) ? null : Number(v); }

async function searchMarket(key, query) {
  const r = await fetch(API + "/markets/search?query=" + encodeURIComponent(query), {
    headers: { "X-API-KEY": key }
  });
  if (!r.ok) throw new Error("airroi search " + r.status);
  const j = await r.json();
  const entries = Array.isArray(j.entries) ? j.entries : (Array.isArray(j.markets) ? j.markets : []);
  if (!entries.length) return null;
  // Prefer a Siesta Key match, then anything in Florida, then the first hit.
  const isFL = (e) => /florida|^fl$/i.test(String(e.region || "")) || /florida/i.test(String(e.full_name || ""));
  return entries.find((e) => /siesta/i.test(String(e.full_name || "") + " " + String(e.locality || "") + " " + String(e.district || "")) && isFL(e))
      || entries.find(isFL)
      || entries[0];
}

async function marketSummary(key, entry) {
  const market = { country: entry.country, region: entry.region, locality: entry.locality };
  if (entry.district) market.district = entry.district;
  const r = await fetch(API + "/markets/summary", {
    method: "POST",
    headers: { "X-API-KEY": key, "Content-Type": "application/json" },
    body: JSON.stringify({ market, currency: "usd", num_months: 12 })
  });
  if (!r.ok) throw new Error("airroi summary " + r.status);
  return r.json();
}

exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers: CORS, body: "" };

  const key = process.env.AIRROI_API_KEY;
  if (!key) {
    return { statusCode: 200, headers: CORS, body: JSON.stringify(Object.assign({}, PLACEHOLDER, { note: "AIRROI_API_KEY not set" })) };
  }

  try {
    let entry = null;
    for (const q of QUERIES) {
      entry = await searchMarket(key, q);
      if (entry) break;
    }
    if (!entry) {
      return { statusCode: 200, headers: CORS, body: JSON.stringify(Object.assign({}, PLACEHOLDER, { note: "no market match for " + QUERIES.join(" | ") })) };
    }

    const s = await marketSummary(key, entry);
    const occ = num(s.occupancy);
    const adr = num(s.average_daily_rate);
    const revpar = num(s.rev_par) != null ? num(s.rev_par) : (occ != null && adr != null ? adr * occ : null);
    if (occ == null || adr == null) {
      return { statusCode: 200, headers: CORS, body: JSON.stringify(Object.assign({}, PLACEHOLDER, { note: "summary missing occupancy/adr", market: entry.full_name })) };
    }
    const revenue = num(s.revenue);
    const out = {
      source: "live",
      zip: "34242",
      market: entry.full_name || [entry.locality, entry.region].filter(Boolean).join(", "),
      occupancy: occ > 1 ? occ / 100 : occ,
      adr: adr,
      revpar: revpar,
      active_listings: num(s.active_listings_count) != null ? num(s.active_listings_count) : num(entry.active_listings_count),
      est_annual_revenue: revenue != null ? Math.round(revenue) : (revpar != null ? Math.round(revpar * 365) : Math.round(adr * 365 * occ)),
      booking_lead_time: num(s.booking_lead_time),
      length_of_stay: num(s.length_of_stay),
      window_months: 12,
      as_of: new Date().toISOString().slice(0, 7)
    };
    return { statusCode: 200, headers: CORS, body: JSON.stringify(out) };
  } catch (e) {
    // On any upstream/credit/network error, degrade gracefully to placeholder and say why.
    return { statusCode: 200, headers: CORS, body: JSON.stringify(Object.assign({}, PLACEHOLDER, { note: String(e.message || e) })) };
  }
};

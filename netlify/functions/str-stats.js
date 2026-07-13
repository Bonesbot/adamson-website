// netlify/functions/str-stats.js
//
// Server-side proxy for AirROI short-term-rental market stats (ZIP 34242 / Siesta Key).
// Keeps the AirROI API key OFF the client. Returns normalized JSON the STR dashboard renders.
//
// Activation: set env var AIRROI_API_KEY in the Netlify dashboard (Site settings > Env vars)
//   after creating an AirROI account and depositing credits (min $10). Until then this
//   returns clearly-labeled placeholder sample data so the page still works.
//
// AirROI: GET https://api.airroi.com/markets/search?query=...  (header: x-api-key)
//   -> { markets: [{ name, active_listings, avg_occupancy, avg_daily_rate, avg_revpar }], total_results }
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

async function fetchMarket(key, query) {
  const url = "https://api.airroi.com/markets/search?query=" + encodeURIComponent(query);
  const r = await fetch(url, { headers: { "x-api-key": key } });
  if (!r.ok) throw new Error("airroi " + r.status);
  const j = await r.json();
  return (j.markets && j.markets[0]) ? j.markets[0] : null;
}

exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers: CORS, body: "" };

  const key = process.env.AIRROI_API_KEY;
  if (!key) {
    return { statusCode: 200, headers: CORS, body: JSON.stringify(PLACEHOLDER) };
  }

  try {
    // Prefer the tightest match; fall back to the Sarasota metro if Siesta Key isn't a distinct market.
    let m = await fetchMarket(key, "Siesta Key, Florida");
    if (!m) m = await fetchMarket(key, "34242");
    if (!m) m = await fetchMarket(key, "Sarasota, Florida");
    if (!m) return { statusCode: 200, headers: CORS, body: JSON.stringify(PLACEHOLDER) };

    const occ = m.avg_occupancy != null ? Number(m.avg_occupancy) : null;
    const adr = m.avg_daily_rate != null ? Number(m.avg_daily_rate) : null;
    const revpar = m.avg_revpar != null ? Number(m.avg_revpar)
                  : (occ != null && adr != null ? adr * occ : null);
    if (occ == null || adr == null) {
      return { statusCode: 200, headers: CORS, body: JSON.stringify(PLACEHOLDER) };
    }
    const out = {
      source: "live",
      zip: "34242",
      market: m.name || "Siesta Key / Sarasota",
      occupancy: occ,
      adr: adr,
      revpar: revpar,
      active_listings: m.active_listings != null ? Number(m.active_listings) : null,
      est_annual_revenue: revpar != null ? Math.round(revpar * 365) : Math.round(adr * 365 * occ),
      as_of: new Date().toISOString().slice(0, 7)
    };
    return { statusCode: 200, headers: CORS, body: JSON.stringify(out) };
  } catch (e) {
    // On any upstream/credit/network error, degrade gracefully to placeholder.
    return { statusCode: 200, headers: CORS, body: JSON.stringify(Object.assign({}, PLACEHOLDER, { note: String(e.message || e) })) };
  }
};

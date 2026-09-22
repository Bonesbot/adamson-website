/**
 * zhvf-refresh: pull Zillow's ZIP-level Home Value Forecast into Supabase.
 *
 * Runs on a schedule (netlify.toml: 1st and 15th, 12:00 UTC). Downloads the public
 * ZHVF growth CSV (smoothed, seasonally adjusted, mid-tier, all home types), keeps
 * the Florida rows, and upserts one row per (zip, base_date, horizon). The CMA client
 * page reads them through cma-adjustments.js ?action=forecast&zip=.
 *
 * The file is ~2 MB / ~21,000 ZIPs nationally; Florida is ~880 ZIPs = ~2,640 rows.
 * Zillow refreshes monthly, so twice a month guarantees we catch each release.
 *
 * Source: https://www.zillow.com/research/data/  (ZHVF, ZIP Code geography)
 * Columns: RegionID,SizeRank,RegionName,RegionType,StateName,State,City,Metro,CountyName,
 *          BaseDate,<+1 month>,<+3 months>,<+12 months>   (the last three headers are dates)
 *
 * Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY. Optional ZHVF_STATES ("FL" default, comma list).
 * DDL: see the header of cma-adjustments.js (forecast_zip).
 */

const ZHVF_URL = process.env.ZHVF_URL ||
  'https://files.zillowstatic.com/research/public_csvs/zhvf_growth/Zip_zhvf_growth_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv';
const STATES = (process.env.ZHVF_STATES || 'FL').split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
const SOURCE = 'zillow_zhvf';

function parseCSV(text) {
  const rows = []; let row = [], f = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
    else if (c === '"') q = true;
    else if (c === ',') { row.push(f); f = ''; }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(f); rows.push(row); row = []; f = ''; }
    else f += c;
  }
  if (f !== '' || row.length) { row.push(f); rows.push(row); }
  return rows.filter(r => r.length > 1);
}

function monthsBetween(a, b) {          // whole months from ISO date a to ISO date b
  const [ay, am] = a.split('-').map(Number), [by, bm] = b.split('-').map(Number);
  return (by - ay) * 12 + (bm - am);
}

async function upsert(base, headers, rows) {
  for (let i = 0; i < rows.length; i += 500) {
    const chunk = rows.slice(i, i + 500);
    const r = await fetch(`${base}/rest/v1/forecast_zip?on_conflict=source,zip,base_date,horizon_months`, {
      method: 'POST',
      headers: { ...headers, Prefer: 'resolution=merge-duplicates,return=minimal' },
      body: JSON.stringify(chunk),
    });
    if (!r.ok) throw new Error(`upsert chunk ${i / 500} failed: ${r.status} ${await r.text()}`);
  }
}

exports.handler = async () => {
  const base = process.env.SUPABASE_URL, key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!base || !key) { console.error('zhvf-refresh: SUPABASE env missing'); return { statusCode: 500, body: 'env' }; }
  const headers = { apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' };

  const t0 = Date.now();
  const res = await fetch(ZHVF_URL, { headers: { 'User-Agent': 'AdamsonFL zhvf-refresh (ryan@adamson-group.com)' } });
  if (!res.ok) { console.error('zhvf-refresh: download failed', res.status); return { statusCode: 502, body: 'download' }; }
  const text = await res.text();
  const rows = parseCSV(text);
  const H = rows[0].map(h => h.trim());
  const ix = n => H.indexOf(n);
  const baseIx = ix('BaseDate');
  const horizonCols = H.map((h, i) => ({ h, i })).filter(x => x.i > baseIx && /^\d{4}-\d{2}-\d{2}$/.test(x.h));
  if (baseIx < 0 || !horizonCols.length) { console.error('zhvf-refresh: unexpected header', H); return { statusCode: 500, body: 'header' }; }

  const out = []; const fetched_at = new Date().toISOString();
  let baseDate = null;
  for (const r of rows.slice(1)) {
    if (!STATES.includes(String(r[ix('State')] || '').toUpperCase())) continue;
    const zip = String(r[ix('RegionName')] || '').padStart(5, '0');
    const bd = r[baseIx]; if (!bd) continue; baseDate = bd;
    for (const { h, i } of horizonCols) {
      const v = Number(r[i]); if (!Number.isFinite(v)) continue;
      out.push({ source: SOURCE, zip, base_date: bd, horizon_months: monthsBetween(bd, h), pct_change: v,
        city: r[ix('City')] || null, county: r[ix('CountyName')] || null, metro: r[ix('Metro')] || null, state: r[ix('State')] || null, fetched_at });
    }
  }
  if (!out.length) { console.error('zhvf-refresh: no rows for', STATES); return { statusCode: 500, body: 'empty' }; }
  await upsert(base, headers, out);
  const msg = `zhvf-refresh: ${out.length} rows for ${STATES.join(',')} (base ${baseDate}, ${horizonCols.map(c => monthsBetween(baseDate, c.h)).join('/')} mo) in ${((Date.now() - t0) / 1000).toFixed(1)}s`;
  console.log(msg);
  return { statusCode: 200, body: msg };
};

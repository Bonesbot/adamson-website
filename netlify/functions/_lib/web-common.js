// netlify/functions/_lib/web-common.js
//
// Shared helpers for first-party analytics and form spam checks. Not a function
// itself: Netlify only deploys files directly in functions/ (or folder/index.js),
// so anything under _lib/ is bundled into the functions that import it.

import { createHash } from 'node:crypto';

// Production hosts. Anything else (deploy previews, localhost) is recorded as
// internal so it never pollutes the reports; unknown hosts are dropped.
export const PROD_HOSTS = new Set([
  'adamsonfl.com', 'www.adamsonfl.com',
  'siestareport.com', 'www.siestareport.com',
  'longboatlido.com', 'www.longboatlido.com',
]);

export function hostClass(host) {
  const h = String(host || '').toLowerCase();
  if (PROD_HOSTS.has(h)) return 'prod';
  if (h === 'adamsonfl.idxbroker.com') return 'prod';          // IDX search + listing detail pages
  if (h.endsWith('.netlify.app') || h === 'localhost' || h.startsWith('127.')) return 'internal';
  return 'unknown';
}

export const BOT_UA = /bot|crawl|spider|slurp|headless|phantom|puppeteer|playwright|selenium|lighthouse|pagespeed|gtmetrix|pingdom|uptime|monitor|preview|facebookexternalhit|embedly|quora link|whatsapp|telegram|skypeuripreview|bitlybot|curl|wget|python|httpclient|okhttp|java\/|go-http|axios|node-fetch|scrapy/i;

export function ipHash(ip) {
  if (!ip) return null;
  const salt = process.env.WEB_TRACK_SALT || (process.env.SUPABASE_SERVICE_ROLE_KEY || '').slice(-24) || 'ag';
  return createHash('sha256').update(salt + '|' + ip).digest('hex').slice(0, 20);
}

export function clientIp(req, context) {
  return (context && context.ip)
    || (req && req.headers && (req.headers.get ? req.headers.get('x-nf-client-connection-ip') : req.headers['x-nf-client-connection-ip']))
    || null;
}

// Geo for v1 (event.headers['x-nf-geo'], base64 JSON) and v2 (context.geo) functions.
export function geoFrom(context, headers) {
  let g = context && context.geo;
  if (!g && headers) {
    const raw = headers['x-nf-geo'] || headers['X-Nf-Geo'];
    if (raw) { try { g = JSON.parse(Buffer.from(raw, 'base64').toString('utf8')); } catch (_) { g = null; } }
  }
  if (!g) return {};
  const round = (n, dp) => (typeof n === 'number' && isFinite(n) ? Math.round(n * 10 ** dp) / 10 ** dp : null);
  return {
    country: (g.country && g.country.code) || null,
    region: (g.subdivision && g.subdivision.code) || null,
    city: g.city || null,
    postal: g.postalCode || null,
    lat: round(g.latitude, 3),
    lon: round(g.longitude, 3),
    tz: g.timezone || null,
  };
}

export async function supaInsert(table, rows) {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return { skipped: 'supabase env vars not configured' };
  const res = await fetch(`${url}/rest/v1/${table}`, {
    method: 'POST',
    headers: { apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json', Prefer: 'return=minimal' },
    body: JSON.stringify(rows),
  });
  if (!res.ok) throw new Error(`${table} insert failed: ${res.status} ${(await res.text()).slice(0, 200)}`);
  return { ok: true };
}

export async function supaCount(pathAndQuery) {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return 0;
  const res = await fetch(`${url}/rest/v1/${pathAndQuery}`, {
    method: 'HEAD',
    headers: { apikey: key, Authorization: `Bearer ${key}`, Prefer: 'count=exact', Range: '0-0' },
  });
  const cr = res.headers.get('content-range') || '';
  const n = parseInt(cr.split('/')[1], 10);
  return Number.isFinite(n) ? n : 0;
}

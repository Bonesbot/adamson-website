// netlify/functions/web-track.js  (Netlify Functions v2, served at /api/pv)
//
// First-party analytics collector for adamsonfl.com, siestareport.com and
// longboatlido.com. The shared SiteAnalytics component (in every layout) sends
// one small JSON beacon per pageview, plus engage / form_submit / contact_click /
// outbound events. This writes them to Supabase public.web_events with
// Netlify's edge geo (city, state, country) and a salted IP hash. No cookies, no
// raw IPs, no third parties. Reporting: supabase/migrations/web_events.sql
// (vw_web_* views and web_report()).
//
// Always answers 204 fast; a failed insert is logged, never surfaced.

import { hostClass, BOT_UA, ipHash, clientIp, geoFrom, supaInsert } from './_lib/web-common.js';

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};
const EVENTS = new Set(['pageview', 'engage', 'form_submit', 'contact_click', 'outbound']);
const s = (v, n) => (v === undefined || v === null || v === '' ? null : String(v).slice(0, n));
const i = (v) => { const n = parseInt(v, 10); return Number.isFinite(n) ? n : null; };

function refHost(ref) {
  try { return new URL(ref).hostname.replace(/^www\./, '').toLowerCase(); } catch (_) { return null; }
}
function device(ua, w) {
  if (/ipad|tablet|kindle|silk/i.test(ua) || (/android/i.test(ua) && !/mobi/i.test(ua))) return 'tablet';
  if (/mobi|iphone|android/i.test(ua)) return 'mobile';
  if (w && w < 768) return 'mobile';
  return 'desktop';
}

export default async (req, context) => {
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS });
  if (req.method !== 'POST') return new Response(null, { status: 405, headers: CORS });

  let b;
  try { b = JSON.parse(await req.text()); } catch (_) { return new Response(null, { status: 400, headers: CORS }); }
  if (!b || typeof b !== 'object') return new Response(null, { status: 400, headers: CORS });

  const host = s(b.h, 80) ? String(b.h).toLowerCase() : null;
  const cls = hostClass(host);
  const event = EVENTS.has(b.e) ? b.e : null;
  if (!host || cls === 'unknown' || !event || !b.p) return new Response(null, { status: 204, headers: CORS });

  const ua = req.headers.get('user-agent') || '';
  const q = new URLSearchParams(String(b.q || ''));
  const site = host.replace(/^www\./, '');
  const rh = refHost(b.r);
  const external = rh && rh !== site ? rh : null;

  const row = {
    event,
    domain: host,
    path: s(b.p, 300),
    query: s(b.q, 500),
    title: s(b.t, 200),
    referrer: external ? s(b.r, 500) : null,
    referrer_host: external,
    utm_source: s(q.get('utm_source') || b.us, 100),
    utm_medium: s(q.get('utm_medium') || b.um, 100),
    utm_campaign: s(q.get('utm_campaign') || b.uc, 100),
    utm_content: s(q.get('utm_content'), 100),
    utm_term: s(q.get('utm_term'), 100),
    vid: s(b.v, 40), sid: s(b.s, 40), pid: s(b.pid, 40),
    new_visitor: typeof b.nv === 'boolean' ? b.nv : null,
    new_session: typeof b.ns === 'boolean' ? b.ns : null,
    device: device(ua, i(b.sw)),
    screen_w: i(b.sw),
    lang: s(b.lg, 20),
    ua: s(ua, 300),
    ...geoFrom(context),
    ip_hash: ipHash(clientIp(req, context)),
    engaged_sec: event === 'engage' ? Math.min(i(b.sec) || 0, 7200) : null,
    scroll_pct: event === 'engage' ? Math.min(Math.max(i(b.sc) || 0, 0), 100) : null,
    label: s(b.l, 200),
    is_bot: BOT_UA.test(ua) || b.wd === true,
    is_internal: cls === 'internal' || b.i === true,
  };

  try { await supaInsert('web_events', row); }
  catch (err) { console.error('web-track:', String(err.message || err)); }
  return new Response(null, { status: 204, headers: CORS });
};

export const config = { path: '/api/pv' };

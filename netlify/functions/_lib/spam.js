// netlify/functions/_lib/spam.js
//
// One spam check for every lead function (community-lead, srqmap-lead,
// off-market-lead, submission-created). Returns a verdict; each function decides
// what to skip. Signals, in order of certainty:
//
//   BOT (never stored as a lead, never emailed; logged to web_events 'form_spam'):
//     honeypot filled · Turnstile token rejected by Cloudflare · submitted < 1.5 s after page load
//   SCORED (>= SPAM_THRESHOLD flags the lead as spam):
//     no client stamp (_meta missing: a direct POST, not our page) · no Turnstile token
//     (only when TURNSTILE_SECRET_KEY is set) · fast submit (< 4 s) · burst from one IP ·
//     solicitation language (web design, SEO, "your website"...) · links in the message ·
//     greeting the domain ("Hi siestareport.com") · gibberish names/messages · Cyrillic/CJK text ·
//     gmail dot-trick addresses
//
// Flagged leads: stored in public.leads with status 'spam' and zoho_sync 'skipped:spam'
// (so cc-queue-poller never pushes them to Zoho), no Zoho, no Home Platform forward.
// SPAM_MODE env: 'tag' (default) still emails the team with a [SPAM?] subject so a
// misfire is visible while we tune; 'quarantine' sends nothing.

import { ipHash, clientIp, geoFrom, supaInsert, supaCount } from './web-common.js';

export const SPAM_THRESHOLD = 5;
export const spamMode = () => (process.env.SPAM_MODE === 'quarantine' ? 'quarantine' : 'tag');

const SOLICIT = [
  /web ?design|web ?develop|website (re)?design|redesign|revamp|well-designed website|modern website/i,
  /\bseo\b|search engine|google (ranking|rank|first page)|first page of google|rank(ing)? higher|backlinks?|guest post/i,
  /digital marketing|marketing agency|lead generation|generate (more )?leads|social media (management|marketing)|more traffic|increase (your )?(sales|traffic)/i,
  /\byour (website|site|web ?page|online presence)\b/i,
  /app development|virtual assistant|outsourc|white ?label|free (quote|audit|consultation|mockup)|affordable (price|rates)|per hour/i,
  /business (loan|funding)|merchant cash|crypto|bitcoin|forex|casino|viagra|cialis|escort|onlyfans/i,
  /pardon the intrusion|i came across your (website|site|business)|i (noticed|visited) your (website|site)|reply (stop|no)|unsubscribe|opt[- ]out/i,
];
const OWN_DOMAIN = /\b(hi|hello|hey|dear|greetings)\b[\s,]*(the\s+)?(team\s+at\s+)?(www\.)?(adamsonfl|siestareport|longboatlido|ccshores)\.com/i;

function vowelRatio(w) { const v = (w.match(/[aeiouy]/gi) || []).length; return v / w.length; }
function gibberishWord(w) {
  if (!/^[a-z]{6,}$/i.test(w)) return false;
  const caseFlips = (w.slice(1).match(/[A-Z]/g) || []).length;   // "HyIEmHpy" style
  return vowelRatio(w) < 0.2 || caseFlips >= 3;
}

/**
 * @param {object} p  { body, fields: {name, email, phone, message}, event, headers, req, context, source }
 */
export async function assessSpam(p) {
  const body = p.body || {};
  const f = p.fields || {};
  const meta = body._meta && typeof body._meta === 'object' ? body._meta : null;
  const reasons = [];
  let score = 0;
  const add = (pts, why) => { score += pts; reasons.push(why); };

  const hdr = p.headers || (p.event && p.event.headers) || {};
  const ip = clientIp(p.req, p.context) || hdr['x-nf-client-connection-ip'] || hdr['x-forwarded-for'] || null;
  const ipH = ipHash(ip);

  // ── certain bots ──
  if (body['bot-field']) return verdict('bot', ['honeypot']);
  if (meta && typeof meta.ts === 'number' && meta.ts < 1500) return verdict('bot', ['submitted_in_' + meta.ts + 'ms']);

  const secret = process.env.TURNSTILE_SECRET_KEY;
  if (secret) {
    const tok = meta && meta.tt;
    if (!tok) add(2, 'no_turnstile_token');
    else {
      try {
        const form = new URLSearchParams({ secret, response: String(tok) });
        if (ip) form.set('remoteip', String(ip).split(',')[0].trim());
        const r = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', { method: 'POST', body: form });
        const j = await r.json();
        if (!j.success) return verdict('bot', ['turnstile_failed:' + (j['error-codes'] || []).join('|')]);
      } catch (_) { /* Cloudflare unreachable: do not penalise the visitor */ }
    }
  }

  // ── scored signals ──
  if (!meta) add(3, 'no_client_stamp');
  else if (typeof meta.ts === 'number' && meta.ts < 4000) add(3, 'fast_submit');

  if (ipH) {
    try {
      const since = new Date(Date.now() - 15 * 60 * 1000).toISOString();
      const n = await supaCount(`leads?select=id&details->>ip_hash=eq.${ipH}&created_at=gte.${since}`);
      if (n >= 2) add(3, 'burst_same_ip');
    } catch (_) {}
  }

  const msg = String(f.message || '');
  const name = String(f.name || '');
  const email = String(f.email || '');
  const text = name + ' ' + msg;

  let sol = 0;
  for (const re of SOLICIT) if (re.test(msg)) sol += 2;
  if (sol) add(Math.min(sol, 6), 'solicitation');
  if (OWN_DOMAIN.test(msg)) add(3, 'greets_domain');
  const links = (msg.match(/https?:\/\/|www\.[a-z0-9-]+\.[a-z]{2,}/gi) || []).length;
  if (links) add(Math.min(links * 2, 4), 'links_in_message');
  if (/[Ѐ-ӿ一-鿿぀-ヿ]/.test(text)) add(3, 'foreign_script');
  const gib = name.split(/\s+/).filter(gibberishWord).length;
  if (gib) add(Math.min(gib * 2, 4), 'gibberish_name');
  if (/^\S{12,}$/.test(msg.trim()) && gibberishWord(msg.trim().replace(/[^a-z]/gi, '').slice(0, 30))) add(3, 'gibberish_message');
  const local = email.split('@')[0] || '';
  if (/@gmail\.com$/i.test(email) && (local.match(/\./g) || []).length >= 3) add(2, 'gmail_dot_trick');

  return verdict(score >= SPAM_THRESHOLD ? 'spam' : 'ok', reasons);

  function verdict(kind, why) {
    const out = {
      kind,                                   // 'ok' | 'spam' | 'bot'
      spam: kind !== 'ok',
      score: kind === 'bot' ? 99 : score,
      reasons: why,
      ipHash: ipH,
      mode: spamMode(),
      attribution: meta ? {
        vid: meta.v || null, sid: meta.s || null, pid: meta.pid || null,
        page_host: meta.h || null, page_path: meta.p || null, page_query: meta.q || null,
        first_touch: meta.ft || null, page_age_ms: typeof meta.ts === 'number' ? meta.ts : null,
      } : null,
      internal: !!(meta && meta.i),
    };
    return out;
  }
}

/** Log a blocked bot submission (no lead row) so the daily report can count them. */
export async function logBlocked(v, p) {
  try {
    const meta = (p.body && p.body._meta) || {};
    const hdr = p.headers || (p.event && p.event.headers) || {};
    await supaInsert('web_events', {
      event: 'form_spam',
      domain: String(meta.h || hdr.host || 'unknown').slice(0, 80),
      path: String(meta.p || p.source || '/').slice(0, 300),
      label: (p.source || 'form') + ' | ' + v.reasons.join(',').slice(0, 150),
      vid: meta.v || null, sid: meta.s || null,
      ip_hash: v.ipHash,
      ua: String(hdr['user-agent'] || '').slice(0, 300),
      ...geoFrom(p.context, hdr),
      is_bot: true,
    });
  } catch (err) { console.error('spam: logBlocked', String(err.message || err)); }
}

/** Fields to merge into a leads row's `details` jsonb. */
export function spamDetails(v) {
  const d = { ip_hash: v.ipHash };
  if (v.attribution) d.attribution = v.attribution;
  if (v.reasons.length) d.spam = { score: v.score, reasons: v.reasons, flagged: v.spam, mode: v.mode };
  return d;
}

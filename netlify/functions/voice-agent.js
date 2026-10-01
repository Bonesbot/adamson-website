// netlify/functions/voice-agent.js
//
// Brain for the AdamsonFL.com voice agent (MVP, 2026-10-01). The page at /voice/ turns
// speech into text in the browser, POSTs the running conversation here, speaks the reply.
//
//   POST { messages: [{role:'user'|'assistant', content:string}, ...], sid?: string }
//   ->   { reply: string, listings: [...], events: [...], handoff?: {...}, usage: {...} }
//
// Tools the model can call (it fills the parameters from natural speech, no intent parsing):
//   search_listings  -> public.raw_listings (active only, capped at 5, display fields + IDX link)
//   search_events    -> src/data/srqmap-events.json (this week's events, bundled at build)
//   local_knowledge  -> src/data/srqmap-pins.json (177 curated places with Ryan's tips)
//   request_showing  -> public.leads (source 'voice-agent:buyer') + team email, like every form
//
// Guardrails: ANTHROPIC_API_KEY absent -> 503 with a plain message (page shows it). Daily
// spend cap VOICE_DAILY_CAP_USD (default 5) from public.api_usage (service 'voice-agent').
// History trimmed to the last 12 turns, 4 tool rounds per request, 350 output tokens per turn.
// No npm deps: global fetch, Netlify Node 18+.

import events from '../../src/data/srqmap-events.json' with { type: 'json' };
import pins from '../../src/data/srqmap-pins.json' with { type: 'json' };
import { routeFor } from './lead-routing.js';

const MODEL = process.env.VOICE_MODEL || 'claude-sonnet-5-5';
const DAILY_CAP = parseFloat(process.env.VOICE_DAILY_CAP_USD || '5');
// Rough list prices per million tokens for the spend ledger; est_cost only, never billed.
const PRICE_IN = parseFloat(process.env.VOICE_PRICE_IN || '3');
const PRICE_OUT = parseFloat(process.env.VOICE_PRICE_OUT || '15');

const json = (statusCode, obj) => ({
  statusCode,
  headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
  body: JSON.stringify(obj),
});

const AREAS = {
  'longboat-key': 'Longboat Key', 'st-armands-lido': 'St. Armands and Lido', 'siesta-key': 'Siesta Key',
  'downtown-sarasota': 'Downtown Sarasota', 'west-of-trail-core': 'West of Trail',
  'west-of-trail-north': 'West of Trail North', 'west-of-trail-south': 'West of Trail South',
  'bird-key': 'Bird Key', 'palmer-ranch': 'Palmer Ranch', 'city-of-sarasota': 'City of Sarasota',
  'west-bradenton-el-con-img-aqua': 'El Conquistador / IMG Academy', 'west-bradenton-seaflower': 'SeaFlower',
  'west-bradenton-coral-shores-cortez': 'Coral Shores / Cortez', 'west-bradenton-tidy-island': 'Tidy Island',
};

const SYSTEM = `You are the voice of The Adamson Group, Ryan Adamson's luxury real estate team at Coldwell Banker Realty on St. Armands Circle in Sarasota, Florida. A visitor is talking to you out loud on AdamsonFL.com, so everything you say will be read aloud by a speech engine.

How to speak:
- Spoken English only. One to three short sentences per turn. No lists, no markdown, no symbols, no URLs, no MLS numbers. Say prices the way a person would: "two point four million", "eight ninety-five".
- Warm, professional, concise, credible. Luxury plus data-backed authority, never hypey. Ryan's voice: a local who knows the islands, not a brochure.
- When you show listings, describe at most three, each in one breath: neighborhood, beds and baths, the one feature that matters, the price. The screen shows cards with photos and links, so you never need to spell details out.
- Blend local knowledge naturally: the beach, the bridge, the Circle, what is on this weekend. If someone drifts to events or restaurants, go with them for a turn, then bring it back to homes.
- Markets you cover: Sarasota, Longboat Key, Siesta Key, St. Armands and Lido, Bird Key, Downtown, West of Trail, Palmer Ranch, and West Bradenton (Tidy Island, El Conquistador and IMG Academy, SeaFlower, Coral Shores and Cortez). Outside those, say so and offer to connect them with Ryan.
- Use the tools for any facts about listings, events or places. Never invent an address, a price or a listing. If a search comes back empty, say so and loosen one filter.
- Your goal is a showing with Ryan. After a good match or two, offer it once, naturally. When they say yes, ask for a first name and a phone number or email, then call request_showing. Confirm in one sentence and say Ryan will reach out personally.
- Data note: listings refresh from the MLS each morning; if asked, say prices and availability are as of this morning.
- Never discuss commissions, give legal or tax advice, steer by protected class, or characterize neighborhoods by who lives there. Fair housing applies to everything you say.
- You cannot see the visitor; if asked whether you are a person, say you are Ryan's digital assistant.`;

const TOOLS = [
  {
    name: 'search_listings',
    description: 'Search active for-sale listings in the Sarasota and Bradenton markets. Returns up to 5 matches. Call this whenever the visitor describes what they want in a home.',
    input_schema: {
      type: 'object',
      properties: {
        area: { type: 'string', enum: Object.keys(AREAS), description: 'Neighborhood slug. Omit to search everywhere.' },
        beds_min: { type: 'integer' }, baths_min: { type: 'integer' },
        price_min: { type: 'integer', description: 'US dollars' }, price_max: { type: 'integer', description: 'US dollars' },
        property_type: { type: 'string', enum: ['house', 'condo', 'townhouse', 'any'] },
        pool: { type: 'boolean', description: 'Private pool required' },
        waterfront: { type: 'boolean' }, golf: { type: 'boolean', description: 'Golf community' },
        gated: { type: 'boolean' }, dock: { type: 'boolean' }, new_construction: { type: 'boolean' },
        sqft_min: { type: 'integer' },
        keyword: { type: 'string', description: 'A word to look for in the public remarks, e.g. "elevator", "guest house", "turnkey"' },
        sort: { type: 'string', enum: ['price_asc', 'price_desc', 'newest'] },
      },
    },
  },
  {
    name: 'search_events',
    description: 'Things happening around Sarasota this week: festivals, markets, concerts, art walks. Call for "what is going on", "this weekend", "anything fun".',
    input_schema: { type: 'object', properties: { keyword: { type: 'string' }, date: { type: 'string', description: 'YYYY-MM-DD, optional' } } },
  },
  {
    name: 'local_knowledge',
    description: 'Ryan\'s curated local places with insider tips: beaches, parks, restaurants, marinas, clubs, neighborhoods. Call for questions about what an area is like or where to eat, play, boat.',
    input_schema: { type: 'object', properties: { query: { type: 'string', description: 'Place name, neighborhood or theme' } }, required: ['query'] },
  },
  {
    name: 'request_showing',
    description: 'Hand the visitor to Ryan for a showing or a conversation. Only call after the visitor has agreed and given a name and at least one of phone or email.',
    input_schema: {
      type: 'object',
      properties: {
        name: { type: 'string' }, phone: { type: 'string' }, email: { type: 'string' },
        listing_ids: { type: 'array', items: { type: 'string' }, description: 'MLS ids they liked' },
        summary: { type: 'string', description: 'One sentence: what they are looking for, in their words' },
      },
      required: ['name'],
    },
  },
];

// ── Supabase helpers ─────────────────────────────────────────────────────────

function sb() {
  const url = process.env.SUPABASE_URL, key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  const h = { apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' };
  return {
    get: async (q) => { const r = await fetch(`${url}/rest/v1/${q}`, { headers: h }); if (!r.ok) throw new Error(`supabase ${r.status} ${await r.text()}`); return r.json(); },
    insert: async (t, row) => { const r = await fetch(`${url}/rest/v1/${t}`, { method: 'POST', headers: { ...h, Prefer: 'return=minimal' }, body: JSON.stringify(row) }); if (!r.ok) throw new Error(`supabase insert ${r.status} ${await r.text()}`); },
  };
}

const money = (n) => { const v = Number(n); return Number.isFinite(v) ? v : null; };
const words = (n) => {
  const v = money(n); if (v == null) return '';
  if (v >= 1e6) return (v / 1e6).toFixed(v % 1e6 === 0 ? 0 : 2).replace(/\.?0+$/, '') + ' million';
  return Math.round(v / 1000) + ' thousand';
};

async function searchListings(a) {
  const s = sb(); if (!s) return { error: 'listings unavailable' };
  const q = ['standard_status=eq.Active', 'select=listing_id,unparsed_address,city,postal_code,detected_area,subdivision_name,property_sub_type,current_price,bedrooms_total,bathrooms_full,bathrooms_half,living_area,year_built,pool_private_yn,is_waterfront,has_golf,is_gated,has_dock,property_condition,water_view,listing_view,days_on_market,public_remarks'];
  if (a.area && AREAS[a.area]) q.push(`detected_area=eq.${a.area}`);
  if (a.beds_min) q.push(`bedrooms_total=gte.${a.beds_min}`);
  if (a.baths_min) q.push(`bathrooms_full=gte.${a.baths_min}`);
  if (a.price_min) q.push(`current_price=gte.${a.price_min}`);
  if (a.price_max) q.push(`current_price=lte.${a.price_max}`);
  if (a.sqft_min) q.push(`living_area=gte.${a.sqft_min}`);
  if (a.pool) q.push('pool_private_yn=eq.true');
  if (a.waterfront) q.push('is_waterfront=eq.true');
  if (a.golf) q.push('has_golf=eq.true');
  if (a.gated) q.push('is_gated=eq.true');
  if (a.dock) q.push('has_dock=eq.true');
  if (a.new_construction) q.push('property_condition=in.(Under%20Construction,Pre-Construction)');
  if (a.property_type === 'house') q.push('property_sub_type=eq.Single%20Family%20Residence');
  else if (a.property_type === 'condo') q.push('property_sub_type=in.(Condominium,Condo%20-%20Hotel)');
  else if (a.property_type === 'townhouse') q.push('property_sub_type=eq.Townhouse');
  if (a.keyword) q.push(`public_remarks=ilike.*${encodeURIComponent(String(a.keyword).replace(/[*,()]/g, ' ').trim())}*`);
  q.push(a.sort === 'price_asc' ? 'order=current_price.asc' : a.sort === 'newest' ? 'order=listing_contract_date.desc' : 'order=current_price.desc');
  q.push('limit=5');
  const rows = await s.get(`raw_listings?${q.join('&')}`);
  const out = rows.map((r) => ({
    id: r.listing_id,
    address: titleCase(r.unparsed_address) + ', ' + titleCase(r.city) + ' ' + (r.postal_code || ''),
    area: AREAS[r.detected_area] || titleCase(r.city),
    subdivision: titleCase(r.subdivision_name),
    type: r.property_sub_type,
    price: money(r.current_price), price_words: words(r.current_price),
    beds: Number(r.bedrooms_total) || null,
    baths: (Number(r.bathrooms_full) || 0) + ((Number(r.bathrooms_half) || 0) ? 0.5 : 0),
    sqft: Number(r.living_area) || null,
    year_built: r.year_built || null,
    pool: r.pool_private_yn === true || r.pool_private_yn === 'True',
    waterfront: !!r.is_waterfront, golf: !!r.has_golf, gated: !!r.is_gated, dock: !!r.has_dock,
    view: r.water_view || r.listing_view || null,
    condition: r.property_condition || null,
    days_on_market: Number(r.days_on_market) || null,
    remarks: String(r.public_remarks || '').slice(0, 280),
    url: `https://adamsonfl.com/idx/details/listing/d003/${r.listing_id}`,
  }));
  return { count: out.length, listings: out };
}

function titleCase(s) {
  return String(s || '').toLowerCase().replace(/\b([a-z])/g, (m) => m.toUpperCase()).replace(/\b(Of|And|The|De|La)\b/g, (m) => m.toLowerCase()).replace(/^./, (m) => m.toUpperCase());
}

function searchEvents(a) {
  const today = new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
  let list = (events || []).filter((e) => !e.end_date || e.end_date >= today);
  if (a.date) list = list.filter((e) => e.start_date <= a.date && (e.end_date || e.start_date) >= a.date);
  if (a.keyword) { const k = a.keyword.toLowerCase(); list = list.filter((e) => JSON.stringify(e).toLowerCase().includes(k)); }
  return { today, events: list.slice(0, 6).map((e) => ({ name: e.name, venue: e.venue, when: [e.dates_label, e.hours_label].filter(Boolean).join(', '), blurb: e.blurb, website: e.website })) };
}

function localKnowledge(a) {
  const k = String(a.query || '').toLowerCase().split(/\s+/).filter((w) => w.length > 2);
  const scored = (pins || []).map((p) => {
    const hay = `${p.name} ${p.group} ${p.address || ''} ${p.blurb || ''} ${p.tip || ''}`.toLowerCase();
    return { p, score: k.reduce((n, w) => n + (hay.includes(w) ? 1 : 0), 0) };
  }).filter((x) => x.score > 0).sort((x, y) => y.score - x.score).slice(0, 5);
  return { places: scored.map(({ p }) => ({ name: p.name, kind: p.group || null, address: p.address || null, about: p.blurb || null, ryans_tip: p.tip || null })) };
}

async function requestShowing(a, sid, hdr) {
  const s = sb();
  const name = String(a.name || '').trim();
  const parts = name.split(/\s+/).filter(Boolean);
  const route = routeFor('/voice/');
  const row = {
    first_name: parts.length > 1 ? parts.slice(0, -1).join(' ') : null,
    last_name: parts.length ? parts[parts.length - 1] : 'Unknown',
    // leads.email is NOT NULL; a phone-only visitor gets a tagged placeholder so the row
    // still lands in the queue (the email body and details say phone only).
    email: (a.email || '').trim() || `phone-only+${String(a.phone || '').replace(/\D/g, '') || 'unknown'}@voice.adamsonfl.com`,
    phone: (a.phone || '').trim() || null,
    source: 'voice-agent:buyer', lead_type: 'Buyer', page: '/voice/',
    message: a.summary || null,
    details: { listing_ids: a.listing_ids || [], phone_only: !(a.email || '').trim(), sid: sid || null, routing: route ? route.label : null, ua: String(hdr['user-agent'] || '').slice(0, 200) },
    raw_payload: a,
  };
  let stored = false;
  try { if (s) { await s.insert('leads', row); stored = true; } } catch (err) { console.error('voice-agent: lead insert', String(err.message || err)); }
  try {
    const key = process.env.RESEND_API_KEY;
    if (key) {
      const to = (route && route.notify && route.notify.length) ? route.notify : ['Ryan@Adamson-Group.com'];
      await fetch('https://api.resend.com/emails', {
        method: 'POST', headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from: process.env.RESEND_FROM || 'The Adamson Group <Info@AdamsonFL.com>', to, reply_to: (a.email || '').trim() || undefined,
          subject: `[VOICE LEAD] ${name} - showing request`,
          text: [
            'A visitor asked the voice agent on adamsonfl.com/voice/ for a showing.', '',
            `Name:  ${name}`, `Phone: ${row.phone || '-'}`, `Email: ${(a.email || '').trim() || '- (phone only)'}`, '',
            `Looking for: ${a.summary || '-'}`,
            `Listings they liked: ${(a.listing_ids || []).map((id) => `https://adamsonfl.com/idx/details/listing/d003/${id}`).join('\n                     ') || '-'}`, '',
            `Received: ${new Date().toLocaleString('en-US', { timeZone: 'America/New_York' })} ET`,
            stored ? 'Stored in the lead queue (source voice-agent:buyer).' : 'NOTE: Supabase insert failed, this email is the only record.', '',
            '- Adamson Group site automation',
          ].join('\n'),
        }),
      });
    }
  } catch (err) { console.error('voice-agent: notify', String(err.message || err)); }
  return { ok: true, stored, message: 'Ryan has the request and will reach out personally.' };
}

// ── spend ledger ─────────────────────────────────────────────────────────────

async function spentToday() {
  const s = sb(); if (!s) return 0;
  try {
    const since = new Date(); since.setUTCHours(0, 0, 0, 0);
    const rows = await s.get(`api_usage?select=est_cost&service=eq.voice-agent&ts=gte.${since.toISOString()}`);
    return rows.reduce((n, r) => n + (Number(r.est_cost) || 0), 0);
  } catch (_) { return 0; }
}
async function logUsage(usage, note) {
  const s = sb(); if (!s || !usage) return;
  const cost = ((usage.input_tokens || 0) * PRICE_IN + (usage.output_tokens || 0) * PRICE_OUT) / 1e6;
  try { await s.insert('api_usage', { service: 'voice-agent', endpoint: MODEL, est_cost: Number(cost.toFixed(5)), note: String(note || '').slice(0, 120) }); } catch (_) {}
  return cost;
}

// ── Anthropic ────────────────────────────────────────────────────────────────

async function callModel(messages) {
  const r = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: { 'x-api-key': process.env.ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
    body: JSON.stringify({ model: MODEL, max_tokens: 350, system: SYSTEM, tools: TOOLS, messages }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`anthropic ${r.status} ${JSON.stringify(data).slice(0, 300)}`);
  return data;
}

// ── Handler ──────────────────────────────────────────────────────────────────

export const handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 200, headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' }, body: '' };
  if (event.httpMethod !== 'POST') return json(405, { error: 'Method Not Allowed' });
  if (!process.env.ANTHROPIC_API_KEY) return json(503, { error: 'The voice agent is not switched on yet (ANTHROPIC_API_KEY is not set).' });

  let body;
  try { body = JSON.parse(event.body || '{}'); } catch (_) { return json(400, { error: 'Bad request' }); }
  const incoming = Array.isArray(body.messages) ? body.messages : [];
  const history = incoming
    .filter((m) => m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string' && m.content.trim())
    .slice(-12)
    .map((m) => ({ role: m.role, content: m.content.slice(0, 1500) }));
  if (!history.length || history[history.length - 1].role !== 'user') return json(400, { error: 'Say something first.' });

  const spent = await spentToday();
  if (spent >= DAILY_CAP) return json(429, { error: 'The voice agent has reached its daily limit. Please call Ryan at (941) 713-9234.' });

  const messages = [...history];
  const listings = [], evs = [], places = [];
  let handoff = null, cost = 0, reply = '';
  try {
    for (let round = 0; round < 4; round++) {
      const res = await callModel(messages);
      cost += (await logUsage(res.usage, `sid ${body.sid || '-'} round ${round}`)) || 0;
      const text = (res.content || []).filter((c) => c.type === 'text').map((c) => c.text).join(' ').trim();
      const calls = (res.content || []).filter((c) => c.type === 'tool_use');
      if (text) reply = text;
      if (!calls.length || res.stop_reason !== 'tool_use') break;
      messages.push({ role: 'assistant', content: res.content });
      const results = [];
      for (const c of calls) {
        let out;
        try {
          if (c.name === 'search_listings') { out = await searchListings(c.input || {}); listings.push(...(out.listings || [])); }
          else if (c.name === 'search_events') { out = searchEvents(c.input || {}); evs.push(...out.events); }
          else if (c.name === 'local_knowledge') { out = localKnowledge(c.input || {}); places.push(...out.places); }
          else if (c.name === 'request_showing') { out = await requestShowing(c.input || {}, body.sid, event.headers || {}); handoff = { name: c.input.name, stored: out.stored }; }
          else out = { error: 'unknown tool' };
        } catch (err) { out = { error: String(err.message || err).slice(0, 200) }; console.error('voice-agent tool', c.name, out.error); }
        results.push({ type: 'tool_result', tool_use_id: c.id, content: JSON.stringify(out) });
      }
      messages.push({ role: 'user', content: results });
    }
  } catch (err) {
    console.error('voice-agent:', String(err.message || err));
    return json(502, { error: 'I lost my train of thought for a second. Could you say that again?' });
  }
  if (!reply) reply = listings.length ? 'Here is what I found. Want me to narrow it down?' : 'Tell me a little more about what you are looking for.';

  // de-dupe listing cards by id, keep order
  const seen = new Set();
  const cards = listings.filter((l) => !seen.has(l.id) && seen.add(l.id)).slice(0, 5);
  return json(200, { reply, listings: cards, events: evs.slice(0, 6), places: places.slice(0, 5), handoff, usage: { est_cost_usd: Number(cost.toFixed(4)), spent_today_usd: Number((spent + cost).toFixed(3)) } });
};

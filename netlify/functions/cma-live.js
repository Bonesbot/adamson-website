// netlify/functions/cma-live.js
//
// Pulls a Home Platform (Compass "CIH") CMA share page and returns the parts a
// landing page renders natively: subject, comps with their full photo stacks,
// Ryan's typed adjustments, and the adjusted price range.
//
// The share page embeds the whole CMA as JSON in <script id="data-literal-cma">.
// We always fetch the /v/latest alias, so whatever Ryan last PUBLISHED in Home
// Platform flows through (edits sitting in "draft" do not). Each successful pull
// is written to cma_snapshots; if Home Platform is unreachable the last snapshot
// is served instead, so the landing page never blanks.
//
//   GET /.netlify/functions/cma-live?cma=cma-6a89...&agent=6a68f0...
//   -> { ok, source: "live"|"snapshot", version, publishedAt, subject, comps[], summary }
//
// Photos stay on Compass's CDN (thumb 165px, 640x480, origin); nothing is
// downloaded or mirrored, per Ryan (2026-11-04).

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Content-Type': 'application/json',
};
const ID_RE = /^cma-[0-9a-f-]{20,60}$/i;
const AGENT_RE = /^[0-9a-f]{16,32}$/i;

const out = (code, body, extra) => ({
  statusCode: code,
  headers: { ...CORS, ...(extra || {}) },
  body: JSON.stringify(body),
});

function sb() {
  const url = process.env.SUPABASE_URL, key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  return { url: url.replace(/\/$/, ''), headers: { apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' } };
}
async function rest(db, path, init) {
  const r = await fetch(`${db.url}/rest/v1/${path}`, { ...init, headers: { ...db.headers, ...((init && init.headers) || {}) } });
  const text = await r.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!r.ok) throw new Error(`supabase ${r.status}: ${typeof body === 'string' ? body : JSON.stringify(body)}`);
  return body;
}

// ── Home Platform ─────────────────────────────────────────────────────────────
function shareUrl(cma, agent) {
  return `https://www.homeplatform.com/listing-presentation/view/cma/${cma}/v/latest?agent_id=${agent}`;
}

async function fetchCma(cma, agent) {
  const r = await fetch(shareUrl(cma, agent), {
    headers: { 'User-Agent': 'Mozilla/5.0 (compatible; AdamsonFL landing page; +https://adamsonfl.com)', Accept: 'text/html' },
    signal: AbortSignal.timeout(15000),
  });
  if (!r.ok) throw new Error(`homeplatform ${r.status}`);
  const html = await r.text();
  const i = html.indexOf('id="data-literal-cma"');
  if (i < 0) throw new Error('no data-literal-cma block');
  const j = html.indexOf('{', i), k = html.indexOf('</script>', j);
  return JSON.parse(html.slice(j, k));
}

// ── Normalize ─────────────────────────────────────────────────────────────────
const ms2iso = (ms) => (typeof ms === 'number' && ms > 0 ? new Date(ms).toISOString().slice(0, 10) : null);
const num = (v) => (typeof v === 'number' && isFinite(v) ? v : null);

function yearBuilt(listing, overrides, key) {
  // Ryan's Listing Editor overrides win (he corrects Year Built by hand), then the feed.
  const o = overrides['buildingInfo.buildingYearOpened'];
  if (o && o[key] != null && String(o[key]).trim() !== '') return Number(o[key]) || null;
  const b = listing.buildingInfo || {};
  return num(b.buildingYearOpened) || num(b.yearBuilt) || null;
}

function media(listing) {
  return (listing.media || [])
    .filter((m) => m && (m.thumbnailUrl || m.originalUrl))
    .map((m) => {
      const base = (m.originalUrl || m.thumbnailUrl || '').replace(/\/[^/]+\.(jpg|jpeg|png|webp)$/i, '');
      return { thumb: m.thumbnailUrl || null, mid: base ? `${base}/640x480.jpg` : null, full: m.originalUrl || null, w: m.width || null, h: m.height || null };
    });
}

function listingCore(l, overrides, key) {
  const loc = l.location || {}, size = l.size || {}, price = l.price || {}, date = l.date || {};
  const statusOv = overrides['localizedStatus'];
  const status = (statusOv && statusOv[key]) || l.localizedStatus || null;
  const sqft = num(size.squareFeet);
  const closed = num(price.closed), listed = num(price.listed), preClose = num(price.preClose);
  return {
    id: key,
    address: loc.prettyAddress || loc.agentAddress || null,
    city: loc.city || null, state: loc.state || null, zip: loc.zipCode || null,
    lat: num(loc.latitude), lng: num(loc.longitude),
    status,
    beds: num(size.bedrooms), baths: num(size.totalBathrooms) ?? num(size.bathrooms),
    sqft, lotSqft: num(size.lotSizeInSquareFeet), lotLabel: size.formattedLotSize || null,
    yearBuilt: yearBuilt(l, overrides, key),
    originalListPrice: listed, lastAskingPrice: preClose, closePrice: closed,
    pricePerSqft: closed && sqft ? Math.round(closed / sqft) : num(price.perSquareFoot) ? Math.round(price.perSquareFoot) : null,
    listedDate: ms2iso(date.listed), contractDate: ms2iso(date.contract), closedDate: ms2iso(date.closed),
    dom: num(date.daysOnMarket), cdom: num(date.cumulativeDaysOnMarket),
    description: l.description || null,
    media: media(l),
  };
}

function findPricing(ai) {
  const hits = {};
  const walk = (o, path, depth) => {
    if (!o || typeof o !== 'object' || depth > 4) return;
    for (const [k, v] of Object.entries(o)) {
      if (/suggest|recommend|listPrice|priceRange|pricing/i.test(k) && !/compSearchQuery|netsheets|chartQuery/i.test(path)) hits[path ? `${path}.${k}` : k] = v;
      if (v && typeof v === 'object' && !/compSearchQuery|netsheets|chartQuery|subjectProperty|appliedAdjustments|selectListingAttributes/i.test(k)) walk(v, path ? `${path}.${k}` : k, depth + 1);
    }
  };
  walk(ai, '', 0);
  // Pull out a low/high pair if one is recognizable; keep the raw hits for inspection.
  let low = null, high = null;
  const nums = [];
  const dig = (v) => { if (typeof v === 'number' && v > 100000) nums.push(v); else if (v && typeof v === 'object') Object.values(v).forEach(dig); };
  Object.values(hits).forEach(dig);
  if (nums.length) { low = Math.min(...nums); high = Math.max(...nums); }
  return { low, high, raw: Object.keys(hits).length ? hits : null };
}

function normalize(d) {
  const ai = d.agentInputs || {}, meta = d.CMAMetaData || {};
  const overrides = {};
  for (const a of ai.selectListingAttributes || []) if (a && a.processedListingPath && a.overrideValue) overrides[a.processedListingPath] = a.overrideValue;

  const subject = listingCore(d.subjectProperty || {}, overrides, 'subject');
  const adj = ai.appliedAdjustments || {};
  const order = ai.compIds || [];
  const byId = new Map((d.compListings || []).map((c) => [String(c.listingIdSHA), c]));
  const comps = [];
  order.forEach((id, i) => {
    const l = byId.get(String(id));
    if (!l) return;
    const core = listingCore(l, overrides, String(id));
    const lines = (adj[id] || []).map((a) => ({ amount: num(a.value) ?? 0, note: a.explanation || '', auto: a.adjustmentType === 4, detail: a.longDescription || null }));
    const total = lines.reduce((s, a) => s + a.amount, 0);
    const basis = core.closePrice ?? core.lastAskingPrice ?? core.originalListPrice;
    comps.push({ ...core, n: i + 1, adjustments: lines, adjustmentTotal: total, adjustedPrice: basis != null ? Math.round(basis + total) : null });
  });

  const adjusted = comps.map((c) => c.adjustedPrice).filter((v) => v != null).sort((a, b) => a - b);
  // Home Platform reports the lower-middle value as "Median" on even counts; match it
  // so the number on this page never disagrees with the CMA PDF.
  const median = adjusted.length ? adjusted[Math.ceil(adjusted.length / 2) - 1] : null;
  const summary = {
    count: comps.length,
    low: adjusted[0] ?? null, high: adjusted[adjusted.length - 1] ?? null, median,
    average: adjusted.length ? Math.round(adjusted.reduce((s, v) => s + v, 0) / adjusted.length) : null,
  };

  const agent = d.primaryAgent || {};
  return {
    // Agent-entered pricing (suggested list price / range). Home Platform stores it
    // under agentInputs; the key is matched loosely so a rename upstream still lands.
    pricing: findPricing(ai),
    cmaId: (d.cma && d.cma.cmaId) || null,
    version: (d.cma && d.cma.version) || null,
    title: meta.title || subject.address,
    publishedAt: meta.publishTimeMs ? new Date(meta.publishTimeMs).toISOString() : null,
    updatedAt: meta.lastUpdateTimeMs ? new Date(meta.lastUpdateTimeMs).toISOString() : null,
    pdfUrl: meta.pdfFile && meta.pdfFile.url ? meta.pdfFile.url : null,
    agent: { name: agent.displayName || null, avatar: agent.avatarUrl || null },
    subject, comps, summary,
  };
}

// ── Handler ───────────────────────────────────────────────────────────────────
exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 204, headers: CORS, body: '' };
  if (event.httpMethod !== 'GET') return out(405, { error: 'GET only' });
  const q = event.queryStringParameters || {};
  const cma = (q.cma || '').trim(), agent = (q.agent || '').trim();
  if (!ID_RE.test(cma) || !AGENT_RE.test(agent)) return out(400, { error: 'cma and agent required' });

  const db = sb();
  const cache = { 'Cache-Control': 'public, max-age=600, stale-while-revalidate=3600' };

  try {
    const raw = await fetchCma(cma, agent);
    const payload = normalize(raw);
    if (db) {
      try {
        await rest(db, 'cma_snapshots?on_conflict=cma_id', {
          method: 'POST',
          headers: { Prefer: 'resolution=merge-duplicates,return=minimal' },
          body: JSON.stringify({ cma_id: cma, version: payload.version, title: payload.title, published_at: payload.publishedAt, fetched_at: new Date().toISOString(), payload }),
        });
      } catch (e) { console.warn('cma-live snapshot write failed:', e.message); }
    }
    return out(200, { ok: true, source: 'live', ...payload }, cache);
  } catch (err) {
    console.warn('cma-live live fetch failed:', err.message);
    if (db) {
      try {
        const rows = await rest(db, `cma_snapshots?select=payload,fetched_at&cma_id=eq.${encodeURIComponent(cma)}&limit=1`);
        if (rows && rows[0]) return out(200, { ok: true, source: 'snapshot', snapshotAt: rows[0].fetched_at, ...rows[0].payload }, { 'Cache-Control': 'public, max-age=120' });
      } catch (e) { console.warn('cma-live snapshot read failed:', e.message); }
    }
    return out(502, { ok: false, error: 'CMA unavailable: ' + err.message });
  }
};

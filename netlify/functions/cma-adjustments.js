// netlify/functions/cma-adjustments.js
//
// Backend for the CMA system. One function, action-routed. One Supabase row per
// CMA slug, so a new listing needs no code or config change.
//
//   GET  ?slug=<slug>                     read live overlay (public; same data
//                                         ships in the static adjustments.json)
//   POST ?action=verify                   check the edit key (login gate)
//   POST ?action=list                     registry of all CMA pages
//   POST ?slug=<slug>                     save overlay (rev-locked)
//   POST ?slug=<slug>&action=create      scaffold a new CMA: copies the two
//                                         templates + writes data.json and
//                                         adjustments.json via the GitHub API,
//                                         registers the page. One rebuild.
//   POST ?slug=<slug>&action=savedata    comp refresh: commit a new data.json
//   POST ?slug=<slug>&action=snapshot    freeze live overlay to git
//
// All POSTs require header x-cma-key == env CMA_EDIT_KEY.
//
// ── Supabase DDL (run once in the SQL editor) ────────────────────────────────
//
//   create table if not exists public.cma_adjustments (
//     slug        text        primary key,
//     adjustments jsonb       not null,
//     rev         integer     not null default 1,
//     updated_at  timestamptz not null default now()
//   );
//   create table if not exists public.cma_pages (
//     slug         text        primary key,
//     profile      text        not null,
//     address      text,
//     saved_search text,
//     status       text        not null default 'draft',
//     created_at   timestamptz not null default now(),
//     updated_at   timestamptz not null default now()
//   );
//   alter table public.cma_adjustments enable row level security;
//   alter table public.cma_pages       enable row level security;
//   -- no policies: only this function's service role key reaches these tables.
//
// ─────────────────────────────────────────────────────────────────────────────
// Env vars: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, CMA_EDIT_KEY
//   git-touching actions (create/savedata/snapshot): GITHUB_TOKEN (Contents:write),
//   GITHUB_REPO (default Bonesbot/adamson-website), GITHUB_BRANCH (default main)
// No npm deps: global fetch (Netlify Node 20).

const SLUG_RE   = /^[a-z0-9][a-z0-9-]{2,63}$/;
const MAX_BYTES = 1024 * 1024;
const TEMPLATE_DIR = 'public/mkt/_template';

const json = (statusCode, obj) => ({
  statusCode,
  headers: {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-store',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type, x-cma-key',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  },
  body: JSON.stringify(obj),
});

function keyMatches(given, expected) {
  if (typeof given !== 'string' || typeof expected !== 'string') return false;
  if (given.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < given.length; i++) diff |= given.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

function sb() {
  const url = process.env.SUPABASE_URL, key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  return { url, headers: { apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' } };
}

function gh() {
  const token = process.env.GITHUB_TOKEN;
  if (!token) return null;
  return {
    repo:   process.env.GITHUB_REPO   || 'Bonesbot/adamson-website',
    branch: process.env.GITHUB_BRANCH || 'main',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'adamson-website-cma/2.0',
      'Content-Type': 'application/json',
    },
  };
}
const ghUrl = (g, path) => `https://api.github.com/repos/${g.repo}/contents/${path}`;

async function ghGet(g, path) {
  const r = await fetch(`${ghUrl(g, path)}?ref=${encodeURIComponent(g.branch)}`, { headers: g.headers });
  if (r.status === 404) return { sha: null, b64: null };
  if (!r.ok) throw new Error(`GitHub read ${path}: ${r.status}`);
  const j = await r.json();
  return { sha: j.sha, b64: (j.content || '').replace(/\n/g, '') };
}

async function ghPut(g, path, b64, message) {
  for (const attempt of [1, 2]) {
    const { sha, b64: cur } = await ghGet(g, path);
    if (cur !== null && cur === b64) return { unchanged: true };
    const r = await fetch(ghUrl(g, path), {
      method: 'PUT', headers: g.headers,
      body: JSON.stringify({ message, content: b64, branch: g.branch, ...(sha ? { sha } : {}) }),
    });
    if (r.ok) { const j = await r.json(); return { commit: (j.commit.sha || '').slice(0, 7) }; }
    if (r.status === 409 && attempt === 1) continue;
    throw new Error(`GitHub write ${path}: ${r.status} ${(await r.text()).slice(0, 150)}`);
  }
  throw new Error(`GitHub write ${path}: exhausted retries`);
}

const b64 = (s) => Buffer.from(typeof s === 'string' ? s : JSON.stringify(s, null, 2), 'utf8').toString('base64');

function validAdjustments(a) {
  if (!a || typeof a !== 'object' || Array.isArray(a)) return 'adjustments must be an object';
  if (!a.overlay || typeof a.overlay !== 'object' || Array.isArray(a.overlay)) return 'adjustments.overlay missing';
  if (!Array.isArray(a.buckets)) return 'adjustments.buckets must be an array';
  for (const [mls, o] of Object.entries(a.overlay)) {
    if (!o || typeof o !== 'object') return `overlay["${mls}"] is not an object`;
    if (o.manual && typeof o.manual !== 'object') return `overlay["${mls}"].manual is not an object`;
    for (const [k, v] of Object.entries(o.manual || {})) {
      if (v !== null && v !== '' && !Number.isFinite(Number(v))) return `overlay["${mls}"].manual.${k} is not a number`;
    }
  }
  return null;
}

function validData(d) {
  if (!d || typeof d !== 'object') return 'data must be an object';
  if (!d.meta || !d.meta.profile) return 'data.meta.profile missing';
  if (!['condo', 'sfh'].includes(d.meta.profile)) return 'profile must be condo or sfh';
  if (!d.subject || !d.subject.address || !Number(d.subject.sqft) || !Number(d.subject.list))
    return 'subject needs address, sqft and list';
  if (!Array.isArray(d.comps)) return 'data.comps must be an array';
  for (const c of d.comps) {
    if (!c.mls) return 'every comp needs an mls (or derived) key';
    if (!Number(c.price) || !Number(c.sqft)) return `comp ${c.mls} needs price and sqft`;
  }
  return null;
}

async function touchRegistry(db, slug, patch) {
  // patch-only when the row may not exist yet; full upsert when create passes profile
  const full = patch && patch.profile;
  const req = full
    ? fetch(`${db.url}/rest/v1/cma_pages?on_conflict=slug`, {
        method: 'POST',
        headers: { ...db.headers, Prefer: 'resolution=merge-duplicates,return=minimal' },
        body: JSON.stringify([{ slug, updated_at: new Date().toISOString(), ...patch }]) })
    : fetch(`${db.url}/rest/v1/cma_pages?slug=eq.${encodeURIComponent(slug)}`, {
        method: 'PATCH',
        headers: { ...db.headers, Prefer: 'return=minimal' },
        body: JSON.stringify({ updated_at: new Date().toISOString(), ...(patch||{}) }) });
  await req.catch(e => console.error('cma: registry touch failed', e));
}

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return json(200, {});

  const qs     = event.queryStringParameters || {};
  const action = qs.action || '';
  const slug   = qs.slug || '';

  const db = sb();
  if (!db) { console.error('cma: missing SUPABASE env'); return json(500, { error: 'Server configuration error' }); }
  const adjRow = `${db.url}/rest/v1/cma_adjustments`;

  // ── public read ─────────────────────────────────────────────────────────
  if (event.httpMethod === 'GET') {
    if (!SLUG_RE.test(slug)) return json(400, { error: 'bad or missing slug' });
    try {
      const r = await fetch(`${adjRow}?slug=eq.${encodeURIComponent(slug)}&select=adjustments,rev,updated_at`, { headers: db.headers });
      if (!r.ok) return json(502, { error: 'store read failed' });
      const rows = await r.json();
      if (!rows.length) return json(200, { source: 'none', adjustments: null, rev: null });
      return json(200, { source: 'supabase', adjustments: rows[0].adjustments, rev: rows[0].rev, updated_at: rows[0].updated_at });
    } catch (e) { console.error('cma: read error', e); return json(500, { error: 'Internal server error' }); }
  }

  if (event.httpMethod !== 'POST') return json(405, { error: 'Method Not Allowed' });

  // ── auth (every POST) ───────────────────────────────────────────────────
  const expected = process.env.CMA_EDIT_KEY;
  if (!expected) { console.error('cma: CMA_EDIT_KEY not set, refusing writes'); return json(500, { error: 'Server configuration error' }); }
  const given = event.headers['x-cma-key'] || event.headers['X-Cma-Key'] || '';
  if (!keyMatches(given, expected)) {
    console.warn('cma: rejected', action || 'save', 'for', slug || '(no slug)');
    return json(401, { error: 'bad edit key' });
  }

  if (action === 'verify') return json(200, { ok: true });

  if (action === 'list') {
    try {
      const r = await fetch(`${db.url}/rest/v1/cma_pages?select=*&order=updated_at.desc`, { headers: db.headers });
      if (!r.ok) return json(502, { error: 'registry read failed' });
      return json(200, { pages: await r.json() });
    } catch (e) { console.error('cma: list error', e); return json(500, { error: 'Internal server error' }); }
  }

  if (!SLUG_RE.test(slug)) return json(400, { error: 'bad or missing slug' });

  const raw = event.body || '';
  if (Buffer.byteLength(raw, 'utf8') > MAX_BYTES) return json(413, { error: 'payload too large' });
  let body;
  try { body = JSON.parse(raw || '{}'); } catch { return json(400, { error: 'body is not valid JSON' }); }

  // ── scaffold a new CMA page ─────────────────────────────────────────────
  if (action === 'create') {
    const g = gh();
    if (!g) return json(500, { error: 'GITHUB_TOKEN not set, cannot create pages' });
    const badD = validData(body.data);
    if (badD) return json(400, { error: badD });
    const badA = validAdjustments(body.adjustments);
    if (badA) return json(400, { error: badA });
    try {
      const existing = await ghGet(g, `public/mkt/${slug}/data.json`);
      if (existing.sha) return json(409, { error: 'exists', message: `public/mkt/${slug}/ already exists in the repo` });
      const [tpl, wb] = await Promise.all([
        ghGet(g, `${TEMPLATE_DIR}/index.html`),
        ghGet(g, `${TEMPLATE_DIR}/workbench.html`),
      ]);
      if (!tpl.b64 || !wb.b64) return json(500, { error: `templates missing at ${TEMPLATE_DIR}/ in the repo` });
      const msg = (f) => `CMA ${slug}: create ${f}`;
      const out = {};
      out.data       = await ghPut(g, `public/mkt/${slug}/data.json`,        b64(body.data),        msg('data.json'));
      out.adj        = await ghPut(g, `public/mkt/${slug}/adjustments.json`, b64(body.adjustments), msg('adjustments.json'));
      out.index      = await ghPut(g, `public/mkt/${slug}/index.html`,       tpl.b64,               msg('index.html'));
      out.workbench  = await ghPut(g, `public/mkt/${slug}/workbench.html`,   wb.b64,                msg('workbench.html'));
      await touchRegistry(db, slug, {
        profile: body.data.meta.profile,
        address: body.data.subject.address,
        saved_search: body.data.meta.savedSearch || '',
        status: 'draft',
      });
      console.log('cma: created', slug);
      return json(200, { ok: true, commits: out,
        clientUrl: `/mkt/${slug}/`, workbenchUrl: `/mkt/${slug}/workbench.html`,
        note: 'Netlify is rebuilding; pages live in 1 to 2 minutes.' });
    } catch (e) { console.error('cma: create error', e); return json(502, { error: String(e.message || e) }); }
  }

  // ── comp refresh: commit a new data.json ────────────────────────────────
  if (action === 'savedata') {
    const g = gh();
    if (!g) return json(500, { error: 'GITHUB_TOKEN not set' });
    const badD = validData(body.data);
    if (badD) return json(400, { error: badD });
    try {
      const existing = await ghGet(g, `public/mkt/${slug}/data.json`);
      if (!existing.sha) return json(404, { error: `no data.json at public/mkt/${slug}/ (create the CMA first)` });
      const r = await ghPut(g, `public/mkt/${slug}/data.json`, b64(body.data),
        `CMA ${slug}: comp refresh (${body.data.meta.lastUpdated || 'undated'})`);
      await touchRegistry(db, slug, {});
      return json(200, { ok: true, ...r, note: r.unchanged ? 'no change' : 'Netlify rebuilding' });
    } catch (e) { console.error('cma: savedata error', e); return json(502, { error: String(e.message || e) }); }
  }

  // ── freeze overlay to git ───────────────────────────────────────────────
  if (action === 'snapshot') {
    const g = gh();
    if (!g) return json(500, { error: 'GITHUB_TOKEN not set' });
    try {
      const r = await fetch(`${adjRow}?slug=eq.${encodeURIComponent(slug)}&select=adjustments,rev`, { headers: db.headers });
      if (!r.ok) return json(502, { error: 'store read failed' });
      const rows = await r.json();
      if (!rows.length) return json(404, { error: 'nothing saved for this slug yet' });
      const out = await ghPut(g, `public/mkt/${slug}/adjustments.json`, b64(rows[0].adjustments),
        `CMA ${slug}: freeze adjustments snapshot`);
      if (out.unchanged) return json(200, { ok: true, unchanged: true, rev: rows[0].rev, message: 'git already matches the live row' });
      return json(200, { ok: true, commit: out.commit, rev: rows[0].rev });
    } catch (e) { console.error('cma: snapshot error', e); return json(502, { error: String(e.message || e) }); }
  }

  if (action) return json(400, { error: `unknown action "${action}"` });

  // ── default POST: save the overlay (rev-locked) ─────────────────────────
  const bad = validAdjustments(body.adjustments);
  if (bad) return json(400, { error: bad });
  const clientRev = body.rev === null || body.rev === undefined ? null : Number(body.rev);
  try {
    const cur = await fetch(`${adjRow}?slug=eq.${encodeURIComponent(slug)}&select=rev`, { headers: db.headers });
    if (!cur.ok) return json(502, { error: 'store read failed' });
    const rows = await cur.json();
    const serverRev = rows.length ? rows[0].rev : null;
    if (serverRev !== null && clientRev !== null && serverRev !== clientRev)
      return json(409, { error: 'stale', serverRev, clientRev,
        message: 'This CMA was saved elsewhere since you loaded it. Reload before saving so you do not overwrite that pass.' });
    if (serverRev !== null && clientRev === null)
      return json(409, { error: 'exists', serverRev, message: 'A saved version already exists. Reload to pick it up, then save.' });
    const nextRev = (serverRev || 0) + 1;
    const up = await fetch(`${adjRow}?on_conflict=slug`, {
      method: 'POST',
      headers: { ...db.headers, Prefer: 'resolution=merge-duplicates,return=representation' },
      body: JSON.stringify([{ slug, adjustments: body.adjustments, rev: nextRev, updated_at: new Date().toISOString() }]),
    });
    if (!up.ok) { console.error('cma: upsert failed', up.status, await up.text()); return json(502, { error: 'store write failed' }); }
    const saved = (await up.json())[0] || {};
    await touchRegistry(db, slug, {});
    console.log('cma: saved', slug, 'rev', saved.rev ?? nextRev);
    return json(200, { ok: true, rev: saved.rev ?? nextRev, updated_at: saved.updated_at });
  } catch (e) { console.error('cma: write error', e); return json(500, { error: 'Internal server error' }); }
};

// netlify/functions/str-reports.js
//
// Property registry + saved investment analyses for the STR dashboard. Companion to
// cma-adjustments.js: same edit key, same slug convention, so a property's CMA and its
// investment analyses live under one address.
//
//   GET  ?action=list                     all properties with CMA + investment status (public, no secrets)
//   GET  ?action=property&slug=<slug>     property facts + report index + latest report (public)
//   GET  ?action=report&id=<id>           one saved report (public; feeds /mkt/<slug>/report)
//   GET  ?action=report&slug=<slug>       latest saved report for the property
//   POST ?action=save        (x-cma-key)  body { slug, address, lat, lon, mls_id, facts, title, scenario,
//                                              inputs, outputs, market, comps, bands, html }
//   POST ?action=delete&id=  (x-cma-key)
//
// Tables (Supabase, service role only): public.properties, public.str_reports (see DDL in repo notes).
// No npm deps — global fetch (Netlify Node 18+).

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type, x-cma-key",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Content-Type": "application/json",
  "Cache-Control": "no-store"
};
const SLUG_RE = /^[a-z0-9][a-z0-9-]{2,63}$/;
const out = (code, obj) => ({ statusCode: code, headers: CORS, body: JSON.stringify(obj) });

function sb() {
  const url = process.env.SUPABASE_URL, key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  const h = { apikey: key, Authorization: "Bearer " + key, "Content-Type": "application/json" };
  return {
    get: async (path) => { const r = await fetch(url + "/rest/v1/" + path, { headers: h }); if (!r.ok) throw new Error("supabase " + r.status + " " + (await r.text()).slice(0, 200)); return r.json(); },
    post: async (path, body, prefer) => { const r = await fetch(url + "/rest/v1/" + path, { method: "POST", headers: Object.assign({ Prefer: prefer || "return=representation" }, h), body: JSON.stringify(body) }); if (!r.ok) throw new Error("supabase " + r.status + " " + (await r.text()).slice(0, 200)); return prefer === "return=minimal" ? null : r.json(); },
    del: async (path) => { const r = await fetch(url + "/rest/v1/" + path, { method: "DELETE", headers: h }); if (!r.ok) throw new Error("supabase " + r.status); return true; }
  };
}
const slugify = (a) => String(a || "").toLowerCase().replace(/#/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const REPORT_COLS = "id,slug,title,scenario,created_at,inputs,outputs,market,comps,bands,html";
const INDEX_COLS = "id,slug,title,scenario,created_at,outputs";

exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers: CORS, body: "" };
  const q = event.queryStringParameters || {};
  const action = q.action || "list";
  const given = event.headers["x-cma-key"] || event.headers["X-Cma-Key"] || "";
  const authed = !!process.env.CMA_EDIT_KEY && given === process.env.CMA_EDIT_KEY;
  const s = sb(); if (!s) return out(500, { error: "supabase env missing" });

  try {
    if (action === "list") {
      const [props, reports, cmas] = await Promise.all([
        s.get("properties?select=slug,address,lat,lon,mls_id,facts,updated_at&order=updated_at.desc&limit=500"),
        s.get("str_reports?select=" + INDEX_COLS + "&order=created_at.desc&limit=2000"),
        s.get("cma_pages?select=slug,profile,address,status,updated_at&order=updated_at.desc&limit=500").catch(() => [])
      ]);
      const bySlug = {};
      props.forEach((p) => { bySlug[p.slug] = Object.assign({ reports: [], cma: null }, p); });
      reports.forEach((r) => { const p = bySlug[r.slug]; if (p) p.reports.push({ id: r.id, title: r.title, scenario: r.scenario, created_at: r.created_at, headline: r.outputs && r.outputs.headline ? r.outputs.headline : null }); });
      // CMA pages: match by slug, by slug minus "-cma", or by address
      const addrKey = (a) => slugify(a);
      (cmas || []).forEach((c) => {
        const base = c.slug.replace(/-cma$/, "");
        let p = bySlug[c.slug] || bySlug[base] || Object.values(bySlug).find((x) => addrKey(x.address) === addrKey(c.address));
        if (!p) { p = bySlug[base] = { slug: base, address: c.address || base, lat: null, lon: null, facts: null, updated_at: c.updated_at, reports: [], cma: null, registry: "cma-only" }; }
        p.cma = { slug: c.slug, profile: c.profile, status: c.status, updated_at: c.updated_at, client_url: "/mkt/" + c.slug + "/", workbench_url: "/mkt/" + c.slug + "/workbench.html" };
      });
      const list = Object.values(bySlug).map((p) => Object.assign({}, p, { invest_url: "/mkt/" + p.slug + "/invest", report_url: p.reports.length ? "/mkt/" + p.slug + "/report" : null }))
        .sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
      return out(200, { properties: list });
    }

    if (action === "property") {
      const slug = String(q.slug || "").toLowerCase();
      if (!SLUG_RE.test(slug)) return out(400, { error: "bad slug" });
      const props = await s.get("properties?slug=eq." + slug + "&select=*");
      const reports = await s.get("str_reports?slug=eq." + slug + "&select=" + INDEX_COLS + "&order=created_at.desc&limit=100");
      let latest = null;
      if (reports.length) { const full = await s.get("str_reports?id=eq." + reports[0].id + "&select=" + REPORT_COLS); latest = full[0] || null; }
      const cma = (await s.get("cma_pages?or=(slug.eq." + slug + ",slug.eq." + slug + "-cma)&select=slug,profile,status,updated_at").catch(() => []))[0] || null;
      return out(200, { property: props[0] || null, reports: reports.map((r) => ({ id: r.id, title: r.title, scenario: r.scenario, created_at: r.created_at, headline: r.outputs && r.outputs.headline })), latest, cma });
    }

    if (action === "report") {
      let rows;
      if (q.id) rows = await s.get("str_reports?id=eq." + encodeURIComponent(q.id) + "&select=" + REPORT_COLS);
      else { const slug = String(q.slug || "").toLowerCase(); if (!SLUG_RE.test(slug)) return out(400, { error: "bad slug" }); rows = await s.get("str_reports?slug=eq." + slug + "&select=" + REPORT_COLS + "&order=created_at.desc&limit=1"); }
      if (!rows.length) return out(404, { error: "no report" });
      const prop = (await s.get("properties?slug=eq." + rows[0].slug + "&select=slug,address,facts,lat,lon,mls_id"))[0] || null;
      return out(200, { report: rows[0], property: prop });
    }

    if (event.httpMethod !== "POST") return out(405, { error: "POST required" });
    if (!authed) return out(401, { error: "edit key required" });
    let body = {}; try { body = JSON.parse(event.body || "{}"); } catch (e) { return out(400, { error: "bad json" }); }

    if (action === "save") {
      const slug = String(body.slug || slugify(body.address)).toLowerCase();
      if (!SLUG_RE.test(slug)) return out(400, { error: "bad slug" });
      if (!body.address) return out(400, { error: "address required" });
      const prop = { slug, address: body.address, lat: body.lat ?? null, lon: body.lon ?? null, mls_id: body.mls_id || null, facts: body.facts || null, updated_at: new Date().toISOString() };
      await s.post("properties?on_conflict=slug", prop, "resolution=merge-duplicates,return=minimal");
      const rep = { slug, title: body.title || (body.address + " · " + new Date().toLocaleDateString("en-US")), scenario: body.scenario || "avg",
                    inputs: body.inputs || {}, outputs: body.outputs || {}, market: body.market || null, comps: body.comps || null, bands: body.bands || null, html: body.html || null };
      const ins = await s.post("str_reports", rep);
      const id = ins && ins[0] ? ins[0].id : null;
      return out(200, { ok: true, id, slug, invest_url: "/mkt/" + slug + "/invest", report_url: "/mkt/" + slug + "/report" + (id ? "?id=" + id : "") });
    }
    if (action === "delete") {
      if (!q.id) return out(400, { error: "id required" });
      await s.del("str_reports?id=eq." + encodeURIComponent(q.id));
      return out(200, { ok: true });
    }
    return out(400, { error: "unknown action" });
  } catch (e) {
    return out(500, { error: String(e.message || e) });
  }
};

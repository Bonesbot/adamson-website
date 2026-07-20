// netlify/functions/lead-routing.js
//
// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  LEAD ROUTING — the ONE place to change who gets landing-page leads.     ║
// ╚══════════════════════════════════════════════════════════════════════════╝
//
// How it works: community-lead.js calls routeFor(pagePath) with the path the
// form was submitted from (e.g. '/siesta-key/gulf-and-bay-club-beachfront/').
// The FIRST route whose `match` regex tests true wins; if nothing matches,
// DEFAULT_ROUTE applies. The winning route drives:
//   • who the Gmail notification DRAFT is addressed to (draft — Ryan still
//     reviews & sends; nothing auto-sends, per the standing guardrail)
//   • the "Team:" line stamped on the Zoho CRM lead
//   • details.routing on the row in Supabase public.leads (Command Center)
//
// To add a new submarket team, copy a block and edit. Examples:
//   match: /^\/siesta-key\//i            → every Siesta Key community page
//   match: /^\/longboat-key\//i          → a future Longboat Key partner
//   match: /gulf-and-bay-club-bayside/i  → one single community page
//
// Order matters — put more specific routes ABOVE broader ones.

const DEFAULT_ROUTE = {
  label: 'Ryan (default)',
  agents: 'Ryan Adamson',
  notify: [process.env.LEAD_NOTIFY_TO || 'Ryan@Adamson-Group.com'],
};

const ROUTES = [
  {
    // Siesta Key — Ryan + Kelli Eggen partnership (all Siesta Key community pages)
    match: /^\/siesta-key\//i,
    label: 'Siesta Key — Ryan + Kelli',
    agents: 'Ryan Adamson + Kelli Eggen',
    notify: ['Ryan@Adamson-Group.com', 'Kelli.Eggen@gmail.com'],
  },
  // ── add future submarket teams here ──────────────────────────────────────
];

function routeFor(pagePath) {
  const path = String(pagePath || '');
  for (const r of ROUTES) {
    if (r.match.test(path)) return r;
  }
  return DEFAULT_ROUTE;
}

module.exports = { routeFor, ROUTES, DEFAULT_ROUTE };

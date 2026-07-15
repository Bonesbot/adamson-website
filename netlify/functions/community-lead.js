// netlify/functions/community-lead.js
//
// Community landing-page lead capture (Gulf & Bay Club Beachfront / Bayside, and any
// future community page using the same form markup).
//
// Does three things, independently — one failing never blocks the others, and the
// browser always gets a 200 as long as the lead landed SOMEWHERE:
//   1. Supabase  -> public.community_leads          (system of record)
//   2. Zoho CRM  -> Leads, Lead_Status "Landing Pg - New"
//   3. Gmail     -> a DRAFT to Ryan@Adamson-group.com (queued, not sent — Ryan reviews)
//
// ── Supabase table DDL ────────────────────────────────────────────────────────────
//
//   create table if not exists public.community_leads (
//     id           uuid        primary key default gen_random_uuid(),
//     created_at   timestamptz not null default now(),
//     name         text,
//     email        text        not null,
//     phone        text,
//     lead_type    text,                       -- 'Buyer' | 'Seller'
//     community    text,                       -- e.g. 'Gulf & Bay Club Bayside'
//     page         text,
//     zoho_lead_id text,
//     zoho_error   text,
//     raw_payload  jsonb
//   );
//   create index if not exists community_leads_created_idx on public.community_leads (created_at desc);
//   create index if not exists community_leads_email_idx   on public.community_leads (email);
//   alter table public.community_leads enable row level security;
//
// ── Env vars (Netlify dashboard) ──────────────────────────────────────────────────
//   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY          (already set for other functions)
//   ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN
//   ZOHO_ACCOUNTS_DOMAIN   optional, default https://accounts.zoho.com
//   ZOHO_API_DOMAIN        optional, default https://www.zohoapis.com
//   GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN
//   LEAD_NOTIFY_TO         optional, default Ryan@Adamson-group.com
//
// Any of the Zoho/Gmail vars being absent simply skips that leg (logged, not fatal),
// so the page keeps working before the OAuth credentials are wired up.
//
// No npm deps — global fetch (Netlify Node 18+).

const NOTIFY_TO = process.env.LEAD_NOTIFY_TO || 'Ryan@Adamson-group.com';

const json = (statusCode, obj) => ({
  statusCode,
  headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
  body: JSON.stringify(obj),
});

// Zoho's Lead_Status picklist value is EXACTLY this — spaces around the dash.
// Sending anything else makes Zoho reject the record.
const LEAD_STATUS = 'Landing Pg - New';

/** "Jane Q. Smith" -> { first: 'Jane Q.', last: 'Smith' }; Last_Name is mandatory in Zoho. */
function splitName(full) {
  const parts = String(full || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return { first: null, last: 'Unknown' };
  if (parts.length === 1) return { first: null, last: parts[0] };
  return { first: parts.slice(0, -1).join(' '), last: parts[parts.length - 1] };
}

// ── Zoho ───────────────────────────────────────────────────────────────────────

async function zohoAccessToken() {
  const id = process.env.ZOHO_CLIENT_ID;
  const secret = process.env.ZOHO_CLIENT_SECRET;
  const refresh = process.env.ZOHO_REFRESH_TOKEN;
  if (!id || !secret || !refresh) return null;

  const accounts = process.env.ZOHO_ACCOUNTS_DOMAIN || 'https://accounts.zoho.com';
  const res = await fetch(`${accounts}/oauth/v2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      refresh_token: refresh,
      client_id: id,
      client_secret: secret,
      grant_type: 'refresh_token',
    }).toString(),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.access_token) {
    throw new Error(`zoho token refresh failed: ${res.status} ${JSON.stringify(data)}`);
  }
  return data.access_token;
}

async function createZohoLead(lead) {
  const token = await zohoAccessToken();
  if (!token) return { skipped: 'zoho env vars not configured' };

  const api = process.env.ZOHO_API_DOMAIN || 'https://www.zohoapis.com';
  const { first, last } = splitName(lead.name);
  const intent = lead.lead_type === 'Seller'
    ? 'Requested a private seller consult'
    : 'Asked to join the coming-soon / off-market list';

  const record = {
    Last_Name: last,
    First_Name: first,
    Email: lead.email,
    Phone: lead.phone || null,
    Lead_Status: LEAD_STATUS,
    Lead_Type: lead.lead_type === 'Seller' ? 'Seller' : 'Buyer',
    Company: lead.community || 'Website Lead',
    Description: [
      `${intent}.`,
      `Community: ${lead.community || 'n/a'}`,
      `Page: ${lead.page || 'n/a'}`,
      `Submitted: ${new Date().toISOString()}`,
    ].join('\n'),
  };

  const res = await fetch(`${api}/crm/v6/Leads`, {
    method: 'POST',
    headers: {
      Authorization: `Zoho-oauthtoken ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ data: [record], trigger: ['workflow'] }),
  });
  const data = await res.json().catch(() => ({}));
  const row = data && data.data && data.data[0];
  if (!res.ok || !row || row.code !== 'SUCCESS') {
    throw new Error(`zoho create failed: ${res.status} ${JSON.stringify(data)}`);
  }
  return { id: row.details && row.details.id };
}

// ── Gmail (draft — queued for Ryan to review & send) ────────────────────────────

async function gmailAccessToken() {
  const id = process.env.GMAIL_CLIENT_ID;
  const secret = process.env.GMAIL_CLIENT_SECRET;
  const refresh = process.env.GMAIL_REFRESH_TOKEN;
  if (!id || !secret || !refresh) return null;

  const res = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: id,
      client_secret: secret,
      refresh_token: refresh,
      grant_type: 'refresh_token',
    }).toString(),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.access_token) {
    throw new Error(`gmail token refresh failed: ${res.status} ${JSON.stringify(data)}`);
  }
  return data.access_token;
}

function b64url(str) {
  return Buffer.from(str, 'utf-8')
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

async function queueGmailDraft(lead, zohoId) {
  const token = await gmailAccessToken();
  if (!token) return { skipped: 'gmail env vars not configured' };

  const kind = lead.lead_type === 'Seller' ? 'SELLER' : 'BUYER';
  const subject = `[${kind} LEAD] ${lead.name || lead.email} — ${lead.community || 'Website'}`;
  const body = [
    `New ${kind.toLowerCase()} lead from the ${lead.community || 'website'} landing page.`,
    '',
    `Name:      ${lead.name || '—'}`,
    `Email:     ${lead.email}`,
    `Phone:     ${lead.phone || '—'}`,
    `Lead Type: ${lead.lead_type}`,
    `Community: ${lead.community || '—'}`,
    `Page:      https://adamsonfl.com${lead.page || ''}`,
    `Received:  ${new Date().toLocaleString('en-US', { timeZone: 'America/New_York' })} ET`,
    '',
    zohoId
      ? `Zoho lead created (status "${LEAD_STATUS}"): https://crm.zoho.com/crm/tab/Leads/${zohoId}`
      : 'NOTE: Zoho lead was NOT created — check the function logs.',
    '',
    '— Adamson Group site automation',
  ].join('\r\n');

  const mime = [
    `To: ${NOTIFY_TO}`,
    `Subject: ${subject}`,
    'Content-Type: text/plain; charset="UTF-8"',
    'MIME-Version: 1.0',
    '',
    body,
  ].join('\r\n');

  const res = await fetch('https://gmail.googleapis.com/gmail/v1/users/me/drafts', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: { raw: b64url(mime) } }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`gmail draft failed: ${res.status} ${JSON.stringify(data)}`);
  return { id: data.id };
}

// ── Supabase ───────────────────────────────────────────────────────────────────

async function storeLead(lead, zohoId, zohoError) {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return { skipped: 'supabase env vars not configured' };

  const res = await fetch(`${url}/rest/v1/community_leads`, {
    method: 'POST',
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      'Content-Type': 'application/json',
      Prefer: 'return=minimal',
    },
    body: JSON.stringify({
      name: lead.name || null,
      email: lead.email,
      phone: lead.phone || null,
      lead_type: lead.lead_type || null,
      community: lead.community || null,
      page: lead.page || null,
      zoho_lead_id: zohoId || null,
      zoho_error: zohoError || null,
      raw_payload: lead,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`supabase insert failed: ${res.status} ${text}`);
  }
  return { ok: true };
}

// ── Handler ────────────────────────────────────────────────────────────────────

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') {
    return {
      statusCode: 200,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
      },
      body: '',
    };
  }
  if (event.httpMethod !== 'POST') return json(405, { error: 'Method Not Allowed' });

  let lead;
  try {
    const body = JSON.parse(event.body || '{}');
    if (body['bot-field']) return json(200, { success: true });   // honeypot

    if (!body.email || !String(body.email).trim()) {
      return json(400, { error: 'Email is required' });
    }
    lead = {
      name: (body.name || '').trim() || null,
      email: String(body.email).trim(),
      phone: (body.phone || '').trim() || null,
      lead_type: body.lead_type === 'Seller' ? 'Seller' : 'Buyer',
      community: (body.community || '').trim() || null,
      page: (body.page || '').trim() || null,
    };
  } catch (err) {
    return json(400, { error: 'Bad request' });
  }

  // Zoho first so its id can ride along into Supabase + the notification.
  let zohoId = null;
  let zohoError = null;
  try {
    const r = await createZohoLead(lead);
    if (r.skipped) console.warn('community-lead: zoho skipped —', r.skipped);
    else { zohoId = r.id; console.log('community-lead: zoho lead', zohoId); }
  } catch (err) {
    zohoError = String(err.message || err);
    console.error('community-lead: zoho failed —', zohoError);
  }

  const results = await Promise.allSettled([
    storeLead(lead, zohoId, zohoError),
    queueGmailDraft(lead, zohoId),
  ]);
  const [stored, mailed] = results;

  if (stored.status === 'rejected') console.error('community-lead: supabase —', stored.reason);
  else if (stored.value && stored.value.skipped) console.warn('community-lead: supabase skipped —', stored.value.skipped);

  if (mailed.status === 'rejected') console.error('community-lead: gmail —', mailed.reason);
  else if (mailed.value && mailed.value.skipped) console.warn('community-lead: gmail skipped —', mailed.value.skipped);

  // Only a total loss (nowhere recorded at all) is an error to the visitor — Netlify
  // Forms still has the submission via the page's mirrored POST.
  const savedSomewhere =
    (stored.status === 'fulfilled' && stored.value && stored.value.ok) || Boolean(zohoId);
  if (!savedSomewhere) return json(500, { error: 'Failed to save your request' });

  console.log('community-lead:', lead.lead_type, 'lead stored for', lead.email, '/', lead.community);
  return json(200, { success: true });
};

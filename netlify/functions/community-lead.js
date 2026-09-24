// netlify/functions/community-lead.js
//
// Community landing-page lead capture (Gulf & Bay Club Beachfront / Bayside, and any
// future community page using the same form markup).
//
// Does three things, independently — one failing never blocks the others, and the
// browser always gets a 200 as long as the lead landed SOMEWHERE:
//   1. Supabase  -> public.leads                     (THE core lead queue)
//   2. Zoho CRM  -> Leads, Lead_Status "Landing Pg - New"
//   3. Gmail     -> notification EMAIL SENT to the routed team (draft fallback if send scope missing)
//
// Schema: supabase/migrations/leads.sql. Every capture form on the site writes to
// public.leads with a `<page-slug>:<intent>` source tag, so a new community
// landing page needs NO new table, NO new function and NO dashboard change — it
// just posts and appears in the Command Center queue, tagged.
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

// Who gets each lead (Gmail draft recipients, Zoho team stamp) lives in ONE
// easy-to-edit config: ./lead-routing.js — e.g. Siesta Key -> Ryan + Kelli.
import { routeFor } from './lead-routing.js';

// Home platform CRM forward: mimics the IDX Broker lead-email format so their
// inbound parser files the lead automatically. Fire-and-forget; never fatal.
import { forwardLeadToHomePlatform } from './homeplatform-lead-forward.js';

// Spam verdict + lead attribution (page stamp from the SiteAnalytics component).
import { assessSpam, logBlocked, spamDetails } from './_lib/spam.js';

const json = (statusCode, obj) => ({
  statusCode,
  headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
  body: JSON.stringify(obj),
});

// Zoho's Lead_Status picklist value is EXACTLY this — spaces around the dash.
// Sending anything else makes Zoho reject the record.
const LEAD_STATUS = 'Landing Pg - New';

/**
 * Build the `<page-slug>:<intent>` source tag from the page the form sat on, so
 * every future community landing page is zero-config: no hidden field to forget,
 * no per-page constant to maintain. '/siesta-key/gulf-and-bay-club-bayside/' +
 * Seller -> 'gulf-and-bay-club-bayside:seller'. An explicit body.source wins.
 */
function sourceFor(body) {
  const explicit = (body.source || '').trim();
  if (explicit) return explicit;
  const slug = String(body.page || '').split('?')[0].split('/').filter(Boolean).pop();
  const intent = body.lead_type === 'Seller' ? 'seller' : 'buyer';
  return slug ? `${slug}:${intent}` : `community:${intent}`;
}

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
      `Team: ${lead.route ? lead.route.agents : 'Ryan Adamson'}`,
      `Community: ${lead.community || 'n/a'}`,
      `Page: ${lead.page || 'n/a'}`,
      ...(lead.notes ? ['', 'What they told us:', lead.notes] : []),
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

// ── Resend (Info@AdamsonFL.com): primary notification channel ─────────────────
//
// Sends the team notification FROM Info@AdamsonFL.com (domain-verified in
// Resend) TO the routed notify list, Reply-To Ryan's real mailbox. Configured
// via RESEND_API_KEY (sending-only key). Falls back to the Gmail leg below if
// the key is absent.

const RESEND_FROM = process.env.RESEND_FROM || 'The Adamson Group <Info@AdamsonFL.com>';
const RESEND_REPLY_TO = process.env.RESEND_REPLY_TO || 'Ryan@adamson-group.com';

async function sendResendEmail({ to, subject, text, replyTo }) {
  const key = process.env.RESEND_API_KEY;
  if (!key) return { skipped: 'RESEND_API_KEY not configured' };
  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      from: RESEND_FROM,
      to: Array.isArray(to) ? to : [to],
      reply_to: replyTo || RESEND_REPLY_TO,
      subject,
      text,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`resend send failed: ${res.status} ${JSON.stringify(data).slice(0, 200)}`);
  return { id: data.id, sent: true, via: 'resend' };
}

async function sendTeamNotification(lead, zohoId) {
  if (!process.env.RESEND_API_KEY) return queueGmailDraft(lead, zohoId);
  const kind = lead.lead_type === 'Seller' ? 'SELLER'
    : lead.lead_type === 'Showing' ? 'SHOWING' : 'BUYER';
  const flagged = lead.spam && lead.spam.spam;
  const subject = `${flagged ? '[SPAM?] ' : ''}[${kind} LEAD] ${lead.name || lead.email} - ${lead.community || 'Website'}`;
  const ft = lead.spam && lead.spam.attribution && lead.spam.attribution.first_touch;
  const cameFrom = ft
    ? [ft.uc ? `campaign ${ft.uc}` : null, ft.us ? `source ${ft.us}` : null,
       !ft.uc && ft.ref ? `referrer ${ft.ref}` : null, ft.lp ? `landed on ${ft.lp}` : null].filter(Boolean).join(' | ')
    : null;
  const body = [
    ...(flagged ? [
      'SPAM FILTER: this submission was flagged as likely spam (score ' + lead.spam.score + ': ' + lead.spam.reasons.join(', ') + ').',
      'It was NOT sent to Zoho or Home Platform. If it is a real person, reply normally and tell Claude so the filter can be tuned.',
      '',
    ] : []),
    `New ${kind.toLowerCase()} lead from the ${lead.community || 'website'} landing page.`,
    '',
    `Name:      ${lead.name || '-'}`,
    `Email:     ${lead.email}`,
    `Phone:     ${lead.phone || '-'}`,
    `Lead Type: ${lead.lead_type}`,
    `Community: ${lead.community || '-'}`,
    ...(lead.notes ? ['', 'What they told us:', lead.notes, ''] : []),
    `Page:      https://adamsonfl.com${lead.page || ''}`,
    `Received:  ${new Date().toLocaleString('en-US', { timeZone: 'America/New_York' })} ET`,
    `Routed to: ${lead.route ? lead.route.label : 'Ryan (default)'}`,
    ...(cameFrom ? [`Came from: ${cameFrom}`] : []),
    '',
    flagged ? 'Zoho: skipped (flagged as spam).' : zohoId
      ? `Zoho lead created (status "${LEAD_STATUS}"): https://crm.zoho.com/crm/tab/Leads/${zohoId}`
      : 'NOTE: Zoho lead was NOT created: check the function logs.',
    '',
    '- Adamson Group site automation',
  ].join('\n');
  const notify = (lead.route && lead.route.notify && lead.route.notify.length)
    ? lead.route.notify
    : ['Ryan@Adamson-Group.com'];
  return sendResendEmail({ to: notify, subject, text: body });
}

// Courtesy receipt to the lead. HARD-GATED: sends only when COURTESY_REPLY=on
// in the environment AND the template below has been approved by Ryan.
// Fixed template — nothing dynamic beyond name/address. Never marketing copy.
async function sendCourtesyReply(lead) {
  if (process.env.COURTESY_REPLY !== 'on') return { skipped: 'courtesy reply disabled' };
  if (!process.env.RESEND_API_KEY || !lead.email) return { skipped: 'no key or no email' };
  const first = String(lead.name || '').trim().split(/\s+/)[0] || 'there';
  const isShowing = lead.lead_type === 'Showing';
  const what = isShowing
    ? `Your showing request${lead.community && lead.community !== 'Website' ? ' for ' + lead.community : ''} is in front of us now.`
    : 'Your message is in front of us now.';
  const body = [
    `Thanks, ${first}.`,
    '',
    what,
    'Expect a personal reply within the hour during business hours.',
    '',
    'Ryan Adamson & Anne Schneider',
    'The Adamson Group · Coldwell Banker Global Luxury, St. Armands',
    '(941) 713-9234',
    '',
    'Prefer to talk now? Just call, or reply to this email and it comes straight to Ryan.',
  ].join('\n');
  return sendResendEmail({
    to: lead.email,
    subject: isShowing ? 'Your showing request is received' : 'We got your message',
    text: body,
  });
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
    ...(lead.notes ? ['', 'What they told us:', lead.notes, ''] : []),
    `Page:      https://adamsonfl.com${lead.page || ''}`,
    `Received:  ${new Date().toLocaleString('en-US', { timeZone: 'America/New_York' })} ET`,
    `Routed to: ${lead.route ? lead.route.label : 'Ryan (default)'}`,
    '',
    zohoId
      ? `Zoho lead created (status "${LEAD_STATUS}"): https://crm.zoho.com/crm/tab/Leads/${zohoId}`
      : 'NOTE: Zoho lead was NOT created — check the function logs.',
    '',
    '— Adamson Group site automation',
  ].join('\r\n');

  const notify = (lead.route && lead.route.notify && lead.route.notify.length)
    ? lead.route.notify.join(', ')
    : 'Ryan@Adamson-Group.com';

  const mime = [
    `To: ${notify}`,
    `Subject: ${subject}`,
    'Content-Type: text/plain; charset="UTF-8"',
    'MIME-Version: 1.0',
    '',
    body,
  ].join('\r\n');

  // SEND the team notification (Ryan requested auto-send 2026-08-27: internal
  // notification to the routed agents only, never to the consumer). If the
  // OAuth token lacks send scope, fall back to the old draft behavior so no
  // lead notification is ever lost.
  const sendRes = await fetch('https://gmail.googleapis.com/gmail/v1/users/me/messages/send', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ raw: b64url(mime) }),
  });
  if (sendRes.ok) {
    const sent = await sendRes.json().catch(() => ({}));
    return { id: sent.id, sent: true };
  }
  const sendErr = await sendRes.json().catch(() => ({}));
  console.warn('community-lead: gmail send failed, falling back to draft:', sendRes.status, JSON.stringify(sendErr).slice(0, 200));
  const res = await fetch('https://gmail.googleapis.com/gmail/v1/users/me/drafts', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: { raw: b64url(mime) } }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`gmail draft failed: ${res.status} ${JSON.stringify(data)}`);
  return { id: data.id, sent: false };
}

// ── Supabase ───────────────────────────────────────────────────────────────────

async function storeLead(lead, zohoId, zohoError) {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return { skipped: 'supabase env vars not configured' };

  const { first, last } = splitName(lead.name);
  const res = await fetch(`${url}/rest/v1/leads`, {
    method: 'POST',
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      'Content-Type': 'application/json',
      Prefer: 'return=minimal',
    },
    body: JSON.stringify({
      first_name: first,
      last_name: last,
      email: lead.email,
      phone: lead.phone || null,
      source: lead.source,
      lead_type: lead.lead_type,
      community: lead.community || null,
      page: lead.page || null,
      ...(lead.spam && lead.spam.spam ? { status: 'spam' } : {}),
      zoho_lead_id: zohoId || null,
      zoho_sync: lead.spam && lead.spam.spam ? 'skipped:spam' : (zohoId ? 'ok' : null),
      zoho_error: zohoError || null,
      details: {
        ...(lead.route
          ? { routing: lead.route.label, routed_to: lead.route.notify, agents: lead.route.agents }
          : {}),
        ...(lead.notes ? { notes: lead.notes } : {}),
        ...(lead.spam ? spamDetails(lead.spam) : {}),
      },
      raw_payload: (({ spam, route, ...rest }) => rest)(lead),
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`supabase insert failed: ${res.status} ${text}`);
  }
  return { ok: true };
}

// ── Handler ────────────────────────────────────────────────────────────────────

export const handler = async (event) => {
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

  // No-JS fallback: forms post here natively (action=this function) as
  // application/x-www-form-urlencoded; answer with a 303 to the thank-you page.
  const ctype = String((event.headers && (event.headers['content-type'] || event.headers['Content-Type'])) || '');
  const native = /application\/x-www-form-urlencoded/i.test(ctype);
  // Send the visitor back to the site they posted from (longboatlido.com posts here cross-origin).
  let backTo = '';
  try {
    const o = new URL(event.headers.referer || event.headers.Referer || '');
    if (/^(www\.)?(adamsonfl|siestareport|longboatlido)\.com$/i.test(o.hostname)) backTo = o.origin;
  } catch (_) {}
  const done = (code, obj) => (native
    ? { statusCode: 303, headers: { Location: backTo + (code < 400 ? '/thank-you/' : '/') }, body: '' }
    : json(code, obj));

  let lead;
  let body;
  try {
    const raw = event.isBase64Encoded ? Buffer.from(event.body || '', 'base64').toString('utf8') : (event.body || '');
    if (native) {
      body = Object.fromEntries(new URLSearchParams(raw));
      if (!body.page) {
        try { body.page = new URL(event.headers.referer || event.headers.Referer).pathname; } catch (_) {}
      }
      if (!body.notes && body.message) body.notes = body.message;
      if (!body.name && body.firstName) body.name = body.firstName;
      if (!body.lead_type && /seller/i.test(body['form-name'] || '')) body.lead_type = 'Seller';
      const STD = new Set(['name', 'firstName', 'email', 'phone', 'notes', 'message', 'lead_type', 'community',
        'page', 'source', 'form-name', 'bot-field', 'consent']);
      const extra = Object.entries(body).filter(([k, v]) => !STD.has(k) && v).map(([k, v]) => `${k}: ${v}`);
      if (extra.length) body.notes = [body.notes, ...extra].filter(Boolean).join('\n');
    } else {
      body = JSON.parse(raw || '{}');
    }

    if (!body.email || !String(body.email).trim()) {
      return done(400, { error: 'Email is required' });
    }
    lead = {
      name: (body.name || '').trim() || null,
      email: String(body.email).trim(),
      phone: (body.phone || '').trim() || null,
      // free text the visitor typed: unit number, view, size, timing. Capped because it
      // rides into Zoho's Description and a Gmail draft, neither of which wants an essay.
      notes: (body.notes || '').trim().slice(0, 1200) || null,
      lead_type: body.lead_type === 'Seller' ? 'Seller' : 'Buyer',
      community: (body.community || '').trim() || null,
      page: (body.page || '').trim() || null,
    };
    lead.source = sourceFor(body);
    lead.route = routeFor(lead.page);
  } catch (err) {
    return done(400, { error: 'Bad request' });
  }

  // ── Spam gate ────────────────────────────────────────────────────────────────
  // bot  -> logged to web_events, nothing stored as a lead, visitor sees success.
  // spam -> stored with status 'spam', no Zoho / Home Platform; team email only in
  //         SPAM_MODE=tag (default), with a [SPAM?] subject.
  try {
    lead.spam = await assessSpam({
      body, event, headers: event.headers, source: lead.source,
      fields: { name: lead.name, email: lead.email, phone: lead.phone, message: lead.notes },
    });
  } catch (err) {
    console.error('community-lead: spam check failed (lead treated as ok):', String(err.message || err));
    lead.spam = null;
  }
  if (lead.spam && lead.spam.kind === 'bot') {
    await logBlocked(lead.spam, { body, event, headers: event.headers, source: lead.source });
    console.log('community-lead: bot blocked |', lead.spam.reasons.join(','));
    return done(200, { success: true });
  }
  const flagged = Boolean(lead.spam && lead.spam.spam);
  if (flagged) console.warn('community-lead: flagged spam |', lead.spam.score, lead.spam.reasons.join(','));

  // Zoho first so its id can ride along into Supabase + the notification.
  let zohoId = null;
  let zohoError = null;
  try {
    const r = flagged ? { skipped: 'flagged as spam' } : await createZohoLead(lead);
    if (r.skipped) console.warn('community-lead: zoho skipped —', r.skipped);
    else { zohoId = r.id; console.log('community-lead: zoho lead', zohoId); }
  } catch (err) {
    zohoError = String(err.message || err);
    console.error('community-lead: zoho failed —', zohoError);
  }

  const results = await Promise.allSettled([
    storeLead(lead, zohoId, zohoError),
    flagged && lead.spam.mode === 'quarantine'
      ? Promise.resolve({ skipped: 'spam quarantined' })
      : sendTeamNotification(lead, zohoId),
    flagged ? Promise.resolve({ skipped: 'spam' }) : sendCourtesyReply(lead),
  ]);
  const [stored, mailed, courtesy] = results;
  if (courtesy && courtesy.status === 'rejected') console.error('community-lead: courtesy reply —', courtesy.reason);

  if (stored.status === 'rejected') console.error('community-lead: supabase —', stored.reason);
  else if (stored.value && stored.value.skipped) console.warn('community-lead: supabase skipped —', stored.value.skipped);

  if (mailed.status === 'rejected') console.error('community-lead: gmail —', mailed.reason);
  else if (mailed.value && mailed.value.skipped) console.warn('community-lead: gmail skipped —', mailed.value.skipped);

  // ── Home platform forward (after Supabase write + our own notifications) ────
  // Failure logs to the function console and never breaks the visitor response.
  if (!flagged) try {
    const { first, last } = splitName(lead.name);
    const fwd = await forwardLeadToHomePlatform({
      firstName: first || '',
      lastName: last || '',
      email: lead.email,
      phone: lead.phone || '',
      message: lead.notes || '',
      sourceUrl: lead.page
        ? (lead.page.startsWith('http') ? lead.page : `https://adamsonfl.com${lead.page}`)
        : 'https://adamsonfl.com',
      // Community forms carry no structured listing data — omit `listing` so the
      // email goes out as a general inquiry (the module handles the formatting).
    });
    if (fwd && fwd.ok) console.log('community-lead: home platform forwarded', fwd.id);
    else if (fwd) console.error('community-lead: home platform forward not ok', fwd.status);
  } catch (err) {
    console.error('community-lead: home platform forward —', String(err && err.message || err));
  }

  // Only a total loss (nowhere recorded at all) is an error to the visitor — Netlify
  // Forms still has the submission via the page's mirrored POST.
  const savedSomewhere =
    (stored.status === 'fulfilled' && stored.value && stored.value.ok) || Boolean(zohoId);
  if (!savedSomewhere) return done(500, { error: 'Failed to save your request' });

  console.log('community-lead:', lead.source, '| stored', lead.email, '| zoho', zohoId || 'skipped');
  return done(200, { success: true });
};

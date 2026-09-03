/**
 * mls-watchdog — off-machine dead-man's-switch for the daily MLS export.
 *
 * WHY THIS EXISTS
 * ---------------
 * From 2026-08-26 to 2026-09-01 the mls-export job failed every morning and
 * nobody was told for eight days. Two alerting layers failed at once:
 *   1. The job's own email (Gmail draft + Apps Script) produced nothing.
 *   2. The old mls-export-watchdog ran ON THE SAME MINI-PC and also used
 *      Gmail, so it died the same silent death.
 *
 * The lesson: a watchdog that shares infrastructure with the thing it watches
 * is not a watchdog. This one runs on Netlify — different machine, different
 * network, different email path — so it survives the mini-PC being asleep,
 * Cowork being closed, Chrome being signed out, or the scheduler being broken.
 *
 * HOW IT DECIDES
 * --------------
 * It does not look at log files or heartbeats written by the job (those live on
 * the mini-PC and are invisible from here, and a frozen file looks identical to
 * a fresh one). Instead it asks the only shared source of truth: Postgres.
 * Every successful run writes a row to import_batches. If the newest row is
 * older than STALE_HOURS, no successful run has happened and Ryan gets an email.
 *
 * This catches EVERY failure mode, including the ones the job cannot report on
 * itself: job never launched, machine off, app closed, run died mid-flight.
 */

const STALE_HOURS = Number(process.env.MLS_STALE_HOURS || 26); // ~1 day + slack
const ALERT_TO = process.env.MLS_ALERT_TO || 'Ryan@Adamson-Group.com';
const RESEND_FROM = process.env.RESEND_FROM || 'The Adamson Group <Info@AdamsonFL.com>';
const RESEND_REPLY_TO = process.env.RESEND_REPLY_TO || 'Ryan@adamson-group.com';

/** Newest import_batches row via the Supabase REST API. */
async function fetchLastIngest() {
  const base = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!base || !key) throw new Error('SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing');

  const url =
    `${base.replace(/\/$/, '')}/rest/v1/import_batches` +
    `?select=imported_at,total_rows,rows_inserted,rows_updated,status` +
    `&order=imported_at.desc&limit=1`;

  const res = await fetch(url, {
    headers: { apikey: key, Authorization: `Bearer ${key}`, Accept: 'application/json' },
  });
  if (!res.ok) {
    throw new Error(`supabase query failed: ${res.status} ${(await res.text()).slice(0, 200)}`);
  }
  const rows = await res.json();
  return Array.isArray(rows) && rows.length ? rows[0] : null;
}

async function sendAlert(subject, text) {
  const key = process.env.RESEND_API_KEY;
  if (!key) return { sent: false, error: 'RESEND_API_KEY not configured' };
  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      from: RESEND_FROM,
      to: [ALERT_TO],
      reply_to: RESEND_REPLY_TO,
      subject,
      text,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return { sent: false, error: `resend ${res.status}: ${JSON.stringify(data).slice(0, 200)}` };
  return { sent: true, id: data.id };
}

function buildBody({ hours, days, last, reason }) {
  if (reason === 'db_unreachable') {
    return [
      'MLS EXPORT WATCHDOG - cannot verify the pipeline.',
      '',
      'This watchdog could not reach the Supabase database to check whether',
      "today's MLS export ran. That is itself a problem worth knowing about:",
      'it means either the database is down or its credentials have changed.',
      '',
      `Detail: ${last}`,
      '',
      'The MLS data may or may not be fine. Worth a manual look.',
      '',
      '- BonesBot (Netlify watchdog)',
    ].join('\n');
  }
  const when = last ? new Date(last).toLocaleString('en-US', { timeZone: 'America/New_York' }) : 'never';
  return [
    'MLS EXPORT WATCHDOG - no successful run detected.',
    '',
    `The last successful MLS load was ${hours} hours ago (about ${days} day(s)).`,
    `Most recent successful run: ${when} Eastern.`,
    '',
    'WHAT THIS MEANS',
    'The daily export has not completed since then. Postgres, the Streamlit',
    'dashboard, and every area page on the site are still serving that older',
    'snapshot. They will look completely normal - a stale number is',
    'indistinguishable from a fresh one - so nothing else will warn you.',
    '',
    'MOST LIKELY CAUSE',
    'An expired Stellar MLS sign-in. Open https://www.stellarmls.com/ in Chrome',
    'on the mini-PC, click MLS Login, enter your password and finish the SMS',
    '2FA. One sign-in usually buys 2+ weeks of unattended runs.',
    '',
    'ALSO CHECK',
    '- Is the mini-PC awake and is the Claude desktop app open?',
    '- Did the scheduled mls-export task get disabled?',
    '',
    'This check runs on Netlify, independent of the mini-PC, and emails through',
    'Resend. It will keep nudging you daily until a successful run lands.',
    '',
    '- BonesBot (Netlify watchdog)',
  ].join('\n');
}

exports.handler = async (event) => {
  // Netlify scheduled invocations carry a body with next_run. Manual browser
  // hits do not. Only the scheduler (or an explicit ?force=1) may SEND email,
  // so a casual visitor to this URL cannot spam Ryan's inbox.
  let isScheduled = false;
  try {
    isScheduled = !!(event && event.body && JSON.parse(event.body).next_run);
  } catch (_) { /* not scheduled */ }
  const force = !!(event && event.queryStringParameters && event.queryStringParameters.force);
  const maySend = isScheduled || force;

  let row = null;
  let dbError = null;
  try {
    row = await fetchLastIngest();
  } catch (e) {
    dbError = e.message || String(e);
  }

  // Could not reach the DB — alert on that too rather than failing quietly.
  if (dbError) {
    const out = { ok: false, reason: 'db_unreachable', detail: dbError, emailed: null };
    if (maySend) {
      out.emailed = await sendAlert(
        'MLS watchdog: cannot verify pipeline (database unreachable)',
        buildBody({ reason: 'db_unreachable', last: dbError })
      );
    }
    return { statusCode: 200, body: JSON.stringify(out) };
  }

  const lastIso = row && row.imported_at ? row.imported_at : null;
  const lastMs = lastIso ? Date.parse(lastIso) : NaN;
  const hours = Number.isFinite(lastMs) ? (Date.now() - lastMs) / 3600000 : Infinity;
  const stale = !(hours < STALE_HOURS);

  const out = {
    ok: !stale,
    lastIngest: lastIso,
    hoursSince: Number.isFinite(hours) ? Math.round(hours * 10) / 10 : null,
    thresholdHours: STALE_HOURS,
    stale,
    scheduled: isScheduled,
    emailed: null,
  };

  if (stale && maySend) {
    const days = Number.isFinite(hours) ? Math.max(1, Math.round(hours / 24)) : '?';
    const h = Number.isFinite(hours) ? Math.round(hours) : 'an unknown number of';
    out.emailed = await sendAlert(
      `MLS export has not run in ${days} day(s) - action needed`,
      buildBody({ hours: h, days, last: lastIso, reason: 'stale' })
    );
  }

  // Always 200 so Netlify does not retry-storm; the payload carries the verdict.
  return { statusCode: 200, body: JSON.stringify(out, null, 2) };
};

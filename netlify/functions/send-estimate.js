// netlify/functions/send-estimate.js
//
// Emails a closing-cost estimate PDF, built client-side by
// /mkt/<slug>/estimator.html (jsPDF + autoTable), through Resend.
//
// Deliberately NOT an open relay: the recipient is always the internal notify
// list, never an address supplied by the caller. Ryan forwards to the party.
// To allow a typed recipient later, set ESTIMATE_ALLOW_RECIPIENT=on and pass
// `to` in the body — it is validated and capped at one address.
//
// Env vars:
//   RESEND_API_KEY            required — already set for the lead flow
//   RESEND_FROM               default 'The Adamson Group <Info@AdamsonFL.com>'
//   RESEND_REPLY_TO           default 'Ryan@adamson-group.com'
//   LEAD_NOTIFY_TO            default 'Ryan@Adamson-group.com' (comma-separated ok)
//   ESTIMATE_ALLOW_RECIPIENT  'on' to honour body.to (off by default)
//
// No npm deps — global fetch (Netlify Node 18+).

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Content-Type': 'application/json'
};

const RESEND_FROM = process.env.RESEND_FROM || 'The Adamson Group <Info@AdamsonFL.com>';
const RESEND_REPLY_TO = process.env.RESEND_REPLY_TO || 'Ryan@adamson-group.com';
const NOTIFY_TO = (process.env.LEAD_NOTIFY_TO || 'Ryan@Adamson-group.com')
  .split(',').map(s => s.trim()).filter(Boolean);

// Resend caps a message at 40MB; a generated estimate is ~40-90KB. Anything
// over 8MB is not one of ours.
const MAX_PDF_BYTES = 8 * 1024 * 1024;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[a-z]{2,}$/i;

const fail = (code, msg) => ({ statusCode: code, headers: CORS, body: JSON.stringify({ error: msg }) });

const money = n =>
  typeof n === 'number' && isFinite(n)
    ? (n < 0 ? '-' : '') + '$' + Math.abs(Math.round(n)).toLocaleString('en-US')
    : '—';

function safeName(name, side) {
  const base = String(name || '').replace(/[^A-Za-z0-9._-]/g, '-').replace(/-+/g, '-').slice(0, 80);
  return /\.pdf$/i.test(base) && base.length > 4 ? base : `closing-estimate-${side}.pdf`;
}

function summaryText(s, side) {
  const L = [];
  L.push(`Closing cost estimate — ${side.toUpperCase()}`);
  L.push('');
  L.push(`Property        ${s.address || '(no address entered)'}`);
  if (s.slug) L.push(`CMA             /mkt/${s.slug}/`);
  L.push(`Purchase price  ${money(s.price)}`);
  L.push(`Financing       ${s.cash ? 'Cash' : money(s.loan) + ' loan'}`);
  L.push(`Closing date    ${s.closingDate || '—'}`);
  L.push(`Contract        ${s.contract || '—'}`);
  L.push(`Title ¶9(c)     (${s.titleOption || '—'})`);
  L.push(`HOA / COA       ${s.hoa ? 'Yes' : 'No'}`);
  L.push('');
  if (side !== 'seller') {
    L.push(`Buyer closing costs      ${money(s.buyerCosts)}`);
    L.push(`Buyer cash to close      ${money(s.cashToClose)}`);
  }
  if (side !== 'buyer') {
    L.push(`Seller costs             ${money(s.sellerCosts)}`);
    L.push(`Seller net proceeds      ${money(s.netProceeds)}`);
  }
  L.push('');
  L.push('The attached PDF is marked ESTIMATE on every page. Figures are estimates only');
  L.push('and are not a Closing Disclosure or a commitment to any term.');
  return L.join('\n');
}

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 204, headers: CORS, body: '' };
  if (event.httpMethod !== 'POST') return fail(405, 'POST only');

  const key = process.env.RESEND_API_KEY;
  if (!key) return fail(503, 'RESEND_API_KEY is not configured on this site');

  let body;
  try { body = JSON.parse(event.body || '{}'); }
  catch { return fail(400, 'Body must be JSON'); }

  const side = ['buyer', 'seller', 'combined'].includes(body.side) ? body.side : 'combined';
  const b64 = String(body.pdfBase64 || '');
  if (!b64) return fail(400, 'pdfBase64 is required');
  if (!/^[A-Za-z0-9+/=\r\n]+$/.test(b64)) return fail(400, 'pdfBase64 is not valid base64');

  // 4 base64 chars per 3 bytes
  const bytes = Math.floor(b64.replace(/[\r\n=]/g, '').length * 3 / 4);
  if (bytes > MAX_PDF_BYTES) return fail(413, `PDF is ${Math.round(bytes / 1024)}KB — over the 8MB limit`);
  if (Buffer.from(b64.slice(0, 12), 'base64').subarray(0, 4).toString('latin1') !== '%PDF') {
    return fail(400, 'Attachment is not a PDF');
  }

  const summary = body.summary && typeof body.summary === 'object' ? body.summary : {};
  const filename = safeName(body.filename, side);

  // Recipient: internal notify list unless explicitly opened up by env var.
  let to = NOTIFY_TO;
  if (process.env.ESTIMATE_ALLOW_RECIPIENT === 'on' && body.to) {
    const one = String(body.to).trim();
    if (!EMAIL_RE.test(one)) return fail(400, 'That recipient address is not valid');
    to = [one];
  }
  if (!to.length) return fail(503, 'No notify address configured');

  const addr = summary.address ? ` — ${summary.address}` : '';
  const subject = `Closing estimate (${side})${addr}`;

  try {
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from: RESEND_FROM,
        to,
        reply_to: RESEND_REPLY_TO,
        subject,
        text: summaryText(summary, side),
        attachments: [{ filename, content: b64 }]
      })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      console.error('send-estimate: resend failed', res.status, JSON.stringify(data).slice(0, 300));
      return fail(502, `Resend rejected the message (${res.status})`);
    }
    return {
      statusCode: 200,
      headers: CORS,
      body: JSON.stringify({ ok: true, id: data.id, to: to.join(', '), bytes, filename })
    };
  } catch (e) {
    console.error('send-estimate: error', e);
    return fail(500, String((e && e.message) || e));
  }
};

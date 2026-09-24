// netlify/functions/_lib/notify.js
// Minimal Resend sender for functions that do not carry their own (wishlist,
// srqmap, off-market). Same sender and Reply-To as community-lead.

export async function notifyTeam({ subject, lines, to }) {
  const key = process.env.RESEND_API_KEY;
  if (!key) return { skipped: 'RESEND_API_KEY not configured' };
  const recipients = to && to.length ? to
    : (process.env.LEAD_NOTIFY_TO || 'Ryan@Adamson-Group.com').split(',').map((x) => x.trim()).filter(Boolean);
  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      from: process.env.RESEND_FROM || 'The Adamson Group <Info@AdamsonFL.com>',
      to: recipients,
      reply_to: process.env.RESEND_REPLY_TO || 'Ryan@adamson-group.com',
      subject,
      text: lines.filter((x) => x !== null && x !== undefined).join('\n'),
    }),
  });
  if (!res.ok) throw new Error(`resend ${res.status} ${(await res.text()).slice(0, 200)}`);
  return { sent: true };
}

export function cameFromLine(v) {
  const ft = v && v.attribution && v.attribution.first_touch;
  if (!ft) return null;
  const parts = [ft.uc ? `campaign ${ft.uc}` : null, ft.us ? `source ${ft.us}` : null,
    !ft.uc && ft.ref ? `referrer ${ft.ref}` : null, ft.lp ? `landed on ${ft.lp}` : null].filter(Boolean);
  return parts.length ? `Came from: ${parts.join(' | ')}` : null;
}

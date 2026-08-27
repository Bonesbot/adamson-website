// homeplatform-lead-forward.js
// Sends a lead email to Home platform's inbound parser, mimicking the
// IDX Broker lead-notification format exactly (labels, order, spacing).
//
// Usage inside your existing Netlify lead function, after the Supabase
// write and your own Resend notifications:
//
//   import { forwardLeadToHomePlatform } from "./homeplatform-lead-forward.js";
//   await forwardLeadToHomePlatform(lead);
//
// Env vars required:
//   RESEND_API_KEY          - already set for your existing flow
//   HOMEPLATFORM_LEAD_EMAIL - dbyq9omalg2l@leads.homeplatform.com
//   LEAD_FROM_ADDRESS       - a verified sender on your Resend domain,
//                             e.g. leads@adamsonfl.com

const HOMEPLATFORM_LEAD_EMAIL =
  process.env.HOMEPLATFORM_LEAD_EMAIL || "dbyq9omalg2l@leads.homeplatform.com";
const LEAD_FROM_ADDRESS =
  process.env.LEAD_FROM_ADDRESS || "leads@adamsonfl.com";

/**
 * lead = {
 *   firstName: "Jane",
 *   lastName:  "Smith",
 *   email:     "jane@example.com",
 *   phone:     "",                   // optional
 *   message:   "Interested in this property",
 *   sourceUrl: "https://adamsonfl.com/longboat-key/country-club-shores",
 *   listing: {                       // optional - omit for general inquiries
 *     mlsNumber: "A4696535",
 *     price:     "$2,195,000",
 *     address:   "549 Halyard Lane",
 *     city:      "Longboat Key",
 *     state:     "Florida",
 *     zipcode:   "34228",
 *   },
 * }
 */
export function buildIdxStyleBody(lead) {
  const fullName = `${lead.firstName} ${lead.lastName}`.trim();

  // Structure mirrors the IDX Broker notification field-for-field.
  // Parsers key on these exact labels - do not reword or reorder.
  let body = "";
  body += `${fullName} filled out the Contact Form on https://adamsonfl.com.\n`;
  body += `\n`;
  body += `Lead Information\n`;
  body += `First Name: ${lead.firstName}\n`;
  body += `Last Name: ${lead.lastName}\n`;
  body += `Email Address: ${lead.email}\n`;
  body += `Phone: ${lead.phone || ""}\n`;
  body += `\n`;
  body += `The message is as follows:\n`;
  body += `${lead.message || ""}\n`;

  if (lead.listing) {
    body += `\n`;
    body += `\n`;
    body += `Additional Listing Information:\n`;
    body += `MLS # : ${lead.listing.mlsNumber}\n`;
    body += `Price : ${lead.listing.price}\n`;
    body += `Address : ${lead.listing.address}\n`;
    body += `City : ${lead.listing.city}\n`;
    body += `State : ${lead.listing.state}\n`;
    body += `Zipcode : ${lead.listing.zipcode}\n`;
    body += `Message : ${lead.message || ""}\n`;
  }

  return body;
}

export async function forwardLeadToHomePlatform(lead) {
  const body = buildIdxStyleBody(lead);
  const fullName = `${lead.firstName} ${lead.lastName}`.trim();

  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: `AdamsonFL Leads <${LEAD_FROM_ADDRESS}>`,
      to: [HOMEPLATFORM_LEAD_EMAIL],
      // Exact subject template from real IDX Broker lead emails.
      // Likely a parser trigger - do not personalize or reword.
      subject: "The Adamson Group - A lead has contacted you.",
      text: body,
      // Reply-to the lead so any human reading it in the CRM can respond.
      reply_to: lead.email,
    }),
  });

  if (!res.ok) {
    const err = await res.text();
    // Log but do not throw - Home platform forwarding should never
    // break the primary capture path (Supabase + your own alerts).
    console.error("Home platform forward failed:", res.status, err);
    return { ok: false, status: res.status, error: err };
  }

  const data = await res.json();
  return { ok: true, id: data.id };
}

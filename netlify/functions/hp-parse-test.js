// TEMPORARY - Home platform parser-mapping probe. Lets us send controlled
// variant leads through the exact production forwarder to see which body
// sections Home platform's inbound parser actually keeps. Token-gated.
// REMOVE THIS FILE once the field mapping is confirmed.
import { forwardLeadToHomePlatform, buildIdxStyleBody } from "./homeplatform-lead-forward.js";

const TOKEN = "hp-test-7f3a9c2e51d84b06-bonesbot";

export const handler = async (event) => {
  if (event.httpMethod !== "POST") return { statusCode: 405, body: "method not allowed" };
  let b;
  try { b = JSON.parse(event.body || "{}"); } catch { return { statusCode: 400, body: "bad json" }; }
  if (b.token !== TOKEN) return { statusCode: 403, body: "forbidden" };

  const lead = {
    firstName: b.firstName || "HP",
    lastName: b.lastName || "Probe",
    email: b.email,
    phone: b.phone || "",
    message: b.message || "",
    sourceUrl: b.sourceUrl || "",
    listing: b.listing || undefined,
  };
  if (!lead.email) return { statusCode: 400, body: "email required" };

  const res = await forwardLeadToHomePlatform(lead);
  // Echo the exact body sent so the caller can archive what went out.
  return {
    statusCode: 200,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ forward: res, emailBody: buildIdxStyleBody(lead) }),
  };
};

// netlify/functions/str-prefill.js
//
// Looks up a property address in the AdamsonGroup Supabase MLS warehouse (public.raw_listings)
// and returns the facts the STR Deal Analyzer can prefill: beds, baths, sqft, year built, pool,
// list/close price, current tax bill, HOA / condo fees, flood zone, CDD, minimum lease (the
// condo STR killer), and location. Read-only, service role stays server-side.
//
//   GET /.netlify/functions/str-prefill?address=1001 Point of Rocks Rd #310
//     -> { match: true, candidates: n, listing: {...} }   or   { match: false }
//
// Matching: house number + first street word, ILIKE on unparsed_address, Active first then most
// recent. Good enough for a typed address; the page shows what it matched so the user can see it.
//
// Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY. No npm deps.

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type",
  "Content-Type": "application/json",
  "Cache-Control": "private, max-age=300"
};

const FIELDS = [
  "listing_id", "standard_status", "unparsed_address", "city", "postal_code", "subdivision_name",
  "detected_area", "property_sub_type", "property_type", "bedrooms_total", "bathrooms_full",
  "bathrooms_half", "living_area", "lot_size_square_feet", "lot_size_acres", "year_built", "pool_private_yn", "current_price",
  "original_list_price", "close_date", "listing_contract_date", "cumulative_days_on_market",
  "tax_annual_amount", "tax_year", "monthly_hoa_amount", "monthly_condo_fee_amount",
  "association_fee", "association_fee_frequency", "total_annual_fees", "monthly_association_cost",
  "cdd_yn", "tax_other_annual_assessment_amount", "flood_zone_code", "waterfront_yn",
  "minimum_lease", "lease_restrictions_yn", "num_of_own_years_prior_to_lse", "pets_allowed",
  "furnished", "latitude", "longitude", "parcel_number", "list_agent_full_name", "list_office_name",
  "stories_total", "garage_spaces", "building_elevator_yn", "elementary_school"
];

const STATUS_RANK = { Active: 0, Pending: 1, Hold: 2, Closed: 3, Withdrawn: 4, Canceled: 5, Expired: 6 };

function parseAddress(a) {
  const s = String(a || "").trim().replace(/\s+/g, " ");
  const m = s.match(/^(\d+[A-Za-z]?)\s+(?:([NSEW]|North|South|East|West)\.?\s+)?([A-Za-z0-9']+)/);
  if (!m) return null;
  let unit = null;
  const u = s.match(/(?:#|Apt\.?|Unit|Ste\.?|Suite)\s*([A-Za-z0-9-]+)/i);
  if (u) unit = u[1];
  return { number: m[1], dir: m[2] || null, street: m[3], unit };
}

exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers: CORS, body: "" };
  const q = event.queryStringParameters || {};
  const parsed = parseAddress(q.address);
  if (!parsed) return { statusCode: 200, headers: CORS, body: JSON.stringify({ match: false, note: "address not parseable" }) };

  const url = process.env.SUPABASE_URL, key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return { statusCode: 200, headers: CORS, body: JSON.stringify({ match: false, note: "supabase env missing" }) };

  try {
    const pattern = `${parsed.number} %${parsed.street}%`;
    const params = new URLSearchParams({
      select: FIELDS.join(","),
      unparsed_address: `ilike.${pattern}`,
      order: "status_change_timestamp.desc",
      limit: "25"
    });
    const r = await fetch(`${url}/rest/v1/raw_listings?${params.toString()}`, {
      headers: { apikey: key, Authorization: "Bearer " + key }
    });
    if (!r.ok) throw new Error("supabase " + r.status);
    let rows = await r.json();
    if (!Array.isArray(rows) || !rows.length) return { statusCode: 200, headers: CORS, body: JSON.stringify({ match: false, parsed }) };

    // Unit filter when the user typed one; otherwise prefer rows without a unit for SFH addresses.
    if (parsed.unit) {
      const uu = parsed.unit.toLowerCase();
      const withUnit = rows.filter((x) => String(x.unparsed_address || "").toLowerCase().replace(/\s+/g, " ").match(new RegExp(`#\\s*${uu.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(\\b|$)`)));
      if (withUnit.length) rows = withUnit;
    }
    rows.sort((a, b) => (STATUS_RANK[a.standard_status] ?? 9) - (STATUS_RANK[b.standard_status] ?? 9)
      || String(b.close_date || b.listing_contract_date || "").localeCompare(String(a.close_date || a.listing_contract_date || "")));
    const L = rows[0];

    // Derived helpers the page uses directly.
    const monthlyAssoc = L.monthly_association_cost != null ? Number(L.monthly_association_cost)
      : L.monthly_condo_fee_amount != null ? Number(L.monthly_condo_fee_amount)
      : L.monthly_hoa_amount != null ? Number(L.monthly_hoa_amount)
      : L.total_annual_fees != null ? Number(L.total_annual_fees) / 12 : null;
    const ml = String(L.minimum_lease || "");
    const strFriendly = /no minimum|1-7 days|1 week|2 weeks|day/i.test(ml);
    const strBlocked = /month|year|no rent/i.test(ml);

    const out = {
      match: true,
      candidates: rows.length,
      parsed,
      listing: L,
      derived: {
        monthly_association_cost: monthlyAssoc,
        min_lease: ml || null,
        min_lease_flag: strBlocked ? "blocked" : strFriendly ? "ok" : (ml ? "verify" : "unknown"),
        is_condo: /condo|town|villa/i.test(String(L.property_sub_type || "")),
        price_basis: L.standard_status === "Closed" ? "close" : "list"
      }
    };
    return { statusCode: 200, headers: CORS, body: JSON.stringify(out) };
  } catch (e) {
    return { statusCode: 200, headers: CORS, body: JSON.stringify({ match: false, note: String(e.message || e) }) };
  }
};

// netlify/functions/zoning.js
//
// Server-side proxy for Sarasota County GIS zoning + overlay districts + City of Sarasota
// limits. The county ArcGIS server (ags3.scgov.net) is token-secured and does not reliably
// send CORS headers, so browsers hitting it directly render unreliably. This proxy fetches
// server-side (no CORS) and returns clean JSON/GeoJSON, cached at the edge.
//
//   ?mode=area                -> { zoning:<GeoJSON FC>, overlays:<GeoJSON FC> }  (Siesta Key bbox)
//   ?mode=city                -> { city:<GeoJSON FC> }  (City of Sarasota limits, simplified)
//   ?mode=point&lat=..&lon=.. -> { zoning:{...}|null, overlays:[names] }
//
// No npm deps — global fetch (Netlify Node 18+).

const ZON = "https://ags3.scgov.net/server/rest/services/Hosted/CountyZoning/FeatureServer/0";
const OVL = "https://ags3.scgov.net/server/rest/services/Hosted/ZoningOverlayDistrict/FeatureServer/0";
const BBOX = "-82.585,27.235,-82.515,27.335"; // Siesta Key / 34242

function cors(maxAge) {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
    "Cache-Control": "public, max-age=" + maxAge
  };
}
async function getJSON(u) {
  const r = await fetch(u);
  if (!r.ok) throw new Error("gis " + r.status);
  return r.json();
}

exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers: cors(60), body: "" };
  const q = event.queryStringParameters || {};
  const mode = q.mode || "area";

  try {
    if (mode === "point") {
      const lat = parseFloat(q.lat), lon = parseFloat(q.lon);
      if (isNaN(lat) || isNaN(lon)) return { statusCode: 400, headers: cors(0), body: JSON.stringify({ error: "lat/lon required" }) };
      const g = encodeURIComponent(lon + "," + lat);
      const base = "/query?geometry=" + g + "&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects&returnGeometry=false&f=json&outFields=";
      const [z, o] = await Promise.all([
        getJSON(ZON + base + encodeURIComponent("zoningcode,zoningdesignation,zoninggroup,municipality")),
        getJSON(OVL + base + encodeURIComponent("districtname,districttype"))
      ]);
      const zoning = (z.features && z.features[0]) ? z.features[0].attributes : null;
      const overlays = (o.features || []).map(f => f.attributes.districtname).filter(Boolean);
      return { statusCode: 200, headers: cors(3600), body: JSON.stringify({ zoning, overlays }) };
    }

    if (mode === "city") {
      // City of Sarasota limits = CountyZoning polygons where municipality='CS'. Simplified for display.
      const u = ZON + "/query?where=" + encodeURIComponent("municipality='CS'") +
        "&outFields=" + encodeURIComponent("zoningcode") +
        "&returnGeometry=true&outSR=4326&f=geojson&maxAllowableOffset=0.0003&geometryPrecision=5";
      const city = await getJSON(u);
      return { statusCode: 200, headers: cors(2592000), body: JSON.stringify({ city }) }; // 30d
    }

    // mode = area (default)
    const base = "/query?geometry=" + BBOX + "&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&returnGeometry=true&f=geojson&outFields=";
    const [zoning, overlays] = await Promise.all([
      getJSON(ZON + base + encodeURIComponent("zoningcode,zoningdesignation,zoninggroup,municipality")),
      getJSON(OVL + base + encodeURIComponent("districtname,districttype"))
    ]);
    return { statusCode: 200, headers: cors(604800), body: JSON.stringify({ zoning, overlays }) };
  } catch (e) {
    return { statusCode: 502, headers: cors(0), body: JSON.stringify({ error: String(e.message || e) }) };
  }
};

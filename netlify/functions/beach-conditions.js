// netlify/functions/beach-conditions.js
//
// Tiny aggregator behind the landing-page "beach strip": today's high/low from
// the National Weather Service + red-tide indicators from Mote Marine
// Laboratory's Beach Conditions Reporting System (visitbeaches.org).
//
// GET /.netlify/functions/beach-conditions?grid=TBW/70,67&beach=2
//   grid  — api.weather.gov gridpoint       (default: Siesta Key)
//   beach — visitbeaches.org beach id        (default: 2 = Siesta Key Beach)
//
// Template note: a cloned community page anywhere on the Gulf just passes its
// own grid/beach via the strip's data attributes — no code change here.
//
// Response: { hi, lo, unit, redTide: { status: 'clear'|'reported', detail },
//             asOf } — every leg is best-effort; partial data is fine. CDN
// caches for 30 min so the upstream APIs see a handful of hits a day, tops.

const NWS_UA = 'adamsonfl.com beach strip (ryan@adamson-group.com)';
const GRID_RE = /^[A-Z]{3}\/\d{1,3},\d{1,3}$/;

// Mote BCRS report parameters that indicate red tide / beach hazards. A null,
// empty or "none"-ish value means nothing reported.
const HAZARD_PARAMS = ['Respiratory Irritation', 'Dead Fish', 'Red Drift Algae'];
const CLEAR_VALUES = new Set(['', 'none', 'no', 'n/a', 'na', 'clear', 'normal', 'low']);

async function nwsHiLo(grid) {
  const res = await fetch(`https://api.weather.gov/gridpoints/${grid}/forecast`, {
    headers: { 'User-Agent': NWS_UA, Accept: 'application/geo+json' },
  });
  if (!res.ok) throw new Error(`nws ${res.status}`);
  const periods = (await res.json()).properties.periods || [];
  const day = periods.find((p) => p.isDaytime);
  const night = periods.find((p) => !p.isDaytime);
  return {
    hi: day ? day.temperature : null,
    lo: night ? night.temperature : null,
    unit: (day || night || {}).temperatureUnit || 'F',
  };
}

async function moteRedTide(beachId) {
  const query = `{ beach(id: ${Number(beachId)}) { name lastThreeDaysOfReports {
    createdAt reportParameters { value parameter { name } } } } }`;
  const res = await fetch('https://api.visitbeaches.org/graphql', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error(`mote ${res.status}`);
  const beach = (await res.json()).data?.beach;
  const report = beach?.lastThreeDaysOfReports?.[0];
  if (!report) return { status: 'clear', detail: 'no recent report' };

  const flagged = [];
  for (const rp of report.reportParameters || []) {
    const name = rp.parameter?.name;
    if (!HAZARD_PARAMS.includes(name)) continue;
    const val = String(rp.value ?? '').trim();
    if (val && !CLEAR_VALUES.has(val.toLowerCase())) flagged.push(`${name}: ${val}`);
  }
  return flagged.length
    ? { status: 'reported', detail: flagged.join('; '), reportedAt: report.createdAt }
    : { status: 'clear', detail: null, reportedAt: report.createdAt };
}

exports.handler = async (event) => {
  const qs = event.queryStringParameters || {};
  const grid = GRID_RE.test(qs.grid || '') ? qs.grid : 'TBW/70,67';
  const beach = /^\d{1,5}$/.test(qs.beach || '') ? qs.beach : '2';

  const [nws, mote] = await Promise.allSettled([nwsHiLo(grid), moteRedTide(beach)]);
  if (nws.status === 'rejected') console.warn('beach-conditions: nws —', String(nws.reason));
  if (mote.status === 'rejected') console.warn('beach-conditions: mote —', String(mote.reason));

  const body = {
    hi: nws.status === 'fulfilled' ? nws.value.hi : null,
    lo: nws.status === 'fulfilled' ? nws.value.lo : null,
    unit: nws.status === 'fulfilled' ? nws.value.unit : 'F',
    redTide: mote.status === 'fulfilled' ? mote.value : null,
    asOf: new Date().toISOString(),
  };

  const total = nws.status === 'rejected' && mote.status === 'rejected';
  return {
    statusCode: total ? 502 : 200,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': 'public, max-age=900, s-maxage=1800',
    },
    body: JSON.stringify(total ? { error: 'all sources unavailable' } : body),
  };
};

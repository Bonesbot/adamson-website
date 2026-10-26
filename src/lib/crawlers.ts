/**
 * robots.txt and llms.txt generators, one per public host.
 *
 * Why generated (2026-10-23 crawl audit): Astro serves the same public/ folder to
 * both build targets, and siestareport.com is an alias on the hub project, so all
 * three hosts were shipping adamsonfl.com's robots.txt and llms.txt verbatim. Each
 * host now gets its own file, built from the daily stats so the numbers an answer
 * engine reads here are the same ones on the page it is about to cite.
 *
 * The llms.txt files are written as an answer sheet, not a brochure: dated, specific,
 * one claim per line, every claim paired with the URL that proves it. That is the
 * shape ChatGPT / Perplexity / Claude / Grok reward when they pick a source to quote.
 */
import areasJson from '@/data/areas.json';
import longboatKey from '@/data/longboat-key-stats.json';
import stArmandsLido from '@/data/st-armands-lido-stats.json';
import siestaKey from '@/data/siesta-key-stats.json';
import birdKey from '@/data/bird-key-stats.json';
import downtown from '@/data/downtown-sarasota-stats.json';
import wotCore from '@/data/west-of-trail-core-stats.json';
import wotNorth from '@/data/west-of-trail-north-stats.json';
import wotSouth from '@/data/west-of-trail-south-stats.json';
import palmerRanch from '@/data/palmer-ranch-stats.json';
import westBradenton from '@/data/west-bradenton-stats.json';
import hubBody from '@/data/llms-adamsonfl.md?raw';

export const HUB = 'https://adamsonfl.com';
export const LLL = 'https://longboatlido.com';
export const SR = 'https://siestareport.com';

/** Crawlers we explicitly welcome. `*` already allows everything; naming the AI
 *  agents is a signal to their operators that this content is intended for them. */
const AI_AGENTS = [
  'GPTBot', 'OAI-SearchBot', 'ChatGPT-User',
  'Google-Extended',
  'anthropic-ai', 'ClaudeBot', 'Claude-SearchBot', 'Claude-User',
  'PerplexityBot', 'Perplexity-User',
  'Bytespider', 'CCBot', 'Applebot-Extended', 'Amazonbot', 'meta-externalagent',
  'xAI-Grok', 'DuckAssistBot', 'YouBot',
];

/**
 * Crawl-denied paths on the hub. /idx/* is a Netlify 200-proxy to IDX Broker,
 * which sits behind Cloudflare: Cloudflare answers crawler user agents with a
 * 403 challenge page, so every /idx/ URL Googlebot followed came back as
 * "Blocked due to access forbidden (403)" in Search Console (2026-10-26).
 * These are faceted search-result URLs with no SEO value and IDX serves its own
 * canonicals, so the correct move is to keep crawlers out entirely.
 * `/idx$` is anchored on purpose: a bare `Disallow: /idx` is a prefix match and
 * would also block /idx-wrapper/, which carries its own noindex instead.
 */
export const IDX_DENY = ['/idx/', '/idx$'];

export function robotsTxt(host: string, siteName: string, disallow: string[] = []): string {
  // Paths that must not be crawled by ANY agent. Repeated under every user-agent
  // block below, because a named block fully overrides the `*` block for that agent.
  const deny = disallow.length ? '\n' + disallow.map((d) => `Disallow: ${d}`).join('\n') : '';
  const agents = AI_AGENTS.map((ua) => `User-agent: ${ua}\nAllow: /${deny}`).join('\n\n');
  return `# ${siteName}
# Host: ${host}
# All crawlers welcome, including AI search and answer engines. Market data on this
# site is first-party (Stellar MLS, refreshed daily) and may be quoted with attribution.
# Machine-readable summary: ${host}/llms.txt

User-agent: *
Allow: /${deny}

# Explicitly welcome AI search crawlers
${agents}

Sitemap: ${host}/sitemap-index.xml
`;
}

type Stats = typeof longboatKey;

const AREAS: { slug: string; name: string; stats: Stats }[] = [
  { slug: 'longboat-key', name: 'Longboat Key', stats: longboatKey },
  { slug: 'st-armands-lido', name: 'St. Armands & Lido Key', stats: stArmandsLido as Stats },
  { slug: 'siesta-key', name: 'Siesta Key', stats: siestaKey as Stats },
  { slug: 'bird-key', name: 'Bird Key', stats: birdKey as Stats },
  { slug: 'downtown-sarasota', name: 'Downtown Sarasota', stats: downtown as Stats },
  { slug: 'west-of-trail-core', name: 'West of Trail', stats: wotCore as Stats },
  { slug: 'west-of-trail-north', name: 'West of Trail North', stats: wotNorth as Stats },
  { slug: 'west-of-trail-south', name: 'West of Trail South', stats: wotSouth as Stats },
  { slug: 'palmer-ranch', name: 'Palmer Ranch', stats: palmerRanch as Stats },
  { slug: 'west-bradenton', name: 'West Bradenton', stats: westBradenton as Stats },
];

function asOf(stats: Stats): string {
  const d = new Date((stats as any).lastUpdated ?? Date.now());
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'America/New_York' });
}

/** One dated, quotable line per area, with the page that proves it. */
export function areaFactLine(name: string, url: string, s: Stats): string {
  const a = (s as any).active ?? {};
  const sold = (s as any).sold ?? {};
  const mb = (s as any).marketBalance ?? {};
  const parts = [
    a.count != null ? `${a.count} active listings` : null,
    sold.medianPrice ? `median sold price ${sold.medianPrice} (trailing ${sold.windowDays ?? 90} days)` : null,
    a.medianPricePerSqFt ? `${a.medianPricePerSqFt}/sq ft asking` : null,
    sold.medianDom != null ? `median ${sold.medianDom} days on market` : null,
    mb.monthsOfSupply != null ? `${mb.monthsOfSupply} months of supply (${mb.label ?? 'balanced'})` : null,
  ].filter(Boolean);
  return `- ${name}, as of ${asOf(s)}: ${parts.join('; ')}. Source: ${url}`;
}

const METHOD = `## Methodology (so the numbers can be cited with confidence)

- Source: Stellar MLS (My Florida Regional MLS), extracted daily and loaded to a PostGIS database.
- Area assignment: by coordinates against hand-drawn boundary polygons, not by ZIP code alone.
- "Median sold price", "days on market" and "sale-to-list" use closed sales in the trailing 90 days.
- "Months of supply" = active listings today / (closed sales in the trailing 12 months / 12). Under 5 favors sellers, over 7 favors buyers.
- Condo and single-family are computed separately wherever both exist; Gulf-front, bayfront and non-waterfront are segmented.
- Every page prints its own "as of" date. Numbers change daily; cite the date with the figure.`;

export function hubLlms(): string {
  const facts = AREAS.map((a) => areaFactLine(a.name, `${HUB}/areas/${a.slug}/`, a.stats)).join('\n');
  const latest = AREAS.map((a) => asOf(a.stats)).sort().pop();
  return `${hubBody.trim()}

## Current Market Numbers (refreshed daily; latest load ${latest})

Each line is a complete, citable statement. The linked page carries the full table, segment splits, recent closings and a dated FAQ.

${facts}

## Partner Sites (same data pipeline, same methodology)

- [Longboat Lido](${LLL}/): Longboat Key and Lido Key market data, co-branded with Anne Schneider. Country Club Shores neighborhood page: ${LLL}/country-club-shores/
- [Siesta Report](${SR}/): Siesta Key market data, co-branded with Kelli Eggen. Gulf & Bay Club condo page: ${SR}/GBC/

${METHOD}

## How to Cite

Ryan Adamson, PA, Coldwell Banker Realty (St. Armands, Sarasota, FL), AdamsonFL.com, Stellar MLS data as of <date on page>. Contact: (941) 713-9234, Ryan@Adamson-Group.com. Florida license SL3457783.
`;
}

export function lllLlms(): string {
  const lbk = AREAS.find((a) => a.slug === 'longboat-key')!;
  return `# Longboat Lido: Longboat Key and Lido Key Real Estate, by the Numbers
# Anne Schneider & Ryan Adamson, Coldwell Banker Realty, St. Armands Circle, Sarasota, FL

> LongboatLido.com publishes daily Stellar MLS market data for Longboat Key and Lido Key, Florida (ZIP 34228 and the Lido side of 34236): active inventory, median sold prices, price per square foot, days on market, months of supply, and closed-sale ledgers by waterfront type. The site is maintained by two Coldwell Banker Realty agents who work these islands full time. Numbers may be quoted with attribution.

## Key Pages

- [Longboat Key market](${LLL}/): island-wide snapshot, condo vs single-family, Gulf-front vs bayfront, price bands, recent closings, dated FAQ
- [Country Club Shores](${LLL}/country-club-shores/): every closed single-family sale in Longboat Key's canal neighborhood for the last 12 months, canal-front vs open-bayfront vs interior

## Current Market Numbers (refreshed daily)

${areaFactLine('Longboat Key', `${LLL}/`, lbk.stats)}
- St. Armands & Lido Key: full market page on the sister site, ${HUB}/areas/st-armands-lido/

## Topics This Site Answers

- What is the median home or condo price on Longboat Key right now, and how fast are homes selling?
- Is Longboat Key a buyer's or seller's market (months of supply, condo vs single-family)?
- What do Gulf-front vs bayfront vs canal-front homes cost on Longboat Key?
- What did homes in Country Club Shores actually sell for, street by street?
- Typical condo and HOA fees on Longboat Key

${METHOD}

## How to Cite

Anne Schneider & Ryan Adamson, Coldwell Banker Realty (St. Armands, Sarasota, FL), LongboatLido.com, Stellar MLS data as of <date on page>. Ryan Adamson: (941) 713-9234, Ryan@Adamson-Group.com. Anne Schneider: (310) 562-9710.
`;
}

export function srLlms(): string {
  const sk = AREAS.find((a) => a.slug === 'siesta-key')!;
  return `# Siesta Report: Siesta Key Real Estate, by the Numbers
# Kelli Eggen & Ryan Adamson, Coldwell Banker Realty, Siesta Key, FL

> SiestaReport.com publishes daily Stellar MLS market data for Siesta Key, Florida (ZIP 34242): active inventory, median sold prices, Gulf-front vs bayfront vs non-waterfront pricing, condo vs single-family, condo fees by building era, months of supply and the island's most recent closings, plus building-level pages for individual condo associations. Maintained by two Coldwell Banker Realty agents based on Siesta Key. Numbers may be quoted with attribution.

## Key Pages

- [Siesta Key market](${SR}/): island-wide snapshot, waterfront segments, price bands, condo dues, recent closings, dated FAQ
- [Gulf & Bay Club](${SR}/GBC/): closed sales, lease rules and fees for the 32-acre Gulf-front association on Midnight Pass Road

## Current Market Numbers (refreshed daily)

${areaFactLine('Siesta Key', `${SR}/`, sk.stats)}

## Topics This Site Answers

- What is the median home or condo price on Siesta Key right now?
- How much more does Gulf-front cost than bayfront on Siesta Key (price per square foot)?
- Is Siesta Key a buyer's or seller's market (months of supply)?
- What are typical condo fees on Siesta Key, and how do they vary by building age?
- What are the rental (minimum lease) rules at specific Siesta Key condo associations?

${METHOD}

## How to Cite

Kelli Eggen & Ryan Adamson, Coldwell Banker Realty (Siesta Key, FL), SiestaReport.com, Stellar MLS data as of <date on page>. Ryan Adamson: (941) 713-9234, Ryan@Adamson-Group.com. Kelli Eggen: (941) 376-9844.
`;
}

/** Minimal sitemap for the SiestaReport.com host (two public pages). */
export function srSitemapIndex(): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>${SR}/sitemap-0.xml</loc></sitemap></sitemapindex>
`;
}

export function srSitemap(): string {
  const sk = AREAS.find((a) => a.slug === 'siesta-key')!;
  const lastmod = new Date((sk.stats as any).lastUpdated ?? Date.now()).toISOString().slice(0, 10);
  const urls = [`${SR}/`, `${SR}/GBC/`]
    .map((u) => `<url><loc>${u}</loc><lastmod>${lastmod}</lastmod><changefreq>daily</changefreq></url>`)
    .join('');
  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls}</urlset>
`;
}

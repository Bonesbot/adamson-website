/**
 * Shared SEO/GEO helpers used by every layout (hub, LongboatLido, SiestaReport).
 *
 * Why these exist (2026-10-23 crawl audit):
 *  - Netlify 301s `/path` -> `/path/` (directory output), and the sitemap lists the
 *    slashed form, but several pages passed a hand-written canonical WITHOUT the
 *    slash. Bing then saw a canonical that redirects and left those pages
 *    "Discovered but not crawled" (Rosewood, Ritz, Mira Mar, all listings).
 *  - Bing flags meta descriptions outside ~25-160 chars as an SEO/GEO error, and
 *    most pages were 170-360 chars. AI answer engines also quote the description
 *    verbatim far more often than the body, so it must be a complete, citable claim.
 */

/** Hard ceiling Bing accepts without a "too long" flag. Keep a little headroom. */
export const DESCRIPTION_MAX = 155;

/** Make a canonical URL match the form Netlify actually serves: trailing slash on
 *  extension-less paths, no query/hash. `https://x.com/foo?a=1` -> `https://x.com/foo/`. */
export function canonicalize(url: string): string {
  try {
    const u = new URL(url);
    u.search = '';
    u.hash = '';
    const last = u.pathname.split('/').pop() ?? '';
    if (u.pathname !== '/' && !u.pathname.endsWith('/') && !last.includes('.')) {
      u.pathname += '/';
    }
    return u.toString();
  } catch {
    return url;
  }
}

/** Clamp a description to DESCRIPTION_MAX on a clause/word boundary. A backstop:
 *  every page should ship a description that already fits, so this never fires. */
export function clampDescription(text: string, max = DESCRIPTION_MAX): string {
  const t = text.replace(/\s+/g, ' ').trim();
  if (t.length <= max) return t;
  const cut = t.slice(0, max - 1);
  const boundary = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('; '), cut.lastIndexOf(', '), cut.lastIndexOf(' '));
  const kept = boundary > max * 0.6 ? cut.slice(0, boundary) : cut;
  return kept.replace(/[\s,;:]+$/, '') + '…';
}

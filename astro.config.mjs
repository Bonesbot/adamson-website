import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';
import sitemap from '@astrojs/sitemap';
import mdx from '@astrojs/mdx';

// One repo, two sites. SITE picks the build target:
//   (unset) / 'adamsonfl' -> the AdamsonFL.com hub (src/)
//   'lll'                 -> LongboatLido.com, the Anne & Ryan co-brand (src-lll/)
// The Netlify project for longboatlido.com sets SITE=lll in its build environment;
// the adamsonfl.com project sets nothing and builds exactly as before.
// Shared components/layouts/data stay in src/ and are reached via the '@' alias
// (tsconfig paths), which always points at src/ regardless of build target.
//
// SiestaReport.com is NOT a third build: it is a domain alias on the adamsonfl.com
// Netlify project, served by host-scoped rewrites in public/_redirects. Its
// robots.txt / llms.txt / sitemap are therefore emitted by the hub build under
// src/pages/siesta-report/ and rewritten onto that host (see _redirects).
const SITE = process.env.SITE ?? 'adamsonfl';

const SITE_URLS = {
  adamsonfl: 'https://adamsonfl.com',
  lll: 'https://longboatlido.com',
};

// Pages that must never appear in a sitemap. Listing a noindex page in the
// sitemap sends Google/Bing contradictory signals ("Excluded by noindex" errors).
const SITEMAP_EXCLUDE = {
  adamsonfl: [
    // SRQMAP-HIDDEN 2026-09-02: keep the map pages out while hidden. Remove to restore.
    /\/(srqmap|srq-map)\/?$/i,
    // SiestaReport.com pages are served on that host; they get their own sitemap
    // (src/pages/siesta-report/sitemap-*.xml.ts) and must not be listed as hub URLs.
    /\/siesta-report(\/.*)?$/i,
    // Form thank-you / receipt pages, the IDX wrapper shell, standalone lead forms
    // and the voice assistant: reachable, but nothing a search result should land on.
    /\/(thank-you|dream-home-received|idx-wrapper|request-showing|home-platform|voice)\/?$/i,
  ],
  lll: [
    /\/thank-you\/?$/i,
  ],
};

export default defineConfig({
  site: SITE_URLS[SITE] ?? SITE_URLS.adamsonfl,
  srcDir: SITE === 'lll' ? './src-lll' : './src',
  integrations: [
    tailwind(),
    sitemap({
      filter: (page) => !(SITEMAP_EXCLUDE[SITE] ?? SITEMAP_EXCLUDE.adamsonfl).some((re) => re.test(page)),
    }),
    mdx(),
  ],
  output: 'static',
  build: {
    inlineStylesheets: 'auto',
  },
  vite: {
    build: {
      cssMinify: true,
    },
  },
});

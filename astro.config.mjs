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
const SITE = process.env.SITE ?? 'adamsonfl';

const SITE_URLS = {
  adamsonfl: 'https://adamsonfl.com',
  lll: 'https://longboatlido.com',
};

export default defineConfig({
  site: SITE_URLS[SITE] ?? SITE_URLS.adamsonfl,
  srcDir: SITE === 'lll' ? './src-lll' : './src',
  integrations: [
    tailwind(),
    sitemap({
      // SRQMAP-HIDDEN 2026-09-02: keep the map pages out of the sitemap while hidden.
      // Remove the filter to restore.
      filter: (page) => !/\/(srqmap|srq-map)\/?$/i.test(page),
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

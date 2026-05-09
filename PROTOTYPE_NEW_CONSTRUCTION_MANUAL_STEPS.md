# Prototype — Manual Steps Ryan Needs to Apply

Two tiny edits the Cowork sandbox couldn't apply reliably (the mount silently truncated writes to pre-existing files at their original byte count). Both are 30-second changes you can do in your editor.

---

## 1. Add the sitemap filter to `astro.config.mjs`

This excludes every `/new-construction/*` URL from `sitemap-index.xml` so search engines never see the prototype URLs even if someone shares a link. (The `noIndex` meta tag on each prototype page is in place — this is belt-and-suspenders.)

**Open `astro.config.mjs` and change line 10 from:**

```js
    sitemap(),
```

**to:**

```js
    sitemap({
      filter: (page) => !page.includes('/new-construction/'),
    }),
```

That's it. Full file should look like:

```js
import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';
import sitemap from '@astrojs/sitemap';
import mdx from '@astrojs/mdx';

export default defineConfig({
  site: 'https://adamsonfl.com',
  integrations: [
    tailwind(),
    sitemap({
      filter: (page) => !page.includes('/new-construction/'),
    }),
    mdx(),
  ],
  output: 'static',
  build: { inlineStylesheets: 'auto' },
  vite: { build: { cssMinify: true } },
});
```

After build, confirm: `dist/sitemap-0.xml` should NOT contain any `/new-construction/` URLs.

---

## 2. Verify the prototype builds

```bash
cd C:\Users\Bones\automation\AG_website
npm install
npm run build
npm run dev
```

Then open:

- http://localhost:4321/new-construction
- http://localhost:4321/new-construction/downtown-sarasota
- http://localhost:4321/new-construction/barrier-islands
- http://localhost:4321/new-construction/the-owen-sarasota
- http://localhost:4321/new-construction/rosewood-residences-lido-key
- http://localhost:4321/new-construction/the-ritz-carlton-residences-sarasota
- http://localhost:4321/new-construction/amara-sarasota (stub example)

Every page should render with:
- Orange "DRAFT — PROTOTYPE" banner at the top
- `<meta name="robots" content="noindex, nofollow">` in the page source
- Existing AdamsonFL.com brand styling (dark backgrounds, CBGL blue + gold, Playfair display headings)

If any page errors out, the most likely cause is a missing image path under `/public/images/new-construction/`. The pages reference `[slug]-hero.jpg` and `[slug]-card.jpg` per project — they degrade gracefully to a colored block when missing, but Astro might warn.

---

## 3. (Optional, defensive) — confirm `package.json` is intact

The same mount issue truncated `package.json` mid-build during this session. I restored it via Write and it parses as valid JSON, but worth verifying:

```bash
node -e "console.log(JSON.parse(require('fs').readFileSync('package.json')))"
```

Should print the package object cleanly. If it errors, run `git checkout HEAD -- package.json` to restore from your last commit.

---

## 4. (When you're ready to flip the prototype LIVE)

See `PROTOTYPE_NEW_CONSTRUCTION_README.md` "To flip live" section. Brief version:

1. Remove `noIndex={true}` from every `src/pages/new-construction/*.astro` page (4 files)
2. Remove every `<DraftBanner />` import + usage (4 pages, 1 component to delete)
3. Add the "New Construction" mega-menu item to `src/components/layout/Header.astro` per spec §3
4. Build, deploy, submit updated sitemap to Google Search Console + Bing Webmaster Tools
5. Run the AEO audit playbook (`AEO_AUDIT_PLAYBOOK.md`) against the live `/new-construction/*` URLs

---

## Sandbox mount issue — for future sessions

In this Cowork session, writes to **pre-existing** files in `automation\AG_website` got silently truncated to the file's original byte count by the sandbox mount. New files write fine. Edits that don't grow the file's byte count also work.

This matches a known recurring issue (`feedback_git_via_cowork_sandbox.md` in memory). For pre-existing-file edits where the new content is larger than the original, the workaround is either:
- Apply the edit manually in the editor (this file documents two such cases), or
- Use the GitHub Contents API + pure-Python mutation pattern from prior sessions.

This had no effect on the prototype work itself — every new file landed cleanly. Only the two tiny edits above (and one near-miss on `package.json`) were impacted.

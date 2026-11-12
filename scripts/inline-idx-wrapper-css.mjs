// Runs after `astro build` (npm postbuild). IDX Broker keeps its own saved copy of
// /idx-wrapper/ and serves every IDX page inside it. If that copy links hashed
// stylesheets (/_astro/<name>.<hash>.css), the next build that renames one leaves
// IDX pages unstyled until IDX Broker refreshes its copy. So the wrapper's
// stylesheets are folded into the page itself: what IDX saves is self-contained.
import { readFileSync, writeFileSync, existsSync } from 'node:fs';

const PAGE = 'dist/idx-wrapper/index.html';
if (!existsSync(PAGE)) { console.log('inline-idx-wrapper-css: no wrapper in this build, skipped'); process.exit(0); }

let html = readFileSync(PAGE, 'utf8');
let count = 0, bytes = 0;
html = html.replace(/<link\b[^>]*>/g, (tag) => {
  if (!/rel=["']?stylesheet/i.test(tag)) return tag;
  const href = (tag.match(/href=["']([^"']+)["']/) || [])[1] || '';
  if (!/^\/_astro\/[^/]+\.css$/.test(href)) return tag;   // leave CDN links (Font Awesome, Google Fonts) alone
  const css = readFileSync('dist' + href, 'utf8');
  if (/url\(\s*["']?\.{1,2}\//.test(css)) throw new Error(`inline-idx-wrapper-css: ${href} has relative url() paths that would break once inlined`);
  count++; bytes += css.length;
  return `<style data-from="${href}">${css.replace(/<\/style/gi, '<\\/style')}</style>`;
});
writeFileSync(PAGE, html);
console.log(`inline-idx-wrapper-css: inlined ${count} stylesheet(s), ${Math.round(bytes / 1024)} KB, into ${PAGE}`);
if (/href=["']\/_astro\/[^"']+\.css/.test(html)) throw new Error('inline-idx-wrapper-css: a /_astro stylesheet link is still in the wrapper');

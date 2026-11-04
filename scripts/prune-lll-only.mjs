// Runs after `astro build` (npm postbuild). public/ ships to BOTH builds, so
// pages that belong to longboatlido.com only are pruned from the hub's dist.
// The hub then has no file at the path and the host-scoped 301 in netlify.toml
// fires cleanly (Netlify serves an existing index.html ahead of a redirect on
// the bare directory URL, even with force = true).
import { rmSync, existsSync } from 'node:fs';

const SITE = process.env.SITE ?? 'adamsonfl';
const LLL_ONLY = ['dist/mkt/501-gunwale'];

if (SITE !== 'lll') {
  for (const p of LLL_ONLY) {
    if (existsSync(p)) { rmSync(p, { recursive: true, force: true }); console.log(`prune-lll-only: removed ${p} from the ${SITE} build`); }
  }
}

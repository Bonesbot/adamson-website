// One-shot: load Zillow's ZIP forecast into Supabase forecast_zip right now, without
// waiting for the 1st/15th schedule. Same code path as the Netlify function.
//   node scripts/seed_zhvf.cjs          (reads AG_website/.env for SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)
// Prereq: supabase/sql/2026-09-22_forecast_zip.sql has been run in the SQL editor.
const fs = require('fs'), path = require('path');
const envPath = path.join(__dirname, '..', '.env');
if (fs.existsSync(envPath)) for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
  const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/); if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
}
// The repo is "type":"module" but Netlify functions are CommonJS; compile the function as CJS explicitly.
const Module = require('module'); const fnPath = path.join(__dirname, '..', 'netlify', 'functions', 'zhvf-refresh.js');
const m = new Module(fnPath + '.cjs', module); m.filename = fnPath + '.cjs'; m.paths = Module._nodeModulePaths(path.dirname(fnPath));
m._compile(fs.readFileSync(fnPath, 'utf8'), m.filename);
m.exports.handler().then(r => { console.log(r.statusCode, r.body); process.exit(r.statusCode === 200 ? 0 : 1); })
  .catch(e => { console.error('seed_zhvf failed:', e.message); process.exit(1); });

// Refresh the baked-in sunspots in index.html from NOAA SWPC's daily solar
// regions feed. Run weekly by .github/workflows/update-sunspots.yml (also
// runnable locally: node tools/update-sunspots.mjs).
//
// What it rewrites:
//   - the REGIONS table between the SUNSPOT-DATA:BEGIN/END markers
//   - the SUN_L0 calibration line (SUNSPOT-CAL): central-meridian Carrington
//     longitude at the observation epoch, derived from the same entries
//     (for every region, carrington_longitude + longitude == L0; the feed's
//     longitude field is east-positive)
//   - the amber "build N" footer (+1), so cache-busting keeps working
//
// If the freshest NOAA data matches what's already baked in, it exits
// without touching the file and the workflow skips the commit.

import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const FEED = 'https://services.swpc.noaa.gov/json/solar_regions.json';
const FILE = join(dirname(fileURLToPath(import.meta.url)), '..', 'index.html');

const rows = await (await fetch(FEED)).json();
if (!Array.isArray(rows) || !rows.length) throw new Error('feed empty or not an array');

// freshest observation day only, one entry per region, must have a real
// on-disc position (location string) and a measured area
const latest = rows.map(r => r.observed_date).sort().at(-1);
if (!/^\d{4}-\d{2}-\d{2}$/.test(latest)) throw new Error('bad observed_date: ' + latest);
const seen = new Set();
const regs = rows.filter(r =>
  r.observed_date === latest && r.region != null && r.location &&
  r.latitude != null && r.carrington_longitude != null && (r.area ?? 0) > 0 &&
  !seen.has(r.region) && seen.add(r.region));

// sanity: a plausible sun has 0..30 numbered regions at low-mid latitudes
if (regs.length > 30) throw new Error('implausible region count: ' + regs.length);
for (const r of regs) if (Math.abs(r.latitude) > 60) throw new Error('implausible latitude: ' + JSON.stringify(r));

// calibration: every region independently gives L0 = carrLon + eastLon.
// They must agree (same observation) - use a circular mean, abort on spread.
let L0line;
const src = readFileSync(FILE, 'utf8');
if (regs.length) {
  const cands = regs.map(r => ((r.carrington_longitude + r.longitude) % 360 + 360) % 360);
  const rad = Math.PI / 180;
  const L0 = Math.round(((Math.atan2(
    cands.reduce((a, c) => a + Math.sin(c * rad), 0),
    cands.reduce((a, c) => a + Math.cos(c * rad), 0)) / rad) % 360 + 360) % 360);
  for (const c of cands) {
    const d = Math.abs(((c - L0) % 360 + 540) % 360 - 180);
    if (d > 4) throw new Error(`L0 candidates disagree: ${cands.join(', ')}`);
  }
  const [y, m, d] = latest.split('-').map(Number);
  L0line = `const SUN_L0 = ${L0}, SUN_L0_EPOCH = Date.UTC(${y}, ${m - 1}, ${d}); ` +
    `// SUNSPOT-CAL auto-updated: NOAA ${latest}, CM Carrington lon ${L0}`;
} else {
  // spotless sun: nothing to calibrate against; the existing L0/epoch keeps
  // the rotation phase correct indefinitely, so leave the line alone
  L0line = null;
}

// bipolar if the McIntosh class opens with B/C/D/E/F (A and H are unipolar)
const lines = regs.map((r, i) => {
  const bip = /^[BCDEF]/i.test(r.spot_class || '');
  const f = (n, w) => String(n).padStart(w);
  return `    [${f(r.region, 4)}, ${f(r.latitude, 3)}, ${f(r.carrington_longitude, 3)}, ` +
    `${f(r.area, 3)}, ${bip ? 'true ' : 'false'}]${i < regs.length - 1 ? ',' : ' '}   // ${r.spot_class || '?'}`;
});
const dataBlock = `  /* SUNSPOT-DATA:BEGIN observed ${latest} */\n` +
  `  const REGIONS = [\n${lines.join('\n')}\n  ];\n  /* SUNSPOT-DATA:END */`;

const dataRe = /  \/\* SUNSPOT-DATA:BEGIN[\s\S]*?SUNSPOT-DATA:END \*\//;
const calRe = /const SUN_L0 = .*\/\/ SUNSPOT-CAL.*/;
if (!dataRe.test(src)) throw new Error('SUNSPOT-DATA markers not found in index.html');
if (!calRe.test(src)) throw new Error('SUNSPOT-CAL line not found in index.html');

let out = src.replace(dataRe, dataBlock);
if (L0line) out = out.replace(calRe, L0line);

if (out === src) {
  console.log(`no change: baked data already matches NOAA ${latest} (${regs.length} regions)`);
  process.exit(0);
}

// bump the build footer so ?v= cache-busting stays honest
out = out.replace(/(<b style="[^"]*">build )(\d+)(<\/b>)/, (_, a, n, b) => a + (+n + 1) + b);
if (out === src.replace(dataRe, dataBlock) && !/build \d+/.test(src)) throw new Error('build footer not found');

writeFileSync(FILE, out, 'utf8');
const bumped = out.match(/<b style="[^"]*">build (\d+)</)[1];
console.log(`updated to NOAA ${latest}: ${regs.length} regions ` +
  `[${regs.map(r => r.region).join(', ')}], now build ${bumped}`);

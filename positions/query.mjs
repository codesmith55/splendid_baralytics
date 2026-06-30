#!/usr/bin/env node
// query.mjs — search and display position records
//
// Usage:
//   node positions/query.mjs                      # list all positions
//   node positions/query.mjs <position-id>        # show full record + samples
//   node positions/query.mjs --map=all-that-glitters
//   node positions/query.mjs --faction=legion

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here   = dirname(fileURLToPath(import.meta.url));
const index  = JSON.parse(readFileSync(join(here, 'index.json'), 'utf8'));
const args   = process.argv.slice(2);
const flag   = (name) => args.find(a => a.startsWith(`--${name}=`))?.split('=').slice(1).join('=') ?? null;
const posArg = args.find(a => !a.startsWith('--'));

const mapFilter     = flag('map');
const factionFilter = flag('faction');

let positions = index.positions;
if (mapFilter)     positions = positions.filter(p => p.map     === mapFilter);
if (factionFilter) positions = positions.filter(p => p.faction === factionFilter);

if (!posArg) {
    // List view
    console.log('\nPositions database:\n');
    if (!positions.length) { console.log('  (none matching filters)'); process.exit(0); }

    const W = Math.max(...positions.map(p => p.id.length));
    for (const p of positions) {
        const obs  = p.best_observed_s  != null ? `obs ${p.best_observed_s}s` : 'no samples';
        const proj = p.best_projected_s != null ? `proj ${p.best_projected_s}s` : '';
        const paths = p.paths.join(', ');
        console.log(`  ${p.id.padEnd(W)}  ${proj.padEnd(12)}  ${obs.padEnd(14)}  [${paths}]`);
        console.log(`  ${' '.repeat(W)}  ${p.description}`);
        console.log();
    }
    console.log(`  ${positions.length} position(s)  —  record.mjs to add a sample  —  query.mjs <id> for detail`);
    console.log();
    process.exit(0);
}

// Detail view
const entry = positions.find(p => p.id === posArg);
if (!entry) {
    console.error(`Position not found: ${posArg}`);
    console.error('Known:', index.positions.map(p => p.id).join(', '));
    process.exit(1);
}

const record = JSON.parse(readFileSync(join(here, entry.file), 'utf8'));

console.log(`\n${record.id}  —  ${record.description}`);
console.log(`  map: ${record.map}   faction: ${record.faction}   start: ${record.start_pos}`);
console.log(`  target: ${record.target.description}`);
console.log(`  branch point: ${record.branch_point.description}`);

console.log('\n  Paths:\n');
const pW = Math.max(...Object.keys(record.paths).map(k => k.length));
for (const [pid, path] of Object.entries(record.paths)) {
    const t = path.timing;
    console.log(`  ${pid.padEnd(pW)}  projected ${path.projected_s}s`);
    console.log(`  ${' '.repeat(pW)}  ${path.description}`);

    if (t) {
        const range = t.min_s === t.max_s ? `${t.min_s}s` : `${t.min_s}–${t.max_s}s`;
        const diff  = t.mean_s - path.projected_s;
        const sign  = diff >= 0 ? '+' : '';
        console.log(`  ${' '.repeat(pW)}  observed: ${range}  mean ${t.mean_s}s (${sign}${diff.toFixed(1)}s vs proj)  n=${t.n}`);

        if (path.samples.length) {
            console.log(`  ${' '.repeat(pW)}  samples:`);
            for (const s of path.samples) {
                const wind = s.wind_avg != null ? `  wind=${s.wind_avg}` : '';
                const note = s.notes    ? `  "${s.notes}"` : '';
                console.log(`  ${' '.repeat(pW)}    ${s.date}  ${s.completion_s}s${wind}${note}`);
            }
        }
    } else {
        console.log(`  ${' '.repeat(pW)}  no samples yet  —  node positions/record.mjs ${record.id} ${pid} <completion_s> [--wind=N]`);
    }
    console.log();
}

if (record.notes) {
    console.log(`  Notes: ${record.notes}`);
    console.log();
}

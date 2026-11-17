#!/usr/bin/env node
// record.mjs — add a real-game sample to a position record
//
// Usage:
//   node positions/record.mjs <position-id> <path-id> <completion_s> [--wind=N] [--notes=...]
//       Manual entry. completion_s = seconds when the target event occurred in-game.
//
//   node positions/record.mjs <position-id> <path-id> --detect [--server=URL]
//       Live detection. Polls bar_analytic_server until the target event fires, then
//       records the game timestamp automatically.
//
// Examples:
//   node positions/record.mjs legion-pos6-first-medmex wind-in-place 312 --wind=9.5
//   node positions/record.mjs legion-pos6-first-medmex return-to-com --detect
//
// After recording, prints the updated timing stats for that path.

import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));

// ── Parse args ────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const flag  = (name) => args.find(a => a.startsWith(`--${name}=`))?.split('=').slice(1).join('=') ?? null;
const bool  = (name) => args.includes(`--${name}`);

const [posId, pathId, ...rest] = args.filter(a => !a.startsWith('--'));
const completionArg = rest[0] ? parseFloat(rest[0]) : NaN;
const wind    = flag('wind')  != null ? parseFloat(flag('wind'))  : null;
const notes   = flag('notes') ?? '';
const detect  = bool('detect');
const server  = flag('server') ?? 'http://localhost:8787';

if (!posId || !pathId) {
    console.error('Usage: node positions/record.mjs <position-id> <path-id> <completion_s|--detect> [--wind=N] [--notes=...]');
    process.exit(1);
}

// ── Load position record ──────────────────────────────────────────────────────
const indexPath  = join(here, 'index.json');
const index      = JSON.parse(readFileSync(indexPath, 'utf8'));
const posEntry   = index.positions.find(p => p.id === posId);
if (!posEntry) {
    console.error(`Unknown position: ${posId}`);
    console.error('Known positions:', index.positions.map(p => p.id).join(', '));
    process.exit(1);
}

const recordPath = join(here, posEntry.file);
const record     = JSON.parse(readFileSync(recordPath, 'utf8'));
const pathDef    = record.paths[pathId];
if (!pathDef) {
    console.error(`Unknown path: ${pathId}`);
    console.error('Known paths:', Object.keys(record.paths).join(', '));
    process.exit(1);
}

// ── Get completion time ───────────────────────────────────────────────────────
let completion_s;

if (detect) {
    completion_s = await detectEvent(server, record.target.detect_live);
} else {
    if (isNaN(completionArg)) {
        console.error('Provide a completion_s value or use --detect');
        process.exit(1);
    }
    completion_s = completionArg;
}

// ── Build sample entry ────────────────────────────────────────────────────────
const today = new Date().toISOString().slice(0, 10);
const sample = {
    date: today,
    completion_s: Math.round(completion_s * 10) / 10,
    ...(wind != null ? { wind_avg: wind } : {}),
    ...(notes        ? { notes }           : {}),
};

pathDef.samples.push(sample);
pathDef.timing = computeTiming(pathDef.samples);

// ── Update index best_observed_s ─────────────────────────────────────────────
const allObserved = Object.values(record.paths)
    .flatMap(p => p.samples.map(s => s.completion_s))
    .filter(Boolean);
if (allObserved.length) posEntry.best_observed_s = Math.min(...allObserved);

// ── Write back ────────────────────────────────────────────────────────────────
writeFileSync(recordPath, JSON.stringify(record, null, 2) + '\n');
writeFileSync(indexPath,  JSON.stringify(index,  null, 2) + '\n');

// ── Report ────────────────────────────────────────────────────────────────────
const t = pathDef.timing;
console.log(`\nRecorded sample for ${posId} / ${pathId}:`);
console.log(`  completion_s : ${sample.completion_s}s  wind: ${sample.wind_avg ?? '—'}  notes: ${sample.notes || '—'}`);
console.log(`\nPath timing (n=${t.n}):`);
console.log(`  min  ${t.min_s}s   mean  ${t.mean_s}s   max  ${t.max_s}s`);
console.log(`  vs projected: ${pathDef.projected_s}s`);
console.log(`\nAll paths for ${posId}:`);
for (const [pid, p] of Object.entries(record.paths)) {
    const marker = pid === pathId ? '→' : ' ';
    const obs    = p.timing ? `observed ${p.timing.min_s}–${p.timing.max_s}s (n=${p.timing.n})` : 'no samples yet';
    console.log(`  ${marker} ${pid.padEnd(18)} projected ${p.projected_s}s   ${obs}`);
}
console.log();

// ── Live detection ────────────────────────────────────────────────────────────
async function detectEvent(serverUrl, detector) {
    const { metric, op, value, window_s = 5, note } = detector;
    const apiUrl = serverUrl.replace(/\/$/, '') + '/api/state';

    console.log(`Connecting to ${apiUrl}`);
    console.log(`Watching: ${metric} ${op} ${value}${note ? `  (${note})` : ''}`);
    console.log('Waiting for game to start...\n');

    let prevFrame     = -1;
    let prevValue     = {};  // teamID → last metric value
    let gameStarted   = false;
    let POLL_MS       = 500;

    while (true) {
        await sleep(POLL_MS);
        let state;
        try {
            const res = await fetch(apiUrl);
            if (!res.ok) { process.stdout.write('.'); continue; }
            state = await res.json();
        } catch { process.stdout.write('.'); continue; }

        const { frame, gameSeconds, teams = [], over } = state;

        if (over) {
            console.log('\nGame ended without detecting target event.');
            process.exit(1);
        }

        // Detect new game
        if (frame < prevFrame) {
            prevValue = {};
            gameStarted = false;
            prevFrame = frame;
            console.log('\nNew game detected, resetting...');
        }
        if (frame > 0 && !gameStarted) { gameStarted = true; console.log('Game started.'); }
        prevFrame = frame;

        if (!gameStarted) continue;

        for (const team of teams) {
            const curr = getMetric(team, metric);
            if (curr == null) continue;

            const prev    = prevValue[team.teamID] ?? curr;
            const delta   = curr - prev;
            prevValue[team.teamID] = curr;

            const triggered =
                op === 'delta_above'  ? delta  >= value :
                op === '>='           ? curr   >= value :
                op === '<='           ? curr   <= value :
                false;

            if (triggered) {
                process.stdout.write('\n');
                console.log(`Event detected! team ${team.teamID}  ${metric}=${curr.toFixed(2)}  gameSeconds=${gameSeconds.toFixed(1)}`);
                return gameSeconds;
            }
        }

        if (gameStarted) process.stdout.write(`\r  T=${gameSeconds?.toFixed(0)}s  ${metric}=${getMetricDisplay(teams, metric)}`);
    }
}

function getMetric(team, metric) {
    return team[metric] ?? team.metalIncome ?? null;
}

function getMetricDisplay(teams, metric) {
    return teams.map(t => {
        const v = t[metric];
        return v != null ? v.toFixed(2) : '?';
    }).join(' / ');
}

function computeTiming(samples) {
    if (!samples.length) return null;
    const times = samples.map(s => s.completion_s).sort((a, b) => a - b);
    const mean  = Math.round(10 * times.reduce((s, x) => s + x, 0) / times.length) / 10;
    return { n: samples.length, mean_s: mean, min_s: times[0], max_s: times[times.length - 1] };
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

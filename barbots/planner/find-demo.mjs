#!/usr/bin/env node
/**
 * find-demo.mjs — locate BAR demo files matching criteria.
 *
 * Scans a demo directory (default: %LocalAppData%/BAR/data/demos on Windows
 * or ~/.spring/demos elsewhere) and filters by mtime / player count /
 * minimum duration / filename regex, then sorts newest-first.
 *
 * Duration and player count require reading each candidate's header (via
 * sdfz-demo-parser --skipPackets); pass --fast to skip demos whose filename
 * doesn't contain the player-count hint. --limit caps how many candidates
 * are opened (default 20).
 *
 * Usage:
 *   node planner/find-demo.mjs [options]
 *
 * Options:
 *   --dir <path>          demo directory (default: OS convention)
 *   --players <N>         require exactly N players
 *   --min-duration <sec>  require full duration >= this many seconds
 *   --match <regex>       filename must match this regex
 *   --limit <N>           inspect at most N most-recent candidates (default 20)
 *   --n <N>               return the newest N matches (default 1)
 *   --json                emit full JSON per match
 *
 * Example:
 *   node planner/find-demo.mjs --players 16 --min-duration 600 --n 1
 */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname  = path.dirname(__filename);
const BARBOTS    = path.resolve(__dirname, '..');
const ROOT       = path.resolve(BARBOTS, '..');
const DEMOPARSER = path.join(ROOT, 'gex_research', 'tools', 'demoparser', 'package.json');


export function defaultDemoDir() {
    if (process.platform === 'win32') {
        const local = process.env.LOCALAPPDATA
            ?? path.join(os.homedir(), 'AppData', 'Local');
        return path.join(local, 'Programs', 'Beyond-All-Reason', 'data', 'demos');
    }
    // Linux / mac fallback
    return path.join(os.homedir(), '.spring', 'demos');
}


export async function findDemos({
    dir = defaultDemoDir(),
    players = null,
    minDurationSec = null,
    matchRe = null,
    limit = 20,
    n = 1,
} = {}) {
    if (!fs.existsSync(dir)) {
        throw new Error(`demo directory not found: ${dir}`);
    }
    const req = createRequire(DEMOPARSER);
    const { DemoParser } = req('sdfz-demo-parser');

    let files = fs.readdirSync(dir)
        .filter(f => f.endsWith('.sdfz'))
        .map(f => {
            const p = path.join(dir, f);
            return { path: p, name: f, mtimeMs: fs.statSync(p).mtimeMs };
        })
        .sort((a, b) => b.mtimeMs - a.mtimeMs);

    if (matchRe) {
        const re = new RegExp(matchRe, 'i');
        files = files.filter(f => re.test(f.name));
    }

    files = files.slice(0, limit);

    const results = [];
    for (const f of files) {
        try {
            const demo = await new DemoParser({ skipPackets: true }).parseDemo(f.path);
            const meta = demo.info?.meta ?? {};
            const playerCount = (demo.info?.players ?? []).filter(Boolean).length;
            const durMs = meta.fullDurationMs ?? meta.durationMs ?? 0;
            const rec = {
                path: f.path,
                name: f.name,
                mtimeMs: f.mtimeMs,
                map: meta.map ?? null,
                playerCount,
                allyTeamCount: (demo.info?.allyTeams ?? []).length,
                durationSec: Math.round(durMs / 1000),
                durationMinutes: +(durMs / 60000).toFixed(1),
                winningAllyTeamIds: meta.winningAllyTeamIds ?? [],
            };
            if (players !== null && rec.playerCount !== players) continue;
            if (minDurationSec !== null && rec.durationSec < minDurationSec) continue;
            results.push(rec);
            if (results.length >= n) break;
        } catch (err) {
            // Skip unparsable files
        }
    }
    return results;
}


function parseFlags(argv) {
    const out = {};
    for (let i = 0; i < argv.length; i++) {
        const a = argv[i];
        if (!a.startsWith('--')) continue;
        const k = a.slice(2);
        const next = argv[i + 1];
        if (next === undefined || next.startsWith('--')) { out[k] = true; }
        else { out[k] = next; i++; }
    }
    return out;
}

if ((process.argv[1] ?? '').replace(/\\/g, '/').endsWith('find-demo.mjs')) {
    const flags = parseFlags(process.argv.slice(2));
    const results = await findDemos({
        dir: flags.dir ?? defaultDemoDir(),
        players: flags.players ? +flags.players : null,
        minDurationSec: flags['min-duration'] ? +flags['min-duration'] : null,
        matchRe: flags.match ?? null,
        limit: flags.limit ? +flags.limit : 20,
        n: flags.n ? +flags.n : 1,
    });
    if (flags.json) {
        console.log(JSON.stringify(results, null, 2));
    } else {
        for (const r of results) {
            console.log(`${new Date(r.mtimeMs).toISOString()}  ${r.playerCount}p  ${r.durationMinutes}min  ${r.map}  →  ${r.path}`);
        }
    }
}

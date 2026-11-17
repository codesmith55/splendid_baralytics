#!/usr/bin/env node
/**
 * demo-roster.mjs — read a BAR .sdfz demo and describe the starting player
 * positions on both teams.
 *
 * Uses the same sdfz-demo-parser vendored under gex_research/tools/demoparser/.
 * Header-only parse — fast (no packet stream). Emits per-allyTeam rosters
 * with each player's start position, faction, skill, and (if the demo has
 * a fixed-box mode) the ally team's start box.
 *
 * Usage:
 *   node planner/demo-roster.mjs <path.sdfz> [--summary]
 *
 * API:
 *   import { readDemoRoster, describeRoster } from './planner/demo-roster.mjs';
 *   const roster = await readDemoRoster('/path/to/demo.sdfz');
 *   console.log(describeRoster(roster));
 *
 * Output shape:
 *   {
 *     meta:    { map, engine, game, startTime, durationMs, playerCount,
 *                allyTeamCount, winningAllyTeamIds, startPosType },
 *     allyTeams: [
 *       { allyTeamId, playerCount, startBox?, players: [
 *           { name, teamId, faction, skill, rank, startPos:{x,y,z} }
 *         ] }
 *     ],
 *     spectatorCount,
 *   }
 */
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import fs from 'node:fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname  = path.dirname(__filename);
const BARBOTS    = path.resolve(__dirname, '..');
const ROOT       = path.resolve(BARBOTS, '..');
const DEMOPARSER = path.join(ROOT, 'gex_research', 'tools', 'demoparser', 'package.json');

export async function readDemoRoster(demoPath) {
    if (!fs.existsSync(demoPath)) throw new Error(`demo not found: ${demoPath}`);
    if (!fs.existsSync(DEMOPARSER)) {
        throw new Error(
            `sdfz-demo-parser package.json not found at ${DEMOPARSER}. ` +
            `Ensure gex_research/tools/demoparser exists with sdfz-demo-parser installed.`
        );
    }
    const req = createRequire(DEMOPARSER);
    const { DemoParser } = req('sdfz-demo-parser');
    const demo = await new DemoParser({ skipPackets: true }).parseDemo(demoPath);

    const info = demo.info ?? {};
    const meta = info.meta ?? {};
    const allyTeams = info.allyTeams ?? [];
    const players   = (info.players ?? []).filter(Boolean);

    // Group players by allyTeamId
    const byAlly = new Map();
    for (const at of allyTeams) byAlly.set(at.allyTeamId, {
        allyTeamId: at.allyTeamId,
        playerCount: at.playerCount ?? 0,
        startBox: at.startBox ?? null,
        players: [],
    });
    for (const p of players) {
        const bucket = byAlly.get(p.allyTeamId) ?? {
            allyTeamId: p.allyTeamId,
            playerCount: 0,
            startBox: null,
            players: [],
        };
        bucket.players.push({
            name: p.name ?? '?',
            teamId: p.teamId ?? -1,
            faction: p.faction ?? '?',
            skill: p.skill ?? null,
            rank: p.rank ?? null,
            startPos: p.startPos ?? null,
            rgbColor: p.rgbColor ?? null,
        });
        if (!byAlly.has(p.allyTeamId)) byAlly.set(p.allyTeamId, bucket);
    }

    return {
        source: path.basename(demoPath),
        meta: {
            map: meta.map ?? null,
            engine: meta.engine ?? null,
            game: meta.game ?? null,
            startTime: meta.startTime ?? null,
            durationMs: meta.durationMs ?? null,
            fullDurationMs: meta.fullDurationMs ?? null,
            durationMinutes: meta.durationMs ? +(meta.durationMs / 60000).toFixed(1) : null,
            playerCount: players.length,
            allyTeamCount: allyTeams.length,
            winningAllyTeamIds: meta.winningAllyTeamIds ?? [],
            startPosType: meta.startPosType ?? null,
        },
        allyTeams: Array.from(byAlly.values()).sort((a, b) => a.allyTeamId - b.allyTeamId),
        spectatorCount: (info.spectators ?? []).length,
    };
}


/** Human-readable summary — one line per ally team, indented players below. */
export function describeRoster(roster) {
    const lines = [];
    const m = roster.meta;
    const dur = m.durationMinutes !== null ? `${m.durationMinutes}min` : '?';
    const winners = (m.winningAllyTeamIds ?? []).join(',') || '?';
    lines.push(`${roster.source}`);
    lines.push(`  map=${m.map}  players=${m.playerCount}  allyTeams=${m.allyTeamCount}  duration=${dur}  winners=[${winners}]`);
    for (const at of roster.allyTeams) {
        const label = m.winningAllyTeamIds?.includes(at.allyTeamId) ? '  ★' : '   ';
        const box = at.startBox
            ? `  box=(${at.startBox.left.toFixed(2)},${at.startBox.top.toFixed(2)})-(${at.startBox.right.toFixed(2)},${at.startBox.bottom.toFixed(2)})`
            : '';
        lines.push(`${label} allyTeam ${at.allyTeamId}  (${at.playerCount} players)${box}`);
        for (const p of at.players) {
            const pos = p.startPos
                ? `pos=(${Math.round(p.startPos.x)}, ${Math.round(p.startPos.z ?? p.startPos.y ?? 0)})`
                : 'pos=?';
            const skill = p.skill ? `skill=${p.skill}` : 'skill=?';
            lines.push(`      ${p.name.padEnd(22)}  faction=${(p.faction ?? '?').padEnd(6)} ${pos.padEnd(20)} ${skill}`);
        }
    }
    return lines.join('\n');
}


// ── CLI ─────────────────────────────────────────────────────────────────────
if ((process.argv[1] ?? '').replace(/\\/g, '/').endsWith('demo-roster.mjs')) {
    const argv = process.argv.slice(2);
    const summary = argv.includes('--summary');
    const demoArg = argv.find(a => !a.startsWith('--'));
    if (!demoArg) {
        console.error('Usage: node planner/demo-roster.mjs <path.sdfz> [--summary]');
        process.exit(1);
    }
    const roster = await readDemoRoster(path.resolve(demoArg));
    if (summary) console.error(describeRoster(roster) + '\n');
    console.log(JSON.stringify(roster, null, 2));
}

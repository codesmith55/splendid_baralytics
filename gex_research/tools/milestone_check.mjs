/**
 * milestone_check.mjs — CLI for milestone trigger evaluation against BAR replays.
 *
 * Usage:
 *   node tools/milestone_check.mjs [game options] [--snapshots "..."] <trigger1> [trigger2] ...
 *
 * Game reference options (mutually-exclusive-ish, last specified wins):
 *   --game last       last completed game (default)
 *   --game 1          same as last
 *   --game 2          second-to-last, 3 = third-to-last, etc.
 *   --game 0          current/live game (polls http://localhost:8787; limited)
 *   --game "pattern"  most recent game whose filename contains this string
 *   --demo <path>     skip resolution, use this .sdfz file directly
 *
 * Filter options:
 *   --player <name>   roster-filter: only consider games where this player is solo
 *                     (no human teammates on their allyTeam).  Default: "splendi"
 *   --team <id>       override teamId (skip roster lookup; useful with --demo)
 *   --since <date>    only consider demos modified after YYYY-MM-DD
 *
 * Analysis options:
 *   --window <s>      analysis window in seconds (default 900 = 15 min)
 *   --snapshots "T2 mex,each medmex"  comma-sep phrases to snapshot on fire
 *   --verbose         print snapshot economy details
 *   --json            output raw JSON (for API use; suppresses human text)
 *
 * Trigger phrases (positional args after options):
 *   "5 mex"          "7 mex"    "each medmex"    "TPV 6000"
 *   "T2 factory"     "T2 mex"   "metal income 15"
 *
 * Examples:
 *   node tools/milestone_check.mjs "5 mex" "7 mex" "each medmex" "TPV 6000" "T2 factory" "T2 mex"
 *   node tools/milestone_check.mjs --game 2 --snapshots "T2 mex" "5 mex" "T2 factory" "T2 mex"
 *   node tools/milestone_check.mjs --demo path/to/replay.sdfz "each medmex" "T2 factory"
 */

import { createRequire } from "node:module";
import fs      from "node:fs";
import path    from "node:path";
import { fileURLToPath } from "node:url";
import { runHeadless } from "../process/lib/headless.mjs";
import { parseTriggers, runMilestones, formatResults } from "../process/lib/milestone_engine.mjs";

const __dirname  = path.dirname(fileURLToPath(import.meta.url));
// sdfz-demo-parser lives in demoparser/node_modules — require from that subdirectory
const require    = createRequire(path.join(__dirname, "demoparser", "package.json"));
const { DemoParser } = require("sdfz-demo-parser");

const DEMOS_DIR  = "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data/demos";
const VENDOR_DIR = path.resolve(__dirname, "../vendor");

// ── arg parsing ────────────────────────────────────────────────────────────────

const argv     = process.argv.slice(2);
const flags    = {};
const triggers = [];

for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--game")      { flags.game      = argv[++i]; continue; }
  if (a === "--demo")      { flags.demo      = argv[++i]; continue; }
  if (a === "--player")    { flags.player    = argv[++i]; continue; }
  if (a === "--team")      { flags.team      = parseInt(argv[++i], 10); continue; }
  if (a === "--since")     { flags.since     = argv[++i]; continue; }
  if (a === "--window")    { flags.window    = parseInt(argv[++i], 10); continue; }
  if (a === "--snapshots") { flags.snapshots = argv[++i]; continue; }
  if (a === "--verbose")   { flags.verbose   = true;      continue; }
  if (a === "--json")      { flags.json      = true;      continue; }
  if (!a.startsWith("--")) triggers.push(a);
}

const PLAYER_DEFAULT = "splendi";
const playerFilter   = (flags.player ?? PLAYER_DEFAULT).toLowerCase();
const windowS        = flags.window  ?? 900;
const snapshotList   = flags.snapshots ? flags.snapshots.split(",").map(s => s.trim()) : [];
const jsonMode       = flags.json ?? false;

if (triggers.length === 0) {
  if (!jsonMode) {
    console.error("Usage: node tools/milestone_check.mjs [options] <trigger1> [trigger2] ...");
    console.error('  Example: "5 mex" "7 mex" "each medmex" "TPV 6000" "T2 factory" "T2 mex"');
  } else {
    process.stdout.write(JSON.stringify({ error: "no triggers provided" }));
  }
  process.exit(1);
}

// ── game resolution ────────────────────────────────────────────────────────────

let demoPath = null;
let teamId   = flags.team ?? null;

if (flags.demo) {
  demoPath = path.resolve(flags.demo);
} else {
  const gameArg = flags.game ?? "last";

  if (gameArg === "0") {
    // live game — limited support: report what milestones are already fired
    // from the live server state
    demoPath = null;
    if (!jsonMode) console.error("[milestone] live game (--game 0) support not yet implemented");
    process.exit(1);
  }

  // List all demos, newest first
  let demos = fs.readdirSync(DEMOS_DIR)
    .filter(f => f.toLowerCase().endsWith(".sdfz"))
    .map(f => {
      const fp = path.join(DEMOS_DIR, f);
      return { file: f, fullPath: fp, mtimeMs: fs.statSync(fp).mtimeMs };
    })
    .sort((a, b) => b.mtimeMs - a.mtimeMs);

  // Filter by --since
  if (flags.since) {
    const sinceMs = new Date(flags.since).getTime();
    demos = demos.filter(d => d.mtimeMs >= sinceMs);
  }

  // Determine if gameArg is numeric (index) or a name pattern
  const idx     = /^\d+$/.test(gameArg) ? parseInt(gameArg, 10) : null;
  const pattern = idx === null ? gameArg.toLowerCase() : null;

  if (pattern) {
    demos = demos.filter(d => d.file.toLowerCase().includes(pattern));
  }

  // Player filter: find demos where playerFilter is solo (only human on their allyTeam)
  let qualifying = [];
  const scanLimit = Math.min(demos.length, 60);
  if (!jsonMode) process.stderr.write(`[milestone] scanning ${scanLimit} demos for player "${playerFilter}"...\n`);

  for (const demo of demos.slice(0, scanLimit)) {
    try {
      const d       = await new DemoParser({ skipPackets: true }).parseDemo(demo.fullPath);
      const players = (d.info.players || []).filter(Boolean);
      const target  = players.find(p => p.name?.toLowerCase().includes(playerFilter));
      if (!target) continue;

      const teammates = players.filter(p => p !== target && p.allyTeamId === target.allyTeamId);
      if (teammates.length > 0) continue;  // has human teammates

      qualifying.push({ ...demo, teamId: target.teamId, playerName: target.name });
    } catch (_) { /* skip unreadable demos */ }

    if (qualifying.length >= Math.max(idx ?? 1, 10)) break;
  }

  if (qualifying.length === 0) {
    const msg = `no solo games found for player "${playerFilter}"`;
    if (!jsonMode) console.error(`[milestone] ${msg}`);
    else process.stdout.write(JSON.stringify({ error: msg }));
    process.exit(1);
  }

  const pick = idx != null ? qualifying[idx - 1] : qualifying[0];
  if (!pick) {
    const msg = `game index ${idx} not found (only ${qualifying.length} qualifying games)`;
    if (!jsonMode) console.error(`[milestone] ${msg}`);
    else process.stdout.write(JSON.stringify({ error: msg }));
    process.exit(1);
  }

  demoPath = pick.fullPath;
  teamId   = teamId ?? pick.teamId;
  if (!jsonMode)
    process.stderr.write(`[milestone] game: ${pick.file}  player: ${pick.playerName}  teamId: ${teamId}\n`);
}

// if teamId still unknown (--demo without --team), try to parse roster
if (teamId === null) {
  try {
    const d = await new DemoParser({ skipPackets: true }).parseDemo(demoPath);
    const players = (d.info.players || []).filter(Boolean);
    const target  = players.find(p => p.name?.toLowerCase().includes(playerFilter));
    if (target) {
      teamId = target.teamId;
      if (!jsonMode) process.stderr.write(`[milestone] resolved teamId=${teamId} for "${target.name}"\n`);
    } else {
      if (!jsonMode) process.stderr.write(`[milestone] player "${playerFilter}" not found in roster; using teamId=0\n`);
      teamId = 0;
    }
  } catch (e) {
    if (!jsonMode) process.stderr.write(`[milestone] roster parse failed: ${e.message}\n`);
    teamId = 0;
  }
}

// ── headless extraction ────────────────────────────────────────────────────────

if (!jsonMode)
  process.stderr.write(`[milestone] running headless (reuseExisting=true)...\n`);

let actionsPath;
try {
  actionsPath = runHeadless({ demoFile: demoPath, vendorDir: VENDOR_DIR, reuseExisting: true });
} catch (e) {
  const msg = `headless failed: ${e.message}`;
  if (!jsonMode) console.error(`[milestone] ${msg}`);
  else process.stdout.write(JSON.stringify({ error: msg, demo: demoPath }));
  process.exit(1);
}

// ── trigger parsing + evaluation ───────────────────────────────────────────────

const triggerSpecs = parseTriggers(triggers, snapshotList);
const result = await runMilestones(actionsPath, teamId, triggerSpecs, windowS);

result.game = {
  file:   path.basename(demoPath),
  path:   demoPath,
  teamId,
  date:   new Date(fs.statSync(demoPath).mtimeMs).toISOString().slice(0, 10),
};

// ── output ─────────────────────────────────────────────────────────────────────

if (jsonMode) {
  process.stdout.write(JSON.stringify(result, null, 2));
} else {
  console.log(formatResults(result, { verbose: flags.verbose }));
}

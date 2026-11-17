/**
 * mex5_timing.mjs — Find 5-mex timing for [APE]Splendi across recent solo games.
 *
 * Steps:
 *   1. Scan last 60 demos for skirmish/solo games with Splendi as a player (DemoParser header only)
 *   2. Take the 10 most recent qualifying games
 *   3. Run headless on each (reuseExisting: true — skips re-run if already extracted)
 *   4. Parse actions.json: count unit_created for isMetalExtractor units on Splendi's team
 *   5. Report frame/second when mex count first hits 5 (capped at 90s window)
 *
 * Usage: node tools/demoparser/mex5_timing.mjs [--limit N] [--window N]
 *
 * Options:
 *   --limit N   number of qualifying games to analyse (default 10)
 *   --window N  ingame seconds to search (default 90)
 */

import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";
import { runHeadless } from "../../process/lib/headless.mjs";

const require = createRequire(import.meta.url);
const { DemoParser } = require("sdfz-demo-parser");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEMOS_DIR = "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data/demos";
const VENDOR_DIR = path.resolve(__dirname, "../../vendor");
const PLAYER_RE = /splendi/i;
const TARGET_MEX = 5;

// ── arg parsing ────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const getArg = (flag, def) => { const i = args.indexOf(flag); return i >= 0 ? Number(args[i + 1]) : def; };
const GAME_LIMIT = getArg("--limit", 10);
const WINDOW_S   = getArg("--window", 90);
const MAX_FRAME  = WINDOW_S * 30;

// ── step 1: scan demo headers ─────────────────────────────────────────────────
console.log(`\nScanning demo headers in ${DEMOS_DIR} ...`);

const allDemos = fs.readdirSync(DEMOS_DIR)
  .filter(f => f.toLowerCase().endsWith(".sdfz"))
  .map(f => {
    const fp = path.join(DEMOS_DIR, f);
    return { file: f, path: fp, mtimeMs: fs.statSync(fp).mtimeMs };
  })
  .sort((a, b) => b.mtimeMs - a.mtimeMs)
  .slice(0, 80);  // parse headers for last 80 demos to find enough qualifying ones

const qualifying = [];
for (const demo of allDemos) {
  if (qualifying.length >= GAME_LIMIT) break;
  try {
    const d = await new DemoParser({ skipPackets: true }).parseDemo(demo.path);
    const players = (d.info.players || []).filter(Boolean);
    const ais = d.info.ais || [];
    const meta = d.info.meta || {};

    const splendi = players.find(p => PLAYER_RE.test(p.name || ""));
    if (!splendi) continue;

    // solo = Splendi is the only human on their allyTeam
    const splendTeammates = players.filter(p =>
      p !== splendi && p.allyTeamId === splendi.allyTeamId
    );
    if (splendTeammates.length > 0) continue;  // has human teammates → skip

    const durMin = meta.durationMs ? (meta.durationMs / 60000).toFixed(1) : "?";
    const map = meta.map || "?";
    const enemies = players.filter(p => p.allyTeamId !== splendi.allyTeamId);
    console.log(
      `  FOUND: ${demo.file.slice(0, 60)} | ${players.length}p+${ais.length}ai ` +
      `| ${splendi.name}(AT${splendi.allyTeamId}) vs ${enemies.map(p => p.name).join(",")||"(ai)"} ` +
      `| ${durMin}min | ${map}`
    );
    qualifying.push({ ...demo, splendTeamId: splendi.teamId, splendName: splendi.name });
  } catch (_e) {
    // skip unreadable demos silently
  }
}

if (qualifying.length === 0) {
  console.log("No qualifying solo games found for Splendi in the last 80 demos.");
  process.exit(0);
}
console.log(`\nFound ${qualifying.length} qualifying games. Running headless...\n`);

// ── step 2: headless + parse ─────────────────────────────────────────────────
const results = [];

for (const game of qualifying) {
  const label = game.file.replace(/\.sdfz$/i, "");
  const date  = new Date(game.mtimeMs).toISOString().slice(0, 10);
  let mex5_s = null;
  let mex5_frame = null;
  let note = "";

  try {
    const actionsPath = runHeadless({
      demoFile: game.path,
      vendorDir: VENDOR_DIR,
      reuseExisting: true,
    });
    const result = await parseMex5(actionsPath, game.splendTeamId);
    mex5_s     = result.mex5_s;
    mex5_frame = result.mex5_frame;
    note       = result.note;
  } catch (e) {
    note = `ERR: ${e.message.slice(0, 60)}`;
  }

  results.push({ date, label, mex5_s, mex5_frame, note });

  if (mex5_s !== null) {
    console.log(`  ${date}  5th mex @ ${mex5_s.toFixed(1)}s  (${label.slice(-30)})`);
  } else {
    console.log(`  ${date}  5th mex NOT reached in ${WINDOW_S}s  [${note}]  (${label.slice(-30)})`);
  }
}

// ── step 3: output table ──────────────────────────────────────────────────────
const reached = results.filter(r => r.mex5_s !== null).sort((a, b) => a.mex5_s - b.mex5_s);

console.log("\n" + "─".repeat(72));
console.log("  5-MEX TIMING RESULTS — [APE]Splendi solo games");
console.log("─".repeat(72));
console.log(`  ${"Date".padEnd(12)} ${"5th mex".padEnd(10)} ${"Demo (truncated)".padEnd(44)}`);
console.log("  " + "─".repeat(68));

for (const r of results.sort((a, b) => a.mex5_s === null ? 1 : b.mex5_s === null ? -1 : a.mex5_s - b.mex5_s)) {
  const timing = r.mex5_s !== null
    ? `${fmt(r.mex5_s)}  ` + (r === reached[0] ? "<-- BEST" : "")
    : `> ${WINDOW_S}s  [${r.note}]`;
  console.log(`  ${r.date.padEnd(12)} ${timing.padEnd(22)} ${r.label.slice(-44)}`);
}

if (reached.length > 0) {
  console.log("─".repeat(72));
  const best = reached[0];
  const med  = reached[Math.floor(reached.length / 2)];
  const worst = reached[reached.length - 1];
  console.log(`  Best:    ${fmt(best.mex5_s)}  (${best.date})`);
  console.log(`  Median:  ${fmt(med.mex5_s)}  (${med.date})`);
  console.log(`  Slowest: ${fmt(worst.mex5_s)}  (${worst.date})`);
  console.log(`  Games reaching 5 mexes in ${WINDOW_S}s: ${reached.length}/${results.length}`);
}
console.log("─".repeat(72));
console.log("  NOTE: timing = unit_created (placement), not unit_finished (completion).");
console.log("        Mex build time ~40-60s, so add ~40-60s for income-start timing.");
console.log("─".repeat(72) + "\n");

// ── helpers ───────────────────────────────────────────────────────────────────

function fmt(s) {
  const min = Math.floor(s / 60);
  const sec = (s % 60).toFixed(1);
  return `${min}:${sec.padStart(4, "0")}`;
}

async function parseMex5(actionsPath, splendTeamId) {
  const stream = fs.createReadStream(actionsPath, { encoding: "utf8" });
  const rl = readline.createInterface({ input: stream, crlfDelay: Infinity });

  const mexDefIDs = new Set();
  let mexCount = 0;
  let mex5_frame = null;
  let lineCount = 0;

  for await (const line of rl) {
    if (!line.trim()) continue;
    lineCount++;
    let ev;
    try { ev = JSON.parse(line); } catch (_) { continue; }

    const action = ev.action;

    if (action === "unit_def") {
      if (ev.isMetalExtractor) mexDefIDs.add(ev.defID);
      continue;
    }

    // past 90s window: stop reading
    if (ev.frame > MAX_FRAME) break;

    if (action === "unit_created" && ev.teamID === splendTeamId && mexDefIDs.has(ev.defID)) {
      mexCount++;
      if (mexCount >= TARGET_MEX) {
        mex5_frame = ev.frame;
        break;
      }
    }
  }

  rl.close();
  stream.destroy();

  if (mex5_frame !== null) {
    return { mex5_s: mex5_frame / 30, mex5_frame, note: "" };
  }
  return { mex5_s: null, mex5_frame: null, note: mexCount > 0 ? `only ${mexCount} mexes` : "no mex data" };
}

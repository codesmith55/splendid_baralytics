#!/usr/bin/env node
/**
 * extract-position.mjs
 * Deciphers eco_engine createState() parameters from a BAR game at a given time.
 *
 * Modes:
 *   --position <name>      Use a saved position file (positions/named/<name>.json)
 *   --demo <path.sdfz>     Run headless extraction on a demo file
 *
 * Options:
 *   --t <seconds>          Capture time (default: position file capture_t, or 50)
 *   --player <name>        Player name filter for demo mode (default: splendi)
 *   --out <file>           Write JSON to file instead of stdout
 *
 * Output JSON fields:
 *   source      demo filename or position file name
 *   t           capture time in seconds
 *   faction     "arm" | "legion"
 *   observed    raw game values (metal, energy, metalIncome, energyIncome, storM, storE)
 *   createState eco_engine createState() parameters — plug in directly
 *   calibration model vs. observed breakdown; Legion residual notes
 *   completed   count by defName of units finished before T
 *   inProgress  count by defName of units placed but not yet finished before T
 *   mode        "position-file" or "headless-parse"
 *
 * Legion note: Legion mexes give ~1.47 m/s (not 1.8), so in position-file mode the
 * createState uses synth_mexes (ARM-equivalent count) to match observed metal income.
 * In headless-parse mode, actual mex count is used and the residual is reported.
 */

import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const __filename = fileURLToPath(import.meta.url);
const __dirname  = path.dirname(__filename);
const ROOT       = path.resolve(__dirname, "../..");
const POS_DIR    = path.join(ROOT, "positions", "named");
const VENDOR_DIR = path.join(ROOT, "gex_research", "vendor");
const GEX_LIB    = path.join(ROOT, "gex_research", "process", "lib");
const DEMOS_DIR  = "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data/demos";

// ARM eco_engine constants — used as baseline for residual calibration
const BASE_M    = 2;
const BASE_E    = 25;
const ARM_MEX_M = 1.8;
const ARM_MEX_E = -3;
const WORKER_E  = 7;
const WIND_E    = 10;   // ATG average
const SOLAR_E   = 20;

// ── arg parse ──────────────────────────────────────────────────────────────────
const argv = process.argv.slice(2);
function flag(k) { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : null; }

const positionName = flag("--position");
const demoArg      = flag("--demo");
const playerName   = flag("--player") ?? "splendi";
const tOverride    = flag("--t") != null ? Number(flag("--t")) : null;
const outFile      = flag("--out");

if (!positionName && !demoArg) {
  process.stderr.write([
    "Usage:",
    "  node extract-position.mjs --position <name> [--t <seconds>]",
    "  node extract-position.mjs --demo <path.sdfz> --t <seconds> [--player <name>] [--out <file>]",
    "",
    "Examples:",
    "  node extract-position.mjs --position legion-5walk",
    "  node extract-position.mjs --demo \"2026-06-22_22-53-03-659_..._2025.06.24.sdfz\" --t 50",
  ].join("\n") + "\n");
  process.exit(1);
}

// ── main ───────────────────────────────────────────────────────────────────────
const result = positionName
  ? await fromPositionFile(positionName, tOverride)
  : await fromDemo(demoArg, tOverride ?? 50, playerName);

const json = JSON.stringify(result, null, 2);
if (outFile) {
  fs.writeFileSync(outFile, json, "utf8");
  console.error(`[extract-position] wrote ${outFile}`);
} else {
  process.stdout.write(json + "\n");
}

// ═══════════════════════════════════════════════════════════════════════════════
// POSITION-FILE MODE
// Uses the observed income snapshot already saved in the position JSON.
// Does not run headless. createState uses synth_mexes for metal-income accuracy.
// ═══════════════════════════════════════════════════════════════════════════════
async function fromPositionFile(name, tOverride) {
  const jsonPath = path.join(POS_DIR, name.endsWith(".json") ? name : `${name}.json`);
  if (!fs.existsSync(jsonPath)) throw new Error(`Position not found: ${jsonPath}`);

  const pos = JSON.parse(fs.readFileSync(jsonPath, "utf8"));
  const st  = pos.state;
  const t   = tOverride ?? st.t ?? 50;

  const metalIncome  = st.metalIncome  ?? 0;
  const energyIncome = st.energyIncome ?? 0;
  const metal  = st.metal        ?? 0;
  const energy = st.energy       ?? 0;
  const storM  = st.metalStorage  ?? 1000;
  const storE  = st.energyStorage ?? 1000;

  // Any completed workers recorded in the position state
  const completedUnits = st.completed ?? {};
  const workerCount = Object.entries(completedUnits)
    .filter(([k]) => isWorkerName(k))
    .reduce((sum, [, v]) => sum + v, 0);

  // Detect faction from unit names present
  const allNames = [
    ...Object.keys(completedUnits),
    ...(pos.build_queue ?? []).map(e => e.defName),
  ];
  const isLegion = allNames.some(n => /^leg/i.test(n));

  // synth_mexes: the ARM mex count whose income best approximates the observed
  // metal income. Legion mexes give ~1.47 m/s — using actual mex count would
  // over-predict in eco_engine (which uses 1.8). synth_mexes is the corrected proxy.
  const mexIncome   = Math.max(0, metalIncome - BASE_M);
  const synth_mexes = Math.round(mexIncome / ARM_MEX_M);

  const model_m      = BASE_M + synth_mexes * ARM_MEX_M;
  const model_e      = BASE_E + synth_mexes * ARM_MEX_E + workerCount * WORKER_E;
  const extraEPerSec = energyIncome - model_e;

  const createState = buildCreateState({
    metal, energy, storM, storE,
    mexes: synth_mexes,
    extraEPerSec,
    workerCount,
  });

  const cal = {
    synth_mexes,
    workers_completed: workerCount,
    model_mIncome: r3(model_m),
    model_eIncome: r1(model_e),
    residual_mIncome: r3(metalIncome - model_m),
  };
  if (isLegion) {
    cal.legion_note =
      `ARM eco_engine uses ${ARM_MEX_M} m/s/mex. synth_mexes=${synth_mexes} gives ` +
      `model_mIncome=${r3(model_m)} (residual ${r3(metalIncome - model_m)} m/s). ` +
      `extraEPerSec=${r1(extraEPerSec)} absorbs Legion commander's higher base energy output.`;
  }

  return {
    source:   pos._meta?.source ?? name,
    t,
    faction:  isLegion ? "legion" : "arm",
    observed: { metal, energy, storM, storE, metalIncome, energyIncome },
    createState,
    calibration: cal,
    completed:   completedUnits,
    inProgress:  st.inProgress ?? [],
    mode: "position-file",
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// DEMO MODE
// Runs headless extraction and parses actions.json for unit-level accuracy.
// Uses actual completed mex/worker/wind/solar counts from unit_finished events.
// ═══════════════════════════════════════════════════════════════════════════════
async function fromDemo(demoFile, captureT, playerFilter) {
  // Resolve demo path
  let demoPath = demoFile;
  if (!path.isAbsolute(demoFile) && !fs.existsSync(demoFile)) {
    demoPath = path.join(DEMOS_DIR, demoFile);
  }
  demoPath = path.resolve(demoPath);
  if (!fs.existsSync(demoPath)) throw new Error(`Demo not found: ${demoPath}`);

  // Get player's teamID from demo header
  const req = createRequire(
    path.join(ROOT, "gex_research", "tools", "demoparser", "package.json")
  );
  const { DemoParser } = req("sdfz-demo-parser");
  const pat = new RegExp(playerFilter, "i");
  let playerTeamId = -1;
  try {
    const parsed  = await new DemoParser({ skipPackets: true }).parseDemo(demoPath);
    const players = (parsed.info.players ?? []).filter(Boolean);
    const match   = players.find(p => pat.test(p.name ?? ""));
    if (match) {
      playerTeamId = match.teamId ?? -1;
      console.error(`[extract-position] "${match.name}" → teamID ${playerTeamId}`);
    } else {
      console.error(`[extract-position] player "${playerFilter}" not found — parsing all teams`);
    }
  } catch (e) {
    console.error(`[extract-position] demo header failed (${e.message}) — parsing all teams`);
  }

  // Headless extraction — reuse cache if valid
  const { runHeadless } = await import(pathToFileURL(path.join(GEX_LIB, "headless.mjs")).href);
  const actionsPath = runHeadless({ demoFile: demoPath, vendorDir: VENDOR_DIR, reuseExisting: true });

  return await parseActions(actionsPath, captureT, playerTeamId, path.basename(demoPath));
}

// ── actions.json parser ────────────────────────────────────────────────────────
async function parseActions(actionsPath, captureT, playerTeamId, label) {
  const captureFrame = Math.floor(captureT * 30);
  // Read a little past T to catch completions that land on the boundary
  const readUntil = captureFrame + 60;

  const defs     = new Map();  // defID → unit_def event
  let   snapshot = null;       // most recent extra_stat_update ≤ captureFrame for player
  const finished = [];         // {frame, defID, defName, unitID} — unit_finished ≤ T
  const placed   = [];         // {frame, defID, defName, unitID} — unit_created ≤ T

  const stream = fs.createReadStream(actionsPath, { encoding: "utf8" });
  const iface  = readline.createInterface({ input: stream, crlfDelay: Infinity });

  for await (const line of iface) {
    if (!line.trim()) continue;
    let ev;
    try { ev = JSON.parse(line); } catch { continue; }

    const { action } = ev;
    const frame = ev.frame ?? 0;

    if (action === "unit_def") {
      defs.set(ev.defID, ev);
      continue;
    }

    if (action === "extra_stat_update" && frame <= captureFrame) {
      if (playerTeamId < 0 || ev.teamID === playerTeamId) snapshot = ev;
      continue;
    }

    if (frame > readUntil) break;

    const mine = playerTeamId < 0 || ev.teamID === playerTeamId;
    if (!mine) continue;

    if (action === "unit_finished" && frame <= captureFrame) {
      const defName = ev.defName ?? defs.get(ev.defID)?.defName ?? `def_${ev.defID}`;
      finished.push({ frame, defID: ev.defID, defName, unitID: ev.unitID });
    }
    if (action === "unit_created" && frame <= captureFrame) {
      const defName = ev.defName ?? defs.get(ev.defID)?.defName ?? `def_${ev.defID}`;
      placed.push({ frame, defID: ev.defID, defName, unitID: ev.unitID });
    }
  }
  iface.close();
  stream.destroy();

  // Count by defName
  const completedCounts = {};
  const placedCounts    = {};
  for (const u of finished) completedCounts[u.defName] = (completedCounts[u.defName] ?? 0) + 1;
  for (const u of placed)   placedCounts[u.defName]    = (placedCounts[u.defName]    ?? 0) + 1;

  // In-progress: placed before T but no matching finish event before T
  const inProgress = {};
  for (const [name, cnt] of Object.entries(placedCounts)) {
    const done = completedCounts[name] ?? 0;
    if (cnt > done) inProgress[name] = cnt - done;
  }

  // Classify completed units
  let mexCount = 0, workerCount = 0, windCount = 0, solarCount = 0;
  for (const u of finished) {
    const d = defs.get(u.defID);
    if (d?.isMetalExtractor)     { mexCount++;    continue; }
    if (isWorkerName(u.defName)) { workerCount++; continue; }
    if (isWindName(u.defName))   { windCount++;   continue; }
    if (isSolarName(u.defName))  { solarCount++;  continue; }
  }

  // Observed eco from nearest snapshot
  const obs  = snapshot ?? {};
  const metalIncome  = obs.metalIncome   ?? 0;
  const energyIncome = obs.energyIncome  ?? 0;
  const metal        = obs.metalCurrent  ?? 0;
  const energy       = obs.energyCurrent ?? 0;
  const storM        = obs.metalStorage  ?? 1000;
  const storE        = obs.energyStorage ?? 1000;

  const isLegion  = finished.some(u => /^leg/i.test(u.defName));
  const model_m   = BASE_M + mexCount * ARM_MEX_M;
  const model_e   = BASE_E + mexCount * ARM_MEX_E + workerCount * WORKER_E
                    + windCount * WIND_E + solarCount * SOLAR_E;
  const extraEPerSec = energyIncome - model_e;

  // synth_mexes for reference: ARM count that best matches observed metal income
  const synth_mexes = Math.max(0, Math.round((metalIncome - BASE_M) / ARM_MEX_M));

  const createState = buildCreateState({
    metal, energy, storM, storE,
    mexes: mexCount,
    solars: solarCount,
    winds:  windCount,
    extraEPerSec,
    workerCount,
  });

  const cal = {
    mexes_completed:   mexCount,
    workers_completed: workerCount,
    winds_completed:   windCount,
    solars_completed:  solarCount,
    model_mIncome:     r3(model_m),
    model_eIncome:     r1(model_e),
    residual_mIncome:  r3(metalIncome - model_m),
    synth_mexes,
  };
  if (isLegion && Math.abs(metalIncome - model_m) > 0.15) {
    const actual_rate = mexCount > 0 ? r3((metalIncome - BASE_M) / mexCount) : "n/a";
    cal.legion_note =
      `${mexCount} mexes completed; ARM model gives ${r3(model_m)} m/s ` +
      `but observed is ${r3(metalIncome)} m/s. ` +
      `Actual Legion mex rate ≈ ${actual_rate} m/s. ` +
      `Use synth_mexes=${synth_mexes} in createState for better metal accuracy ` +
      `(replaces mexes field — eco_engine will use ARM rate as proxy).`;
  }

  return {
    source:   label,
    t:        captureT,
    faction:  isLegion ? "legion" : "arm",
    observed: { metal, energy, storM, storE, metalIncome, energyIncome },
    createState,
    calibration: cal,
    completed: completedCounts,
    inProgress,
    mode: "headless-parse",
  };
}

// ── shared createState builder ─────────────────────────────────────────────────
function buildCreateState({ metal, energy, storM, storE, mexes, solars = 0, winds = 0,
                             extraEPerSec, workerCount = 0 }) {
  return {
    metal,
    energy,
    storM,
    storE,
    mexes,
    solars,
    winds,
    converters: 0,
    extraEPerSec: r1(extraEPerSec),
    builders: [
      { name: "commander", bp: 300, priority: "high" },
      ...Array(workerCount).fill(null).map(() => ({ name: "worker", bp: 80, priority: "normal" })),
    ],
  };
}

// ── unit name classifiers ──────────────────────────────────────────────────────
// Workers: ARM/COR/Legion con bots (T1 and T2)
function isWorkerName(n) {
  return /^(arm|cor|leg)(ck|ack|fark|con)\d*$/i.test(n);
}

// Wind turbines
function isWindName(n) {
  return /^(arm|cor|leg)(vp|win)\d*$/i.test(n);
}

// Solar panels (including advsol)
function isSolarName(n) {
  return /^(arm|cor|leg)(adv)?sol\d*$/i.test(n);
}

// ── numeric helpers ────────────────────────────────────────────────────────────
function r3(n) { return Math.round(n * 1000) / 1000; }
function r1(n) { return Math.round(n * 10) / 10; }

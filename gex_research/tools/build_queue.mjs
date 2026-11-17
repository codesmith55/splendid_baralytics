/**
 * build_queue.mjs — Named position snapshot + build-complete queue from a BAR replay.
 *
 * Produces two sections:
 *   1. POSITION SNAPSHOT at --snap-at seconds (default 50): economy, completed
 *      units/buildings, units currently under construction.
 *   2. BUILD QUEUE from --snap-at to --window (default 8 min = 480s):
 *      every unit_finished event with an inline economy snapshot.
 *
 * Uses unit_finished events (from vendor/gex.lua UnitFinished callback added 2026-06-24).
 * Auto-invalidates cache if existing actions.json pre-dates the UnitFinished addition.
 *
 * Usage:
 *   node tools/build_queue.mjs [game opts] [options]
 *
 * Game options (same as milestone_check.mjs):
 *   --game N          1=last solo game, 2=second-to-last, etc.
 *   --demo <path>     skip game resolution, use this .sdfz directly
 *   --player <name>   player name filter (default: splendi)
 *   --team <id>       override teamId
 *
 * Analysis options:
 *   --snap-at <s>     game time for position snapshot in seconds (default 50)
 *   --window <s>      end time of build queue in seconds (default 480 = 8 min)
 *   --name <str>      name for the position (default: "unnamed")
 *   --map <str>       map name annotation
 *   --pos <str>       starting position number/id (e.g. "6")
 *   --role <str>      player role annotation (e.g. "Tech", "Eco")
 *   --save <path>     save position JSON to this path
 *   --json            output raw JSON instead of formatted text
 */

import { createRequire }  from "node:module";
import fs   from "node:fs";
import path from "node:path";
import rl   from "node:readline";
import { fileURLToPath }  from "node:url";
import { runHeadless }    from "../process/lib/headless.mjs";
import { classifyDef }    from "../process/lib/milestone_engine.mjs";

const __dirname  = path.dirname(fileURLToPath(import.meta.url));
// sdfz-demo-parser lives in demoparser/node_modules — require from that subdirectory
const require    = createRequire(path.join(__dirname, "demoparser", "package.json"));
const { DemoParser } = require("sdfz-demo-parser");
const DEMOS_DIR  = "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data/demos";
const VENDOR_DIR = path.resolve(__dirname, "../vendor");

// ── arg parsing ────────────────────────────────────────────────────────────────

const argv = process.argv.slice(2);
const flags = {};

for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--game")    { flags.game   = argv[++i]; continue; }
  if (a === "--demo")    { flags.demo   = argv[++i]; continue; }
  if (a === "--player")  { flags.player = argv[++i]; continue; }
  if (a === "--team")    { flags.team   = parseInt(argv[++i], 10); continue; }
  if (a === "--snap-at") { flags.snapAt = parseFloat(argv[++i]); continue; }
  if (a === "--window")  { flags.window = parseFloat(argv[++i]); continue; }
  if (a === "--name")    { flags.name   = argv[++i]; continue; }
  if (a === "--map")     { flags.map    = argv[++i]; continue; }
  if (a === "--pos")     { flags.pos    = argv[++i]; continue; }
  if (a === "--role")    { flags.role   = argv[++i]; continue; }
  if (a === "--save")    { flags.save   = argv[++i]; continue; }
  if (a === "--json")    { flags.json   = true;      continue; }
}

const snapAt      = flags.snapAt ?? 50;
const windowS     = flags.window ?? 480;
const playerFilter = (flags.player ?? "splendi").toLowerCase();
const posName     = flags.name ?? "unnamed";
const jsonMode    = flags.json ?? false;

// ── game resolution (same pattern as milestone_check.mjs) ─────────────────────

let demoPath = null;
let teamId   = flags.team ?? null;

if (flags.demo) {
  demoPath = path.resolve(flags.demo);
} else {
  const gameArg = flags.game ?? "last";
  const idx     = /^\d+$/.test(gameArg) ? parseInt(gameArg, 10) : null;
  const pattern = idx === null ? gameArg.toLowerCase() : null;

  let demos = fs.readdirSync(DEMOS_DIR)
    .filter(f => f.toLowerCase().endsWith(".sdfz"))
    .map(f => { const fp = path.join(DEMOS_DIR, f);
                return { file: f, fullPath: fp, mtimeMs: fs.statSync(fp).mtimeMs }; })
    .sort((a, b) => b.mtimeMs - a.mtimeMs);

  if (pattern) demos = demos.filter(d => d.file.toLowerCase().includes(pattern));

  const scanLimit = Math.min(demos.length, 60);
  process.stderr.write(`[build_queue] scanning ${scanLimit} demos for player "${playerFilter}"...\n`);

  let qualifying = [];
  for (const demo of demos.slice(0, scanLimit)) {
    try {
      const d       = await new DemoParser({ skipPackets: true }).parseDemo(demo.fullPath);
      const players = (d.info.players || []).filter(Boolean);
      const target  = players.find(p => p.name?.toLowerCase().includes(playerFilter));
      if (!target) continue;
      const mates   = players.filter(p => p !== target && p.allyTeamId === target.allyTeamId);
      if (mates.length > 0) continue;
      qualifying.push({ ...demo, teamId: target.teamId, playerName: target.name });
    } catch (_) {}
    if (qualifying.length >= (idx ?? 1) + 2) break;
  }

  const pick = idx != null ? qualifying[idx - 1] : qualifying[0];
  if (!pick) {
    process.stderr.write(`[build_queue] no qualifying game found\n`);
    process.exit(1);
  }
  demoPath = pick.fullPath;
  teamId   = teamId ?? pick.teamId;
  process.stderr.write(`[build_queue] game: ${pick.file}\n`);
  process.stderr.write(`[build_queue] player: ${pick.playerName}  teamId: ${teamId}\n`);
}

// ── headless extraction — auto-invalidate cache if it lacks unit_finished ──────

function cacheHasFinishedEvents(actionsPath) {
  if (!fs.existsSync(actionsPath)) return false;
  // Fast scan: check first 200KB for unit_finished events
  const fd  = fs.openSync(actionsPath, "r");
  const buf = Buffer.alloc(204800);
  const n   = fs.readSync(fd, buf, 0, 204800, 0);
  fs.closeSync(fd);
  return buf.slice(0, n).includes(Buffer.from('"unit_finished"'));
}

// Determine tentative cache path (mirrors headless.mjs wd logic)
const tmpBase    = path.join(
  process.env.TEMP || process.env.TMP || "/tmp",
  "gex_harness",
  "wd_" + path.basename(demoPath).replace(/[^\w.-]/g, "_"),
);
const cachedPath = path.join(tmpBase, "actions.json");

// If cached actions.json lacks unit_finished events (pre-dates the gex.lua UnitFinished
// callback added 2026-06-24), force a fresh run; headless.mjs handles the cleanup safely.
const staleCache = fs.existsSync(cachedPath) && !cacheHasFinishedEvents(cachedPath);
if (staleCache) {
  process.stderr.write(`[build_queue] cache lacks unit_finished events — forcing re-run (updated gex.lua)\n`);
}

process.stderr.write(`[build_queue] headless extraction (reuseExisting=${!staleCache})...\n`);
const actionsPath = runHeadless({ demoFile: demoPath, vendorDir: VENDOR_DIR, reuseExisting: !staleCache });

// ── actions.json parsing ───────────────────────────────────────────────────────

const MAX_FRAME  = windowS * 30;
const SNAP_FRAME = snapAt  * 30;

const defs    = new Map();  // defID → full unit_def object + classified class
const eco     = [];         // [{frame, metalCurrent, energyCurrent, metalIncome, energyIncome, metalStorage, energyStorage, totalValue}]
const placed  = [];         // {frame, unitID, defID, defName, defClass}  (unit_created)
const finished= [];         // {frame, unitID, defID, defName, defClass}  (unit_finished)
const died    = new Set();  // unitIDs that died before windowS

process.stderr.write(`[build_queue] parsing ${path.basename(actionsPath)}...\n`);

{
  const stream = fs.createReadStream(actionsPath, { encoding: "utf8" });
  const reader = rl.createInterface({ input: stream, crlfDelay: Infinity });
  for await (const line of reader) {
    if (!line.trim()) continue;
    let ev; try { ev = JSON.parse(line); } catch (_) { continue; }

    if (ev.action === "unit_def") {
      defs.set(ev.defID, { ...ev, defClass: classifyDef(ev) });
      continue;
    }

    const f = ev.frame ?? 0;
    if (f > MAX_FRAME && ev.action !== "extra_stat_update") continue;  // still need eco past window for snapshots

    if (ev.action === "extra_stat_update" && ev.teamID === teamId) {
      if (f <= MAX_FRAME + 450) {  // capture a bit past window for final snapshot
        eco.push({
          frame:         f,
          game_s:        f / 30,
          metalCurrent:  ev.metalCurrent  ?? 0,
          energyCurrent: ev.energyCurrent ?? 0,
          metalIncome:   ev.metalIncome   ?? 0,
          energyIncome:  ev.energyIncome  ?? 0,
          metalStorage:  ev.metalStorage  ?? 1000,
          energyStorage: ev.energyStorage ?? 1000,
          totalValue:    ev.totalValue    ?? 0,
        });
      }
      continue;
    }

    if (f > MAX_FRAME) continue;

    if (ev.action === "unit_created" && ev.teamID === teamId) {
      const def = defs.get(ev.defID) ?? {};
      placed.push({ frame: f, unitID: ev.unitID, defID: ev.defID,
                    defName: ev.defName ?? def.defName ?? "?", defClass: def.defClass ?? "unit" });
    }
    if (ev.action === "unit_finished" && ev.teamID === teamId) {
      const def = defs.get(ev.defID) ?? {};
      finished.push({ frame: f, unitID: ev.unitID, defID: ev.defID,
                      defName: ev.defName ?? def.defName ?? "?", defClass: def.defClass ?? "unit" });
    }
    if (ev.action === "unit_killed" && ev.teamID === teamId) {
      died.add(ev.unitID);
    }
  }
  reader.close(); stream.destroy();
}

process.stderr.write(`[build_queue] parsed: ${placed.length} placed  ${finished.length} finished  ${eco.length} eco updates\n`);

// ── helpers ────────────────────────────────────────────────────────────────────

function ecoAt(frame) {
  // Most recent extra_stat_update at or before frame
  let best = null;
  for (const e of eco) { if (e.frame <= frame) best = e; else break; }
  return best ?? eco[0] ?? { metalCurrent: 0, energyCurrent: 0, metalIncome: 0, energyIncome: 0,
                              metalStorage: 1000, energyStorage: 1000, totalValue: 0, game_s: 0, frame: 0 };
}

function ecoLine(e) {
  const m = e.metalCurrent.toFixed(0);
  const ms = e.metalStorage.toFixed(0);
  const mi = (e.metalIncome >= 0 ? "+" : "") + e.metalIncome.toFixed(2);
  const en = e.energyCurrent.toFixed(0);
  const es = e.energyStorage.toFixed(0);
  const ei = (e.energyIncome >= 0 ? "+" : "") + e.energyIncome.toFixed(1);
  const tpv = (e.totalValue + e.metalCurrent + e.energyCurrent / 70).toFixed(0);
  return `m=${m.padStart(4)}/${ms}(${mi}/s)  e=${en.padStart(4)}/${es}(${ei}/s)  TPV≈${tpv}`;
}

function fmt(s) {
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed(1).padStart(4, "0");
  return `${m}:${sec}`;
}

// unit counts at a given frame (units placed before frame, not dead)
function unitCountsAt(frame) {
  const counts = {};
  for (const p of placed) {
    if (p.frame > frame) break;
    if (!died.has(p.unitID)) {
      counts[p.defName] = (counts[p.defName] ?? 0) + 1;
    }
  }
  return counts;
}

// units completed (unit_finished) before a given frame, not dead
function completedAt(frame) {
  const counts = {};
  for (const f of finished) {
    if (f.frame > frame) break;
    if (!died.has(f.unitID)) {
      counts[f.defName] = (counts[f.defName] ?? 0) + 1;
    }
  }
  return counts;
}

// units placed but not yet finished at a given frame
function inProgressAt(frame) {
  const finishedIds = new Set(finished.filter(f => f.frame <= frame).map(f => f.unitID));
  return placed
    .filter(p => p.frame <= frame && !finishedIds.has(p.unitID) && !died.has(p.unitID))
    .map(p => {
      const def      = defs.get(p.defID) ?? {};
      const buildT   = (def.buildTime ?? 0) / 300;  // sec at commander BP=300
      const startS   = p.frame / 30;
      const estFinish = startS + buildT;
      return { ...p, startS, estFinish: Math.max(estFinish, startS + 1) };
    });
}

// ── position snapshot data ─────────────────────────────────────────────────────

const snapEco       = ecoAt(SNAP_FRAME);
const snapCompleted = completedAt(SNAP_FRAME);
const snapInProgress= inProgressAt(SNAP_FRAME);
const snapTPV       = snapEco.totalValue + snapEco.metalCurrent + snapEco.energyCurrent / 70;

// classify buildings vs mobile
function splitUnitList(countMap) {
  const buildings = {}, mobile = {};
  for (const [defName, cnt] of Object.entries(countMap)) {
    const def = [...defs.values()].find(d => d.defName === defName);
    if (!def || (def.speed ?? 0) === 0) buildings[defName] = cnt;
    else mobile[defName] = cnt;
  }
  return { buildings, mobile };
}

const { buildings: snapBuildings, mobile: snapMobile } = splitUnitList(snapCompleted);

// ── build-queue events (unit_finished from snapAt to windowS) ─────────────────

// Running unit counts for the queue (track as we iterate)
let runCounts = {};
for (const f of finished) {
  if (f.frame > SNAP_FRAME) break;
  if (!died.has(f.unitID)) {
    runCounts[f.defName] = (runCounts[f.defName] ?? 0) + 1;
  }
}

const queueEvents = finished
  .filter(f => f.frame > SNAP_FRAME && f.frame <= MAX_FRAME && !died.has(f.unitID))
  .map(f => {
    runCounts = { ...runCounts };
    runCounts[f.defName] = (runCounts[f.defName] ?? 0) + 1;
    const e = ecoAt(f.frame);
    const def = defs.get(f.defID) ?? {};
    const isBuilding = (def.speed ?? 0) === 0;
    return {
      frame:     f.frame,
      game_s:    f.frame / 30,
      defName:   f.defName,
      defClass:  f.defClass,
      isBuilding,
      count:     runCounts[f.defName],
      eco:       e,
      ecoLine:   ecoLine(e),
    };
  });

// If no unit_finished events (fallback: use unit_created with a note)
const useFinished   = finished.length > 0;
const fallbackQueue = !useFinished
  ? placed.filter(p => p.frame > SNAP_FRAME && p.frame <= MAX_FRAME && !died.has(p.unitID))
          .map(p => {
            const e = ecoAt(p.frame);
            return { frame: p.frame, game_s: p.frame/30, defName: p.defName,
                     defClass: p.defClass, isBuilding: (defs.get(p.defID)?.speed??0)===0,
                     eco: e, ecoLine: ecoLine(e), isStart: true };
          })
  : [];

const queue = useFinished ? queueEvents : fallbackQueue;

// ── JSON output ────────────────────────────────────────────────────────────────

const positionDoc = {
  _meta: {
    name:        posName,
    map:         flags.map  ?? null,
    position:    flags.pos  ?? null,
    role:        flags.role ?? null,
    source:      path.basename(demoPath),
    capture_t:   snapAt,
    notes:       `Captured from headless replay at T=${snapAt}s`,
  },
  state: {
    t:            snapAt,
    metal:        +snapEco.metalCurrent.toFixed(1),
    energy:       +snapEco.energyCurrent.toFixed(1),
    metalStorage: +snapEco.metalStorage.toFixed(0),
    energyStorage:+snapEco.energyStorage.toFixed(0),
    metalIncome:  +snapEco.metalIncome.toFixed(3),
    energyIncome: +snapEco.energyIncome.toFixed(1),
    totalValue:   +snapEco.totalValue.toFixed(0),
    tpv:          +snapTPV.toFixed(0),
    completed:    snapCompleted,
    inProgress:   snapInProgress.map(p => ({
      defName:    p.defName,
      startS:     +p.startS.toFixed(1),
      estFinishS: +p.estFinish.toFixed(1),
    })),
    buildings:    snapBuildings,
    mobile:       snapMobile,
  },
  build_queue: queue.map(q => ({
    t:        +q.game_s.toFixed(1),
    frame:    q.frame,
    defName:  q.defName,
    defClass: q.defClass,
    count:    q.count,
    eco: {
      metal:        +q.eco.metalCurrent.toFixed(1),
      energy:       +q.eco.energyCurrent.toFixed(1),
      metalIncome:  +q.eco.metalIncome.toFixed(3),
      energyIncome: +q.eco.energyIncome.toFixed(1),
      tpv:          +(q.eco.totalValue + q.eco.metalCurrent + q.eco.energyCurrent/70).toFixed(0),
    },
  })),
};

if (flags.save) {
  fs.writeFileSync(flags.save, JSON.stringify(positionDoc, null, 2));
  process.stderr.write(`[build_queue] position saved -> ${flags.save}\n`);
}

if (jsonMode) {
  process.stdout.write(JSON.stringify(positionDoc, null, 2));
  process.exit(0);
}

// ── human-readable output ──────────────────────────────────────────────────────

const W    = 78;
const bar  = "═".repeat(W);
const dash = "─".repeat(W);

console.log(bar);
console.log(`  BUILD QUEUE — ${path.basename(demoPath).slice(0, 40)}`);
console.log(`  Player: ${playerFilter}  teamId: ${teamId}`);
console.log(`  Map: ${flags.map ?? "(not set)"}  |  Pos: ${flags.pos ?? "-"}  |  Role: ${flags.role ?? "-"}`);
console.log(`  Window: T=0:00 → T=${fmt(windowS)}`);
console.log(bar);

// Pre-snapshot build events (placed events, showing setup)
console.log(`  PRE-SNAPSHOT BUILD LOG (T=0 → T=${fmt(snapAt)}):`);
console.log();
const preEvents = placed.filter(p => p.frame <= SNAP_FRAME);
for (const p of preEvents) {
  const e    = ecoAt(p.frame);
  const def  = defs.get(p.defID) ?? {};
  const bt   = (def.buildTime ?? 0) / 300;
  const cls  = p.defClass.padEnd(11);
  const cnt  = (runCounts[p.defName] ?? 0) + 1;
  // count of this type placed so far
  console.log(
    `  T=${fmt(p.frame/30).padStart(7)}  ${p.defName.padEnd(18)} PLACED  [${cls} ×${cnt}]   ${ecoLine(e)}`
  );
}

// ── POSITION SNAPSHOT ─────────────────────────────────────────────────────────

console.log();
console.log(dash);
console.log(`  POSITION SNAPSHOT @ T=${fmt(snapAt)}  —  "${posName}"`);
if (flags.map)  console.log(`  Map: ${flags.map}  |  Position: ${flags.pos ?? "-"}  |  Role: ${flags.role ?? "-"}`);
console.log(dash);
console.log();
console.log(`  Economy:`);
console.log(`    metal  = ${snapEco.metalCurrent.toFixed(0).padStart(5)} / ${snapEco.metalStorage.toFixed(0).padStart(5)}  (${(snapEco.metalIncome>=0?"+":"")+snapEco.metalIncome.toFixed(2)} m/s)`);
console.log(`    energy = ${snapEco.energyCurrent.toFixed(0).padStart(5)} / ${snapEco.energyStorage.toFixed(0).padStart(5)}  (${(snapEco.energyIncome>=0?"+":"")+snapEco.energyIncome.toFixed(1)} e/s)`);
console.log(`    TPV    ≈ ${snapTPV.toFixed(0)}`);
console.log();

if (Object.keys(snapBuildings).length > 0 || Object.keys(snapMobile).length > 0) {
  const fmtCounts = obj => Object.entries(obj).map(([n,c]) => `${n}×${c}`).join("  ");
  if (Object.keys(snapBuildings).length > 0)
    console.log(`  Completed buildings:  ${fmtCounts(snapBuildings)}`);
  if (Object.keys(snapMobile).length > 0)
    console.log(`  Completed mobile:     ${fmtCounts(snapMobile)}`);
  if (Object.keys(snapCompleted).length === 0)
    console.log(`  Completed: (none — eco data may be from T=0; check if unit_finished events present)`);
} else {
  // Fallback: use placed counts if no finished events
  const allPlaced = unitCountsAt(SNAP_FRAME);
  const { buildings: pb, mobile: pm } = splitUnitList(allPlaced);
  if (Object.keys(pb).length > 0)
    console.log(`  Placed buildings:     ${Object.entries(pb).map(([n,c])=>`${n}×${c}`).join("  ")}  (placement time, not completion)`);
  if (Object.keys(pm).length > 0)
    console.log(`  Placed mobile:        ${Object.entries(pm).map(([n,c])=>`${n}×${c}`).join("  ")}`);
}

if (snapInProgress.length > 0) {
  console.log();
  console.log(`  Under construction:`);
  for (const p of snapInProgress) {
    console.log(`    ${p.defName.padEnd(18)}  started T=${fmt(p.startS)}  est. finish T=${fmt(p.estFinish)}`);
  }
}

if (!useFinished) {
  console.log();
  console.log(`  ⚠ unit_finished events not found in this cache — re-run with --force to refresh.`);
  console.log(`    Build times shown are placement times (unit_created), not completion.`);
}

// ── BUILD QUEUE ────────────────────────────────────────────────────────────────

console.log();
console.log(dash);
console.log(`  BUILD QUEUE  T=${fmt(snapAt)} → T=${fmt(windowS)}  (${useFinished ? "COMPLETION" : "placement ⚠"}  events)`);
console.log(dash);
console.log(`  ${"T".padEnd(8)}  ${"unit".padEnd(20)}  ${"class".padEnd(11)}  economy`);
console.log(`  ${"-".repeat(8)}  ${"-".repeat(20)}  ${"-".repeat(11)}  ${"-".repeat(30)}`);

if (queue.length === 0) {
  console.log(`  (no build events in this window)`);
} else {
  for (const q of queue) {
    const tag = q.isBuilding ? "BLDG" : "UNIT";
    console.log(
      `  ${fmt(q.game_s).padEnd(8)}  ${q.defName.padEnd(20)}  ${q.defClass.padEnd(11)}  ${q.ecoLine}`
    );
  }
}

console.log(bar);
if (flags.save) console.log(`  Position JSON saved -> ${flags.save}`);
console.log(`  NOTE: timings are unit_finished (build completion).`);
console.log(`  Eco snapshots are from nearest prior extra_stat_update (±15s resolution).`);
console.log(bar);

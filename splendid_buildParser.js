"use strict";
// splendid_buildParser.js — pull build-relevant facts out of a BAR game.
//
//   node splendid_buildParser.js <source> [--team N | --me <name>] [--every <sec>] [--until <sec>|full]
//                                          [--json <out.json>] [--defs <ref.jsonl>] [--dir <demosDir>]
//
// <source> is one of
//   • a widget JSONL      (live/games/<id>.jsonl, live/bar_analytic_live.jsonl, or any *.jsonl)
//   • a .sdfz demo        (path, filename inside the demos dir, or "latest")
//   • a 1-based index     into live/games/ sorted newest-first ("1" = newest archived game)
//
// It produces a `Game` — the single input shape the simulator (splendid_buildSimulator.js)
// and strategizer (splendid_buildStrategizer.js) consume:
//
//   game.teams      Map<teamID, {name, ally, faction, isAI, startX, startZ}>
//   game.defs       Map<defID,  {defName, name, metal, energy, buildPower, isMex, isFactory, isCommander, convCap}>
//   game.moments    reality snapshots, one per team per `every` seconds (see makeMoment for the shape)
//   game.events     normalized unit lifecycle + build orders, frame-ordered
//   game.mexSpots   every distinct spot a mex was ever placed on (≈ the map's metal spots)
//   game.wind       [{sec, value}] wind samples (widget only)
//
// Reality coverage differs by source, and every moment says what it actually knows:
//   widget JSONL  → bank, storage, income, build power, unit counts, builder positions   (full)
//   .sdfz demo    → income from cumulative teamStats; bank DERIVED from the counters;
//                   build ORDERS (with map positions) from the command stream; no unit roster.
// The simulator treats unknown fields as "keep the simulated value".
//
// The economy-series helpers the analyzer used to own (computeSeries, trimEndFlush,
// loadValueFlow, …) live here now; splendid_buildAnalyzer.js requires them from this file.

const fs = require("fs");
const path = require("path");
const readline = require("readline");

const FPS = 30;                  // BAR sim frames per second
const VALUE_E_DIV = 70;          // energy→metal value conversion (repo convention)
const MIN_PEAK = 40;             // ignore "collapses" of trivially small economies (value/s)
const START_BANK = 1000;         // starting metal & energy (also the T1 storage cap)
const MEX_SPOT_GRID = 48;        // elmos; two mex placements closer than this are one spot

const ROOT = __dirname;
const LIVE_GAMES_DIR = path.join(ROOT, "live", "games");
const DEMO_DIRS = [
  process.env.BAR_DEMOS,
  "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data/demos",
  process.env.HOME && path.join(process.env.HOME, ".local/state/Beyond All Reason/demos"),
].filter(Boolean);

// ---------------------------------------------------------------- parser resolution
function loadDemoParser() {
  const attempts = [
    "sdfz-demo-parser",
    "./gex_research/tools/demoparser/node_modules/sdfz-demo-parser",
    "./sdfz-demo-parser",
  ];
  for (const id of attempts) {
    try {
      const mod = require(id.startsWith("./") ? path.join(ROOT, id) : id);
      if (typeof mod.DemoParser === "function") return mod.DemoParser;
    } catch (_) { /* try next */ }
  }
  throw new Error(
    "sdfz-demo-parser not found. Run `npm install` here, or keep " +
    "gex_research/tools/demoparser/node_modules installed."
  );
}

function demosDir(override) {
  const dirs = override ? [override, ...DEMO_DIRS] : DEMO_DIRS;
  for (const d of dirs) { try { if (fs.statSync(d).isDirectory()) return d; } catch (_) {} }
  return null;
}

function resolveDemo(arg, dirOverride) {
  if (arg && arg !== "latest" && fs.existsSync(arg)) return arg;
  const dir = demosDir(dirOverride);
  if (!dir) throw new Error("no demos directory found; pass a demo path or --dir <dir>");
  if (arg && arg !== "latest") {
    const direct = path.join(dir, arg);
    if (fs.existsSync(direct)) return direct;
  }
  const demos = fs.readdirSync(dir).filter(f => f.endsWith(".sdfz"))
    .map(f => ({ f, m: fs.statSync(path.join(dir, f)).mtimeMs }))
    .sort((x, y) => y.m - x.m);
  if (!demos.length) throw new Error(`no .sdfz demos in ${dir}`);
  return path.join(dir, demos[0].f);
}

/** Archived widget games, newest first. */
function listArchivedGames() {
  if (!fs.existsSync(LIVE_GAMES_DIR)) return [];
  return fs.readdirSync(LIVE_GAMES_DIR).filter(f => f.endsWith(".jsonl"))
    .map(f => path.join(LIVE_GAMES_DIR, f))
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
}

/** "1" → newest archive, "latest"/".sdfz" → demo, "*.jsonl" → widget stream. */
function resolveSource(ref, dirOverride) {
  if (/^\d+$/.test(ref)) {
    const games = listArchivedGames();
    const g = games[Number(ref) - 1];
    if (!g) throw new Error(`no archived game #${ref} (have ${games.length})`);
    return { kind: "widget", path: g };
  }
  if (ref.endsWith(".jsonl")) {
    if (!fs.existsSync(ref)) throw new Error(`no such file: ${ref}`);
    return { kind: "widget", path: ref };
  }
  return { kind: "demo", path: resolveDemo(ref, dirOverride) };
}

// ------------------------------------------------------------------------- team meta
function buildTeamMeta(info) {
  const meta = new Map(); // teamId -> { name, ally, faction, isAI, startX, startZ }
  for (const p of info.players || [])
    meta.set(p.teamId, { name: p.name, ally: p.allyTeamId, faction: p.faction || "?", isAI: false,
      startX: p.startPos ? p.startPos.x : null, startZ: p.startPos ? p.startPos.z : null });
  for (const ai of info.ais || [])
    meta.set(ai.teamId, { name: ai.name || `AI ${ai.teamId}`, ally: ai.allyTeamId, faction: ai.faction || "AI", isAI: true,
      startX: ai.startPos ? ai.startPos.x : null, startZ: ai.startPos ? ai.startPos.z : null });
  return meta;
}

// ------------------------------------------------- differentiate cumulative -> rates
// Per-team series of { frame, sec, econ, metalInc, energyInc, buildUse, waste, ... }
function computeSeries(teamStats) {
  const out = new Map();
  for (const key of Object.keys(teamStats)) {
    const teamId = Number(key);
    const samples = teamStats[key];
    if (!samples || samples.length < 2) { out.set(teamId, []); continue; }
    const series = [];
    for (let i = 1; i < samples.length; i++) {
      const a = samples[i - 1], b = samples[i];
      const dt = Math.max((b.frame - a.frame) / FPS, 1e-6);
      const metalInc = (b.metalProduced - a.metalProduced) / dt;
      const energyInc = (b.energyProduced - a.energyProduced) / dt;
      const econ = metalInc + energyInc / VALUE_E_DIV;
      const buildUse = (b.metalUsed - a.metalUsed) / dt
        + ((b.energyUsed - a.energyUsed) / dt) / VALUE_E_DIV;
      const waste = (b.metalExcess - a.metalExcess) / dt
        + ((b.energyExcess - a.energyExcess) / dt) / VALUE_E_DIV;
      series.push({
        frame: b.frame,
        sec: b.frame / FPS,
        econ, metalInc, energyInc, buildUse, waste,
        dmgRecvRate: (b.damageReceived - a.damageReceived) / dt,
        unitsDiedRate: (b.unitsDied - a.unitsDied) / dt,
        cumUnitsDied: b.unitsDied,
        cumDmgRecv: b.damageReceived,
        dDealt: b.damageDealt - a.damageDealt,
        dTaken: b.damageReceived - a.damageReceived,
        dKilled: b.unitsKilled - a.unitsKilled,
        dLost: b.unitsDied - a.unitsDied,
        dBuilt: b.unitsProduced - a.unitsProduced,
        dProduced: (b.metalProduced - a.metalProduced) + (b.energyProduced - a.energyProduced) / VALUE_E_DIV,
        // derived bank: what the cumulative counters imply is sitting in storage now
        metalBank: START_BANK + b.metalProduced + b.metalReceived - b.metalUsed - b.metalSent - b.metalExcess,
        energyBank: START_BANK + b.energyProduced + b.energyReceived - b.energyUsed - b.energySent - b.energyExcess,
      });
    }
    out.set(teamId, series);
  }
  return out;
}

// Drop the game-end economy crater artifact (broad simultaneous drop on the last sample).
function trimEndFlush(seriesMap, maxTrim = 2) {
  let trimmed = 0;
  for (let pass = 0; pass < maxTrim; pass++) {
    const arrs = [...seriesMap.values()].filter(s => s.length >= 2);
    if (arrs.length < 3) break;
    const len = Math.max(...arrs.map(s => s.length));
    const ratios = [];
    for (const s of arrs) {
      if (s.length !== len) continue;
      const last = s[s.length - 1].econ, prev = s[s.length - 2].econ;
      if (prev > MIN_PEAK) ratios.push(last / prev);
    }
    if (ratios.length < 3) break;
    ratios.sort((a, b) => a - b);
    const median = ratios[Math.floor(ratios.length / 2)];
    if (median >= 0.5) break;
    for (const [k, s] of seriesMap) if (s.length === len) seriesMap.set(k, s.slice(0, -1));
    trimmed++;
  }
  return trimmed;
}

// ---------------------------------------------------- unit value flow (headless lifecycle)
// value = metal + e/70, commander = flat 1200. Returns Map<teamId,{built[],lost[]}>.
function loadValueFlow(actionsPath, bucketSec, nBuckets) {
  const lines = fs.readFileSync(actionsPath, "utf8").split(/\r?\n/);
  const bf = bucketSec * FPS;
  const val = new Map();
  const events = [];
  for (const ln of lines) {
    if (!ln) continue;
    let e; try { e = JSON.parse(ln); } catch { continue; }
    if (e.action === "unit_def") {
      const com = e.isCommander === true || /com$/.test(e.defName || "");
      val.set(e.defID, com ? 1200 : (e.metalCost || 0) + (e.energyCost || 0) / VALUE_E_DIV);
    } else events.push(e);
  }
  const flow = new Map();
  const ensure = t => { if (!flow.has(t)) flow.set(t, { built: new Array(nBuckets).fill(0), lost: new Array(nBuckets).fill(0) }); return flow.get(t); };
  for (const e of events) {
    if (typeof e.frame !== "number" || typeof e.teamID !== "number") continue;
    const bi = Math.min(nBuckets - 1, Math.floor(e.frame / bf));
    if (bi < 0) continue;
    if (e.action === "unit_created" || e.action === "factory_unit_created") ensure(e.teamID).built[bi] += val.get(e.defID) || 0;
    else if (e.action === "unit_killed") ensure(e.teamID).lost[bi] += val.get(e.defID) || 0;
  }
  return flow;
}

// ------------------------------------------------------------------ unit definitions
function normDef(e) {
  return {
    defID: e.defID, defName: e.defName, name: e.name || e.defName,
    metal: e.metalCost || 0, energy: e.energyCost || 0,
    buildPower: e.buildPower || 0,
    isMex: !!e.isMetalExtractor, isFactory: !!e.isFactory, isCommander: !!e.isCommander,
    convCap: e.energyConversionCapacity || 0,
  };
}

/** defID → def table from any widget JSONL (only reads the unit_def lines). */
async function loadDefsFromJsonl(file) {
  const defs = new Map();
  const rl = readline.createInterface({ input: fs.createReadStream(file), crlfDelay: Infinity });
  for await (const ln of rl) {
    if (!ln.includes('"unit_def"')) continue;
    let e; try { e = JSON.parse(ln); } catch { continue; }
    if (e.action === "unit_def") defs.set(e.defID, normDef(e));
  }
  rl.close();
  return defs;
}

// ---------------------------------------------------------------------- moments
/**
 * A moment = what reality says about ONE team at ONE frame. `known` lists which
 * fields are measured (true), derived (string) or absent (false).
 */
function makeMoment(base) {
  return Object.assign({
    frame: 0, sec: 0, teamID: null,
    metal: null, energy: null, storM: null, storE: null,
    mIncome: null, eIncome: null, bpAvail: null, bpUsed: null,
    nMex: null, nConv: null, wind: null,
    units: null,          // {defName: finishedCount}
    building: null,       // [{unitID, defName, x, z, sinceFrame}] under construction
    builders: null,       // [{unitID, defName, bp, x, z, idle, building, isFactory}]
    orders: null,         // demo: build orders issued in the interval ending here [{sec, defName, defID, x, z}]
    known: { bank: false, storage: false, income: false, buildPower: false, units: false, builders: false },
  }, base);
}

function spotKey(x, z) { return `${Math.round(x / MEX_SPOT_GRID)}:${Math.round(z / MEX_SPOT_GRID)}`; }

// ------------------------------------------------------------- widget JSONL → Game
async function parseWidget(file, { every = 15, until = Infinity, onlyTeam = null } = {}) {
  const game = {
    source: "widget", path: file, map: null, mapSize: null,
    teams: new Map(), defs: new Map(), moments: [], events: [], mexSpots: [], wind: [],
    lastFrame: 0, every,
  };
  const spots = new Map();
  const roster = new Map();      // unitID -> {teamID, defID, defName, x, z, finished, createdFrame}
  const builderPos = new Map();  // unitID -> {x, z, idle, building, frame, teamID, defID}
  const nextSample = new Map();  // teamID -> next frame to sample at
  let wind = 0;
  const stepFrames = every * FPS;
  const untilFrame = until * FPS;

  const rl = readline.createInterface({ input: fs.createReadStream(file), crlfDelay: Infinity });
  for await (const ln of rl) {
    if (!ln) continue;
    let e; try { e = JSON.parse(ln); } catch { continue; }
    const a = e.action;
    if (typeof e.frame === "number") {
      if (e.frame > untilFrame) break;
      if (e.frame > game.lastFrame) game.lastFrame = e.frame;
    }
    switch (a) {
      case "session": game.map = e.mapName; break;
      case "start": game.mapSize = { x: e.mapSizeX, z: e.mapSizeZ }; break;
      case "session_team":
        game.teams.set(e.teamID, { name: e.name, ally: e.allyTeamID, faction: e.side, isAI: !!e.isAI,
          startX: e.startX || null, startZ: e.startZ || null });
        break;
      case "team_spawn": {
        const t = game.teams.get(e.teamID) || { name: `team ${e.teamID}`, ally: null, faction: "?", isAI: false };
        t.startX = e.startX; t.startZ = e.startZ; game.teams.set(e.teamID, t);
        break;
      }
      case "unit_def": game.defs.set(e.defID, normDef(e)); break;
      case "wind_update": wind = e.value; game.wind.push({ sec: e.frame / FPS, value: e.value }); break;
      case "unit_created": {
        const d = game.defs.get(e.defID);
        const defName = e.defName || (d && d.defName) || String(e.defID);
        roster.set(e.unitID, { teamID: e.teamID, defID: e.defID, defName, x: e.unit_x, z: e.unit_z, finished: false, createdFrame: e.frame });
        if (d && d.isMex) { const k = spotKey(e.unit_x, e.unit_z); if (!spots.has(k)) spots.set(k, { x: e.unit_x, z: e.unit_z }); }
        game.events.push({ kind: "created", frame: e.frame, sec: e.frame / FPS, teamID: e.teamID, unitID: e.unitID, defName, x: e.unit_x, z: e.unit_z });
        break;
      }
      case "unit_finished": {
        const u = roster.get(e.unitID);
        if (u) { u.finished = true; u.finishedFrame = e.frame; }
        game.events.push({ kind: "finished", frame: e.frame, sec: e.frame / FPS, teamID: e.teamID, unitID: e.unitID, defName: e.defName || (u && u.defName) });
        break;
      }
      case "unit_killed": {
        const u = roster.get(e.unitID);
        game.events.push({ kind: "killed", frame: e.frame, sec: e.frame / FPS, teamID: e.teamID, unitID: e.unitID, defName: e.defName || (u && u.defName),
          finished: !!(u && u.finished), attackerTeam: e.attackerTeam });
        roster.delete(e.unitID); builderPos.delete(e.unitID);
        break;
      }
      case "unit_given": case "unit_taken": {
        const u = roster.get(e.unitID); if (u) u.teamID = e.newTeamID;
        const b = builderPos.get(e.unitID); if (b) b.teamID = e.newTeamID;
        break;
      }
      case "builder_status":
        builderPos.set(e.unitID, { teamID: e.teamID, defID: e.defID, x: e.x, z: e.z, idle: !!e.idle, building: !!e.building, frame: e.frame });
        break;
      case "extra_stat_update": {
        if (onlyTeam != null && e.teamID !== onlyTeam) break;
        const due = nextSample.get(e.teamID) ?? 0;
        if (e.frame < due) break;
        nextSample.set(e.teamID, due + stepFrames * Math.max(1, Math.ceil((e.frame - due + 1) / stepFrames)));
        game.moments.push(momentFromWidget(e, game, roster, builderPos, wind));
        break;
      }
      default: break;
    }
  }
  rl.close();
  game.mexSpots = [...spots.values()];
  return game;
}

function momentFromWidget(e, game, roster, builderPos, wind) {
  const units = {}, building = [];
  for (const [unitID, u] of roster) {
    if (u.teamID !== e.teamID) continue;
    if (u.finished) units[u.defName] = (units[u.defName] || 0) + 1;
    else building.push({ unitID, defName: u.defName, x: u.x, z: u.z, sinceFrame: u.createdFrame });
  }
  const builders = [];
  for (const [unitID, b] of builderPos) {
    if (b.teamID !== e.teamID) continue;
    const u = roster.get(unitID); if (u && !u.finished) continue;   // a builder still being built has no BP yet
    const d = game.defs.get(b.defID);
    builders.push({ unitID, defName: d ? d.defName : String(b.defID), bp: d ? d.buildPower : 0,
      x: b.x, z: b.z, idle: b.idle, building: b.building, isFactory: !!(d && d.isFactory) });
  }
  return makeMoment({
    frame: e.frame, sec: e.frame / FPS, teamID: e.teamID,
    metal: e.metalCurrent, energy: e.energyCurrent, storM: e.metalStorage, storE: e.energyStorage,
    mIncome: e.metalIncome, eIncome: e.energyIncome, bpAvail: e.buildPowerAvailable, bpUsed: e.buildPowerUsed,
    nMex: e.nMex, nConv: e.nConv, wind,
    totalValue: e.totalValue, ecoValue: e.ecoValue, militaryValue: e.militaryValue,
    units, building, builders,
    known: { bank: true, storage: true, income: true, buildPower: true, units: true, builders: true },
  });
}

// --------------------------------------------------------------- .sdfz demo → Game
async function parseDemoFile(file, { every = 15, until = Infinity, onlyTeam = null, defsFrom = null } = {}) {
  const DemoParser = loadDemoParser();
  // build orders: cmdId < 0 in a COMMAND packet is a build of unitDef |cmdId| at (x,y,z)
  const orders = [];
  const parser = new DemoParser({ verbose: false });
  parser.onPacket.add(p => {
    if (p.id !== 11 /* COMMAND */ && p.id !== 14 /* AICOMMAND */) return;
    const c = p.data && p.data.command;
    if (!c || c.unitDefId == null) return;
    const d = c.data || {};
    if (typeof d.x !== "number") return;
    // sdfz-demo-parser resolves build ids to engine names ("armmex") when it can; else a numeric defID
    const raw = c.unitDefId;
    const asNum = typeof raw === "number" ? Math.abs(raw) : (/^-?\d+$/.test(String(raw)) ? Math.abs(Number(raw)) : null);
    orders.push({ sec: p.actualGameTime, playerNum: p.data.playerNum, defID: asNum, defName: asNum == null ? String(raw) : null,
      x: d.x, z: d.z, facing: d.direction, shift: !!(c.options && c.options.SHIFT_KEY) });
  });
  const demo = await parser.parseDemo(file);
  const info = demo.info || {};
  const meta = info.meta || {};
  const teamStats = (demo.statistics && demo.statistics.teamStats) || {};

  const game = {
    source: "demo", path: file, map: meta.map || null, mapSize: null,
    teams: buildTeamMeta(info), defs: new Map(), moments: [], events: [], mexSpots: [], wind: [],
    lastFrame: 0, every, meta, teamStats, demo,
  };
  // unit-def names: the demo has none; borrow a table from a widget stream of the same game version
  const refJsonl = defsFrom || listArchivedGames()[0];
  if (refJsonl) { game.defs = await loadDefsFromJsonl(refJsonl); game.defsFrom = refJsonl; }
  const playerTeam = new Map();
  for (const p of info.players || []) playerTeam.set(p.playerId, p.teamId);
  const defByName = new Map();
  for (const d of game.defs.values()) defByName.set(d.defName, d);

  const series = computeSeries(teamStats);
  trimEndFlush(series);
  game.series = series;
  const spots = new Map();
  for (const o of orders) {
    const teamID = playerTeam.get(o.playerNum);
    if (teamID == null) continue;
    const d = o.defID != null ? game.defs.get(o.defID) : defByName.get(o.defName);
    o.teamID = teamID; o.frame = Math.round(o.sec * FPS);
    if (d) { o.defName = d.defName; o.defID = d.defID; } else if (o.defName == null) o.defName = String(o.defID);
    const isMex = d ? d.isMex : /mex$/.test(o.defName);
    if (isMex) { const k = spotKey(o.x, o.z); if (!spots.has(k)) spots.set(k, { x: o.x, z: o.z }); }
    game.events.push({ kind: "order", frame: o.frame, sec: o.sec, teamID, defName: o.defName, defID: o.defID, x: o.x, z: o.z, shift: o.shift });
  }
  game.events.sort((a, b) => a.frame - b.frame);
  game.mexSpots = [...spots.values()];

  const stepFrames = every * FPS;
  for (const [teamID, s] of series) {
    if (onlyTeam != null && teamID !== onlyTeam) continue;
    let due = 0, lastOrderIdx = 0;
    const teamOrders = game.events.filter(e => e.kind === "order" && e.teamID === teamID);
    for (const pt of s) {
      if (pt.sec > until) break;
      if (pt.frame < due) continue;
      due = pt.frame + stepFrames;
      const ords = [];
      while (lastOrderIdx < teamOrders.length && teamOrders[lastOrderIdx].frame <= pt.frame) ords.push(teamOrders[lastOrderIdx++]);
      game.moments.push(makeMoment({
        frame: pt.frame, sec: pt.sec, teamID,
        metal: Math.max(0, pt.metalBank), energy: Math.max(0, pt.energyBank),
        mIncome: pt.metalInc, eIncome: pt.energyInc,
        orders: ords,
        known: { bank: "derived", storage: false, income: true, buildPower: false, units: false, builders: false },
      }));
      game.lastFrame = Math.max(game.lastFrame, pt.frame);
    }
  }
  game.moments.sort((a, b) => a.frame - b.frame || a.teamID - b.teamID);
  return game;
}

// ------------------------------------------------------------------------ public API
/** Parse any source into a Game. opts: {every, until, team, defs, dir} */
async function parseSource(ref, opts = {}) {
  const src = resolveSource(ref, opts.dir);
  const o = { every: opts.every || 15, until: opts.until ?? Infinity, onlyTeam: opts.team ?? null };
  return src.kind === "widget" ? parseWidget(src.path, o) : parseDemoFile(src.path, { ...o, defsFrom: opts.defs || null });
}

function momentsFor(game, teamID) { return game.moments.filter(m => m.teamID === teamID); }

function findTeam(game, nameOrId) {
  if (nameOrId == null) return null;
  if (/^\d+$/.test(String(nameOrId)) && game.teams.has(Number(nameOrId))) return Number(nameOrId);
  const lc = String(nameOrId).toLowerCase();
  for (const [id, t] of game.teams) if ((t.name || "").toLowerCase() === lc) return id;
  for (const [id, t] of game.teams) if ((t.name || "").toLowerCase().includes(lc)) return id;
  return null;
}

/** Everything a strategizer would call a "builder": mobile cons, commander, con turrets, factories. */
function isBuilderDef(d) { return !!d && d.buildPower > 0; }

// ------------------------------------------------------------------------ CLI
function mmss(sec) { const m = Math.floor(sec / 60), s = Math.round(sec % 60); return `${m}:${String(s).padStart(2, "0")}`; }
function pad(s, n) { s = String(s); return s.length >= n ? s : s + " ".repeat(n - s.length); }
function padL(s, n) { s = String(s); return s.length >= n ? s : " ".repeat(n - s.length) + s; }
function fmt(v, d = 0) { return v == null ? "—" : Number(v).toFixed(d); }

function parseArgs(argv) {
  const a = { source: null, team: null, me: null, every: 15, until: 900, json: null, defs: null, dir: null };
  const rest = [];
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t === "--team") a.team = argv[++i];
    else if (t === "--me") a.me = argv[++i];
    else if (t === "--every") a.every = Number(argv[++i]) || 15;
    else if (t === "--until") { const v = argv[++i]; a.until = v === "full" ? Infinity : (Number(v) || 900); }
    else if (t === "--json") a.json = argv[++i];
    else if (t === "--defs") a.defs = argv[++i];
    else if (t === "--dir") a.dir = argv[++i];
    else rest.push(t);
  }
  a.source = rest[0] || "1";
  return a;
}

const SHORT = { armmex: "mex", cormex: "mex", legmex: "mex", armwin: "wind", corwin: "wind", legwin: "wind",
  armsolar: "sol", corsolar: "sol", legsolar: "sol", armck: "con", corck: "con", legck: "con",
  armnanotc: "nano", cornanotc: "nano", legnanotc: "nano", armlab: "lab", corlab: "lab", leglab: "lab",
  armmakr: "conv", cormakr: "conv", legeconv: "conv", armestor: "estor", corestor: "estor", legestor: "estor" };

/** ["armwin","armwin","armmex"] → "2×armwin, armmex" */
function runLength(names) {
  const out = [];
  for (const n of names) { const last = out[out.length - 1]; if (last && last.n === n) last.c++; else out.push({ n, c: 1 }); }
  return out.map(r => (r.c > 1 ? `${r.c}×${r.n}` : r.n)).join(", ");
}

function summarizeUnits(units) {
  if (!units) return "—";
  const agg = {};
  for (const [k, v] of Object.entries(units)) { const s = SHORT[k]; if (s) agg[s] = (agg[s] || 0) + v; }
  return Object.entries(agg).map(([k, v]) => `${v}${k}`).join(" ") || "(no eco yet)";
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const game = await parseSource(args.source, { every: args.every, until: args.until, defs: args.defs, dir: args.dir });
  const teamID = findTeam(game, args.team ?? args.me);
  console.log(`\nBAR Build Parser — ${game.map || "?"}  [${game.source}] ${path.basename(game.path)}`);
  console.log(`teams ${game.teams.size} · defs ${game.defs.size}${game.defsFrom ? " (from " + path.basename(game.defsFrom) + ")" : ""} · moments ${game.moments.length} · events ${game.events.length} · mex spots seen ${game.mexSpots.length} · last ${mmss(game.lastFrame / FPS)}`);
  if (teamID == null) {
    console.log("\nteams:");
    for (const [id, t] of [...game.teams].sort((a, b) => a[0] - b[0]))
      console.log(`  ${padL(id, 2)}  AT${t.ally}  ${pad(t.name, 24)} ${t.faction}${t.isAI ? " (AI)" : ""}`);
    console.log("\npass --team <id|name> for that team's moments");
  } else {
    const t = game.teams.get(teamID);
    console.log(`\nteam ${teamID} ${t.name} (AT${t.ally}, ${t.faction})`);
    console.log(`  ${pad("time", 6)} ${padL("metal", 7)} ${padL("energy", 7)} ${padL("m/s", 6)} ${padL("e/s", 7)} ${padL("bp", 8)} ${pad("units", 30)} builders`);
    for (const m of momentsFor(game, teamID)) {
      const bp = m.bpAvail != null ? `${fmt(m.bpUsed)}/${fmt(m.bpAvail)}` : "—";
      const bl = m.builders
        ? m.builders.map(b => `${b.defName.replace(/^(arm|cor|leg)/, "")}@${Math.round(b.x)},${Math.round(b.z)}${b.idle ? "·idle" : ""}`).join(" ")
        : (m.orders && m.orders.length ? `orders: ${runLength(m.orders.map(o => o.defName))}` : "");
      console.log(`  ${pad(mmss(m.sec), 6)} ${padL(fmt(m.metal), 7)} ${padL(fmt(m.energy), 7)} ${padL(fmt(m.mIncome, 1), 6)} ${padL(fmt(m.eIncome, 1), 7)} ${padL(bp, 8)} ${pad(summarizeUnits(m.units), 30)} ${bl}`);
    }
  }
  if (args.json) {
    const out = { ...game, teams: [...game.teams], defs: [...game.defs.values()], demo: undefined, series: undefined, teamStats: undefined };
    fs.writeFileSync(args.json, JSON.stringify(out));
    console.log(`\nwrote ${args.json}`);
  }
}

module.exports = {
  FPS, VALUE_E_DIV, MIN_PEAK, START_BANK, SHORT,
  loadDemoParser, demosDir, resolveDemo, resolveSource, listArchivedGames,
  buildTeamMeta, computeSeries, trimEndFlush, loadValueFlow, loadDefsFromJsonl,
  parseSource, parseWidget, parseDemoFile, momentsFor, findTeam, isBuilderDef, makeMoment,
};

if (require.main === module) main().catch(e => { console.error("✘ " + (e.stack || e.message)); process.exit(1); });

"use strict";
// splendid_buildSimulator.js — simulated economy/builder state for a BAR player.
//
//   node splendid_buildSimulator.js <source> --team <id|name> [--every <sec>] [--until <sec>|full]
//                                            [--free <sec>] [--dt <sec>] [--json <out.json>]
//   node splendid_buildSimulator.js --selftest
//
// The state calculator is a port of bar-calc/bar_unified.py — the consolidated BAR calculator
// (bar_calc Environment + bar_distance grid/walk model + wind_simulator income + eco_calculator
// ROI). Section for section:
//   1. constants            ENERGY_PER_METAL, DEFAULT_BUILDER_BP, UNIT_PROFILES, grid calibration
//   2. distance / walk      resolveUnit, squaresToElmos, canReach, walkTime, walkTimeSquares
//   3. wind income          windIncome(min, max)
//   4. object data + ROI    OBJECT_TYPES (bar_unified.OBJECTS ∪ bar_calc.object_types), buildTime/troi/eroi
//   5. Environment          buildTimes / build(name, {walkSquares}) / advance / buildOrder / status,
//                           plus the bar_calc spellings (calculateBuildTimes, constructObject, advanceTime)
//   6. ROI report           generatorRoiReport  (CLI --roi)
// Every number is resolved at load from bar-calc/econ_model.json + the engine unit-def dumps it lists — the same
// files bar_unified.py and positions/state_api.py read. `--selftest` checks the resolved numbers, the ROI helpers
// and both demo openings (bar_unified's with walks, bar_calc's t=3/+1 s) against bar-calc/parity.json.
// On top of that this file adds what a running game needs:
//   • a continuous `tick(dt)` — every builder spends its own BP against its own task,
//     walking to the site first (bar_unified UNIT_PROFILES speed / build range), throttled by
//     the shared metal+energy pool in insertion order (eco_simulator.py semantics)
//   • `resetToReality(moment)` — snap the simulated state to a parser moment; fields the
//     moment does not know (see splendid_buildParser makeMoment.known) keep their simulated value
//   • `divergence(moment)` — how far the simulation drifted from the next reality moment
//   • `simulateSpan(...)` — the alternate-reset-and-simulate loop over a whole game
//
// The strategizer (splendid_buildStrategizer.js) plugs into `tick` through the `decider`
// hook: each tick it may hand idle builders a new task.

const fs = require("fs");
const path = require("path");
const P = require("./splendid_buildParser");

const FPS = P.FPS;

// ───────────────────────────────────────────── 1. constants (bar-calc/econ_model.json — the one model config)
// Every number in this file is resolved from bar-calc/econ_model.json + the engine unit-def dumps it lists,
// with the same rules as bar-calc/econ_data.py (which feeds bar_unified.py and positions/state_api.py).
// `--selftest` compares the resolved numbers with bar-calc/parity.json (python bar-calc/bar_unified.py --write-parity).
const ECON_MODEL_PATH = path.join(__dirname, "bar-calc", "econ_model.json");
const PARITY_PATH = path.join(__dirname, "bar-calc", "parity.json");
const ECON = JSON.parse(fs.readFileSync(ECON_MODEL_PATH, "utf8"));
const ENERGY_PER_METAL = ECON.constants.energyPerMetal;      // T1 energy-converter exchange rate
const DEFAULT_BUILDER_BP = ECON.constants.defaultBuilderBp;  // T1 constructor / commander build power
const GAME_FPS = ECON.constants.gameFps;
const DEFAULT_WIND = ECON.constants.defaultWind;             // e/s per turbine when no wind sample is known
const BUILD_RANGE_IN_GRID_SQUARES = ECON.gridCalibration.buildRangeInGridSquares;

// ───────────────────────────────────────────── engine unit-def library (econ_model.json `engineDefs`)
// The widget's unit_def has costs but no buildTime. The dumps carry the full engine def per defName:
// buildTime, windGenerator, energyProduction, energyUpkeep, extractsMetal, storage, speed, buildPower.
// Loaded once, joined by defName; later files win (same order as econ_data.engine_defs()).
/** econ_data._resolve_source: a fixed `path`, or a `glob` whose newest match by name wins (units_<dateTime>.json). */
function resolveEngineSource(src) {
  if (!src.glob) return [path.join(__dirname, ...src.path.split("/"))];
  const parts = src.glob.split("/"); const pat = parts.pop(); const dir = path.join(__dirname, ...parts);
  if (!fs.existsSync(dir)) return [];
  const re = new RegExp("^" + pat.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$");
  const m = fs.readdirSync(dir).filter(f => re.test(f)).sort();
  if (!m.length) return [];
  return ((src.pick || "latest") === "latest" ? [m[m.length - 1]] : m).map(f => path.join(dir, f));
}
const UNITDEF_LIBRARY_PATHS = ECON.engineDefs.flatMap(src => resolveEngineSource(src).map(p => ({ path: p, format: src.format })));
function libEntry(e) {
  return { defName: e.defName, buildTime: e.buildTime || 0, metal: e.metalCost || 0, energy: e.energyCost || 0, speed: e.speed || 0, buildPower: e.buildPower || 0,
    windGenerator: e.windGenerator || 0, energyProduction: e.energyProduction || 0, energyUpkeep: e.energyUpkeep || 0,
    metalMake: e.metalMake || 0, extractsMetal: e.extractsMetal || 0, isMex: !!e.isMetalExtractor,
    energyStorage: e.energyStorage || 0, metalStorage: e.metalStorage || 0, convCap: e.energyConversionCapacity || 0,
    isFactory: !!e.isFactory, isCommander: !!e.isCommander, name: e.name };
}
let _unitdefLib = null;
function unitdefLibrary(extraPath = null) {
  if (_unitdefLib && !extraPath) return _unitdefLib;
  const lib = _unitdefLib || new Map();
  const sources = extraPath ? [{ path: extraPath, format: /\.jsonl?$/.test(extraPath) && !extraPath.endsWith("unitdefs.json") ? "jsonl-unit_def" : "defs-array" }] : UNITDEF_LIBRARY_PATHS;
  for (const { path: p, format } of sources) {
    if (!fs.existsSync(p)) continue;
    if (format === "defs-array") {
      const d = JSON.parse(fs.readFileSync(p, "utf8"));
      for (const e of (Array.isArray(d) ? d : d.defs)) lib.set(e.defName, libEntry(e));
      continue;
    }
    // jsonl-unit_def: defs are the leading block of the file: read in chunks and stop once past them
    const fd = fs.openSync(p, "r"); const buf = Buffer.alloc(1 << 20); let rest = "", pos = 0, seen = 0, done = false;
    try {
      while (!done) {
        const n = fs.readSync(fd, buf, 0, buf.length, pos); if (n <= 0) break; pos += n;
        const chunk = rest + buf.toString("utf8", 0, n); const lines = chunk.split(/\r?\n/); rest = lines.pop();
        for (const ln of lines) {
          if (!ln) continue;
          if (!ln.includes('"unit_def"')) { if (seen > 50) { done = true; break; } continue; }
          let e; try { e = JSON.parse(ln); } catch { continue; }
          if (e.action !== "unit_def") continue;
          seen++;
          lib.set(e.defName, libEntry(e));
        }
      }
    } finally { fs.closeSync(fd); }
  }
  _unitdefLib = lib;
  return lib;
}

// ───────────────────────────────────────────── derivation rules (mirror bar-calc/econ_data.py line for line)
/** [production, upkeep] in e/s — engine: energyUpkeep < 0 means the unit PRODUCES. */
function energyFlows(L) {
  const prod = Math.max(0, L.energyProduction || 0) + Math.max(0, -(L.energyUpkeep || 0));
  const upk = Math.max(0, L.energyUpkeep || 0);
  return [prod, upk];
}
/** m/s on the reference spot: extractsMetal / mexBaseExtract × metalSpot (calibrated per-def overrides). */
function mexIncome(L) {
  const c = ECON.constants, over = c.mexMultiplierOverride || {};
  if (L.defName && L.defName in over) return over[L.defName] * c.metalSpot;
  const ex = L.extractsMetal || 0;
  if (ex <= 0) return 0;
  return Number((ex / c.mexBaseExtract).toFixed(4)) * c.metalSpot;
}
function _defOrFallback(spec, lib) {
  const L = spec.def ? lib.get(spec.def) : null;
  if (L) return [L, false];
  const f = spec.fallback || {};
  return [libEntry({ defName: null, metalCost: f.metalCost, energyCost: f.energyCost, buildTime: f.buildTime }), true];
}
// build range (elmos, config) + speed / build power (engine def)
const UNIT_PROFILES = {};
for (const [k, spec] of Object.entries(ECON.builderProfiles)) {
  if (k.startsWith("_")) continue;
  const [L, provisional] = _defOrFallback(spec, unitdefLibrary());
  UNIT_PROFILES[k] = { buildRange: spec.buildRange, speed: L.speed || 0, bp: L.buildPower || 0, def: spec.def, provisional };
}
const ELMOS_PER_GRID_SQUARE = UNIT_PROFILES.commander.buildRange / BUILD_RANGE_IN_GRID_SQUARES;

/** econ_data.object_types(): one model object from its config spec + engine def. */
function resolveObjectType(name, spec, lib, resolved) {
  const kind = spec.kind || "unit";
  if (kind === "reclaim") {
    const of = resolved[spec.of];
    return { kind, of: spec.of, metal: 0, energy: 0, bp: of.bp, mInc: 0, eInc: 0, storE: 0, storM: 0,
      windPowered: false, converter: 0, factory: false, free: false, defName: null, provisional: false };
  }
  const [L, provisional] = _defOrFallback(spec, lib);
  const free = !!spec.free;
  const [prod, upk] = energyFlows(L);
  const windPowered = !!spec.windPowered || (L.windGenerator || 0) > 0;
  const factory = !!spec.factory || !!L.isFactory;
  const t = {
    kind, defName: spec.def || null, provisional,
    metal: free ? 0 : L.metal, energy: free ? 0 : L.energy, bp: free ? 0 : L.buildTime,
    mInc: (L.metalMake || 0) + mexIncome(L),
    eInc: windPowered ? DEFAULT_WIND : prod - upk,
    storE: L.energyStorage || 0, storM: L.metalStorage || 0,
    windPowered, converter: (L.convCap || 0) > 0 ? 1 : 0, factory, free,
  };
  if (kind === "builder") {
    const prof = spec.profile ? UNIT_PROFILES[spec.profile] : null;
    t.builderBp = L.buildPower || 0;
    t.speed = factory ? 0 : (L.speed || 0);
    t.range = factory ? 0 : (prof ? prof.buildRange : 0);
    if (spec.profile) t.profile = spec.profile;
  }
  return t;
}
/** econ_data.legion_actions(): positions/state_api ACTIONS data resolved from the same defs (used by --selftest). */
function resolveLegionAction(aid) {
  const lib = unitdefLibrary(); const spec = ECON.legion.actions[aid];
  if (!spec) return null;
  const need = d => { const L = lib.get(d); if (!L) throw new Error(`engine def ${d} is not in the dumps`); return L; };
  const L = need(spec.def), rep = spec.replaces ? need(spec.replaces) : null;
  const reclaim = (spec.reclaim || []).reduce((sum, d) => sum + need(d).metal, 0);
  const [prod, upk] = energyFlows(L), [rprod, rupk] = rep ? energyFlows(rep) : [0, 0];
  const windPowered = (L.windGenerator || 0) > 0;
  return { def: spec.def, metal: L.metal - reclaim, energy: L.energy, bw: L.buildTime,
    dm: mexIncome(L) - (rep ? mexIncome(rep) : 0), de_inc: windPowered ? null : prod - rprod, de_upk: upk - rupk,
    reclaim, dn: spec.dn || {}, prereq: spec.prereq || {} };
}

// ───────────────────────────────────────────── 2. distance / worker walk time (bar_unified §2)
function resolveUnit(unit) {
  const u = String(unit || "").trim().toLowerCase();
  if (u.includes("commander")) return "commander";
  if (u.includes("turret") || u.includes("nano")) return "con_turret";
  return "con_bot";
}
const squaresToElmos = sq => sq * ELMOS_PER_GRID_SQUARE;
const elmosToSquares = el => el / ELMOS_PER_GRID_SQUARE;
/** True if a target gapElmos away is already within build range. */
function canReach(gapElmos, unit = "commander") { return gapElmos <= UNIT_PROFILES[resolveUnit(unit)].buildRange; }
/** Seconds a builder walks before it can start a target gapElmos away (stops once in range; static → Infinity). */
function walkTime(gapElmos, unit = "con_bot", accountBuildRange = true) {
  const p = UNIT_PROFILES[resolveUnit(unit)];
  const gap = accountBuildRange ? Math.max(0, gapElmos - p.buildRange) : gapElmos;
  if (gap <= 0) return 0;
  if (p.speed <= 0) return Infinity;
  return gap / p.speed;
}
function walkTimeSquares(gapSquares, unit = "con_bot", accountBuildRange = true) { return walkTime(squaresToElmos(gapSquares), unit, accountBuildRange); }

// ───────────────────────────────────────────── 3. wind income (bar_unified §3)
/** Average E/s of a turbine on a map with the given wind range (turbines output linearly between min and max). */
function windIncome(minWind, maxWind) { return (minWind + maxWind) / 2; }

// ───────────────────────────────────────────── 4b. ROI helpers on object types (bar_unified.ObjectType)
/** Wall-clock build time for one builder. */
function buildTime(t, builderBp = DEFAULT_BUILDER_BP) { return builderBp ? t.bp / builderBp : Infinity; }
/** Total ROI in T1-converted energy-seconds: (M*70 + E) / output. */
function troi(t, outputEPerSec) { return outputEPerSec <= 0 ? Infinity : (t.metal * ENERGY_PER_METAL + t.energy) / outputEPerSec; }
/** Time to repay own energy cost (or build time if E_cost == 0). */
function eroi(t, outputEPerSec, builderBp = DEFAULT_BUILDER_BP) {
  if (t.energy === 0) return buildTime(t, builderBp);
  return outputEPerSec ? t.energy / outputEPerSec : Infinity;
}

// ───────────────────────────────────────────── object table (econ_model.json `objectTypes`, resolved from the engine defs)
// kind: building | builder | unit | reclaim.  bp = build work (buildpower-seconds).  Incomes are per second.
// builderBp = build power the finished object contributes; speed from the def, range from UNIT_PROFILES.
const OBJECT_TYPES = {};
{
  const lib = unitdefLibrary();
  const specs = Object.entries(ECON.objectTypes).filter(([k]) => !k.startsWith("_"));
  for (const [name, spec] of specs) if ((spec.kind || "unit") !== "reclaim") OBJECT_TYPES[name] = resolveObjectType(name, spec, lib, OBJECT_TYPES);
  for (const [name, spec] of specs) if (spec.kind === "reclaim") OBJECT_TYPES[name] = resolveObjectType(name, spec, lib, OBJECT_TYPES);
}
const BASE_STORAGE = { metal: ECON.baseState.teamStorage.metal, energy: ECON.baseState.teamStorage.energy };   // team base; the commander carries the rest (engine defs)
const FACTORY_PRODUCTS = new Set(ECON.factoryProducts);

// engine defName → object type (primary defs + the faction variants in econ_model.json `aliases`)
const ALIASES = {};
for (const [name, spec] of Object.entries(ECON.objectTypes)) if (!name.startsWith("_") && spec.def) ALIASES[spec.def] = name;
for (const [d, name] of Object.entries(ECON.aliases)) if (!d.startsWith("_")) ALIASES[d] = name;

// ───────────────────────────────────────────── type registry (table + per-game defs)
/**
 * A registry maps engine defNames to object types. Game defs override metal/energy/builderBp
 * for known types (game version drift); the unit-def library supplies build work for everything
 * it knows; anything still unknown gets a generic type with estimated build work.
 */
class TypeRegistry {
  constructor(game = null, { library = true } = {}) {
    this.types = {};
    for (const [k, v] of Object.entries(OBJECT_TYPES)) this.types[k] = { name: k, ...v };
    this.byDef = new Map();                        // defName -> type name
    for (const [d, t] of Object.entries(ALIASES)) this.byDef.set(d, t);
    this.lib = library ? unitdefLibrary() : new Map();
    if (game && game.defs) for (const d of game.defs.values()) this.absorbDef(d);
  }
  absorbDef(d) {
    const L = this.lib.get(d.defName);
    const known = this.byDef.get(d.defName);
    if (known) {
      const t = this.types[known];
      if (known !== "Commander") { t.metal = d.metal; t.energy = d.energy; }   // the game's own costs win over the table
      if (d.buildPower > 0) t.builderBp = d.buildPower;
      if (L && L.buildTime > 0 && t.kind !== "reclaim") t.bp = L.buildTime;
      if (L && L.speed > 0 && t.kind === "builder") t.speed = L.speed;
      if (L) {   // engine incomes/storage win over the bar_calc table (com 30 e/s, con +7 e/s, lab +100/+100 storage …)
        if (!t.windPowered) { t.eInc = (L.energyProduction || 0) - (L.energyUpkeep || 0); t.mInc = (L.metalMake || 0) + (L.isMex ? (t.mInc || 0) : 0); }
        t.storE = L.energyStorage || 0; t.storM = L.metalStorage || 0;
      }
      t.defName = t.defName || d.defName;
      return known;
    }
    if (d.isCommander) return this.byDef.set(d.defName, "Commander"), "Commander";
    // unknown def → generic type from the library (engine truth) or, failing that, a value-based estimate
    const value = d.metal + d.energy / ENERGY_PER_METAL;
    const t = { name: d.defName, defName: d.defName, metal: d.metal, energy: d.energy,
      bp: L && L.buildTime > 0 ? L.buildTime : Math.round(value * 20), bpEstimated: !(L && L.buildTime > 0), mInc: 0, eInc: 0,
      kind: d.buildPower > 0 ? "builder" : (d.isMex || (L && (L.energyProduction || L.windGenerator || L.energyStorage || L.metalStorage || L.convCap))) ? "building" : "unit" };
    if (d.buildPower > 0) { t.builderBp = d.buildPower; t.speed = d.isFactory ? 0 : (L && L.speed > 0 ? L.speed : 36); t.range = d.isFactory ? 0 : 130; t.factory = !!d.isFactory; }
    if (d.isMex) { t.mInc = L ? mexIncome(L) : ECON.constants.metalSpot; t.eInc = L ? energyFlows(L)[0] - energyFlows(L)[1] : 0; }
    if (L) {
      if (L.windGenerator > 0) { t.windPowered = true; t.eInc = DEFAULT_WIND; }
      else if (!d.isMex) { t.eInc = (L.energyProduction || 0) - (L.energyUpkeep || 0); t.mInc = L.metalMake || 0; }
      if (L.energyStorage > 0) t.storE = L.energyStorage;
      if (L.metalStorage > 0) t.storM = L.metalStorage;
    }
    if (d.convCap > 0) t.converter = 1;
    this.types[d.defName] = t;
    this.byDef.set(d.defName, d.defName);
    return d.defName;
  }
  resolve(nameOrDef) {
    if (this.types[nameOrDef]) return nameOrDef;
    const t = this.byDef.get(nameOrDef);
    return t || null;
  }
  get(nameOrDef) { const k = this.resolve(nameOrDef); return k ? this.types[k] : null; }
}

// ───────────────────────────────────────────── Environment (bar_calc.Environment port)
let _builderSeq = 0;
function makeBuilder(type, opts = {}) {
  return {
    id: opts.id ?? `b${++_builderSeq}`, unitID: opts.unitID ?? null,
    type, bp: opts.bp ?? type.builderBp ?? 0,
    x: opts.x ?? 0, z: opts.z ?? 0,
    speed: opts.speed ?? type.speed ?? 36, range: opts.range ?? type.range ?? 130,
    factory: !!type.factory,
    task: null,                 // {object, x, z, progress, walkLeft, metalSpent, energySpent, startedAt}
    queue: [],                  // [{object, x, z}] taken up in order when the task completes
    priority: opts.priority || "high",
    stalled: null,              // "metal" | "energy" | null (last tick)
  };
}

class Environment {
  constructor({
    time = 0, metal = ECON.baseState.metal, metalPerSecond = null, maxMetal = ECON.baseState.maxMetal,   // econ_model.json baseState (bar_calc started at t=3)
    energy = ECON.baseState.energy, maxEnergy = ECON.baseState.maxEnergy, energyPerSecond = null,        // null → the Commander's own incomes
    builders = null, buildings = null, constructionHistory = null, numberConverters = 0,
    wind = DEFAULT_WIND, registry = null, verbose = false,
  } = {}) {
    this.registry = registry || new TypeRegistry();
    this.time = time;
    const com = this.registry.get("Commander") || { mInc: 0, eInc: 0 };
    this.metal = metal; this.metalPerSecond = metalPerSecond ?? com.mInc; this.maxMetal = maxMetal;
    this.energy = energy; this.energyPerSecond = energyPerSecond ?? com.eInc; this.maxEnergy = maxEnergy;
    this.builders = builders || [makeBuilder(this.registry.get("Commander"), { id: "commander" })];
    this.buildings = buildings || [];                       // type names, like bar_calc
    this.constructionHistory = constructionHistory || [];   // [{object, time, builder}]
    this.numberConverters = numberConverters;
    this.wind = wind;
    this.incomeAdjust = { m: 0, e: 0 };   // reality − model, set by resetToReality
    this.verbose = verbose;
    this.log = [];
    // diagnostics
    this.overflowLost = { m: 0, e: 0 };
    this.stallSec = { metal: 0, energy: 0 };
    this.spent = { m: 0, e: 0 };
    this.converted = 0;
  }

  copy() {
    const e = new Environment({ registry: this.registry, wind: this.wind, verbose: false });
    Object.assign(e, JSON.parse(JSON.stringify({ ...this, registry: undefined, log: undefined })));
    e.registry = this.registry; e.log = [];
    for (const b of e.builders) b.type = this.registry.get(b.type.name) || b.type;
    return e;
  }

  say(msg) { this.log.push(msg); if (this.verbose) console.log(msg); }
  obj(name) { const t = this.registry.get(name); if (!t) throw new Error(`Unknown object type: ${name}`); return t; }

  // ── bar_unified / bar_calc formulas ─────────────────────────────────────────
  optimalBuildPower(name) { const t = this.obj(name); return (t.bp * this.metalPerSecond) / t.metal; }
  reqEnergyWithBp(name, bpTotal) { const t = this.obj(name); return t.energy / (t.bp / bpTotal); }
  totalBp() { return this.builders.reduce((s, b) => s + b.bp, 0); }            // bar_unified.total_bp
  getTotalBuildpower() { return this.totalBp(); }                                // bar_calc spelling

  /** bar_unified.build_times: time gated by build power, energy income and metal income — the max wins. */
  buildTimes(name, builderBp = null) {
    const bt = this.calculateBuildTimes(name, { buildpower: builderBp || 0, minAddTime: 0 });
    return { bp: bt.buildpowerTime, energy: bt.energyTime, metal: bt.metalTime, total: bt.totalTime, stall: bt.stall };
  }

  /** bar_unified.build: walk to the site (grid squares, calibrated) then build at full pool BP. */
  build(name, { walkSquares = 0, walker = "commander", minAddTime = 0 } = {}) {
    if (!this.registry.get(name)) { this.say(`  ! unknown object: ${name}`); return false; }
    const wt = walkSquares ? walkTimeSquares(walkSquares, walker) : 0;
    if (wt > 0 && isFinite(wt)) this.advance(wt);
    const bt = this.calculateBuildTimes(name, { minAddTime });
    if (!isFinite(bt.totalTime)) { this.say(`  ! cannot build ${name}: no income for the missing resource`); return false; }
    if (bt.energyTime > bt.buildpowerTime) this.say(`  ! energy stall building ${name}`);
    if (bt.metalTime > bt.buildpowerTime) this.say(`  ! metal stall building ${name}`);
    const t = this.obj(name);
    this.metal -= t.metal;
    this.advance(bt.totalTime, t.energy / Math.max(bt.totalTime, 1e-9));
    this.applyCompletion(name, null);
    const walkNote = wt ? ` (+${wt.toFixed(1)}s walk ${walkSquares}sq)` : "";
    this.say(`  ${this.time.toFixed(1).padStart(6)}s  built ${name.padEnd(11)}${walkNote}  M=${this.metal.toFixed(0).padStart(6)} E=${this.energy.toFixed(0).padStart(6)}  +${this.incomeM().toFixed(1)}M/s +${this.incomeE().toFixed(0)}E/s`);
    return true;
  }

  /** bar_unified.build_order: entries are "Name" or ["Name", walkSquares]. */
  buildOrder(order, opts = {}) {
    for (const entry of order) {
      const [name, walk] = Array.isArray(entry) ? entry : [entry, 0];
      if (!this.build(name, { ...opts, walkSquares: walk })) break;
    }
    return this;
  }

  /** bar_unified.status */
  status() {
    console.log(`\n  t=${this.time.toFixed(1)}s  M=${this.metal.toFixed(0)}/${this.maxMetal.toFixed(0)} E=${this.energy.toFixed(0)}/${this.maxEnergy.toFixed(0)}  income +${this.incomeM().toFixed(1)}M/s +${this.incomeE().toFixed(0)}E/s  BP=${this.totalBp().toFixed(0)}`);
    console.log(`  builders: ${this.builders.map(b => b.type.name).join(", ")}`);
    console.log(`  buildings: ${this.buildings.join(", ") || "none"}`);
  }
  /** Rate-based incomes as the model sees them (bar_calc's metal_per_second / energy_per_second + wind + adjust). */
  incomeM() { return this.metalPerSecond + this.incomeAdjust.m; }
  /** Current wind (e/s per turbine): the recorded wind series at this time when one is attached, else the last known value. */
  windNow() {
    const ws = this.windSeries;
    if (!ws || !ws.length) return this.wind;
    let i = this._windIdx || 0;
    if (i >= ws.length || ws[i].sec > this.time) i = 0;
    while (i + 1 < ws.length && ws[i + 1].sec <= this.time) i++;
    this._windIdx = i;
    return ws[i].value;
  }
  incomeE() {
    let e = this.energyPerSecond + this.incomeAdjust.e;
    const w = this.windNow();
    for (const b of this.buildings) { const t = this.registry.get(b); if (t && t.windPowered) e += w - t.eInc; }   // swap table wind for live wind
    return e;
  }

  /** bar_calc.calculate_build_times: buildpower / energy / metal time, max wins (minAddTime=1 was bar_calc's fudge; bar_unified drops it). */
  calculateBuildTimes(name, { buildpower = 0, minAddTime = 0 } = {}) {
    const t = this.obj(name);
    if (!buildpower) buildpower = this.getTotalBuildpower();
    const buildpowerTime = t.bp / buildpower + minAddTime;
    const mInc = this.incomeM(), eInc = this.incomeE();
    const energyTime = t.energy <= this.energy ? 0 : (eInc > 0 ? (t.energy - this.energy) / eInc : Infinity);
    const metalTime = t.metal <= this.metal ? 0 : (mInc > 0 ? (t.metal - this.metal) / mInc : Infinity);
    return { buildpowerTime, energyTime, metalTime, totalTime: Math.max(buildpowerTime, energyTime, metalTime),
      stall: energyTime > buildpowerTime ? "energy" : metalTime > buildpowerTime ? "metal" : null };
  }

  /** bar_calc.construct_object: jump straight to completion with the whole BP pool. */
  constructObject(name, { theoretical = false, minAddTime = 1 } = {}) {
    if (!this.registry.get(name)) { this.say(`Unknown building type: ${name}`); return false; }
    const env = theoretical ? this.copy() : this;
    const t = env.obj(name);
    const bt = env.calculateBuildTimes(name, { minAddTime });
    if (!isFinite(bt.totalTime)) { env.say(`Cannot build ${name}: no income for the missing resource`); return false; }
    if (bt.energyTime > bt.buildpowerTime) env.say("Alert:: Energy Stall");
    if (bt.metalTime > bt.buildpowerTime) env.say("Warning:: Metal Stall");
    env.say(`Building ${name} will take ${bt.totalTime.toFixed(2)}/${bt.buildpowerTime.toFixed(2)} seconds`);
    env.metal -= t.metal;                                   // metal up front (bar_calc), energy as drain
    env.advanceTime(bt.totalTime, t.energy / bt.totalTime);
    env.applyCompletion(name, null);
    env.say(`Completed ${name} at time ${env.time.toFixed(2)}`);
    env.say(`Current resources: Metal=${env.metal.toFixed(2)}, Energy=${env.energy.toFixed(2)}`);
    env.say(`Income rates: Metal=${env.incomeM().toFixed(2)}/s, Energy=${env.incomeE().toFixed(2)}/s`);
    return theoretical ? env : true;
  }

  /** bar_unified.advance: income, caps, converters (surplus above convFloor×cap → whole metal, ≤ n×dt). */
  advance(dt, eps = 0, convFloor = 0.5) {
    if (dt <= 0) return;
    this.metal = Math.min(this.metal + this.incomeM() * dt, this.maxMetal);
    this.energy += (this.incomeE() - eps) * dt;
    const excess = this.energy - convFloor * this.maxEnergy;
    if (excess > 0 && this.numberConverters) {
      const converted = Math.min(this.numberConverters * dt, Math.floor(excess / ENERGY_PER_METAL));
      this.metal += converted; this.energy -= converted * ENERGY_PER_METAL; this.converted += converted;
    }
    this.energy = Math.min(this.energy, this.maxEnergy);
    this.time += dt;
  }
  /** bar_calc.advance_time spelling (same semantics). */
  advanceTime(dt, eps = 0, eConvMult = 0.5) { return this.advance(dt, eps, eConvMult); }

  runConverters(dt, eConvMult = 0.5) {
    if (this.numberConverters <= 0) return;
    const excess = this.energy - eConvMult * this.maxEnergy;
    if (excess <= 0) return;
    const capacity = this.numberConverters * ENERGY_PER_METAL * dt;   // 70 e → 1 m per converter-second
    const eEat = Math.min(excess, capacity);
    this.energy -= eEat;
    this.metal += eEat / ENERGY_PER_METAL;
    this.converted += eEat / ENERGY_PER_METAL;
  }

  /** Register a completed object: incomes, storage, converters, new builders. */
  applyCompletion(name, builder, at = {}) {
    const t = this.obj(name);
    if (t.kind === "reclaim") {
      this.removeCompletion(t.of, { reclaim: true });
      this.constructionHistory.push({ object: t.name, time: this.time, builder: builder ? builder.id : "pool" });
      return;
    }
    if (t.kind === "builder") {
      const b = makeBuilder(t, { x: at.x ?? (builder ? builder.x : 0), z: at.z ?? (builder ? builder.z : 0), priority: "low" });
      this.builders.push(b);
    } else {
      this.buildings.push(t.name);
    }
    if (t.converter) this.numberConverters += t.converter;
    if (t.storE) this.maxEnergy += t.storE;
    if (t.storM) this.maxMetal += t.storM;
    this.metalPerSecond += t.mInc || 0;
    this.energyPerSecond += t.eInc || 0;
    this.constructionHistory.push({ object: t.name, time: this.time, builder: builder ? builder.id : "pool" });
  }

  printStatus() {
    const lines = [
      "\nCurrent Environment Status:",
      `Time: ${this.time.toFixed(2)} seconds`,
      `Resources: Metal=${this.metal.toFixed(2)}/${this.maxMetal}, Energy=${this.energy.toFixed(2)}/${this.maxEnergy}`,
      `Income: Metal=${this.incomeM().toFixed(2)}/s, Energy=${this.incomeE().toFixed(2)}/s`,
      `Builders: ${this.builders.length} (${this.builders.map(b => b.type.name).join(", ")})`,
      `Buildings: ${this.buildings.length} (${this.buildings.join(", ") || "None"})`,
      `Total Buildpower: ${this.getTotalBuildpower()}`,
    ];
    for (const l of lines) console.log(l);
  }

  /** bar_calc.build_with_priorities — jump semantics; first non-stalling item wins, else Wind. */
  buildWithPriorities(priorityList, endTime = 100) {
    while (this.time < endTime) {
      let built = false, allStall = true;
      for (const name of priorityList) {
        if (!this.registry.get(name)) { this.say(`Warning: Unknown object type ${name} in priority list`); continue; }
        const bt = this.calculateBuildTimes(name);
        if (!bt.stall) { allStall = false; if (this.constructObject(name)) { built = true; break; } }
      }
      if (!built) {
        if (allStall) { this.say("All priority options would stall, building Wind instead"); if (!this.constructObject("Wind")) break; }
        else { this.say("No priority objects buildable right now, waiting..."); this.advanceTime(1); }
      }
    }
  }

  // ── continuous simulation ────────────────────────────────────────────────────
  counts() {
    const c = {};
    for (const b of this.buildings) c[b] = (c[b] || 0) + 1;
    for (const b of this.builders) c[b.type.name] = (c[b.type.name] || 0) + 1;
    return c;
  }
  idleBuilders() { return this.builders.filter(b => !b.task); }

  /** Give a builder a task (queued behind the current one if busy). Walk = max(0, gap − build range). */
  assign(builder, objectName, x = builder.x, z = builder.z) {
    const t = this.obj(objectName);
    if (builder.task) { builder.queue.push({ object: t.name, x, z }); return builder.queue[builder.queue.length - 1]; }
    const gap = builder.factory ? 0 : Math.hypot(x - builder.x, z - builder.z);
    const walk = Math.max(0, gap - builder.range);
    // the builder stops as soon as the site is in range — it ends up `range` short of the site, not on it
    const f = gap > 0 ? walk / gap : 0;
    builder.task = { object: t.name, x, z, progress: 0, walkLeft: walk, destX: builder.x + (x - builder.x) * f, destZ: builder.z + (z - builder.z) * f,
      metalSpent: 0, energySpent: 0, startedAt: this.time };
    return builder.task;
  }

  /** Pick the builder that can start `objectName` at (x,z) soonest: factories for factory products, else
   *  idle-and-in-range, else idle-nearest (walk), else the builder with the shortest queue. */
  chooseBuilder(objectName, x, z) {
    const t = this.obj(objectName);
    const wantsFactory = FACTORY_PRODUCTS.has(t.name) || (t.kind === "unit") || (t.kind === "builder" && (t.speed || 0) > 0);
    const pool = this.builders.filter(b => b.bp > 0 && (wantsFactory ? b.factory : !b.factory));
    if (!pool.length) return null;
    const eta = b => {
      const gap = b.factory ? 0 : Math.max(0, Math.hypot(x - b.x, z - b.z) - b.range);
      const walk = b.speed > 0 ? gap / b.speed : (gap > 0 ? 1e6 : 0);
      let busy = 0;
      if (b.task) { const tt = this.obj(b.task.object); busy += (1 - b.task.progress) * tt.bp / b.bp + b.task.walkLeft / (b.speed || 1); }
      for (const q of b.queue) busy += this.obj(q.object).bp / b.bp;
      return walk + busy * 1.5;     // queued work is penalised: a parallel builder beats a serial one
    };
    return pool.reduce((best, b) => (eta(b) < eta(best) ? b : best), pool[0]);
  }

  /** Reverse of applyCompletion: a finished object died. `reclaim` refunds its metal (bar_economy: 100% back). */
  removeCompletion(name, { reclaim = false, unitID = null } = {}) {
    const t = this.registry.get(name); if (!t) return false;
    if (t.kind === "builder") {
      const i = unitID != null ? this.builders.findIndex(b => b.unitID === unitID) : this.builders.findIndex(b => b.type.name === t.name);
      if (i < 0) return false;
      this.builders.splice(i, 1);
    } else {
      const i = this.buildings.lastIndexOf(t.name);
      if (i < 0) return false;
      this.buildings.splice(i, 1);
    }
    if (t.converter) this.numberConverters = Math.max(0, this.numberConverters - t.converter);
    if (t.storE) this.maxEnergy -= t.storE;
    if (t.storM) this.maxMetal -= t.storM;
    this.metalPerSecond -= t.mInc || 0;
    this.energyPerSecond -= t.eInc || 0;
    if (reclaim) { this.metal += t.metal; this.reclaimed = (this.reclaimed || 0) + t.metal; }
    return true;
  }

  /**
   * Advance dt seconds. Income lands first, then every builder works its task (walk, then spend
   * its BP-share of the cost, throttled to the pool), then converters, then storage caps.
   * `decider(env)` runs before spending so it can assign idle builders.
   */
  tick(dt, decider = null) {
    if (decider) decider(this);
    const flags = { stalled: [], completed: [] };
    this.metal += this.incomeM() * dt;
    this.energy += this.incomeE() * dt;
    const order = [...this.builders.filter(b => b.priority === "high"), ...this.builders.filter(b => b.priority !== "high")];
    for (const b of order) {
      b.stalled = null;
      const task = b.task; if (!task) continue;
      if (task.walkLeft > 0) { task.walkLeft -= b.speed * dt; if (task.walkLeft > 0) continue; task.walkLeft = 0; }
      const t = this.obj(task.object);
      if (b.bp <= 0 || t.bp <= 0) { task.progress = 1; }
      else {
        const wantFrac = Math.min((b.bp * dt) / t.bp, 1 - task.progress);
        const wantM = t.metal * wantFrac, wantE = t.energy * wantFrac;
        let ratio = 1;
        if (wantM > 0 && this.metal < wantM) { ratio = Math.min(ratio, Math.max(0, this.metal) / wantM); b.stalled = "metal"; }
        if (wantE > 0 && this.energy < wantE) { const r = Math.max(0, this.energy) / wantE; if (r < ratio) { ratio = r; b.stalled = "energy"; } }
        if (b.stalled) { this.stallSec[b.stalled] += dt; flags.stalled.push(b.id); }
        this.metal -= wantM * ratio; this.energy -= wantE * ratio;
        this.spent.m += wantM * ratio; this.spent.e += wantE * ratio;
        task.metalSpent += wantM * ratio; task.energySpent += wantE * ratio;
        task.progress += wantFrac * ratio;
      }
      if (task.progress >= 0.9999) {
        this.applyCompletion(task.object, b, { x: task.x, z: task.z });
        flags.completed.push({ builder: b.id, object: task.object, x: task.x, z: task.z });
        if (!b.factory) { b.x = task.destX ?? task.x; b.z = task.destZ ?? task.z; }
        b.task = null;
        const nxt = b.queue.shift();
        if (nxt) this.assign(b, nxt.object, nxt.x, nxt.z);
      }
    }
    this.runConverters(dt);
    if (this.metal > this.maxMetal) { this.overflowLost.m += this.metal - this.maxMetal; this.metal = this.maxMetal; }
    if (this.energy > this.maxEnergy) { this.overflowLost.e += this.energy - this.maxEnergy; this.energy = this.maxEnergy; }
    this.metal = Math.max(0, this.metal); this.energy = Math.max(0, this.energy);
    this.time += dt;
    return flags;
  }

  /** Run ticks until `untilSec`. Returns the completion list. */
  runUntil(untilSec, { dt = 0.5, decider = null, onTick = null } = {}) {
    const done = [];
    while (this.time < untilSec - 1e-9) {
      const step = Math.min(dt, untilSec - this.time);
      const f = this.tick(step, decider);
      for (const c of f.completed) done.push({ ...c, time: this.time });
      if (onTick) onTick(this, f);
    }
    return done;
  }

  // ── reality coupling ─────────────────────────────────────────────────────────
  /**
   * Snap to a parser moment. Known fields overwrite; unknown ones keep the simulated value.
   * `incomeAdjust` absorbs whatever the model does not explain (reclaim, shares, unmodeled units)
   * so the simulated income equals the measured income at the reset instant.
   */
  resetToReality(m) {
    this.time = m.sec;
    if (m.wind != null) this.wind = m.wind;
    if (m.known.bank) { this.metal = m.metal; this.energy = m.energy; }
    if (m.known.storage) { this.maxMetal = m.storM; this.maxEnergy = m.storE; }
    if (m.known.units) {
      this.buildings = []; this.numberConverters = 0;
      this.metalPerSecond = 0; this.energyPerSecond = 0;
      let storM = BASE_STORAGE.metal, storE = BASE_STORAGE.energy;
      for (const [defName, n] of Object.entries(m.units)) {
        const t = this.registry.get(defName); if (!t) continue;
        for (let i = 0; i < n; i++) {
          if (t.kind !== "builder") this.buildings.push(t.name);
          if (t.converter) this.numberConverters += t.converter;
          if (t.storE) storE += t.storE; if (t.storM) storM += t.storM;
          this.metalPerSecond += t.mInc || 0; this.energyPerSecond += t.eInc || 0;
        }
      }
      if (!m.known.storage) { this.maxMetal = storM; this.maxEnergy = storE; }
    }
    if (m.known.builders) {
      const prev = new Map(this.builders.filter(b => b.unitID != null).map(b => [b.unitID, b]));
      const next = [];
      for (const rb of m.builders) {
        const t = this.registry.get(rb.defName); if (!t) continue;
        const old = prev.get(rb.unitID);
        const b = old || makeBuilder(t, { unitID: rb.unitID, id: `${t.name}#${rb.unitID}` });
        b.bp = rb.bp || t.builderBp || 0; b.x = rb.x; b.z = rb.z; b.factory = !!rb.isFactory;
        if (rb.idle || !rb.building) b.task = null;
        else if (!b.task) b.task = this._guessTask(b, m);
        else b.task.walkLeft = 0;
        next.push(b);
      }
      // builder_status can lag unit_finished (frame 0 especially): any finished builder-type unit the
      // roster knows but the status list does not gets a builder at the team start position
      if (m.units) {
        const have = {}; for (const b of next) have[b.type.name] = (have[b.type.name] || 0) + 1;
        for (const [defName, n] of Object.entries(m.units)) {
          const t = this.registry.get(defName); if (!t || t.kind !== "builder" || !(t.builderBp > 0)) continue;
          for (let i = have[t.name] || 0; i < n; i++) {
            const old = this.builders.find(b => b.type.name === t.name && !next.includes(b));
            next.push(old || makeBuilder(t, { id: `${t.name}#?${i}`, x: this.startX || 0, z: this.startZ || 0, priority: t.name === "Commander" ? "high" : "low" }));
          }
        }
      }
      this.builders = next;
      // every nanoframe reality has in progress must be on SOME builder's list, or the sim silently
      // drops work reality is doing: unmatched ones go to the nearest builder that says "building"
      // but has no task, else the nearest idle builder, else the nearest builder's queue
      if (m.building) {
        const covered = new Set();
        for (const b of next) { if (b.task && b.task.guessed) covered.add(b.task.x + ":" + b.task.z); for (const q of b.queue) covered.add(q.x + ":" + q.z); }
        for (const u of m.building) {
          const t = this.registry.get(u.defName); if (!t || covered.has(u.x + ":" + u.z)) continue;
          const wantsFactory = t.kind === "unit" || (t.kind === "builder" && (t.speed || 0) > 0);
          const cands = next.filter(b => b.bp > 0 && (wantsFactory ? b.factory : !b.factory));
          if (!cands.length) continue;
          const dist = b => b.factory ? 0 : Math.hypot(u.x - b.x, u.z - b.z);
          const pick = (arr) => arr.length ? arr.reduce((a, b) => (dist(b) < dist(a) ? b : a)) : null;
          const rb = new Map(m.builders.map(x => [x.unitID, x]));
          const b = pick(cands.filter(c => !c.task && rb.get(c.unitID) && rb.get(c.unitID).building)) || pick(cands.filter(c => !c.task)) || pick(cands);
          const elapsed = Math.max(0, (m.frame - u.sinceFrame) / FPS);
          this.assign(b, t.name, u.x, u.z);
          if (b.task && b.task.object === t.name && b.task.x === u.x) { b.task.walkLeft = 0; b.task.progress = Math.min(0.9, t.bp > 0 ? (b.bp * elapsed) / t.bp : 0); b.task.guessed = true; }
          covered.add(u.x + ":" + u.z);
        }
      }
    }
    // residual = measured − modelled income (reclaim, shares, unmodelled units). The frame-0 moment
    // reports 0 income before anything has produced, so the residual is only trusted after ~10 s.
    if (m.known.income && m.sec >= 10) {
      this.incomeAdjust.m = m.mIncome - this.metalPerSecond;
      this.incomeAdjust.e = m.eIncome - (this.incomeE() - this.incomeAdjust.e);
    } else { this.incomeAdjust.m = 0; this.incomeAdjust.e = 0; }
    return this;
  }

  // A builder reported "building" with no known target: take the nearest in-range nanoframe.
  _guessTask(b, m) {
    if (!m.building || !m.building.length) return null;
    let best = null, bestD = Infinity;
    for (const u of m.building) {
      const t = this.registry.get(u.defName); if (!t) continue;
      const d = Math.hypot(u.x - b.x, u.z - b.z);
      if (d <= b.range + 120 && d < bestD) { best = u; bestD = d; }   // +120: building footprints are measured from the centre
    }
    if (!best) return null;
    const t = this.registry.get(best.defName);
    const elapsed = Math.max(0, (m.frame - best.sinceFrame) / FPS);
    const progress = Math.min(0.9, t.bp > 0 ? (b.bp * elapsed) / t.bp : 0);
    return { object: t.name, x: best.x, z: best.z, progress, walkLeft: 0, metalSpent: t.metal * progress, energySpent: t.energy * progress, startedAt: m.sec - elapsed, guessed: true };
  }

  /** Simulated − real, for the fields the moment knows. */
  divergence(m) {
    const d = { sec: m.sec };
    if (m.known.bank) { d.metal = this.metal - m.metal; d.energy = this.energy - m.energy; }
    if (m.known.income) { d.mIncome = this.incomeM() - m.mIncome; d.eIncome = this.incomeE() - m.eIncome; }
    if (m.known.units) {
      const real = {}; for (const [defName, n] of Object.entries(m.units)) { const t = this.registry.get(defName); if (t) real[t.name] = (real[t.name] || 0) + n; }
      const sim = this.counts(); d.units = {};
      for (const k of new Set([...Object.keys(real), ...Object.keys(sim)])) { const diff = (sim[k] || 0) - (real[k] || 0); if (diff) d.units[k] = diff; }
    }
    return d;
  }
}

// ───────────────────────────────────────────── game-level loops
function environmentForTeam(game, teamID, registry = null) {
  const reg = registry || new TypeRegistry(game);
  const t = game.teams.get(teamID) || {};
  const env = new Environment({ registry: reg, time: 0, wind: game.wind.length ? game.wind[0].value : DEFAULT_WIND });
  env.startX = t.startX || 0; env.startZ = t.startZ || 0;
  env.builders[0].x = env.startX; env.builders[0].z = env.startZ;
  env.mexSpots = game.mexSpots || [];
  env.windSeries = game.wind && game.wind.length ? game.wind : null;   // recorded wind → same weather as reality
  return env;
}

/**
 * A decider that re-issues reality's own decisions: every unit the team STARTED (widget
 * `created`, or demo `order`) is assigned to the builder that can start it soonest, and every
 * unit that DIED is removed (own eco with no attacker = reclaim → metal refunded). With this
 * decider the simulation answers "given the same decisions, does the modelled economy track
 * the real one?" — the fidelity question `simulateSpan` step mode reports on.
 */
function replayDecider(game, teamID) {
  const evs = game.events.filter(e => e.teamID === teamID && (e.kind === "created" || e.kind === "order" || e.kind === "killed"));
  let cursor = 0;
  const reg = { last: -1 };
  return env => {
    // a reset can move time backwards (step mode) — re-seek
    if (env.time < reg.last) { cursor = 0; while (cursor < evs.length && evs[cursor].sec < env.time) cursor++; }
    reg.last = env.time;
    while (cursor < evs.length && evs[cursor].sec <= env.time) {
      const e = evs[cursor++];
      const typeName = env.registry.resolve(e.defName); if (!typeName) continue;
      if (e.kind === "killed") {
        if (e.finished === false) continue;                     // a nanoframe died: nothing was ever completed
        // the widget reports a reclaim as a kill by the owner (attackerTeam = own team) or with no attacker
        const own = e.attackerTeam == null || e.attackerTeam === teamID;
        env.removeCompletion(typeName, { reclaim: own && env.registry.get(typeName).kind === "building", unitID: e.unitID });
        continue;
      }
      if (typeName === "Commander") continue;
      if (e.kind === "created" && e.sec < env.time - env.every) continue;   // stale (before the last reset)
      const b = env.chooseBuilder(typeName, e.x, e.z);
      if (b) env.assign(b, typeName, e.x, e.z);
    }
  };
}

/**
 * Alternate reset ↔ simulate over a team's moments.
 *   mode "step": reset at each moment, simulate to the next, report drift (sim fidelity per interval)
 *   mode "free": reset once at `from`, then simulate without resets, report drift at each moment
 * decisions: "replay" (reality's own build starts, default) | "none" | a decider function
 *   (the strategizer hook: `decider(env)` runs every tick and may assign idle builders).
 */
function simulateSpan(game, teamID, { mode = "step", from = 0, dt = 0.5, decisions = "replay", until = Infinity } = {}) {
  const moments = P.momentsFor(game, teamID).filter(m => m.sec <= until);
  const env = environmentForTeam(game, teamID);
  env.every = game.every || 15;
  const decider = typeof decisions === "function" ? decisions : decisions === "replay" ? replayDecider(game, teamID) : null;
  const rows = [];
  let started = false;
  for (let i = 0; i < moments.length - 1; i++) {
    const a = moments[i], b = moments[i + 1];
    if (a.sec < from) continue;
    if (mode === "step" || !started) { env.resetToReality(a); started = true; }
    const completed = env.runUntil(b.sec, { dt, decider });
    rows.push({ from: a.sec, to: b.sec, completed, drift: env.divergence(b),
      sim: { metal: env.metal, energy: env.energy, mIncome: env.incomeM(), eIncome: env.incomeE(), counts: env.counts() },
      real: { metal: b.metal, energy: b.energy, mIncome: b.mIncome, eIncome: b.eIncome } });
  }
  return { env, rows };
}

// ───────────────────────────────────────────── 6. ROI report (bar_unified.generator_roi_report)
function generatorRoiReport(builderBp = DEFAULT_BUILDER_BP, windAvg = null, registry = null) {
  const R = registry || new TypeRegistry();
  console.log(`Generator ROI  (${ENERGY_PER_METAL} E = 1 M, builder ${builderBp.toFixed(0)} BP)`);
  console.log(`  ${"gen".padEnd(10)} ${"out E/s".padStart(8)} ${"BuildT".padStart(8)} ${"EROI".padStart(10)} ${"TROI".padStart(8)}`);
  const rows = [["Solar", R.get("Solar").eInc], ["Wind", windAvg != null ? windAvg : R.get("Wind").eInc], ["AdvSolar", R.get("AdvSolar").eInc]];
  for (const [name, out] of rows) {
    const o = R.get(name);
    const e = o.energy === 0 ? "build" : `${eroi(o, out, builderBp).toFixed(1)}s`;
    console.log(`  ${name.padEnd(10)} ${out.toFixed(1).padStart(8)} ${(buildTime(o, builderBp).toFixed(1) + "s").padStart(8)} ${e.padStart(10)} ${(troi(o, out).toFixed(0) + "s").padStart(8)}`);
  }
}

// ───────────────────────────────────────────── self test (port fidelity vs bar_unified.py / bar_calc.py)
function selftest() {
  if (!fs.existsSync(PARITY_PATH)) { console.log("no parity file; run: python bar-calc/bar_unified.py --write-parity"); return false; }
  const P = JSON.parse(fs.readFileSync(PARITY_PATH, "utf8"));
  const bad = []; let n = 0;
  const same = (a, b, abs) => {
    if (typeof a === "number" && typeof b === "number") {
      if (!isFinite(a) || !isFinite(b)) return a === b;
      return Math.abs(a - b) <= (abs != null ? abs : 1e-6 * Math.max(1, Math.abs(a)));
    }
    return a === b || (a == null && b == null);
  };
  const cmp = (label, want, got, abs) => { n++; if (!same(want, got, abs)) bad.push(`${label}: parity ${JSON.stringify(want)}  js ${JSON.stringify(got === undefined ? null : got)}`); };
  // constants, grid calibration, builder profiles
  cmp("constants.energyPerMetal", P.constants.energyPerMetal, ENERGY_PER_METAL);
  cmp("constants.defaultBuilderBp", P.constants.defaultBuilderBp, DEFAULT_BUILDER_BP);
  cmp("constants.defaultWind", P.constants.defaultWind, DEFAULT_WIND);
  cmp("constants.gameFps", P.constants.gameFps, GAME_FPS);
  cmp("constants.buildRangeInGridSquares", P.constants.buildRangeInGridSquares, BUILD_RANGE_IN_GRID_SQUARES);
  cmp("constants.elmosPerGridSquare", P.constants.elmosPerGridSquare, ELMOS_PER_GRID_SQUARE);
  for (const [k, p] of Object.entries(P.profiles)) for (const f of ["buildRange", "speed", "bp"]) cmp(`profiles.${k}.${f}`, p[f], UNIT_PROFILES[k] && UNIT_PROFILES[k][f]);
  // object table: every field of every object
  for (const [name, o] of Object.entries(P.objects)) {
    const t = OBJECT_TYPES[name];
    if (!t) { cmp(`objects.${name}`, "present", "missing"); continue; }
    for (const f of ["kind", "metal", "energy", "bp", "mInc", "eInc", "storE", "storM", "converter", "windPowered", "factory", "defName", "provisional"]) cmp(`objects.${name}.${f}`, o[f], t[f]);
    if (o.kind === "builder") for (const f of ["builderBp", "speed", "range"]) cmp(`objects.${name}.${f}`, o[f], t[f]);
  }
  for (const name of Object.keys(OBJECT_TYPES)) if (!(name in P.objects)) cmp(`objects.${name}`, "missing", "present");
  for (const [d, name] of Object.entries(P.aliases)) cmp(`aliases.${d}`, name, ALIASES[d]);
  // ROI helpers + walk model
  const R = new TypeRegistry();
  cmp("roi.solarTroi", P.roi.solarTroi, troi(R.get("Solar"), R.get("Solar").eInc));
  cmp("roi.windTroi", P.roi.windTroi, troi(R.get("Wind"), R.get("Wind").eInc));
  cmp("roi.windEroi", P.roi.windEroi, eroi(R.get("Wind"), R.get("Wind").eInc));
  cmp("roi.solarBuildTime", P.roi.solarBuildTime, buildTime(R.get("Solar")));
  cmp("roi.walkCon400", P.roi.walkCon400, walkTime(400, "con_bot"));
  // the two demo openings (bar_unified: walks; bar_calc: t=3, +1 s per build)
  const snap = e => ({ time: e.time, metal: e.metal, energy: e.energy, maxMetal: e.maxMetal, maxEnergy: e.maxEnergy, mInc: e.incomeM(), eInc: e.incomeE(), bp: e.totalBp() });
  const u = new Environment(); u.buildOrder(P.unifiedDemo.order);
  const su = snap(u); for (const [k, v] of Object.entries(P.unifiedDemo.result)) cmp(`unifiedDemo.${k}`, v, su[k]);
  const c = new Environment({ time: P.barCalcDemo.start.time });
  for (const o of P.barCalcDemo.order) c.constructObject(o, { minAddTime: P.barCalcDemo.minAddTime });
  const sc = snap(c); for (const [k, v] of Object.entries(P.barCalcDemo.result)) cmp(`barCalcDemo.${k}`, v, sc[k]);
  // Legion actions (positions/state_api.py ACTIONS): same defs → same costs and income deltas
  for (const [aid, a] of Object.entries(P.legion.actions)) {
    let got; try { got = resolveLegionAction(aid); } catch (e) { cmp(`legion.${aid}`, "resolvable", e.message); continue; }
    if (!got) { cmp(`legion.${aid}`, "present", "missing"); continue; }
    for (const f of ["def", "metal", "energy", "bw", "dm", "de_inc", "de_upk", "reclaim"]) cmp(`legion.${aid}.${f}`, a[f], got[f]);
  }
  for (const aid of Object.keys(ECON.legion.actions)) if (!(aid in P.legion.actions)) cmp(`legion.${aid}`, "missing", "present");
  // continuous tick: one mex by the commander from the start → bp / comBp seconds of work, no stall
  const mex = OBJECT_TYPES.Mex, com = OBJECT_TYPES.Commander;
  const c2 = new Environment({ time: 0 }); c2.assign(c2.builders[0], "Mex");
  const done = c2.runUntil(30, { dt: 1 / 30 });
  cmp("tick.mexDoneAt", mex.bp / com.builderBp, done.length ? done[0].time : null, 0.1);
  cmp("tick.incomeM", com.mInc + mex.mInc, c2.incomeM(), 1e-9);
  // walk: a con 400 elmos away walks (400 − range) / speed before working, then builds a wind at its own BP
  const con = OBJECT_TYPES.BotWorker, wind = OBJECT_TYPES.Wind;
  const w = new Environment({ time: 0, builders: [makeBuilder(new TypeRegistry().get("BotWorker"), { id: "con", x: 0, z: 0 })] });
  w.assign(w.builders[0], "Wind", 400, 0);
  const wd = w.runUntil(120, { dt: 1 / 30 });
  cmp("walk.windDoneAt", walkTime(400, "con_bot") + wind.bp / con.builderBp, wd.length ? wd[0].time : null, 0.1);
  console.log(`  unifiedDemo   t=${su.time.toFixed(2)}s  M=${su.metal.toFixed(1)}  E=${su.energy.toFixed(1)}  +${su.mInc.toFixed(3)}M/s +${su.eInc.toFixed(1)}E/s  BP=${su.bp}`);
  console.log(`  barCalcDemo   t=${sc.time.toFixed(2)}s  M=${sc.metal.toFixed(1)}  E=${sc.energy.toFixed(1)}  +${sc.mInc.toFixed(3)}M/s +${sc.eInc.toFixed(1)}E/s  BP=${sc.bp}`);
  console.log(`  tick: mex done ${done.length ? done[0].time.toFixed(2) : "never"} s · walk: wind 400 elmos away done ${wd.length ? wd[0].time.toFixed(2) : "never"} s`);
  for (const b of bad.slice(0, 40)) console.log("  ✘ " + b);
  console.log(bad.length ? `\nselftest FAILED: ${bad.length} of ${n} values differ from ${path.basename(PARITY_PATH)}` : `\nselftest OK: ${n} values match ${path.basename(PARITY_PATH)}`);
  return bad.length === 0;
}

// ───────────────────────────────────────────── CLI
function mmss(sec) { const m = Math.floor(sec / 60), s = Math.round(sec % 60); return `${m}:${String(s).padStart(2, "0")}`; }
function pad(s, n) { s = String(s); return s.length >= n ? s : s + " ".repeat(n - s.length); }
function padL(s, n) { s = String(s); return s.length >= n ? s : " ".repeat(n - s.length) + s; }
function sgn(v, d = 0) { return v == null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(d); }

function parseArgs(argv) {
  const a = { source: null, team: null, every: 15, until: 900, free: null, dt: 0.5, json: null, selftest: false, decisions: "replay" };
  const rest = [];
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t === "--team") a.team = argv[++i];
    else if (t === "--decisions") a.decisions = argv[++i];
    else if (t === "--every") a.every = Number(argv[++i]) || 15;
    else if (t === "--until") { const v = argv[++i]; a.until = v === "full" ? Infinity : (Number(v) || 900); }
    else if (t === "--free") a.free = Number(argv[++i]) || 0;
    else if (t === "--dt") a.dt = Number(argv[++i]) || 0.5;
    else if (t === "--json") a.json = argv[++i];
    else if (t === "--selftest") a.selftest = true;
    else if (t === "--roi") a.roi = true;
    else if (t === "--wind") a.wind = Number(argv[++i]);
    else if (t === "--bp") a.bp = Number(argv[++i]) || DEFAULT_BUILDER_BP;
    else rest.push(t);
  }
  a.source = rest[0] || "1";
  return a;
}

function printRows(rows, title) {
  console.log(`\n${title}`);
  console.log(`  ${pad("interval", 13)} ${padL("sim M", 6)} ${padL("real M", 6)} ${padL("ΔM", 6)} ${padL("sim E", 6)} ${padL("real E", 6)} ${padL("ΔE", 6)} ${padL("Δm/s", 6)} ${padL("Δe/s", 7)}  completed (sim)   unit drift`);
  for (const r of rows) {
    const d = r.drift;
    const comp = r.completed.map(c => c.object).reduce((m, o) => (m[o] = (m[o] || 0) + 1, m), {});
    const compS = Object.entries(comp).map(([k, v]) => `${v}×${k}`).join(" ");
    const ud = d.units ? Object.entries(d.units).map(([k, v]) => `${k}${sgn(v)}`).join(" ") : "";
    console.log(`  ${pad(mmss(r.from) + "→" + mmss(r.to), 13)} ${padL(Math.round(r.sim.metal), 6)} ${padL(r.real.metal == null ? "—" : Math.round(r.real.metal), 6)} ${padL(sgn(d.metal), 6)} ${padL(Math.round(r.sim.energy), 6)} ${padL(r.real.energy == null ? "—" : Math.round(r.real.energy), 6)} ${padL(sgn(d.energy), 6)} ${padL(sgn(d.mIncome, 1), 6)} ${padL(sgn(d.eIncome, 1), 7)}  ${pad(compS, 18)} ${ud}`);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.selftest) { process.exit(selftest() ? 0 : 1); }
  if (args.roi) { generatorRoiReport(args.bp || DEFAULT_BUILDER_BP, args.wind != null && !Number.isNaN(args.wind) ? args.wind : null); return; }
  const game = await P.parseSource(args.source, { every: args.every, until: args.until });
  const teamID = P.findTeam(game, args.team);
  if (teamID == null) throw new Error(`--team required; teams: ${[...game.teams].map(([id, t]) => `${id}=${t.name}`).join(", ")}`);
  const t = game.teams.get(teamID);
  console.log(`\nBAR Build Simulator — ${game.map || "?"}  [${game.source}] ${path.basename(game.path)}`);
  console.log(`team ${teamID} ${t.name}  · every ${args.every}s · dt ${args.dt}s · moments ${P.momentsFor(game, teamID).length} · decisions ${args.decisions}`);
  const step = simulateSpan(game, teamID, { mode: "step", dt: args.dt, until: args.until, decisions: args.decisions });
  printRows(step.rows, `== Step mode: reset at each moment, simulate to the next (Δ = simulated − real) ==`);
  let free = null;
  if (args.free != null) {
    free = simulateSpan(game, teamID, { mode: "free", from: args.free, dt: args.dt, until: args.until, decisions: args.decisions });
    printRows(free.rows, `== Free mode: reset once at ${mmss(args.free)}, then simulate with no further resets ==`);
  }
  if (args.json) {
    fs.writeFileSync(args.json, JSON.stringify({ team: teamID, name: t.name, step: step.rows, free: free ? free.rows : null }, null, 1));
    console.log(`\nwrote ${args.json}`);
  }
}

module.exports = {
  // bar_unified §1–3
  ENERGY_PER_METAL, DEFAULT_BUILDER_BP, GAME_FPS, UNIT_PROFILES, BUILD_RANGE_IN_GRID_SQUARES, ELMOS_PER_GRID_SQUARE,
  resolveUnit, squaresToElmos, elmosToSquares, canReach, walkTime, walkTimeSquares, windIncome,
  // §4 object data + ROI
  OBJECT_TYPES, ALIASES, FACTORY_PRODUCTS, DEFAULT_WIND, buildTime, troi, eroi, unitdefLibrary,
  // the shared data layer (bar-calc/econ_model.json + engine dumps) and its derivation rules
  ECON, ECON_MODEL_PATH, PARITY_PATH, energyFlows, mexIncome, resolveObjectType, resolveLegionAction,
  // §5–6 environment, report, game loops
  TypeRegistry, Environment, makeBuilder, environmentForTeam, simulateSpan, replayDecider, generatorRoiReport, selftest };

if (require.main === module) main().catch(e => { console.error("✘ " + (e.stack || e.message)); process.exit(1); });

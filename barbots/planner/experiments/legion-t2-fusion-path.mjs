// legion-t2-fusion-path.mjs — Legion pos6 T2 fusion line, simulated through eco_engine,
// every number shown. Sweeps medmex count (0-4) as INDEPENDENT calculations (each its own
// battery, no shared formula).
//
// Build order (matches barbots/intents/legion-pos6-t2-fusion.md, the team's established
// opening): 5 mex + 5 solar + factory -> 3 workers (1 to air) -> mex 6+7 -> medmex(es) ->
// con turret for BP -> solar+estor battery -> T2 factory -> T2 con -> fusion, RECLAIMING
// the battery's solars+estor into the fusion (it eats them, ending at 0 solars).
//
// Costs: read directly from gex_research/legion/legion_unitdefs.json (same `def()` lookup
// legion_eco.mjs uses) — no hand-duplicated numbers. T1 legmex uses eco_engine's NATIVE
// mex/upkeep mechanic (state.mexes + state.mex.{mPerSec,eUpkeep}) instead of manual income
// hacking — legmex is energy-POSITIVE (+7E, modeled as eUpkeep:-7) so it never stalls itself,
// matching "Extracts Slightly Reduced Metal and Produces 7 Energy".
//
// Run:  node planner/experiments/legion-t2-fusion-path.mjs

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createState, tick, simulateBuild, applyCompletion } from "../../../gex_research/process/lib/sim/eco_engine.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const DB = JSON.parse(readFileSync(path.join(here, "../../../gex_research/legion/legion_unitdefs.json"), "utf8"));
const def = (n) => { const d = DB.defs.find((x) => x.defName === n); if (!d) throw new Error(`no legion def "${n}"`); return d; };

const WIND = 14;   // ATG average (LEGION_ECON.md WIND_AVG)
const r0 = (x) => Math.round(x), r1 = (x) => Math.round(x * 10) / 10, pad = (s, n) => String(s).padStart(n);
const fmt = (s) => { const t = r0(s); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };

// ── Sourced costs (legion_unitdefs.json fields -> eco_engine's {m,e,bp,gives} shape) ──
const D = {
  factory: def("leglab"),    worker: def("legck"),     mex: def("legmex"),
  medmex:  def("legmext15"), turret: def("legnanotc"), solar: def("legsolar"),
  estor:   def("legestor"),  t2fac:  def("legalab"),   t2con: def("legack"),
  fusion:  def("legfus"),    com:    def("legcom"),
};
const UNITS = {
  factory: { m: D.factory.metalCost, e: D.factory.energyCost, bp: D.factory.buildTime, gives: {} },
  worker:  { m: D.worker.metalCost,  e: D.worker.energyCost,  bp: D.worker.buildTime,  gives: {} },  // applied manually (it's also a mex builder choice point)
  turret:  { m: D.turret.metalCost,  e: D.turret.energyCost,  bp: D.turret.buildTime,  gives: { builderBp: D.turret.buildPower } },
  sol:     { m: D.solar.metalCost,   e: D.solar.energyCost,   bp: D.solar.buildTime,   gives: {} },   // "solar" key reserved by eco_engine's own solar bookkeeping; sol applied manually
  estor:   { m: D.estor.metalCost,   e: D.estor.energyCost,   bp: D.estor.buildTime,   gives: { storE: D.estor.energyStorage } },
  mex:     { m: D.mex.metalCost,     e: D.mex.energyCost,     bp: D.mex.buildTime,     gives: {} },   // applied manually -> state.mexes++ (native mex income)
  medmex:  { m: D.medmex.metalCost,  e: D.medmex.energyCost,  bp: D.medmex.buildTime,  gives: {} },   // applied manually -> mex upgrade delta
  t2fac:   { m: D.t2fac.metalCost,   e: D.t2fac.energyCost,   bp: D.t2fac.buildTime,   gives: {} },
  t2con:   { m: D.t2con.metalCost,   e: D.t2con.energyCost,   bp: D.t2con.buildTime,   gives: { builderBp: D.t2con.buildPower, ePerSec: D.t2con.energyProduction } },
  fusion:  { m: D.fusion.metalCost,  e: D.fusion.energyCost,  bp: D.fusion.buildTime,  gives: { ePerSec: D.fusion.energyProduction } },
};

// Calibrated T1 legmex rate (LEGION_ECON.md: "measured ... empirically exact" — 1.47 m/s).
// medmex rate derives from the SAME spot via the sourced extractsMetal ratio
// (legmext15 0.002 / legmex 0.0008 = 2.5x), exactly as legion_eco.mjs's mps() computes it.
const LEGMEX_MPS = 1.47;
const MEDMEX_MPS = LEGMEX_MPS * (D.medmex.extractsMetal / D.mex.extractsMetal);   // 1.47 * 2.5 = 3.675
const LEGMEX_E = -D.mex.energyUpkeep;       // +7 (engine convention: state.mex.eUpkeep negative = produces)
const MEDMEX_E = -D.medmex.energyUpkeep;    // -30 (drains)
const WORKER_BP = D.worker.buildPower;      // 75 (legck) — NOT the ARM 80 some of this codebase used before
const TURRET_BP = D.turret.buildPower;      // 200
const T2CON_BP  = D.t2con.buildPower;       // 195
const COM_BP    = D.com.buildPower;         // 300

// Simulate the whole line for `nMedTotal` medmex upgrades, with an EXPLICIT battery size
// (no shared formula across cases — each medmex count is its own problem, its own battery).
function simulate(nMedTotal, nSolarBattery, verbose) {
  let bp = COM_BP, nMexT1 = 5, nMed = 0, nEstor = 0;
  let s = createState({
    metal: 500, energy: 700, storM: D.com.metalStorage + 1000, storE: D.com.energyStorage + 500,
    mexes: nMexT1, solars: 5,
    extraEPerSec: D.com.energyProduction,           // commander's own +30 E (its mex income is base.m)
    base: { m: D.com.metalMake, e: 0 },              // commander passive +2 m/s
    builders: [{ name: "pool", bp, priority: "high" }],
    units: UNITS, mex: { mPerSec: LEGMEX_MPS, eUpkeep: -LEGMEX_E },   // native mex income/upkeep (legmex never self-stalls)
  });
  const mInc = () => s.base.m + nMexT1 * LEGMEX_MPS;
  const eInc = () => s.extraEPerSec + s.solars * 20 + nMexT1 * LEGMEX_E;

  function step(label, key, after) {
    const b0 = { m: s.metal, e: s.energy, t: s.t };
    s.builders = [{ name: "pool", bp, priority: "high" }];
    const r = simulateBuild(s, key, { priority: "high", wind: WIND });
    s = r.endState;
    if (after) after();
    if (verbose) console.log(
      `${pad(fmt(s.t), 7)} ${label.padEnd(20)} ${pad(bp, 4)} ${pad(r1(s.t - b0.t) + "s", 6)} │ ` +
      `${pad(r0(b0.m), 6)}→${pad(r0(s.metal), 6)} ${pad(r1(mInc()), 5)} │ ` +
      `${pad(r0(b0.e), 6)}→${pad(r0(s.energy), 6)} ${pad(r0(eInc()), 5)} │ ` +
      `${r.throttledSec > 1 ? "STALL " + r1(r.throttledSec) + "s" : ""}`);
    return r;
  }

  if (verbose) {
    console.log(`\nVERBOSE LEDGER — ${nMedTotal} medmex.  ENV 5 mex (legmex ${LEGMEX_MPS}m/s +${LEGMEX_E}E each), 5 solar, com ${COM_BP}BP`);
    console.log(`${"time".padEnd(7)} ${"step".padEnd(20)} ${"BP".padStart(4)} ${"dur".padStart(6)} │ ${"metal in→out".padStart(13)} ${"m/s".padStart(5)} │ ${"energy in→out".padStart(13)} ${"e/s".padStart(5)} │ stall`);
    console.log("─".repeat(92));
  }

  // PHASE 1 — factory, 3 workers (1 to air), mex 6+7, medmex #1 (mandatory: worker2's job)
  step("factory", "factory", () => { /* leglab itself adds no direct BP to the pool; its queue is separate */ });
  step("worker 1/3", "worker", () => { bp += WORKER_BP; });
  step("worker 2/3", "worker", () => { bp += WORKER_BP; });
  step("worker 3/3 → AIR", "worker");                                          // built, then given away: no BP added
  step("mex 6 (worker1)", "mex", () => { nMexT1++; s.mexes++; });
  step("mex 7 (worker1)", "mex", () => { nMexT1++; s.mexes++; });
  const upgradeMex = () => {
    nMed++; nMexT1--; s.mexes--;                                               // one legmex slot becomes a medmex
    s.base.m += MEDMEX_MPS; s.extraEPerSec += MEDMEX_E - LEGMEX_E;             // sourced delta (legion_eco.mjs's dMps/dEs)
  };
  step("medmex #1 (w2→AIR)", "medmex", upgradeMex);

  // PHASE 2 — con turret, battery (exactly nSolarBattery solars, the caller's choice), the
  // remaining medmexes, 2 estor
  step("con turret (+BP)", "turret", () => { bp += TURRET_BP; });
  for (let i = 1; i <= nSolarBattery; i++) step(`solar ${i}`, "sol", () => { s.solars++; });
  for (let i = 2; i <= nMedTotal; i++) step(`medmex #${i}`, "medmex", upgradeMex);
  step("estor 1", "estor", () => { nEstor++; });
  step("estor 2", "estor", () => { nEstor++; });

  // PHASE 3 — T2 factory → con → fusion (reclaim battery into the fusion's metal cost)
  const tCommit = s.t;
  step("T2 factory (legalab)", "t2fac");
  const t2facSec = s.t - tCommit;
  step("T2 con (factory BP)", "t2con", () => { bp += T2CON_BP; });
  const reclaim = s.solars * D.solar.metalCost + nEstor * D.estor.metalCost;
  s.units.fusion.m = Math.max(0, D.fusion.metalCost - reclaim);                // mutate the LIVE state's units (a clone)
  if (verbose) console.log(`     reclaim ${s.solars} solar + ${nEstor} estor = +${reclaim}m → fusion ${D.fusion.metalCost}→${s.units.fusion.m}m, solars→0`);
  const fr = step("FUSION (reclaim)", "fusion", () => { s.solars = 0; });

  return { nMed, mInc: mInc(), fusionSec: s.t, t2facSec, nSolarBattery, totalSolars: nSolarBattery + 5, reclaim, fusStall: fr.throttledSec };
}

// ── Each medmex count, calculated on its own terms ──────────────────────────────
console.log(`\nLegion T2 fusion — sourced from gex_research/legion/legion_unitdefs.json (no hand-typed costs):`);
console.log(`  legck worker ${WORKER_BP}BP (NOT ARM's 80), legmex ${LEGMEX_MPS}m/s +${LEGMEX_E}E, medmex ${r1(MEDMEX_MPS)}m/s ${MEDMEX_E}E`);
console.log(`\nEach medmex count calculated separately (own best battery — walk solars until fusion is soonest):\n`);
const headline = [];
for (const nMed of [0, 1, 2, 3, 4]) {
  let best = null;
  for (let nSolarBattery = 4; nSolarBattery <= 30; nSolarBattery++) {
    const r = simulate(nMed, nSolarBattery, false);
    if (!best || r.fusionSec < best.fusionSec - 0.01) best = r;
  }
  headline.push({ nMed, ...best });
  console.log(`${nMed} medmex  —  income ${r1(best.mInc)} m/s`);
  console.log(`   own battery = ${best.nSolarBattery} solar (${best.totalSolars} total) + 2 estor  →  reclaim ${best.reclaim}m into the fusion (${D.fusion.metalCost}→${Math.max(0, D.fusion.metalCost - best.reclaim)}m)`);
  console.log(`   T2 factory ${r0(best.t2facSec)}s (metal-gated: ${D.t2fac.metalCost}m ÷ ${r1(best.mInc)} m/s),  fusion build ${best.fusStall > 1 ? "STALL " + r1(best.fusStall) + "s" : "clean"}`);
  console.log(`   >>> FUSION ONLINE  ${fmt(best.fusionSec)}  (${r0(best.fusionSec)}s)\n`);
}
const fastest = headline.reduce((a, b) => b.fusionSec < a.fusionSec ? b : a);
console.log(`Fastest: ${fastest.nMed} medmex at ${fmt(fastest.fusionSec)}.  Verbose ledger:\n`);
simulate(fastest.nMed, fastest.nSolarBattery, true);
console.log("─".repeat(92) + "\n");

// legion-5walk-2workers.mjs — Eco theory experiment (standalone, runnable).
//
// THEORY UNDER TEST
// -----------------
// Legion pos-6 Tech opens with a 5-walk. At T=50s the commander has just placed the
// 5th mex and is free. The plan: build 2 workers (legck), then start a medmex (legmext15).
//
// PROBLEM: High-priority commander builds drain energy before mex upkeep (tick step 2 > step 3).
// With base income 67 e/s and commander draining 147 e/s per build, energy hits 0 fast and
// mexes stall — metal income drops while the metal bar is full.
//
// FIX: "Energy stall while having metal means we juggle another solar."
// Insert a solar build (155m, 8.67s ideal) between worker 1 and worker 2.
// Solar gives +20 e/s permanently. With solar online during medmex:
//   income 101 e/s − mex upkeep 9 e/s = 92 e/s available > medmex drain 80 e/s
//   → medmex runs at FULL SPEED, no throttle, no stalls.
//
// VARIANTS
//   A   — no solar. Commander → w1 → w2; worker → medmex. Stalls during worker builds.
//   B   — no solar. Worker 2 given to air right after starting medmex.
//   D   — solar juggle. Commander → w1 → solar → w2; worker → medmex. Reduced stalls.
//   E   — solar juggle + give to air.
//
// METRIC: mexStallSec (cumulative mex-seconds stalled) and metalLostToStalls,
//         plus totalGenerated at T=480s (8-min horizon).
//
// Run:  node planner/experiments/legion-5walk-2workers.mjs

import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT      = path.resolve(__dirname, "../../..");

// ── imports ───────────────────────────────────────────────────────────────────
const { createState, applyCompletion, tick, UNITS, BASE_INCOME } =
  await import(pathToFileURL(path.join(ROOT, "gex_research/process/lib/sim/eco_engine.mjs")).href);

const { UNITS_EXT } =
  await import(pathToFileURL(path.join(ROOT, "barbots/planner/project.mjs")).href);

// ── position snapshot (from extract-position.mjs --position legion-5walk) ─────
// Legion 5-walk at T=50s. synth_mexes=3 gives model income ≈ observed 7.87 m/s.
// extraEPerSec=42 absorbs Legion commander's higher base energy vs ARM BASE_E=25.
const SNAP = {
  t:            50,
  metal:        991.7,
  energy:       763,
  storM:        1200,
  storE:        1000,
  mexes:        3,
  extraEPerSec: 42,   // Legion commander net extra over ARM BASE_E=25 (observed 58 e/s net)
};

// ── constants ─────────────────────────────────────────────────────────────────
const COMMANDER_BP = 300;
const WORKER_BP    = 80;
const WIND         = 14;   // ATG average wind (e/s per turbine)

const LEG_CON    = "leg_con";    // worker legck
const LEG_MEDMEX = "leg_medmex"; // medmex legmext15
const SOLAR      = "solar";      // ARM solar proxy (m=155, e=0,   bp=2600, +20 e/s fixed)
const WIND_T     = "wind";       // ARM wind  proxy (m=40,  e=175, bp=1600, +14 e/s @ ATG wind=14)

// Ideal build times at full BP (actual will be longer due to energy throttle)
const T_WORKER_IDEAL = UNITS_EXT[LEG_CON].bp    / COMMANDER_BP; // 3250/300 = 10.83s
const T_MEDMEX_IDEAL = UNITS_EXT[LEG_MEDMEX].bp / WORKER_BP;    // 5000/80  = 62.5s
const T_SOLAR_IDEAL  = UNITS_EXT[SOLAR].bp       / COMMANDER_BP; // 2600/300 = 8.67s
const T_WIND_IDEAL   = UNITS_EXT[WIND_T].bp      / COMMANDER_BP; // 1600/300 = 5.33s

const T_HORIZON = 480;   // 8-min horizon

// ── helpers ────────────────────────────────────────────────────────────────────
function freshState() {
  return createState({
    metal:        SNAP.metal,
    energy:       SNAP.energy,
    storM:        SNAP.storM,
    storE:        SNAP.storE,
    mexes:        SNAP.mexes,
    extraEPerSec: SNAP.extraEPerSec,
    builders:     [{ name: "commander", bp: COMMANDER_BP, priority: "high" }],
    units:        UNITS_EXT,
  });
}

// Simulate one build using ONLY the named builder (others remain passive — income/give still active).
// Returns { state, wallSec, throttledSec }.
function buildWith(startState, unitKey, builderName, priority = "low") {
  const state   = structuredClone(startState);
  const builder = state.builders.find(b => b.name === builderName);
  if (!builder) throw new Error(`Builder "${builderName}" not found in state at t=${state.t.toFixed(1)}`);
  const others  = state.builders.filter(b => b !== builder);
  state.builders = [{ ...builder, priority }];

  const DT           = 1 / 30;
  const job          = { unit: unitKey, priority, progress: 0, done: false };
  let   throttledSec = 0;
  const tStart       = state.t;
  const tMax         = state.t + (state.units[unitKey].bp / builder.bp) * 5; // safety timeout

  while (!job.done && state.t < tMax) {
    const f = tick(state, DT, job, WIND);
    if (f.jobThrottled) throttledSec += DT;
  }
  if (job.done) applyCompletion(state, unitKey);
  state.builders.push(...others);

  return { state, wallSec: state.t - tStart, throttledSec };
}

// Idle for durationSec (no active build).
function idle(startState, durationSec) {
  const state = structuredClone(startState);
  const DT    = 1 / 30;
  const tEnd  = state.t + durationSec;
  while (state.t < tEnd) tick(state, DT, null, WIND);
  return state;
}

// Remove first builder with name from pool (in-place).
function removeBuilder(state, builderName) {
  const idx = state.builders.findIndex(b => b.name === builderName);
  if (idx >= 0) state.builders.splice(idx, 1);
}

// Summary snapshot.
function snap(state) {
  return {
    t:             parseFloat(state.t.toFixed(1)),
    metal:         Math.round(state.metal),
    energy:        Math.round(state.energy),
    gen:           parseFloat(state.totalGenerated.toFixed(1)),
    stalls:        parseFloat(state.mexStallSec.toFixed(1)),
    metalLost:     parseFloat(state.metalLostToStalls.toFixed(1)),
    solars:        state.solars,
    winds:         state.winds,
  };
}

function fmtT(t) {
  const m = Math.floor(t / 60);
  const s = (t % 60).toFixed(0).padStart(2, "0");
  return `${m}:${s}`;
}

// ── Variant A: no solar — commander → w1 → w2; worker → medmex ────────────────
const A0  = freshState();
const Aw1 = buildWith(A0,       LEG_CON,    "commander", "high");
const Aw2 = buildWith(Aw1.state, LEG_CON,   "commander", "high");
const Amx = buildWith(Aw2.state, LEG_MEDMEX, LEG_CON,   "low");
const Af  = idle(Amx.state, T_HORIZON - Amx.state.t);

// ── Variant B: no solar — same as A, give w2 to air right after starting medmex
const B0  = freshState();
const Bw1 = buildWith(B0,       LEG_CON,   "commander", "high");
const Bw2 = buildWith(Bw1.state, LEG_CON,  "commander", "high");
// Worker 2 takes one tick on medmex (registers the start), then is "given" away.
const Bfork = structuredClone(Bw2.state);
tick(Bfork, 1/30, { unit: LEG_MEDMEX, priority: "low", progress: 0, done: false }, WIND);
removeBuilder(Bfork, LEG_CON);
Bfork.extraEPerSec -= 7;   // lose w2's passive energy
const Bf  = idle(Bfork, T_HORIZON - Bfork.t);

// ── Variant D: solar juggle — commander → w1 → SOLAR → w2; worker → medmex ────
const D0  = freshState();
const Dw1 = buildWith(D0,        LEG_CON,    "commander", "high");
const Dsol = buildWith(Dw1.state, SOLAR,      "commander", "high");  // ← the juggle
const Dw2  = buildWith(Dsol.state, LEG_CON,  "commander", "high");
const Dmx  = buildWith(Dw2.state, LEG_MEDMEX, LEG_CON,   "low");
const Df   = idle(Dmx.state, T_HORIZON - Dmx.state.t);

// ── Variant E: solar juggle + give w2 to air ──────────────────────────────────
const E0   = freshState();
const Ew1  = buildWith(E0,         LEG_CON,   "commander", "high");
const Esol = buildWith(Ew1.state,  SOLAR,     "commander", "high");
const Ew2  = buildWith(Esol.state, LEG_CON,  "commander", "high");
const Efork = structuredClone(Ew2.state);
tick(Efork, 1/30, { unit: LEG_MEDMEX, priority: "low", progress: 0, done: false }, WIND);
removeBuilder(Efork, LEG_CON);
Efork.extraEPerSec -= 7;
const Ef   = idle(Efork, T_HORIZON - Efork.t);

// ── Variant F: wind juggle — commander → w1 → WIND → w2; worker → medmex ─────
const F0  = freshState();
const Fw1 = buildWith(F0,        LEG_CON,   "commander", "high");
const Fwnd = buildWith(Fw1.state, WIND_T,   "commander", "high");  // ← wind juggle
const Fw2  = buildWith(Fwnd.state, LEG_CON, "commander", "high");
const Fmx  = buildWith(Fw2.state, LEG_MEDMEX, LEG_CON,  "low");
const Ff   = idle(Fmx.state, T_HORIZON - Fmx.state.t);

// ── Variant G: wind juggle + give w2 to air ───────────────────────────────────
const G0   = freshState();
const Gw1  = buildWith(G0,         LEG_CON,  "commander", "high");
const Gwnd = buildWith(Gw1.state,  WIND_T,   "commander", "high");
const Gw2  = buildWith(Gwnd.state, LEG_CON,  "commander", "high");
const Gfork = structuredClone(Gw2.state);
tick(Gfork, 1/30, { unit: LEG_MEDMEX, priority: "low", progress: 0, done: false }, WIND);
removeBuilder(Gfork, LEG_CON);
Gfork.extraEPerSec -= 7;
const Gf   = idle(Gfork, T_HORIZON - Gfork.t);

// ── final snapshots ────────────────────────────────────────────────────────────
const snapA = snap(Af);
const snapB = snap(Bf);
const snapD = snap(Df);
const snapE = snap(Ef);
const snapF = snap(Ff);
const snapG = snap(Gf);

// ── report ─────────────────────────────────────────────────────────────────────
const HR = "─".repeat(76);

console.log("\nLegion 5-walk pos-6 — solar vs wind juggle + give-to-air analysis");
console.log(HR);

// Build parameters
console.log("Parameters:");
console.log(`  snapshot         T=${SNAP.t}s  m=${SNAP.metal}  e=${SNAP.energy}  income +7.87 m/s +58 e/s`);
console.log(`  worker (leg_con) m=${UNITS_EXT[LEG_CON].m}    e=${UNITS_EXT[LEG_CON].e}    bp=${UNITS_EXT[LEG_CON].bp}  ideal ${T_WORKER_IDEAL.toFixed(1)}s by cmd`);
console.log(`  solar            m=${UNITS_EXT[SOLAR].m}   e=${UNITS_EXT[SOLAR].e}      bp=${UNITS_EXT[SOLAR].bp}  ideal ${T_SOLAR_IDEAL.toFixed(1)}s by cmd   +20 e/s fixed`);
console.log(`  wind             m=${UNITS_EXT[WIND_T].m}    e=${UNITS_EXT[WIND_T].e}    bp=${UNITS_EXT[WIND_T].bp}  ideal ${T_WIND_IDEAL.toFixed(1)}s by cmd   +${WIND} e/s (ATG avg)`);
console.log(`  medmex           m=${UNITS_EXT[LEG_MEDMEX].m}   e=${UNITS_EXT[LEG_MEDMEX].e}   bp=${UNITS_EXT[LEG_MEDMEX].bp}  ideal ${T_MEDMEX_IDEAL.toFixed(1)}s by worker`);
console.log(`  WIND=${WIND} e/s, horizon T=${T_HORIZON}s`);

// Build timelines — all in-game time
const GT = dt => fmtT(SNAP.t + dt);  // wall-sec from SNAP → game time string
const Aw1_end  = Aw1.wallSec;
const Aw2_end  = Aw1_end  + Aw2.wallSec;
const Amx_end  = Aw2_end  + Amx.wallSec;
const Dw1_end  = Dw1.wallSec;
const Dsol_end = Dw1_end  + Dsol.wallSec;
const Dw2_end  = Dsol_end + Dw2.wallSec;
const Dmx_end  = Dw2_end  + Dmx.wallSec;
const Fw1_end  = Fw1.wallSec;
const Fwnd_end = Fw1_end  + Fwnd.wallSec;
const Fw2_end  = Fwnd_end + Fw2.wallSec;
const Fmx_end  = Fw2_end  + Fmx.wallSec;
console.log(`\nBuild timelines (in-game, actual walls due to energy throttle):`);
console.log(`  Variant │ w1 done  juggle done  w2 done  medmex done`);
console.log(`  ────────┼──────────────────────────────────────────────`);
console.log(`  A B     │ ${GT(Aw1_end)}    —          ${GT(Aw2_end)}    ${GT(Amx_end)}  (no juggle)`);
console.log(`  D E     │ ${GT(Dw1_end)}    ${GT(Dsol_end)} (solar)  ${GT(Dw2_end)}    ${GT(Dmx_end)}`);
console.log(`  F G     │ ${GT(Fw1_end)}    ${GT(Fwnd_end)} (wind)   ${GT(Fw2_end)}    ${GT(Fmx_end)}`);
console.log(`  (ideal) │ ${GT(T_WORKER_IDEAL)}    solar:${GT(T_WORKER_IDEAL+T_SOLAR_IDEAL)} wind:${GT(T_WORKER_IDEAL+T_WIND_IDEAL)}`);

// Energy available for medmex (at steady-state income, ignoring energy bar level)
const mexUpkeep   = SNAP.mexes * 3;  // 9 e/s
const medmexDrain = UNITS_EXT[LEG_MEDMEX].e / (UNITS_EXT[LEG_MEDMEX].bp / WORKER_BP); // 80 e/s
const eInNone  = BASE_INCOME.e + 0    + SNAP.extraEPerSec + 7 + 7; // 81 e/s
const eInSolar = BASE_INCOME.e + 1*20 + SNAP.extraEPerSec + 7 + 7; // 101 e/s
const eInWind  = BASE_INCOME.e + 0    + SNAP.extraEPerSec + 7 + 7 + WIND; // 95 e/s (winds×14)
const spd = (eIn) => Math.min(100, ((eIn - mexUpkeep) / medmexDrain * 100)).toFixed(0);
console.log(`\nIncome at medmex start (steady-state, mex upkeep = ${mexUpkeep} e/s, medmex drain = ${medmexDrain} e/s):`);
console.log(`  no juggle : ${eInNone} e/s − ${mexUpkeep} e/s upkeep = ${eInNone-mexUpkeep} e/s → medmex speed ${spd(eInNone)}%  (throttled)`);
console.log(`  solar     : ${eInSolar} e/s − ${mexUpkeep} e/s upkeep = ${eInSolar-mexUpkeep} e/s → medmex speed ${spd(eInSolar)}% (full)`);
console.log(`  wind      : ${eInWind} e/s − ${mexUpkeep} e/s upkeep = ${eInWind-mexUpkeep} e/s → medmex speed ${spd(eInWind)}% (full)`);

// Main results table
console.log(`\nEconomy at T=${T_HORIZON/60}:00 (${T_HORIZON}s horizon):`);
console.log(`  Var │ metal  energy    gen(m)  stalls(mx-s)  metalLost  e-gen  note`);
console.log(`  ────┼─────────────────────────────────────────────────────────────────`);
function fmtRow(label, s, note) {
  const eStr = s.solars > 0 ? `sol` : s.winds > 0 ? `wnd` : `   `;
  return `  ${label.padEnd(4)}│ ${String(s.metal).padStart(4)}m  ${String(s.energy).padStart(4)}e  ` +
         `${String(s.gen).padStart(9)}  ${String(s.stalls).padStart(10)}s  ` +
         `${String(s.metalLost).padStart(7)}m  ${eStr}  ${note}`;
}
console.log(fmtRow("A ", snapA, "no juggle, keep w2"));
console.log(fmtRow("B ", snapB, "no juggle, give w2"));
console.log(fmtRow("D ", snapD, "solar juggle, keep w2"));
console.log(fmtRow("E ", snapE, "solar juggle, give w2"));
console.log(fmtRow("F ", snapF, "wind juggle,  keep w2"));
console.log(fmtRow("G ", snapG, "wind juggle,  give w2"));

// Phase-by-phase stall breakdown (3 columns)
const stallsAw1  = parseFloat(Aw1.state.mexStallSec.toFixed(1));
const stallsAw2  = parseFloat((Aw2.state.mexStallSec - Aw1.state.mexStallSec).toFixed(1));
const stallsAmx  = parseFloat((Amx.state.mexStallSec - Aw2.state.mexStallSec).toFixed(1));
const stallsDw1  = parseFloat(Dw1.state.mexStallSec.toFixed(1));
const stallsDsol = parseFloat((Dsol.state.mexStallSec - Dw1.state.mexStallSec).toFixed(1));
const stallsDw2  = parseFloat((Dw2.state.mexStallSec - Dsol.state.mexStallSec).toFixed(1));
const stallsDmx  = parseFloat((Dmx.state.mexStallSec - Dw2.state.mexStallSec).toFixed(1));
const stallsFw1  = parseFloat(Fw1.state.mexStallSec.toFixed(1));
const stallsFwnd = parseFloat((Fwnd.state.mexStallSec - Fw1.state.mexStallSec).toFixed(1));
const stallsFw2  = parseFloat((Fw2.state.mexStallSec - Fwnd.state.mexStallSec).toFixed(1));
const stallsFmx  = parseFloat((Fmx.state.mexStallSec - Fw2.state.mexStallSec).toFixed(1));

const p = (v) => String(v).padStart(7);
console.log(`\nStall breakdown (mex-stall-seconds per phase):`);
console.log(`  Phase              │  A (no juggle)  │   D (solar)    │   F (wind)`);
console.log(`  ───────────────────┼─────────────────┼────────────────┼────────────`);
console.log(`  cmd → worker 1     │ ${p(stallsAw1)}s         │ ${p(stallsDw1)}s        │ ${p(stallsFw1)}s`);
console.log(`  cmd → juggle unit  │ ${p("—")}          │ ${p(stallsDsol)}s  (solar) │ ${p(stallsFwnd)}s  (wind)`);
console.log(`  cmd → worker 2     │ ${p(stallsAw2)}s         │ ${p(stallsDw2)}s        │ ${p(stallsFw2)}s`);
console.log(`  worker → medmex    │ ${p(stallsAmx)}s         │ ${p(stallsDmx)}s        │ ${p(stallsFmx)}s`);
console.log(`  ───────────────────┼─────────────────┼────────────────┼────────────`);
console.log(`  TOTAL              │ ${p(snapA.stalls)}s         │ ${p(snapD.stalls)}s        │ ${p(snapF.stalls)}s`);
console.log(`  metalLost          │ ${p(snapA.metalLost)}m         │ ${p(snapD.metalLost)}m        │ ${p(snapF.metalLost)}m`);

// Juggle comparison table
const dAD = (snapD.gen - snapA.gen);
const dAF = (snapF.gen - snapA.gen);
const solarCost = UNITS_EXT[SOLAR].m;
const windCost  = UNITS_EXT[WIND_T].m;
const solarROI = (dAD - solarCost).toFixed(1);
const windROI  = (dAF - windCost).toFixed(1);
console.log(`\nJuggle comparison (keep w2, vs A baseline):`);
console.log(`  Juggle │ cost  gen gain  net (gain−cost)  e income  w2 stalls  medmex speed`);
console.log(`  ───────┼────────────────────────────────────────────────────────────────────`);
console.log(`  solar  │ ${solarCost}m  +${dAD.toFixed(1)}m  net ${solarROI >= 0 ? "+" : ""}${solarROI}m       +20 e/s   ${snapD.stalls}s      ${spd(eInSolar)}%`);
console.log(`  wind   │ ${windCost}m   +${dAF.toFixed(1)}m  net ${windROI >= 0 ? "+" : ""}${windROI}m       +${WIND} e/s   ${snapF.stalls}s      ${spd(eInWind)}%`);

// Give-to-air analysis
const dAB = snapA.gen - snapB.gen;
const dDE = snapD.gen - snapE.gen;
const dFG = snapF.gen - snapG.gen;
console.log(`\nGive-to-air threshold (Δgen = what air must return to break even):`);
console.log(`  No juggle (A→B): must return >${dAB.toFixed(0)}m-equiv`);
console.log(`  Solar juggle (D→E): must return >${dDE.toFixed(0)}m-equiv`);
console.log(`  Wind juggle  (F→G): must return >${dFG.toFixed(0)}m-equiv`);

console.log(`\n${HR}`);
console.log("Findings:");
console.log(`  1. Why stalls happen: commander (HIGH priority) drinks energy at step 2 before mex`);
console.log(`     upkeep at step 3 — any high-priority build with income < drain empties the bar.`);
console.log(`     The medmex (LOW priority) does NOT cause stalls; income covers upkeep before it runs.`);
console.log(`  2. WHY solar >> wind for the juggle:`);
console.log(`     Solar costs e=0 → commander builds it at full speed while energy RECHARGES freely.`);
console.log(`     ${Dsol.wallSec.toFixed(1)}s × (74 e/s income − 9 e/s upkeep) ≈ ${Math.round(Dsol.wallSec * 65)}e buffered → w2 nearly stall-free.`);
console.log(`     Wind costs e=${UNITS_EXT[WIND_T].e} → drains part of the recharge window.`);
console.log(`     ${Fwnd.wallSec.toFixed(1)}s wind build only recovers ~${Math.round(Fwnd.wallSec * (74 - UNITS_EXT[WIND_T].e / (UNITS_EXT[WIND_T].bp / COMMANDER_BP) - 9))}e buffer → w2 stalls more (${snapF.stalls}s vs ${snapD.stalls}s).`);
console.log(`  3. Both juggle options enable full-speed medmex (solar +20, wind +${WIND} — both push`);
console.log(`     income past the 89 e/s threshold). The difference is the w2 stall window.`);
console.log(`  4. Net value over horizon: solar +${dAD.toFixed(0)}m at T=8:00, costs ${solarCost}m → ROI ${solarROI >= 0 ? "+" : ""}${solarROI}m.`);
console.log(`     Wind +${dAF.toFixed(0)}m at T=8:00, costs ${windCost}m → ROI ${windROI >= 0 ? "+" : ""}${windROI}m. Wind is better ROI by m-spent.`);
console.log(`  5. Give-to-air threshold barely changes with the juggle (±15m). The juggle decision`);
console.log(`     is independent of whether you give w2.`);
console.log(`\n  NOTE: Legion-specific rates: mex ≈1.47 m/s (not ARM 1.8). Absolute values ~15% high.`);
console.log(`  Stall counts and Δgen values are internally consistent (same rate assumptions).`);
console.log(HR + "\n");

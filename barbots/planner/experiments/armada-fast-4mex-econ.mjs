// armada-fast-4mex-econ.mjs — ARM fast-econ build, step-by-step through the eco_engine.
//
// Requested build order:
//   4 mex, 2 solar, factory -> produce 3 con, 2 laz, 4th con (given away) ->
//   con turret, wind, solar, wind (opportunistic energy/BP rotation) ->
//   converter (early) -> 1-2 estorage (bank energy before going T2).
//
// Modeling notes (stated up front, not hidden):
//   - Factory production (con/con/con/laz/laz/con) runs on the FACTORY'S OWN build
//     power (100 BP for botlab) — matches expand-goals.mjs's `produce` convention
//     (factoryBP, not the mobile pool). Commander is otherwise idle during this
//     window in this model; a real player would overlap it, so the REAL wall-clock
//     total is somewhat faster than shown here. Sequential-but-transparent, same
//     caveat project.mjs documents for its own serialized-build model.
//   - Structure-building (turret/wind/solar/wind/converter/estor/estor) then runs
//     on the pooled MOBILE build power: commander (300) + the 3 KEPT con bots
//     (+80 each; the 4th con is given away and contributes 0).
//   - laz has no `gives` (matches units.json: "_note: no income effect on
//     completion" — it's a reclaim/rez utility bot, not an income/BP source).
//
// Run:  node planner/experiments/armada-fast-4mex-econ.mjs

import { createState, simulateBuild } from "../../../gex_research/process/lib/sim/eco_engine.mjs";

const WIND = 11.9;   // ATG average, per the confirmed cross-check earlier this session
const r0 = x => Math.round(x), r1 = x => Math.round(x * 10) / 10, pad = (s, n) => String(s).padStart(n);
const fmt = s => { const t = r0(s); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };

// ARM costs — mex/solar/wind/turret/worker/eStorage/converter from eco_engine.mjs's
// own canonical UNITS (ARM defaults); botlab/laz from planner/data/units.json.
const U = {
  mex:      { m: 50,  e: 500,  bp: 1800, gives: { mex: 1 } },
  solar:    { m: 155, e: 0,    bp: 2600, gives: { ePerSec: 20 } },
  wind:     { m: 40,  e: 175,  bp: 1600, gives: { windGen: 1 } },
  turret:   { m: 230, e: 3200, bp: 5300, gives: { builderBp: 200 } },
  con:      { m: 110, e: 1600, bp: 3450, gives: { builderBp: 80, ePerSec: 7 } },
  laz:      { m: 110, e: 1100, bp: 4500, gives: {} },                       // reclaim/rez util — no income/BP effect
  estor:    { m: 230, e: 1700, bp: 4100, gives: { storE: 6000 } },          // ARM eStorage (NOT Legion's 175/1800/4260)
  converter:{ m: 1,   e: 1150, bp: 2600, gives: { converter: 1 } },
  botlab:   { m: 620, e: 1200, bp: 6500, gives: {} },                       // factory itself (built by commander)
};
const FACTORY_BP = 100;   // botlab's own build power (produces its queue)

let bp = 300;              // mobile pool: starts as commander alone
let nConKept = 0;

let s = createState({
  metal: 1000, energy: 1000, storM: 1000, storE: 1000,   // standard BAR start
  mexes: 0, solars: 0, winds: 0, converters: 0, extraEPerSec: 0,
  base: { m: 2, e: 25 },                                  // commander passive (eco_engine BASE_INCOME)
  builders: [{ name: "pool", bp, priority: "high" }],
  units: U,
});

console.log(`\nArmada fast-econ build — every number, step by step (eco_engine, wind=${WIND})`);
console.log("─".repeat(96));
console.log(`${"time".padEnd(7)} ${"step".padEnd(24)} ${"BP".padStart(4)} ${"dur".padStart(6)} │ ` +
            `${"metal in→out".padStart(16)} ${"m/s".padStart(5)} │ ${"energy in→out".padStart(16)} ${"e/s".padStart(5)} │ stall`);
console.log("─".repeat(96));

function step(label, key, poolBP, after) {
  const b0 = { m: s.metal, e: s.energy, t: s.t };
  s.builders = [{ name: "pool", bp: poolBP, priority: "high" }];
  const r = simulateBuild(s, key, { priority: "high", wind: WIND });
  s = r.endState;
  if (after) after();
  const mInc = () => s.base.m + s.mexes * s.mex.mPerSec;   // gives.mex already drives s.mexes automatically
  const eInc = () => s.base.e + s.solars * 20 + s.extraEPerSec;
  console.log(
    `${pad(fmt(s.t), 7)} ${label.padEnd(24)} ${pad(poolBP, 4)} ${pad(r1(s.t - b0.t) + "s", 6)} │ ` +
    `${pad(r0(b0.m), 6)}→${pad(r0(s.metal), 6)}     ${pad(r1(mInc()), 5)} │ ` +
    `${pad(r0(b0.e), 6)}→${pad(r0(s.energy), 6)}     ${pad(r0(eInc()), 5)} │ ` +
    `${r.throttledSec > 1 ? "STALL " + r1(r.throttledSec) + "s" : ""}`);
  return r;
}

// ── Opening: 4 mex, 2 solar, factory (commander alone, 300 BP) ──────────────────
// mex/solar/wind/converter/estor effects (s.mexes/s.solars/s.winds/s.converters/s.storE)
// all apply automatically via applyCompletion's `gives` — no manual bookkeeping needed.
for (let i = 1; i <= 4; i++) step(`mex ${i}`, "mex", bp);
for (let i = 1; i <= 2; i++) step(`solar ${i}`, "solar", bp);
step("factory (botlab)", "botlab", bp);

// ── Factory production: 3 con, 2 laz, 4th con (given away) — factory's own BP ───
// `bp`/`nConKept` are OUR OWN pool tracking (not modeled by state.builders, since
// each step() call overwrites state.builders with just the pool entry) — con's own
// gives.ePerSec still applies automatically, so it's not added again here.
for (let i = 1; i <= 3; i++) step(`con ${i}/4 (factory)`, "con", FACTORY_BP, () => { nConKept++; bp += 80; });
for (let i = 1; i <= 2; i++) step(`laz ${i}/2 (factory)`, "laz", FACTORY_BP);
step("con 4/4 → GIVEN AWAY", "con", FACTORY_BP);   // no bp/income credit — leaves the economy

// ── Structure rotation: turret, wind, solar, wind (mobile pool: com + 3 kept con) ──
step("con turret (+200 BP)", "turret", bp, () => { bp += 200; });
step("wind 1", "wind", bp);
step("solar 3", "solar", bp);
step("wind 2", "wind", bp);

// ── Converter (early, once energy has real surplus) ─────────────────────────────
step("converter", "converter", bp);

// ── Bank the energy before T2: 2 estorage ────────────────────────────────────────
step("estor 1", "estor", bp);
step("estor 2", "estor", bp);

console.log("─".repeat(96));
console.log(`>>> BUILD COMPLETE at ${fmt(s.t)} (${r0(s.t)}s).  BP pool ${bp} (com 300 + ${nConKept} con ×80).  ` +
            `${s.winds} wind, ${s.solars} solar, ${s.converters} converter, storE ${s.storE}.`);
console.log(`    metal ${r0(s.metal)}/${s.storM}   energy ${r0(s.energy)}/${s.storE}   ` +
            `income ${r1(s.base.m + s.mexes * s.mex.mPerSec)} m/s, ${r0(s.base.e + s.solars * 20 + s.extraEPerSec)} e/s`);
console.log("─".repeat(96) + "\n");

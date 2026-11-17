// legion_sim.mjs — Legion build-order simulator/comparator.
// Projects a build order forward from a start state using Legion unit stats with
// BUILD POWER, WALK TIMES (distance/speed), and RESOURCE-GATED STALLS baked in.
// Stats are MODELLED from legion_unitdefs.json + measured constants; the #2 refinement
// step will replace the modelled build/walk times with exact values from live games.
//
//   import { simulate, compare } from "./legion_sim.mjs"   (or run this file for the demo)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const DB = JSON.parse(fs.readFileSync(path.join(here, "legion_unitdefs.json"), "utf8"));
const D = (n) => DB.defs.find((d) => d.defName === n);

// ---- measured / modelled constants (calibrated from 2026-06-20_18-53-11-610) ----
export const CONST = {
  comSpeed: 37.5,          // legcom elmo/s (from def)
  comBP: 300,              // legcom build power
  spotMps: 1.47,           // legmex m/s on a starting ATG spot (measured)
  startMetal: 1000, startEnergy: 1000,
  comBaseM: 2, comBaseE: 30,   // commander's own metalMake / +energy
  mexE: 7, medmexMps_mult: 2.5, medmexE: -30, solarE: 20,
  dt: 0.05,
};

// resolve a step into {def, mDelta, eDelta} where deltas are income added on finish
function stepUnit(s) {
  if (s.do === "mex")    return { def: D("legmex"),    m: CONST.spotMps,                 e: CONST.mexE };
  if (s.do === "medmex") return { def: D("legmext15"), m: CONST.spotMps*CONST.medmexMps_mult, e: CONST.medmexE };
  if (s.do === "solar")  return { def: D("legsolar"),  m: 0,                              e: CONST.solarE };
  if (s.do === "build")  return { def: D(s.name),      m: 0,                              e: 0 };
  return null;
}

export function simulate(order, opts = {}) {
  const o = { ...CONST, ...opts };
  let t = 0, m = o.startMetal, e = o.startEnergy;
  let comAlive = true;
  // income continues from the seed's already-built economy (default = bare commander)
  let incM = opts.startIncM ?? o.comBaseM, incE = opts.startIncE ?? o.comBaseE;
  const producers = [];                            // for record
  const log = [];
  // extra build power available from time tSec (e.g., a worker+turret assist): {at, bp}
  const assists = opts.assists || [];
  const bpAt = (tt) => (comAlive ? o.comBP : 0) + assists.filter(a => tt >= a.at).reduce((s,a)=>s+a.bp,0);

  let idx = 0, progress = 0, stalledSec = 0, walkRem = null, waitRem = null;
  const maxT = opts.until || 300;
  const dt = o.dt;

  while (t < maxT && idx < order.length) {
    const s = order[idx];

    if (s.do === "comboom") {
      const gain = (opts.comReclaimMetal ?? 1350);   // reclaim own commander -> metal
      m += gain; incM -= o.comBaseM; incE -= o.comBaseE; comAlive = false;
      log.push({ t: r1(t), ev: `commander exploded (+${gain} m), com BP & income removed` });
      idx++; progress = 0; walkRem = null; continue;
    }

    // initialise this step's walk/wait once
    if (walkRem === null) walkRem = (s.dist || 0) / o.comSpeed;

    if (walkRem > 0) {                                // walking to the build site
      const w = Math.min(dt, walkRem); walkRem -= w;
      m += incM * w; e += incE * w; t += w; continue;
    }
    if (s.do === "wait") {                            // timed pause
      if (waitRem === null) waitRem = s.secs;
      const w = Math.min(dt, waitRem); waitRem -= w;
      m += incM * w; e += incE * w; t += w;
      if (waitRem <= 0) { idx++; walkRem = null; waitRem = null; }
      continue;
    }

    const u = stepUnit(s); if (!u || !u.def) { idx++; walkRem = null; continue; }
    let frac = (bpAt(t) * dt) / u.def.buildTime;      // desired build fraction this tick
    const mNeed = u.def.metalCost * frac, eNeed = u.def.energyCost * frac;
    let scale = 1;
    if (mNeed > 0) scale = Math.min(scale, (m + incM * dt) / mNeed);
    if (eNeed > 0) scale = Math.min(scale, (e + incE * dt) / eNeed);
    scale = Math.max(0, Math.min(1, scale));
    if (scale < 0.999) stalledSec += dt;
    frac *= scale;
    m += incM * dt - u.def.metalCost * frac;
    e += incE * dt - u.def.energyCost * frac;
    if (m < 0) m = 0; if (e < 0) e = 0;
    progress += frac; t += dt;
    if (progress >= 1) {
      incM += u.m; incE += u.e; producers.push(s.do);
      log.push({ t: r1(t), ev: `${s.do}${s.name?(" "+s.name):""} done @${s.dist||0}el  (M/s=${r1(incM)}, E/s=${r1(incE)})` });
      idx++; progress = 0; walkRem = null;
    }
  }
  // value of what got built (metal+energy/70)
  let value = 0; for (const s of order.slice(0, idx)) { const u = stepUnit(s); if (u?.def) value += u.def.metalCost + (u.def.energyCost||0)/70; }
  return { t: r1(t), metal: Math.round(m), energy: Math.round(e), incM: r1(incM), incE: r1(incE),
           built: producers, builtCount: idx, value: Math.round(value), stalledSec: r1(stalledSec), log };
}

export function compare(builds, checkpoint = 300) {
  console.log(`\n# Build comparison @ ${checkpoint}s (${Math.floor(checkpoint/60)}:${String(checkpoint%60).padStart(2,"0")})  — Legion, walk+build+stalls baked in\n`);
  const rows = builds.map(b => {
    const r = simulate(b.order, { ...b.opts, until: checkpoint });
    const finished = r.log.filter(l => /done/.test(l.ev)).length;
    return { build: b.name, "M/s": r.incM, "E/s": r.incE, metal: r.metal, energy: r.energy,
             "built#": finished, "value(m+e/70)": r.value, "stall_s": r.stalledSec };
  });
  console.table(rows);
  return rows;
}

const r1 = (x) => Math.round(x * 10) / 10;
const clock = (s) => `${Math.floor(s/60)}:${String(Math.round(s%60)).padStart(2,"0")}`;

// "You were here at x:yz with R. System suggests pattern P. Compare end-state at next checkpoint vs original."
export function project(seed, suggested, original, horizonSec) {
  const opts = { startMetal: seed.metal, startEnergy: seed.energy, startIncM: seed.incM, startIncE: seed.incE, comReclaimMetal: seed.comReclaimMetal };
  console.log(`\n# In this replay: you were at ${clock(seed.t)} with ${seed.metal} m / ${seed.energy} e`
    + (seed.note ? ` (${seed.note})` : ""));
  console.log(`# System suggests: ${suggested.name}`);
  console.log(`# Compare end-state at ${clock(seed.t + horizonSec)} (next ${horizonSec}s):\n`);
  const run = (b) => { const r = simulate(b.order, { ...opts, until: horizonSec });
    return { plan: b.name, "M/s": r.incM, "E/s": r.incE, metal: r.metal, energy: r.energy,
             "built#": r.log.filter(l=>/done/.test(l.ev)).length, "value": r.value, "stall_s": r.stalledSec }; };
  console.table([ { ...run(original), plan: `original: ${original.name}` }, { ...run(suggested), plan: `SUGGESTED: ${suggested.name}` } ]);
}

// ---------- demo ----------
if ((process.argv[1] || "").replace(/\\/g, "/").endsWith("legion_sim.mjs")) {
  // distances (elmos) modelled from the skirmish: tight starting cluster, then expansion
  const A = { name: "3 mex > factory > 2 solar", order: [
    {do:"mex",dist:150},{do:"mex",dist:250},{do:"mex",dist:250},
    {do:"build",name:"leglab",dist:150},{do:"solar",dist:100},{do:"solar",dist:100},
    {do:"mex",dist:500},{do:"mex",dist:650},{do:"solar",dist:120},{do:"mex",dist:600},
  ]};
  const B = { name: "3 mex > 4th mex > factory", order: [
    {do:"mex",dist:150},{do:"mex",dist:250},{do:"mex",dist:250},{do:"mex",dist:500},
    {do:"build",name:"leglab",dist:520},{do:"solar",dist:120},{do:"solar",dist:100},
    {do:"mex",dist:650},{do:"solar",dist:120},{do:"mex",dist:600},
  ]};
  const C = { name: "3 mex > factory > MedMex on 1 spot", order: [
    {do:"mex",dist:150},{do:"mex",dist:250},{do:"mex",dist:250},
    {do:"build",name:"leglab",dist:150},{do:"solar",dist:100},{do:"solar",dist:100},
    {do:"medmex",dist:500},{do:"solar",dist:120},{do:"solar",dist:120},{do:"mex",dist:650},
  ]};
  compare([A,B,C], 240);
  console.log("\n## Build A timeline (3 mex > factory > 2 solar)");
  for (const l of simulate(A.order,{until:240}).log) console.log(`  ${String(l.t).padStart(5)}s  ${l.ev}`);

  // seeded "system suggests vs original" — seed = replay state at 1:00 (measured)
  project(
    { t: 60, metal: 628, energy: 549, incM: 2 + 4*1.47, incE: 30 + 4*7, note: "4 mex up (M/s 7.9, E/s 58)" },
    { name: "expand: 3 more mex then 2 solar", order: [
      {do:"mex",dist:500},{do:"mex",dist:650},{do:"mex",dist:600},{do:"solar",dist:120},{do:"solar",dist:120}] },
    { name: "original: factory now then sit", order: [
      {do:"build",name:"leglab",dist:500},{do:"solar",dist:120},{do:"solar",dist:120}] },
    120);
}

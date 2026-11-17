// legion_factory_energy.mjs — "5-walk mex > factory" opening: how fast do the factory's
// 3 workers + 2 lazarus pop out under different ENERGY choices (0-5 solar vs repeat wind
// at various wind speeds)?  Multi-builder sim: commander builds eco WHILE the bot lab
// produces units, sharing one metal/energy pool (proportional stall when short).
//
//   node legion_factory_energy.mjs
import fs from "node:fs"; import path from "node:path"; import { fileURLToPath } from "node:url";
const here = path.dirname(fileURLToPath(import.meta.url));
const DB = JSON.parse(fs.readFileSync(path.join(here, "legion_unitdefs.json"), "utf8"));
const D = (n) => DB.defs.find((d) => d.defName === n);

const COM_BP = 300, COM_SPEED = 37.5, FAC_BP = 150;
const START_M = 1000, START_E = 1000, COM_M = 2, COM_E = 30, MEX_MPS = 1.47, MEX_E = 7, SOLAR_E = 20, dt = 0.05;
const leglab = D("leglab"), legck = D("legck"), laz = D("legrezbot"), legmex = D("legmex"), solar = D("legsolar"), win = D("legwin");
// 5-walk opening: commander walks out building 5 mexes (measured-ish elmo distances), then returns to build the lab
const MEX_DISTS = [150, 270, 245, 475, 700], FAC_DIST = 350, ENE_DIST = 90;

function income(doType, windAvg) {
  if (doType === "mex") return { m: MEX_MPS, e: MEX_E };
  if (doType === "solar") return { m: 0, e: SOLAR_E };
  if (doType === "win") return { m: 0, e: windAvg };
  return { m: 0, e: 0 };
}
function stepDef(s) {
  if (s.do === "mex") return legmex; if (s.do === "solar") return solar; if (s.do === "win") return win;
  return D(s.name);
}

function run({ mode, count = 0, windAvg = 0, maxT = 240, sustain = 0 }) {
  let t = 0, m = START_M, e = START_E, incM = COM_M, incE = COM_E;
  let mCap = START_M, eCap = START_E, eWasted = 0, firstStall = null, unitsOut = 0;
  const comQ = MEX_DISTS.map((d) => ({ do: "mex", dist: d }));
  comQ.push({ do: "build", name: "leglab", dist: FAC_DIST });
  if (mode === "solar") for (let i = 0; i < count; i++) comQ.push({ do: "solar", dist: i ? 30 : ENE_DIST });
  if (mode === "wind")  for (let i = 0; i < 30; i++) comQ.push({ do: "win", dist: i ? 25 : ENE_DIST });
  const com = { name: "com", bp: COM_BP, speed: COM_SPEED, q: comQ, qi: 0, walk: null, prog: 0 };
  const fac = { name: "fac", bp: FAC_BP, speed: 0, q: [], qi: 0, walk: null, prog: 0, active: false };
  const builders = [com, fac];
  const done = {};   // label -> finish time
  let minE = START_E, facBuiltAt = null;

  while (t < maxT) {
    if (com.qi >= com.q.length && (!fac.active || fac.qi >= fac.q.length)) break;
    // init walks
    for (const b of builders) {
      if (b.qi < b.q.length && b.walk === null) b.walk = (b.q[b.qi].dist || 0) / (b.speed || 1);
    }
    // add income for this tick (clamp to storage; overflow wasted)
    m += incM * dt; e += incE * dt;
    if (m > mCap) m = mCap;
    if (e > eCap) { eWasted += e - eCap; e = eCap; }
    // gather builders that BUILD this tick (not walking, have a step)
    const active = [];
    for (const b of builders) {
      if (b.qi >= b.q.length) continue;
      if (b.walk > 0) { b.walk -= dt; continue; }       // walking, no resource
      const s = b.q[b.qi], d = stepDef(s);
      const frac = (b.bp * dt) / d.buildTime;
      active.push({ b, s, d, frac, mc: d.metalCost * frac, ec: d.energyCost * frac });
    }
    const totM = active.reduce((a, x) => a + x.mc, 0), totE = active.reduce((a, x) => a + x.ec, 0);
    let scale = 1;
    if (totM > 0) scale = Math.min(scale, m / totM);
    if (totE > 0) scale = Math.min(scale, e / totE);
    scale = Math.max(0, Math.min(1, scale));
    m -= totM * scale; e -= totE * scale; if (m < 0) m = 0; if (e < 0) e = 0;
    if (scale < 0.999 && active.length && firstStall === null && fac.active) firstStall = t;
    t += dt; if (e < minE) minE = e;
    for (const x of active) {
      x.b.prog += x.frac * scale;
      if (x.b.prog >= 1) {
        const inc = income(x.s.do, windAvg); incM += inc.m; incE += inc.e;
        mCap += x.d.metalStorage || 0; eCap += x.d.energyStorage || 0;
        if (x.b === com && x.s.do === "build" && x.s.name === "leglab") { fac.active = true; facBuiltAt = t;
          fac.q = sustain ? Array.from({length:sustain},()=>({do:"build",name:"legck",dist:0}))
            : [{do:"build",name:"legck",dist:0},{do:"build",name:"legck",dist:0},{do:"build",name:"legck",dist:0},
               {do:"build",name:"legrezbot",dist:0},{do:"build",name:"legrezbot",dist:0}]; }
        if (x.b === fac) { unitsOut++; const k = x.s.name === "legck" ? "W" : "L"; const n = Object.keys(done).filter(z=>z[0]===k).length+1; done[`${k}${n}`] = t; }
        x.b.qi++; x.b.prog = 0; x.b.walk = null;
      }
    }
  }
  return { facBuiltAt, done, minE: Math.round(minE), incE: Math.round(incE), eWasted: Math.round(eWasted), firstStall, unitsOut };
}

const r = (x) => x == null ? "  -  " : `${Math.floor(x/60)}:${String(Math.round(x%60)).padStart(2,"0")}`;
const cols = ["W1","W2","W3","L1","L2"];
function rowstr(res){ return cols.map(c=>r(res.done[c]).padStart(6)).join(" "); }

console.log("Opening: 5 mexes (walk) > Legion Bot Lab. Then factory makes 3 workers (W) + 2 lazarus (L).");
console.log("Times = game clock each unit POPS. minE = lowest stored energy (0 => energy-stalled).\n");

console.log("## SOLAR opens (commander builds N solars after the lab)");
console.log(`solars  fac@  ${cols.map(c=>c.padStart(6)).join(" ")}   minE`);
for (let n = 0; n <= 5; n++) { const res = run({ mode: "solar", count: n }); console.log(`  ${n}    ${r(res.facBuiltAt)}  ${rowstr(res)}   ${res.minE}`); }

console.log("\n## REPEAT-WIND opens at various wind speeds (commander spams wind after the lab)");
console.log(`windAvg fac@  ${cols.map(c=>c.padStart(6)).join(" ")}   minE`);
for (const w of [2,5,8,11,14,16]) { const res = run({ mode: "wind", windAvg: w }); console.log(`  ${String(w).padStart(2)}   ${r(res.facBuiltAt)}  ${rowstr(res)}   ${res.minE}`); }

console.log("\n  NOTE: the 5-walk opening banks ~a full energy bar during the walk, so the first 5");
console.log("  units pop at nearly the same time on ANY energy choice — what changes is the");
console.log("  HEADROOM left (minE) and whether you stall. 0 solar finishes on fumes (minE 47).");

console.log("\n## SUSTAINED production — factory runs workers non-stop. Units out by 4:00 + first stall:");
console.log("energy        unitsBy4:00  firstStall  minE");
for (let n = 0; n <= 5; n++) { const res = run({ mode: "solar", count: n, sustain: 16, maxT: 240 });
  console.log(`  ${n} solar       ${String(res.unitsOut).padStart(3)}        ${r(res.firstStall)}     ${res.minE}`); }
for (const w of [2,5,8,11,14,16]) { const res = run({ mode: "wind", windAvg: w, sustain: 16, maxT: 240 });
  console.log(`  wind ${String(w).padStart(2)}      ${String(res.unitsOut).padStart(3)}        ${r(res.firstStall)}     ${res.minE}`); }

console.log("\n## Crossover — repeat-wind vs solar (sustained units-out-by-4:00)");
const solarUnits = []; for (let n=0;n<=5;n++) solarUnits[n] = run({mode:"solar",count:n,sustain:16}).unitsOut;
for (const w of [2,5,8,11,14,16]) {
  const u = run({ mode: "wind", windAvg: w, sustain: 16 }).unitsOut;
  let eq = "< 0-solar"; for (let n=5;n>=0;n--){ if (u >= solarUnits[n]) { eq = `≈ ${n}-solar (${solarUnits[n]} u)`; break; } }
  console.log(`  wind ${String(w).padStart(2)}: ${u} units -> ${eq}`);
}
console.log(`\n  (solar baselines, units-by-4:00:  ${solarUnits.map((u,n)=>`${n}s=${u}`).join("  ")})`);

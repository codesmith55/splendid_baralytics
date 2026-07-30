// legion_planner.mjs — interlocking goal-driven build planner + multi-builder simulator.
//
//   GOALS preset ──▶ nextStep(state, goals) ──▶ {do, dist, why}        (the auto-planner)
//                          ▲                          │
//                          └──────── plan(goals) ─────┘  (sim: calls nextStep when the pool is free,
//                                                          advances builders, shares metal/energy)
//
// Models the corrected Tech build from AFTER "5 mex + factory": a factory making workers (each +75 BP
// to the pool, +5 E) while the COMMANDER+WORKERS+CON-TURRET pool builds the planner's structures.
// The planner enforces "energy before the next med-mex" so energy never floors (the replay's bug).
//
//   node legion_planner.mjs            (run corrected build)
//   node legion_planner.mjs fastt2     (run a different preset)
import fs from "node:fs"; import path from "node:path"; import { fileURLToPath } from "node:url";
const here = path.dirname(fileURLToPath(import.meta.url));
const DB = JSON.parse(fs.readFileSync(path.join(here, "legion_unitdefs.json"), "utf8"));
const D = (n) => DB.defs.find((d) => d.defName === n);

// ---- constants (user-calibrated) ----
// BASE_MEX = a STANDARD (arm/cor) mex on this spot. Legion factors off it:
//   legmex 0.75x (1.369 m/s), T1.5 med-mex 2.0x (3.65), T2 moho 4.0x (7.30).
//   medmex over a legmex spot: ΔM = BASE*(2-0.75)=+2.28 m/s, ΔE = -30 drain minus the legmex's +7 ≈ -37.
const COM_BP = 300, COM_SPEED = 37.5, FAC_BP = 150, dt = 0.05;
const COM_M = 2, COM_E = 30, BASE_MEX = 1.825;
const MULT = { mex: 0.75, medmex: 2.0, moho: 4.0 };
const UNIT = { mex:"legmex", solar:"legsolar", advsol:"legadvsol", win:"legwin", medmex:"legmext15", turret:"legnanotc", moho:"legmoho", estor:"legestor" };
const ESTOR_CAP = D("legestor")?.energyStorage ?? 6000;  // +6000 E-cap; reclaimable for 175m later
const MPS = (d) => (MULT[d] || 0) * BASE_MEX;
const ENET = (d,w) => d==="mex"?7 : d==="solar"?20 : d==="advsol"?100 : d==="win"?w : d==="medmex"?-30 : d==="moho"?-20 : 0;
const CAT = (d) => d==="win"?"wind" : d; // count bucket
const r1 = (x) => Math.round(x*10)/10;

// ============ PRESETS: the overarching goals for a build ============
// 3 LEVERS: M (metal, from mexes) · BP (build power, to USE the metal) · E (energy, to RUN the BP/builds).
// egenTarget = ~300ish egen goal (the "ish" = wind variance); it's the whole energy economy, not just T2.
export const PRESETS = {
  corrected: { label:"Tech B (metal engine: med-mexes, energy-gated)",
    windAvg:11.2, targetMex:7, conTurret:1, solarTarget:2, windWhenWindGE:8, minNetE:15,
    medmexTarget:6, mohoTarget:0, egenTarget:300, estorTarget:1, workerTarget:4, maxT:360 },
  fastt2: { label:"Tech A (fast T2: energy to egen target, then moho)",
    windAvg:11.2, targetMex:7, conTurret:1, solarTarget:2, windWhenWindGE:8, minNetE:15,
    medmexTarget:0, mohoTarget:2, egenTarget:300, estorTarget:1, workerTarget:3, maxT:360 },
};

// ============ AUTO-PLANNER: what should be next on the build order? ============
const mk = (doType, dist, why) => ({ do: doType, name: UNIT[doType], dist, why });
const distMex = (i) => [150,270,245,475,700,650,600,900,800][i] ?? 800;
// energy in the user's order: solar (fastest, 0 build-E, reliable) → wind (cheap bulk, variable) → advsol (scaling)
const energyPick = (s, g) => s.solar < g.solarTarget ? "solar" : (s.windAvg >= g.windWhenWindGE ? "win" : "advsol");

const MEDMEX_SWING = 30 + 7; // med-mex drain (30) + the legmex's +7 you give up ≈ -37 E
export function nextStep(s, g) {
  // LEVER 1 — METAL: claim every available mex spot first (max metal generation)
  if (s.mex < g.targetMex)   return mk("mex", distMex(s.mex), `[M] mex ${s.mex+1}/${g.targetMex}`);
  // ENERGY (reactive floor): if income can't sustain, fix it before anything else (solar→wind→advsol)
  if (s.incE < g.minNetE)    { const p = energyPick(s,g); return mk(p, 90, `[E] reactive floor: E ${Math.round(s.incE)}<${g.minNetE} → ${p}`); }
  // ENERGY BUFFER: estor BEFORE the con turret — so the turret's 3200e drain doesn't kill the bank.
  // +6000 E-cap; bank fills while the turret and other builds happen → medmex starts with a full bank → ≈ full-speed.
  // Reclaimable for 175m metal later when T2 factory goes up.
  if (g.estorTarget && s.estor < g.estorTarget && s.medmex < g.medmexTarget)
    return mk("estor", 90, `[E-buf] estor (+${ESTOR_CAP}E cap, reclaimable 175m; built before turret so bank fills first → medmex near full-speed)`);
  // LEVER 2 — BP: con turret converts banked metal into build speed (workers come from factory in parallel)
  if (s.turret < g.conTurret) return mk("turret", 300, `[BP] con turret (+200 pooled BP)`);
  // METAL upgrade — med-mex: ΔM +2.28, ΔE -37. Interleave: take one if income can still absorb -37, else add energy.
  if (s.medmex < g.medmexTarget) {
    if (s.incE - MEDMEX_SWING < g.minNetE) {           // income can't sustain another -37 → add egen first
      const p = energyPick(s,g); return mk(p, 90, `[E] income for med-mex (E ${Math.round(s.incE)}<${g.minNetE+MEDMEX_SWING}) → ${p}`);
    }
    return mk("medmex", distMex(s.mex + s.medmex), `[M] med-mex ${s.medmex+1}/${g.medmexTarget} (E ${Math.round(s.incE)}→${Math.round(s.incE-MEDMEX_SWING)})`);
  }
  // T2 — moho: the ~egen target is the commitment gate (no point being T2 unpowered)
  if (s.moho < g.mohoTarget) {
    if (s.incE < g.egenTarget) { const p = energyPick(s,g); return mk(p, 90, `[E] T2 needs egen ${Math.round(s.incE)}/~${g.egenTarget} → ${p}`); }
    return mk("moho", distMex(s.mex + s.moho), `[M] T2 moho ${s.moho+1}/${g.mohoTarget}`);
  }
  // trend the energy economy up toward the ~egen target
  if (s.incE < g.egenTarget) { const p = energyPick(s,g); return mk(p, 90, `[E] trend egen ${Math.round(s.incE)}/~${g.egenTarget} → ${p}`); }
  return null; // all goals met
}

// ============ saved start states (retrievable) ============
export function loadState(key) {
  const states = JSON.parse(fs.readFileSync(path.join(here, "legion_states.json"), "utf8"));
  return states[key];
}

// ============ SIMULATOR: run the planner's choices with real timings ============
// st (optional) = a saved start state from legion_states.json; default = bare "after 5 mex + factory".
export function plan(g, st) {
  const c0 = st?.counts || { mex:5, medmex:0, advsol:0, wind:0, solar:0, turret:0, moho:0, workers:0, lazarus:0 };
  let t = st?.t || 0;
  let m = st?.m ?? 600, e = st?.e ?? 1000;
  let incM = st?.incM ?? (COM_M + 5*MPS("mex")), incE = st?.incE ?? (COM_E + 5*ENET("mex"));
  let mCap = st?.mCap ?? (1000 + (c0.mex||0)*50), eCap = st?.eCap ?? 1000, minE = e;
  let poolBP = st?.poolBP ?? COM_BP;
  const s = { ...c0, get incE(){return incE}, get e(){return e}, windAvg:g.windAvg };
  s.solar = s.solar || 0; s.estor = s.estor || 0;
  const fac = { left: Math.max(0, g.workerTarget - (c0.workers||0)), prog: 0, walk: 0 };
  const pool = { step: null, walk: 0, prog: 0 };
  const timeline = [];

  while (t < g.maxT) {
    if (!pool.step) { pool.step = nextStep(s, g); if (pool.step) { pool.walk = (pool.step.dist||0)/COM_SPEED; pool.prog = 0; } }
    if (!pool.step && fac.left <= 0) break;

    m = Math.min(mCap, m + incM*dt); e = Math.min(eCap, e + incE*dt);
    const active = [];
    if (fac.left > 0) { if (fac.walk > 0) fac.walk -= dt; else { const d = D("legck"); active.push({ who:"fac", d, f: FAC_BP*dt/d.buildTime }); } }
    if (pool.step)   { if (pool.walk > 0) pool.walk -= dt; else { const d = D(pool.step.name); active.push({ who:"pool", d, f: poolBP*dt/d.buildTime }); } }

    const totM = active.reduce((a,x)=>a+x.d.metalCost*x.f,0), totE = active.reduce((a,x)=>a+x.d.energyCost*x.f,0);
    let sc = 1; if (totM>0) sc = Math.min(sc, m/totM); if (totE>0) sc = Math.min(sc, e/totE); sc = Math.max(0, Math.min(1, sc));
    m -= totM*sc; e -= totE*sc; if (m<0) m=0; if (e<0) e=0; if (e<minE) minE=e; t += dt;

    for (const x of active) {
      if (x.who === "fac") { fac.prog += x.f*sc; if (fac.prog>=1) { fac.prog=0; fac.left--; s.workers++; poolBP += 75; incE += 5;
        timeline.push({ t, ev:`[BP] worker #${s.workers} out`, bp:poolBP, incM, incE, e, m:Math.round(m), mCap, eCap, mex:s.mex, workers:s.workers, turret:s.turret }); } }
      else { pool.prog += x.f*sc; if (pool.prog>=1) { const pstep = pool.step;
        s[CAT(pstep.do)]++; incM += MPS(pstep.do); incE += ENET(pstep.do, g.windAvg);
        mCap += x.d.metalStorage||0; eCap += x.d.energyStorage||0;
        if (pstep.do==="turret") poolBP += 200;
        timeline.push({ t, ev:pstep.why, bp:poolBP, incM, incE, e, m:Math.round(m), mCap, eCap, mex:s.mex, workers:s.workers, turret:s.turret });
        pool.step = null; } }
    }
  }
  return { label:g.label, t:r1(t), counts:s, incM:r1(incM), incE:r1(incE), minE:Math.round(minE), m:Math.round(m), e:Math.round(e), timeline };
}

// ============ NARRATIVE STATE DESCRIPTION ============
// "I am at an N-mex (M/s) economy, with BP build power, being spent on X,
//  with current resources showing a surplus of metal, next objective: medmex."
export function narrativeState(ev, g, nextAction) {
  const { bp, incM, incE, m, mCap, workers, turret } = ev;
  const mexCount  = ev.mex ?? null;    // actual count if tracked; null falls back to display without count
  const parts     = [`com${COM_BP}`];
  if (workers > 0) parts.push(`${workers}×w75`);
  if (turret  > 0) parts.push(`${turret}×nano200`);
  const poolStr   = `${bp} BP  (${parts.join(" + ")})`;
  const mPct      = Math.round(100 * m / mCap);
  const drainCap  = r1(bp * LEG_MEX_M_BT);
  const mState    = mPct >= 80 ? `SURPLUS ⚠ (${mPct}%, drain-cap ${drainCap} M/s)` : `${mPct}%`;
  const mexStr = mexCount != null ? `${mexCount}-mex` : ``;
  console.log(`\n${"═".repeat(70)}`);
  console.log(`  ${mexStr} economy  (${r1(incM)} M/s)  |  ${poolStr}  |  ${r1(incE)} E/s`);
  console.log(`  M: ${m}/${mCap}  [${mState}]    E: ${ev.e}/${ev.eCap ?? 1000}`);
  if (nextAction) console.log(`  next objective: ${nextAction}`);
  console.log(`${"═".repeat(70)}`);
}

// ============ ENERGY SEARCH FOR TARGET ============
// For each candidate energy source, compute how many to build first (or juggle in)
// so the target's energy-intensive build doesn't stall.
//
// env = { poolBP, incE, incM, eBank, eCap, [facDraw] }
//   facDraw: optional ongoing E/s draw from factory (subtract from effective incE)
//
// Stall model (bank-first, then income-throttled):
//   Phase 1: build at full poolBP, draining (draw - incE) E/s from bank  → lasts bank/(draw-incE) s
//   Phase 2: build at incE/E_BT effective BP until done
export function energy_search_at_target(env, targetKey, eSources) {
  const tDef   = D(UNIT[targetKey]);
  const tE_BT  = tDef.energyCost / tDef.buildTime;   // E/s per BP while building
  const { poolBP, eBank = 1000, eCap = 1000, facDraw = 0 } = env;
  const netInc = env.incE - facDraw;                  // effective E/s available for this build

  const effBP = (ie) => Math.min(poolBP, ie / tE_BT);

  function stalledTime(ie, bank) {
    const draw = poolBP * tE_BT;
    if (ie >= draw) return r1(tDef.buildTime / poolBP);  // no stall
    const drain  = draw - ie;
    const ph1T   = bank / drain;
    const ph1P   = Math.min(1, ph1T * poolBP / tDef.buildTime);
    if (ph1P >= 1) return r1(tDef.buildTime / poolBP);   // bank outlasts the build → full-speed
    return r1(ph1T + (1 - ph1P) * tDef.buildTime / effBP(ie));
  }

  const draw    = r1(poolBP * tE_BT);
  const baseT   = stalledTime(netInc, eBank);
  const basePct = Math.round(100 * effBP(netInc) / poolBP);
  const fullBPT = r1(tDef.buildTime / poolBP);

  console.log(`\n  target: ${targetKey}  (${tDef.metalCost}m / ${tDef.energyCost}e)  |  pool ${poolBP} BP  →  draw ${draw} E/s`);
  console.log(`  income: ${r1(netInc)} E/s${facDraw ? ` (gross ${r1(env.incE)} − factory ${r1(facDraw)})` : ""}   bank ${eBank}/${eCap}`);
  console.log(`  baseline: ${basePct}% eff  →  ~${baseT}s  (perfect full-speed: ${fullBPT}s)`);
  if (netInc < draw) console.log(`  ⚠ E-bottleneck  (${r1(draw - netInc)} E/s short)  — options below:`);
  if (facDraw > 0)   console.log(`  ✦ option: pause factory  →  free ${r1(facDraw)} E/s during this build`);

  for (const eKey of eSources) {
    const eDef    = D(UNIT[eKey]);
    const eYield  = ENET(eKey, 11.2);
    const eBT     = r1(eDef.buildTime / poolBP);
    const eDraw   = r1(poolBP * eDef.energyCost / eDef.buildTime);
    const enetBld = r1(netInc - eDraw);   // net E/s while building this source (positive = bank recovers)

    console.log(`\n  [${eKey}]  +${eYield} E/s  |  ${eDef.metalCost}m / ${eDef.energyCost}e  |  ${eBT}s @ ${poolBP}BP  |  draw ${eDraw} E/s while building  (bank net ${enetBld >= 0 ? "+" : ""}${enetBld} E/s)`);

    // N=1 — build one then target
    {
      const ie1 = netInc + eYield;
      const t1  = stalledTime(ie1, eBank);
      const p1  = (t1 === fullBPT) ? 100 : Math.round(100 * effBP(ie1) / poolBP);
      console.log(`    N=1:    +${eDef.metalCost}m  ${eBT}s  →  E ${r1(ie1)} E/s  →  target ${t1}s (${p1}%)   [${r1(parseFloat(eBT) + parseFloat(t1))}s total]`);
    }

    // N for ≥50% speed
    const n50 = Math.max(2, Math.ceil((poolBP * tE_BT * 0.5 - netInc) / eYield));
    {
      const ie50 = netInc + n50 * eYield;
      const t50  = stalledTime(ie50, eBank);
      const p50  = (t50 === fullBPT) ? 100 : Math.round(100 * effBP(ie50) / poolBP);
      const eBld = r1(n50 * eBT);
      console.log(`    N=${n50}: +${n50 * eDef.metalCost}m  ${eBld}s  →  E ${r1(ie50)} E/s  →  target ${t50}s (${p50}%)   [${r1(parseFloat(eBld) + parseFloat(t50))}s total]  (≥50% speed)`);
    }

    // N for 100% (no stall)
    const nFull = Math.ceil((poolBP * tE_BT - netInc) / eYield);
    if (nFull !== n50) {
      const ieFull = netInc + nFull * eYield;
      const eBld   = r1(nFull * eBT);
      console.log(`    N=${nFull}: +${nFull * eDef.metalCost}m  ${eBld}s  →  E ${r1(ieFull)} E/s  →  target ${fullBPT}s (100%)   [${r1(parseFloat(eBld) + parseFloat(fullBPT))}s total]  (no stall)`);
    }

    // Juggling simulation: build target ↔ insert one energy source when bank hits floor
    {
      let ie = netInc, bank = eBank, prog = 0, time = 0, n = 0, iter = 0;
      const FLOOR = 50, MAX = 500;
      while (prog < 1 && iter++ < MAX) {
        const draw2   = poolBP * tE_BT;
        if (ie >= draw2) { time += (1 - prog) * tDef.buildTime / poolBP; prog = 1; break; }
        const netD    = draw2 - ie;
        const tToF    = Math.max(0, (bank - FLOOR) / netD);
        const pps     = poolBP / tDef.buildTime;
        const tBuild  = Math.min(tToF, (1 - prog) / pps);
        prog  += tBuild * pps;
        bank   = Math.max(FLOOR, bank - tBuild * netD);
        time  += tBuild;
        if (prog >= 1) break;
        // insert one energy source
        const eNetDuringBuild = netInc - poolBP * (eDef.energyCost / eDef.buildTime);
        bank   = Math.min(eCap, bank + eBT * eNetDuringBuild);
        time  += parseFloat(eBT);
        ie    += eYield;
        n++;
      }
      const note = iter >= MAX ? " (MAX iterations)" : "";
      console.log(`    juggle: ${n} ${eKey}(s) inserted mid-build  →  ~${r1(time)}s total  end-incE ${r1(ie)} E/s${note}`);
    }
  }

  // ── estor bank-buffer analysis (different category: not income, just cap)
  {
    const estDef     = D(UNIT.estor);
    const estBT      = r1(estDef.buildTime / poolBP);
    const estCap     = estDef.energyStorage ?? ESTOR_CAP;
    const estorBuilt = eCap > 1000;   // >1000 = an estor is already in the plan
    const newCap     = estorBuilt ? eCap : eCap + estCap;
    const draw  = poolBP * tE_BT;
    const drain = draw - netInc;
    const bankForFullSpeed = drain > 0 ? r1(drain * tDef.buildTime / poolBP) : 0;

    if (estorBuilt) {
      console.log(`\n  [estor]  already in plan  —  eCap ${eCap}  (+${estCap}E already added)`);
      console.log(`    current bank: ${eBank}/${eCap}  (${Math.round(100*eBank/eCap)}% full)`);
    } else {
      console.log(`\n  [estor]  legestor  +${estCap}E cap (eCap ${eCap}→${newCap})  ${estDef.metalCost}m  reclaimable later`);
      console.log(`    build: ${estBT}s @ ${poolBP}BP  (draw ${r1(poolBP * estDef.energyCost / estDef.buildTime)} E/s while building)`);
    }
    console.log(`    bank threshold for full-speed target: ${bankForFullSpeed}E  (need bank ≥ ${bankForFullSpeed}E when medmex starts)`);
    const levels = [0, 1000, 2000, Math.round(bankForFullSpeed), newCap].filter((v,i,a)=>a.indexOf(v)===i).sort((a,b)=>a-b);
    console.log(`    medmex build time at bank level (eCap ${newCap}):`);
    for (const lv of levels) {
      if (lv > newCap) continue;
      const t = stalledTime(netInc, lv);
      const spd = lv >= bankForFullSpeed ? "100% ← full speed" : `${Math.round(100 * Math.min(1, lv / (bankForFullSpeed||1)))}% bank`;
      console.log(`      bank ${String(lv).padStart(5)}E → ${t}s  (${spd})`);
    }
    if (!estorBuilt) {
      console.log(`    → build estor EARLY (before con turret drains the bank); bank fills gradually,`);
      console.log(`      leaving ~${Math.round(newCap * 0.6)}–${newCap}E when medmex starts → near full-speed`);
    }
    console.log(`    → reclaim for ${estDef.metalCost}m when T2 factory goes up (no E returned)`);
  }

  // ── solar vs wind: when to prefer which
  if (eSources.includes("solar") && eSources.includes("win")) {
    const sDef   = D(UNIT.solar),  wDef = D(UNIT.win);
    const sBT    = r1(sDef.buildTime / poolBP);
    const wBT    = r1(wDef.buildTime / poolBP);
    const sNetE  = r1(netInc - poolBP * (sDef.energyCost / sDef.buildTime));   // net E/s during solar build (solar 0 e-cost → = netInc)
    const wNetE  = r1(netInc - poolBP * (wDef.energyCost / wDef.buildTime));   // net E/s during wind build
    const sRecover = r1(parseFloat(sBT) * sNetE);   // bank E recovered per solar inserted
    const wRecover = r1(parseFloat(wBT) * Math.max(0, wNetE));
    const metalSaved = sDef.metalCost - wDef.metalCost;                         // 155 - 45 = 110m saved by wind
    const incomeSecs = r1(metalSaved / env.incM);                               // seconds of income to earn the difference
    const sPerM  = r1(sDef.metalCost / sRecover);   // metal per E recovered (juggling) — lower = better
    const wPerM  = wRecover > 0 ? r1(wDef.metalCost / wRecover) : "∞";

    console.log(`\n  ── solar vs wind (juggling efficiency)`);
    console.log(`    solar: ${sDef.metalCost}m / 0e  →  bank net +${sNetE} E/s × ${sBT}s = +${sRecover}E recovered  (${sPerM} m per E)`);
    console.log(`    wind:  ${wDef.metalCost}m / ${wDef.energyCost}e  →  bank net +${wNetE} E/s × ${wBT}s = +${wRecover}E recovered  (${wPerM} m per E)`);
    console.log(`    metal saved by wind over solar: ${metalSaved}m = ${incomeSecs}s of income @ ${r1(env.incM)} M/s`);
    console.log(`    solar gives ${r1(sRecover / (wRecover||0.001))}× more bank recovery per juggle cycle → faster medmex build`);
    console.log(`    ⚠ if you're building solar and hit 0 metal: switch to wind — ${metalSaved}m × 1/${metalSaved} saves ${incomeSecs}s`);
    console.log(`      BUT only if wind's extra medmex time (worse recovery) costs more than ${incomeSecs}s`);
    console.log(`      Rule: solar dominates unless metal is < ${sDef.metalCost}m and you can't wait ${incomeSecs}s for income`);
  }

  // Reclaim note
  console.log(`\n  ✦ reclaim: commander uses 300 BP in reverse — zero E cost, returns metalCost when done.`);
  console.log(`    e.g. reclaim legwin: ${r1(D(UNIT.win).buildTime / COM_BP)}s, returns ${D(UNIT.win).metalCost}m, 0e recovered.`);
}

// ============ BUILD-RATE REFERENCE TABLE ============
// M/BP/s × poolBP = metal draw per second while building that unit type.
// E/BP/s × poolBP = energy draw per second while building.
// Scale to any pool size: 525 BP on medmex → 525 × 0.050 = 26.3 M/s, 525 × 1.000 = 525 E/s demand.
export function bpRefTable(refBP = 500) {
  const r3 = (x) => Math.round(x * 1000) / 1000;
  const ckD = D("legck"), labD = D("leglab"), convD = D("legeconv");
  const entries = [
    ["mex",    "T1 legmex",           "metal"  ],
    ["medmex", "MedMex T1.5 (delta)", "metal+" ],
    ["moho",   "T2 moho",             "metal"  ],
    ["win",    "wind",                "energy" ],
    ["solar",  "solar  (0 build-E)",  "energy" ],
    ["advsol", "adv solar",           "energy" ],
    ["turret", "con turret +200BP",   "BP"     ],
  ];
  const rows = entries.map(([key, label, cat]) => {
    const d = D(UNIT[key]);
    const mBP = r3(d.metalCost / d.buildTime);
    const eBP = r3(d.energyCost / d.buildTime);
    const bT  = r1(d.buildTime / refBP);
    let yM = "—", yE = "—";
    if (key === "medmex") {
      yM = `ΔM+${r1(MPS("medmex") - MPS("mex"))}`; yE = `ΔE-${MEDMEX_SWING}`;
    } else if (MPS(key)) {
      yM = `+${r1(MPS(key))}`; yE = `${ENET(key, 11.2) >= 0 ? "+" : ""}${ENET(key, 11.2)}`;
    } else {
      const ne = ENET(key, 11.2); yE = ne ? `+${ne}${key === "win" ? "avg" : ""}` : "0";
    }
    return { label, defName: UNIT[key], cat, mBP, eBP, bT, yM, yE };
  });
  const extra = (d, label, cat, yM, yE) => ({ label, defName: d.defName, cat,
    mBP: r3(d.metalCost / d.buildTime), eBP: r3(d.energyCost / d.buildTime),
    bT: r1(d.buildTime / refBP), yM, yE });
  rows.push(extra(ckD,   "worker +75BP",       "BP",      "—",               "+5"));
  rows.push(extra(labD,  "factory (leglab)",   "BP",      "+150BP",           "—"));
  rows.push(extra(convD, "econv 70E→1M",       "cleanup", "70E→1M",           "—"));
  const estD = D(UNIT.estor);
  rows.push(extra(estD,  "estor (reclaimable)","E-buf",   `+${ESTOR_CAP}E cap`, "0"));
  return rows;
}

// ============ DECISION CHECKS ============
// At each build event: answer the 4 key planning questions.
const LEG_MEX_M_BT = 50 / 1880;  // legmex metalCost/buildTime — metal draw rate per BP building mex
function decisionsStr(ev, g) {
  const { incM, incE, bp, m, mCap } = ev;

  // Q1: more BP justified? — income exceeds what the pool can sink building mexes
  const drainCap = r1(bp * LEG_MEX_M_BT);
  const q1 = incM > drainCap
    ? `YES (${r1(incM)}M/s > pool-drain ${drainCap})`
    : `no  (${r1(incM)}M/s ≤ pool-drain ${drainCap})`;

  // Q2: unspendable metal? — M near cap; if so, which energy source to fix or is it temporary?
  const mPct = Math.round(100 * m / mCap);
  let q2;
  if (mPct >= 85) {
    const margin = r1(incE - g.minNetE);
    q2 = margin < 25
      ? `YES → solar  (E-margin ${margin}, fastest & 0 build-E)`
      : `YES → more BP  (E margin ${margin} ok, pool can't drain metal)`;
  } else { q2 = `no  (M ${mPct}% full)`; }

  // Q3: enough energy income to justify the next med-mex? (ΔE = -37 when built)
  const eAfter = r1(incE - MEDMEX_SWING);
  const q3 = eAfter >= g.minNetE
    ? `yes  (E${r1(incE)}-37=${eAfter}≥${g.minNetE})`
    : `no   (E${r1(incE)}-37=${eAfter}<${g.minNetE})`;

  // Q4: cleanup — M capping; econv (70E→1M) or reclaim solars if also E-full
  const q4 = mPct >= 90 ? `check  (M ${mPct}% full → econv or reclaim solars if E also full)` : `no`;

  return [
    `    ∙ more BP?   ${q1}`,
    `    ∙ M-stall?   ${q2}`,
    `    ∙ medmex ok? ${q3}`,
    `    ∙ cleanup?   ${q4}`,
  ].join("\n");
}

// ============ POOL DESCRIPTION ============
// "X BP economy (com300 + N×w75 + N×nano200)" — the user's narrative framing.
function poolDesc(ev) {
  const parts = [`com${COM_BP}`];
  if (ev.workers > 0) parts.push(`${ev.workers}×w75`);
  if (ev.turret  > 0) parts.push(`${ev.turret}×nano200`);
  return `${ev.bp} BP  (${parts.join(" + ")})`;
}

// ---- run ----
if ((process.argv[1]||"").replace(/\\/g,"/").endsWith("legion_planner.mjs")) {
  const key      = process.argv[2] || "corrected";
  const stateKey = process.argv[3] || "fivewalk_3rd_on_medmex";
  const g = PRESETS[key]; if (!g) { console.error("presets:", Object.keys(PRESETS).join(", ")); process.exit(1); }
  const st = loadState(stateKey);
  const R  = plan(g, st);
  const clk = (x) => { const s = Math.floor(x); return `${Math.floor(s/60)}:${String(s%60).padStart(2,"0")}`; };

  // --- reference table ---
  const REF_BP = 500;
  console.log(`\n${"=".repeat(78)}`);
  console.log(`  BUILD-RATE REFERENCE  (scale by your pool size)`);
  console.log(`  M/BP/s × pool = metal draw while building   E/BP/s × pool = energy draw`);
  console.log(`  reference build time at ${REF_BP} BP`);
  console.log(`${"=".repeat(78)}`);
  console.log(`  ${"unit  (defName)".padEnd(34)} ${"cat".padEnd(8)} ${"M/BP/s".padStart(7)} ${"E/BP/s".padStart(7)} ${("@"+REF_BP+"BP").padStart(7)}  ${"yield M/s".padEnd(13)} yield E/s`);
  console.log("  " + "-".repeat(76));
  const fmt = (r) => {
    const lbl = `${r.label}  (${r.defName})`.padEnd(34);
    const cat = r.cat.padEnd(8);
    const mBP = String(r.mBP).padStart(7);
    const eBP = String(r.eBP).padStart(7);
    const bT  = `${r.bT}s`.padStart(7);
    const yM  = String(r.yM).padEnd(13);
    console.log(`  ${lbl} ${cat} ${mBP} ${eBP} ${bT}  ${yM} ${r.yE}`);
  };
  for (const r of bpRefTable(REF_BP)) fmt(r);

  // --- timeline ---
  console.log(`\n${"=".repeat(78)}`);
  console.log(`  PRESET: ${R.label}`);
  console.log(`  start:  ${stateKey} — ${st?.desc ?? "after 5 mex + factory"}`);
  console.log(`  levers: BP · M/s (metal) · E/s (energy)   egen target ~${g.egenTarget}`);
  console.log(`${"=".repeat(78)}\n`);

  const medmexDef = D(UNIT.medmex);
  let eSearchDone = false;
  for (let i = 0; i < R.timeline.length; i++) {
    const ev = R.timeline[i];

    // Before the first medmex event: narrative state + energy search
    if (!eSearchDone && ev.ev.startsWith("[M] med-mex")) {
      const pre = R.timeline[i - 1] ?? ev;
      const preCap = pre.eCap ?? 1000;
      // bank fills during the walk to the medmex spot — pass the bank AT BUILD START, not at last event
      const walkDist = distMex(pre.mex ?? 7);
      const walkTime = walkDist / COM_SPEED;
      const eBankAtStart = Math.min(preCap, (pre.e || 0) + (pre.incE || 0) * walkTime);
      narrativeState({ ...pre, eCap: preCap }, g, `med-mex (legmext15) — ${medmexDef.metalCost}m / ${medmexDef.energyCost}e`);
      console.log(`  (bank fills during ${r1(walkTime)}s walk: ${pre.e}→${Math.round(eBankAtStart)}e at build start)`);
      energy_search_at_target(
        { poolBP: pre.bp, incE: pre.incE, incM: pre.incM, eBank: eBankAtStart, eCap: preCap },
        "medmex", ["solar", "win", "advsol"]
      );
      eSearchDone = true;
      console.log();
    }

    console.log(`  ${clk(ev.t).padStart(5)}  ${poolDesc(ev).padEnd(36)}  ${r1(ev.incM).toString().padStart(6)} M/s  ${r1(ev.incE).toString().padStart(6)} E/s`);
    console.log(`         ${ev.ev}`);
    console.log(decisionsStr(ev, g));
    console.log();
  }

  const last = R.timeline.at(-1);
  console.log(`${"=".repeat(78)}`);
  console.log(`  end @ ${clk(R.t)}`);
  if (last) console.log(`  ${poolDesc(last)}`);
  console.log(`  M/s ${R.incM}   E/s ${R.incE}   min-energy-ever ${R.minE}`);
  console.log(`  built: mex×${R.counts.mex}  medmex×${R.counts.medmex}  moho×${R.counts.moho}  solar×${R.counts.solar}  wind×${R.counts.wind}  advsol×${R.counts.advsol}  turret×${R.counts.turret}  workers×${R.counts.workers}`);
}

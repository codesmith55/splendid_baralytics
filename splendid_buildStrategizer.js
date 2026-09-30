"use strict";
// splendid_buildStrategizer.js — decide what every source of build power should do next.
//
//   node splendid_buildStrategizer.js <source> --team <id|name> [--at <sec>] [--horizon <sec>]
//                                              [--strategy S] [--profile P] [--compare [S1,S2,..]] [--dt <sec>]
//   node splendid_buildStrategizer.js --fresh [--strategy S] [--profile P] [--horizon <sec>]   (no game: from spawn)
//
// Input is the simulator's state (splendid_buildSimulator Environment, reset to a parser moment);
// output is one task per idle builder plus the projected timeline. Strategies:
//
//   eco_rules            bar-calc/bar_economy.md "course corrections" as a rule
//                        cascade (metal+energy → build power / e-storage, metal+no energy → solar,
//                        no metal+storage+energy → reclaim solar → converters, default wind)
//   flow:<name>          a KNOWN FLOW = named priority list (FLOWS below; e.g. bar_calc's solar opening),
//                        consumed in order by whichever builder is free, then eco_rules take over
//   priority:<A,B,..>    bar_calc.build_with_priorities — first non-stalling entry, else Wind
//   towards:<Object>     bar_calc.calc_build_towards_object — grow energy (wind vs solar decided by
//                        the required-eps multiplier) until the target can be built, then build it
//   replay               reality's own decisions (splendid_buildSimulator.replayDecider) — the baseline
//
// Profiles (playstyles, mirroring barbots/decider/profiles.py) re-weight candidates:
// score = (rank + 1) / bias[object]; lowest wins. Same state, different weights → different orders.

const fs = require("fs");
const path = require("path");
const P = require("./splendid_buildParser");
const S = require("./splendid_buildSimulator");

const MEX_SPOT_GRID = 48;
const spotKey = (x, z) => `${Math.round(x / MEX_SPOT_GRID)}:${Math.round(z / MEX_SPOT_GRID)}`;

// ───────────────────────────────────────────── known flows (priority lists)
const FLOWS = {
  // bar_calc.py __main__ solar opening
  solar_open: ["Mex", "Mex", "Solar", "Mex", "Solar", "BotFactory", "Mex", "Mex"],
  // bar_calc.py wind variant
  wind_open: ["Mex", "Mex", "Wind", "Wind", "Mex", "BotFactory", "Wind", "BotWorker"],
  // Glitters standard: 3 mex, winds, lab, cons keep winding, first turret + storage
  glitters_std: ["Mex", "Mex", "Mex", "Wind", "Wind", "Wind", "BotFactory", "Wind", "Wind", "Wind", "Mex",
    "BotWorker", "Wind", "Wind", "BotWorker", "Wind", "Wind", "Wind", "ConTurret", "Wind", "Wind", "EStorage"],
  // wind-conversion (Splendi 7mex/56wind@7:00 shape): solars early, reclaimed into winds later
  wind_conversion: ["Mex", "Mex", "Mex", "Solar", "Solar", "BotFactory", "Mex", "Mex", "Wind", "Wind", "Wind", "Wind",
    "BotWorker", "Wind", "Wind", "Wind", "EStorage", "Wind", "Wind", "BotWorker", "ConTurret", "Wind", "Wind",
    "ReclaimSolar", "Wind", "Wind", "ReclaimSolar", "Wind", "Wind", "EConverter", "EConverter"],
};

// ───────────────────────────────────────────── playstyle profiles (barbots names)
const PROFILES = {
  balanced:      { desc: "Follow the rules as written, small energy buffer.", bias: {}, mexReach: 600, eLow: 0.2, eHigh: 0.6, mLow: 0.2, mHigh: 0.6 },
  greedy_expand: { desc: "Metal above all — walk far for mexes, energy only when starved.", bias: { Mex: 1.6, AMex: 1.3, Solar: 0.75, Wind: 0.75 }, mexReach: 1100, eLow: 0.12, eHigh: 0.6, mLow: 0.15, mHigh: 0.7 },
  energy_first:  { desc: "Overbuild energy, never stall, convert surplus later.", bias: { Wind: 1.5, Solar: 1.4, EConverter: 1.2 }, mexReach: 500, eLow: 0.3, eHigh: 0.7, mLow: 0.2, mHigh: 0.55 },
  tech_rush:     { desc: "Bank toward big-ticket eco (AMex) instead of width.", bias: { AMex: 1.6, ConTurret: 0.8, Wind: 0.9 }, mexReach: 500, eLow: 0.2, eHigh: 0.6, mLow: 0.1, mHigh: 0.8, bankTarget: 500 },
  tempo:         { desc: "Fast-payback builds only; nothing banks.", bias: { Wind: 1.2, Mex: 1.2, ConTurret: 1.1 }, mexReach: 500, eLow: 0.2, eHigh: 0.5, mLow: 0.25, mHigh: 0.5 },
};

// ───────────────────────────────────────────── situation (what the rules look at)
function situation(env, builder, ctx, prof) {
  const c = env.counts();
  const mFill = env.maxMetal > 0 ? env.metal / env.maxMetal : 0;
  const eFill = env.maxEnergy > 0 ? env.energy / env.maxEnergy : 0;
  const s = {
    mFill, eFill,
    mHigh: mFill > prof.mHigh, mLow: mFill < prof.mLow, eHigh: eFill > prof.eHigh, eLow: eFill < prof.eLow,
    mInc: env.incomeM(), eInc: env.incomeE(), eNet: env.incomeE() - drainE(env),
    solars: c.Solar || 0, winds: c.Wind || 0, mexes: c.Mex || 0, turrets: c.ConTurret || 0,
    estor: c.EStorage || 0, conv: c.EConverter || 0, factories: c.BotFactory || 0, workers: c.BotWorker || 0,
    isFactory: !!builder.factory, wind: env.wind,
    freeMex: builder.factory ? null : nearestFreeSpot(env, ctx, builder, prof.mexReach),
    bpTotal: env.getTotalBuildpower(),
  };
  return s;
}

/** Energy/s the current tasks are drawing (bp share of each build's energy cost). */
function drainE(env) {
  let d = 0;
  for (const b of env.builders) {
    if (!b.task || b.task.walkLeft > 0) continue;
    const t = env.obj(b.task.object); if (t.bp <= 0) continue;
    d += (b.bp / t.bp) * t.energy;
  }
  return d;
}

function nearestFreeSpot(env, ctx, builder, reach) {
  let best = null, bestD = Infinity;
  for (const sp of ctx.spots) {
    const k = spotKey(sp.x, sp.z);
    if (ctx.taken.has(k)) continue;
    const d = Math.hypot(sp.x - builder.x, sp.z - builder.z);
    if (d < bestD) { best = sp; bestD = d; }
  }
  return best && bestD <= reach ? { ...best, dist: bestD } : null;
}

// ───────────────────────────────────────────── eco_rules (bar_economy.md cascade)
// Each rule: when(s) → object name or null. Order = importance. Candidates from every firing rule
// are ranked by position, then re-weighted by the profile bias.
const RULES = [
  { name: "free mex in reach", why: "a free metal spot is the best ROI on the board",
    when: s => s.freeMex ? "Mex" : null },
  { name: "Metal + Energy = Build Power", why: "we have metal and energy: upgear the economy for future flexibility (con turrets / workers, ~1 e-storage per 4 turrets after the 2nd)",
    when: s => !(s.mHigh && s.eHigh) ? null : s.isFactory ? "BotWorker" : (s.turrets >= 2 && s.estor < Math.ceil(s.turrets / 4)) ? "EStorage" : "ConTurret" },
  { name: "Metal + No Energy = Solar", why: "metal we cannot spend: solar turns it into E at the fastest EROI",
    when: s => (s.mHigh && s.eLow && !s.isFactory) ? "Solar" : null },
  { name: "No Metal + E-storage + Energy = Reclaim solar", why: "through the energy stall: reclaim gives 100% of the solar's metal back, wind is the better E/M now",
    when: s => (s.mLow && s.eHigh && s.estor > 0 && s.solars > 0 && !s.isFactory) ? "ReclaimSolar" : null },
  { name: "No Metal + E-storage + Energy + No Solars = Converters", why: "still out of metal with energy to spare: converters bleed off everything past storage",
    when: s => (s.mLow && s.eHigh && s.estor > 0 && s.solars === 0 && !s.isFactory) ? "EConverter" : null },
  { name: "Metal + E-storage + Energy + low wind = Adv Solar", why: "safe energy when wind is low and no more build power is wanted (2 apm, not the fastest)",
    when: s => (s.mHigh && s.eHigh && s.estor > 0 && s.wind < 8 && !s.isFactory) ? "AdvSolar" : null },
  { name: "Default: Low Metal + Low Energy = Wind", why: "wind map default (0–16 like glitters or better)",
    when: s => s.isFactory ? null : "Wind" },
];

function ecoRuleCandidates(s) {
  const out = [];
  RULES.forEach((r, rank) => { const o = r.when(s); if (o) out.push({ object: o, rank, rule: r.name, why: r.why }); });
  return out;
}

// ───────────────────────────────────────────── strategies → candidate lists
function makeStrategy(spec, ctx) {
  if (spec === "eco_rules") return { name: spec, candidates: (env, b, s) => ecoRuleCandidates(s) };
  if (spec.startsWith("flow:")) {
    const flow = FLOWS[spec.slice(5)]; if (!flow) throw new Error(`unknown flow ${spec.slice(5)}; have: ${Object.keys(FLOWS).join(", ")}`);
    const queue = [...flow];
    let trimmed = false;
    return { name: spec, queue, candidates: (env, b, s) => {
      // flows are written from spawn: when entered mid-game, steps the current state already
      // covers are consumed first (a lab that exists is not built again)
      if (!trimmed) {
        trimmed = true;
        const have = { ...env.counts() };
        for (let i = 0; i < queue.length;) { if (have[queue[i]] > 0) { have[queue[i]]--; queue.splice(i, 1); } else i++; }
      }
      // the first queued item this builder can make; factory products only from factories
      for (let i = 0; i < queue.length; i++) {
        const o = queue[i];
        if (!canMake(env, b, o)) continue;
        return [{ object: o, rank: 0, rule: `flow ${spec.slice(5)} #${flow.length - queue.length + i + 1}`, why: "next step of the known flow", take: () => queue.splice(i, 1) }];
      }
      return ecoRuleCandidates(s);   // flow exhausted (or nothing makeable) → rules
    } };
  }
  if (spec.startsWith("priority:")) {
    const list = spec.slice(9).split(",").map(x => x.trim()).filter(Boolean);
    return { name: spec, candidates: (env, b, s) => {
      const c = list.filter(o => canMake(env, b, o)).map((o, i) => ({ object: o, rank: i, rule: "priority list", why: "first entry that does not stall (bar_calc.build_with_priorities)" }));
      if (!b.factory) c.push({ object: "Wind", rank: list.length, rule: "priority fallback", why: "all priority options would stall → Wind" });
      return c;
    } };
  }
  if (spec.startsWith("towards:")) {
    const target = spec.slice(8);
    let baseline = null;
    return { name: spec, candidates: (env, b, s) => {
      // once the target has been built (count rose since we started), hand over to the rules
      const have = env.counts()[target] || 0;
      if (baseline == null) baseline = have + env.builders.filter(x => x.task && x.task.object === target).length;
      if (have > baseline) return ecoRuleCandidates(s);
      if (env.builders.some(x => (x.task && x.task.object === target) || x.queue.some(q => q.object === target))) return ecoRuleCandidates(s);
      if (b.factory) return canMake(env, b, target) ? [{ object: target, rank: 0, rule: "towards", why: "target" }] : [];
      const reqBps = Math.max(1, env.optimalBuildPower(target));
      const reqEps = Math.max(1e-6, env.reqEnergyWithBp(target, reqBps));
      const eMult = env.incomeE() / reqEps;
      if (eMult >= 1 || target === "Wind") return [{ object: target, rank: 0, rule: "towards: energy sufficient", why: `eCurMult ${eMult.toFixed(2)} ≥ 1 → build the target` }];
      const wReq = Math.max(1e-6, env.reqEnergyWithBp("Wind", Math.max(1, env.optimalBuildPower("Wind"))));
      const wMult = env.incomeE() / wReq;
      const o = wMult >= 1 ? "Wind" : "Solar";
      return [{ object: o, rank: 0, rule: "towards: build more energy", why: `eCurMult ${eMult.toFixed(2)} < 1 for ${target}; wind eCurMult ${wMult.toFixed(2)} → ${o}` }];
    } };
  }
  throw new Error(`unknown strategy ${spec}`);
}

/** Can this builder physically make the object (factory products from factories, buildings from mobile/turret)? */
function canMake(env, b, objectName) {
  const t = env.registry.get(objectName); if (!t) return false;
  const factoryProduct = S.FACTORY_PRODUCTS.has(t.name) || t.kind === "unit" || (t.kind === "builder" && (t.speed || 0) > 0);
  if (factoryProduct) return !!b.factory;
  if (b.factory) return false;
  if (t.kind === "reclaim") {   // only as many reclaims as there are targets not already being reclaimed
    const inFlight = env.builders.filter(x => (x.task && x.task.object === t.name) || x.queue.some(q => q.object === t.name)).length;
    return (env.counts()[t.of] || 0) - inFlight > 0;
  }
  return true;
}

// ───────────────────────────────────────────── the decider
/**
 * Build a decider (env → void) for splendid_buildSimulator: every tick, each idle builder gets the
 * best-scoring feasible candidate of the strategy, re-weighted by the profile. Decisions are logged
 * to `log` with the rule that produced them.
 */
function makeDecider(game, teamID, { strategy = "eco_rules", profile = "balanced", log = [] } = {}) {
  const prof = PROFILES[profile]; if (!prof) throw new Error(`unknown profile ${profile}; have: ${Object.keys(PROFILES).join(", ")}`);
  if (strategy === "replay") { if (!game) throw new Error("replay needs a game"); return S.replayDecider(game, teamID); }
  const ctx = { spots: [], taken: new Set(), seeded: false };
  const strat = makeStrategy(strategy, ctx);

  const seed = env => {
    ctx.spots = (env.mexSpots && env.mexSpots.length) ? env.mexSpots : syntheticSpots(env);
    // spots any team already occupied before this instant count as taken (dead mexes are ignored)
    if (game) for (const e of game.events) if (e.kind === "created" && e.sec <= env.time && /mex$/.test(e.defName || "")) ctx.taken.add(spotKey(e.x, e.z));
    ctx.seeded = true;
  };

  return env => {
    if (!ctx.seeded) seed(env);
    for (const b of env.idleBuilders()) {
      if (b.bp <= 0) continue;
      const s = situation(env, b, ctx, prof);
      const cands = strat.candidates(env, b, s).filter(c => canMake(env, b, c.object));
      if (!cands.length) continue;
      // feasibility: stall check with this builder's BP (bar_calc.calculate_build_times), profile bias
      let best = null, bestScore = Infinity;
      for (const c of cands) {
        const bt = env.calculateBuildTimes(c.object, { buildpower: b.bp, minAddTime: 0 });
        const bias = prof.bias[c.object] || 1;
        const stallPenalty = bt.stall ? 2 : 0;
        const score = (c.rank + 1 + stallPenalty) / bias;
        if (score < bestScore) { best = { ...c, bt }; bestScore = score; }
      }
      if (!best) continue;
      if (prof.bankTarget && env.metal < prof.bankTarget && best.object !== "Mex" && best.object !== "Wind" && env.obj(best.object).metal > 200) continue;  // tech_rush banks
      // site
      let x = b.x, z = b.z;
      if (best.object === "Mex") { const sp = s.freeMex || nearestFreeSpot(env, ctx, b, Infinity); if (!sp) continue; x = sp.x; z = sp.z; ctx.taken.add(spotKey(x, z)); }
      if (best.take) best.take();
      env.assign(b, best.object, x, z);
      const ot = env.obj(best.object);
      const out = ot.windPowered ? env.windNow() : Math.max(0, ot.eInc || 0) + (ot.mInc || 0) * S.ENERGY_PER_METAL;   // generator output in E/s-equivalent
      log.push({ time: env.time, builder: b.id, object: best.object, x, z, rule: best.rule, why: best.why,
        walk: b.task ? b.task.walkLeft / (b.speed || 1) : 0, eta: best.bt.totalTime, stall: best.bt.stall,
        troi: out > 0 ? S.troi(ot, out) : null, eroi: out > 0 ? S.eroi(ot, out, b.bp) : null,   // bar_unified ROI at current wind
        state: { metal: Math.round(env.metal), energy: Math.round(env.energy), mInc: +env.incomeM().toFixed(1), eInc: +env.incomeE().toFixed(1) } });
    }
  };
}

// No game → a ring of spots at 150-elmo steps from spawn (3 close, then further out)
function syntheticSpots(env) {
  const out = [];
  for (let i = 1; i <= 12; i++) { const a = i * 2.4, r = 120 + 140 * i; out.push({ x: (env.startX || 0) + r * Math.cos(a), z: (env.startZ || 0) + r * Math.sin(a) }); }
  return out;
}

// ───────────────────────────────────────────── run a strategy from a moment
function summarize(env) {
  const c = env.counts();
  return {
    time: env.time, metal: env.metal, energy: env.energy, mInc: env.incomeM(), eInc: env.incomeE(),
    econ: env.incomeM() + env.incomeE() / S.ENERGY_PER_METAL,
    bp: env.getTotalBuildpower(), counts: c,
    stallMetal: env.stallSec.metal, stallEnergy: env.stallSec.energy,
    overflowM: env.overflowLost.m, overflowE: env.overflowLost.e,
    worth: env.metal + env.energy / S.ENERGY_PER_METAL + env.spent.m + env.spent.e / S.ENERGY_PER_METAL,
  };
}

/**
 * Reset the simulator to reality at `at` (nearest moment), run `strategy` for `horizon` seconds.
 * Returns {env, log, completions, start, end, real} where real = the reality moment nearest at+horizon.
 */
function runStrategy(game, teamID, { at = 60, horizon = 180, strategy = "eco_rules", profile = "balanced", dt = 0.5 } = {}) {
  const log = [];
  let env, startMoment = null, real = null;
  if (game) {
    const moments = P.momentsFor(game, teamID);
    startMoment = moments.reduce((b, m) => (Math.abs(m.sec - at) < Math.abs(b.sec - at) ? m : b), moments[0]);
    env = S.environmentForTeam(game, teamID);
    env.every = game.every || 15;
    env.resetToReality(startMoment);
    const endSec = startMoment.sec + horizon;
    real = moments.reduce((b, m) => (Math.abs(m.sec - endSec) < Math.abs(b.sec - endSec) ? m : b), moments[0]);
  } else {
    env = new S.Environment({ time: 0 });
    env.startX = 0; env.startZ = 0; env.mexSpots = [];
  }
  const decider = makeDecider(game, teamID, { strategy, profile, log });
  const start = summarize(env);
  const completions = env.runUntil(env.time + horizon, { dt, decider });
  return { env, log, completions, start, end: summarize(env), real, strategy, profile, startMoment };
}

// ───────────────────────────────────────────── CLI
function mmss(sec) { const m = Math.floor(sec / 60), s = Math.round(sec % 60); return `${m}:${String(s).padStart(2, "0")}`; }
function pad(s, n) { s = String(s); return s.length >= n ? s : s + " ".repeat(n - s.length); }
function padL(s, n) { s = String(s); return s.length >= n ? s : " ".repeat(n - s.length) + s; }
function countsStr(c) {
  const order = ["Mex", "AMex", "Wind", "Solar", "AdvSolar", "EStorage", "EConverter", "ConTurret", "BotFactory", "BotWorker"];
  return order.filter(k => c[k]).map(k => `${c[k]}${k.replace("BotFactory", "lab").replace("BotWorker", "con").replace("ConTurret", "nano").replace("EConverter", "conv").replace("EStorage", "estor").toLowerCase()}`).join(" ");
}

function parseArgs(argv) {
  const a = { source: null, team: null, at: 60, horizon: 180, strategy: "eco_rules", profile: "balanced", compare: null, dt: 0.5, fresh: false, json: null, every: 15 };
  const rest = [];
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t === "--team") a.team = argv[++i];
    else if (t === "--at") a.at = Number(argv[++i]) || 0;
    else if (t === "--horizon") a.horizon = Number(argv[++i]) || 180;
    else if (t === "--strategy") a.strategy = argv[++i];
    else if (t === "--profile") a.profile = argv[++i];
    else if (t === "--dt") a.dt = Number(argv[++i]) || 0.5;
    else if (t === "--every") a.every = Number(argv[++i]) || 15;
    else if (t === "--json") a.json = argv[++i];
    else if (t === "--fresh") a.fresh = true;
    else if (t === "--compare") { const n = argv[i + 1]; if (n && !n.startsWith("--")) { a.compare = n.split(",").map(x => x.trim()); i++; } else a.compare = ["replay", "eco_rules", "flow:solar_open", "flow:wind_open", "flow:glitters_std", "towards:BotFactory"]; }
    else rest.push(t);
  }
  a.source = rest[0] || null;
  return a;
}

function printRun(r, label) {
  console.log(`\n== ${label} ==  (${r.strategy} · profile ${r.profile})`);
  console.log(`  start ${mmss(r.start.time)}: metal ${Math.round(r.start.metal)} energy ${Math.round(r.start.energy)} · ${r.start.mInc.toFixed(1)} m/s ${r.start.eInc.toFixed(1)} e/s · bp ${r.start.bp} · ${countsStr(r.start.counts)}`);
  console.log(`  ${pad("time", 6)} ${pad("builder", 18)} ${pad("build", 13)} ${padL("walk", 5)} ${padL("eta", 6)} ${pad("stall", 7)} ${padL("TROI", 6)} ${pad("metal/energy", 13)} rule`);
  for (const d of r.log) {
    console.log(`  ${pad(mmss(d.time), 6)} ${pad(d.builder, 18)} ${pad(d.object, 13)} ${padL(d.walk ? d.walk.toFixed(0) + "s" : "-", 5)} ${padL(isFinite(d.eta) ? d.eta.toFixed(0) + "s" : "∞", 6)} ${pad(d.stall || "-", 7)} ${padL(d.troi != null && isFinite(d.troi) ? d.troi.toFixed(0) + "s" : "-", 6)} ${pad(d.state.metal + "/" + d.state.energy, 13)} ${d.rule}`);
  }
  const e = r.end;
  console.log(`  end   ${mmss(e.time)}: metal ${Math.round(e.metal)} energy ${Math.round(e.energy)} · ${e.mInc.toFixed(1)} m/s ${e.eInc.toFixed(1)} e/s (${e.econ.toFixed(1)} value/s) · bp ${e.bp} · ${countsStr(e.counts)} · stalled ${e.stallMetal.toFixed(0)}s metal ${e.stallEnergy.toFixed(0)}s energy · overflow ${Math.round(e.overflowM)}m ${Math.round(e.overflowE)}e`);
  if (r.real && r.real.known.income) {
    const rm = r.real;
    console.log(`  real  ${mmss(rm.sec)}: metal ${Math.round(rm.metal)} energy ${Math.round(rm.energy)} · ${rm.mIncome.toFixed(1)} m/s ${rm.eIncome.toFixed(1)} e/s (${(rm.mIncome + rm.eIncome / 70).toFixed(1)} value/s)${rm.bpAvail != null ? ` · bp ${rm.bpAvail}` : ""}`);
  }
}

function printCompare(runs) {
  console.log(`\n== Strategy comparison  (same start state, ${mmss(runs[0].start.time)} → ${mmss(runs[0].end.time)}) ==`);
  console.log(`  ${pad("strategy", 24)} ${padL("value/s", 8)} ${padL("m/s", 6)} ${padL("e/s", 7)} ${padL("bp", 5)} ${padL("metal", 6)} ${padL("energy", 7)} ${padL("stallM", 7)} ${padL("stallE", 7)} ${padL("ovfl", 6)}  built`);
  for (const r of runs) {
    const e = r.end;
    console.log(`  ${pad(r.strategy + (r.profile !== "balanced" ? "/" + r.profile : ""), 24)} ${padL(e.econ.toFixed(1), 8)} ${padL(e.mInc.toFixed(1), 6)} ${padL(e.eInc.toFixed(1), 7)} ${padL(e.bp, 5)} ${padL(Math.round(e.metal), 6)} ${padL(Math.round(e.energy), 7)} ${padL(e.stallMetal.toFixed(0) + "s", 7)} ${padL(e.stallEnergy.toFixed(0) + "s", 7)} ${padL(Math.round(e.overflowM + e.overflowE / 70), 6)}  ${countsStr(e.counts)}`);
  }
  const real = runs.find(r => r.real && r.real.known.income);
  if (real) {
    const rm = real.real;
    console.log(`  ${pad("(reality)", 24)} ${padL((rm.mIncome + rm.eIncome / 70).toFixed(1), 8)} ${padL(rm.mIncome.toFixed(1), 6)} ${padL(rm.eIncome.toFixed(1), 7)} ${padL(rm.bpAvail ?? "—", 5)} ${padL(Math.round(rm.metal), 6)} ${padL(Math.round(rm.energy), 7)}`);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  let game = null, teamID = null;
  if (!args.fresh) {
    if (!args.source) throw new Error("pass a game source (jsonl | demo | archive index) or --fresh");
    game = await P.parseSource(args.source, { every: args.every, until: args.at + args.horizon + args.every * 2 });
    teamID = P.findTeam(game, args.team);
    if (teamID == null) throw new Error(`--team required; teams: ${[...game.teams].map(([id, t]) => `${id}=${t.name}`).join(", ")}`);
    console.log(`\nBAR Build Strategizer — ${game.map || "?"}  [${game.source}] ${path.basename(game.path)} · team ${teamID} ${game.teams.get(teamID).name}`);
  } else {
    console.log(`\nBAR Build Strategizer — fresh start (no game; synthetic mex spots)`);
  }
  const specs = args.compare || [args.strategy];
  const runs = [];
  for (const spec of specs) {
    let strategy = spec, profile = args.profile;
    if (spec.includes("/")) [strategy, profile] = spec.split("/");
    if (strategy === "replay" && !game) continue;
    const r = runStrategy(game, teamID, { at: args.at, horizon: args.horizon, strategy, profile, dt: args.dt });
    runs.push(r);
    if (!args.compare) printRun(r, `Decisions from ${mmss(r.start.time)} for ${args.horizon}s`);
  }
  if (args.compare) { printCompare(runs); }
  if (args.json) {
    fs.writeFileSync(args.json, JSON.stringify(runs.map(r => ({ strategy: r.strategy, profile: r.profile, start: r.start, end: r.end, log: r.log, completions: r.completions })), null, 1));
    console.log(`\nwrote ${args.json}`);
  }
}

module.exports = { FLOWS, PROFILES, RULES, situation, ecoRuleCandidates, makeStrategy, makeDecider, runStrategy, summarize, canMake };

if (require.main === module) main().catch(e => { console.error("✘ " + (e.stack || e.message)); process.exit(1); });

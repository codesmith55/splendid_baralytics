// eco_engine.mjs — first-person economy state engine.
//
// Models the LOCAL player's economy from their own perspective at one moment:
// stockpiles, storage caps, income sources, and build-power sources each tagged
// high or low priority. From a state it enumerates the rule-cascade option subset
// (see eco_advisor.mjs / bar_economy.md) and simulates each forward to find
// breakeven crossovers between builds.
//
// ── The priority drain order (the point of this engine) ───────────────────────
// Each tick, resources drain in this order:
//   1. generators produce (solar fixed, wind at current wind value, mex pending step 3)
//   2. HIGH priority builders spend (throttled to what's available)
//   3. mex energy upkeep is paid — any mex that cannot pay its ~3 e/s produces
//      NOTHING this tick (a stalled mex loses its metal income entirely)
//   4. metal income lands from non-stalled mexes
//   5. LOW priority builders spend from what remains
//   6. stockpiles clamp to storage caps
//
// This captures the trap the rules warn about: queueing construction at high
// priority during an energy squeeze can starve the (so cheap!) 3 e/s mex upkeep
// and bleed metal income that no build is worth. The same build queued at LOW
// priority lets the mexes drink first and merely builds slower.
//
// Engine-accuracy note: real Recoil allocates upkeep proportionally rather than
// by strict ordering, but the strict order makes the failure mode legible and
// matches how players reason about the priority toggle.
//
// Usage:
//   const state = createState({ mexes: 3, solars: 3, winds: 0, builders: [
//     { name: "commander", bp: 300, priority: "high" } ]});
//   const r = simulateBuild(state, "wind", { priority: "high", wind: 14 });
//   const cmp = compareOptions(state, { wind: 14, horizonSec: 240 });

export const ENERGY_PER_METAL = 70;

// Canonical T1 build targets (BAR ~2025 values; override via params.units).
export const UNITS = {
  wind:      { m: 40,  e: 175,  bp: 1600, gives: { windGen: 1 } },
  solar:     { m: 155, e: 0,    bp: 2600, gives: { ePerSec: 20 } },
  advSolar:  { m: 370, e: 0,    bp: 8200, gives: { ePerSec: 75 } },
  mex:       { m: 50,  e: 500,  bp: 1800, gives: { mex: 1 } },
  conTurret: { m: 230, e: 3200, bp: 5300, gives: { builderBp: 200 } },
  worker:    { m: 110, e: 1600, bp: 3450, gives: { builderBp: 80, ePerSec: 7 } },
  eStorage:  { m: 230, e: 1700, bp: 4100, gives: { storE: 6000 } },
  converter: { m: 1,   e: 1150, bp: 2600, gives: { converter: 1 } },  // eats 70 e/s → +1 m/s when E surplus
  // reclaimSolar is a pseudo-build: returns 155 metal over the reclaim time, removes one solar
  reclaimSolar: { m: -155, e: 0, bp: 2600, gives: { ePerSec: -20 } },
};

export const MEX = { mPerSec: 1.8, eUpkeep: 3 };       // per extractor
export const BASE_INCOME = { m: 2, e: 25 };            // commander passive

// ── state ─────────────────────────────────────────────────────────────────────

/**
 * Create a first-person economy state.
 * builders: [{ name, bp, priority: "high"|"low" }] — each source of build power,
 * designated by spend order. Multiple same-priority builders pool their BP.
 */
export function createState({
  metal = 500, energy = 500,
  storM = 1000, storE = 1000,
  mexes = 3, solars = 0, winds = 0, converters = 0,
  extraEPerSec = 0,                       // anything else feeding the grid
  builders = [{ name: "commander", bp: 300, priority: "high" }],
  units = UNITS, mex = MEX, base = BASE_INCOME,
} = {}) {
  return {
    t: 0,
    metal, energy, storM, storE,
    mexes, solars, winds, converters,
    extraEPerSec,
    builders: builders.map(b => ({ ...b })),
    units, mex, base,
    // running diagnostics
    mexStallSec: 0,          // total mex-seconds spent stalled
    metalLostToStalls: 0,    // metal income lost to starved mex upkeep
    converted: 0,            // metal gained via converters
    reclaimed: 0,            // metal returned by reclaiming (spendable, but not "generated")
    totalGenerated: 0,       // cumulative metal-equiv generated (pre-clamp) — the comparison metric;
                             // stock alone saturates at storage caps and makes every option tie
    overflowLost: 0,         // metal-equiv lost to full storage (locally wasted; goes to team in BAR)
  };
}

// ── tick ──────────────────────────────────────────────────────────────────────

/**
 * Advance one step of dt seconds. `job` (optional): { unit, priority, progress }
 * — the active build. wind = current wind value (e/s per turbine).
 * Returns flags: { mexesStalled, jobThrottled }.
 */
export function tick(state, dt, job = null, wind = 10) {
  const u = state.units;

  // 1. generation (mex metal handled in step 4, after upkeep settles)
  let eIn = state.base.e + state.solars * 20 + state.winds * Math.max(0, wind) + state.extraEPerSec;
  state.energy += eIn * dt;
  state.totalGenerated += (eIn * dt) / ENERGY_PER_METAL;

  // 2 & 5. builder spending, high first, low after mex upkeep
  let jobThrottled = false;
  const spend = (priority) => {
    if (!job || job.priority !== priority || job.done) return;
    const def = u[job.unit];
    const bp = state.builders.filter(b => b.priority === priority).reduce((s, b) => s + b.bp, 0);
    if (bp <= 0) return;
    const wantFrac = Math.min((bp * dt) / def.bp, 1 - job.progress);   // fraction of total build this tick
    const wantM = Math.max(0, def.m) * wantFrac;
    const wantE = Math.max(0, def.e) * wantFrac;
    // throttle to available stock (income already landed for this tick where applicable)
    const frac = Math.min(
      1,
      wantM > 0 ? state.metal  / wantM : 1,
      wantE > 0 ? state.energy / wantE : 1,
    );
    if (frac < 1) jobThrottled = true;
    state.metal  -= wantM * frac;
    state.energy -= wantE * frac;
    // reclaim pseudo-build returns metal as it progresses. Tracked in `reclaimed`,
    // not `totalGenerated` — it is returned investment, not generation (see
    // eco_advisor reclaim-discounting rule) — but it IS spendable value, so
    // _netWorth counts it when ranking options.
    if (def.m < 0) { const ret = -def.m * wantFrac * frac; state.metal += ret; state.reclaimed += ret; }
    job.progress += wantFrac * frac;
    if (job.progress >= 0.9999) { job.progress = 1; job.done = true; }
  };

  spend("high");                                        // 2. high priority drinks first

  // 3. mex upkeep — strict order: whatever energy is left feeds the extractors
  const upkeepNeed = state.mexes * state.mex.eUpkeep * dt;
  let mexesStalled = 0;
  let payable = state.mexes;
  if (upkeepNeed > 0 && state.energy < upkeepNeed) {
    payable = Math.floor(state.energy / (state.mex.eUpkeep * dt));   // whole mexes only
    mexesStalled = state.mexes - payable;
  }
  state.energy -= payable * state.mex.eUpkeep * dt;

  // 4. metal income from non-stalled mexes + base
  const mIn = (state.base.m + payable * state.mex.mPerSec) * dt;
  state.metal += mIn;
  state.totalGenerated += mIn;
  if (mexesStalled > 0) {
    state.mexStallSec       += mexesStalled * dt;
    state.metalLostToStalls += mexesStalled * state.mex.mPerSec * dt;
  }

  spend("low");                                         // 5. low priority gets leftovers

  // converters: eat energy above a reserve, 70e → 1m, capped at 1 m/s per converter
  if (state.converters > 0 && state.energy > state.storE * 0.5) {
    const eAvail = state.energy - state.storE * 0.5;
    const eEat = Math.min(eAvail, state.converters * ENERGY_PER_METAL * dt);
    state.energy -= eEat;
    const mMade = eEat / ENERGY_PER_METAL;
    state.metal += mMade;
    state.converted += mMade;
  }

  // 6. clamp (overflow is locally wasted — track what the caps cost us)
  const overM = Math.max(0, state.metal  - state.storM);
  const overE = Math.max(0, state.energy - state.storE);
  state.overflowLost += overM + overE / ENERGY_PER_METAL;
  state.metal  = Math.min(Math.max(0, state.metal),  state.storM);
  state.energy = Math.min(Math.max(0, state.energy), state.storE);
  state.t += dt;

  return { mexesStalled, jobThrottled };
}

/** Apply a completed unit's `gives` to the state (new income/storage/builders). */
export function applyCompletion(state, unitKey) {
  const g = state.units[unitKey]?.gives ?? {};
  if (g.windGen)    state.winds      += g.windGen;
  if (g.mex)        state.mexes      += g.mex;
  if (g.converter)  state.converters += g.converter;
  if (g.storE)      state.storE      += g.storE;
  if (g.ePerSec)    state.extraEPerSec += g.ePerSec;   // solar/worker passive e (solar via extraEPerSec keeps solars count for reclaim separate)
  if (g.builderBp)  state.builders.push({ name: unitKey, bp: g.builderBp, priority: "low" });
  if (unitKey === "solar")        { state.solars++; state.extraEPerSec -= 20; } // counted via solars, undo extra
  if (unitKey === "reclaimSolar") { state.solars = Math.max(0, state.solars - 1); state.extraEPerSec += 20; } // undo the -20 double count
}

// ── simulate one build from here ──────────────────────────────────────────────

/**
 * Run the engine until `unitKey` completes (or maxSec). Returns completion time,
 * stall diagnostics, and the end state — the player's economy as it would look.
 */
export function simulateBuild(startState, unitKey, {
  priority = "high", wind = 10, dt = 1 / 30, maxSec = 600, windSeries = null,
} = {}) {
  const state = structuredClone(startState);
  // the priority designation retags the build-power sources working this job:
  // it decides whether they drain before or after mex upkeep
  state.builders = state.builders.map(b => ({ ...b, priority }));
  const job = { unit: unitKey, priority, progress: 0, done: false };
  let throttledSec = 0;
  while (!job.done && state.t < maxSec) {
    const w = windSeries ? _windAt(windSeries, state.t, wind) : wind;
    const f = tick(state, dt, job, w);
    if (f.jobThrottled) throttledSec += dt;
  }
  if (job.done) applyCompletion(state, unitKey);
  return {
    unit: unitKey, priority,
    completionSec: job.done ? round(state.t, 1) : null,
    throttledSec:  round(throttledSec, 1),
    mexStallSec:   round(state.mexStallSec, 1),
    metalLostToStalls: round(state.metalLostToStalls, 1),
    endState: state,
  };
}

// ── option comparison: the rule-cascade subset, simulated forward ─────────────

/**
 * From this state, pick the rule-cascade option subset, simulate each forward
 * (both priorities where it matters), and rank by metal-equivalent net worth at
 * the horizon. Crossovers report when one option's worth overtakes another's.
 */
export function compareOptions(startState, {
  wind = 10, windSeries = null, horizonSec = 240, dt = 1 / 30,
  candidates = null,            // override; default = rule-cascade subset for this state
  excessFill = 0.70, starvedFill = 0.15,
} = {}) {
  const cands = candidates ?? optionSubset(startState, excessFill, starvedFill);

  const runs = [];
  for (const unitKey of cands) {
    for (const priority of ["high", "low"]) {
      const series = _worthSeries(startState, unitKey, { priority, wind, windSeries, horizonSec, dt });
      runs.push({ unit: unitKey, priority, ...series });
      // low-priority pass only matters when high stalls something; skip dup if identical
      if (priority === "high" && series.mexStallSec === 0) break;
    }
  }
  // baseline: build nothing
  runs.push({ unit: "idle", priority: "-", ..._worthSeries(startState, null, { wind, windSeries, horizonSec, dt }) });

  runs.sort((a, b) => b.finalWorth - a.finalWorth);
  const best = runs[0];
  const recordStepSec = Math.max(1, Math.round(0.5 / dt)) * dt;   // matches _worthSeries recording cadence
  const crossovers = runs.slice(1).map(r => ({
    vs: r.unit + "/" + r.priority,
    overtakenAtSec: _crossover(best.worth, r.worth, recordStepSec),
    finalGap: round(best.finalWorth - r.finalWorth, 1),
  }));

  return {
    stateSnapshot: _snapshot(startState),
    candidates: cands,
    ranked: runs.map(r => ({
      unit: r.unit, priority: r.priority,
      completionSec: r.completionSec, finalWorth: r.finalWorth,
      mexStallSec: r.mexStallSec, metalLostToStalls: r.metalLostToStalls,
      warning: r.metalLostToStalls > 0
        ? `high-priority build starved ${r.mexStallSec}s of mex upkeep (-${r.metalLostToStalls} metal income) — queue LOW priority instead`
        : null,
    })),
    best: { unit: best.unit, priority: best.priority },
    crossovers,
  };
}

/**
 * Project one option (or null = idle) from a state to a horizon.
 * Returns finalWorth and the metal-equiv income rate near the horizon —
 * the two numbers needed to convert worth gaps into LOST SECONDS:
 *   lostSec = (worthBetter - worthWorse) / incomeRateEnd
 * i.e. how much later the worse path reaches the better path's position.
 */
export function projectOption(startState, unitKey, {
  priority = "high", wind = 10, windSeries = null, horizonSec = 90, dt = 1 / 30,
} = {}) {
  const state = structuredClone(startState);
  if (unitKey) state.builders = state.builders.map(b => ({ ...b, priority }));
  const job = unitKey ? { unit: unitKey, priority, progress: 0, done: false } : null;
  let worthAtMinus10 = null;
  while (state.t < horizonSec) {
    const w = windSeries ? _windAt(windSeries, state.t, wind) : wind;
    tick(state, dt, job && job.done !== "applied" && !job.done ? job : null, w);
    if (job?.done === true) { applyCompletion(state, unitKey); job.done = "applied"; }
    if (worthAtMinus10 == null && state.t >= horizonSec - 10) worthAtMinus10 = _netWorth(state);
  }
  const finalWorth = _netWorth(state);
  return {
    finalWorth: round(finalWorth, 1),
    incomeRateEnd: round(Math.max(0.1, (finalWorth - (worthAtMinus10 ?? finalWorth)) / 10), 2),
    completed: job ? job.done === "applied" : null,
  };
}

/** The rule-cascade subset of sensible options for this state (advisor logic). */
export function optionSubset(state, excessFill = 0.70, starvedFill = 0.15) {
  const mFill = state.storM > 0 ? state.metal / state.storM : 0;
  const eFill = state.storE > 0 ? state.energy / state.storE : 0;
  const m = mFill > excessFill ? "excess" : mFill < starvedFill ? "starved" : "ok";
  const e = eFill > excessFill ? "excess" : eFill < starvedFill ? "starved" : "ok";

  if (m === "excess" && e === "excess")  return ["conTurret", "worker", "eStorage", "wind"];
  if (m === "excess" && e === "starved") return ["solar", "wind"];                       // solar = only safe build; wind shown for the gap
  if (m === "starved" && e !== "starved" && state.solars > 0)
                                          return ["reclaimSolar", "eStorage", "advSolar"];
  if (m === "starved" && e === "excess") return ["converter", "eStorage"];
  return ["wind", "solar"];                                                              // default; solar = the slow comparator
}

// ── internals ─────────────────────────────────────────────────────────────────

// Simulate to horizon (building unitKey first if given, idle after), recording
// metal-equivalent net worth: stock + income capitalized as cumulative generation.
function _worthSeries(startState, unitKey, { priority = "high", wind, windSeries, horizonSec, dt }) {
  const state = structuredClone(startState);
  if (unitKey) state.builders = state.builders.map(b => ({ ...b, priority }));
  const job = unitKey ? { unit: unitKey, priority, progress: 0, done: false } : null;
  const worth = [];
  let completionSec = null;
  const step = Math.max(1, Math.round(0.5 / dt));      // record every ~0.5s
  for (let i = 0; state.t < horizonSec; i++) {
    const w = windSeries ? _windAt(windSeries, state.t, wind) : wind;
    tick(state, dt, job && !job.done ? job : null, w);
    if (job?.done && completionSec == null) { completionSec = round(state.t, 1); applyCompletion(state, unitKey); job.done = "applied"; }
    if (i % step === 0) worth.push(round(_netWorth(state), 1));
  }
  return {
    worth, finalWorth: round(_netWorth(state), 1), completionSec,
    mexStallSec: round(state.mexStallSec, 1), metalLostToStalls: round(state.metalLostToStalls, 1),
  };
}

// Net worth in metal-equivalent: cumulative generation minus overflow waste.
// Stock alone saturates at storage caps and makes options tie; cumulative income
// keeps rising after a build completes, which is what creates crossovers.
// Stall losses never enter totalGenerated (stalled mexes generate nothing).
function _netWorth(state) {
  return state.totalGenerated + state.reclaimed - state.overflowLost;
}

function _crossover(seriesA, seriesB, stepSec) {
  // first index where A pulls ahead of B for good
  for (let i = 0; i < Math.min(seriesA.length, seriesB.length); i++) {
    if (seriesA[i] > seriesB[i]) return round(i * stepSec, 1);
  }
  return null;
}

function _windAt(series, t, fallback) {
  let v = fallback;
  for (const s of series) { if (s.second > t) break; v = s.value; }
  return v;
}

function _snapshot(s) {
  return {
    t: s.t, metal: round(s.metal), energy: round(s.energy),
    mFill: round(s.storM > 0 ? s.metal / s.storM : 0, 2),
    eFill: round(s.storE > 0 ? s.energy / s.storE : 0, 2),
    mexes: s.mexes, solars: s.solars, winds: s.winds, converters: s.converters,
    builders: s.builders.map(b => `${b.name}(${b.bp}bp/${b.priority})`),
  };
}

function round(x, d = 0) { const p = 10 ** d; return Math.round((x + Number.EPSILON) * p) / p; }

// eco_advisor.mjs — moment-by-moment economic rule advisor for one player.
//
// Walks the replay in 15s intervals from the PLAYER'S PERSPECTIVE: reconstructs
// what they could see (stockpiles, income, wind, their own structures), applies
// the economic rule cascade from bar-calc/build-order-calc/bar_economy.md, and
// emits the response that "would have made sense". Then compares against what
// they actually completed next, producing a followed/deviated verdict per interval.
//
// ── Rule cascade (in evaluation order) ────────────────────────────────────────
//  R1  M:excess + E:excess              → BUILD_BP        (con turret = bp flavor, worker = energy flavor)
//      ...and E_STORAGE if storages < conTurrets/4 (the 1:4 rule)
//  R2  M:excess + E:starved             → BUILD_SOLAR     (only thing the economy can safely build)
//  R3  M:starved + E:ok|excess + solars → RECLAIM_SOLARS  (+ e-storage; adv solar = slow comparator)
//  R4  M:starved + E:excess  + no solars→ ENERGY_CONVERTERS (bleed E past storage into M)
//  R5  default                          → BUILD_WIND      (solar is just a proxy for more BP to build wind)
//
// ── State thresholds ──────────────────────────────────────────────────────────
//  excess  = stockpile fill > excessFill (default 0.70) — bar is visibly filling
//  starved = stockpile fill < starvedFill (default 0.15) — bar is visibly empty
//  Fill = metalCurrent/metalStorage. Storage caps come from extra_stat_update when
//  present (gex.lua ≥ 2026-06-09); for older actions.json the caps are ESTIMATED:
//  1000 base (BAR starting storage) + sum of metalStorage/energyStorage def fields
//  of every structure the player owns (estor +6000e, mstor +3000m, solar +50e, ...).
//  summary.dataMode reports which path was used.
//
// ── Breakeven reference (TROI = (M×70 + E) / output, in energy-seconds) ───────
//  solar  TROI = 155×70/20         = 542.5 s   (fixed)
//  wind   TROI = (40×70+175)/wind  = 2975/wind (213 s @ wind 14 — dominates on ATG)
//  conv   EPM  = 70 E → 1 M        (not ROI; converts surplus, only sane when E overflows)
// Wind direction note: windDelta (change vs previous interval) is reported as
// perceived trend — magnitude of a moving 2D vector, so a falling value is a hint,
// not a guarantee, of continued decline.

import { buildDefIndex } from "../classify.mjs";
import { createState, projectOption } from "../sim/eco_engine.mjs";

export const meta = {
  id: "eco_advisor",
  title: "Economic rule advisor — what made sense at each moment, vs what happened",
  granularity: "team-per-interval",
  inputs: ["unit_def", "unit_created", "unit_killed", "wind_update", "extra_stat_update"],
};

const RECLAIM_WEAPON_ID = -12;
const ENERGY_PER_METAL  = 70;
const SOLAR_TROI        = 155 * 70 / 20;     // 542.5 energy-seconds
const WIND_TROI_NUM     = 40 * 70 + 175;     // 2975; divide by current wind for TROI

export function compute(ctx, teamID, params = {}) {
  const { byAction, defMap } = ctx;
  const fps          = params.fps          ?? ctx.sampling?.fps ?? 30;
  const windowSec    = params.windowSec    ?? 360;
  const intervalSec  = params.intervalSec  ?? 15;
  const excessFill   = params.excessFill   ?? 0.70;
  const starvedFill  = params.starvedFill  ?? 0.15;
  // bar_economy.md frames the rules as COURSE CORRECTIONS, not opening guidance —
  // the first intervals follow a scripted build order (mex/solar/factory) and are
  // marked "opening" rather than judged. Default 4 intervals = first 60s.
  const graceIntervals = params.graceIntervals ?? 4;

  const intervalFrames = intervalSec * fps;
  const intervalCount  = Math.ceil((windowSec * fps) / intervalFrames);
  const windowFrames   = intervalCount * intervalFrames;

  const defIndex = buildDefIndex(defMap, params);

  const created = (byAction.get("unit_created") ?? [])
    .filter(e => e.teamID === teamID && e.frame <= windowFrames + intervalFrames) // +1 interval lookahead for verdicts
    .sort((a, b) => a.frame - b.frame);
  const killed  = (byAction.get("unit_killed") ?? [])
    .filter(e => e.teamID === teamID && e.frame <= windowFrames + intervalFrames);
  const windEvents = (byAction.get("wind_update") ?? []).sort((a, b) => a.frame - b.frame);
  const extra      = (byAction.get("extra_stat_update") ?? []).filter(e => e.teamID === teamID);

  // ── inventory ledger: what the player owns at any frame ────────────────────
  // kind: mex | solar | advSolar | wind | converter | eStorage | mStorage | conTurret | worker | factory
  const inventoryEvents = [];
  for (const e of created) {
    const defRaw = defMap.get(e.defID);
    const kind = _kind(defRaw);
    const storM = num(defRaw?.metalStorage), storE = num(defRaw?.energyStorage);
    if (kind || storM > 0 || storE > 0) inventoryEvents.push({ frame: e.frame, kind, delta: +1, defName: e.defName, storM, storE });
  }
  for (const e of killed) {
    const defRaw = defMap.get(e.defID);
    const kind = _kind(defRaw);
    const storM = num(defRaw?.metalStorage), storE = num(defRaw?.energyStorage);
    if (kind || storM > 0 || storE > 0) inventoryEvents.push({
      frame: e.frame, kind, delta: -1, defName: e.defName, storM, storE,
      selfReclaim: e.weaponDefID === RECLAIM_WEAPON_ID && e.attackerTeam === e.teamID,
    });
  }
  inventoryEvents.sort((a, b) => a.frame - b.frame);

  // ── walk intervals ───────────────────────────────────────────────────────────
  const inv = { mex: 0, solar: 0, advSolar: 0, wind: 0, converter: 0, eStorage: 0, mStorage: 0, conTurret: 0, worker: 0, factory: 0 };
  const BASE_STORAGE = params.baseStorage ?? 1000;  // BAR starting storage (observed at frame 0)
  let estStorM = BASE_STORAGE, estStorE = BASE_STORAGE;
  let invIdx = 0;
  const intervals = [];

  for (let i = 0; i < intervalCount; i++) {
    const startFrame = i * intervalFrames;
    const endFrame   = startFrame + intervalFrames;

    // advance inventory to END of this interval (player's view entering the next decision)
    const reclaimedThisInterval = [];
    while (invIdx < inventoryEvents.length && inventoryEvents[invIdx].frame <= endFrame) {
      const ev = inventoryEvents[invIdx++];
      if (ev.kind) inv[ev.kind] += ev.delta;
      estStorM += ev.delta * ev.storM;
      estStorE += ev.delta * ev.storE;
      if (ev.selfReclaim) reclaimedThisInterval.push(ev.defName);
    }

    // wind at interval start (nearest sample at or before)
    let wind = null, windPrev = null;
    for (const w of windEvents) {
      if (w.frame > startFrame) break;
      windPrev = wind; wind = w.value;
    }
    const windDelta = wind != null && windPrev != null ? round(wind - windPrev, 2) : null;

    // economy snapshot from extra_stat_update at interval boundary
    const es = extra.find(e => e.frame >= startFrame && e.frame < endFrame) ?? null;
    const bpAvail = es?.buildPowerAvailable ?? null;
    // prefer real storage caps (new gex.lua); fall back to estimated caps from inventory
    const storM = es?.metalStorage  > 0 ? es.metalStorage  : estStorM;
    const storE = es?.energyStorage > 0 ? es.energyStorage : estStorE;
    const mFill = es?.metalCurrent  != null && storM > 0 ? es.metalCurrent  / storM : null;
    const eFill = es?.energyCurrent != null && storE > 0 ? es.energyCurrent / storE : null;

    const mState = _resState(mFill, excessFill, starvedFill);
    const eState = _resState(eFill, excessFill, starvedFill);

    // ── rule cascade ──────────────────────────────────────────────────────────
    const advice = _advise(mState, eState, inv, wind, windDelta);

    // ── actual response: notable completions in the NEXT interval ─────────────
    const responses = created
      .filter(e => e.frame > endFrame && e.frame <= endFrame + intervalFrames)
      .map(e => ({ defName: e.defName, kind: _kind(defMap.get(e.defID)), bucket: defIndex.get(e.defID)?.bucket ?? "other" }));
    const verdict = i < graceIntervals ? "opening" : _verdict(advice, responses, reclaimedThisInterval);

    // ── lost seconds vs the preferable path ───────────────────────────────────
    // Simulate the advised option and the actual choice from the SAME calibrated
    // state; lostSec = worth gap at horizon / income rate = how much later the
    // actual path reaches where the advised path got. 0 when they match.
    const lostSec = (verdict === "opening" || advice.rule === "NO_DATA" || es?.metalIncome == null)
      ? null
      : _lostSeconds({
          es, inv, wind, advice, responses, reclaimedThisInterval, bpAvail,
          horizonSec: params.lossHorizonSec ?? 90,
        });

    intervals.push({
      i,
      startSec: round(startFrame / fps, 1),
      endSec:   round(endFrame / fps, 1),
      // what the player could see
      wind:      wind  != null ? round(wind, 2) : null,
      windDelta,                                   // perceived trend, not a guarantee
      metalFill:  mFill != null ? round(mFill, 3) : null,
      energyFill: eFill != null ? round(eFill, 3) : null,
      metalCurrent:  es?.metalCurrent  != null ? round(es.metalCurrent)  : null,
      energyCurrent: es?.energyCurrent != null ? round(es.energyCurrent) : null,
      storageM: round(storM), storageE: round(storE),
      storageEstimated: !(es?.metalStorage > 0),
      metalIncome:  es?.metalIncome  ?? null,
      energyIncome: es?.energyIncome ?? null,
      mState, eState,                              // "excess" | "ok" | "starved" | "unknown"
      inventory: { ...inv },
      // the advisor's call
      rule:    advice.rule,
      advice:  advice.text,
      breakeven: advice.breakeven,
      // what actually happened
      actualBuilds: responses.map(r => r.defName),
      selfReclaimed: reclaimedThisInterval,
      verdict,                                     // qualitative label: "followed" | "deviated" | "idle" | "opening" | "no_data"
      lostSec,                                     // seconds the actual choice trails the advised path (the real metric)
    });
  }

  // ── summary: lost seconds toward the objective, not a compliance % ──────────
  const costed = intervals.filter(iv => iv.lostSec != null);
  const totalLostSec = round(costed.reduce((s, iv) => s + iv.lostSec, 0), 1);
  const worstMoments = costed
    .filter(iv => iv.lostSec > 0)
    .sort((a, b) => b.lostSec - a.lostSec)
    .slice(0, 3)
    .map(iv => ({
      time: `${iv.startSec}-${iv.endSec}s`,
      lostSec: iv.lostSec,
      advised: iv.rule,
      actual: iv.actualBuilds.slice(0, 3).join(",") || (iv.selfReclaimed.length ? "reclaim" : "idle"),
    }));
  const ruleCounts = {};
  for (const iv of intervals) ruleCounts[iv.rule] = (ruleCounts[iv.rule] ?? 0) + 1;

  return {
    metricId: "eco_advisor",
    teamID, windowSec, intervalSec,
    params: { excessFill, starvedFill, graceIntervals },
    intervals,
    summary: {
      // Per-interval losses are independent 90s projections from each decision
      // point, so the sum over overlapping windows is an upper-bound estimate.
      totalLostSec,
      costedIntervals: costed.length,
      worstMoments,
      ruleCounts,
      dataMode: extra.some(e => e.metalStorage != null) ? "full"
        : extra.some(e => e.metalCurrent != null) ? "estimated_storage"
        : "degraded_no_economy_fields",
    },
  };
}

// ── the rule cascade ──────────────────────────────────────────────────────────

function _advise(mState, eState, inv, wind, windDelta) {
  const windTroi  = wind > 0 ? round(WIND_TROI_NUM / wind, 0) : null;
  const breakeven = {
    solarTroiSec: round(SOLAR_TROI, 1),
    windTroiSec:  windTroi,                                  // null when becalmed
    windBeatsSolar: windTroi != null ? windTroi < SOLAR_TROI : false,
    converterRate: `${ENERGY_PER_METAL}E -> 1M`,
  };
  const trend = windDelta == null ? "" :
    windDelta > 1  ? " Wind trending up."  :
    windDelta < -1 ? " Wind trending down (indicator only — vector magnitude can reverse)." : "";

  if (mState === "unknown" || eState === "unknown") {
    return { rule: "NO_DATA", text: "No stockpile data in this actions.json (pre-storage-fields gex.lua). Inventory context only.", breakeven };
  }

  // R1 — both overflowing: convert surplus into future flexibility
  if (mState === "excess" && eState === "excess") {
    const wantStorage = inv.eStorage < Math.floor(inv.conTurret / 4) || (inv.conTurret >= 2 && inv.eStorage === 0);
    return {
      rule: "BUILD_BP",
      text: "Metal and energy both overflowing — add build power. Con turret (BP flavor) or worker (energy flavor)."
        + (wantStorage ? " Also fit an energy storage (1:4 storage-to-turret rule)." : "")
        + trend,
      breakeven,
    };
  }

  // R2 — metal piling up, energy empty: solar is the only safe spend
  if (mState === "excess" && eState === "starved") {
    return {
      rule: "BUILD_SOLAR",
      text: "Metal overflowing with no energy — basic solar is the only thing the economy can safely build "
        + `(costs 0 energy, TROI ${SOLAR_TROI}s).` + trend,
      breakeven,
    };
  }

  // R3 — no metal but energy is fine: liquidate solars back into metal
  if (mState === "starved" && eState !== "starved" && (inv.solar > 0 || inv.advSolar > 0)) {
    return {
      rule: "RECLAIM_SOLARS",
      text: `No metal, energy is ${eState} — reclaim solars (100% metal back) now that wind carries the grid. `
        + "Add energy storage to ride wind dips; advanced solar only as the slow APM-saving comparator." + trend,
      breakeven,
    };
  }

  // R4 — no metal, energy overflowing, nothing left to reclaim: convert
  if (mState === "starved" && eState === "excess" && inv.solar === 0 && inv.advSolar === 0) {
    return {
      rule: "ENERGY_CONVERTERS",
      text: `No metal and energy past storage with no solars left to eat — energy converters bleed the overflow at ${ENERGY_PER_METAL}E per metal.` + trend,
      breakeven,
    };
  }

  // R5 — default: wind
  return {
    rule: "BUILD_WIND",
    text: "Default: build wind"
      + (windTroi != null ? ` (TROI ${windTroi}s at current wind ${round(wind,1)} vs solar ${SOLAR_TROI}s).` : ".")
      + " Solar is just a proxy for more BP to build wind." + trend,
    breakeven,
  };
}

// ── verdict: did the next interval's builds match the advice? ─────────────────

const RULE_MATCHES = {
  BUILD_BP:          kinds => kinds.includes("conTurret") || kinds.includes("worker") || kinds.includes("eStorage"),
  BUILD_SOLAR:       kinds => kinds.includes("solar") || kinds.includes("advSolar"),
  BUILD_WIND:        kinds => kinds.includes("wind"),
  ENERGY_CONVERTERS: kinds => kinds.includes("converter"),
  RECLAIM_SOLARS:    null, // judged on reclaim events, not builds
};

function _verdict(advice, responses, reclaimedThisInterval) {
  if (advice.rule === "NO_DATA") return "no_data";
  if (advice.rule === "RECLAIM_SOLARS") {
    return reclaimedThisInterval.length > 0 ? "followed" : (responses.length === 0 ? "idle" : "deviated");
  }
  if (responses.length === 0) return "idle";
  const kinds = responses.map(r => r.kind).filter(Boolean);
  const match = RULE_MATCHES[advice.rule];
  return match && match(kinds) ? "followed" : "deviated";
}

// ── lost-seconds estimator ────────────────────────────────────────────────────

const RULE_TO_UNIT = {
  BUILD_WIND: "wind", BUILD_SOLAR: "solar", BUILD_BP: "conTurret",
  ENERGY_CONVERTERS: "converter", RECLAIM_SOLARS: "reclaimSolar",
};
// eco kinds the engine can simulate as "the actual choice"
const SIMULATABLE = new Set(["wind", "solar", "advSolar", "mex", "converter", "eStorage", "conTurret", "worker"]);

function _lostSeconds({ es, inv, wind, advice, responses, reclaimedThisInterval, bpAvail, horizonSec }) {
  const advisedUnit = RULE_TO_UNIT[advice.rule];
  if (!advisedUnit) return null;

  // actual choice → engine unit (first simulatable eco build; reclaim if they reclaimed;
  // non-eco builds (military/factory) contribute 0 to the eco objective → idle)
  const actualUnit = reclaimedThisInterval.length > 0 ? "reclaimSolar"
    : responses.map(r => r.kind).find(k => SIMULATABLE.has(k)) ?? null;
  if (actualUnit === advisedUnit) return 0;

  // calibrated engine state: measured stockpiles/storage/bp, and income matched to
  // the measured rates (mex yield + residual energy) so the sim starts from reality
  const w = wind ?? 10;
  const mexYield = inv.mex > 0 ? Math.max(0.1, (es.metalIncome - 2) / inv.mex) : 1.8;
  const knownE   = 25 + inv.solar * 20 + inv.advSolar * 75 + inv.wind * w;
  const state = createState({
    metal: es.metalCurrent, energy: es.energyCurrent,
    storM: es.metalStorage ?? 1000, storE: es.energyStorage ?? 1000,
    mexes: inv.mex, solars: inv.solar, winds: inv.wind, converters: inv.converter,
    extraEPerSec: Math.max(0, (es.energyIncome ?? knownE) - knownE),
    builders: [{ name: "pool", bp: Math.max(80, bpAvail ?? 300), priority: "high" }],
    mex: { mPerSec: mexYield, eUpkeep: 3 },
  });

  const adv = projectOption(state, advisedUnit, { wind: w, horizonSec });
  const act = projectOption(state, actualUnit,  { wind: w, horizonSec });   // null = idle
  const gap = adv.finalWorth - act.finalWorth;
  if (gap <= 0) return 0;                       // actual matched or beat the advice — no loss
  return round(gap / adv.incomeRateEnd, 1);     // seconds the actual path trails the advised path
}

// ── resource state classifier ─────────────────────────────────────────────────

function _resState(fill, excessFill, starvedFill) {
  if (fill == null) return "unknown";
  if (fill > excessFill)  return "excess";
  if (fill < starvedFill) return "starved";
  return "ok";
}

// ── unit kind classifier ──────────────────────────────────────────────────────

function _kind(defRaw) {
  if (!defRaw) return null;
  if (defRaw.isMetalExtractor === true)            return "mex";
  if (num(defRaw.windGenerator) > 0)               return "wind";
  if (num(defRaw.energyConversionCapacity) > 0)    return "converter";
  if (defRaw.isFactory === true)                   return "factory";
  const eOut = num(defRaw.energyProduction) + Math.max(0, -num(defRaw.energyUpkeep));
  if (eOut >= 60)                                  return "advSolar";
  if (eOut > 0)                                    return "solar";
  if (num(defRaw.energyStorage) >= 2000 && num(defRaw.buildPower) === 0) return "eStorage";
  if (num(defRaw.metalStorage)  >= 500  && num(defRaw.buildPower) === 0) return "mStorage";
  if (num(defRaw.buildPower) > 0 && defRaw.isBuilder === true) {
    return num(defRaw.speed) > 0 ? "worker" : "conTurret";
  }
  return null;
}

function num(x) { return typeof x === "number" && isFinite(x) ? x : 0; }
function round(x, d = 0) { const p = 10 ** d; return Math.round((x + Number.EPSILON) * p) / p; }

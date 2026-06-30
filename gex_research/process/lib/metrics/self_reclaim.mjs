// self_reclaim.mjs — cumulative self-reclaimed unit value per team, over time.
//
// Self-reclaim = unit_killed where attackerTeam === teamID AND weaponDefID === -12.
// (weaponDefID -12 is Spring/Recoil's internal constant for the reclaim action.)
//
// Value formula: metalCost + energyCost/70  (same as economy_composition default).
// Bucketed using the same classify logic (economy, military, build_power, infrastructure, other).
// Commander (if ever self-reclaimed) is double-counted: build_power + military.
//
// ── Lifetime accounting ────────────────────────────────────────────────────────
// Economy structures (eco bucket):
//   Reclaiming a solar is NOT pure churn. The building produced energy during its
//   lifetime. net_metal_position = lifetimeEnergyValue (the energy generated).
//   The metalCost you get back is just returning what you invested.
//   lifetimeEnergyValue = energyRate × lifetimeSec / 70  (metal-equiv).
//
// Military units (military bucket):
//   Reclaiming gives 100% of metalCost back regardless of HP.
//   Letting a unit die produces a wreck worth ~55% of metalCost.
//   reclaimAdvantage = metalCost × 0.45  (max saved vs wreck, if unit was about to die).
//   If the unit was healthy, this is a liquidation (military presence → raw metal, net 0).
//   Distinguishing deathsave from liquidation requires HP-at-reclaim-start — see todo.md.
//
// ── Missing data for full analysis ────────────────────────────────────────────
//   To calculate precise reclaimAdvantage we need HP% when reclaim starts. That requires
//   a new gex.lua event (unit_reclaim_start with UnitHealth). See todo.md.
import { buildDefIndex } from "../classify.mjs";

export const meta = {
  id: "self_reclaim",
  title: "Self-reclaim — cumulative value of own units reclaimed, by category, per team",
  granularity: "team-per-time",
  inputs: ["unit_def", "unit_created", "unit_killed", "start", "end"],
};

const BUCKETS = ["economy", "military", "build_power", "infrastructure", "other"];
// Default BAR wreck percentage: unit becomes a wreck worth ~55% of its metalCost when killed normally.
const WRECK_PCT = 0.55;

export function compute(ctx, params = {}) {
  const { byAction, defMap, meta: m } = ctx;
  const everyFrames = params?.sampling?.everyFrames ?? ctx.sampling?.everyFrames ?? 450;
  const fps         = params?.sampling?.fps         ?? ctx.sampling?.fps         ?? 30;

  const defIndex = buildDefIndex(defMap, params);

  // ---- creation frame index: unitID -> frame ----
  const createFrame = new Map();
  for (const e of byAction.get("unit_created") ?? []) createFrame.set(e.unitID, e.frame);

  // ---- unit_damage summary index: unitID -> {dealt, taken, experience} ----
  // Emitted by gex.lua at unit death (UnitDestroyed), populated by UnitDamagedReplay accumulator.
  // Only present for units that participated in combat. Units eaten before seeing any combat = null.
  const combatStats = new Map();
  for (const e of byAction.get("unit_damage") ?? []) combatStats.set(e.unitID, e);

  // ---- filter for self-reclaim events, sort by frame ----
  const kills = (byAction.get("unit_killed") ?? [])
    .filter(e => e.weaponDefID === -12 && e.attackerTeam != null && e.attackerTeam === e.teamID)
    .sort((a, b) => a.frame - b.frame);

  // ---- per-team event lists ----
  const evByTeam = new Map();
  for (const tm of m.teams) evByTeam.set(tm, []);

  for (const e of kills) {
    const tm  = e.teamID;
    if (!evByTeam.has(tm)) evByTeam.set(tm, []);
    const def    = defIndex.get(e.defID);
    const defRaw = defMap.get(e.defID);
    const bucket = def
      ? (def.isCommander ? "commander" : (def.bucket in _zero() ? def.bucket : "other"))
      : "other";
    const value  = def?.value ?? 0;

    // ── lifetime energy analysis (eco structures) ──
    const cf = createFrame.get(e.unitID) ?? null;
    const lifetimeSec      = cf != null ? round((e.frame - cf) / fps, 1) : null;
    const energyRatePerSec = defRaw ? _energyRate(defRaw) : 0;
    const isVariableRate   = defRaw ? num(defRaw.windGenerator) > 0 : false;   // wind output depends on map wind speed
    const lifetimeEnergyValue = (lifetimeSec != null && energyRatePerSec > 0)
      ? round(energyRatePerSec * lifetimeSec / 70, 1)
      : null;

    // ── military wreck reference ──
    const wreckedValue      = bucket === "military" ? round(value * WRECK_PCT, 1) : null;
    // max theoretical advantage assuming unit was about to die (deathsave scenario)
    const reclaimAdvantage  = bucket === "military" ? round(value * (1 - WRECK_PCT), 1) : null;

    // ── combat stats at eat-time (from unit_damage summary) ──
    const cs = combatStats.get(e.unitID);
    const damageDealt  = cs ? round(cs.dealt, 0) : null;   // total combat damage dealt during lifetime
    const damageTaken  = cs ? round(cs.taken, 0) : null;   // total combat damage taken
    const experience   = cs ? round(cs.experience, 4) : null;

    evByTeam.get(tm).push({
      frame: e.frame, second: round(e.frame / fps, 1),
      defName: e.defName ?? "?", defID: e.defID, bucket, value,
      // lifetime fields
      lifetimeSec,
      energyRatePerSec: energyRatePerSec > 0 ? energyRatePerSec : null,
      isVariableRate: isVariableRate || null,
      lifetimeEnergyValue,   // metal-equiv energy the structure generated; null for non-eco
      // military wreck reference
      wreckedValue,          // reference: what wreck would give (~55%); null for non-military
      reclaimAdvantage,      // max theoretical savings vs wreck (if unit was at ~0 HP); null for non-military
      // combat stats (from unit_damage summary — null if unit never participated in combat before being eaten)
      damageDealt,
      damageTaken,
      experience,
    });
  }

  // ---- sample frames (match economy_composition convention) ----
  const allFrames = kills.map(e => e.frame);
  const end = m.endFrame || (allFrames.length ? allFrames[allFrames.length - 1] : 0);
  const frames = [];
  for (let f = 0; f <= end; f += everyFrames) frames.push(f);
  if (!frames.length || frames[frames.length - 1] !== end) frames.push(end);

  // ---- build cumulative series per team ----
  const series = new Map();
  for (const tm of m.teams) series.set(tm, []);

  for (const tm of m.teams) {
    const evs  = evByTeam.get(tm) ?? [];
    const sums = _zero();
    let ei = 0;
    for (const F of frames) {
      while (ei < evs.length && evs[ei].frame <= F) {
        const ev = evs[ei++];
        if (ev.bucket === "commander") { sums.build_power += ev.value; sums.military += ev.value; }
        else sums[ev.bucket] += ev.value;
      }
      const value = {};
      for (const b of BUCKETS) value[b] = round(sums[b]);
      const total = BUCKETS.reduce((a, b) => a + value[b], 0);
      const pct = {};
      for (const b of BUCKETS) pct[b] = total > 0 ? round((value[b] / total) * 100, 2) : 0;
      series.get(tm).push({ frame: F, second: round(F / fps, 1), total: round(total), value, pct });
    }
  }

  // ---- final snapshot + summary stats per team ----
  const final = {}, eventCount = {}, lifetimeEnergyTotal = {}, reclaimAdvantageTotal = {};
  for (const tm of m.teams) {
    const arr  = series.get(tm);
    final[tm]  = arr[arr.length - 1];
    const evs  = evByTeam.get(tm) ?? [];
    eventCount[tm] = evs.length;
    lifetimeEnergyTotal[tm] = round(evs.reduce((s, e) => s + (e.lifetimeEnergyValue ?? 0), 0), 1);
    reclaimAdvantageTotal[tm] = round(evs.reduce((s, e) => s + (e.reclaimAdvantage ?? 0), 0), 1);
  }

  return {
    metricId:   "self_reclaim",
    buckets:    BUCKETS,
    params:     { everyFrames, fps, valueFormula: params?.value?.formula ?? "metal_plus_energy_div_70", wreckPct: WRECK_PCT },
    teams:      m.teams.slice(),
    series:     Object.fromEntries([...series]),
    final,
    eventCount,
    // team-level summary of lifetime analysis
    lifetimeEnergyTotal,       // metal-equiv energy generated by reclaimed eco structures (their real contribution)
    reclaimAdvantageTotal,     // max theoretical savings vs wreck for all military reclaims (assumes deathsave)
    // raw event list: includes lifetime/wreck fields for drilldown
    events:     Object.fromEntries([...evByTeam]),
  };
}

// ── helpers ──────────────────────────────────────────────────────────────────

// Energy production rate per second from a raw unit def.
// BAR uses two patterns: direct energyProduction field, OR negative energyUpkeep (armsolar/corsolar).
// Wind turbines use windGenerator (max capacity; actual output is wind-speed-dependent).
function _energyRate(def) {
  return num(def.energyProduction)
    + Math.max(0, -num(def.energyUpkeep))
    + num(def.windGenerator)
    + num(def.tidalGenerator);
}

function _zero() { return { economy: 0, military: 0, build_power: 0, infrastructure: 0, other: 0 }; }
function num(x)  { return typeof x === "number" && isFinite(x) ? x : 0; }
function round(x, d = 0) { const p = 10 ** d; return Math.round((x + Number.EPSILON) * p) / p; }

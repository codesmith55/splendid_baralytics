// tech_analysis.mjs — deep per-interval resource analysis for a Tech player.
//
// Tracks wind, income rates, eco structure inventory, and spending efficiency
// over 15-second intervals for the first 6 minutes. Segments pre/post first factory.
//
// Key design choices:
//  - Wind: sampled from wind_update (fires every 5s / 150 frames). Each interval
//    uses the sample nearest its start frame. windDelta shows direction of change.
//  - Income: metalIncome/energyIncome from extra_stat_update (fires every 15s).
//    These are the CURRENT RATE at sample time (m/s and e/s), including all sources.
//  - Reclaim discounting: self-reclaimed eco structures (unit_killed, weaponDefID=-12,
//    eco bucket) are tracked separately. Their metalCost is real metal returned to pool
//    but is NOT genuine generation — subtract from income accounting to get true eco value.
//  - Eco inventory: mex/solar/wind counts built up from unit_created events; decremented
//    on unit_killed (combat or reclaim). unit_created includes unit_x/unit_z positions.
//  - Phase: segmented by completion frame of the first factory (any tier).
//
// Limitations: unit_created fires at build COMPLETION, not build start. A factory
// started at 1:30 may appear at ~3:30 depending on constructor count and buildPower.

import { buildDefIndex } from "../classify.mjs";

export const meta = {
  id: "tech_analysis",
  title: "Tech player — per-interval resource efficiency, first 6 min",
  granularity: "team-per-interval",
  inputs: ["unit_def", "unit_created", "unit_killed", "wind_update", "extra_stat_update"],
};

const T2_FACTORY_METAL_THRESHOLD = 700; // factories ≥ this = T2
const DEFAULT_WINDOW_SEC   = 360;
const DEFAULT_INTERVAL_SEC = 15;
const RECLAIM_WEAPON_ID    = -12;       // Spring internal constant for reclaim action

export function compute(ctx, techTeamID, params = {}) {
  const { byAction, defMap } = ctx;
  const fps           = params.fps           ?? ctx.sampling?.fps ?? 30;
  const windowSec     = params.windowSec     ?? DEFAULT_WINDOW_SEC;
  const intervalSec   = params.intervalSec   ?? DEFAULT_INTERVAL_SEC;
  const compareIDs    = params.compareTeamIDs ?? [];

  const windowFrames   = windowSec   * fps;
  const intervalFrames = intervalSec * fps;
  const intervalCount  = Math.ceil(windowFrames / intervalFrames);

  const defIndex   = buildDefIndex(defMap, params);

  // ── shared event streams ──────────────────────────────────────────────────
  const allCreated = byAction.get("unit_created") ?? [];
  const allKilled  = byAction.get("unit_killed")  ?? [];
  const windSamples    = _indexWind(byAction.get("wind_update") ?? [], intervalFrames, intervalCount);
  const extraSamples   = _indexExtra(byAction.get("extra_stat_update") ?? []);

  // ── build intervals for tech + compare players ────────────────────────────
  const allTeamIDs    = [techTeamID, ...compareIDs];
  const teamIntervals = new Map(allTeamIDs.map(tid => [
    tid,
    _buildIntervals(
      allCreated.filter(e => e.teamID === tid && e.frame <= windowFrames).sort((a,b) => a.frame - b.frame),
      allKilled.filter(e => e.teamID === tid && e.frame <= windowFrames),
      intervalCount, intervalFrames, fps, defIndex, defMap,
      windSamples, extraSamples.get(tid) ?? []
    )
  ]));

  const techIvs = teamIntervals.get(techTeamID);

  return {
    teamID:      techTeamID,
    windowSec,
    intervalSec,
    intervals:   techIvs,
    compare:     compareIDs.length > 0
      ? Object.fromEntries(compareIDs.map(id => [id, teamIntervals.get(id)]))
      : null,
    deltas:      compareIDs.length > 0
      ? _buildDeltas(techIvs, compareIDs.map(id => teamIntervals.get(id)))
      : null,
    summary:     _buildSummary(techIvs, windowFrames),
  };
}

// ── interval construction ─────────────────────────────────────────────────────

function _buildIntervals(createdEvents, killedEvents, intervalCount, intervalFrames, fps,
                         defIndex, defMap, windSamples, extraByInterval) {

  // ── pre-pass: eco inventory tracking (mex, solar, wind) ──────────────────
  // Map unitID → { type: "mex"|"solar"|"wind", addFrame, removeFrame? }
  const ecoUnits = new Map();
  for (const e of createdEvents) {
    const defRaw = defMap.get(e.defID);
    const ecoType = _ecoType(defRaw);
    if (ecoType) ecoUnits.set(e.unitID, { type: ecoType, addFrame: e.frame });
  }
  for (const e of killedEvents) {
    if (ecoUnits.has(e.unitID)) {
      ecoUnits.get(e.unitID).removeFrame = e.frame;
    }
  }

  // ── pre-pass: self-reclaim kills for eco discounting ─────────────────────
  const selfReclaimKills = killedEvents.filter(e =>
    e.weaponDefID === RECLAIM_WEAPON_ID && e.attackerTeam === e.teamID
  );
  const ecoReclaimsByInterval = new Array(intervalCount).fill(null).map(() => []);
  for (const e of selfReclaimKills) {
    const defRaw = defMap.get(e.defID);
    if (!_ecoType(defRaw)) continue;
    const idx = Math.min(Math.floor(e.frame / intervalFrames), intervalCount - 1);
    ecoReclaimsByInterval[idx].push({ metalCost: num(defRaw?.metalCost), ecoType: _ecoType(defRaw) });
  }

  // ── pre-pass: first factory detection ────────────────────────────────────
  let firstFactoryFrame = Infinity;
  let firstFactoryInfo  = null;
  for (const e of createdEvents) {
    const defRaw  = defMap.get(e.defID);
    const isFactory = defRaw?.isFactory === true;
    if (!isFactory) continue;
    if (e.frame < firstFactoryFrame) {
      firstFactoryFrame = e.frame;
      firstFactoryInfo  = {
        defName:   e.defName ?? `def${e.defID}`,
        metalCost: num(defRaw.metalCost),
        tier:      num(defRaw.metalCost) >= T2_FACTORY_METAL_THRESHOLD ? "T2" : "T1",
        frame:     e.frame,
        second:    round(e.frame / fps, 1),
      };
    }
  }

  // ── build skeleton ────────────────────────────────────────────────────────
  const ivs = Array.from({ length: intervalCount }, (_, i) => ({
    i,
    startSec:   round(i       * intervalFrames / fps, 1),
    endSec:     round((i + 1) * intervalFrames / fps, 1),
    startFrame: i       * intervalFrames,
    endFrame:   (i + 1) * intervalFrames,

    // Wind
    wind:       null,   // strength magnitude at interval start
    windX:      null,   // x-component (direction)
    windZ:      null,   // z-component (direction)
    windDelta:  null,   // change from previous interval (+ = rising, − = falling)

    // Income snapshot from extra_stat_update (null until gex.lua emits new fields)
    metalIncome:   null,
    energyIncome:  null,
    metalCurrent:  null,
    energyCurrent: null,
    // Cumulative team metal transfers received (diff from prev to get per-interval inflow)
    metalReceived: null,

    // Eco inventory changes this interval
    mexAdded: 0, solarAdded: 0, windAdded: 0,
    mexLost:  0, solarLost:  0, windLost:  0,
    // Cumulative active structures at end of interval
    cumMex: 0, cumSolar: 0, cumWind: 0,

    // Self-reclaim discounting: eco structures eaten by self this interval
    reclaimedEcoMetal: 0,   // metalCost returned via reclaim (not true generation)
    reclaimedEcoCount: 0,
    reclaimedByType:   { mex: 0, solar: 0, wind: 0 },

    // Spending (unit completions)
    metalSpent:  0,
    energySpent: 0,
    bpDeployed:  0,
    byBucket:    _zeros(),
    built:       [],
    t2Factory:   null,

    // Phase
    phase:        firstFactoryFrame === Infinity ? "no_factory" :
                  i * intervalFrames < firstFactoryFrame ? "pre_factory" : "post_factory",
    factoryBuilt: null,   // set if first factory completed in this interval

    // Cumulative
    cumMetal:    0,
    cumEnergy:   0,
    cumByBucket: _zeros(),
  }));

  // ── fill eco inventory changes ─────────────────────────────────────────────
  for (const [, u] of ecoUnits) {
    const addIdx = Math.min(Math.floor(u.addFrame / intervalFrames), intervalCount - 1);
    if      (u.type === "mex")   ivs[addIdx].mexAdded++;
    else if (u.type === "solar") ivs[addIdx].solarAdded++;
    else if (u.type === "wind")  ivs[addIdx].windAdded++;

    if (u.removeFrame != null) {
      const rmIdx = Math.min(Math.floor(u.removeFrame / intervalFrames), intervalCount - 1);
      if      (u.type === "mex")   ivs[rmIdx].mexLost++;
      else if (u.type === "solar") ivs[rmIdx].solarLost++;
      else if (u.type === "wind")  ivs[rmIdx].windLost++;
    }
  }

  // ── fill reclaim discounting ───────────────────────────────────────────────
  for (let i = 0; i < intervalCount; i++) {
    const iv = ivs[i];
    for (const r of ecoReclaimsByInterval[i]) {
      iv.reclaimedEcoMetal += r.metalCost;
      iv.reclaimedEcoCount++;
      if (r.ecoType && iv.reclaimedByType[r.ecoType] != null) iv.reclaimedByType[r.ecoType]++;
    }
    iv.reclaimedEcoMetal = round(iv.reclaimedEcoMetal);
  }

  // ── fill unit_created spending ─────────────────────────────────────────────
  for (const e of createdEvents) {
    const idx     = Math.min(Math.floor(e.frame / intervalFrames), intervalCount - 1);
    const iv      = ivs[idx];
    const def     = defIndex.get(e.defID);
    const defRaw  = defMap.get(e.defID);
    const metal   = num(defRaw?.metalCost);
    const energy  = num(defRaw?.energyCost);
    const bp      = num(defRaw?.buildPower);
    const bucket  = _normBucket(def?.bucket ?? "other");
    const isFactory   = defRaw?.isFactory === true;
    const isBuilder   = defRaw?.isBuilder === true && !isFactory;
    const isT2Factory = isFactory && metal >= T2_FACTORY_METAL_THRESHOLD;

    iv.metalSpent  += metal;
    iv.energySpent += energy;
    if (isFactory || isBuilder) iv.bpDeployed += bp;
    iv.byBucket[bucket] += metal;

    if (isT2Factory && !iv.t2Factory) {
      iv.t2Factory = { defName: e.defName ?? `def${e.defID}`, metalCost: metal, frame: e.frame, second: round(e.frame / fps, 1) };
    }
    if (firstFactoryInfo && e.frame === firstFactoryFrame && !iv.factoryBuilt) {
      iv.factoryBuilt = firstFactoryInfo;
    }
    if (isFactory || metal >= 150) {
      iv.built.push({ defName: e.defName ?? `def${e.defID}`, bucket, metalCost: metal, isFactory, isT2Factory, second: round(e.frame / fps, 1), unit_x: e.unit_x ?? null, unit_z: e.unit_z ?? null });
    }
  }

  // ── fill wind ──────────────────────────────────────────────────────────────
  for (let i = 0; i < intervalCount; i++) {
    const w = windSamples[i];
    if (w) {
      ivs[i].wind  = w.value != null ? round(w.value, 2)  : null;
      ivs[i].windX = w.windX != null ? round(w.windX, 2)  : null;
      ivs[i].windZ = w.windZ != null ? round(w.windZ, 2)  : null;
    }
    if (i > 0 && ivs[i].wind != null && ivs[i - 1].wind != null) {
      ivs[i].windDelta = round(ivs[i].wind - ivs[i - 1].wind, 2);
    }
  }

  // ── fill income (extra_stat_update) ───────────────────────────────────────
  for (const es of extraByInterval) {
    // extra_stat_update fires at frame % 450 == 0, which aligns with interval boundaries
    const idx = Math.min(Math.floor(es.frame / intervalFrames), intervalCount - 1);
    const iv  = ivs[idx];
    iv.metalIncome   = es.metalIncome   ?? null;
    iv.energyIncome  = es.energyIncome  ?? null;
    iv.metalCurrent  = es.metalCurrent  ?? null;
    iv.energyCurrent = es.energyCurrent ?? null;
    iv.metalReceived = es.metalReceived ?? null;
  }

  // ── cumulative passes ──────────────────────────────────────────────────────
  const cumEco = { mex: 0, solar: 0, wind: 0 };
  const cumSpend = { metal: 0, energy: 0, buckets: _zeros() };
  for (const iv of ivs) {
    // eco inventory
    cumEco.mex   += iv.mexAdded   - iv.mexLost;
    cumEco.solar += iv.solarAdded - iv.solarLost;
    cumEco.wind  += iv.windAdded  - iv.windLost;
    iv.cumMex   = Math.max(0, cumEco.mex);
    iv.cumSolar = Math.max(0, cumEco.solar);
    iv.cumWind  = Math.max(0, cumEco.wind);

    // spending
    cumSpend.metal  += iv.metalSpent;
    cumSpend.energy += iv.energySpent;
    for (const b of BUCKETS) cumSpend.buckets[b] += iv.byBucket[b] ?? 0;
    iv.cumMetal    = round(cumSpend.metal);
    iv.cumEnergy   = round(cumSpend.energy);
    iv.cumByBucket = _roundBuckets({ ...cumSpend.buckets });

    // round raw fields
    iv.metalSpent  = round(iv.metalSpent);
    iv.energySpent = round(iv.energySpent);
    iv.bpDeployed  = round(iv.bpDeployed);
    iv.byBucket    = _roundBuckets(iv.byBucket);
  }

  return ivs;
}

// ── summary ────────────────────────────────────────────────────────────────

function _buildSummary(ivs, windowFrames) {
  const t2Iv    = ivs.find(iv => iv.t2Factory);
  const t2Event = t2Iv?.t2Factory ?? null;
  const firstFactoryIv   = ivs.find(iv => iv.factoryBuilt);
  const firstFactoryInfo = firstFactoryIv?.factoryBuilt ?? null;

  const totalMetal  = ivs[ivs.length - 1]?.cumMetal  ?? 0;
  const totalEnergy = ivs[ivs.length - 1]?.cumEnergy ?? 0;
  const totalBuckets = _zeros();
  for (const iv of ivs) for (const b of BUCKETS) totalBuckets[b] += iv.byBucket[b] ?? 0;

  const factoryFrame = firstFactoryInfo?.frame ?? Infinity;

  // Pre/post factory window
  const preIvs  = ivs.filter(iv => iv.phase === "pre_factory");
  const postIvs = ivs.filter(iv => iv.phase === "post_factory");

  const _ivSummary = (subset) => {
    const buckets = _zeros();
    for (const iv of subset) for (const b of BUCKETS) buckets[b] += iv.byBucket[b] ?? 0;
    const last = subset[subset.length - 1] ?? null;
    const incomes = subset.filter(iv => iv.metalIncome != null);
    return {
      intervalCount:    subset.length,
      metal:            round(Object.values(buckets).reduce((a,b) => a+b, 0)),
      byBucket:         _roundBuckets(buckets),
      peakMex:          last?.cumMex   ?? 0,
      peakSolar:        last?.cumSolar ?? 0,
      peakWind:         last?.cumWind  ?? 0,
      avgMetalIncome:   incomes.length ? round(incomes.reduce((s,iv) => s + iv.metalIncome,  0) / incomes.length, 2) : null,
      avgEnergyIncome:  incomes.length ? round(incomes.reduce((s,iv) => s + iv.energyIncome, 0) / incomes.length, 2) : null,
      reclaimedEcoMetal: round(subset.reduce((s,iv) => s + iv.reclaimedEcoMetal, 0)),
    };
  };

  // Tech quality: % of pre-T2 spend on infra + eco
  const preT2Ivs = t2Event ? ivs.filter(iv => iv.endFrame <= t2Event.frame) : ivs;
  const preT2Buckets = _zeros();
  for (const iv of preT2Ivs) for (const b of BUCKETS) preT2Buckets[b] += iv.byBucket[b] ?? 0;
  const preT2Total = Object.values(preT2Buckets).reduce((a,b) => a+b, 0);
  const techScore  = preT2Total > 0
    ? round(((preT2Buckets.infrastructure + preT2Buckets.economy) / preT2Total) * 100, 1) : null;
  const preT2MilFraction = preT2Total > 0
    ? round((preT2Buckets.military / preT2Total) * 100, 1) : 0;

  // Wind range across the window
  const winds = ivs.map(iv => iv.wind).filter(v => v != null);
  const windRange = winds.length ? { min: round(Math.min(...winds),2), max: round(Math.max(...winds),2), mean: round(winds.reduce((a,b)=>a+b,0)/winds.length,2) } : null;

  // Total reclaim discounting
  const totalReclaimedEco = round(ivs.reduce((s,iv) => s + iv.reclaimedEcoMetal, 0));

  return {
    firstFactory:     firstFactoryInfo,
    firstFactorySec:  firstFactoryInfo?.second ?? null,
    t2Factory:        t2Event,
    t2FactorySec:     t2Event?.second ?? null,
    totalMetal,
    totalEnergy,
    totalByBucket:    _roundBuckets(totalBuckets),
    preFactory:       _ivSummary(preIvs),
    postFactory:      _ivSummary(postIvs),
    // Wind context
    windRange,
    // Reclaim accounting
    totalReclaimedEcoMetal: totalReclaimedEco,
    // Tech quality
    techScore,
    preT2MilFraction,
    preT2VelocityPerInterval: preT2Ivs.length > 0 ? round(preT2Total / preT2Ivs.length, 1) : 0,
    unitCount: ivs.reduce((s,iv) => s + iv.built.length, 0),
  };
}

// ── comparison deltas ──────────────────────────────────────────────────────

function _buildDeltas(techIvs, refIvsArray) {
  const n = refIvsArray.length;
  return techIvs.map((t, i) => {
    const refMeans = {
      metalSpent:   round(refIvsArray.reduce((s,r) => s + r[i].metalSpent,  0) / n),
      energySpent:  round(refIvsArray.reduce((s,r) => s + r[i].energySpent, 0) / n),
      bpDeployed:   round(refIvsArray.reduce((s,r) => s + r[i].bpDeployed,  0) / n),
      metalIncome:  refIvsArray.some(r => r[i].metalIncome != null)
        ? round(refIvsArray.filter(r => r[i].metalIncome != null).reduce((s,r) => s + r[i].metalIncome, 0) / n, 2) : null,
      energyIncome: refIvsArray.some(r => r[i].energyIncome != null)
        ? round(refIvsArray.filter(r => r[i].energyIncome != null).reduce((s,r) => s + r[i].energyIncome, 0) / n, 2) : null,
      cumMex:   round(refIvsArray.reduce((s,r) => s + r[i].cumMex,   0) / n, 1),
      cumSolar: round(refIvsArray.reduce((s,r) => s + r[i].cumSolar, 0) / n, 1),
      cumWind:  round(refIvsArray.reduce((s,r) => s + r[i].cumWind,  0) / n, 1),
      byBucket: _roundBuckets(Object.fromEntries(BUCKETS.map(b => [
        b, round(refIvsArray.reduce((s,r) => s + (r[i].byBucket[b] ?? 0), 0) / n)
      ]))),
    };

    return {
      i, startSec: t.startSec, endSec: t.endSec,
      wind: t.wind,
      phase: t.phase,
      tech:    { metalSpent: t.metalSpent, metalIncome: t.metalIncome, energyIncome: t.energyIncome, cumMex: t.cumMex, cumSolar: t.cumSolar, cumWind: t.cumWind, byBucket: t.byBucket },
      refMean: refMeans,
      delta: {
        metalSpent:   round(t.metalSpent  - refMeans.metalSpent),
        energySpent:  round(t.energySpent - refMeans.energySpent),
        metalIncome:  t.metalIncome != null && refMeans.metalIncome != null ? round(t.metalIncome - refMeans.metalIncome, 2) : null,
        energyIncome: t.energyIncome != null && refMeans.energyIncome != null ? round(t.energyIncome - refMeans.energyIncome, 2) : null,
        cumMex:   round(t.cumMex   - refMeans.cumMex,   1),
        cumSolar: round(t.cumSolar - refMeans.cumSolar, 1),
        cumWind:  round(t.cumWind  - refMeans.cumWind,  1),
        byBucket: _roundBuckets(Object.fromEntries(BUCKETS.map(b => [b, round((t.byBucket[b] ?? 0) - refMeans.byBucket[b])]))),
      },
    };
  });
}

// ── wind indexing: map interval index → nearest wind_update event ──────────

function _indexWind(windEvents, intervalFrames, intervalCount) {
  // wind_update fires every 150 frames (5s); for each 15s interval pick the nearest
  // sample at or before the interval's start frame.
  if (!windEvents.length) return new Array(intervalCount).fill(null);
  const sorted = [...windEvents].sort((a, b) => a.frame - b.frame);
  const result = [];
  for (let i = 0; i < intervalCount; i++) {
    const targetFrame = i * intervalFrames;
    let best = null;
    for (const w of sorted) {
      if (w.frame > targetFrame) break;
      best = w;
    }
    result.push(best);
  }
  return result;
}

// ── extra_stat_update indexing: Map teamID → array of events ─────────────

function _indexExtra(extraEvents) {
  const byTeam = new Map();
  for (const e of extraEvents) {
    if (!byTeam.has(e.teamID)) byTeam.set(e.teamID, []);
    byTeam.get(e.teamID).push(e);
  }
  return byTeam;
}

// ── eco type classifier ────────────────────────────────────────────────────

function _ecoType(defRaw) {
  if (!defRaw) return null;
  if (defRaw.isMetalExtractor === true) return "mex";
  if (num(defRaw.windGenerator) > 0)    return "wind";
  if (num(defRaw.tidalGenerator) > 0)   return "wind"; // treat tidal same as wind
  // solar / fusion / energy structures (fixed output)
  if (num(defRaw.energyProduction) > 0 || num(defRaw.energyUpkeep) < 0) return "solar";
  return null;
}

// ── helpers ────────────────────────────────────────────────────────────────

const BUCKETS    = ["economy", "military", "build_power", "infrastructure", "other"];
const BUCKET_SET = new Set(BUCKETS);
const _normBucket = b => (b === "commander" ? "build_power" : (BUCKET_SET.has(b) ? b : "other"));
function _zeros() { return Object.fromEntries(BUCKETS.map(b => [b, 0])); }
function _roundBuckets(b) { return Object.fromEntries(Object.entries(b).map(([k,v]) => [k, round(v)])); }
function num(x) { return typeof x === "number" && isFinite(x) ? x : 0; }
function round(x, d = 0) { const p = 10 ** d; return Math.round((x + Number.EPSILON) * p) / p; }

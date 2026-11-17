// economy_composition.mjs — % of total economy value by category, per team, per time.
// value(unit) = metalCost + energyCost/70 (configurable). Commander = flat 1200, double-counted
// into build_power AND military. Storage bucket = current metal + energy/70 held (extra_stat_update).
import { buildDefIndex } from "../classify.mjs";

export const meta = {
  id: "economy_composition",
  title: "Economy composition — % of total value by category, per team, per time",
  granularity: "team-per-time",
  inputs: ["unit_def", "unit_created", "unit_killed", "unit_given", "unit_taken", "extra_stat_update", "start", "end"],
};

const UNIT_BUCKETS = ["build_power", "economy", "infrastructure", "military", "other"];
const ALL_BUCKETS = [...UNIT_BUCKETS, "storage"];

export function compute(ctx, params = {}) {
  const { byAction, defMap, meta: m } = ctx;
  const everyFrames = params?.sampling?.everyFrames ?? ctx.sampling?.everyFrames ?? 450;
  const fps = params?.sampling?.fps ?? ctx.sampling?.fps ?? 30;
  const defIndex = buildDefIndex(defMap, params);

  // ---- merged, frame-sorted lifecycle stream ----
  const lc = [];
  for (const e of byAction.get("unit_created") ?? []) lc.push({ f: e.frame, t: "create", unitID: e.unitID, team: e.teamID, defID: e.defID });
  for (const e of byAction.get("unit_killed") ?? []) lc.push({ f: e.frame, t: "kill", unitID: e.unitID });
  for (const e of byAction.get("unit_given") ?? []) lc.push({ f: e.frame, t: "move", unitID: e.unitID, team: e.newTeamID });
  for (const e of byAction.get("unit_taken") ?? []) lc.push({ f: e.frame, t: "move", unitID: e.unitID, team: e.teamID });
  lc.sort((a, b) => a.f - b.f || order(a.t) - order(b.t));

  // ---- per-team running bucket sums (incremental) ----
  const teams = m.teams.slice();
  const sums = new Map();   // team -> {bucket: value}
  for (const tm of teams) sums.set(tm, zero());
  const alive = new Map();  // unitID -> {team, info}

  const apply = (team, info, sign) => {
    const s = sums.get(team) || zero();
    if (!sums.has(team)) sums.set(team, s);
    if (info.isCommander) { s.build_power += sign * info.value; s.military += sign * info.value; }
    else s[info.bucket in s ? info.bucket : "other"] += sign * info.value;
  };

  // ---- storage time series per team (sorted extra_stat_update) ----
  const xs = (byAction.get("extra_stat_update") ?? []).slice().sort((a, b) => a.frame - b.frame);
  const xsByTeam = new Map();
  for (const e of xs) { if (!xsByTeam.has(e.teamID)) xsByTeam.set(e.teamID, []); xsByTeam.get(e.teamID).push(e); }
  const storageAt = (team, frame) => {
    const arr = xsByTeam.get(team); if (!arr) return 0;
    let v = 0;
    for (const e of arr) { if (e.frame > frame) break; v = num(e.metalCurrent) + num(e.energyCurrent) / 70; }
    return v;
  };

  // ---- sample frames ----
  const end = m.endFrame || (lc.length ? lc[lc.length - 1].f : 0);
  const frames = [];
  for (let f = 0; f <= end; f += everyFrames) frames.push(f);
  if (frames[frames.length - 1] !== end) frames.push(end);

  // ---- walk lifecycle, snapshot at each sample frame ----
  const series = new Map(); // team -> [snap]
  for (const tm of teams) series.set(tm, []);
  let p = 0;
  for (const F of frames) {
    while (p < lc.length && lc[p].f <= F) {
      const ev = lc[p++];
      if (ev.t === "create") {
        const info = defIndex.get(ev.defID) || { bucket: "other", value: 0, isCommander: false };
        alive.set(ev.unitID, { team: ev.team, info });
        apply(ev.team, info, +1);
      } else if (ev.t === "kill") {
        const rec = alive.get(ev.unitID); if (rec) { apply(rec.team, rec.info, -1); alive.delete(ev.unitID); }
      } else if (ev.t === "move") {
        const rec = alive.get(ev.unitID); if (rec) { apply(rec.team, rec.info, -1); rec.team = ev.team; apply(rec.team, rec.info, +1); }
      }
    }
    for (const tm of teams) {
      const s = sums.get(tm) || zero();
      const buckets = {};
      for (const b of UNIT_BUCKETS) buckets[b] = round(s[b]);
      buckets.storage = round(storageAt(tm, F));
      const total = ALL_BUCKETS.reduce((a, b) => a + buckets[b], 0);
      const pct = {};
      for (const b of ALL_BUCKETS) pct[b] = total > 0 ? round((buckets[b] / total) * 100, 2) : 0;
      series.get(tm).push({ frame: F, second: round(F / fps, 1), total: round(total), value: buckets, pct });
    }
  }

  // ---- final + peak snapshots per team (peak = highest unit-value total; ignores all-dead frames) ----
  const final = {}, peak = {};
  for (const tm of teams) {
    const arr = series.get(tm);
    final[tm] = arr[arr.length - 1];
    let best = arr[0];
    for (const s of arr) {
      const unitTotal = s.total - (s.value.storage || 0); // exclude residual stored resources
      const bestUnit = best.total - (best.value.storage || 0);
      if (unitTotal >= bestUnit) best = s;
    }
    peak[tm] = best;
  }

  return {
    metricId: "economy_composition",
    buckets: ALL_BUCKETS,
    params: { everyFrames, fps, valueFormula: params?.value?.formula ?? "metal_plus_energy_div_70", commanderValue: num(params.commanderValue ?? 1200) },
    teams,
    series: Object.fromEntries([...series].map(([k, v]) => [k, v])),
    final,
    peak,
  };
}

function zero() { return { build_power: 0, economy: 0, infrastructure: 0, military: 0, other: 0 }; }
function order(t) { return t === "kill" ? 0 : t === "move" ? 1 : 2; } // process kills/moves before creates on same frame
function num(x) { return typeof x === "number" && isFinite(x) ? x : 0; }
function round(x, d = 0) { const p = 10 ** d; return Math.round((x + Number.EPSILON) * p) / p; }

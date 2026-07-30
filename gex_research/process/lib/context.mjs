// context.mjs — assemble the shared analysis context the metrics/situations read from.
import { buildDefIndex } from "./classify.mjs";

export function buildContext(parsed, opts = {}) {
  const { byAction, defMap, meta } = parsed;
  const defIndex = buildDefIndex(defMap, opts.params || {});

  // start position per team = its commander's spawn (unit_created with a commander def)
  const startPos = new Map();
  for (const e of byAction.get("unit_created") ?? []) {
    if (startPos.has(e.teamID)) continue;
    const info = defIndex.get(e.defID);
    const isCom = info?.isCommander || /com$/.test(e.defName || "");
    if (isCom && e.unit_x != null && e.unit_z != null) startPos.set(e.teamID, { x: e.unit_x, z: e.unit_z });
  }
  // fallback: first unit_created position for any team still missing
  for (const e of byAction.get("unit_created") ?? []) {
    if (!startPos.has(e.teamID) && e.unit_x != null) startPos.set(e.teamID, { x: e.unit_x, z: e.unit_z });
  }

  // roster (names/faction/ally) from a demo-parser file, else nulls
  const roster = opts.roster || new Map(); // team -> {name, faction, skill, allyTeam}

  // ally membership: prefer roster, else infer two clusters by the dominant spatial axis
  const allyOf = new Map();
  let usedRosterAlly = false;
  for (const tm of meta.teams) {
    const r = roster.get(tm);
    if (r && r.allyTeam != null) { allyOf.set(tm, r.allyTeam); usedRosterAlly = true; }
  }
  if (!usedRosterAlly) inferAllies(meta.teams, startPos, allyOf);

  // center = true map center from map dimensions (preferred) or centroid of start positions (fallback).
  // Using the true map center is correct because players choose spawn positions freely —
  // the centroid drifts if selection is uneven.  mapSizeX/Z are emitted by gex.lua (Game.mapSizeX/Z).
  const pts = [...startPos.values()];
  const center = (meta.mapSizeX != null && meta.mapSizeZ != null)
    ? { x: meta.mapSizeX / 2, z: meta.mapSizeZ / 2 }
    : pts.length
      ? { x: avg(pts.map(p => p.x)), z: avg(pts.map(p => p.z)) }
      : { x: 0, z: 0 };

  return { ...parsed, defIndex, startPos, roster, allyOf, center, sampling: opts.sampling || {} };
}

function inferAllies(teams, startPos, allyOf) {
  const pts = teams.map(t => ({ t, p: startPos.get(t) })).filter(x => x.p);
  if (!pts.length) { for (const t of teams) allyOf.set(t, 0); return; }
  const xs = pts.map(o => o.p.x), zs = pts.map(o => o.p.z);
  const axis = (Math.max(...xs) - Math.min(...xs)) >= (Math.max(...zs) - Math.min(...zs)) ? "x" : "z";
  const vals = pts.map(o => o.p[axis]).sort((a, b) => a - b);
  const mid = vals[Math.floor(vals.length / 2)];
  for (const o of pts) allyOf.set(o.t, o.p[axis] < mid ? 0 : 1);
  for (const t of teams) if (!allyOf.has(t)) allyOf.set(t, 0);
}

const avg = a => a.reduce((x, y) => x + y, 0) / a.length;

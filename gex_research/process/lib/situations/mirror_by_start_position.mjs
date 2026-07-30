// mirror_by_start_position.mjs — pair each player with their mirror opponent.
//
// Default (no adapter):  full 180° point reflection (XZ) through the map centre for every player.
//
// With a map adapter (params.mapAdapter = map id, e.g. "all_that_glitters"):
//   split_axis schema — two reflection types:
//     back-middle slots  abs(x - mapW/2) < adapter.splitAxis.xRangeFromCenter
//                        → XZ reflection (double-axis, point reflection)
//     flank slots        all other positions
//                        → Z-only reflection; matched within the same horizontal side
//                          (left-bottom with left-top, right-bottom with right-top)
//
// When one side has more flank players than the other (asymmetric spawn selection),
// the excess appear in `unpaired` — this is intentional and surfaced so callers can
// construct explicit pairings for analysis.
//
// Matching is greedy-by-distance: all valid candidate pairs are sorted by distance
// (ascending) and assigned smallest-first, so every paired player gets their
// geometrically closest valid counterpart.
import fs   from "node:fs";
import path from "node:path";
import { label } from "./per_user.mjs";
import { paths } from "../registry.mjs";

export const meta = {
  id:    "mirror_by_start_position",
  title: "Mirror matchup by start position",
  needs: ["start_positions"],
};

export function apply(metricResult, ctx, params = {}) {
  const maxDist    = params.maxPairDistance ?? 6000;
  const adapter    = _loadAdapter(params.mapAdapter);
  const mapW       = ctx.meta?.mapSizeX ?? null;
  const mapH       = ctx.meta?.mapSizeZ ?? null;
  const center     = ctx.center;

  const teams   = metricResult.teams.filter(tm => ctx.startPos.has(tm));
  const used    = new Set();
  const pairs   = [];

  // ── per-team classification ──────────────────────────────────────────────
  const classify = (tm) => {
    const p = ctx.startPos.get(tm);
    if (!adapter || adapter.mirrorSchema !== "split_axis" || !mapW) return "XZ";
    const threshold = adapter.splitAxis?.backMiddle?.xRangeFromCenter ?? 1000;
    return Math.abs(p.x - mapW / 2) < threshold ? "XZ" : "Z";
  };

  // horizontal side: -1=left, 1=right  (only meaningful for Z-type players)
  const sideOf = (tm) => {
    if (!mapW) return 0;
    return ctx.startPos.get(tm)?.x < mapW / 2 ? -1 : 1;
  };

  // reflect a position according to the team's mirror type
  const reflect = (p, type) =>
    type === "Z"
      ? { x: p.x,                  z: 2 * center.z - p.z }
      : { x: 2 * center.x - p.x,  z: 2 * center.z - p.z };

  // ── build all valid candidate pairs ──────────────────────────────────────
  // A pair (a, b) is valid if:
  //  – a and b are on opposing ally-teams
  //  – their mirror types agree  (both XZ, or both Z)
  //  – for Z-type: they are on the SAME horizontal side
  //  – distance(reflect(a.pos, type), b.pos) ≤ maxDist
  const candidates = [];
  for (let i = 0; i < teams.length; i++) {
    const tm  = teams[i];
    const typ = classify(tm);
    const ref = reflect(ctx.startPos.get(tm), typ);
    for (let j = i + 1; j < teams.length; j++) {
      const o = teams[j];
      if ((ctx.allyOf.get(o) ?? -1) === (ctx.allyOf.get(tm) ?? -2)) continue; // same ally → skip
      if (classify(o) !== typ) continue;                                        // different schema → skip
      if (typ === "Z" && adapter?.splitAxis?.flank?.matchSameSide) {
        if (sideOf(o) !== sideOf(tm)) continue;                                // wrong flank → skip
      }
      const d = dist(ctx.startPos.get(o), ref);
      if (d > maxDist) continue;
      candidates.push({ a: tm, b: o, d, type: typ });
    }
  }

  // ── greedy assignment: smallest distance first ───────────────────────────
  candidates.sort((x, y) => x.d - y.d);
  for (const { a, b, d, type } of candidates) {
    if (used.has(a) || used.has(b)) continue;
    used.add(a); used.add(b);
    const A = _side(ctx, metricResult, a);
    const B = _side(ctx, metricResult, b);
    pairs.push({
      distance:    round(d),
      mirrorType:  type,
      a: A, b: B,
      delta:       _deltaSnap(A.peak,  B.peak),
      deltaFinal:  _deltaSnap(A.final, B.final),
    });
  }

  const unpaired = teams
    .filter(t => !used.has(t))
    .map(t => ({
      teamID:      t,
      user:        label(ctx, t),
      mirrorType:  classify(t),
      side:        sideOf(t) < 0 ? "left" : sideOf(t) > 0 ? "right" : "center",
      allyTeam:    ctx.allyOf.get(t) ?? null,
      startPos:    ctx.startPos.get(t) ?? null,
    }));

  return {
    situationId: "mirror_by_start_position",
    mapAdapter:  adapter?.mapId ?? null,
    pairCount:   pairs.length,
    pairs,
    unpaired,
  };
}

// ── helpers ─────────────────────────────────────────────────────────────────

function _loadAdapter(id) {
  if (!id) return null;
  const { ROOT } = paths();
  const slug = id.replace(/_/g, "-");
  const p    = path.join(ROOT, "metrics", "maps", `${slug}.json`);
  if (!fs.existsSync(p)) { console.warn(`[mirror] map adapter not found: ${p}`); return null; }
  try { return JSON.parse(fs.readFileSync(p, "utf8")); }
  catch (e) { console.warn(`[mirror] failed to parse adapter ${p}: ${e.message}`); return null; }
}

function _side(ctx, mr, tm) {
  return {
    teamID:   tm,
    user:     label(ctx, tm),
    userId:   ctx.roster.get(tm)?.userId ?? null,
    allyTeam: ctx.allyOf.get(tm) ?? null,
    startPos: ctx.startPos.get(tm) ?? null,
    final:    mr.final[tm],
    peak:     mr.peak?.[tm] ?? mr.final[tm],
    series:   mr.series[tm],
  };
}

// %-point difference per bucket (a minus b) at two snapshots
function _deltaSnap(a, b) {
  if (!a || !b) return null;
  const out = {};
  for (const k of Object.keys(a.pct)) out[k] = round((a.pct[k] ?? 0) - (b.pct[k] ?? 0), 2);
  return out;
}

function dist(p, q) { return p && q ? Math.hypot(p.x - q.x, p.z - q.z) : Infinity; }
function round(x, d = 0) { const p = 10 ** d; return Math.round(x * p) / p; }

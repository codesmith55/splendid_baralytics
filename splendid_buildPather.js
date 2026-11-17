"use strict";
// splendid_buildPather.js — build PATTERNS (wind farms, converter blocks, …) as a builder PATHING problem.
//
//   node splendid_buildPather.js [pattern|file.txt] [--workers N] [--builder con_bot|con_veh|commander]
//                                [--start left|right|top|bottom|r,c] [--order auto|beam|greedy|naive] [--beam W]
//                                [--stands engine|free] [--improve N] [--seed S] [--compare] [--frames K] [--json out.json] [--quiet]
//   node splendid_buildPather.js [pattern] --queue "W(3,0) W(5,0) …"|file   evaluate YOUR order (walk, clashes, sealing)
//   node splendid_buildPather.js --list          patterns shipped in PATTERNS
//   node splendid_buildPather.js --selftest      invariants on every shipped pattern
//
// Home for the PLACEMENT side of building. The strategizer decides WHAT to build; this decides, once a pattern is
// chosen, the ORDER the pieces go down in. The output is a plain build queue: issue the placements in that order and
// the walking falls out of it — the engine walks the builder along the shortest path toward each target and stops
// at the first point in range, so the order alone fixes the route (--stands engine, the default). --stands free lets
// the planner pick stands (needs move orders between builds; reported for comparison).
//
// Model
//   grid      one cell = one 48×48 footprint (wind / converter / e-storage / con turret are all sizeX 6 = 48 elmos,
//             gex_research/sample_output/actions.json unit_def). '.' = gap (walkable lane; also the chain-explosion
//             firebreak), letters = buildings, '#' = never walkable, lowercase = already standing. A margin of
//             walkable cells surrounds the pattern (the outside world).
//   reach     a builder on a cell can build a target when dist(cell centre, target centre) ≤ buildRange + target radius:
//             clipping the footprint edge counts. Con bot 130 + 24 → 3 cells straight, (3,1) and (2,2) diagonally.
//   walking   8-connected, no corner cutting. A footprint blocks the moment it is placed (nanoframe). Cells that WILL
//             hold a building are walkable until then — walk space on the first pass, build space on the way back.
//   swarm     N workers share the queue and arrive strung out along the approach path behind the lead, so the swarm
//             blob = the last N cells of that path (+ the approach-side neighbours). A target under a trailing worker
//             = clash; under the lead = self-step; a target BEHIND the direction of travel = behind (reverse = the
//             route doubles back on itself); fewer than N free cells around the stand = cramped (a 1-wide tunnel).
//             The next building should constantly lead the swarm. Weights are walked-cell equivalents (defaults()),
//             so --workers 1 has no swarm penalties at all and the plan is the pure shortest route.
//   invariant after every placement the stand must still connect to the outside AND every remaining building must
//             still have a reachable stand — never wall in, never seal off part of the pattern.
//   search    auto = portfolio of greedy / beam seeds (± lookahead) → local search on the queue (relocate / reverse /
//             swap segments, every candidate re-simulated with the stand rule). Cost = walked cells + penalties.
//             naive = reading order (what a shift-dragged queue does) — the baseline.

const fs = require("fs");
const path = require("path");

// ───────────────────────────────────────────── engine truth
const PITCH = 48;                                   // elmos per footprint cell (sizeX 6 × 8)
const BUILDERS = {                                  // speed elmos/s · build range elmos · build power
  con_bot:   { speed: 36,   range: 130, bp: 80,  desc: "armck T1 construction bot" },
  con_veh:   { speed: 54,   range: 130, bp: 90,  desc: "armcv T1 construction vehicle" },
  commander: { speed: 37.5, range: 145, bp: 300, desc: "armcom" },
};
const TYPES = {                                     // buildTime = build-power seconds
  W: { name: "Wind",       buildTime: 1600, metal: 40,  energy: 175 },
  C: { name: "EConverter", buildTime: 2600, metal: 1,   energy: 1150 },
  S: { name: "EStorage",   buildTime: 4110, metal: 170, energy: 1800, group: true },  // contiguous S cells = one building
  T: { name: "ConTurret",  buildTime: 5300, metal: 230, energy: 3200 },
};

// ───────────────────────────────────────────── patterns (editable data; one char per cell, spaces ignored)
const PATTERNS = {
  windfarm_4x4: {
    desc: "Screenshot layout: four 4×4 blocks on a + of lane firebreaks; 54 wind, 8 converters (inner 2×2 of the bottom blocks), e-storage top-right.",
    start: "left",
    rows: [
      "W W W W . W W W W",
      "W W W W . W W W W",
      "W W W W . W S S W",
      "W W W W . W W W W",
      ". . . . . . . . .",
      "W W W W . W W W W",
      "W C C W . W C C W",
      "W C C W . W C C W",
      "W W W W . W W W W",
    ],
  },
  windrow_2x8: {
    desc: "Two 2-deep wind rows either side of one lane, converters at the far end — the minimal lane pattern.",
    start: "left",
    rows: [
      "W W W W W W W W C",
      "W W W W W W W W C",
      ". . . . . . . . .",
      "W W W W W W W W C",
      "W W W W W W W W C",
    ],
  },
  block_8x8: {
    desc: "Solid 8×8 wind block, no lanes — the 2×2 core is out of reach from outside, so the plan must stand on footprints first.",
    start: "left",
    rows: ["W W W W W W W W", "W W W W W W W W", "W W W W W W W W", "W W W W W W W W", "W W W W W W W W", "W W W W W W W W", "W W W W W W W W", "W W W W W W W W"],
  },
  courtyard_7x7: {
    desc: "Wind ring around a courtyard with one wind in the middle — reading order walls the builder in; a planned order does not.",
    start: "left",
    rows: ["W W W W W W W", "W . . . . . W", "W . . . . . W", "W . . W . . W", "W . . . . . W", "W . . . . . W", "W W W W W W W"],
  },
};

// ───────────────────────────────────────────── pattern → world
function parsePattern(spec) {
  const lines = (typeof spec === "string" ? spec.split(/\r?\n/) : spec).map(l => l.replace(/\s+/g, "")).filter(l => l.length && !l.startsWith("//"));
  const h = lines.length, w = Math.max(...lines.map(l => l.length));
  const cells = lines.map(l => l.padEnd(w, ".").split(""));
  return { h, w, cells };
}

function makeWorld(pat, opts) {
  const m = opts.margin, H = pat.h + 2 * m, W = pat.w + 2 * m;
  const at = (r, c) => r * W + c;
  const perm = new Uint8Array(H * W);              // permanently blocked (# / already standing)
  const cellBuilding = new Int16Array(H * W).fill(-1);
  const buildings = [];
  const seen = new Uint8Array(H * W);
  let startCell = null;
  for (let r = 0; r < pat.h; r++) for (let c = 0; c < pat.w; c++) {
    const ch = pat.cells[r][c], idx = at(r + m, c + m);
    if (ch === "#" || (ch >= "a" && ch <= "z")) { perm[idx] = 1; continue; }
    if (ch === "@") { startCell = idx; continue; }
    if (!TYPES[ch] || seen[idx]) continue;
    const t = TYPES[ch], cellsB = [];
    const q = [[r, c]]; seen[idx] = 1;
    while (q.length) {
      const [rr, cc] = q.shift(); cellsB.push(at(rr + m, cc + m));
      if (!t.group) continue;
      for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nr = rr + dr, nc = cc + dc;
        if (nr < 0 || nc < 0 || nr >= pat.h || nc >= pat.w) continue;
        const ni = at(nr + m, nc + m);
        if (pat.cells[nr][nc] === ch && !seen[ni]) { seen[ni] = 1; q.push([nr, nc]); }
      }
    }
    const rs = cellsB.map(i => Math.floor(i / W)), cs = cellsB.map(i => i % W);
    const rMin = Math.min(...rs), rMax = Math.max(...rs), cMin = Math.min(...cs), cMax = Math.max(...cs);
    const b = {
      id: buildings.length, type: ch, name: t.name, cells: cellsB,
      r: (rMin + rMax) / 2, c: (cMin + cMax) / 2,                             // centre in grid cells
      radius: 0.5 * PITCH * Math.max(rMax - rMin + 1, cMax - cMin + 1),      // footprint half-width
      stands: [],
    };
    for (const i of cellsB) cellBuilding[i] = b.id;
    buildings.push(b);
  }
  const world = { H, W, m, at, perm, cellBuilding, buildings, pat, builder: BUILDERS[opts.builder], adj: buildAdjacency(H, W), covers: null };
  // candidate stands: every non-permanent cell (margin + lanes + future building cells) inside reach, own footprint excluded
  for (const b of buildings) {
    const bx = (b.c + 0.5) * PITCH, bz = (b.r + 0.5) * PITCH, lim = world.builder.range + b.radius;
    for (let i = 0; i < H * W; i++) {
      if (perm[i] || cellBuilding[i] === b.id) continue;
      const x = ((i % W) + 0.5) * PITCH, z = (Math.floor(i / W) + 0.5) * PITCH;
      if (Math.hypot(x - bx, z - bz) <= lim) b.stands.push(i);
    }
    if (!b.stands.length) throw new Error(`building ${b.id} (${b.name}) has no reachable stand — reach too short`);
  }
  world.covers = new Array(H * W).fill(null).map(() => []);
  for (const b of buildings) for (const s of b.stands) world.covers[s].push(b.id);
  world.start = startCell != null ? startCell : resolveStart(world, opts.start);
  if (perm[world.start]) throw new Error("start cell is blocked");
  return world;
}

function resolveStart(world, spec) {
  const { H, W, m, at, pat } = world;
  const midR = m + Math.floor(pat.h / 2), midC = m + Math.floor(pat.w / 2);
  if (spec === "left") return at(midR, m - 1);
  if (spec === "right") return at(midR, m + pat.w);
  if (spec === "top") return at(m - 1, midC);
  if (spec === "bottom") return at(m + pat.h, midC);
  const mm = /^(-?\d+),(-?\d+)$/.exec(spec || "");
  if (!mm) throw new Error(`bad --start ${spec} (left|right|top|bottom|r,c in pattern coords)`);
  const r = Number(mm[1]) + m, c = Number(mm[2]) + m;
  if (r < 0 || c < 0 || r >= H || c >= W) throw new Error("start outside the world");
  return at(r, c);
}

// ───────────────────────────────────────────── grid movement
const DIRS = [[1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1], [1, 1, Math.SQRT2], [1, -1, Math.SQRT2], [-1, 1, Math.SQRT2], [-1, -1, Math.SQRT2]];

/** adjacency per cell: [ni, cost, cornerA, cornerB] × 8 (cornerA/B = the two orthogonal cells a diagonal must not cut; -1 for straight) */
function buildAdjacency(H, W) {
  const adj = new Array(H * W);
  for (let r = 0; r < H; r++) for (let c = 0; c < W; c++) {
    const list = [];
    for (const [dr, dc, cost] of DIRS) {
      const nr = r + dr, nc = c + dc;
      if (nr < 0 || nc < 0 || nr >= H || nc >= W) continue;
      list.push(nr * W + nc, cost, dr && dc ? r * W + nc : -1, dr && dc ? nr * W + c : -1);
    }
    adj[r * W + c] = list;
  }
  return adj;
}
/** neighbors of i that are walkable under `blocked` (no corner cutting), as a flat [ni, cost, ni, cost, …] array */
function neighbors(world, blocked, i) {
  const a = world.adj[i], out = [];
  for (let k = 0; k < a.length; k += 4) {
    const ni = a[k]; if (blocked[ni]) continue;
    if (a[k + 2] >= 0 && (blocked[a[k + 2]] || blocked[a[k + 3]])) continue;
    out.push(ni, a[k + 1]);
  }
  return out;
}

/** Dijkstra over walkable cells: dist (cells, diagonals √2) + parent for path tracing. */
function dijkstra(world, blocked, start) {
  const n = world.H * world.W, dist = new Float64Array(n).fill(Infinity), parent = new Int32Array(n).fill(-1);
  const heap = [[0, start]]; dist[start] = 0;
  const push = it => { heap.push(it); let i = heap.length - 1; while (i > 0) { const p = (i - 1) >> 1; if (heap[p][0] <= heap[i][0]) break; [heap[p], heap[i]] = [heap[i], heap[p]]; i = p; } };
  const pop = () => { const top = heap[0], last = heap.pop(); if (heap.length) { heap[0] = last; let i = 0; for (;;) { const l = 2 * i + 1, r = l + 1; let s = i; if (l < heap.length && heap[l][0] < heap[s][0]) s = l; if (r < heap.length && heap[r][0] < heap[s][0]) s = r; if (s === i) break; [heap[s], heap[i]] = [heap[i], heap[s]]; i = s; } } return top; };
  while (heap.length) {
    const [d, i] = pop(); if (d > dist[i]) continue;
    const nb = neighbors(world, blocked, i);
    for (let k = 0; k < nb.length; k += 2) {
      const ni = nb[k], nd = d + nb[k + 1]; if (nd < dist[ni] - 1e-9) { dist[ni] = nd; parent[ni] = i; push([nd, ni]); }
    }
  }
  return { dist, parent };
}
function tracePath(parent, end) { const p = []; for (let i = end; i !== -1; i = parent[i]) p.push(i); return p.reverse(); }

/** Unweighted reachability (visited mask) — the invariant check. */
function reachable(world, blocked, start) {
  const vis = new Uint8Array(world.H * world.W); const q = [start]; vis[start] = 1;
  for (let qi = 0; qi < q.length; qi++) { const nb = neighbors(world, blocked, q[qi]); for (let k = 0; k < nb.length; k += 2) { const ni = nb[k]; if (!vis[ni]) { vis[ni] = 1; q.push(ni); } } }
  return vis;
}
function isMargin(world, i) { const r = Math.floor(i / world.W), c = i % world.W; return r === 0 || c === 0 || r === world.H - 1 || c === world.W - 1; }

/** After placing `placed`, can the swarm still get out, and can every remaining building still be reached from a stand? */
function viable(world, blocked, stand, built, placed) {
  const vis = reachable(world, blocked, stand);
  let out = false; for (let i = 0; i < vis.length && !out; i++) if (vis[i] && isMargin(world, i)) out = true;
  if (!out) return false;
  for (const b of world.buildings) {
    if (built[b.id] || b.id === placed) continue;
    if (!b.stands.some(s => vis[s] && !blocked[s])) return false;
  }
  return true;
}

/**
 * Where N workers stand: the lead cell, then the seed order (approach path backwards / previous blob), then a fill of
 * the cells around the lead. Trailing workers stop short and get shoved sideways, so the fill prefers cells on the
 * approach side (closest to `from`, the previous stand) and lane/margin cells over future footprints.
 */
function swarmBlob(world, blocked, lead, seed, n, from = lead) {
  const out = [lead], seen = new Set(out);
  for (const c of seed) { if (out.length >= n) break; if (!blocked[c] && !seen.has(c)) { seen.add(c); out.push(c); } }
  if (out.length < n) {
    const [fx, fy] = cellXY(world, from), ring = [], nb = neighbors(world, blocked, lead);
    for (let k = 0; k < nb.length; k += 2) if (!seen.has(nb[k])) ring.push(nb[k]);
    const key = i => { const [x, y] = cellXY(world, i); return Math.hypot(x - fx, y - fy) + (world.cellBuilding[i] >= 0 ? 1.5 : 0); };
    ring.sort((a, b) => key(a) - key(b));
    for (const c of ring) { if (out.length >= n) break; if (!seen.has(c)) { seen.add(c); out.push(c); } }
  }
  return out;
}

// ───────────────────────────────────────────── search
const cellXY = (world, i) => [i % world.W, Math.floor(i / world.W)];

function initState(world, opts) {
  const blocked = world.perm.slice();
  return { blocked, built: new Uint8Array(world.buildings.length), left: world.buildings.length, stand: world.start,
    blob: swarmBlob(world, blocked, world.start, [], opts.workers), dir: null, cost: 0, walk: 0, steps: null };
}

/**
 * All moves from a state that keep the invariant, scored walk + penalties.
 * engine stands: the one cell the engine would stop on = nearest in-reach cell (ties → closest to the target centre,
 * which is where the pathfinder is heading). free stands: the k nearest in-reach cells.
 */
function expand(world, st, opts, only = null) {
  const { dist, parent } = dijkstra(world, st.blocked, st.stand);
  const out = [];
  const [sx, sy] = cellXY(world, st.stand);
  const k = opts.stands === "free" ? opts.k : 1;
  for (const B of world.buildings) {
    if (st.built[B.id] || (only != null && B.id !== only)) continue;
    const cands = B.stands.filter(s => !st.blocked[s] && dist[s] < Infinity);
    const toB = s => { const [x, y] = cellXY(world, s); return Math.hypot(B.c - x, B.r - y); };
    cands.sort((a, b) => (dist[a] - dist[b]) || (a === st.stand ? -1 : b === st.stand ? 1 : 0) || (toB(a) - toB(b)));
    for (const s of cands.slice(0, k)) {
      const blocked2 = st.blocked.slice(); for (const c of B.cells) blocked2[c] = 1;
      if (!viable(world, blocked2, s, st.built, B.id)) continue;
      const moved = s !== st.stand, walk = dist[s], pathCells = moved ? tracePath(parent, s) : [s];
      const seed = moved ? pathCells.slice(0, -1).reverse() : st.blob.slice(1);
      const blob = swarmBlob(world, blocked2, s, seed, opts.workers, st.stand);
      let pen = 0; const flags = [];
      // trailing workers (blob minus the lead) standing on the footprint = the swarm is in the way of its own next piece
      if (B.cells.some(c => st.blob.includes(c) && c !== st.stand)) { pen += opts.wClash; flags.push("clash"); }
      else if (B.cells.includes(st.stand)) { pen += opts.wSelf; flags.push("self"); }     // the lead has to step off its own cell
      if (blob.length < opts.workers) { pen += opts.wCramped; flags.push("cramped"); }
      let dir = st.dir;
      const [nx, ny] = cellXY(world, s);
      if (moved) {
        const mvx = nx - sx, mvy = ny - sy, len = Math.hypot(mvx, mvy);
        dir = [mvx / len, mvy / len];
        const tx = B.c - nx, ty = B.r - ny;
        if (mvx * tx + mvy * ty < -1e-9) { pen += opts.wBehind; flags.push("behind"); }
        if (st.dir && st.dir[0] * dir[0] + st.dir[1] * dir[1] < -1e-9) { pen += opts.wReverse; flags.push("reverse"); }
      }
      const tie = 0.001 * Math.hypot(B.c - nx, B.r - ny);
      // coverage: value of the stand this move ends on = remaining buildings it can reach without walking again.
      // Makes "step onto a future footprint that reaches the whole block" beat "stay and build what is near".
      let cover = 0;
      if (opts.wCover > 0) for (const id of world.covers[s]) if (!st.built[id] && id !== B.id) cover++;
      const penReal = pen;
      if (opts.noise > 0) pen += opts.noise * rand01();
      // lookahead: how far is the farthest remaining building's nearest stand from here once this is placed?
      // Ranks states that strand a corner behind a sealed interior below states that visit it while it is cheap.
      const la = (opts.wLook > 0 || opts.wSum > 0) ? lookahead(world, blocked2, s, st.built, B.id) : { far: 0, sum: 0 };
      out.push({ b: B.id, s, walk, pathCells, pen, penReal, flags, blob, blocked2, dir, far: la.far, sum: la.sum, cover, score: walk + pen + tie - opts.wCover * cover });
    }
  }
  return out;
}

/**
 * Per remaining building: walk to its nearest usable stand. far = the trip the plan cannot avoid; sum = how expensive
 * the rest has become (it jumps when the last cheap interior stand of a corner gets built over — the signal that
 * says "go stand on that future footprint now, build the corner from it, fill it in on the way back").
 */
function lookahead(world, blocked, stand, built, placed) {
  const { dist } = dijkstra(world, blocked, stand);
  let far = 0, sum = 0;
  for (const b of world.buildings) {
    if (built[b.id] || b.id === placed) continue;
    let best = Infinity; for (const s of b.stands) if (!blocked[s] && dist[s] < best) best = dist[s];
    if (best > far) far = best;
    sum += best;
  }
  return { far, sum };
}

function apply(st, cand) {
  const built = st.built.slice(); built[cand.b] = 1;
  return { blocked: cand.blocked2, built, left: st.left - 1, stand: cand.s, blob: cand.blob, dir: cand.dir,
    cost: st.cost + cand.walk + cand.penReal, walk: st.walk + cand.walk,
    steps: { b: cand.b, stand: cand.s, path: cand.pathCells, walk: cand.walk, flags: cand.flags, pen: cand.penReal, prev: st.steps } };
}

function planBeam(world, opts, width, from = null) {
  let beam = [from || initState(world, opts)];
  for (let step = beam[0].left; step > 0; step--) {
    const pool = [];
    for (const st of beam) for (const cand of expand(world, st, opts)) pool.push({ st, cand, total: st.cost + cand.score + opts.wLook * cand.far + opts.wSum * cand.sum });
    if (!pool.length) return { state: beam[0], stuck: `no viable move with ${step} left` };
    pool.sort((a, b) => a.total - b.total);
    const next = [], keys = new Set();
    for (const p of pool) {
      const key = Array.from(p.st.built, (v, i) => (v || i === p.cand.b) ? 1 : 0).join("") + ":" + p.cand.s;
      if (keys.has(key)) continue; keys.add(key);
      next.push(apply(p.st, p.cand)); if (next.length >= width) break;
    }
    beam = next;
  }
  return { state: beam[0], stuck: null };
}

/** Reading order — a shift-dragged queue. Same invariant; stops when it seals itself in. */
function planNaive(world, opts) {
  let st = initState(world, opts);
  for (const B of world.buildings) {
    const cands = expand(world, st, opts, B.id).sort((a, b) => a.walk - b.walk || a.pen - b.pen);
    if (!cands.length) return { state: st, stuck: `naive order seals itself off at #${world.buildings.length - st.left + 1} (${B.name} ${cellLabel(world, B.cells[0])})` };
    st = apply(st, cands[0]);
  }
  return { state: st, stuck: null };
}

/** Replay a fixed building order (a queue) with the stand rule; null when it seals itself off. */
function replayOrder(world, order, opts, from = null, fromStep = 0, trace = null) {
  let st = from || initState(world, opts);
  for (let i = fromStep; i < order.length; i++) {
    const cands = expand(world, st, opts, order[i]);
    if (!cands.length) return null;
    st = apply(st, cands.reduce((a, c) => c.score < a.score ? c : a));
    if (trace) trace[i + 1] = st;
  }
  return st;
}
function commonPrefix(a, b) { let k = 0; while (k < a.length && a[k] === b[k]) k++; return k; }
function orderOf(state) { return unrollSteps(state).map(s => s.b); }

let rand01 = () => 0;
function rng(seed) { let x = (seed >>> 0) || 1; return () => { x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0; return x / 4294967296; }; }

/**
 * Local search on the queue: relocate / reverse / swap segments, keep what walks less (penalties included).
 * Every candidate is re-simulated with the stand rule, so the result is always a legal, complete queue.
 */
function improve(world, order, opts, iters, seed) {
  const rand = rng(seed), n = order.length;
  let best = order.slice(), trace = [initState(world, opts)], bestState = replayOrder(world, best, opts, trace[0], 0, trace);
  if (!bestState) return { order: best, state: null, accepted: 0 };
  let bestCost = bestState.cost, accepted = 0;
  const accept = (o, st) => { best = o; bestCost = st.cost; const t = [trace[0]]; bestState = replayOrder(world, best, opts, t[0], 0, t); trace = t; accepted++; };
  for (let it = 0; it < iters; it++) {
    const o = best.slice(), m = rand();
    if (m < 0.2) {                                      // regrow: keep a prefix, greedy (noisy, coverage-aware) for the rest
      const keep = Math.floor(rand() * n);
      let st = trace[keep];
      rand01 = rand;
      const so = { ...opts, noise: 0.8, wCover: rand() < 0.5 ? 0 : 0.15 + rand() * 0.3 };
      const r = planBeam(world, so, 1, st);
      rand01 = () => 0;
      if (r.stuck) continue;
      const o2 = orderOf(r.state), st2 = replayOrder(world, o2, opts, trace[keep], keep);
      if (st2 && st2.cost < bestCost - 1e-9) accept(o2, st2);
      continue;
    } else if (m < 0.5) {                               // relocate a segment of 1-4
      const len = 1 + Math.floor(rand() * 4), i = Math.floor(rand() * (n - len)), seg = o.splice(i, len);
      const j = Math.floor(rand() * (o.length + 1)); o.splice(j, 0, ...seg);
    } else if (m < 0.85) {                              // reverse a segment of 2-8
      const len = 2 + Math.floor(rand() * 7), i = Math.floor(rand() * (n - len));
      const seg = o.slice(i, i + len).reverse(); o.splice(i, len, ...seg);
    } else {                                            // swap two
      const i = Math.floor(rand() * n), j = Math.floor(rand() * n); [o[i], o[j]] = [o[j], o[i]];
    }
    const k = commonPrefix(o, best), st = replayOrder(world, o, opts, trace[k], k);
    if (st && st.cost < bestCost - 1e-9) accept(o, st);
  }
  return { order: best, state: bestState, accepted };
}

/** Portfolio: greedy and beam seeds (with/without lookahead), best one polished by local search. */
function planAuto(world, opts) {
  const seeds = [], variants = [["greedy", { order: "greedy" }], ["beam", { order: "beam" }], ["greedy+look", { order: "greedy", wLook: 1 }]];
  for (const w of [0.15, 0.25, 0.4]) variants.push([`cover${w}`, { order: "greedy", wCover: w }], [`beam+cover${w}`, { order: "beam", wCover: w }]);
  for (const [label, o] of variants) {
    const so = { ...opts, ...o };
    const r = planBeam(world, so, so.order === "greedy" ? 1 : so.beam);
    if (!r.stuck) seeds.push({ label, state: replayOrder(world, orderOf(r.state), opts) || r.state });
  }
  if (!seeds.length) return { state: planBeam(world, opts, opts.beam).state, stuck: "no seed plan completed" };
  seeds.sort((a, b) => a.state.cost - b.state.cost);
  let best = seeds[0], improvements = 0;
  if (opts.improve > 0) for (const seed of seeds.slice(0, 2)) {
    const imp = improve(world, orderOf(seed.state), opts, opts.improve, opts.seed);
    improvements += imp.accepted;
    if (imp.state && imp.state.cost < best.state.cost - 1e-9) best = { label: seed.label + "→ls", state: imp.state };
  }
  return { state: best.state, stuck: null, note: `seeds: ${seeds.map(s => `${s.label} ${s.state.walk.toFixed(1)}`).join(", ")} → local search ${opts.improve} iters ×2 seeds, ${improvements} improvements → ${best.label} cost ${best.state.cost.toFixed(1)}` };
}

// ───────────────────────────────────────────── plan → steps + metrics
function unrollSteps(st) { const s = []; for (let n = st.steps; n; n = n.prev) s.push(n); return s.reverse(); }

function cellLabel(world, i) { return `(${Math.floor(i / world.W) - world.m},${(i % world.W) - world.m})`; }

function analyze(world, result, opts) {
  const steps = unrollSteps(result.state), bld = world.buildings, n = world.H * world.W;
  const walkedAt = new Int32Array(n).fill(-1);                 // first step index a cell was walked/stood on
  const mark = (c, i) => { if (walkedAt[c] < 0) walkedAt[c] = i; };
  mark(world.start, 0); for (const c of initState(world, opts).blob) mark(c, 0);
  const rows = [], stands = []; let cumWalk = 0, cumTime = 0, buildSec = 0;
  const bpTotal = opts.workers * world.builder.bp;
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i], B = bld[s.b];
    for (const c of s.path) mark(c, i + 1);
    const bt = TYPES[B.type].buildTime / bpTotal, wt = s.walk * PITCH / world.builder.speed;
    cumWalk += s.walk; cumTime += wt + bt; buildSec += bt;
    const [sx, sy] = cellXY(world, s.stand);
    const reachSlack = world.builder.range + B.radius - Math.hypot((B.c - sx) * PITCH, (B.r - sy) * PITCH);
    if (!stands.length || stands[stands.length - 1].stand !== s.stand) stands.push({ stand: s.stand, from: i + 1, to: i + 1, walk: s.walk, n: 1 });
    else { const g = stands[stands.length - 1]; g.to = i + 1; g.n++; }
    rows.push({ i: i + 1, b: s.b, type: B.type, name: B.name, cell: cellLabel(world, B.cells[0]), stand: cellLabel(world, s.stand), walk: s.walk, walkSec: wt, buildSec: bt, reachSlack, flags: s.flags, cum: cumTime });
  }
  const doubleBack = [];
  for (let i = 0; i < steps.length; i++) {
    const B = bld[steps[i].b];
    const w = Math.min(...B.cells.map(c => walkedAt[c] < 0 ? Infinity : walkedAt[c]));
    if (w <= i) doubleBack.push({ step: i + 1, cell: cellLabel(world, B.cells[0]), walkedAtStep: w });
  }
  const count = f => steps.filter(s => s.flags.includes(f)).length;
  return {
    rows, stands, steps, doubleBack, walkedAt,
    summary: {
      buildings: bld.length, placed: steps.length, stuck: result.stuck,
      walkCells: cumWalk, walkElmos: cumWalk * PITCH, walkSec: cumWalk * PITCH / world.builder.speed, buildSec, totalSec: cumTime,
      moves: steps.filter(s => s.walk > 0).length, stands: stands.length,
      clash: count("clash"), self: count("self"), behind: count("behind"), reverse: count("reverse"), cramped: count("cramped"),
      doubleBack: doubleBack.length, penalty: steps.reduce((a, s) => a + s.pen, 0),
    },
  };
}

// ───────────────────────────────────────────── rendering
function renderGrid(world, cellFn, tight) {
  const { H, W, m, pat } = world, lines = [];
  const r0 = tight ? m - 1 : 0, r1 = tight ? m + pat.h : H - 1, c0 = tight ? m - 1 : 0, c1 = tight ? m + pat.w : W - 1;
  for (let r = r0; r <= r1; r++) {
    let line = "";
    for (let c = c0; c <= c1; c++) line += cellFn(r * W + c, r, c);
    lines.push(line.replace(/\s+$/, ""));
  }
  return lines.join("\n");
}
function isInside(world, i) { const r = Math.floor(i / world.W), c = i % world.W; return r >= world.m && c >= world.m && r < world.m + world.pat.h && c < world.m + world.pat.w; }

/** Build-order view: every footprint shows the step it goes down in; lanes '.'; '@' start; margin blank. */
function renderOrder(world, an) {
  const order = new Map(); for (const s of an.rows) order.set(s.b, s.i);
  return renderGrid(world, i => {
    const b = world.cellBuilding[i];
    if (i === world.start) return " @ ";
    if (b >= 0) return order.has(b) ? String(order.get(b)).padStart(2, " ") + " " : " ? ";
    if (world.perm[i]) return " # ";
    return isInside(world, i) ? " . " : "   ";
  }, true);
}

/** Route view: stands numbered in visit order, walked cells '+', footprints by letter. */
function renderRoute(world, an) {
  const standNo = new Map(); an.stands.forEach((g, k) => { if (!standNo.has(g.stand)) standNo.set(g.stand, k + 1); });
  const walked = new Set(); for (const s of an.steps) for (const c of s.path) walked.add(c);
  return renderGrid(world, i => {
    if (standNo.has(i)) return "#" + String(standNo.get(i)).padEnd(2, " ");
    if (walked.has(i)) return " + ";
    const b = world.cellBuilding[i];
    if (b >= 0) return " " + world.buildings[b].type.toLowerCase() + " ";
    if (world.perm[i]) return " # ";
    return isInside(world, i) ? " . " : "   ";
  }, true);
}

/** One frame after step k: built lowercase, pending uppercase, 'o' swarm, '@' lead, '*' the piece just placed, '+' walked this step. */
function renderFrame(world, an, k) {
  const built = new Set(); for (let i = 0; i < k; i++) built.add(an.steps[i].b);
  const s = an.steps[k - 1], blob = new Set(replayBlob(world, an, k)), walked = new Set(s ? s.path : []);
  return renderGrid(world, i => {
    if (s && i === s.stand) return "@";
    if (blob.has(i)) return "o";
    if (walked.has(i)) return "+";
    const b = world.cellBuilding[i];
    if (b >= 0) return b === (s && s.b) ? "*" : built.has(b) ? world.buildings[b].type.toLowerCase() : world.buildings[b].type;
    if (world.perm[i]) return "#";
    return isInside(world, i) ? "." : " ";
  }, true);
}
function replayBlob(world, an, k) {
  let st = initState(world, an.opts);
  for (let i = 0; i < k; i++) { const c = expand(world, st, an.opts, an.steps[i].b).find(c => c.s === an.steps[i].stand); if (!c) break; st = apply(st, c); }
  return st.blob;
}

const pad = (s, n) => String(s).padEnd(n), padL = (s, n) => String(s).padStart(n);
const mmss = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const indent = s => s.split("\n").map(l => "  " + l).join("\n");

function printPlan(world, an, opts, label) {
  const S = an.summary;
  console.log(`\n== ${label} ==  ${opts.workers}× ${opts.builder} (reach ${world.builder.range}+${PITCH / 2} elmos = ${((world.builder.range + PITCH / 2) / PITCH).toFixed(2)} cells) · stands ${opts.stands} · beam ${opts.order === "beam" ? opts.beam : opts.order === "greedy" ? 1 : "-"}`);
  if (S.stuck) console.log(`  ✘ ${S.stuck} — ${S.placed}/${S.buildings} placed`);
  if (an.note) console.log(`  ${an.note}`);
  console.log(`  walk ${S.walkCells.toFixed(1)} cells = ${S.walkElmos.toFixed(0)} elmos = ${S.walkSec.toFixed(0)}s · build ${S.buildSec.toFixed(0)}s · total ${mmss(S.totalSec)} · ${S.stands} stands / ${S.moves} moves`);
  console.log(`  swarm: clash ${S.clash} · self-step ${S.self} · behind ${S.behind} · reverse ${S.reverse} · cramped ${S.cramped} · double-back footprints ${S.doubleBack} (walked first, built later)`);
  console.log(`\n  build order (step number on each footprint, '@' start, '.' lane):\n` + indent(renderOrder(world, an)));
  console.log(`\n  route (#n = n-th stand, '+' walked, letters = footprints):\n` + indent(renderRoute(world, an)));
  console.log(`\n  stands:`);
  for (const g of an.stands) console.log(`    ${g.walk > 0 ? `walk ${g.walk.toFixed(1)} → ` : "start   "}${pad(cellLabel(world, g.stand), 8)} builds #${g.from}${g.to > g.from ? `-#${g.to}` : ""} (${g.n})`);
  console.log(`\n  queue: ` + an.rows.map(r => `${r.type}${r.cell}`).join(" "));
  if (!opts.quiet) {
    console.log(`\n  ${padL("#", 3)} ${pad("build", 11)} ${pad("cell", 8)} ${pad("stand", 8)} ${padL("walk", 5)} ${padL("slack", 6)} ${padL("t", 6)}  flags`);
    for (const r of an.rows) console.log(`  ${padL(r.i, 3)} ${pad(r.name, 11)} ${pad(r.cell, 8)} ${pad(r.stand, 8)} ${padL(r.walk ? r.walk.toFixed(1) : "-", 5)} ${padL(r.reachSlack.toFixed(0), 6)} ${padL(mmss(r.cum), 6)}  ${r.flags.join(",")}`);
  }
  if (opts.frames) {
    for (let k = opts.frames; k <= an.steps.length; k += opts.frames) console.log(`\n  after #${k} (${an.rows[k - 1].name} ${an.rows[k - 1].cell}, stand ${an.rows[k - 1].stand}):\n` + indent(renderFrame(world, an, k)));
    if (an.steps.length % opts.frames) console.log(`\n  after #${an.steps.length} (done):\n` + indent(renderFrame(world, an, an.steps.length)));
  }
}

function printCompare(runs) {
  console.log(`\n== Orders compared ==`);
  console.log(`  ${pad("order", 10)} ${padL("placed", 7)} ${padL("walk", 6)} ${padL("walk s", 7)} ${padL("total", 7)} ${padL("stands", 7)} ${padL("clash", 6)} ${padL("self", 5)} ${padL("behind", 7)} ${padL("cramped", 8)} ${padL("dbl-back", 9)} ${padL("cost", 6)}  stuck`);
  for (const r of runs) { const S = r.an.summary; console.log(`  ${pad(r.label, 10)} ${padL(S.placed + "/" + S.buildings, 7)} ${padL(S.walkCells.toFixed(1), 6)} ${padL(S.walkSec.toFixed(0), 7)} ${padL(mmss(S.totalSec), 7)} ${padL(S.stands, 7)} ${padL(S.clash, 6)} ${padL(S.self, 5)} ${padL(S.behind, 7)} ${padL(S.cramped, 8)} ${padL(S.doubleBack, 9)} ${padL((S.walkCells + S.penalty).toFixed(1), 6)}  ${S.stuck || ""}`); }
}

// ───────────────────────────────────────────── API
/** "W(3,0) W(5,0) …" / "3,0 5,0 …" (pattern coords, or a file holding them) → building ids in that order. */
function parseQueue(world, spec) {
  const text = fs.existsSync(spec) ? fs.readFileSync(spec, "utf8") : spec;
  const order = [], seen = new Set();
  for (const m of text.matchAll(/(-?\d+)\s*,\s*(-?\d+)/g)) {
    const r = Number(m[1]) + world.m, c = Number(m[2]) + world.m;
    const b = (r >= 0 && c >= 0 && r < world.H && c < world.W) ? world.cellBuilding[world.at(r, c)] : -1;
    if (b < 0) throw new Error(`queue cell (${m[1]},${m[2]}) holds no building`);
    if (!seen.has(b)) { seen.add(b); order.push(b); }
  }
  for (const b of world.buildings) if (!seen.has(b.id)) order.push(b.id);      // anything unlisted goes last, pattern order
  return order;
}

function loadPattern(ref) {
  if (PATTERNS[ref]) return { name: ref, ...PATTERNS[ref] };
  if (fs.existsSync(ref)) return { name: path.basename(ref), desc: "file", start: "left", rows: fs.readFileSync(ref, "utf8") };
  throw new Error(`unknown pattern ${ref}; --list shows the shipped ones or pass a text file`);
}

/** Plan a pattern: returns { world, an, pattern } with an.summary / an.rows (the queue) / an.stands / an.doubleBack. */
function plan(patternRef, options = {}) {
  const opts = { ...defaults(), ...options };
  const p = typeof patternRef === "string" ? loadPattern(patternRef) : patternRef;
  if (opts.start == null) opts.start = p.start || "left";
  const world = makeWorld(parsePattern(p.rows), opts);
  let result;
  if (opts.queue) { const order = parseQueue(world, opts.queue); const st = replayOrder(world, order, opts); result = st ? { state: st, stuck: null } : { state: initState(world, opts), stuck: "queue seals itself off" }; }
  else if (opts.order === "naive") result = planNaive(world, opts);
  else if (opts.order === "auto") result = planAuto(world, opts);
  else result = planBeam(world, opts, opts.order === "greedy" ? 1 : opts.beam);
  const an = analyze(world, result, opts); an.opts = opts; an.note = result.note || null;
  return { world, an, pattern: p };
}

function defaults() {
  return { workers: 4, builder: "con_bot", start: null, order: "auto", queue: null, beam: 6, stands: "engine", k: 3, margin: 2, frames: 0, compare: false, json: null, quiet: false,
    // penalty weights in walked-cell equivalents (1 cell = 48 elmos = 1.3 s for a con bot); all --wX overridable
    wClash: 2, wBehind: 1, wReverse: 0.25, wCramped: 1, wSelf: 0.5, wLook: 0, wSum: 0, wCover: 0, noise: 0, improve: 1000, seed: 1 };
}

function parseArgs(argv) {
  const a = { ...defaults(), pattern: null, list: false, selftest: false };
  const rest = [];
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t === "--workers") a.workers = Math.max(1, Number(argv[++i]) || 1);
    else if (t === "--builder") a.builder = argv[++i];
    else if (t === "--start") a.start = argv[++i];
    else if (t === "--order") a.order = argv[++i];
    else if (t === "--stands") a.stands = argv[++i];
    else if (t === "--beam") a.beam = Math.max(1, Number(argv[++i]) || 1);
    else if (t === "--k") a.k = Math.max(1, Number(argv[++i]) || 1);
    else if (t === "--margin") a.margin = Math.max(1, Number(argv[++i]) || 1);
    else if (t === "--frames") a.frames = Number(argv[++i]) || 0;
    else if (t === "--json") a.json = argv[++i];
    else if (t === "--queue") a.queue = argv[++i];
    else if (t === "--improve") a.improve = Number(argv[++i]) || 0;
    else if (t === "--seed") a.seed = Number(argv[++i]) || 1;
    else if (t === "--compare") a.compare = true;
    else if (t === "--quiet") a.quiet = true;
    else if (t === "--list") a.list = true;
    else if (t === "--selftest") a.selftest = true;
    else if (/^--w[A-Z]/.test(t)) a[t.slice(2)] = Number(argv[++i]);            // --wClash 5, --wLook 1, --wSum 0.3 …
    else rest.push(t);
  }
  if (!BUILDERS[a.builder]) throw new Error(`--builder must be one of ${Object.keys(BUILDERS).join("|")}`);
  if (!["engine", "free"].includes(a.stands)) throw new Error("--stands engine|free");
  if (!["auto", "beam", "greedy", "naive"].includes(a.order)) throw new Error("--order auto|beam|greedy|naive");
  a.pattern = rest[0] || "windfarm_4x4";
  return a;
}

function selftest() {
  let fails = 0;
  const check = (ok, msg) => { console.log(`  ${ok ? "✔" : "✘"} ${msg}`); if (!ok) fails++; };
  for (const name of Object.keys(PATTERNS)) for (const workers of [1, 4]) {
    const { world, an } = plan(name, { workers, quiet: true });
    const S = an.summary;
    check(!S.stuck && S.placed === S.buildings, `${name} ×${workers}: all ${S.buildings} placed (walk ${S.walkCells.toFixed(1)} cells, ${S.stands} stands, ${S.clash} clashes)`);
    // replay the queue on a fresh grid: every stand walkable + reachable, every placement in reach, swarm can exit at the end
    const blocked = world.perm.slice(); let ok = true, prev = world.start;
    for (const s of an.steps) {
      const { dist } = dijkstra(world, blocked, prev); if (!(dist[s.stand] < Infinity) || blocked[s.stand]) ok = false;
      const B = world.buildings[s.b]; if (!B.stands.includes(s.stand)) ok = false;
      for (const c of B.cells) blocked[c] = 1; prev = s.stand;
    }
    const vis = reachable(world, blocked, prev); let exit = false; for (let i = 0; i < vis.length; i++) if (vis[i] && isMargin(world, i)) exit = true;
    check(ok && exit, `${name} ×${workers}: replay valid — every stand reachable, every piece in reach, swarm can exit`);
  }
  const bad = plan("courtyard_7x7", { order: "naive", quiet: true }).an.summary;
  check(!!bad.stuck, `courtyard_7x7 naive order walls itself in (${bad.stuck}) — the invariant catches it`);
  const dbl = plan("block_8x8", { quiet: true }).an.summary;
  check(dbl.doubleBack > 0, `block_8x8 auto stands on ${dbl.doubleBack} footprints before building them (walk space first)`);
  const solo = plan("windfarm_4x4", { workers: 1, quiet: true }).an.summary, swarm = plan("windfarm_4x4", { workers: 4, quiet: true }).an.summary;
  check(solo.clash === 0 && solo.cramped === 0 && solo.walkCells <= swarm.walkCells + 1e-9, `solo builder never clashes and walks no more than the swarm plan (${solo.walkCells.toFixed(1)} ≤ ${swarm.walkCells.toFixed(1)})`);
  console.log(fails ? `\n${fails} check(s) failed` : `\nall checks passed`);
  process.exit(fails ? 1 : 0);
}

function toJSON(r) {
  const w = r.world, xz = i => [((i % w.W) - w.m + 0.5) * PITCH, (Math.floor(i / w.W) - w.m + 0.5) * PITCH];
  return { order: r.label, pattern: r.pattern.name, pitch: PITCH, builder: r.an.opts.builder, workers: r.an.opts.workers, stands: r.an.opts.stands, summary: r.an.summary,
    queue: r.an.rows.map((row, i) => ({ ...row, standXZ: xz(r.an.steps[i].stand), targetXZ: [(w.buildings[row.b].c - w.m + 0.5) * PITCH, (w.buildings[row.b].r - w.m + 0.5) * PITCH], path: r.an.steps[i].path.map(xz) })),
    stands: r.an.stands.map(g => ({ ...g, cell: cellLabel(w, g.stand), xz: xz(g.stand) })), doubleBack: r.an.doubleBack };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.list) { for (const [k, v] of Object.entries(PATTERNS)) console.log(`${pad(k, 14)} ${v.rows.length}×${parsePattern(v.rows).w}  ${v.desc}`); return; }
  if (args.selftest) return selftest();
  const p = loadPattern(args.pattern);
  console.log(`\nBAR Build Pather — ${p.name}: ${p.desc}`);
  const counts = {}; for (const row of parsePattern(p.rows).cells) for (const ch of row) if (TYPES[ch]) counts[ch] = (counts[ch] || 0) + 1;
  console.log(`  cells: ${Object.entries(counts).map(([k, v]) => `${v} ${TYPES[k].name}`).join(" · ")} · start ${args.start || p.start}`);
  if (args.compare) {
    const runs = [];
    for (const order of ["naive", "greedy", "beam", "auto"]) { const r = plan(p, { ...args, order, queue: null }); runs.push({ label: order, ...r }); }
    runs.push({ label: "walk-only", ...plan(p, { ...args, order: "auto", queue: null, wClash: 0, wBehind: 0, wReverse: 0, wCramped: 0, wSelf: 0 }) });
    if (args.queue) runs.unshift({ label: "queue", ...plan(p, { ...args }) });
    printCompare(runs);
    console.log(`  (walk-only = auto with every swarm penalty at 0: the shortest route regardless of bunching; --workers 1 makes auto behave the same)`);
    const best = runs.find(r => r.label === "auto");
    printPlan(best.world, best.an, best.an.opts, "auto plan");
    if (args.json) fs.writeFileSync(args.json, JSON.stringify(runs.map(r => toJSON(r)), null, 1));
  } else {
    const r = plan(p, args);
    printPlan(r.world, r.an, r.an.opts, `${args.queue ? "queue" : args.order} plan`);
    if (args.json) fs.writeFileSync(args.json, JSON.stringify(toJSON({ label: args.order, ...r }), null, 1));
  }
  if (args.json) console.log(`\nwrote ${args.json}`);
}

module.exports = { PITCH, BUILDERS, TYPES, PATTERNS, parsePattern, makeWorld, plan, planBeam, planNaive, planAuto, replayOrder, improve, parseQueue, analyze, renderOrder, renderRoute, renderFrame, dijkstra, reachable, viable, swarmBlob };

if (require.main === module) { try { main(); } catch (e) { console.error("✘ " + (e.stack || e.message)); process.exit(1); } }

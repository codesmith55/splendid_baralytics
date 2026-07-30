// expand-goals.mjs — barbots planner, layer 2.
//
// Goal DAG in (the output of parse-intent.mjs) -> flat, costed ACTION LIST out.
// A goal is a *declaration* ("take 7 mex"); an action is a *unit of work* one actor
// performs ("worker1 builds the mex at pos:mex_5, walking there first"). This layer
// turns counts / countToTotal / countToTarget / group goals / factory queues into the
// concrete N actions that carry them out, attaches resource costs from data/units.json,
// and inserts walk legs (time from the bar-calc grid calibration) wherever an action
// implies movement.
//
// It does NOT project resources over time — that is the next layer (the eco_engine
// projectOption bridge), which consumes this action list. We only cost each action.
//
// No live-game dependencies. Pure goal-DAG JSON -> action-list JSON.

import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';
import { parseIntentFile } from './parse-intent.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const DATA = JSON.parse(readFileSync(join(here, 'data', 'units.json'), 'utf8'));

// ── Tunables (documented in planner/README.md) ──────────────────────────────
// Map positions are STUBBED as named placeholders ("pos:mex_5") until a real map
// reader resolves them. Because we don't yet know inter-site distances, every walk
// leg uses one provisional hop length. 4.0 grid squares matches bar_unified.py's
// expansion-mex distance and is far enough that a walk leg is non-trivial (a real
// reader will replace this per-leg).
const DEFAULT_HOP_SQUARES = 4.0;
const ELMOS_PER_GRID_SQUARE = DATA._meta.elmosPerGridSquare; // 48.3
// `infinite X` (a *repeat in a factory queue) is unbounded. We materialize the first
// FACTORY_QUEUE_HORIZON concrete actions of the queue, then emit ONE action with
// repeat:true standing in for the open-ended tail. 8 covers the opening's worker/laz
// rotation with headroom without flooding the list.
const FACTORY_QUEUE_HORIZON = 8;

const round = (x, p = 1) => { const m = 10 ** p; return Math.round(x * m) / m; };

// ── Builder / cost resolution ───────────────────────────────────────────────
/** commander vs con profile. See data/units.json `_builderResolution`. */
function resolveBuilder(actor) {
  const a = String(actor).toLowerCase();
  if (a === 'com' || a === 'commander') return DATA.builders.commander;
  return DATA.builders.con;
}

function unitData(type) {
  const u = DATA.units[type];
  if (!u) throw new Error(`no cost data for unit type "${type}" (add it to planner/data/units.json)`);
  return u;
}

/** {metal_cost, energy_cost, build_time_s} for building `type` with `builderBP` power. */
function costFor(type, builderBP) {
  const u = unitData(type);
  return {
    metal_cost: u.metal,
    energy_cost: u.energy,
    build_time_s: round(u.buildWork / builderBP),
  };
}

/** Walk seconds for one provisional hop with this builder (honors build range:
 *  the builder stops once the target is within range, so close sites cost 0). */
function hopWalkTime(builder) {
  const gap = DEFAULT_HOP_SQUARES * ELMOS_PER_GRID_SQUARE;
  const walked = Math.max(0, gap - builder.buildRange);
  return round(walked / builder.speed);
}

// ── Expansion context ───────────────────────────────────────────────────────
// Shared mutable state threaded through goal expansion, in DAG order.
function newCtx() {
  return {
    actions: [],
    tally: {},        // unit type -> running built count (drives site indices + to-total math)
    actorPos: {},     // actor -> current position placeholder
    exitIds: {},      // goalId -> [action ids that "complete" the goal] (for `after` wiring)
  };
}

function posOf(ctx, actor) {
  return ctx.actorPos[actor] ?? `pos:${actor}_start`;
}

/** Push a build/queue action, attaching a walk leg if the actor must move to `site`. */
function emitBuild(ctx, { id, goalId, type, actor, target, site, builderBP, after, extra }) {
  const builder = resolveBuilder(actor);
  const action = {
    id, goalId, type, actor, target,
    ...costFor(target, builderBP ?? builder.buildPower),
    after,
  };
  if (site) {
    const from = posOf(ctx, actor);
    if (from !== site) {
      action.walk_leg_from = from;
      action.walk_leg_to = site;
      action.walk_time_s = hopWalkTime(builder);
    }
    ctx.actorPos[actor] = site;
  }
  if (extra) Object.assign(action, extra);
  ctx.actions.push(action);
  return action;
}

// ── Goal expanders ──────────────────────────────────────────────────────────
/** N actors for N actions: single `who` repeated, a pool round-robined, or pool:any. */
function actorList(who, n) {
  if (Array.isArray(who)) return Array.from({ length: n }, (_, k) => who[k % who.length]);
  if (typeof who === 'string') return Array(n).fill(who);
  return Array(n).fill('pool:any');
}

/** Resolve count + the running site index, updating the tally. */
function countAndStart(ctx, g) {
  const type = g.build;
  const cur = ctx.tally[type] ?? 0;
  let n, start;
  if (g.count != null) { n = g.count; start = cur + 1; ctx.tally[type] = cur + n; }
  else if (g.countToTotal != null) { n = Math.max(0, g.countToTotal - cur); start = cur + 1; ctx.tally[type] = Math.max(cur, g.countToTotal); }
  else if (g.countToTarget != null) { n = Math.max(0, g.countToTarget - cur); start = cur + 1; ctx.tally[type] = Math.max(cur, g.countToTarget); }
  else { n = 1; start = cur + 1; ctx.tally[type] = cur + 1; }
  return { n, start, type };
}

function expandBuild(ctx, g, entryAfter) {
  const { n, start, type } = countAndStart(ctx, g);
  const actors = actorList(g.who, n);
  const parallel = !!g.parallel;
  const ids = [];
  const carry = {};
  if (g.priority) carry.priority = g.priority;
  if (g.conditional) carry.conditional = g.conditional;
  for (let k = 0; k < n; k++) {
    const id = `${g.id}#${k + 1}`;
    const after = parallel || k === 0 ? entryAfter : [`${g.id}#${k}`];
    emitBuild(ctx, {
      id, goalId: g.id, type: 'build', actor: actors[k], target: type,
      site: `pos:${type}_${start + k}`, after,
      extra: Object.keys(carry).length ? { ...carry } : undefined,
    });
    ids.push(id);
  }
  // Exit = whatever a downstream `after` should wait on: all of a parallel group,
  // else just the last link of the chain.
  ctx.exitIds[g.id] = parallel ? ids : ids.length ? [ids[ids.length - 1]] : [];
}

function expandProduce(ctx, g, entryAfter) {
  const factory = g.factory;
  const factoryBP = unitData(factory).buildPower;
  const concrete = [];
  let repeatUnit = null;
  for (const it of g.produce) {
    if (it && typeof it === 'object' && it.repeat) repeatUnit = it.repeat;
    else concrete.push(it);
  }
  // Materialize the queue front: concrete items, padded with the repeat unit up to
  // the horizon so the projection sees a realistic factory program.
  const queue = [...concrete];
  if (repeatUnit) while (queue.length < FACTORY_QUEUE_HORIZON) queue.push(repeatUnit);

  const ids = [];
  for (let k = 0; k < queue.length; k++) {
    const id = `${g.id}#${k + 1}`;
    const after = k === 0 ? entryAfter : [`${g.id}#${k}`];
    const extra = g.assist ? { assist: g.assist } : undefined;
    emitBuild(ctx, { id, goalId: g.id, type: 'queue_at', actor: factory, target: queue[k], builderBP: factoryBP, after, extra });
    ids.push(id);
  }
  // One action standing in for the unbounded `*repeat` tail.
  if (repeatUnit) {
    const id = `${g.id}#repeat`;
    emitBuild(ctx, {
      id, goalId: g.id, type: 'queue_at', actor: factory, target: repeatUnit, builderBP: factoryBP,
      after: ids.length ? [ids[ids.length - 1]] : entryAfter,
      extra: { repeat: true, ...(g.assist ? { assist: g.assist } : {}) },
    });
  }
  // Exit = the last concrete (bounded) action; the repeat tail is ongoing, not a gate.
  ctx.exitIds[g.id] = ids.length ? [ids[ids.length - 1]] : [];
}

/** give_unit / reclaim_zone — single action, no build cost, walk leg to its target. */
function expandMeta(ctx, g, entryAfter) {
  const id = `${g.id}#1`;
  const builder = resolveBuilder(g.unit);
  const zero = { metal_cost: 0, energy_cost: 0, build_time_s: 0 };
  let action;
  if (g.meta === 'give_unit') {
    const to = `pos:${g.timer ? g.timer.target : g.to}`;
    action = { id, goalId: g.id, type: 'give_unit', actor: g.unit, target: g.to, ...zero, after: entryAfter };
    if (g.timer) action.timer = g.timer;
    const from = posOf(ctx, g.unit);
    if (from !== to) { action.walk_leg_from = from; action.walk_leg_to = to; action.walk_time_s = hopWalkTime(builder); }
    ctx.actorPos[g.unit] = to; // the unit has left for the ally; it is no longer ours after this
  } else if (g.meta === 'reclaim_zone') {
    const to = `pos:${g.zone.map}_zone`;
    action = { id, goalId: g.id, type: 'reclaim_zone', actor: g.unit, target: g.zone, ...zero, after: entryAfter };
    if (g.filter) action.filter = g.filter;
    const from = posOf(ctx, g.unit);
    if (from !== to) { action.walk_leg_from = from; action.walk_leg_to = to; action.walk_time_s = hopWalkTime(builder); }
    ctx.actorPos[g.unit] = to;
  } else {
    throw new Error(`unknown meta kind: ${g.meta}`);
  }
  ctx.actions.push(action);
  ctx.exitIds[g.id] = [id];
}

// ── Top-level ───────────────────────────────────────────────────────────────
/** Expand a goal DAG (parse-intent.mjs output) into a flat, costed action list. */
export function expandGoalDag(dag) {
  const ctx = newCtx();
  for (const g of dag.goals) {
    const entryAfter = g.after ? (ctx.exitIds[g.after] ?? []) : [];
    if (g.build) expandBuild(ctx, g, entryAfter);
    else if (g.factory) expandProduce(ctx, g, entryAfter);
    else if (g.meta) expandMeta(ctx, g, entryAfter);
    else throw new Error(`goal ${g.id}: unrecognized goal kind`);
  }
  // Checkpoints become marker actions gated on their goal's completion.
  for (const c of dag.checkpoints ?? []) {
    ctx.actions.push({
      id: c.id, goalId: c.goal, type: 'checkpoint', metric: c.metric,
      metal_cost: 0, energy_cost: 0, build_time_s: 0,
      after: ctx.exitIds[c.goal] ?? [],
    });
  }
  const out = {};
  if (dag.intentId) out.intentId = dag.intentId;
  out.actions = ctx.actions;
  return out;
}

/** Read an intent .md file, parse it, and expand to an action list. */
export function expandIntentFile(path) {
  return expandGoalDag(parseIntentFile(path));
}

// CLI: node expand-goals.mjs <intent.md>  -> prints action list JSON to stdout.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const path = process.argv[2];
  if (!path) {
    console.error('usage: node expand-goals.mjs <intent.md>');
    process.exit(2);
  }
  try {
    console.log(JSON.stringify(expandIntentFile(path), null, 2));
  } catch (e) {
    console.error(`expand error: ${e.message}`);
    process.exit(1);
  }
}

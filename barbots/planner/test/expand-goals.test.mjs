// Test runner for expand-goals.mjs — no framework, runs on plain node.
//   node planner/test/expand-goals.test.mjs
//
// 1. Golden test: the reference intent's goal DAG expands to the snapshotted action list.
// 2. Construct tests: each goal kind expands to the documented action shape
//    (countToTarget, group/parallel, factory queue + *repeat, give_unit, reclaim_zone,
//    countToTotal tally, walk-leg insertion, after-chain wiring, checkpoint).

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { compileIntentBlock, parseIntentFile } from '../parse-intent.mjs';
import { expandGoalDag, expandIntentFile } from '../expand-goals.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, '..', '..');

let pass = 0;
let fail = 0;

/** Order-insensitive deep equality (sorts object keys before comparing). */
function canon(v) {
  if (Array.isArray(v)) return v.map(canon);
  if (v && typeof v === 'object') {
    return Object.keys(v).sort().reduce((o, k) => ((o[k] = canon(v[k])), o), {});
  }
  return v;
}
function eq(a, b) {
  return JSON.stringify(canon(a)) === JSON.stringify(canon(b));
}

function check(name, got, want) {
  if (eq(got, want)) {
    pass++;
    console.log(`  ok   ${name}`);
  } else {
    fail++;
    console.log(`  FAIL ${name}`);
    console.log(`       got:  ${JSON.stringify(canon(got))}`);
    console.log(`       want: ${JSON.stringify(canon(want))}`);
  }
}

function assert(name, cond, detail = '') {
  if (cond) { pass++; console.log(`  ok   ${name}`); }
  else { fail++; console.log(`  FAIL ${name} ${detail}`); }
}

/** Expand a one-line intent block and return its action list. */
const expand = (block) => expandGoalDag(compileIntentBlock(block));
/** The actions belonging to a given goal id. */
const forGoal = (actions, goalId) => actions.filter((a) => a.goalId === goalId);

// --- 1. Golden ---------------------------------------------------------------
console.log('golden:');
const got = expandIntentFile(join(repo, 'intents', '7mex-25wind-fast-t2.md'));
const golden = JSON.parse(readFileSync(join(here, 'golden', '7mex-25wind-fast-t2.actions.json'), 'utf8'));
check('reference intent expands to snapshot', got, golden);
// Sanity: golden is also the live parse->expand pipeline output.
check('expandGoalDag(parseIntentFile) == expandIntentFile',
  expandGoalDag(parseIntentFile(join(repo, 'intents', '7mex-25wind-fast-t2.md'))), got);

// --- 2. Constructs -----------------------------------------------------------
console.log('constructs:');

// count -> N sequential actions, after-chained, costed from units.json
{
  const a = expand('build com: 3 mex id=g1').actions;
  check('count=3 -> 3 actions', a.length, 3);
  check('  sequential after-chain', [a[0].after, a[1].after, a[2].after], [[], ['g1#1'], ['g1#2']]);
  check('  mex cost from data', { m: a[0].metal_cost, e: a[0].energy_cost, t: a[0].build_time_s }, { m: 50, e: 500, t: 6 });
}

// countToTarget -> (target - prior) actions; prior of same type subtracts
check('countToTarget=25 from zero -> 25 actions',
  expand('build: wind to-target 25 id=g1').actions.length, 25);
{
  const a = expand('build com: 2 wind id=g1\nbuild: wind to-target 25 id=g2').actions;
  check('countToTarget subtracts prior tally (2 + 23)', [forGoal(a, 'g1').length, forGoal(a, 'g2').length], [2, 23]);
}

// countToTotal -> raises a shared running total across goals
{
  const a = expand('build com: 3 mex id=g1\nbuild [com,w1,w2]: mex to-total 6 parallel id=g2 after=g1\nbuild: mex to-total 7 id=g3 after=g2').actions;
  check('to-total tally 3 -> 6 -> 7 yields 3,3,1',
    ['g1', 'g2', 'g3'].map((g) => forGoal(a, g).length), [3, 3, 1]);
  // site indices continue across goals: g2 mexes are #4,#5,#6
  check('site indices continue across goals', forGoal(a, 'g2').map((x) => x.walk_leg_to),
    ['pos:mex_4', 'pos:mex_5', 'pos:mex_6']);
}

// group / parallel -> one action per pool member, all gated on the prereq, not chained
{
  const a = expand('build com: solar id=g0\nbuild [com,w1,w2]: mex to-total 3 parallel id=g1 after=g0').actions;
  const g1 = forGoal(a, 'g1');
  check('parallel pool -> 3 distinct actors', g1.map((x) => x.actor), ['com', 'w1', 'w2']);
  check('parallel actions all gate on prereq, none chained',
    g1.map((x) => x.after), [['g0#1'], ['g0#1'], ['g0#1']]);
}

// factory queue: *repeat -> concrete prefix padded to horizon + one repeat action
{
  const a = forGoal(expand('produce botlab: con, laz, con, laz, *con id=g1').actions, 'g1');
  check('queue padded to horizon (8) + 1 repeat tail', a.length, 9);
  check('  queue front materializes the repeat unit',
    a.slice(0, 8).map((x) => x.target), ['con', 'laz', 'con', 'laz', 'con', 'con', 'con', 'con']);
  const rep = a.find((x) => x.id.endsWith('#repeat'));
  check('  repeat tail flagged + after last concrete', { repeat: rep.repeat, after: rep.after }, { repeat: true, after: ['g1#8'] });
  check('  queue items are queue_at on the factory', [a[0].type, a[0].actor], ['queue_at', 'botlab']);
}
{
  const a = forGoal(expand('produce botlab: con, con assist=com id=g1').actions, 'g1');
  check('bounded queue (no repeat) -> exactly its items', a.length, 2);
  check('  assist carried onto actions', a[0].assist, 'com');
}

// meta give_unit -> single give action, walk leg to the timer target, timer carried
{
  const a = forGoal(expand('meta give_unit worker2: to=ally:air timer=walk_arrival:ally_air.bottomLeftMex id=g1').actions, 'g1');
  check('give_unit -> 1 action', a.length, 1);
  check('  give action shape',
    { type: a[0].type, actor: a[0].actor, target: a[0].target, to: a[0].walk_leg_to, timer: a[0].timer },
    { type: 'give_unit', actor: 'worker2', target: 'ally:air', to: 'pos:ally_air.bottomLeftMex', timer: { type: 'walk_arrival', target: 'ally_air.bottomLeftMex' } });
  assert('  give has a walk leg with time', a[0].walk_time_s > 0);
}

// meta reclaim_zone -> single reclaim action carrying zone + filter, walk leg to zone
{
  const a = forGoal(expand('meta reclaim_zone laz1: zone=all_that_glitters:[1,2,3,5,6,7]@900 filter=features:rocks id=g1').actions, 'g1');
  check('reclaim_zone -> 1 action', a.length, 1);
  check('  reclaim action shape',
    { type: a[0].type, actor: a[0].actor, filter: a[0].filter, to: a[0].walk_leg_to, zone: a[0].target.map },
    { type: 'reclaim_zone', actor: 'laz1', filter: 'features:rocks', to: 'pos:all_that_glitters_zone', zone: 'all_that_glitters' });
}

// walk-leg insertion: a leg appears only when the actor moves to a new site
{
  const a = expand('build com: 2 mex id=g1').actions;
  check('first build walks from actor start', [a[0].walk_leg_from, a[0].walk_leg_to], ['pos:com_start', 'pos:mex_1']);
  check('second build walks from the previous site', [a[1].walk_leg_from, a[1].walk_leg_to], ['pos:mex_1', 'pos:mex_2']);
  assert('walk time is positive at the default hop', a[0].walk_time_s > 0);
}
// factory-produced units pop out at the factory -> no walk leg
assert('queue_at actions have no walk leg',
  forGoal(expand('produce botlab: con, con id=g1').actions, 'g1').every((x) => x.walk_leg_to === undefined));

// builder resolution: commander (BP 300) builds faster than a con (BP 80)
{
  const com = forGoal(expand('build com: mex id=g1').actions, 'g1')[0];
  const con = forGoal(expand('build w1: mex id=g1').actions, 'g1')[0];
  assert('commander builds the same mex faster than a con bot', com.build_time_s < con.build_time_s,
    `(com ${com.build_time_s}s vs con ${con.build_time_s}s)`);
}

// checkpoint -> a marker action gated on its goal's completion
{
  const a = expand('build: t2mex id=g_t2mex\ncheckpoint t2mex_online: goal=g_t2mex metric=lost_seconds').actions;
  const cp = a.find((x) => x.type === 'checkpoint');
  check('checkpoint marker gated on goal exit',
    { id: cp.id, metric: cp.metric, after: cp.after }, { id: 't2mex_online', metric: 'lost_seconds', after: ['g_t2mex#1'] });
}

// --- 3. Errors ---------------------------------------------------------------
console.log('errors:');
try {
  expand('build com: mex id=g1'.replace('mex', 'frobnitz'));
  fail++; console.log('  FAIL unknown unit type (expected throw)');
} catch (e) {
  if (/no cost data for unit type/.test(e.message)) { pass++; console.log('  ok   unknown unit type rejected'); }
  else { fail++; console.log(`  FAIL unknown unit type (wrong message: ${e.message})`); }
}

// --- summary -----------------------------------------------------------------
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);

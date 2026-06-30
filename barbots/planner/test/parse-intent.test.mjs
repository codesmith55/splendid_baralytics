// Test runner for parse-intent.mjs — no framework, runs on plain node.
//   node planner/test/parse-intent.test.mjs
//
// 1. Golden test: the reference intent compiles to the hand-compiled sketch.
// 2. Unit tests: each shorthand construct compiles to the documented shape.
// 3. Error tests: malformed input is rejected with a useful message.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { compileIntentBlock, parseIntentFile } from '../parse-intent.mjs';

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

function throws(name, fn, re) {
  try {
    fn();
    fail++;
    console.log(`  FAIL ${name} (expected throw)`);
  } catch (e) {
    if (re && !re.test(e.message)) {
      fail++;
      console.log(`  FAIL ${name} (message "${e.message}" did not match ${re})`);
    } else {
      pass++;
      console.log(`  ok   ${name}`);
    }
  }
}

const goal = (block) => compileIntentBlock(block).goals[0];

// --- 1. Golden ---------------------------------------------------------------
console.log('golden:');
const dag = parseIntentFile(join(repo, 'intents', '7mex-25wind-fast-t2.md'));
const golden = JSON.parse(readFileSync(join(here, 'golden', '7mex-25wind-fast-t2.json'), 'utf8'));
check('reference intent == hand-compiled sketch', dag, golden);

// --- 2. Constructs -----------------------------------------------------------
console.log('constructs:');
check('sequenced build with count + who', goal('build com: 3 mex id=g1'),
  { id: 'g1', build: 'mex', count: 3, who: 'com' });

check('single build, no count', goal('build com: botlab id=g1 after=g0\nbuild com: x id=g0'),
  { id: 'g1', build: 'botlab', who: 'com', after: 'g0' });

check('group parallel count-to-total', goal('build [com,w1,w2]: mex to-total 6 parallel id=g1'),
  { id: 'g1', build: 'mex', countToTotal: 6, who: ['com', 'w1', 'w2'], parallel: true });

check('no-who build with count-to-target + conditional',
  goal('build: wind to-target 25 conditional=wind:solar_equivalent_eps id=g1'),
  { id: 'g1', build: 'wind', countToTarget: 25, conditional: { on: 'wind', lowWindSubstitute: 'solar_equivalent_eps' } });

check('priority', goal('build: t2lab priority=critical id=g1'),
  { id: 'g1', build: 't2lab', priority: 'critical' });

check('factory produce with assist', goal('produce botlab: con, con assist=com id=g1'),
  { id: 'g1', factory: 'botlab', produce: ['con', 'con'], assist: 'com' });

check('factory produce with infinite repeat', goal('produce botlab: con, laz, *con id=g1'),
  { id: 'g1', factory: 'botlab', produce: ['con', 'laz', { repeat: 'con' }] });

check('meta give_unit with walk timer',
  goal('meta give_unit worker2: to=ally:air timer=walk_arrival:ally_air.bottomLeftMex id=g1'),
  { id: 'g1', meta: 'give_unit', unit: 'worker2', to: 'ally:air', timer: { type: 'walk_arrival', target: 'ally_air.bottomLeftMex' } });

check('meta reclaim_zone',
  goal('meta reclaim_zone laz1: zone=all_that_glitters:[1,2,3,5,6,7]@900 filter=features:rocks id=g1'),
  { id: 'g1', meta: 'reclaim_zone', unit: 'laz1', zone: { map: 'all_that_glitters', positions: [1, 2, 3, 5, 6, 7], radiusElmos: 900 }, filter: 'features:rocks' });

check('checkpoint', compileIntentBlock('build: t2mex id=g_t2mex\ncheckpoint t2mex_online: goal=g_t2mex metric=lost_seconds').checkpoints[0],
  { id: 't2mex_online', goal: 'g_t2mex', metric: 'lost_seconds' });

check('comments and blank lines ignored', compileIntentBlock('# a comment\n\nbuild: mex id=g1\n').goals.length, 1);

// --- 3. Errors ---------------------------------------------------------------
console.log('errors:');
throws('unknown verb', () => compileIntentBlock('frobnicate foo: bar id=g1'), /unknown verb/);
throws('missing colon', () => compileIntentBlock('build com 3 mex id=g1'), /missing ':'/);
throws('missing id', () => compileIntentBlock('build com: 3 mex'), /missing id/);
throws('duplicate id', () => compileIntentBlock('build: mex id=g1\nbuild: solar id=g1'), /duplicate goal id/);
throws('dangling after', () => compileIntentBlock('build: mex id=g1 after=nope'), /after unknown goal/);
throws('checkpoint to unknown goal', () => compileIntentBlock('checkpoint c: goal=ghost metric=x'), /unknown goal/);

// --- summary -----------------------------------------------------------------
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);

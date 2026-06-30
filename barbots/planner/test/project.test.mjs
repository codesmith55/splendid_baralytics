// Test runner for project.mjs — no framework, runs on plain node.
//   node planner/test/project.test.mjs
//
// 1. Golden test: the reference intent's action list projects to the snapshotted timeline.
// 2. Invariant tests: structural properties that should hold regardless of exact numbers.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { expandIntentFile } from '../expand-goals.mjs';
import { projectActionList } from '../project.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, '..', '..');

let pass = 0;
let fail = 0;

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
    console.log(`       got:  ${JSON.stringify(canon(got)).slice(0, 200)}`);
    console.log(`       want: ${JSON.stringify(canon(want)).slice(0, 200)}`);
  }
}

function assert(name, cond, detail = '') {
  if (cond) { pass++; console.log(`  ok   ${name}`); }
  else { fail++; console.log(`  FAIL ${name} ${detail}`); }
}

// ── 1. Golden ─────────────────────────────────────────────────────────────────
console.log('golden:');
const expanded = expandIntentFile(join(repo, 'intents', '7mex-25wind-fast-t2.md'));
const result   = projectActionList(expanded, { wind: 10 });
const golden   = JSON.parse(readFileSync(join(here, 'golden', '7mex-25wind-fast-t2.project.json'), 'utf8'));

check('reference intent projects to snapshot', result, golden);

// ── 2. Invariants ─────────────────────────────────────────────────────────────
console.log('invariants:');

const { actions, goalTimelines, econSeries } = result;

// All actions annotated with timing fields
assert('all actions have projectedStart',
  actions.every(a => typeof a.projectedStart === 'number'));
assert('all actions have projectedEnd',
  actions.every(a => typeof a.projectedEnd === 'number'));
assert('all actions have stallSec',
  actions.every(a => typeof a.stallSec === 'number'));

// Build time monotonicity: projectedEnd > projectedStart for build actions
assert('build actions end after they start',
  actions.filter(a => a.type === 'build').every(a => a.projectedEnd >= a.projectedStart),
  actions.filter(a => a.type === 'build' && a.projectedEnd < a.projectedStart).map(a => a.id).join(', '));

// After-chain respected: each action starts no earlier than its deps end
{
  const endById = Object.fromEntries(actions.map(a => [a.id, a.projectedEnd]));
  const violations = actions.filter(a =>
    (a.after ?? []).some(dep => endById[dep] !== undefined && a.projectedStart < endById[dep] - 0.15)
  );
  assert('after-deps respected (start ≥ dep end)', violations.length === 0,
    violations.map(a => `${a.id} starts ${a.projectedStart} but dep ends ${Math.max(...a.after.map(d => endById[d]))}`).join('; '));
}

// Factory queue doesn't start before factory build completes
{
  const factoryEnd = actions.find(a => a.type === 'build' && a.target === 'botlab')?.projectedEnd ?? 0;
  const queueStarts = actions.filter(a => a.type === 'queue_at' && a.actor === 'botlab').map(a => a.projectedStart);
  assert('factory queue starts after factory build',
    queueStarts.every(t => t >= factoryEnd - 0.15),
    `factory done=${factoryEnd}, queue starts=${queueStarts.join(',')}`);
}

// Goal timelines span their member actions
{
  const actionsByGoal = {};
  for (const a of actions) {
    (actionsByGoal[a.goalId] ??= []).push(a);
  }
  const bad = goalTimelines.filter(g => {
    const acts = actionsByGoal[g.id] ?? [];
    if (!acts.length) return false;
    const minStart = Math.min(...acts.map(a => a.projectedStart));
    const maxEnd   = Math.max(...acts.map(a => a.projectedEnd));
    return Math.abs(g.projectedStart - minStart) > 0.15 || Math.abs(g.projectedEnd - maxEnd) > 0.15;
  });
  assert('goal timelines span member action range', bad.length === 0,
    bad.map(g => g.id).join(', '));
}

// Commander acts as 300 BP actor (builds faster than con's 80 BP on same unit)
{
  // first mex is built by com; if any later mex is built by a con, com's build time is shorter
  const comMex = actions.find(a => a.type === 'build' && a.target === 'mex' && a.actor === 'com');
  const conMex = actions.find(a => a.type === 'build' && a.target === 'mex' && a.actor !== 'com');
  if (comMex && conMex) {
    const comT = comMex.projectedEnd - comMex.projectedStart - (comMex.walk_time_s ?? 0);
    const conT = conMex.projectedEnd - conMex.projectedStart - (conMex.walk_time_s ?? 0);
    assert('commander builds mex faster than con bot', comT < conT,
      `com=${comT.toFixed(1)}s con=${conT.toFixed(1)}s`);
  }
}

// econSeries: values are finite and metal/energy never go deeply negative (model floors at 0)
assert('econSeries non-empty', econSeries.length > 0);
assert('econSeries metal ≥ 0 throughout',
  econSeries.every(p => p.metal >= -0.1),
  econSeries.filter(p => p.metal < -0.1).map(p => `t=${p.t} m=${p.metal}`).join(', '));
assert('econSeries energy ≥ -1 throughout',
  econSeries.every(p => p.energy >= -1),
  econSeries.filter(p => p.energy < -1).map(p => `t=${p.t} e=${p.energy}`).join(', '));

// ── Summary ───────────────────────────────────────────────────────────────────
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);

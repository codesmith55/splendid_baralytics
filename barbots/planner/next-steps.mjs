#!/usr/bin/env node
/**
 * next-steps.mjs — barbots planner: "given a location or reference to game
 * state, return the next projected actions"
 *
 * This is the compound entrypoint most external callers want. It stitches
 * together the four planner layers:
 *
 *   state ref  ──►  extract-position  ──┐
 *                                       ├──►  project.mjs  ──►  next N actions
 *   intent    ──►  parse-intent ──►  expand-goals ──┘
 *
 * State references:
 *   - `--position <name>`     read positions/named/<name>.json
 *   - `--demo <path.sdfz>`    headless BAR demo parse at time `--t`
 *   - `--state <path.json>`   read an already-serialized eco_engine createState
 *   - (default)                use ARM opening (3 mex + commander)
 *
 * Intent references:
 *   - `--intent <path.md>`    absolute or relative to barbots/intents/
 *   - `--intent-name <name>`  short form: resolves to intents/<name>.md
 *
 * Output selection:
 *   - `--n <N>`               return the next N actions after `--from-t`
 *                             (default N=5)
 *   - `--from-t <seconds>`    only include actions whose projectedStart >=
 *                             this time (default 0 → whole projection)
 *   - `--summary`             emit a compact table to stderr instead of JSON
 *
 * Usage:
 *   node planner/next-steps.mjs \
 *        --position pos_50s_legpos6 \
 *        --intent-name legion-pos6-t2-fusion \
 *        --n 5 --from-t 60
 *
 * Programmatic API:
 *   import { nextSteps } from './planner/next-steps.mjs';
 *   const { actions, projection } = await nextSteps({
 *     stateRef: { kind: 'position', name: 'pos_50s_legpos6' },
 *     intent:   { kind: 'name', name: 'legion-pos6-t2-fusion' },
 *     n: 5, fromT: 60,
 *   });
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseIntentFile } from './parse-intent.mjs';
import { expandGoalDag } from './expand-goals.mjs';
import { projectActionList, UNITS_EXT } from './project.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname  = path.dirname(__filename);
const BARBOTS    = path.resolve(__dirname, '..');
const POS_DIR    = path.join(BARBOTS, 'positions', 'named');
const INTENT_DIR = path.join(BARBOTS, 'intents');


// ── State resolution ─────────────────────────────────────────────────────────

/** Load the eco_engine initial state from a variety of reference types.
 *  Returns `null` on default (project.mjs will use ARM opening). */
export async function resolveState(ref) {
  if (!ref || ref.kind === 'default') return null;

  if (ref.kind === 'literal') {
    // Already a createState() result — pass through.
    return ref.state;
  }

  if (ref.kind === 'state-file') {
    // A previously-saved createState JSON.
    const p = path.isAbsolute(ref.path) ? ref.path : path.resolve(process.cwd(), ref.path);
    const raw = JSON.parse(fs.readFileSync(p, 'utf8'));
    // The saved file may be the whole extract-position output OR just createState.
    return raw.createState ?? raw;
  }

  if (ref.kind === 'position') {
    const p = path.join(POS_DIR, `${ref.name}.json`);
    if (!fs.existsSync(p)) {
      throw new Error(
        `position file not found: ${p}\n` +
        `create one with: node planner/extract-position.mjs --demo <path.sdfz> --t <sec> --out ${p}`
      );
    }
    const raw = JSON.parse(fs.readFileSync(p, 'utf8'));
    return raw.createState ?? raw;
  }

  if (ref.kind === 'demo') {
    // Headless demo parse: shell out to extract-position and capture stdout.
    // Cross-platform via node's own binary.
    const { execFileSync } = await import('node:child_process');
    const args = [
      path.join(BARBOTS, 'planner', 'extract-position.mjs'),
      '--demo', ref.path,
      '--t', String(ref.t ?? 50),
    ];
    if (ref.player) args.push('--player', ref.player);
    const out = execFileSync(process.execPath, args, { encoding: 'utf8' });
    const parsed = JSON.parse(out);
    return parsed.createState ?? parsed;
  }

  throw new Error(`unknown state ref kind: ${ref.kind}`);
}


// ── Intent resolution ────────────────────────────────────────────────────────

export function resolveIntentPath(ref) {
  if (ref.kind === 'path') {
    return path.isAbsolute(ref.path) ? ref.path : path.resolve(process.cwd(), ref.path);
  }
  if (ref.kind === 'name') {
    return path.join(INTENT_DIR, `${ref.name}.md`);
  }
  throw new Error(`unknown intent ref kind: ${ref.kind}`);
}

/** Enumerate available intents (data — the .md files under intents/). */
export function listIntents() {
  if (!fs.existsSync(INTENT_DIR)) return [];
  return fs.readdirSync(INTENT_DIR)
    .filter(f => f.endsWith('.md'))
    .map(f => ({ name: f.replace(/\.md$/, ''), path: path.join(INTENT_DIR, f) }));
}


// ── The compound capability ──────────────────────────────────────────────────

/** The main verb: state ref + intent ref → next N projected actions.
 *
 *  Returns:
 *    {
 *      intent:        { id, path, dagGoals, expandedActions },
 *      state:         { source, ecoT0 } | null,
 *      projection:    full projectActionList output,
 *      nextActions:   the first N actions whose projectedStart >= fromT,
 *      nextCheckpoints: goal-level checkpoints hit in the next window,
 *    }
 */
export async function nextSteps({
  stateRef = { kind: 'default' },
  intent,
  n = 5,
  fromT = 0,
  wind = 10,
  sampleSec = 5,
} = {}) {
  if (!intent) throw new Error('nextSteps: `intent` is required');

  const intentPath = resolveIntentPath(intent);
  const initialState = await resolveState(stateRef);

  const dag       = await parseIntentFile(intentPath);
  const expanded  = expandGoalDag(dag);
  const projection = projectActionList(expanded, {
    initialState, wind, sampleSec,
  });

  const nextActions = projection.actions
    .filter(a => a.projectedStart >= fromT)
    .sort((a, b) => a.projectedStart - b.projectedStart)
    .slice(0, n);

  const nextCheckpoints = projection.goalTimelines
    .filter(g => g.projectedEnd >= fromT)
    .sort((a, b) => a.projectedEnd - b.projectedEnd)
    .slice(0, n);

  return {
    intent: {
      id: dag.intentId ?? path.basename(intentPath, '.md'),
      path: intentPath,
      dagGoals: dag.goals?.length ?? 0,
      expandedActions: expanded.actions?.length ?? 0,
    },
    state: initialState ? {
      source: describeStateRef(stateRef),
      ecoT0: {
        metal: initialState.metal ?? null,
        energy: initialState.energy ?? null,
        mexes: initialState.mexes ?? null,
      },
    } : { source: 'default:ARM-opening' },
    projection,
    nextActions,
    nextCheckpoints,
    windowFrom: fromT,
    n,
  };
}

function describeStateRef(ref) {
  switch (ref.kind) {
    case 'position':  return `position:${ref.name}`;
    case 'demo':      return `demo:${ref.path}@t=${ref.t ?? 50}`;
    case 'state-file': return `state-file:${ref.path}`;
    case 'literal':   return 'literal';
    default:          return 'default';
  }
}


// ── CLI ──────────────────────────────────────────────────────────────────────

function parseFlags(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) continue;
    const k = a.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) { out[k] = true; }
    else { out[k] = next; i++; }
  }
  return out;
}

async function main() {
  const flags = parseFlags(process.argv.slice(2));

  if (flags['list-intents']) {
    console.log(JSON.stringify(listIntents(), null, 2));
    return;
  }

  let stateRef = { kind: 'default' };
  if (flags.position)   stateRef = { kind: 'position', name: flags.position };
  else if (flags.demo)  stateRef = { kind: 'demo', path: flags.demo, t: +(flags.t ?? 50), player: flags.player };
  else if (flags.state) stateRef = { kind: 'state-file', path: flags.state };

  let intent;
  if (flags['intent-name']) intent = { kind: 'name', path: null, name: flags['intent-name'] };
  else if (flags.intent)    intent = { kind: 'path', path: flags.intent };
  else {
    console.error('Usage: node planner/next-steps.mjs (--position <name> | --demo <path.sdfz> [--t <sec>] | --state <json>) (--intent <path.md> | --intent-name <name>) [--n <N>] [--from-t <sec>] [--wind <e/s>] [--summary]');
    console.error('   or: node planner/next-steps.mjs --list-intents');
    process.exit(1);
  }

  const result = await nextSteps({
    stateRef, intent,
    n: +(flags.n ?? 5),
    fromT: +(flags['from-t'] ?? 0),
    wind: +(flags.wind ?? 10),
  });

  if (flags.summary) {
    console.error(`\n  intent ${result.intent.id}  from ${result.state.source}  window t>=${result.windowFrom}`);
    console.error('  #  t_start   t_end   type       actor          target                 stall');
    console.error('  ' + '-'.repeat(80));
    for (const [i, a] of result.nextActions.entries()) {
      const stall = a.stallSec > 0 ? `⚠ ${a.stallSec}s` : '';
      console.error(`  ${String(i+1).padEnd(2)} ${String(a.projectedStart).padStart(6)}s ${String(a.projectedEnd).padStart(6)}s  ${(a.type ?? '?').padEnd(10)} ${(a.actor ?? '').padEnd(14)} ${(a.target ?? '').padEnd(22)} ${stall}`);
    }
    console.error();
  }
  console.log(JSON.stringify(result, null, 2));
}

if ((process.argv[1] ?? '').replace(/\\/g, '/').endsWith('next-steps.mjs')) {
  main().catch(err => { console.error(err.message); process.exit(1); });
}

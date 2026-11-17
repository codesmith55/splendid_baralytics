// parse-intent.mjs — barbots planner entry point.
//
// Reads an intent `.md` file, extracts its machine-readable ```intent``` block, and
// compiles the terse build shorthand into a goal DAG (the shape in
// docs/intent-language.md). This is the planner's front door: every downstream layer
// (eco_engine projection, stall pass, adapter gating) consumes a goal DAG.
//
// SCOPE: this parses a *structured shorthand* (grammar in docs/intent-grammar.md), not
// free-form English. The human prose at the top of an intent file is for people; the
// fenced ```intent``` block is the machine input. Prose -> shorthand is out of scope.
//
// No live-game dependencies. Pure text -> JSON.

import { readFileSync } from 'node:fs';
import { basename } from 'node:path';
import { pathToFileURL } from 'node:url';

/** Extract the contents of the first ```intent ... ``` fenced block. */
export function extractIntentBlock(md) {
  const m = md.match(/```intent\s*\n([\s\S]*?)```/);
  if (!m) throw new Error('no ```intent``` block found in file');
  return m[1];
}

/** Split a body string into positional tokens and a kwargs map.
 *  A kwarg is a token shaped `key=value` (key is [a-z-]+). Everything else is
 *  positional. Bracket lists must not contain spaces, so whitespace tokenizing is safe. */
function splitTokens(body) {
  const tokens = body.trim().split(/\s+/).filter(Boolean);
  const positionals = [];
  const kwargs = {};
  for (const tok of tokens) {
    const eq = tok.indexOf('=');
    if (eq > 0 && /^[a-z][a-z-]*$/.test(tok.slice(0, eq))) {
      kwargs[tok.slice(0, eq)] = tok.slice(eq + 1);
    } else {
      positionals.push(tok);
    }
  }
  return { positionals, kwargs };
}

/** `[a,b,c]` -> ['a','b','c']; `com` -> 'com'; '' -> undefined. */
function parseWho(s) {
  if (!s) return undefined;
  if (s.startsWith('[') && s.endsWith(']')) {
    return s.slice(1, -1).split(',').map((x) => x.trim()).filter(Boolean);
  }
  return s;
}

/** `wind:solar_equivalent_eps` -> { on:'wind', lowWindSubstitute:'solar_equivalent_eps' } */
function parseConditional(s) {
  const [on, lowWindSubstitute] = s.split(':');
  return { on, lowWindSubstitute };
}

/** `walk_arrival:ally_air.bottomLeftMex` -> { type:'walk_arrival', target:'ally_air.bottomLeftMex' } */
function parseTimer(s) {
  const i = s.indexOf(':');
  return { type: s.slice(0, i), target: s.slice(i + 1) };
}

/** `all_that_glitters:[1,2,3,5,6,7]@900` -> { map, positions:[...], radiusElmos:900 } */
function parseZone(s) {
  const m = s.match(/^([^:]+):\[([^\]]*)\]@(\d+)$/);
  if (!m) throw new Error(`bad zone spec: ${s}`);
  return {
    map: m[1],
    positions: m[2].split(',').map((x) => Number(x.trim())),
    radiusElmos: Number(m[3]),
  };
}

function parseBuild(who, body) {
  const { positionals, kwargs } = splitTokens(body);
  const g = { id: kwargs.id };
  let i = 0;
  if (/^\d+$/.test(positionals[i])) g.count = Number(positionals[i++]);
  g.build = positionals[i++];
  while (i < positionals.length) {
    const tok = positionals[i++];
    if (tok === 'to-total') g.countToTotal = Number(positionals[i++]);
    else if (tok === 'to-target') g.countToTarget = Number(positionals[i++]);
    else if (tok === 'parallel') g.parallel = true;
    else throw new Error(`unexpected token in build: ${tok}`);
  }
  const w = parseWho(who);
  if (w !== undefined) g.who = w;
  if (kwargs.priority) g.priority = kwargs.priority;
  if (kwargs.conditional) g.conditional = parseConditional(kwargs.conditional);
  if (kwargs.after) g.after = kwargs.after;
  return g;
}

function parseProduce(factory, body) {
  // Split positionals (item list, comma-separated) from kwargs.
  const { positionals, kwargs } = splitTokens(body);
  const produce = positionals
    .join(' ')
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)
    .map((item) => (item.startsWith('*') ? { repeat: item.slice(1) } : item));
  const g = { id: kwargs.id, factory, produce };
  if (kwargs.assist) g.assist = kwargs.assist;
  if (kwargs.after) g.after = kwargs.after;
  return g;
}

function parseMeta(kind, unit, body) {
  const { kwargs } = splitTokens(body);
  const g = { id: kwargs.id, meta: kind, unit };
  if (kind === 'give_unit') {
    if (kwargs.to) g.to = kwargs.to;
    if (kwargs.timer) g.timer = parseTimer(kwargs.timer);
  } else if (kind === 'reclaim_zone') {
    if (kwargs.zone) g.zone = parseZone(kwargs.zone);
    if (kwargs.filter) g.filter = kwargs.filter;
  } else {
    throw new Error(`unknown meta kind: ${kind}`);
  }
  if (kwargs.after) g.after = kwargs.after;
  return g;
}

function parseCheckpoint(id, body) {
  const { kwargs } = splitTokens(body);
  return { id, goal: kwargs.goal, metric: kwargs.metric };
}

/** Compile the text of an ```intent``` block into a goal DAG. */
export function compileIntentBlock(block, { intentId } = {}) {
  const goals = [];
  const checkpoints = [];
  const lines = block.split('\n');
  for (let n = 0; n < lines.length; n++) {
    const raw = lines[n];
    const line = raw.replace(/\s+$/, '');
    if (!line.trim() || line.trim().startsWith('#')) continue; // blank / comment
    const colon = line.indexOf(':');
    if (colon < 0) throw new Error(`line ${n + 1}: missing ':' -> ${line.trim()}`);
    const head = line.slice(0, colon).trim().split(/\s+/);
    const body = line.slice(colon + 1).trim();
    const verb = head[0];
    try {
      if (verb === 'build') {
        goals.push(parseBuild(head.slice(1).join(' '), body));
      } else if (verb === 'produce') {
        goals.push(parseProduce(head[1], body));
      } else if (verb === 'meta') {
        goals.push(parseMeta(head[1], head[2], body));
      } else if (verb === 'checkpoint') {
        checkpoints.push(parseCheckpoint(head[1], body));
      } else {
        throw new Error(`unknown verb: ${verb}`);
      }
    } catch (e) {
      throw new Error(`line ${n + 1}: ${e.message} -> ${line.trim()}`);
    }
  }
  validate(goals, checkpoints);
  const dag = {};
  if (intentId) dag.intentId = intentId;
  dag.checkpoints = checkpoints;
  dag.goals = goals;
  return dag;
}

/** Structural checks: unique goal ids, every `after`/checkpoint target resolves. */
function validate(goals, checkpoints) {
  const ids = new Set();
  for (const g of goals) {
    if (!g.id) throw new Error(`goal missing id= : ${JSON.stringify(g)}`);
    if (ids.has(g.id)) throw new Error(`duplicate goal id: ${g.id}`);
    ids.add(g.id);
  }
  for (const g of goals) {
    if (g.after && !ids.has(g.after)) throw new Error(`goal ${g.id} after unknown goal: ${g.after}`);
  }
  for (const c of checkpoints) {
    if (!c.goal || !ids.has(c.goal)) throw new Error(`checkpoint ${c.id} references unknown goal: ${c.goal}`);
  }
}

/** Read an intent .md file and return its compiled goal DAG. intentId = filename stem. */
export function parseIntentFile(path) {
  const md = readFileSync(path, 'utf8');
  const intentId = basename(path).replace(/\.md$/, '');
  return compileIntentBlock(extractIntentBlock(md), { intentId });
}

// CLI: node parse-intent.mjs <intent.md>  -> prints goal DAG JSON to stdout.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const path = process.argv[2];
  if (!path) {
    console.error('usage: node parse-intent.mjs <intent.md>');
    process.exit(2);
  }
  try {
    console.log(JSON.stringify(parseIntentFile(path), null, 2));
  } catch (e) {
    console.error(`parse error: ${e.message}`);
    process.exit(1);
  }
}

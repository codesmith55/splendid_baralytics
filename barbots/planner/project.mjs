// project.mjs — planner Layer 3: eco_engine projection bridge
//
// Feeds expand-goals.mjs output through the eco simulator to attach per-action and
// per-goal projected start/end times plus M/E stall diagnostics.
//
// CLI:
//   node planner/project.mjs intents/<name>.md [--wind=N]
//
// Exports:
//   projectActionList(actionList, opts) -> { intentId, actions, goalTimelines, econSeries }
//
// Simulation model (sequential, single-actor-per-action):
//   Each action is simulated with its assigned actor's BP drawing from the shared M/E pool.
//   Parallel actions (same entry constraint, no inter-dep) are serialized here — they will
//   show sequential end times even though the real game executes them concurrently.
//   The stall diagnostics are still valid: M/E curves reflect the true pool draw sequence.

import { createState, tick, applyCompletion, UNITS as ENG_UNITS }
    from '../../gex_research/process/lib/sim/eco_engine.mjs';
import { expandGoalDag } from './expand-goals.mjs';
import { parseIntentFile } from './parse-intent.mjs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

// ── Unit table: eco_engine native keys + barbots-specific extensions ──────────
// eco_engine's applyCompletion dispatches on unitKey against state.units[unitKey].gives
// and on the special-case guards `if (unitKey === "solar")` etc.
// Setting state.units = UNITS_EXT makes those gives available for extended targets.
export const UNITS_EXT = {
    ...ENG_UNITS,
    // ARM units
    con:        { ...ENG_UNITS.worker },
    t2mex:      { m: 620, e: 7700,  bp: 14900, gives: { mex: 1 } },
    botlab:     { m: 620, e: 1200,  bp: 6500,  gives: {} },
    t2lab:      { m: 720, e: 1700,  bp: 16000, gives: {} },
    laz:        { m: 110, e: 1100,  bp: 4500,  gives: {} },
    // Legion units (costs from legion_unitdefs.json)
    leg_mex:    { m: 50,  e: 500,   bp: 1880,  gives: { mex: 1 } },                      // legmex — same gives as ARM mex
    leg_factory:{ m: 470, e: 1050,  bp: 5000,  gives: {} },                               // leglab — builder added via FACTORY_BUILDERS
    leg_con:    { m: 100, e: 1600, bp: 3250, gives: { builderBp: 75, ePerSec: 5 } },      // legck — own gives (75 BP/+5E), NOT the ARM worker's 80/+7
    leg_medmex: { m: 250, e: 5000,  bp: 5000,  gives: { mex: 1 } },                      // legmext15 — proxied as +mex; actual income delta differs
    leg_turret: { ...ENG_UNITS.conTurret, m: 230, e: 3200, bp: 5300 },                   // legnanotc — costs already match eco_engine's conTurret
    leg_estor:  { ...ENG_UNITS.eStorage,  m: 175, e: 1800, bp: 4260 },                   // legestor — same gives {storE:6000}, different costs
    // Legion T2 (costs from legion_unitdefs.json)
    leg_t2factory: { m: 2600, e: 16000, bp: 25200, gives: {} },                          // legalab — builder via FACTORY_BUILDERS (600 BP)
    leg_t2con:     { m: 410,  e: 6900,  bp: 9300,  gives: { builderBp: 195, ePerSec: 14 } }, // legack — T2 con bot, +195 BP
    leg_fusion:    { m: 4000, e: 25000, bp: 66000, gives: { ePerSec: 950 } },             // legfus — T2 fusion, +950 E/s
};

// Factory completions add a builder to the eco state's builder pool
const FACTORY_BUILDERS = {
    botlab:        { name: 'botlab',        bp: 100, priority: 'low' },
    t2lab:         { name: 't2lab',         bp: 200, priority: 'low' },
    leg_factory:   { name: 'leg_factory',   bp: 150, priority: 'low' },
    leg_t2factory: { name: 'leg_t2factory', bp: 600, priority: 'low' },
};

// Actor → build power override (expand-goals uses actor profiles from units.json;
// commanders have 300 BP, everyone else defaults to con/worker 80 BP)
const ACTOR_BP = { com: 300, commander: 300 };
const DEFAULT_BP = 80;
function actorBP(actor) { return ACTOR_BP[actor] ?? DEFAULT_BP; }

const DT = 1 / 30;  // tick resolution matching eco_engine default
const r1 = (x) => Math.round(x * 10) / 10;

// ── Topological sort: respect `after` dep links ───────────────────────────────
function topoSort(actions) {
    const byId = new Map(actions.map(a => [a.id, a]));
    const done  = new Set();
    const out   = [];
    function visit(a) {
        if (done.has(a.id)) return;
        for (const dep of (a.after ?? [])) { const d = byId.get(dep); if (d) visit(d); }
        done.add(a.id);
        out.push(a);
    }
    for (const a of actions) visit(a);
    return out;
}

// ── Main: project an expanded action list ─────────────────────────────────────
/**
 * Project a costed action list (from expand-goals.mjs) through eco_engine.
 *
 * @param {object} actionList  - { intentId, actions } from expand-goals.mjs
 * @param {object} opts
 * @param {object} [opts.initialState]  eco_engine state; default = ARM opening (3 mex, commander)
 * @param {number} [opts.wind=10]       wind e/s per turbine
 * @param {number} [opts.sampleSec=5]   econSeries sampling interval in seconds
 *
 * @returns {{ intentId, actions, goalTimelines, econSeries }}
 *   actions      — input actions annotated with projectedStart, projectedEnd, stallSec
 *   goalTimelines — per-goal { id, projectedStart, projectedEnd, totalStallSec }
 *   econSeries    — [{ t, metal, energy, mexes, winds, solars }] sampled every sampleSec
 */
export function projectActionList(actionList, {
    initialState = null,
    wind = 10,
    sampleSec = 5,
} = {}) {
    const actions = actionList.actions ?? actionList;
    const state   = initialState
        ? structuredClone(initialState)
        : createState({ units: UNITS_EXT });
    state.units = UNITS_EXT;   // ensure extended unit table

    const sorted    = topoSort(actions);
    const endTime   = {};  // actionId → projectedEnd second
    const actorFree = {};  // actor    → next free second
    const annotated = [];
    const econSeries = [];
    let   nextSample = 0;

    // Advance state forward with no active build to time T
    function advanceTo(T) {
        while (state.t < T - DT * 0.5) {
            if (state.t >= nextSample) {
                econSeries.push({ t: r1(state.t), metal: r1(state.metal), energy: r1(state.energy),
                    mexes: state.mexes, winds: state.winds, solars: state.solars });
                nextSample += sampleSec;
            }
            tick(state, DT, null, wind);
        }
    }

    for (const action of sorted) {
        // Earliest start = last dep's end OR actor's next free time (whichever is later)
        const depEnd   = action.after.length > 0
            ? Math.max(...action.after.map(id => endTime[id] ?? 0))
            : 0;
        const actorAt  = actorFree[action.actor] ?? 0;
        const walkEnd  = Math.max(depEnd, actorAt);          // walk starts here
        const buildAt  = walkEnd + (action.walk_time_s ?? 0); // build starts after walk

        let projectedEnd, stallSec = 0;

        if (action.type === 'build' || action.type === 'queue_at') {
            const unitDef = UNITS_EXT[action.target];

            advanceTo(buildAt);

            if (!unitDef) {
                // No eco model for this target: use wall-clock time from expander, no stall sim
                projectedEnd = buildAt + (action.build_time_s ?? 0);
                advanceTo(projectedEnd);
            } else {
                const bp          = actorBP(action.actor);
                const stallBefore = state.mexStallSec;
                const job         = { unit: action.target, priority: 'high', progress: 0, done: false };

                // Override builder pool to this actor only for the duration of this build
                const savedBuilders = state.builders;
                state.builders = [{ name: action.actor, bp, priority: 'high' }];

                const tStart = state.t;
                while (!job.done && state.t < tStart + 600) {
                    if (state.t >= nextSample) {
                        econSeries.push({ t: r1(state.t), metal: r1(state.metal), energy: r1(state.energy),
                            mexes: state.mexes, winds: state.winds, solars: state.solars });
                        nextSample += sampleSec;
                    }
                    tick(state, DT, job, wind);
                }
                state.builders = savedBuilders;
                stallSec     = r1(state.mexStallSec - stallBefore);
                projectedEnd = r1(state.t);

                if (job.done) {
                    // Apply income/storage/builder effects.
                    // Legion leg_* keys map to ARM equivalents in eco_engine.
                    const key = action.target;
                    const ecoKey =
                        (key === 'con' || key === 'leg_con')     ? 'worker'     :
                        (key === 'leg_mex')                      ? 'mex'        :
                        (key === 'leg_medmex')                   ? 'mex'        :  // approximate: gives {mex:1} at ARM rate
                        (key === 'leg_turret')                   ? 'conTurret'  :
                        (key === 'leg_estor')                    ? 'eStorage'   :
                        key;
                    if (UNITS_EXT[ecoKey] && UNITS_EXT[ecoKey].gives) {
                        applyCompletion(state, ecoKey);
                    }
                    const facB = FACTORY_BUILDERS[key];
                    if (facB) state.builders.push({ ...facB });
                }
            }
        } else {
            // checkpoint / give_unit / reclaim_zone: record timing only, no eco sim
            advanceTo(buildAt);
            projectedEnd = buildAt + (action.build_time_s ?? 0);
            advanceTo(projectedEnd);
        }

        projectedEnd = r1(projectedEnd);
        endTime[action.id]      = projectedEnd;
        actorFree[action.actor] = projectedEnd;
        // Semantic inference: a factory build completion gates its own queue start.
        // The intent grammar doesn't require `after=g_factory` on `produce` goals —
        // but physically, the factory can't queue until it's built.
        if (action.type === 'build' && FACTORY_BUILDERS[action.target]) {
            actorFree[action.target] = Math.max(actorFree[action.target] ?? 0, projectedEnd);
        }
        annotated.push({ ...action, projectedStart: r1(buildAt), projectedEnd, stallSec });
    }

    // Final sample
    econSeries.push({ t: r1(state.t), metal: r1(state.metal), energy: r1(state.energy),
        mexes: state.mexes, winds: state.winds, solars: state.solars });

    // Per-goal summary: span from first action's projectedStart to last's projectedEnd
    const goalMap = new Map();
    for (const a of annotated) {
        if (!goalMap.has(a.goalId)) goalMap.set(a.goalId, []);
        goalMap.get(a.goalId).push(a);
    }
    const goalTimelines = Array.from(goalMap.entries()).map(([id, acts]) => ({
        id,
        projectedStart: r1(Math.min(...acts.map(a => a.projectedStart))),
        projectedEnd:   r1(Math.max(...acts.map(a => a.projectedEnd))),
        totalStallSec:  r1(acts.reduce((s, a) => s + (a.stallSec ?? 0), 0)),
    }));

    return { intentId: actionList.intentId, actions: annotated, goalTimelines, econSeries };
}

// ── CLI ───────────────────────────────────────────────────────────────────────
if ((process.argv[1] ?? '').replace(/\\/g, '/').endsWith('project.mjs')) {
    const [,, intentPath, ...flags] = process.argv;
    if (!intentPath) {
        console.error('Usage: node planner/project.mjs <intent.md> [--wind=N]');
        process.exit(1);
    }
    const wind = +(flags.find(f => f.startsWith('--wind='))?.split('=')[1] ?? 10);
    const dag      = await parseIntentFile(path.resolve(intentPath));
    const expanded = expandGoalDag(dag);
    const result   = projectActionList(expanded, { wind });

    // Summary to stderr, full JSON to stdout
    const goals = result.goalTimelines;
    console.error(`\n  ${result.intentId ?? '(intent)'}  —  ${goals.length} goals  wind=${wind} e/s`);
    console.error('  goal                         start    end   stall');
    console.error('  ' + '-'.repeat(52));
    for (const g of goals) {
        const stall = g.totalStallSec > 0 ? `  ⚠ ${g.totalStallSec}s stall` : '';
        console.error(`  ${g.id.padEnd(28)} ${String(r1(g.projectedStart)).padStart(5)}s  ${String(r1(g.projectedEnd)).padStart(5)}s${stall}`);
    }
    console.error();
    console.log(JSON.stringify(result, null, 2));
}

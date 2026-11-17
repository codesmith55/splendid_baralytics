# ✓ Done: eco_engine projection bridge (planner/project.mjs)

**Status:** shipped. `project.mjs` maps action targets → eco_engine keys, walks the DAG
in `after` order (topological sort), simulates each build with the actor's BP, and attaches
`{projectedStart, projectedEnd, stallSec}` per action + per-goal summaries + econSeries.
`con` PROVISIONAL costs fixed (4400→3450 buildWork, 1100→1600 energy); golden snapshot
regenerated. Factory timing inferred: factory queue won't start before factory build completes.

---

# Next dev task: stall + mitigation pass (planner layer 4)

**Task:** Build the bridge that feeds the expander's costed action list
(`planner/expand-goals.mjs` output) through the eco simulator and back, producing
per-goal **projected start/end times** and metal/energy curves. The simulator already
exists upstream:
`splendid_baralytics/gex_research/process/lib/sim/eco_engine.mjs` (`projectOption`,
`optionSubset`). Likely lands as `planner/project.mjs`.

**Why this one:** It is the first layer that turns the static action list into *time* —
nothing downstream (the stall + mitigation pass, then the live adapter's
projected-vs-actual grading) can exist until each action and goal has a projected
timeline. The expander deliberately stopped at costed actions for exactly this handoff;
`projectOption` is the consumer it was shaped for.

**Produce:** an adapter that maps each action's `{metal_cost, energy_cost,
build_time_s, walk_time_s, after}` into eco_engine's state/job model, walks the DAG in
`after` order, and attaches `{projectedStart, projectedEnd}` per goal plus the M/E
series — matching the "stall annotation pass" shape sketched in
`docs/intent-language.md`. A golden test over the 7mex-25wind action list, and a CLI to
emit the projected DAG JSON.

**Before coding:** read `gex_research/process/lib/sim/eco_engine.mjs` end-to-end
(state shape, `tick`, `applyCompletion`, which `unitKey`s it understands) — the
expander's `target` names (`mex`, `solar`, `con`, …) will need mapping to whatever keys
eco_engine's `applyCompletion` switches on. **Also replace the `_PROVISIONAL` costs in
`planner/data/units.json`** (con, laz, t2lab) with canonical BAR unit-def values before
trusting any projection — the bridge is the first place those numbers actually bite.

**Will NOT do:** the stall + mitigation pass itself (that consumes this layer's
projected timeline); touch the reader, adapter, or executor; require BAR running.

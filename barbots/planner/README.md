# planner/

Layer 2 of barbots (see [../docs/architecture.md](../docs/architecture.md)): compiles
an intent into a goal DAG, then (eventually) projects it through the eco_engine for
stall detection and mitigation insertion.

## Shipped

- **`parse-intent.mjs`** — the planner's entry point. Reads an intent `.md` file,
  extracts its machine-readable ` ```intent ` block, and compiles the build shorthand
  into a goal DAG. Pure text → JSON, no live-game dependency.
  - grammar: [../docs/intent-grammar.md](../docs/intent-grammar.md)
  - target DAG shape: [../docs/intent-language.md](../docs/intent-language.md)
  - the reference intent compiles byte-equivalent to the hand-compiled sketch
    (golden test).

- **`expand-goals.mjs`** — layer 2. Takes a goal DAG and emits a flat, costed
  **action list**: each goal (a declaration like "take 7 mex") becomes the concrete N
  actions that carry it out. Pure JSON → JSON, no live-game dependency.
  - **What it produces.** One or more actions per goal, each
    `{ id, goalId, type, actor, target, metal_cost, energy_cost, build_time_s,
    walk_leg_from?, walk_leg_to?, walk_time_s?, after:[…] }`. Action types:
    `build` (a building placed by a con/com), `queue_at` (a unit produced by a
    factory), `give_unit`, `reclaim_zone`, `checkpoint`.
  - **Expansion rules.** `count` / `countToTotal` / `countToTarget` expand to N build
    actions; a running tally per unit type drives both how many are left to build and
    the site index (so `mex` sites number 1..7 across all the mex goals). A
    `parallel` group goal distributes its N actions across the actor pool, all gated on
    the prerequisite, none chained to each other; a sequential goal chains action k
    after k−1. `after` is rewired from goal→goal onto **action→action** (a dependent
    goal's entry actions wait on the prerequisite goal's *exit* actions).
  - **Factory queues.** A `*repeat` (`infinite X`) queue materializes the first
    `FACTORY_QUEUE_HORIZON = 8` concrete actions (the bounded prefix padded with the
    repeat unit) plus one extra action flagged `repeat: true` standing in for the
    open-ended tail. 8 covers the opening's worker/laz rotation with headroom.
  - **Costs** come from [`data/units.json`](data/units.json):
    `build_time_s = buildWork / builderBuildPower`, so the commander (BP 300) builds
    the same mex faster than a con bot (BP 80). Building costs are transcribed from
    `bar-calc`; **bot units (con, laz) and the T2 lab are `_PROVISIONAL` placeholders**
    — bar-calc only tables buildings, so those numbers must still be pulled from the
    canonical BAR unit defs named in the file. Don't trust them for projection yet.
  - **Walk legs** are inserted whenever an action's target site differs from the
    actor's previous position. Walk time uses the `bar-calc/bar_distance.py`
    calibration (commander 37.5 elmos/s, con bot 36, grid ≈ 48.3 elmos, honoring build
    range). **Map positions are stubbed** as named placeholders (`pos:mex_5`,
    `pos:ally_air.bottomLeftMex`) and every leg uses one provisional hop length
    (`DEFAULT_HOP_SQUARES = 4.0`) until a real map reader resolves true distances.

```
node parse-intent.mjs ../intents/7mex-25wind-fast-t2.md   # prints goal DAG JSON
node expand-goals.mjs ../intents/7mex-25wind-fast-t2.md    # prints costed action list JSON
npm test          # both suites (parse: 18 cases, expand: 29 cases)
```

## Not yet built (next steps, in order)

1. **Projection bridge** (next) — feed the expanded action list through
   `splendid_baralytics/gex_research/process/lib/sim/eco_engine.mjs` (`projectOption`)
   to produce M/E curves and per-goal projected start/end times. This also wants the
   `_PROVISIONAL` unit costs replaced with canonical values.
2. **Stall + mitigation pass** — annotate each goal with stalls (lost-seconds) and
   mitigations in the preference order from intent-language.md.

`parse-intent.mjs` → `expand-goals.mjs` produce the goal DAG and costed action list
those steps consume.

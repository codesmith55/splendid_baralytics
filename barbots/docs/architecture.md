# barbots architecture

Three layers and an adapter. Each layer has a single time-direction concern.

## Layer 1 — live reader ("gexbot")

A gex.lua-derived widget running in the live game, emitting the same event shapes
gex_research already parses (`unit_created`, `extra_stat_update`, `wind_update`, ...)
plus command-feedback events the bot needs (`order_issued`, `order_completed`,
`builder_idle`).

**Fog honesty is enforced here.** The reader runs in the player's unsynced context,
which by construction only sees what the player sees:
- own team + allies: full data (resource pools, unit states, shared LOS)
- enemies: only `enemy_seen` events — `{frame, defName|null, x, z, confidence}`
  emitted when a unit enters vision/radar. Radar blips without LOS emit
  defName=null (you see a dot, not a unit type — same as a human).
- everything seen is **remembered with its timestamp** (humans remember scouting);
  nothing is updated while unseen.

Difference from replay gex.lua: replay mode has `/globallos` omniscience; the live
reader must NOT. Shared code, different capability — gate every emit on
`Spring.IsUnitInLos / IsPosInLos` for non-allied subjects.

## Layer 2 — planner (baranalytics leg)

Compiles an intent (docs/intent-language.md) into a **goal DAG**, then runs the
eco_engine projection over it:

1. Each goal expands to actions with resource costs and walk legs (walk time from
   bar_distance calibration: commander 37.5 elmos/s, con bot 36, grid ≈ 48.3 elmos).
2. The projection (eco_engine `projectOption` machinery, priority drain order
   included) produces the expected M/E curves for the whole build.
3. **Stall detection**: anywhere the projected stockpile pins at 0 while build power
   wants to spend → flagged with start/duration/severity (lost seconds, same unit as
   gex_research's eco_advisor).
4. **Mitigation insertion** — the planner edits the plan, in preference order:
   - **pre-walk build power**: dispatch the builder toward the next site BEFORE
     resources allow the build, so walk time overlaps the stall instead of adding to
     it (walk legs are free — they cost no M/E)
   - re-order goals with slack (a goal not on the critical path moves later)
   - insert bank thresholds ("don't start geo until E ≥ X" — duo-geo-rush learning:
     run-003 lost ~33s to an undersized bank)
   - insert a reclaim pass (Lazarus/rock-eating directives produce metal exactly
     where a metal stall was flagged)
   - downgrade: if a stall is unavoidable, mark which goal slips and by how much,
     so the live layer knows the expected delay vs an actual problem

Output: an **action queue** — ordered actions with preconditions, each tagged with
its goal, projected start/end, and the stall/mitigation annotations.

## Layer 3 — executor

Consumes ready actions, issues game commands.

- **Primary mechanism: widget orders** (`Spring.GiveOrderToUnit` from the bot's own
  widget) — robust, position-exact, and the sanctioned modding interface.
- **Fallback: input simulation** (screen clicks via the gex-script approach) for
  anything widgets cannot legally issue (e.g. some UI-only meta actions). Click
  targets computed by world→screen projection. This path is brittle (camera state,
  resolution) — keep it minimal.
- Meta actions are first-class: `give_unit(unitID, toPlayer)` (the worker-gift in
  the reference intent), `share_resource`, chat signals to allies.

## The adapter (the new code this project exists for)

Sits between planner and executor. Holds two world models and reconciles them:

```
projected state (planner, simulated)  ◄──── re-plan ────┐
        │ divergence check each tick                    │
actual state (live reader, fog-limited) ────────────────┘
```

Responsibilities:
1. **Precondition gating** — release an action to the executor when its actual (not
   projected) preconditions hold: resources banked, builder arrived, factory idle.
2. **Divergence detection** — compare actual M/E/income/unit-counts against the
   projection at the same game-second. Small drift (slow walk, wind variance):
   shift timestamps. Structural divergence (builder died, mex spot occupied, goal
   impossible): mark the goal failed and **re-run the planner from the live state**
   — the plan is a cached projection, never an obligation.
3. **Stall watch, live** — the projection says where stalls SHOULD be. If a stall
   appears anywhere else, that is new information (e.g. enemy pressure forced extra
   spend) → re-plan. If a projected stall doesn't appear, bank thresholds can be
   relaxed → opportunistic acceleration.
4. **Timer meta-actions** — the worker-gift has a declared timer ("con given with
   respect to walk time until it starts building air's bottom-left mex"): the
   adapter computes gift time = airMexSiteETA(walk from gift point) and schedules
   the give so arrival ≈ build-start readiness.

## Repo layout (planned)

```
barbots/
  reader/        gexbot.lua (live, fog-honest), event schema
  planner/       intent parser, goal compiler, projection bridge (imports eco_engine)
  adapter/       state reconciliation, divergence policy, action gating
  executor/      widget order issuing; input-sim fallback
  intents/       declared builds (text) + compiled goal DAGs (json)
  docs/
```

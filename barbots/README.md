# barbots

The third leg of the BAR analytics stack: a live bot that executes declared build
intents in Beyond All Reason, using only the information a real player has.

## The three legs

| Leg | Project | Question it answers | Time direction |
|---|---|---|---|
| 1 | `splendid_baralytics/gex_research` | What happened? (replay reading, metrics, build grading) | past |
| 2 | `splendid_baralytics/bar-calc` + eco_engine | What should happen? (state simulation, breakeven, lost-seconds, build justification) | future |
| 3 | **barbots** (this repo) | Make it happen, live | present |

This is a **parallel sibling project**, not a child of splendid_baralytics:
- the analytics repo stays pure analysis — no live-game side effects
- barbots carries its own infra (live state sync, action execution, fog model) and its
  own risk profile (it touches a running game)
- both existing projects are consumed as **imported reference projects**, read-only:
  - `gex_research/vendor/gex.lua` — the live-reading pattern (widget event emission)
  - `gex_research/process/lib/sim/eco_engine.mjs` — state projection, priority drain
    order, lost-seconds
  - `bar-calc/` — TROI/breakeven math, walk-time calibration (`bar_distance.py`,
    grid square ≈ 48.3 elmos), wind simulation

## Pipeline

```
intent (text build declaration)
   │  intents/ — see docs/intent-language.md
   ▼
goal compiler  ──────────────  baranalytics leg: compiles intent into a goal DAG,
   │                           simulates the resource curve, flags M/E stalls,
   │                           inserts mitigations (pre-walked build power, bank
   ▼                           thresholds, reclaim passes)
action queue (ordered, conditional)
   │
   ▼
adapter  ────────────────────  docs/architecture.md — merges the queue with the
   │                           LIVE game state (fog-limited gex-like reading) and
   ▼                           re-plans when reality diverges from the projection
executor ────────────────────  issues game commands. Primary: Lua widget orders
                               (Spring.GiveOrderToUnit — the sanctioned modding
                               interface). Screen-click simulation only as fallback.
```

## Information honesty rule

The bot reads **only what its player could know**: own-team shared data (the
team-resource pools, allied unit positions, shared LOS) plus whatever enemy
information its own vision/radar produces. No reading of enemy economy, build
queues, or fog-hidden units. This is enforced at the reading layer, not the
decision layer — the live reader simply never emits fog-hidden data.
See docs/scouting-economy-estimation.md for what the bot does with partial
enemy information.

## Status

Early build. Spec docs are complete; the **planner's first two slices have shipped**.

**Working:** `planner/parse-intent.mjs` — the intent parser (planner entry point):
reads an intent `.md`, compiles its machine-readable build shorthand into a goal DAG.
`planner/expand-goals.mjs` — layer 2: expands that goal DAG into a flat, costed action
list (counts/groups/factory queues → per-actor build actions with resource costs and
walk legs). Both are pure JSON, no live game needed; the reference intent has a golden
test at each stage (`npm test`, 18 + 29 = 47 cases). Costs come from
`planner/data/units.json` — building costs are transcribed from `bar-calc`, but bot
units and the T2 lab are `_PROVISIONAL` placeholders, and map positions are stubbed.

**Stubbed / not built:** eco_engine projection bridge + stall pass (the remaining
planner layers), and the entire reader, adapter, and executor. The shorthand is a
*structured* DSL — compiling free-form English prose into it is out of scope (future,
likely LLM-assisted).

Docs:
- [docs/architecture.md](docs/architecture.md) — the three layers + the adapter
- [docs/intent-language.md](docs/intent-language.md) — intent → goal compilation,
  with the duo-worker meta-give example fully parsed (the target DAG shape)
- [docs/intent-grammar.md](docs/intent-grammar.md) — the shorthand grammar the parser
  reads
- [docs/scouting-economy-estimation.md](docs/scouting-economy-estimation.md) —
  future idea: opponent economy estimation from scouting
- [docs/builds/](docs/builds/) — build-idea analyses (costed comparators the planner will
  score in lost-seconds): first-unit rush, Gunslinger turnaround
- [planner/README.md](planner/README.md) — what's shipped and the next steps in order

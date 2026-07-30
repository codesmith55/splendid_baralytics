# splendid_baralytics — agent guide

## BAR replay metrics (gex_research/)

A Node pipeline that turns a BAR replay into per-user economy metrics over time.
Full docs: `gex_research/DISPATCH.md`. Output is **per user** (the user controlling each engine team).

### Running a metric (this is what "run the BAR metric / economy metric / gex run" means)

```bash
cd gex_research && node process/run.mjs <run>
```
- `<run>` accepts a short id: `001`, a keyword (`economy`), a filename, or omit it to run the
  lowest-numbered config. So `node process/run.mjs 001` ≡ the full `metrics/runs/run-001-economy-composition.json`.
- Output → `gex_research/output/<run>/` : `report.html`, `metrics.json`, `situations.json`, `context.json`.

### Dispatch phrases → action
- "run the BAR economy metric" / "run gex 001" → `cd gex_research && node process/run.mjs 001`
- "run economy on demo <file>" → copy `metrics/runs/run-001-economy-composition.json` to a new
  `run-NNN-*.json`, set `input.source:"headless"` + `input.demoFile:"<file>"`, then run it.
- "add a metric / situation" → `node process/addMetric.mjs <criteria.json>` /
  `node process/addSituation.mjs <criteria.json>` (templates in `metrics/criteria-examples/`).

### Notes
- **Default analysis window = first 15 min** of a game unless the user asks for longer (or "full").
  Most action is early; the rest expands from there. `gex_research/tools/eco_table.mjs` defaults to
  900 s; opening-build views stay 0–5 min.
- Permissions are pre-authorized for dispatch (`Bash(node:*)`); the machine must stay on + logged in for
  headless replays (~137 s per ~13-min game).
- Master lists: `gex_research/metrics/catalog.json` (metrics), `metrics/situations.json` (situations).

## Live analytics server (`live/`)

`bar_analytic_server.py` tails the widget JSONL, maintains per-team economy state, and serves a live dashboard.

### Starting the server
```bash
cd live && python bar_analytic_server.py --no-exit
```
- `--no-exit` keeps it alive across game sessions (default auto-exits ~4 min after a game ends).
- Dashboard: `http://localhost:8787` — SVG pie grids, one per player.
- Raw state: `http://localhost:8787/api/state` — JSON snapshot polled at 1 Hz by the dashboard.
- JSONL source: `C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data/bar_analytic_live.jsonl`

### Per-minute snapshot recall + projection
The server captures a full per-team snapshot at every game-minute (persisted to `live/snapshots/game-<wall>.json`) so a game is recallable at any minute:
- `GET /api/snapshots` — index of recallable minutes.
- `GET /api/snapshot?minute=N` — full game state recalled at minute N.
- `GET /api/compare?minute=N[&to=M]` — per-team delta N→N+1 (income, mex, value buckets).
- `GET /api/project?minute=N` — project each team's eco from N (state_api/navigator), grade vs actual N+1: best build options at N, passive baseline, realized deltas, verdict flags (`eco_growth`/`spent_non_eco`/`idle`/`metal_overflow`).
- `GET /api/shares` — energy donation/overflow flows between teammates as `X > Y` with donation/overflow split.

### Energy sharing / overflow (`energy_share` event)
The widget samples `Spring.GetTeamResources(teamID,"energy")` (returns `...,sent,received`) each `shareEverySec`; the per-sample delta is the flow. X→Y is inferred inside an allyteam (sender outflow split across receivers ∝ their inflow). Classification: **overflow** = sender at/near energy cap AND not named in recent chat (forced spill); **donation** = sender below cap (deliberate) OR named in chat (announced). The widget's `AddConsoleLine` ring supplies the chat hint. Server aggregates per `fromTeam>toTeam` pair into the snapshot's `shares` and `/api/shares`.

### Analysis registry (`analyses.py`) — independent functions, composed by API or CLI
Every analysis is a source-agnostic pure function `fn(game, **params)` registered in `live/analyses.py` `REGISTRY` (`minutes`, `recall`, `compare`, `project`, `build`, `shares`). A `game` is any object with the replayed-game read API (the live `Live`, or a `Live` from replaying a saved JSONL), so the same function runs on live, recalled, or DB-archived games. `run(game, [requests]) → {name: result}` composes them; requests are `"build"`, `"project:7"`, or `{name, params}`.
- **API**: `POST /api/run {game, functions:[...]}` (game = `"live"` | archived id | 1-based index | `*.jsonl` path). `GET /api/functions` lists the registry; `GET /api/games` lists archives.
- **CLI**: `cd live && python replay_jsonl.py --run "build,shares,project:7"` (runs on `--path`).
- **Saved games**: each game's JSONL is archived to `live/games/<gameid>.jsonl` on game-end; `load_game(ref)` replays it. Adding an analysis = add one function to `REGISTRY` (auto-exposed by both front-ends).

### Validating snapshots/projection offline (no BAR needed)
`replay_jsonl.py` feeds any JSONL through the same Live pipeline to test recall/compare/project on a past game. **Use this instead of hand-writing throwaway test scripts.**
```bash
cd live && python replay_jsonl.py [--path FILE] [--minutes|--snapshot N|--compare N|--project N|--shares] [--json]
```
Default (no flag) = summary + project the mid-game minute. `team_state`/`compare_minutes`/`project_team` live in `bar_analytic_server.py` and are shared by the server and this script.

### Passive monitoring mode
When the user says they are playing or watching a game, adopt a **passive observer role**:
- Start the server with `--no-exit` in the background and set up a Monitor on its output.
- Report game state events (session start, team changes, game end) as notifications.
- Do **not** take autonomous actions, open the browser, or change any files during the session.
- Only act if the user explicitly asks.

### Dispatch phrases → action
- "start the analytics server" / "run the live server" → `cd live && python bar_analytic_server.py --no-exit` (background + monitor)
- "open the dashboard" → `start http://localhost:8787`
- "show raw state" → `curl -s http://localhost:8787/api/state | python -m json.tool`
- "validate snapshots" / "replay the jsonl" / "project minute N of the last game" → `cd live && python replay_jsonl.py [--project N]` (offline; do NOT write a throwaway script)
- "recall minute N" / "compare minute N" → `curl -s "http://localhost:8787/api/snapshot?minute=N"` / `.../api/compare?minute=N`

## Build-order planner (`barbots/`)

Intent-driven build-order planner for BAR. Three shipped layers + a live reader:

```
Intent (.md)  →  parse-intent.mjs  →  Goal DAG
                                          ↓
                               expand-goals.mjs  →  Costed action list
                                                          ↓
                                             project.mjs  →  Projected timeline (per-goal start/end + stalls)
                                                                         ↑
                                           live-reader.mjs ──── /api/state (bar_analytic_server)
```

### Running the planner layers
```bash
cd barbots
node planner/parse-intent.mjs intents/<name>.md      # → goal DAG JSON
node planner/expand-goals.mjs intents/<name>.md      # → costed action list JSON
node planner/project.mjs intents/<name>.md [--wind=N]  # → projected timeline JSON (summary to stderr)
npm test                                              # 29 parse + expand tests
```

### Dispatch phrases → action
- "parse/expand/project <intent>" → run the corresponding layer on `barbots/intents/<name>.md`
- "what does the 7mex-25wind intent project to?" → `node planner/project.mjs intents/7mex-25wind-fast-t2.md`
- "add a build intent" → create a new `barbots/intents/<slug>.md` following `docs/intent-grammar.md`

### Key files
- `planner/data/units.json` — canonical ARM/COR unit costs (sourced from bar-calc + eco_engine; `laz` and `t2lab` still PROVISIONAL)
- `planner/project.mjs` — Layer 3; feeds eco_engine (`gex_research/process/lib/sim/eco_engine.mjs`) to attach timeline + stall diagnostics
- `reader/live-reader.mjs` — polls `http://localhost:8787/api/state`, emits typed events (`econ`, `builderIdle`, `builderBusy`, `gameReset`, `gameEnd`)
- `docs/intent-grammar.md` — intent block language spec
- `docs/builds/` — build-specific analysis docs (first-unit-rush, gunslinger-turnaround)
- `NEXT_TASK.md` — current development priority

### Notes
- Intent unit names map to eco_engine keys: `con` → `worker`, `wind/solar/mex` → same key
- `project.mjs` serializes parallel builds (real game is concurrent); stall diagnostics are valid
- Factory timing is inferred: factory queue can't start before the factory build completes
- `eco_engine` stall metric = mex-seconds where upkeep couldn't be paid (high-priority builds starve mexes — queue LOW priority to avoid)

## Dispatch shorthands

`pc` / `Pc` / `PC` — runs the nearest `capabilities.py` found by upward search.
Shortcut files: `gex_research/ai_processes/pc.bat` (Windows), `pc.sh` (bash).

```
pc                      # interactive menu
pc .                    # nav context (where was capabilities.py resolved?)
pc info a               # BAR Replay Metrics Runner detail
pc info a b             # sub-command b of capability a
pc run  a b             # print run-command for sub-command b of capability a
pc filter bar           # capabilities tagged 'bar'
pc tags                 # tag index
pc --spec --pretty      # full JSON spec (AI/agent-friendly)
```

### Extension model

`capabilities.py` is a thin extension of the canonical base framework at
`scavengers_guild/ai_processes/capabilities_core.py`.
`pc.bat`/`pc.sh` route `PC_BASE_DIR` to the canonical source when
scavengers_guild is present on the machine; otherwise fall back to the local
sync copy at `gex_research/ai_processes/capabilities_core.py`.

To sync the local fallback copy after a core update:
```
copy scavengers_guild\ai_processes\capabilities_core.py ^
     splendid_baralytics\gex_research\ai_processes\capabilities_core.py
```

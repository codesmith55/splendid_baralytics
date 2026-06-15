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

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

## Build parser → simulator → strategizer (repo root, Node, no npm deps)

Three scripts that run side by side on the same game; the state calculator is a port of
`bar-calc/bar_unified.py` (the consolidated calculator: grid/walk calibration, wind income,
ObjectType ROI helpers `buildTime/troi/eroi`, `Environment` with `buildTimes/build/advance/buildOrder/status`,
`generatorRoiReport` → `--roi [--wind N] [--bp N]`). bar_calc's spellings (`calculateBuildTimes`,
`constructObject`, `advanceTime`) remain; `--selftest` reproduces both bar_unified's and bar_calc's demo numbers.

```
splendid_buildParser.js      game → reality "moments" per team (bank, storage, income, BP, unit
                             counts, builder positions, nanoframes; demo: derived bank + build ORDERS)
splendid_buildSimulator.js   Environment (bar_calc port) + continuous per-builder tick (walk, BP share,
                             pool throttling) + resetToReality(moment) + divergence; alternates reset ↔ simulate
splendid_buildStrategizer.js decides what each build-power source does: bar_economy.md rule cascade,
                             known flows (priority lists), bar_calc priority/towards modes, playstyle profiles
splendid_buildAnalyzer.js    comparative economy / collapse detector (now imports its parsing from the parser)
splendid_buildPather.js      PLACEMENT: build patterns (ASCII layouts on the 48-elmo footprint grid) → the build ORDER
                             that walks least while keeping a path + keeping the next piece ahead of the worker swarm
```
`<source>` everywhere = widget JSONL (`live/games/<id>.jsonl`), a `.sdfz` demo (path | filename | `latest`),
or a 1-based index into `live/games/` newest-first (`1`). `--team` takes an id or a name substring.

```bash
node splendid_buildParser.js 1 --team Splendi --every 60 --until 600          # moments table (--json out.json)
node splendid_buildSimulator.js --selftest                                     # port fidelity vs bar_calc.py
node splendid_buildSimulator.js 1 --team Splendi --every 60 --until 480 --free 60
#   step mode: reset at each moment, replay reality's own build starts/deaths, report Δ(sim − real)
#   --free N: reset once at N s then no more resets; --decisions none|replay
node splendid_buildStrategizer.js 1 --team Splendi --at 120 --horizon 180 --strategy eco_rules [--profile P]
node splendid_buildStrategizer.js 1 --team Splendi --at 60 --horizon 180 --compare   # vs replay + reality
node splendid_buildStrategizer.js --fresh --strategy flow:solar_open --horizon 120   # no game, from spawn
```
Strategies: `eco_rules` · `flow:<solar_open|wind_open|glitters_std|wind_conversion>` · `priority:A,B,C` ·
`towards:<Object>` · `replay`. Profiles: `balanced greedy_expand energy_first tech_rush tempo`
(`--compare "eco_rules,eco_rules/greedy_expand,flow:glitters_std"`).

### Build pather (`splendid_buildPather.js`) — patterns as a pathing problem
Home for placement capabilities. A pattern is data (`PATTERNS` or a text file: `W` wind, `C` converter,
`S` e-storage (contiguous = one building), `T` con turret, `.` gap/lane, `#` blocked, lowercase = already
standing). Output is a plain **build queue**: the engine walks the builder to the nearest in-range cell of
each target, so the order alone fixes the route (`--stands engine`, default). Model: reach = buildRange +
footprint half-width (con bot 130+24 → 3 cells straight, (3,1)/(2,2) diagonal — clipping the edge counts);
footprints are walkable until placed (walk space first, build space later = "double back"); after every
placement the stand must still connect to the outside and every remaining piece must still have a stand
(never seal off); N workers = a blob behind the lead — clash (trailing worker on the footprint), self-step,
behind (target behind the direction of travel), cramped (1-wide tunnel) are penalties in walked-cell
units (`--wClash 2 --wBehind 1 --wCramped 1 --wSelf 0.5 --wReverse 0.25`, all overridable).
`auto` = greedy/beam/coverage seeds → local search on the queue (relocate/reverse/swap/regrow, every
candidate re-simulated). `--workers 1` has no swarm penalties = pure shortest route.
```bash
node splendid_buildPather.js                          # windfarm_4x4 (the screenshot: 54 wind, 8 conv, estorage), 4 con bots
node splendid_buildPather.js --compare [--quiet]      # naive (shift-drag reading order) vs greedy vs beam vs auto vs walk-only
node splendid_buildPather.js <pattern|file> --workers 1 --start left|top|r,c --frames 10 --json plan.json
node splendid_buildPather.js --queue "1,3 0,0 0,1 …"|file   # evaluate YOUR order: walk, clashes, does it seal itself off
node splendid_buildPather.js --list | --selftest
```
Dispatch: "path/plan the wind pattern", "what order do I build this layout in", "will 4 cons bunch on this" →
`node splendid_buildPather.js [pattern] --compare`; "check my build order" → `--queue`; "add a pattern" →
entry in `PATTERNS` (or a text file); "add a building type" → `TYPES` (sizeX 6 = one cell; multi-cell = `group`).
JSON `queue[]` carries `targetXZ`/`standXZ`/`path` in elmos relative to the pattern's top-left — the seam
for the adapter (`barbots/adapter`) to place real orders.

### Dispatch phrases → action
- "parse the build / show moments for X" → `node splendid_buildParser.js <source> --team X`
- "simulate X's game / how far does the sim drift" → `node splendid_buildSimulator.js <source> --team X`
- "what should X build at minute N / compare strategies from N" → `node splendid_buildStrategizer.js <source> --team X --at N*60 --compare`
- "add a flow" → entry in `FLOWS`; "add an eco rule" → entry in `RULES`; "add a playstyle" → `PROFILES` (all in the strategizer)
- Build work / incomes for engine units come from `gex_research/sample_output/actions.json` `unit_def`
  lines (engine truth: buildTime, energyProduction/Upkeep, storage); the widget's `unit_def` has no buildTime.

## Economy model data layer (`bar-calc/econ_model.json` + `bar-calc/econ_data.py`)

Every economy calculator resolves its numbers from ONE config plus the engine unit-def dumps. No
hand-copied costs live in the readers any more.
- `bar-calc/econ_model.json` — model choices only: exchange rate, grid calibration, builder build
  ranges, which engine defName stands for each model object (`objectTypes`, `aliases`), the base
  state, the Legion action semantics (`legion.actions`: def / replaces / reclaim / dn / prereq /
  label), and calibrated overrides (`mexMultiplierOverride.legmex = 0.75`).
- engine truth: **the newest `bar-calc/units_<dateTime>.json`** (every def the engine reports for a real
  game, harvested from the most recent 8v8 replay — see below). A faction the lobby did not enable
  (usually Legion) is carried through from the previous data into the new file, tagged `carriedFrom`,
  so the file is always complete: fresh Armada/Cortex, prior Legion. The two older dumps
  `gex_research/sample_output/actions.json` (`unit_def` block) and `gex_research/legion/legion_unitdefs.json`
  stay as the base of the chain; all are listed in `engineDefs`, later entry wins, the glob is last.
- readers: `bar-calc/bar_unified.py` (Python calculator), `positions/state_api.py` and
  `positions/compare.py` (the Legion state engine behind `/api/project`, `/api/t2`, `/api/analyze`,
  the navigator, the decider and eco_viz), `splendid_buildSimulator.js` (and the strategizer /
  pather / analyzer through it). `bar-calc/econ_data.py` is the Python loader; the JS mirrors its
  derivation rules (`energyFlows`, `mexIncome`, `resolveObjectType`, `resolveLegionAction`).
- `bar-calc/parity.json` pins the resolved numbers, the ROI helpers and both demo openings. Every
  side checks it, so the three models cannot drift apart silently.

**Wind is a 2-D vector, not a scalar** (`bar_unified.py` §3). The engine re-rolls it every 450 frames
(15 s) by adding a random delta to the current vector and clamping the new length to the map's
[min, max]; across the window the live vector slides old→new by a smoothstep, and a turbine's output
is the vector's length. So the destination is fixed the moment a window opens — `RecordedWind.forecast(t)`
reports it. `RecordedWind` = one real game's wind (from the widget's `wind_update` samples, exact);
`WindModel` = a map's distribution. **Never use `(min+max)/2`** — on All That Glitters ([0, 16] per the
map file) that says 8.0 E/s against a measured ~11.9; `wind_income()` returns the real expectation.

**The map file answers what a replay only implies** (`bar_unified.py` §4, folded in from
`bar_analytics/map_spots.py`, pure stdlib): metal-spot positions, geovents, team start positions,
world size, extractor radius and the map's **real wind range**. `RecordedWind` can only ever see the
wind max (the walk clamps against it), never the floor, so take the range from the map. Spot income
is calibrated: `metal_sum` is authoritative relative richness, scaled against the map's standard spot
and `metalSpot` (1.825 m/s), which reproduces 1.825 on All That Glitters. The raw
`metal_per_s_est` is NOT m/s. Cached to `bar-calc/map_data/` keyed by archive, so map versions never
collide; only reading a NEW archive needs `py7zr`. Caveat: current maps keep only geovents in the
SMF feature section, so `MapInfo.rocks()` finds no rocks — track map reclaim from the game instead.

**Metal income splits into mex / converter / RECLAIM per unit** (`bar_unified.py` §5). The engine
reports each unit's own `metalMake`, and a builder shows it only while reclaiming; the gex widget
samples every frame and accumulates `metalMake/30`, so its `unit_resources` figure is that unit's
lifetime metal production. Summing them reproduces the engine's `team_stats.metalProduced` to 98.6%,
so the split is real. In the sample 16-player game reclaim was 18.3% of all metal, and the two
resurrection bots (Lazarus `armrectr`, Graverobber `cornecro`) were 20% of that reclaim.
Two limits: `unit_resources` fires ONCE per unit, at death or game end, so there is **no time
series**; and it carries **no source** (nine fields, `defID` names the producer, never what was
eaten), so rock-vs-wreck needs `wreck_removed`, which in turn has no metal amount.

**Reclaim resolves to individual objects** (`--reclaim-runs`, needs the patched widget — see
`gex_research/vendor/VENDOR.md`). Measured: reclaim is a **constant rate held for 29-211 frames**,
never a one-frame spike, so one reclaimed object = the integral of one contiguous run. Identity comes
from EVIDENCE first: the unit that died beside the run and whose cost can account for the metal.
Value-matching against a price list is the fallback, because it cannot tell a 470-metal corlab from a
500-metal armlab once a reclaim is 97% done. Verified on a 10-min duel: a 483.3-metal run resolved to
an armlab (500, 97% recovered) and a 470.0-metal run to a corlab (470, 100%), both confirmed against
the actual deaths. Runs with no corpse to point at are the `rock_or_wreck` bucket. Watch for two
confounders the report separates out: a cancelled build refunds metal through the same channel, and
back-to-back reclaims with no idle frame merge into one run.

**Time and place gate the answer.** A candidate is rejected outright if no unit of that type had been
built yet anywhere in the game — the stream knows every `unit_created`, so "no fusion at 6 min" needs
no hand-tuned rule. That gate alone corrected two `corwin` matches to `armwin` in a solo Armada
skirmish, where no Cortex unit ever existed. Each run also reports its distance from the reclaiming
team's own spawn and a `home`/`field` zone. On top sits a **loose sanity layer that annotates, never
rejects**: a unit wreck before anything had died, a T2 object before 5 minutes, an unidentified run at
home before the first death (that is a map rock), and any match under 25% recovered (a fragment).

**Building reclaim returns 100% of metal cost**, so a run total names the object outright. Validated on
two All That Glitters skirmishes: wind x34 at 40 each, solar x7 and x4 at 155, advanced solar x3 at 350,
fusion x2 at 3350, advanced bot lab at 2600, bot lab at 500, con turret at 230 — every one at 100%
recovered and corpse-confirmed. Partial reclaims (an interrupted advanced fusion at 4%, workers at 82%)
are the exception and the `got` column exposes them. With a T2-aware catalog `rock_or_wreck` falls to
2-7% of all reclaim; omitting T2 sent one 2600-metal lab into that bucket and inflated it fourfold.

```bash
node bar-calc/replay_demo.mjs --list 10 --only 1v0      # newest skirmishes (one human, no AI)
node bar-calc/replay_demo.mjs --demo 1v0                 # full headless replay -> actions.json path
python bar-calc/bar_unified.py --reclaim-runs <actions.json> [--tol 0.04] [--min-metal 0.5]
python bar-calc/bar_unified.py --metal-sources [actions.json]   # mex / converter / reclaim per team + per unit
python bar-calc/bar_unified.py --map --game 1 --team 0   # map of a recorded game + nearest mex spots
python bar-calc/bar_unified.py --map "all that glitters"  # by name; --refresh re-reads the archive
python bar-calc/bar_unified.py --wind --game 1     # a real game's wind: average, droughts, forecast
python bar-calc/bar_unified.py --wind-validate     # key functionality test: model vs recorded games
python bar-calc/bar_unified.py --harvest-defs      # newest 8v8 demo → headless replay → bar-calc/units_<dateTime>.json (+ parity)
#   [--demo latest|4v4|<demo file>] [--engine recoil_X] [--full] [--no-parity];  node bar-calc/harvest_defs.mjs --list 20
python bar-calc/bar_unified.py --write-parity      # after editing econ_model.json or refreshing a dump
python bar-calc/bar_unified.py --selftest && python positions/state_api.py --selftest && node splendid_buildSimulator.js --selftest
python bar-calc/econ_data.py [--objects|--legion]  # resolved tables (GET /api/econ_model serves the same live)
python bar-calc/econ_data.py --check               # drift vs the tables NOT on this layer yet
```
Dispatch: "refresh / harvest the unit stats", "pull the unit defs from the latest 8v8", "update the
units file" → `python bar-calc/bar_unified.py --harvest-defs` (≈40 s: spring-headless is stopped as soon as
the frame-0 `unit_def` block is complete; the machine must be on + logged in). "add a building / unit to
the model" → `objectTypes` entry (def + kind, `fallback` only if the def is missing from every dump);
"change a calibration" → `constants` / `gridCalibration`; "add a Legion action" → `legion.actions`;
then `--write-parity` and the three selftests.
Not on this layer yet (still hand-written; `--check` reports their drift): `barbots/planner/data/units.json`,
`gex_research/process/lib/sim/eco_engine.mjs`.

### Decision model: what to build, and when hands beat resources

The capstone of the calculator. Every structure burns metal and energy in a **fixed
ratio** Mc:Ec, because at build power B it draws `Mc*B/W` metal and `Ec*B/W` energy per
second. So "I cannot spend my build power" is a statement about the TARGET, never about
the position. The spectrum spans everything: Solar 155:0 is a pure metal sink and the
only generator that costs no energy to erect (so the only one buildable in an energy
famine); EConverter 1:1150 is a pure energy sink; Wind 40:175, Mex 50:500,
BotWorker 110:1600, ConTurret 230:3200 sit between. **The inverse is the signal to buy
build power**: when the best target absorbs 100%, resources are no longer the limit -
and if energy is what blocks buying hands, the energy-friendly generator comes first.
**Metal bound is the GOAL**; the other three regimes are idle builders, idle metal, or
spilled energy.

| function | file | what it answers |
| --- | --- | --- |
| `absorb_profile` / `target_advisor` | `bar_unified.py` | which target can consume this build power, ranked; the famine and overflow special cases |
| `regime_of` / `recommend` / `scaling_map` | `bar_unified.py` | which of the four regimes a position is in and its one fix; the lattice of both scaling sources |
| `build_horizon` / `_project_row` | `bar_unified.py` | takes target + BP source + wind plane, projects forward; row i stops to build i BP sources first, marks at true completion times, `crossover` = where it catches up |
| `roi_figures` / `effective_bproi` | `bar_unified.py` | BPROI corrected by the share of added build power income can actually FEED - unfed BP never repays |
| `idle_audit` | `bar_unified.py` | idle build power split FREE (income could not have fed it, so walking there was free) vs COSTLY |
| `build_gaps` | `bar_unified.py` | finish-to-start dead time from unthrottled chains; commander measured at 5 frames |

```bash
python bar-calc/bar_unified.py --target --game 1 --at 30      # ranked absorption + verdict
python bar-calc/bar_unified.py --target --game 1 --timeline   # advice vs what was actually built
python bar-calc/bar_unified.py --map-scaling --game 1 --at 60 # the regime lattice
python bar-calc/bar_unified.py --horizon --game 1 --at 60 --rows 4 [--depth 4,8,11.9,16]
python bar-calc/bar_unified.py --idle --game 1 | --gaps --unit Wind --bp 300
```

### Horizon viz (`bar-calc/horizon_viz.py` + `horizon_viz_page.py` -> `bar-calc/viz/`)

One self-contained HTML page (no CDN, opens offline) with four views of that same
model: the **2-D decision table** (rows add the BP source, columns add the energy
source, coloured by regime, with lenses `Regime` / `What to build` / `Target absorbs`),
the **absorption spectrum** (each candidate's Mc:Ec on a log axis against your actual
surplus ratio), the **forward projection** (`build_horizon` as a timeline with the
crossover tick), and the **3-D cube** with WIND AS DEPTH - one plane per wind speed,
drag to rotate. Two modes: **Replay** plays the game's measured 15 s samples so the
regime surface deforms in time (ribbon strip = regime per sample, advice letters, click
to jump); **Sandbox** puts the five quantities on sliders to push it and watch it react.

The page computes the model in JavaScript so nothing round-trips, which means a SECOND
copy of the model. So the payload ships Python's answers for ~280 sampled cells,
profiles, verdicts and projections, and three guards check it:
`--verify-port` runs the page's own JS under Node against them, plus `node --check` on
the whole page script and an element-id check. The badge top-right of the page is the
same check in the browser.
```bash
python bar-calc/horizon_viz.py --game 1 --at 60 [--open]      # -> bar-calc/viz/horizon_<id>.html
python bar-calc/bar_unified.py --viz --game 1 --at 60         # same thing
python bar-calc/horizon_viz.py --selftest                    # payload + JS port + syntax + ids
python bar-calc/horizon_viz.py --verify-port                 # just the Python/JS parity
#   flags: --target --bpsrc --energy --on --depth 4,8,11.9,16 --bprows --ecols --rows --until --out
```
Live via the calc server: `http://localhost:8799/viz/horizon?game=1&at=60`
(`&fmt=json` for the payload). Dispatch: "show/open the build horizon", "visualise the
decision table / the cube", "what should I build at N and why" -> generate and open the
page; "add a candidate to the spectrum" -> `--candidates` or `DEFAULT_CANDIDATES`;
"add a wind plane" -> `--depth`.

### Econ capability API (`bar-calc/econ_api.py` + `econ_db.py` -> `bar-calc/econ.db`)

**One shape for every economic question: `Context` -> `capability(**params)` -> `dict`.**
A Context is the STATE IN, either a recorded game at a moment (`game`, `at`) or a
hand-written position (`state`), plus the framing every economic question needs: the mex
budget, the worker policy, whether the factory is on. A capability is one PERSPECTIVE.
Adding one is a single decorated function; the decorator carries the docs, so `--spec` is
always current and an agent can read the whole surface without reading the code.

```bash
python bar-calc/econ_api.py --list            # every capability, its question and params
python bar-calc/econ_api.py --spec            # the same, machine-readable JSON
python bar-calc/econ_api.py --game 1 --at 90 --run all --name Splendi --build "wind-conversion front"
python bar-calc/econ_api.py --game 1 --at 60 --run "state,budget,phases,next_build"
python bar-calc/econ_api.py --state '{"m_inc":9.3,"e_inc":97,"bp":610}' --run next_build
python bar-calc/econ_api.py --selftest        # every capability, on a game AND a bare state
#   Context flags: --game --at --state --position tech|front --mex --standing --team --map
#                  --workers --expanding --commander base|expand --factory-off --assist
#                  --target --bpsrc --energy --on --name --build --json --no-record
```

| capability | the question it answers |
| --- | --- |
| `state` | Where am I, and what is limiting me right now? |
| `budget` | How much room to grow, and what is each remaining spot worth? |
| `phases` | What phase am I in, and what does it say is worth doing? |
| `claim` | If I task my workers with every remaining spot, when is it done? |
| `pools` | Which build power may legally do this work, and how much? |
| `bp_measured` | Where did my build power really go? (from a replay) |
| `next_build` | **How long will it take to build the next X from here?** |
| `cadence` | How far apart do they land, and what does stopping to scale cost? |
| `path` | **How many generators per build-power source should I build?** |
| `advisor` | My build power is idle. What can absorb it? |
| `lattice` | If I add N energy and M build power, what becomes the constraint? |
| `idle` | Was my build power idle because I was slow, or because there was nothing to spend? |
| `cadence_check` | Does this chart actually match reality? |
| `roi` | Is this worth building, and does more build power pay for itself? |
| `concentration` | Should my workers build together or separately? |
| `extractor_rate` | What is a spot worth once the extractor's energy is counted? |
| `catalog` | What exists in this game, per faction? |
| `tiers` | What gates what, and in which order does tech open up? |
| `lab` | What comes out of this lab, and what gates that product? |
| `unlocks` | Given what I have built, what are my options? |
| `goal` | How long to N of these, and should I stop to build hands first? |

### The database (`bar-calc/econ.db`, gitignored, rebuildable)

**Build times live in a database, not a dump.** The engine dumps stay the source on disk,
but nothing parses JSON to ask how long an advanced lab takes: `unit_defs` has one row per
def (841 of them, all with build times) carrying the file it won from and its
`work_pool` (extractor -> expand, mobile -> factory, else base). `bar_unified.def_db()`
reads it and falls back to the dumps if unseeded.

**Every analysis is recorded, with its version.** The `runs` table holds
`file_name, file_version, function_name, function_version, user_name, build_name,
game_id, at_sec, input_state, output`. So builds accumulate data across games, and a row
whose `function_version` no longer matches the registry is visibly STALE and can be
re-run. That is the difference between a record and a cache: a record knows when it is
out of date.

```bash
python bar-calc/econ_db.py                    # what is in it
python bar-calc/econ_db.py --ingest           # (re)load the unit defs
python bar-calc/econ_db.py --defs armalab armck
python bar-calc/econ_db.py --runs [--function path] [--build "wind-conversion front"]
python bar-calc/econ_db.py --builds           # which builds have data collected
python bar-calc/econ_db.py --compare path --field ratio.per_cross   # across builds
python bar-calc/econ_db.py --stale            # rows a newer version supersedes
python bar-calc/econ_db.py --selftest
```
Dispatch: "what is the build ratio for X" -> `econ_api --run path --build X`; "compare
builds" -> `econ_db --compare`; "is that conclusion still valid" -> `econ_db --stale`.

### Build power is three pools, not one number

One BP figure is a fiction: what a point may legally build and where it stands both
matter. `split_bp` / `pool_bp_for` / `reassign_to_expand` in `bar_unified.py`:
- **EXPAND** claims metal spots. **Highest priority** - it raises the ceiling every other
  pool works under, and it is the only work containing a walk.
- **FACTORY** is a factory's own points. Factory products only, and **binary**: producing
  or idle. Base may **assist** it.
- **BASE** is con turrets, workers at home, the commander when home. Infrastructure and
  energy, or assist, or **give up a worker to expand**, which then walks to the next spot.

Builder POSITION is not in the stream, so the split is a stated policy and `policy` is
reported back with every answer. What IS measurable is `bp_delivered`: build work is
conserved, so completions in a window divided by the window is the build power that was
really working, split by pool. Cross-checked against the engine's own `bp_used` — 0.75x
from completions alone, 1.02x counting unfinished nanoframes, the rest being assist,
repair and reclaim.

### Phases come from the room left to grow

Two axes, six markers, all measured against the budget (`phase_markers`):
- **claiming**: `to_take` -> `tasked` (workers routed, with an expected completion time)
  -> `taken`.
- **spending**: `underpowered` -> `spend_current` (energy enough to spend the metal from
  spots HELD) -> `spend_projected` (enough for the whole budget) -> `scaling` (past that;
  only here is 70:1 defensible). Thresholds come from the work the metal is for (`on`),
  not from the generator being added.

**Metal bound is the goal ONLY while room remains.** With room it means "take another
spot". With the budget spent it means CAPPED, and the answer becomes an advanced
extractor, reclaim, or a converter. Nothing may print "add an extractor" when there is
none left to add.

### How long the next one takes (`time_to_build`)

Not `bp_cost / bp` — that is only right while the economy can pay at that pace. The real
duration is piecewise: full pace while a bank has something in it, then whatever income
alone feeds, and the two banks do not empty together. Walked analytically, at most two
bank-emptying events, no timestep. `--selftest` asserts it against a simulation across
eight regimes and eight units; worst error 0.018s on a 0.02s timestep.
```bash
python bar-calc/bar_unified.py --budget --position front --standing 4
python bar-calc/bar_unified.py --phases --game 1 --at 60 --workers 3
python bar-calc/bar_unified.py --cadence --game 1 --at 60 --items 10 [--measured]
python bar-calc/bar_unified.py --path --game 1 --at 60 [--objective most_economy_at]
python bar-calc/bar_unified.py --cadence-check --game 1 --unit Wind   # the honesty test
python bar-calc/bar_unified.py --share --game 1 --unit Wind
```
**The cadence at share 1.0 is a DEDICATED upper bound**, not a prediction: it points every
point of build power at one copy at a time. Measured against a real game it ran 2.4x fast,
which is exactly what the three pools explain. `--cadence-check` therefore tests the
BOUND (the dedicated figure must never be slower than reality) and reports the
measured-share fit as information, because the share is derived from those same gaps and
cannot disagree with them.

### Two workers together or apart, and what a spot is really worth

**Concentration** (`concentration_advantage`, `--concentrate`). Both policies finish the
n-th copy at the same instant, so a count at the end shows nothing. The difference is
entirely WHEN the earlier copies land: extra copies standing is
`D(t) = floor(t/tau) mod n` where `tau = W/(n*b)` — for two workers `[0, +1, 0, +1, ...]`,
mean `(n-1)/2` held **forever**. Two con bots on one turbine are permanently half a
turbine ahead, bought by ordering alone. Worth: half a turbine's output reinvested at one
price per TROI is `(n-1)/2 * exp(t/TROI)`; stepping it with a fixed `+1 segment/TROI` is
the Euler approximation, right to first order and undershooting later. One worker-build
is `W/b / TROI` of an ROI — 20/250 = **1/12.5** for a con bot on a turbine at 11.9 E/s.
The one way pooling loses is resources: n builders on one target draw n times per second,
so pass a state and `stall` says whether the pooled build stalls where split builds would
not.
```bash
python bar-calc/bar_unified.py --concentrate --unit Wind --workers 2 --wind 11.9
python bar-calc/bar_unified.py --extractor-rate [--units Mex,legmex,AMex,legmoho]
```

**Effective extractor rate** (`effective_metal_rate`, `extractor_rates`). An extractor's
energy flow is part of its metal rate: `net = spot m/s + energy_flow / 70`.
armmex `1.825 - 3/70 = 1.782` (-2.3%); **legmex `1.369 + 7/70 = 1.469` (+7.3%, a GAIN)`;
armmoho `7.300 - 20/70 = 7.014` (-3.9%). Net, Legion T1 goes from 75% of Armada to
**82%** — the energy it hands back closes 30% of the gap. Upkeep is per BUILDING and
flat, so a poor spot loses proportionally more (-2.3% on 1.825 against -1.4% on a 3.16
rich spot). `mex_budget` now reports NET by default with `*_raw` kept alongside, and the
whole 12-spot budget's `energy_flow_total` (-36 E/s for Armada). Legitimate only where
surplus energy actually converts — the `scaling` phase; earlier, upkeep is build power
you cannot feed, not metal lost.

### Unit catalog: every def by faction and by lab (`bar-calc/unit_catalog.py`)

**Nothing about the build tree is hard-coded any more.** The vendored widget now emits
`buildOptions` per def (local patch 2, see `gex_research/vendor/VENDOR.md`), `econ_db`
stores it as **5210 edges over 846 defs**, and `unit_catalog.py` is the view. So "an air
con needs an air lab" is a query, not a comment:

```bash
python bar-calc/unit_catalog.py --tiers [--faction Armada|Cortex|Legion]
python bar-calc/unit_catalog.py --tree --faction Legion
python bar-calc/unit_catalog.py --lab "air lab"        # what comes out of it
python bar-calc/unit_catalog.py --who aircon          # what gates it
python bar-calc/unit_catalog.py --options --have "com,bot lab,con bot"
python bar-calc/unit_catalog.py --catalog --all | --selftest
```

**The tiers are DERIVED**, breadth-first from the commander, and they reproduce the shape
by themselves. Rebalance the game and the layers move with it:

| depth | gated by | opens |
| --- | --- | --- |
| 1 | commander | mex, solar/wind/tidal, converters, storage, **6 T1 factories**, T1 defence |
| 2 | those factories | **workers** (con bot, air con, con vee, con ship) and 28 T1 units |
| 3 | a T1 worker | **con turret**, advanced solar, geo, **6 T2 factories**, T1 defence |
| 4 | a T2 factory | **T2 workers** (adv con bot/air/vee) and 46 T2 units |
| 5 | a T2 worker | **Moho**, fusion, advanced converter, T2 defence, **T3 gantry** |

**Faction** comes from the defName prefix, because BAR leaves `customParams.faction` empty
on 843 of 844 defs. Counts from the newest harvest: Armada 253, Cortex 262, Legion 244,
Other 87 (scavengers, raptors, shared).

**Classification puts ROLE before economics.** A bot lab holds 100 metal and a con bot
makes 7 E/s, so testing storage or energy first files every factory under storage and
every worker under energy. Kinds: commander, extractor, factory, worker, converter,
energy, storage, defence, unit, other. A T1 solar reports `energyProduction` 0 and carries
its 20 E/s as NEGATIVE upkeep, so the check goes through `econ_data.energy_flows` rather
than re-deriving it and disagreeing with the rest of the model.

**Aliases** live in `bar-calc/unit_aliases.json`, hand-edited and **never overwritten by a
harvest**; `econ_db --ingest` merges them so every reader resolves the same names. "aircon",
"nano", "moho", "bot lab", "com" all work. The selftest caught a wrong one on the way in:
`armamex` is the *Twilight*, a T1 stealth extractor at 200 metal, and the Moho is
`armmoho`.

### Harvesting a Legion-enabled game (`--find-demo`, `--installed-games`)

The def harvest replays ONE game, and a game only defines the factions the lobby enabled.
That is why Legion used to be *carried through* from an older file while everything else
refreshed. Now the demo is chosen on purpose:

```bash
python bar-calc/bar_unified.py --find-demo [--need Armada,Cortex,Legion] [--limit 200] [--refresh]
python bar-calc/bar_unified.py --installed-games
python bar-calc/bar_unified.py --harvest-defs --demo <path from --find-demo>
```
- Demo headers carry each player's faction, so a scan finds a game with all three. The scan
  is cached to `demo_index.json` because a header parse costs ~0.17 s and there are 9500+
  demos.
- **A demo is only usable if its game version is still installed.** Rapid keeps one `.sdp`
  per package plus a `versions.gz` mapping tag to name; intersecting them is the difference
  between a 26-second harvest and a `Fatal: Dependent archive not found` four seconds in.
  Every three-faction 8v8 on disk needed `test-31422-df3633c`, which rapid has replaced, so
  the finder now excludes them and says which version they wanted. A game recorded on the
  local sdd build reports `Beyond All Reason $VERSION`, which is BAR.sdd and IS loadable.
- Result: `units_20260928_155608.json`, **844 defs, `factionsMissing: []`, nothing
  carried** — arm 253, cor 260, leg 244, other 87 from one Legion-enabled game.
  Only 2 of 545 pinned values moved, both real: the source filename, and the Zeus at
  8000 -> 9500 build time (it also lost 550 health) between game builds.

### A dump is not the live game (`bar-calc/unit_overrides.json`)

A harvest is a snapshot of ONE build. `units_20260928_155608.json` came from the local sdd
checkout (the demo records the game as `Beyond All Reason $VERSION`), not a live rapid
version, so it still carries units the live game has removed. Showing those as build
options is worse than not having the tree at all.

`unit_overrides.json` is hand-edited and never overwritten by a harvest, same as the alias
file. `unavailable` hides a def from tiers, options and every builder's product list;
`--include-unavailable` still shows it for auditing, and `econ_db --ingest` prints what it
hid and why.

Currently marked: **`legmext15`**, the Overcharged Metal Extractor (250 metal, 2x
extraction, 30 E/s upkeep), removed from the live game 2026-09-28. Consequence, and the
selftest asserts it: **Legion now has no advanced T1 extractor.** `legmex` is its only
sub-T2 extractor, so its metal ladder is 50 metal then straight to the T2 `legmoho` at
640, exactly like Armada and Cortex.

### Energy production: negative upkeep IS production

A T1 solar reports `energyProduction` 0 and carries its **20 E/s as `energyUpkeep -20`**.
Any reader that trusts `energyProduction` alone sees a solar producing nothing, which is
what the first cut of the `unit_defs` table did. The resolved columns
`energy_production` / `energy_upkeep` now come from `econ_data.energy_flows`, the model's
single derivation, so the table and the calculator cannot disagree:

| def | production | upkeep | net |
| --- | --- | --- | --- |
| `armsolar` | 20 | 0 | +20 |
| `armadvsol` | 80 | 0 | +80 |
| `armfus` | 750 | 0 | +750 |
| `armmex` | 0 | 3 | **-3** |
| `legmex` | 7 | 0 | **+7** |
| `armwin` | 0 | 0 | none fixed |

A turbine is the exception and has no fixed output at all: `windGenerator` 25 is the
map-wind CEILING, and the real figure is the wind vector's length. `econ_db --ingest`
prints turbines as "up to N E/s on map wind" rather than as a production number.
```bash
python -c "import sys;sys.path.insert(0,'bar-calc');import econ_db as D;print(D.energy_flow('armsolar'))"
python bar-calc/unit_catalog.py --options --have legck          # removed units excluded
python bar-calc/econ_db.py --ingest                            # prints what it hid
```

### The pools inside the cadence and the path, and when to trust them

`share` is gone from the analyses: the pools say it properly. A turbine is BASE work, an
extractor is EXPAND work, a factory product is FACTORY work, and each target draws only on
the pool that may legally do it. A cross joins BASE, or EXPAND with `--assign expand`.

```bash
python bar-calc/bar_unified.py --cadence --game 1 --at 60 --pools --expanding 2
python bar-calc/bar_unified.py --path --game 1 --at 60 --pools --expanding 2 \
    --bpsrc BotWorker --assign expand
python bar-calc/bar_unified.py --spread --windows --game 1   # is the split even real?
```

**A cross must relieve the pool that is bound, and the path now refuses to pretend
otherwise.** Measured at t=60: with `on=Mex` and `bp_source=ConTurret` the walk returned
**4.5 Wind : 1 ConTurret**, against 9:1 on a single build-power number. Both are artifacts.
A con turret is immobile, joins BASE, and can never claim a metal spot, so the expand pool
stays empty, the saturation ratio stays pinned at infinity, and the walk keeps buying hands
that cannot do the job. `cross_relieves()` names the mismatch and the ratio is stamped
ARTIFACT. Swap to a con bot assigned to expand and the feed ratio decays honestly —
338%, 189%, 136%, 110%, 94% — crossing below 100% at **five con bots**, which is an answer.

**The disjoint-pool assumption is false early and true later**, and `placement_spread` /
`placement_windows` test it from data rather than assuming. Every placement carries
coordinates, so an extractor and a turbine going down within 150 elmos and 30 s of each
other is evidence that one crew did both. Windowed on game `20260925-204248`:

| window | co-located | expand median | base median | reading |
| --- | --- | --- | --- | --- |
| 0-60s | 90% | 138 | 155 | **one crew** |
| 60-120s | 62% | 547 | 433 | **one crew** |
| 120-180s | 0% | 1045 | 306 | separate |
| 300-360s | 25% | 162 | 378 | separate |

**Run it windowed.** Over 0-300s the same test reads 34% and concludes "separate crews",
because every co-located pair came from the first twenty seconds inside a 40-elmo home
cluster. Averaging that against a late game whose last extractor went 1445 elmos out
produces a number describing neither.

So: **the crews separate around 120s in that game.** Before then an "empty expand pool" is
a fact about the stated policy, not about the position, and the 30-90s verdicts are
unreliable. The sensitivity test agrees: moving the commander to `expand` flips 30-90s from
"buy expansion hands" to "off this chart", and the placements say the commander WAS doing
the early claiming. After 120s the verdict is stable under every policy — that game wanted
expansion hands, with 5 to 9 spots of room standing idle while energy climbed past 600 E/s.

`--selftest` pins the guard: a con turret must never be reported as relieving expansion,
and a Mex cadence against an empty expand pool must stop and say which pool is empty
rather than silently falling back to total build power.

**The old `--horizon` ASCII chart is retired.** Its marks were `int(t * chars_per_second)`
with a mod-10 label, so two completions inside one character overwrote each other and copy
12 printed as "2". `--cadence` draws one segment per copy at its true width. The ROI table
stays, because effective BPROI and the fed share are not computed anywhere else.

### The goal planner: "four advanced solars from here" (`goal_plan`, `--goal`)

A fixed end state makes the question definite in a way the open-ended walk never was.
There is no exit rule to argue about: the objective is the time to N copies, and a detour
for build power is worth it exactly when it lowers that number. Every cell of the grid is a
full re-simulation, so the answer is read off measured finish times.

```bash
python bar-calc/bar_unified.py --goal --game 1 --at 180 --goal-unit AdvSolar --count 4
python bar-calc/bar_unified.py --goal --count 6 --max-sources 3 \
    --state '{"metal":2000,"energy":8000,"m_inc":25,"e_inc":900,"bp":300}'
python bar-calc/econ_api.py --game 1 --at 180 --run "goal" --json
```

**Two dimensions, and they are not the same question.** One rises, the other falls, so they
cross:

| | what it asks | moves |
| --- | --- | --- |
| **ABLE** | can I pay for the source now, bank plus income, with no stall? | switches **ON** as income grows |
| **SENSIBLE** | does it arrive early enough to repay its own build time out of the copies still to come? | switches **OFF** as the goal approaches |

The window between them is where the detour belongs, and **it can be empty, which is itself
the answer.**

**Both regimes measured, and both pinned by `--selftest`:**

*Energy-bound, at t=180 in game 1* — 1250 BP, 313 E/s. Four advanced solars take 44.6s and
**every detour only adds time** (55s, 65s, 75s). The reason is printed rather than left to
be inferred: the goal itself stalls **42 of those 45 seconds on energy**, because 1250 BP on
an advanced solar wants 786 E/s against 313 coming in. More hands cannot help a build that
income already cannot feed. Window EMPTY, so build straight through and buy build power for
the next job.

*Build-power-bound, 300 BP on 900 E/s* — six advanced solars, nominal 26.5s each and no
stall.

| | j=0 | j=1 | j=2 | j=3 | j=4 | j=5 | j=6 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| k=0 | 159s | | | | | | |
| k=1 | 113s | 124s | 134s | 145s | 155s | 166s | 177s |
| k=2 | 96s | 112s | 127s | 142s | 157s | 172s | 187s |
| k=3 | **89s** | 106s | 124s | 142s | 160s | 177s | 195s |

Rows are how many con turrets, columns are inserting them after the jth solar. ABLE from
j=0, SENSIBLE to j=4, so the window is j=0 to 4. Best is three turrets first: **159s to
89s, a 70-second saving**, with each copy dropping from 26.5s to 9s. Past j=4 the detour
loses, because a source bought near the end has nothing left to repay it with.

The selftest also pins the structural claim that inserting after the LAST copy can never
beat inserting before it.

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

### Economy visualization (`live/eco_viz.py`) — replayer `--viz` / `--h2h`
Self-contained HTML reports (inline SVG, light+dark, hover tooltips, data table) written to `live/viz/`:
```bash
cd live && python replay_jsonl.py --viz [TEAM]        # one player: income, banks vs caps, value,
                                                       #   BP utilization, mex, value-composition stack
cd live && python replay_jsonl.py --h2h "A,B"          # head-to-head; each side is one of:
#   3                                — teamID from the replayed game
#   snap:<id>[:strategy]             — known state from positions/snapshots.json,
#                                      projected with a navigator strategy (default wind_med)
#   state:<file.json>[:strategy]     — any state_api dict from a file
```
So `--h2h "0,snap:leg-pos6-eco-t245-standard:solar_med"` = in-game player vs a theoretical line, and two `snap:` sides compare strategies from the same known state. Series data is also a registry analysis (`series[:team]` via `--run` / `POST /api/run`). Dispatch: "visualize the economy / eco report for team N" → `--viz N`; "compare player X vs Y / vs a theoretical build" → `--h2h`.

**Player-size bubble pairs** — each player is TWO circles. Left = size (stock):
concentric area-true layers, core = infrastructure value, +army, +banks; scaled
against the game's largest player. Right = activity (flow over a window,
default last 2 game-min): value built (eco/army) + |bank swing| + value
destroyed (eco/army), on its own shared scale. Fed by per-team flow counters in
`Live` (`unit_created`/`unit_killed` × unit values; killer team credited with
`enemy_killed`; eco killed with no enemy attacker ≈ own reclaim), carried into
every minute snapshot so windows recall at any point in time. `made` counts
construction **completed** (`unit_finished`, widget ≥ 2026-08-06); streams
recorded by older widgets fall back to construction-started counts
automatically. Caveat: a unit killed mid-construction still counts full value
as a loss, so losses can slightly exceed makes. Layer composition is data
(`eco_viz.INFRA_BUCKETS` / `ARMY_BUCKETS` / `LAYERS` / `ACT_LAYERS`). Replay:
`python replay_jsonl.py --bubbles [MINUTE] [--window MIN]`. Cards and the data
table also quantify **eco added in the last game-minute** per player
(`eco +X/min`, independent of the activity window); the same number is the
`eco_added` column of the `series` analysis and an "Eco added per minute"
chart + tile in the `--viz` player dashboard.

**Insights (`insights[:minute]` registry analysis + chips on bubble cards)** —
directional judgments from metric combinations, per window: trade efficiency
(army lost vs enemy value killed — flags the cheap-unit metal sink at <0.6x,
credits winning trades), bank swings judged by cause (spending down = good;
banking is good if fed by reclaim, a warning if BP is saturated, bad if BP is
idle), idle-BP-with-empty-bank recognized as the optimal fully-invested waiting
state, and cross-player army growth (bottom-half economy with the fastest net
army growth = losing less than the big ecos). CLI:
`python replay_jsonl.py --run insights` (or `insights:MINUTE`, `POST /api/run`).

**Live mode (server routes, same renderers)** — while a game runs,
`bar_analytic_server.py` serves the views at any point in time:
- `http://localhost:8787/viz` — player-size bubbles, auto-refresh (`?refresh=S`),
  with a minute strip; `?minute=N` recalls that game-minute.
- `/viz/player?team=N[&minute=M]` — full dashboard, series truncated to minute M.
- `/viz/h2h?a=<side>&b=<side>` — same side specs as `--h2h`.
Dispatch: "show player sizes / the bubble view" → open `/viz` (live) or run
`--bubbles` (replay).

### Economy hex infographic (`live/display_hex.py` → `/hex`, `live/viz/hex_*.html`)
`DisplayHex`: hex grid-point structure — clickable center (0) + six vertex
directions (1-6 clockwise from top), expanding faint hex rings as magnitude
tiers. Attributes render at (direction, magnitude, scale linear|log|custom);
metal=5 (bottom-left), bp=1 (top), energy=3 (bottom-right) form the weighted
triangle: perfect economy = equilateral at mid ring, an overweighted side sags
the triangle (distress fill) and lights the RESPONSE FLAG on the 180°-opposing
vertex (`opposite(d)`; catalog in `RESPONSES`). Orientation is view-only:
⟲/⟳ animate a directionalOffset (60° steps) while labels counter-rotate
upright (persisted in localStorage); `window.HEX` = extension surface
(rotate/setOffset/onPoint). First imbalance rule wired:
`check_reclaim_overload` (metal bank+income > spending+growth capacity with
energy limiting BP) → `solar_conturret_step` ("con turret while I have
energy, solar when I don't", loop until solved). Future: response REGION maps
(overlapping options like wind@16 vs solar) — the flag catalog is the seam.
- Live: `http://localhost:8787/hex[?team=N][&minute=M][&rot=P][&refresh=S]`
- Offline: `python display_hex.py --game <ref|1> [--team N]`; `--demo` runs
  the synthetic states + reclaim-rule assertions.

### Build-order chronicle site (`live/build_orders.py` → `live/builds/` + `live/viz/builds.html`)
Website featuring named build orders extracted from recorded games: per-build
completion timeline (mex, wind, solar, worker, factory, converter, advsolar
+ nano/moho/advconverter), per-minute resource snapshots (current bank,
income, cumulative gathered), auto benchmarks (nth-completion times, counts at
3/5/8/10 min), and a benchmark-comparison table across ★ starred builds.
Completion times are **recorded** (`unit_finished`); old streams fall back to
created+estimated (flagged). Names are auto-suggested from the 5:00 shape
(`wind-conversion 7mex/24wind/3solar@5:00 (SL4rk)`) and editable — inline on
the page (localStorage overlay + shows the CLI to persist) or canonically via
CLI. Library = `live/builds/*.json` (committed, curated).
```bash
cd live && python build_orders.py extract <game|1|substr> --player NAME [--name S] [--star]
python build_orders.py list | rename <id> "..." | star <id> [--off] | render
```
Live: `http://localhost:8787/builds` (re-renders from the library on request).
Dispatch: "add X's build from game Y to the site" → `extract`; "open the build
orders site" → `start live/viz/builds.html` or the server route.

### Player-behavior database (`live/player_db.py` → `live/players.db`)
Cross-game SQLite DB of pseudo-subjective gameplay tendencies. Per game it
stores one **appearance** per player (name, geometric position class from
spawn lanes — `front-corner`, `back-mid`, … — lane index, factories built,
end value) and one **observation** per detected trait (minutes + evidence
JSON). Traits are pure detectors over `eco_viz.flow_series` (per-minute
behavioral deltas) in `player_db.TRAITS` — currently: `techs_over_t1` (stops
making units to tech, evidence says whether while losing), `hoards_while_ecoing`,
`feeds_cheap_units` (sub-0.6x trades), `chronic_idle_bp` (idle BP with a full
bank only), `recycles_eco`. **Tags are role-relative**: a trait may carry a
`notable_at` position predicate — observations are recorded for everyone, but
tags fire only where the behavior is OUT of role (teching instead of T1 is the
tech player's job; it's a tell from front/corner). Aggregation = "trait shown
in N of M games at that position" → tag lines like `X: hoards metal while
ecoing as back-corner — 3/4 games (75%)`. Adding a trait = one entry in
`TRAITS`.
- The server **auto-ingests every game at game-end**; manual/backfill:
  `python player_db.py ingest <jsonl|archive-id|1>` or `ingest --all`.
- Query: `python player_db.py tags [name]` / `player <name>` (full profile) /
  `traits` / `games`. In-game view: `tags` registry analysis
  (`--run tags` / `POST /api/run`) returns known tendencies for the players
  in the current game.
- Rebuild from archives any time: `python live/player_db.py ingest --all`
  (DB is gitignored).

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
- "is reclaiming X for Y worth it" / "solar reclaim break-even" → `node planner/reclaim-breakeven.mjs --from=solar --to=wind --bp=N --wind=N [--sweep]`

### Reclaim swap break-even (`planner/reclaim-breakeven.mjs`)
Answers "I reclaim an eco building to unlock metal for idle BP — how many seconds until the
replacement is net energy-positive vs. leaving it alone?" Clock starts when the reclaim
*completes* (the old building produces until then, so both branches are identical before that).
`tau = Tb + D/R` where `Tb = n*BW_to/bp`, `D = E_from*Tb + n*E_to − early income`,
`R = n*W − E_from`. Prints serial/parallel × fractional/whole-unit bounds, the construction
drain rate (`bp*E_to/BW_to` — the real stall risk), and the **infinite-BP floor**
`n*E_to/(n*W − E_from)`: more build power cannot rescue a bad swap. `--sweep` tables it against
map wind and BP. Costs come from `planner/data/units.json`.

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

## Lobby watchers (`bar_watchers/`)

Long-running BAR battle-list watcher service, moved here from `ryan_adapter`
(2026-07-31; the old copy has a MOVED.md). Polls api.bar-rts.com, spawns
per-game watchers on qualifiers, archives snapshots/events/replays to SQLite,
renders a dashboard, alerts on watchlist players. Self-contained — full docs in
`bar_watchers/README.md`.
- Install/re-point scheduled task: `cd bar_watchers && install_supervisor_task.bat`
- Read state: `python bar_watchers/game_coordinator.py list|active|target-json`
- Fetched `.sdfz` replays land in `bar_watchers/replays/` → feed `sdfz-demo-parser`.

## Bot loop — Watcher → Decider → Acter (`barbots/decider,adapter,bots`)

Realtime bot pipeline, distributed over the generic relay hub in
`../ryan_adapter/relay/` (content-blind message router + session ledger +
replay; see its README). Roles, each independently runnable (own PC ok):

```
watcher   live/bar_analytic_server.py /api/state          (already existed)
decider   barbots/decider/decider.py  — snapshot → analyses.team_state →
          navigator.step_options → playstyle weighting → intent
adapter   barbots/adapter/bar_adapter.py — intent → keyboard/mouse transcript
          (transcript.py + keymap.json, executor action dialect)
acter     ryan_adapter: python -m relay acter --backend dry|interception
```

Playstyles = data-only profiles in `barbots/decider/profiles.py` (`balanced`,
`greedy_expand`, `energy_first`, `tech_rush`, `tempo`): bias multipliers per
action + energy_floor / bank_target / horizon patience / energy_relax. Same
state, different weights → different build orders.

### Dispatch phrases → action
- "run the bot offline / on the last game" → `cd barbots/bots && python run_bot.py --offline <jsonl|1> [--profile P]`
- "demo the bot chain" → `python run_bot.py --demo <jsonl|1>` (hub+adapter+dry acter in-process, full relay round-trip)
- "run the bot live" → start hub (`ryan_adapter: python -m relay hub`), adapter (`python barbots/adapter/bar_adapter.py`), acter (`python -m relay acter`), then `python run_bot.py --profile P`
- "what would each playstyle do" → `cd barbots/decider && python decider.py --game 1 --all-profiles`

### Known gaps (deliberate v1 seams)
- Placement clicks are screen-anchor placeholders (`keymap.json` places) — real
  world→screen projection needs camera state (see `barbots/docs/architecture.md`).
- `keymap.json` grid keys are unverified against actual in-game bindings.
- Decision space = economy only (`positions/state_api.py` ACTIONS); `mex_cap=7`
  stands in for map mex spots.
- Real input backend = Interception driver (`ryan_adapter/executors/`); default
  everywhere is `dry`.

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

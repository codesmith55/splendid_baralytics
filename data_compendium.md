# Capability compendium

Routing by intent: if you are trying to do X, these are the functions and flags.
Everything lives in `bar-calc/bar_unified.py` unless stated. Surveyed 2026-09-23
against the actual source, so names here are real.

```bash
python bar-calc/bar_unified.py <flag>          # everything below has a CLI form
```

---

## Routing table

| If you want to… | Use |
|---|---|
| find a game without hunting filenames | `resolve_game` · `--games` |
| know who played it | `roster` · `resolve_player` |
| turn a game into facts on disk | `extract_game` · `--extract` |
| read those facts back | `load_game_data` · `--data` |
| analyse the facts | `@analysis` · `run_analyses` · `--analyze` |
| know what the wind did | `RecordedWind` · `WindModel` · `--wind` |
| know the map's spots and wind range | `read_map` · `--map` |
| get a unit's real cost | `econ_data.unitdef` · `OBJECTS` · `--objects` |
| refresh unit costs from the game | `harvest_unit_defs` · `--harvest-defs` |
| see what was reclaimed | `reclaim_runs` · `--reclaim-runs` |
| split metal into mex / converter / reclaim | `metal_sources` · `--metal-sources` |
| see what was built and when | `build_timeline` · `path_from_replay` |
| compare whole strategies | `BuildPath` · `run_paths` · `--paths` |
| find where an answer flips | `ANALYTICAL` · `breakpoint_table` |
| do resource algebra | `drain_rates` · `generator_breakevens` · `--rates` |
| simulate an opening | `simulate_opening_parallel` · `--openings` |
| check the model still holds | `--selftest` · `--wind-validate` |

---

## Finding a game

`resolve_game(spec)` takes whatever you have: `1` for the newest, a local
wall-clock time like `"11:21"` or `"2026-09-23 11:06"`, an extracted game id like
`"20260923-180706"`, a favorite label, a filename substring, or a path. Filters:
`matchup="1v0"`, `player="Splend"`.

- `recent_games(count, matchup, player)` / `print_recent_games` → `--games 10 --matchup 1v0`
- `game_ref(n)` — Nth most recent, 1 is newest
- `ensure_actions(ref)` — the replayed event stream, replaying headlessly if needed
- `add_favorite(label, ref)` → `--favorite "morning-eco" --game 1`
- `roster(ref)` → `PlayerData` list; `resolve_player(ref, name)` picks one and
  records `chosen_because`. Preference: `--player`, then the only player, then
  `DEFAULT_PLAYER` (`SplendYoMetal`, or `$BAR_PLAYER`), then first on the roster.

Replaying is `node bar-calc/replay_demo.mjs --demo <ref>`, about 60 s for a
ten-minute game. `--list --only 1v0` browses.

## Facts out of a game

`extract_game(spec, player=, team=, until_sec=)` → `bar-calc/data/<id>-team<N>.json`.
Facts only. Read back with `load_game_data(ref)`, list with `list_game_data()`.

Contents: `game`, `player`, `roster`, `mexes` (n, t, x, z, dist, walk_sec, spot,
spot_metal_per_s), `completions`, `wind` (samples, 15 s windows, min/max/mean),
`econ` (the measured 15 s series), `reclaim`, `deaths`.

## Analysing the facts

```python
@analysis("name")
def _fn(data: dict) -> dict: ...
```
`run_analyses(data)` runs all; `--analyze 1`. Registered: `mex_timing`,
`wind_profile`. An analysis reads hard data and nothing else — if it needs a fact
that is not there, add it to `extract_game` and re-extract.

## Wind

- `RecordedWind.from_game(ref)` — one real game's wind; `.at`, `.average`,
  `.energy_between`, `.forecast`, `.droughts`, `.map_range`
- `WindModel(min, max, seed)` — the engine's generator for distributions
- `wind_income(min, max)` — real expectation; `flat_wind_income` is the midpoint,
  kept only to show how wrong it is
- `validate_wind_model()` → `--wind-validate`

## Map

`read_map(name)` → `MapInfo`: `mex_spots`, `wind_range`, `start_positions`,
`geo_spots`, `features`, `extractor_radius`. Methods `spots_from(x, z)`,
`spots_for_team`, `spot_metal_per_s`, `rocks`. Cached to `bar-calc/map_data/`,
keyed by archive so versions never collide. `--map "all that glitters" --team 0`.

## Unit costs

`OBJECTS` is the model table; `econ_data.unitdef(defName)` is the raw engine def.
Both resolve from `bar-calc/econ_model.json` plus the harvested dumps. Never type a
cost into a model file — change the config or refresh the dump, then
`--write-parity` and the three selftests.

`harvest_unit_defs()` → `--harvest-defs` replays the newest 8v8 just far enough to
capture the frame-0 defs, about 40 s, and carries forward any faction that game did
not load.

## Reclaim

`reclaim_runs(actions)` splits per-frame `metalMake` into contiguous runs and
identifies each: a corpse that can account for the metal beats a price match.
Unmatched is `rock_or_wreck`. `--reclaim-runs <actions.json>`.

`metal_sources(actions)` splits a team's metal into mex / converter / reclaim;
`reclaimers()` ranks the units doing it. `--metal-sources`, alias `--reclaim`.

Needs `reclaim_sample`, which is a **local patch** to the vendored widget.

## Build paths and breakpoints

- `BuildPath(name, steps=[BuildStep(unit, walk_sec)], rule=fn)` — a whole strategy
- `run_path(path)` → `PathTrace` with full series, events and a bounds proof
- `trace_from_replay(actions)` — a played game as the same trace type
- `path_from_replay` / `register_replay` — persist a played order to `bar-calc/paths/`
- `breakpoint_table(traces, registry=ANALYTICAL)` — where answers flip
- `run_paths([names])` → `--paths`, `--list-paths`

`ANALYTICAL` holds crossings (wind past the metal or build-power break-even, metal
outrunning build power, energy overflowing). `BREAKPOINTS` holds milestones (nth
mex, first factory). Both are dicts you can extend.

## Resource algebra

`drain_rates(unit, bp)` — metal and energy per second at that build power.
`sustainable_bp(unit, m_inc, e_inc)` — how much build power your income can keep
busy. `bank_runway(...)` — how long a bank funds it. `energy_ceiling(bp)` — the most
energy build power can consume; above it is overflow. `generator_breakevens()` —
the three separate wind speeds. `--rates`.

## Simulating

`simulate_opening_parallel(generator, wind=, mex_walk_sec=, gen_walk_sec=)` runs
concurrent builders against a shared pool and raises if a bank goes negative.
`compare_at_time(t)` → `--even-time --at 180`. `--openings --sweep` sweeps wind.

Serial `simulate_opening` also exists; it idles the economy during walks and
overstates banks. Prefer the parallel one.

## Verifying

```bash
python bar-calc/bar_unified.py --selftest        # 545 values vs parity.json
python positions/state_api.py --selftest
node splendid_buildSimulator.js --selftest
python bar-calc/bar_unified.py --wind-validate
python bar-calc/econ_data.py --check             # drift in tables not on the layer
```

---

## Where the data lives

| Store | Path | Scale |
|---|---|---|
| Demos | `<BAR>/data/demos/*.sdfz` | 9,415 files, 14 GB, 2026-04 onward |
| Replayed events | `%TEMP%/gex_harness/wd_*/actions.json` | 2-7 MB per game |
| Live archives | `live/games/*.jsonl` | 41 files, 1.7 GB |
| Engine defs | `bar-calc/units_<dateTime>.json` | 825 defs |
| Map cache | `bar-calc/map_data/` | 8 of 483 archives read |
| Hard data | `bar-calc/data/` | per extraction |
| Paths | `bar-calc/paths/` | per registered build |

Nearly everything recent is All That Glitters: 268 of the newest 300 demos.

### What a replayed game contains

| Event | Carries |
|---|---|
| `extra_stat_update` | **measured economy every 15 s**: banks, income, storage, build power available and used, value split, transfers |
| `unit_finished` | completion — the honest timing signal |
| `unit_created` | the order, with spawn position |
| `unit_def` | full engine def per type, frame 0 |
| `wind_update` | value and the 2-D vector, every 5 s |
| `reclaim_sample` | per-frame metalMake per unit, with position (**local patch**) |
| `unit_killed` | death with position, attacker, weapon |
| `unit_resources` | lifetime totals, only at death or game end |

Not in the stream: player names (they are in the demo header), rock/feature
tracking, and what a reclaim consumed.

---

## Established numbers

| Quantity | Value |
|---|---|
| Mex energy drain at 300 BP | 83.3 E/s |
| Commander passive energy | 30 E/s |
| Opening bank funds | 3.1 extractors before energy empties |
| Wind beats solar on metal above | 5.48 E/s |
| Wind beats solar on build power above | 12.31 E/s |
| Wind beats solar on build energy | never |
| Building reclaim returns | 100% of metal cost |
| Wind update period | 450 frames, 15 s, smoothstep |

The 3.1-extractor figure matches the three free mexes in every solo replay checked.

---

## Traps

- **Demo filenames are UTC, mtimes are local.** A 09:22 game reads 16:14. Go
  through `resolve_game`.
- **The widget carries a local patch** for `reclaim_sample`; see
  `gex_research/vendor/VENDOR.md`. A re-vendor silently removes it.
- **A defs-only harvest is not a gameplay replay.** `ensure_actions` checks for
  `unit_finished` before trusting a cached file.
- **Solo games never end**; the idle watchdog stops the replay.
- **`unit_created` is an order, `unit_finished` is a completion.**
- **`unit_resources` is a lifetime total, not a series.** Use `reclaim_sample`.
- **`trace_from_replay` reconstructs income from completions and leaves banks at
  zero.** `extra_stat_update` has the measured values every 15 s and this should be
  revisited.
- **Two similar names:** `resolve_game` finds a demo, `resolve_live_jsonl` finds a
  widget archive. They shadowed each other once.

---

## Extension points

| To add | Put it in |
|---|---|
| an analysis | `@analysis("name")` |
| an analytical breakpoint | `ANALYTICAL` |
| a milestone | `BREAKPOINTS` |
| a build path | `PATHS`, or `register_replay` from a game |
| a reclaim target | `RECLAIM_CATALOG` (54 entries) |
| a unit or calibration | `bar-calc/econ_model.json`, then `--write-parity` |
| an engine data source | `econ_model.json` `engineDefs` |

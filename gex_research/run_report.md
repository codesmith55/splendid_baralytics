# run_report.md — first successful local headless stat extraction

**Date:** 2026-06-09 · **Status:** ✅ working end-to-end, no full Gex stack, no downloads.

Proved the [`headless_harness.md`](./headless_harness.md) recipe against the **local BAR install** using
the vendored `gex.lua` widget. Both user goals demonstrated:
1. Run a replay → dump per-player/per-team stats to file ✅
2. Calculate NEW stats from that dump ✅

---

## What ran (the exact working invocation)

Key discovery: **the local BAR install already has everything** — no engine/game/map download needed.
- Install: `C:\Users\codes\AppData\Local\Programs\Beyond-All-Reason\data`
- Engine used: `…\data\engine\recoil_2025.06.24\spring-headless.exe` (matches demo's `_2025.06.24` tag)
- Demos: `…\data\demos\` (14,173 of them)

**Isolation strategy (important):** the user's real `…\data\LuaUI\Config\BYAR.lua` is 792 KB (their whole
widget config). We must NOT touch it. So we run with an **isolated write-dir** that *shadows* it, and add
the BAR data dir as a read-only source:

```powershell
$BAR = "C:\Users\codes\AppData\Local\Programs\Beyond-All-Reason\data"
$ENG = "$BAR\engine\recoil_2025.06.24"
$WD  = "$env:TEMP\gex_harness\wd"            # isolated, disposable

# install widget + tiny enable-config into the isolated write-dir
#   $WD\LuaUI\Widgets\gex.lua   <- vendor\gex.lua
#   $WD\LuaUI\Config\BYAR.lua   <- vendor\BYAR.lua   (order={game_event_extractor=1})

# start script with ABSOLUTE demofile path
"[game] {`ndemofile=<ABS .sdfz>;HostPort=50124;`n}" | Set-Content "$WD\_script.txt" -Encoding ASCII

$env:SPRING_DATADIR = "$WD;$BAR"             # write-dir first (writable+shadow), BAR data = read
& "$ENG\spring-headless.exe" --write-dir "$WD" "$WD\_script.txt"   # cwd = $ENG
# output: $WD\actions.json
```

Engine confirmed it loaded the map (`all_that_glitters_v2.2.3.sd7`) + game content straight from the BAR
data dir, and the widget logged `[Gex] started gex!, true` (headless=true) → `starting game event extractor`.

## Performance

| demo | size | game length | headless wall-clock | speedup |
|---|---|---|---|---|
| `2026-06-09_14-56-38-076…` | 133 KB | **aborted** (spectator quit @ frame 0) | ~45 s (mostly load) | — |
| `2026-06-09_14-59-25-160…` | 1.65 MB | 23,192 frames (~13 min, 8v8) | **137 s** | ~10× realtime |

> Lesson: demo file size ≈ game length. Tiny demos (<150 KB) are aborts/specs and emit only `unit_def` +
> `init`/`shutdown` — pick ≥1 MB demos for real games. The harness still ran correctly on the aborted one;
> it just had nothing to simulate.

## Output: 19,533 events in `actions.json` (3.67 MB) — see `sample_output/actions.json`

```
6747 unit_position   2512 unit_created   2228 commander_position_update
1590 unit_killed     1539 unit_resources 1414 unit_damage
 925 factory_unit_created   848 extra_stat_update   848 team_stats
 593 unit_def   155 wind_update   48 unit_taken   48 unit_given
  13 transport_loaded/unloaded   8 team_died   1 start/end/init/shutdown
```
Every stat category from `gex_process.md` is present. `team_stats` + `extra_stat_update` are the per-team
backbone; `unit_resources`/`unit_damage`/`unit_created` roll up per team via their `teamID`.

---

## GOAL 1 — per-team stats dumped to file (final/cumulative, end of game)

From `team_stats` (engine history, max-frame per team) + `extra_stat_update` (gex custom, final per team).
8v8: teams 0–7 = side A (won), 8–15 = side B (all died @ frame 22,740 = lost).

| team | metalProd | enProd | dmgDealt | dmgRecv | unitsProd | unitsKill | armyVal | ecoVal | BPused | APM |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 20978 | 300575 | 48227 | 37699 | 173 | 47 | 2100 | 8559 | 625 | 725 |
| 2 | 23418 | 291376 | 64266 | 49488 | 205 | 82 | 1134 | 10128 | 1490 | 685 |
| 3 | 21171 | 384269 | 68098 | 60784 | 212 | 67 | 3791 | 5682 | 2790 | 590 |
| 5 | 20184 | 364659 | 66927 | 45338 | 183 | 92 | 2870 | 6801 | 90 | 615 |
| 8 | 18619 | 258384 | 73260 | 69437 | 161 | 42 | (dead) | — | — | 686 |
| 11 | 14914 | 207353 | 53921 | 71599 | 177 | 49 | (dead) | — | — | 721 |
| … | (all 16 teams captured) | | | | | | | | | |

(Composition `armyVal/ecoVal/BP` reads 0 for side-B teams because they're dead at the final frame; their
mid-game values are in the 848 time-series `extra_stat_update` rows.)

**Per-player:** identical table — 1 team = 1 player here. The only missing piece is the **name↔teamID
roster**, which is NOT in the action log; it comes from the demo header (gex's `BarDemofileParser`) or the
BAR API. Follow-up: parse the `.sdfz` header (or use the JS `sdfz-demo-parser` already in this repo).

---

## GOAL 2 — NEW stats we calculated (gex does NOT dump these)

Pure functions over the dumped events — the whole point of running locally. These cleanly separate winners
from losers, which validates them as signal:

| team | side | dmg/metal | tradeRatio (dealt/taken) | energy:metal | metalExcess% | killsPerUnit | APM |
|---|---|---|---|---|---|---|---|
| 0 | A won | 2.30 | **1.28** | 14.3 | 0.0 | 0.27 | 725 |
| 2 | A won | 2.74 | **1.30** | 12.4 | 0.0 | 0.40 | 685 |
| 5 | A won | 3.32 | **1.48** | 18.1 | 0.0 | 0.50 | 615 |
| 9 | B lost | 1.48 | 0.45 | 25.2 | 0.0 | 0.10 | 767 |
| 10 | B lost | 0.36 | 0.32 | 17.5 | 0.0 | 0.04 | 438 |
| 12 | B lost | 2.92 | 0.55 | 19.5 | 5.1 | 0.36 | 656 |
| 13 | B lost | 0.36 | 0.50 | 19.0 | **23.6** | 0.06 | 412 |

**Signal:** winning side A trade ratios cluster ≥1.0 (won their fights); losing side B mostly <1.0. Team 13
also bled 23.6% of its metal as excess (eco mismanagement). None of these numbers exist in gex's output —
we derived them from the raw event dump.

**Side (allyteam) totals, derived by summing teams:**
| side | metalProduced | damageDealt | unitsKilled | unitsProduced |
|---|---|---|---|---|
| A (won) | 159,563 | 320,785 | 369 | 1,282 |
| B (lost) | 125,804 | 279,700 | 233 | 1,230 |

---

## Reusable pipeline established

`pick demo → spring-headless (installed engine, isolated write-dir) → actions.json → parse line-delimited
JSON → per-team aggregate → derive new stats`. No web server, no Postgres, no downloads, user's config
untouched. ~137 s/game; batchable across the 14k local demos (distinct ports + write-dirs for parallelism).

## Next steps
1. **Roster join** — parse `.sdfz` header for name/faction/skill ↔ teamID (so tables show player names).
2. **Time-series** — use the 848 `extra_stat_update` + `team_stats` rows (not just final) for build-order /
   eco-curve / army-timing stats.
3. **Wrap** the PowerShell into a `splendid_baralytics` batch runner + a JS/TS `actions.json` parser module.
4. **Per-unit-type** analysis from `unit_created`/`unit_resources`/`unit_damage` joined to `unit_def` names.

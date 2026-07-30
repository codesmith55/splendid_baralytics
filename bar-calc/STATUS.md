# BAR Calc — Consolidated Status

> **`splendid_baralytics` is now the canonical home for all Beyond All Reason (BAR)
> economy / build / cost calculation work.** This folder gathers every BAR
> calculator that was previously scattered across other repos and archive folders.
>
> Generated 2026-06-06. These are **copies** — the originals still exist at their
> source paths (listed below) and have *not* been deleted yet. Once you confirm
> this collection is complete and correct, the source copies can be removed as
> part of the wider reorg (see `../../REORG-INVENTORY.csv`).

BAR's economy rests on three resources — **Metal (M)**, **Energy (E)**, and
**Build Power (BP)** — and every tool here models some slice of converting those
into builds, ROI, and timing.

---

## Subfolder map

| Subfolder | What it is | Status |
|-----------|-----------|--------|
| `eco-calculator-suite/` | The most complete, most recent toolkit (build DB + eco sim + guide + data) | ✅ **PRIMARY — active** |
| `build-order-calc/` | Object-oriented build-order economy model + strategy notes | 🟡 Working, secondary |
| `wind-simulator/` | Wind-income simulator + build-time calculator (the "Wind Simulator" project) | 🟡 Working, standalone |
| `build-time-calculator/` | Earliest resource-wait/build-time calculator (sequential + greedy) | 🟠 Stale (2024), superseded |
| `misc-calculators/` | One-off economy-state simulator experiment | 🟠 Experimental scratch |
| `references/` | Spreadsheet, text guides, idea notes, source dumps | 📄 Reference data |

---

## `eco-calculator-suite/` — ✅ PRIMARY (active, May 2026)
**Origin:** `workflow-dashboard/contentManageMaker-migrated/guild/BAR/`
The richest and most recently worked-on collection — treat this as the base to
build the consolidated tool on.

| File | Role |
|------|------|
| `eco_simulator.py` (586 L) | Largest piece — time-stepped economy simulator |
| `eco_calculator.py` (278 L) | Core ROI / payback calculator |
| `build_db.py`, `build_export.py` | Build the SQLite unit/build database and export it |
| `builds.db`, `builds.json` | Generated build data (M/E/BP cost tables) |
| `build_explorer.html` | Browser UI for exploring builds |
| `worker_analysis.py` | Worker / build-power analysis |
| `Combined_Bar_Stats.csv`, `arm_structures.csv`, `bar_eco_table.csv` | Unit/structure stat tables |
| `eco_guide.md` | Written eco theory (payback times, TROI @ 70 E = 1 M) |
| `eco_guide_old.md` | Prior version of the guide — diff then delete |
| `air_steps.md` | **Empty** (0 bytes) — placeholder, delete or fill |
| `laudyCreeping.md` | Short strategy note (Oct 2024) |

**Cleanup notes:** `builds.db-journal` and `__pycache__/` were intentionally *not*
copied (SQLite temp + Python bytecode). `eco_guide_old.md` is a near-duplicate of
`eco_guide.md`. `air_steps.md` is empty.

## `build-order-calc/` — 🟡 working secondary (May 2026)
**Origin:** `splendid_dashdev/`
- `bar_calc.py` (396 L) — clean OO model: `BuildingType` / `UnitType` with
  metal/energy/buildpower cost + income. Good candidate to merge into the suite.
- `bar_economy.md` — concise in-game decision rules ("course corrections":
  wind / solar / e-storage / converters by M/E state).

## `wind-simulator/` — 🟡 working standalone (May 2026)
**Origin:** `Obsidian_RyLife/Beyond-All-Reason-Wind-Simulator-master/`
- `wind_simulator.py` — simulates variable wind income.
- `build_calculator.py` (550 L) + `build_calc_vibe.py` — build-time calculators.
- `vector.py`, `utils.py` — helpers.

> ⚠️ The original folder also contained a `Description.md` that is **unrelated
> coursework (NewsGenie)**, not BAR — it was deliberately excluded.
> Two stale duplicates of this project also exist (top-level
> `Beyond-All-Reason-Wind-Simulator-master/` is double-nested + a `.zip`); this
> Obsidian copy was the most complete and was used as the source.

## `build-time-calculator/` — 🟠 stale, superseded (Dec 2024)
**Origin:** `2024down/scuffed_dash/`
- `build-time-calculator.py` (225 L) + `_sequential.py` — the earliest take on
  resource-wait + build-time math. Logic is now better covered by the suite;
  kept for reference / salvageable ideas.

## `misc-calculators/` — 🟠 experimental (May 2026)
**Origin:** `scavengers_guild/gamejunk/`
- `yetanotherbarcalc.py` (78 L) — a compact `EconomyState` experiment. Scratch.

## `references/` — 📄 reference data
| File | Origin |
|------|--------|
| `Game-BAR-Cost Calc.xlsx` | GitHub root — spreadsheet cost calc (Mar 2025) |
| `bar_guide.txt` | GitHub root — general BAR guide |
| `Bar Calc AI.md` | `Obsidian_RyLife/05 - Content Ideas/Games/` — idea note |
| `Beyond_All_Reason_build_calculator__*.txt` | guild Claude-dump input |
| `Calculating_Build_Time_for_Wind_Turbine__*.txt` | guild Claude-dump input |

---

## Source paths (originals, not yet deleted)

```
workflow-dashboard/contentManageMaker-migrated/guild/BAR/        -> eco-calculator-suite/
splendid_dashdev/bar_calc.py, bar_economy.md                     -> build-order-calc/
Obsidian_RyLife/Beyond-All-Reason-Wind-Simulator-master/*.py     -> wind-simulator/
2024down/scuffed_dash/build-time-calculator*.py                  -> build-time-calculator/
scavengers_guild/gamejunk/yetanotherbarcalc.py                   -> misc-calculators/
Game-BAR-Cost Calc.xlsx, bar_guide.txt (root)                    -> references/
Obsidian_RyLife/05 - Content Ideas/Games/Bar Calc AI.md          -> references/
guild/converter/0507claudedump/inputs/*build*calc*.txt           -> references/
```

## Distance & worker walk-time model (`eco-calculator-suite/bar_distance.py`)

New module added 2026-06-07. Converts **map grid distance → elmos → worker walk
time**, replacing the old hand-guessed walk constants.

**Engine ground truth** (read from `units/*.lua` in the BAR game repo):

| Unit | build range (elmos) | move speed (elmos/s) |
|------|--------------------:|---------------------:|
| Commander (armcom) | 145 | 37.5 |
| Construction Bot (armck) | 130 | 36.0 |
| Construction Turret (armnanotc) | 400 | 0 (static) |

**Grid calibration** (the one tunable assumption): the in-game start grid
squares show true distance; the commander's build-range circle was observed to
be "just larger than 3 squares". Taking build range (145) as the circle radius
→ **1 grid square ≈ 48.3 elmos** (`BUILD_RANGE_IN_GRID_SQUARES = 3.0`).
A builder only walks until the target is *within build range*, so walked
distance = `max(0, gap − build_range)`.

> ⚠️ **One number to verify:** if "3 squares" was the build-range *diameter*
> (radius ≈ 1.5 squares), set `BUILD_RANGE_IN_GRID_SQUARES = 1.5` and every walk
> time **doubles** (1 square ≈ 96.7 elmos). This flips whether the 3 starting
> mexes need any walking at all.

**Integration:**
- `eco_simulator.py` now accepts walk steps as `walk_squares` / `walk_elmos`
  (converted per the walking unit) in addition to legacy `walk_delay` (seconds).
- `worker_analysis.py` derives `MEX_WALK_TIME` from the model
  (`MEX_EXPAND_DISTANCE_SQUARES`, placeholder = 5 sq — measure your real
  expansion distance) instead of the old flat `45`.

Run `python bar_distance.py` for a quick walk-time reference table.

## Recommended next steps
1. **Consolidate around `eco-calculator-suite/`** — fold `build-order-calc/bar_calc.py`'s
   clean class model into it; pull the wind-income model from `wind-simulator/`.
2. **Delete the superseded** `build-time-calculator/` once its ideas are salvaged.
3. **Resolve guide duplication** (`eco_guide.md` vs `eco_guide_old.md`) and the
   empty `air_steps.md`.
4. After verifying nothing is lost, **delete the source copies** per
   `../../REORG-INVENTORY.csv` (the guild/BAR original, scuffed_dash, the
   wind-sim duplicates, etc.).
5. Consider committing this `bar-calc/` tree to `splendid_baralytics` on GitHub.

---

### Not included (intentionally)
- **Upstream game clones** (`2025down/Beyond-All-Reason/`, `2024down/teiserver/`,
  `2025down/gex/`) — these are third-party BAR *game/server* repos, not your
  calculators. Their `economy.json` / `*_econ.*` files are game data, not tools.
- **Chemistry/business "economics"** files in the guild (`pcy/economics.py`,
  `Calcium_*`, `Glycerol_*`, `zap_economics.html`) — unrelated to BAR.
- **`.claude/worktrees/` copies** — autogenerated worktree mirrors.

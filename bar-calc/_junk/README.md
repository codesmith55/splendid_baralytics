# `_junk/` — pre-consolidation originals. Do not start here.

Everything in this folder is **superseded**. The one file to use and extend is
[`../bar_unified.py`](../bar_unified.py); its numbers come from
[`../econ_model.json`](../econ_model.json) + the engine dumps, via `../econ_data.py`.

These copies are kept for one reason: a few capabilities listed below have **not**
been folded into `bar_unified.py` yet. Do not delete the folder until they are.

| Folder | Status |
|---|---|
| `eco-calculator-suite/` | ROI + distance/walk model folded in. Per-builder tick engine **not** folded (the JS simulator re-implements it). |
| `build-order-calc/` | `Environment` folded in. `build_with_priorities` / `calc_build_towards_object` / `compare_environments` **not** (the JS strategizer covers priority/towards). `bar_economy.md` moved up to `../bar_economy.md` — it is live reference, cited by the strategizer and `gex_research/.../eco_advisor.mjs`. |
| `wind-simulator/` | **Wind model folded in 2026-09-22** — `bar_unified.py` §3 now has the engine's real vector generator, validated against recorded games (`--wind-validate`). The e-stall search and optimal wind/solar/storage solver are **not** folded. |
| `build-time-calculator/` | Stale (2024). `find_optimal_winds` never salvaged. |
| `misc-calculators/` | Scratch. `yetanotherbarcalc.py`'s break-even never salvaged. |

## Two bugs that were fixed on the way in — do not copy them back

1. **`wind-simulator/vector.py` aliases its state.** `update_wind` does
   `self.new_wind_vec = self.old_wind_vec` and then mutates `.x` / `.y` in place,
   so rolling the new vector corrupts the old one and the 15-second interpolation
   starts from the wrong place. `bar_unified.Vec2` is frozen, so this cannot happen.
2. **`wind_income()` used to return `(min + max) / 2`.** That is not the mean of the
   engine's random walk. On All That Glitters (`[0, 16]`, read from the map file) the
   midpoint says 8.0 E/s against a measured ~11.9. `bar_unified.wind_income()` now
   returns the real expectation; `flat_wind_income()` keeps the midpoint for comparison.

## Also note

The repo root has `bar_analytics/`, an untracked near-copy of `eco-calculator-suite/`.
It is **not** a duplicate to bin. `map_spots.py` **was folded into `bar_unified.py` §4**
on 2026-09-22 (rewritten to pure stdlib, spot income calibrated), so that one is now
superseded. `map_classify.py` and `eco_planner.py` still exist only there.

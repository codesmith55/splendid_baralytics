"""
bar_unified.py — one unified BAR (Beyond All Reason) economy/build calculator
============================================================================

Merges the previously-scattered BAR calculators into a single module:

  source (subfolder)                 capability folded in here
  ---------------------------------  ----------------------------------------
  eco-calculator-suite/eco_calculator.py   EROI / TROI generator ROI
  eco-calculator-suite/bar_distance.py     grid → elmo → worker walk time
  eco-calculator-suite/eco_simulator.py    per-builder build-power + walk
  build-order-calc/bar_calc.py             Environment build-order sim, stalls,
                                           energy converters
  wind-simulator/wind_simulator.py         wind income model
  misc-calculators/yetanotherbarcalc.py    EconomyState time-stepping (subset)
  build-time-calculator/*.py               resource-wait build time (subset)
  bar_analytics/map_spots.py               map archive -> metal spots, geos, wind range
  (new) gex actions.json                   per-unit metal sources: mex / converter / reclaim

Every number comes from ONE place: `econ_model.json` (model choices) resolved
against the engine unit-def dumps it lists, through `econ_data.py`. The JS port
(splendid_buildSimulator.js) and the Legion state engine (positions/state_api.py)
read the same files; `parity.json` pins the resolved numbers and each side's
`--selftest` checks against it.

  python bar_unified.py                 demo build order
  python bar_unified.py --roi [--wind N] [--bp N]
  python bar_unified.py --objects       resolved object table
  python bar_unified.py --write-parity  regenerate parity.json (after a data change)
  python bar_unified.py --selftest      recompute and compare with parity.json
  python bar_unified.py --harvest-defs [--demo 8v8|latest|<demo>] [--engine E] [--full] [--no-parity]
                                        pull every unit/structure def from the engine (headless replay of
                                        the newest 8v8) -> units_<dateTime>.json, which becomes the default
  python bar_unified.py --wind [--game 1] [--min N --max N] [--until S] [--drought E]
                                        engine wind model: a real game's wind, or a map's distribution
  python bar_unified.py --list-paths | --paths [--paths a,b] [--wind N] [--until S]
                                        run each BUILD PATH separately, then table the breakpoints
  python bar_unified.py --ledger [N|id] [--until SEC] [--snap 60,120,300] [--only Mex,Solar]
                                        effective build order: every start and finish, with the
                                        measured state at each, plus snapshots you name
  python bar_unified.py --state [--game N] [--at SEC]
                                        from a real position: steps until unsustainable per option,
                                        and the rate that survives once the banks are gone
  python bar_unified.py --scaling Solar [--game N] [--at SEC]
                                        build power as the scaling dimension: what more of it buys
  python bar_unified.py --balance [--bp N] [--a Solar --b Wind] [--bank N --minc N]
                                        per wind speed: when does b's efficiency beat a's immediacy,
                                        and what income each pace needs to keep running
  python bar_unified.py --rates [--wind N]
                                        four-resource algebra: drain rates, sustainable BP, break-evens
  python bar_unified.py --wind-validate [--game 1]
                                        check the wind model against recorded games (key functionality test)
  python bar_unified.py --map "<name>" | --map --game 1   [--team N] [--spots N] [--refresh]
                                        read the map archive: mex spots, geos, wind range, start positions
  python bar_unified.py --metal-sources [<actions.json>] [--top N]
                                        split each team's metal into mex / converter / RECLAIM, per unit
"""

from __future__ import annotations

import glob
import json
import math
import os
import random
import re
import struct
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import econ_data as ED  # noqa: E402

_CFG = ED.config()
_C = _CFG["constants"]


# ════════════════════════════════════════════════════════════════════════════
# 1. CONSTANTS  (econ_model.json `constants` / `builderProfiles` / `gridCalibration`)
# ════════════════════════════════════════════════════════════════════════════

ENERGY_PER_METAL = _C["energyPerMetal"]        # T1 energy-converter exchange rate (eco_calculator)
DEFAULT_BUILDER_BP = _C["defaultBuilderBp"]    # T1 constructor / commander build power
DEFAULT_WIND = _C["defaultWind"]               # E/s per turbine when the map wind is unknown
GAME_FPS = _C["gameFps"]

# build range (elmos, config) + speed / build power (engine def)
UNIT_PROFILES = {
    k: {"build_range": p["buildRange"], "speed": p["speed"], "bp": p["bp"]}
    for k, p in ED.builder_profiles().items()
}

# Grid calibration: the commander's build-range circle is ~N start-grid squares (radius).
BUILD_RANGE_IN_GRID_SQUARES = _CFG["gridCalibration"]["buildRangeInGridSquares"]
ELMOS_PER_GRID_SQUARE = UNIT_PROFILES["commander"]["build_range"] / BUILD_RANGE_IN_GRID_SQUARES


# ════════════════════════════════════════════════════════════════════════════
# 2. DISTANCE / WORKER WALK TIME   (was bar_distance.py)
# ════════════════════════════════════════════════════════════════════════════

def resolve_unit(unit: str) -> str:
    u = (unit or "").strip().lower()
    if "commander" in u:
        return "commander"
    if "turret" in u or "nano" in u:
        return "con_turret"
    return "con_bot"


def squares_to_elmos(squares: float) -> float:
    return squares * ELMOS_PER_GRID_SQUARE


def elmos_to_squares(elmos: float) -> float:
    return elmos / ELMOS_PER_GRID_SQUARE


def can_reach(gap_elmos: float, unit: str = "commander") -> bool:
    """True if a target gap_elmos away is already within build range."""
    return gap_elmos <= UNIT_PROFILES[resolve_unit(unit)]["build_range"]


def walk_time(gap_elmos: float, unit: str = "con_bot",
              account_build_range: bool = True) -> float:
    """Seconds a builder walks before it can start a target gap_elmos away.

    A builder stops once the target is within build range, so the walked
    distance is max(0, gap - build_range). Static builders (speed 0) return 0
    if already in range, else +inf."""
    p = UNIT_PROFILES[resolve_unit(unit)]
    gap = max(0.0, gap_elmos - p["build_range"]) if account_build_range else gap_elmos
    if gap <= 0:
        return 0.0
    if p["speed"] <= 0:
        return float("inf")
    return gap / p["speed"]


def walk_time_squares(gap_squares: float, unit: str = "con_bot",
                      account_build_range: bool = True) -> float:
    return walk_time(squares_to_elmos(gap_squares), unit, account_build_range)


# ════════════════════════════════════════════════════════════════════════════
# 3. WIND   (was wind-simulator/wind_simulator.py — the ENGINE's own generator)
#
# Wind is a 2-D vector, not a scalar. Every WIND_UPDATE_FRAMES (450 = 15 s) the
# engine picks a NEW vector by ADDING a random delta to the current one, then
# clamping the new vector's LENGTH into the map's [min, max]. During the 15 s
# window the live vector slides from old to new by a smoothstep, and a turbine's
# output is the live vector's length — the distance of the tip from the origin.
# That is why the first moment of a window already tells you where the wind is
# going: the destination is fixed the instant the window opens (see `forecast`).
#
# Verified against recorded games (`python bar_unified.py --wind-validate`):
# reconstructing the in-between samples from the window's endpoints with a
# smoothstep matches the engine to ~0.1–0.35 E/s, and beats both a linear ramp
# and every other period/phase.
#
# IMPORTANT: a turbine's expected output is NOT (min + max) / 2. The random walk
# spends most of its time far from the origin, so the true mean sits well above
# the midpoint — on a [0, 16] map it is ~11.9 E/s, not 8. `wind_income()` returns
# the real expectation; `flat_wind_income()` keeps the old midpoint for reference.
# ════════════════════════════════════════════════════════════════════════════

WIND_UPDATE_FRAMES = 450          # engine: wind is re-rolled every 450 frames = 15 s
WIND_UPDATE_SEC = WIND_UPDATE_FRAMES / GAME_FPS


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(value, hi))


def smooth_step(edge1: float, edge2: float, value: float) -> float:
    """The engine's smoothstep: 3t² − 2t³ over [edge1, edge2]."""
    t = clamp((clamp(value, edge1, edge2) - edge1) / (edge2 - edge1), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


@dataclass(frozen=True)
class Vec2:
    """Immutable 2-D vector (the old wind_simulator's Vector aliased its state and
    corrupted `old` while building `new` — that bug does not exist here)."""
    x: float = 0.0
    z: float = 0.0

    def __add__(self, o: "Vec2") -> "Vec2":
        return Vec2(self.x + o.x, self.z + o.z)

    def __sub__(self, o: "Vec2") -> "Vec2":
        return Vec2(self.x - o.x, self.z - o.z)

    def __mul__(self, k: float) -> "Vec2":
        return Vec2(self.x * k, self.z * k)

    def length(self) -> float:
        return math.hypot(self.x, self.z)

    def normalized(self) -> "Vec2":
        n = self.length()
        return Vec2(self.x / n, self.z / n) if n > 1e-6 else Vec2(0.0, 0.0)

    def heading(self) -> float:
        """Compass-style bearing in degrees (0 = +x, counter-clockwise)."""
        return math.degrees(math.atan2(self.z, self.x)) % 360.0


def mix(a: Vec2, b: Vec2, t: float) -> Vec2:
    return a + (b - a) * t


class WindModel:
    """The engine's wind generator: random-walk a 2-D vector, clamp its length to
    [min_wind, max_wind], smoothstep between windows.

    A specific game's wind cannot be reproduced (the engine's RNG seed is not in
    the replay) — use `RecordedWind` for that. This class is for distributions:
    what a map's wind does on average, how long droughts last, how much a turbine
    is really worth."""

    def __init__(self, min_wind: float, max_wind: float, seed: Optional[int] = None,
                 start: Optional[Vec2] = None):
        self.min_wind = float(min_wind)
        self.max_wind = float(max_wind)
        self.rng = random.Random(seed)
        # engine's frame-0 state: (max/2, max/2)
        first = start if start is not None else Vec2(self.max_wind / 2, self.max_wind / 2)
        self._windows: List[Tuple[Vec2, Vec2]] = [(first, self._roll(first))]

    def _roll(self, base: Vec2) -> Vec2:
        """new = normalize(base + delta) * clamp(|base + delta|, min, max), delta
        components uniform in ±max/2 (engine subtracts (rand − 0.5) * max)."""
        while True:
            v = Vec2(base.x - (self.rng.random() - 0.5) * self.max_wind,
                     base.z - (self.rng.random() - 0.5) * self.max_wind)
            n = v.length()
            if n > 0.0:
                return v.normalized() * clamp(n, self.min_wind, self.max_wind)

    def _window(self, index: int) -> Tuple[Vec2, Vec2]:
        while len(self._windows) <= index:
            # the engine copies `curr` into `old` at the window boundary, and at
            # that instant curr is the previous window one frame from its end
            prev_old, prev_new = self._windows[-1]
            carried = self._vector_in(prev_old, prev_new, WIND_UPDATE_FRAMES - 1)
            self._windows.append((carried, self._roll(carried)))
        return self._windows[index]

    def _vector_in(self, old: Vec2, new: Vec2, timer: int) -> Vec2:
        v = mix(old, new, smooth_step(0.0, 1.0, timer / WIND_UPDATE_FRAMES))
        return v.normalized() * clamp(v.length(), self.min_wind, self.max_wind)

    def vector_at_frame(self, frame: int) -> Vec2:
        old, new = self._window(int(frame) // WIND_UPDATE_FRAMES)
        return self._vector_in(old, new, int(frame) % WIND_UPDATE_FRAMES)

    def at_frame(self, frame: int) -> float:
        """E/s a turbine makes at this frame."""
        return self.vector_at_frame(frame).length()

    def at(self, sec: float) -> float:
        return self.at_frame(int(round(sec * GAME_FPS)))

    def series(self, until_sec: float, every_sec: float = 1.0) -> List[Tuple[float, float]]:
        n = int(until_sec / every_sec) + 1
        return [(i * every_sec, self.at(i * every_sec)) for i in range(n)]

    def average(self, seconds: float = 900.0) -> float:
        s = self.series(seconds, WIND_UPDATE_SEC / 15)   # 1 s resolution
        return sum(v for _, v in s) / len(s)


# Monte-Carlo mean E/s per turbine by (min, max), from the original wind-simulator.
# Kept as a fast lookup and as a cross-check on `wind_income`.
WIND_AVG_TABLE: Dict[int, Dict[int, float]] = {
    0: {1: 0.8, 2: 1.5, 3: 2.2, 4: 3.0, 5: 3.7, 6: 4.5, 7: 5.2, 8: 6.0, 9: 6.7, 10: 7.5, 11: 8.2, 12: 9.0, 13: 9.7, 14: 10.4, 15: 11.2, 16: 11.9, 17: 12.7, 18: 13.4, 19: 14.2, 20: 14.9, 21: 15.7, 22: 16.4, 23: 17.2, 24: 17.9, 25: 18.6, 26: 19.2, 27: 19.6, 28: 20.0, 29: 20.4, 30: 20.7},
    1: {2: 1.6, 3: 2.3, 4: 3.0, 5: 3.8, 6: 4.5, 7: 5.2, 8: 6.0, 9: 6.7, 10: 7.5, 11: 8.2, 12: 9.0, 13: 9.7, 14: 10.4, 15: 11.2, 16: 11.9, 17: 12.7, 18: 13.4, 19: 14.2, 20: 14.9},
    2: {3: 2.6, 4: 3.2, 5: 3.9, 6: 4.6, 7: 5.3, 8: 6.0, 9: 6.8, 10: 7.5, 11: 8.2, 12: 9.0, 13: 9.7, 14: 10.5, 15: 11.2, 16: 12.0, 17: 12.7, 18: 13.4, 19: 14.2, 20: 14.9},
    3: {4: 3.6, 5: 4.2, 6: 4.8, 7: 5.5, 8: 6.2, 9: 6.9, 10: 7.6, 11: 8.3, 12: 9.0, 13: 9.8, 14: 10.5, 15: 11.2, 16: 12.0, 17: 12.7, 18: 13.5, 19: 14.2, 20: 15.0},
    4: {5: 4.6, 6: 5.2, 7: 5.8, 8: 6.4, 9: 7.1, 10: 7.8, 11: 8.5, 12: 9.2, 13: 9.9, 14: 10.6, 15: 11.3, 16: 12.1, 17: 12.8, 18: 13.5, 19: 14.3, 20: 15.0},
    5: {6: 5.5, 7: 6.1, 8: 6.8, 9: 7.4, 10: 8.0, 11: 8.7, 12: 9.4, 13: 10.1, 14: 10.8, 15: 11.5, 16: 12.2, 17: 12.9, 18: 13.6, 19: 14.4, 20: 15.1},
    6: {7: 6.5, 8: 7.1, 9: 7.7, 10: 8.4, 11: 9.0, 12: 9.7, 13: 10.3, 14: 11.0, 15: 11.7, 16: 12.4, 17: 13.1, 18: 13.8, 19: 14.5, 20: 15.2},
    7: {8: 7.5, 9: 8.1, 10: 8.7, 11: 9.3, 12: 10.0, 13: 10.6, 14: 11.3, 15: 11.9, 16: 12.6, 17: 13.3, 18: 14.0, 19: 14.7, 20: 15.4},
    8: {9: 8.5, 10: 9.1, 11: 9.7, 12: 10.3, 13: 11.0, 14: 11.6, 15: 12.2, 16: 12.9, 17: 13.6, 18: 14.2, 19: 14.9, 20: 15.6},
}


def wind_income(min_wind: float, max_wind: float, seconds: float = 3600.0,
                runs: int = 8, seed: int = 0) -> float:
    """Expected E/s of ONE turbine on a map with this wind range — the real mean of
    the engine's random walk, not the midpoint of the range. Uses the lookup table
    when the range is a known integer pair, else simulates."""
    lo, hi = int(round(min_wind)), int(round(max_wind))
    if abs(min_wind - lo) < 1e-9 and abs(max_wind - hi) < 1e-9 and lo in WIND_AVG_TABLE and hi in WIND_AVG_TABLE[lo]:
        return WIND_AVG_TABLE[lo][hi]
    tot = 0.0
    for r in range(runs):
        tot += WindModel(min_wind, max_wind, seed=seed + r).average(seconds)
    return tot / runs


def flat_wind_income(min_wind: float, max_wind: float) -> float:
    """The old (min + max) / 2 midpoint. Kept only for comparison — it understates
    a real map badly (on [0, 16] it says 8.0 against a measured ~11.9)."""
    return (min_wind + max_wind) / 2.0


# ──────────────────────────────────────────────────────────────────────────
# Wind as a replay actually recorded it
# ──────────────────────────────────────────────────────────────────────────

GAMES_DIR = os.path.join(ED.REPO_ROOT, "live", "games")


def resolve_live_jsonl(ref: str = "1") -> str:
    """A widget JSONL from live/games: '1' = newest, a substring, or a path.

    Distinct from `resolve_game`, which finds a .sdfz DEMO. Two different stores:
    the widget archives a live game as JSONL, the engine writes a demo."""
    if ref and os.path.exists(ref):
        return ref
    games = sorted(glob.glob(os.path.join(GAMES_DIR, "*.jsonl")), key=os.path.getmtime, reverse=True)
    if not games:
        raise FileNotFoundError(f"no archived games in {GAMES_DIR}")
    if str(ref).isdigit():
        return games[int(ref) - 1]
    hit = [g for g in games if str(ref) in os.path.basename(g)]
    if not hit:
        raise FileNotFoundError(f"no archived game matching {ref!r}")
    return hit[0]


class RecordedWind:
    """The wind of ONE real game, read from the widget's `wind_update` samples.

    The widget records the vector (windX, windZ) every few seconds; its length is
    the turbine output (verified to 2e-6). Because the engine's window is a fixed
    450 frames, the samples that land on window boundaries are the `old`/`new`
    vectors themselves, so `at()` reconstructs any instant exactly instead of
    interpolating blindly between samples."""

    def __init__(self, samples: Sequence[Tuple[int, Vec2]], source: str = "", map_name: str = ""):
        self.samples = sorted(samples)
        self.source = source
        self.map_name = map_name
        self.by_frame = {f: v for f, v in self.samples}

    @classmethod
    def from_game(cls, ref: str = "1") -> "RecordedWind":
        path = resolve_live_jsonl(ref)
        samples, map_name = [], ""
        with open(path, encoding="utf-8", errors="ignore") as f:
            for ln in f:
                if '"mapName"' in ln and not map_name:
                    try:
                        map_name = json.loads(ln).get("mapName", "") or ""
                    except ValueError:
                        pass
                if '"wind_update"' not in ln:
                    continue
                try:
                    e = json.loads(ln)
                except ValueError:
                    continue
                if e.get("action") != "wind_update":
                    continue
                if e.get("windX") is None:                    # older widget: scalar only
                    samples.append((int(e["frame"]), Vec2(float(e.get("value") or 0.0), 0.0)))
                else:
                    samples.append((int(e["frame"]), Vec2(float(e["windX"]), float(e["windZ"]))))
        if not samples:
            raise ValueError(f"no wind_update samples in {os.path.basename(path)}")
        return cls(samples, source=os.path.basename(path), map_name=map_name)

    # ---- the map's range, as the game itself revealed it ----
    def observed_range(self) -> Tuple[float, float]:
        vals = [v.length() for f, v in self.samples if f > 0]
        return (min(vals), max(vals)) if vals else (0.0, 0.0)

    def _clamped_at(self, value: float, tol: float = 0.002) -> int:
        """How many samples sit exactly on `value` — the signature of the engine
        clamping the vector's length against a map limit."""
        return sum(1 for f, v in self.samples if f > 0 and abs(v.length() - value) <= tol)

    def map_range(self) -> Tuple[float, float]:
        """The map's [min, max] as far as the recording can show it.

        The MAX is trustworthy: the walk keeps pushing past it and gets clamped, so
        the same value repeats exactly. The MIN usually is not — the walk rarely
        reaches the floor, so the lowest sample is only an upper bound on it, and
        `min_known` says which case this is. Prefer `average()` (what the turbine
        actually earned) over any range-derived table for a game you have."""
        lo, hi = self.observed_range()
        hi_r = round(hi, 2)
        lo_r = round(lo, 2) if self._clamped_at(lo) >= 3 else 0.0
        return (lo_r, hi_r)

    def min_known(self) -> bool:
        lo, _ = self.observed_range()
        return self._clamped_at(lo) >= 3

    # ---- wind at any instant ----
    def vector_at_frame(self, frame: float) -> Vec2:
        frame = max(0.0, float(frame))
        w = int(frame // WIND_UPDATE_FRAMES)
        a, b = w * WIND_UPDATE_FRAMES, (w + 1) * WIND_UPDATE_FRAMES
        if a in self.by_frame and b in self.by_frame:
            return mix(self.by_frame[a], self.by_frame[b],
                       smooth_step(0.0, 1.0, (frame - a) / WIND_UPDATE_FRAMES))
        # outside the recorded window boundaries: fall back to the nearest samples
        before = [s for s in self.samples if s[0] <= frame]
        after = [s for s in self.samples if s[0] >= frame]
        if not before:
            return after[0][1]
        if not after:
            return before[-1][1]
        (f0, v0), (f1, v1) = before[-1], after[0]
        return v0 if f1 == f0 else mix(v0, v1, (frame - f0) / (f1 - f0))

    def at(self, sec: float) -> float:
        return self.vector_at_frame(sec * GAME_FPS).length()

    def series(self, until_sec: float = 900.0, every_sec: float = 1.0) -> List[Tuple[float, float]]:
        n = int(until_sec / every_sec) + 1
        return [(i * every_sec, self.at(i * every_sec)) for i in range(n)]

    def average(self, start_sec: float = 0.0, end_sec: Optional[float] = None,
                every_sec: float = 1.0) -> float:
        """Mean E/s per turbine over a window — the number a turbine built at
        `start_sec` actually earned, as opposed to any table's expectation."""
        end_sec = self.duration_sec() if end_sec is None else end_sec
        if end_sec <= start_sec:
            return self.at(start_sec)
        n = max(1, int((end_sec - start_sec) / every_sec))
        return sum(self.at(start_sec + i * every_sec) for i in range(n)) / n

    def energy_between(self, start_sec: float, end_sec: float, turbines: float = 1.0) -> float:
        """Total energy ONE (or N) turbines produce over a window — the integral,
        which is what actually matters for a build comparison."""
        return self.average(start_sec, end_sec) * max(0.0, end_sec - start_sec) * turbines

    def duration_sec(self) -> float:
        return self.samples[-1][0] / GAME_FPS if self.samples else 0.0

    # ---- what a watchful player can see ----
    def forecast(self, sec: float) -> dict:
        """The window in progress at `sec`: where the wind is heading and when it
        arrives. The destination is fixed the moment the window opens, so the
        early drift of the vector already gives the window away."""
        frame = sec * GAME_FPS
        w = int(frame // WIND_UPDATE_FRAMES)
        a, b = w * WIND_UPDATE_FRAMES, (w + 1) * WIND_UPDATE_FRAMES
        v_now, v_end = self.vector_at_frame(frame), self.vector_at_frame(b)
        v_start = self.vector_at_frame(a)
        return {
            "sec": sec,
            "window_start_sec": a / GAME_FPS, "window_end_sec": b / GAME_FPS,
            "seconds_left": (b - frame) / GAME_FPS,
            "now": v_now.length(), "window_start": v_start.length(), "target": v_end.length(),
            "delta": v_end.length() - v_now.length(),
            "heading_now": v_now.heading(), "heading_target": v_end.heading(),
            "rising": v_end.length() > v_now.length(),
        }

    def droughts(self, threshold: float, until_sec: Optional[float] = None,
                 every_sec: float = 1.0) -> List[Tuple[float, float]]:
        """[(start, end)] spans where a turbine makes less than `threshold` E/s —
        the risk a wind opening carries and a solar opening does not."""
        end = self.duration_sec() if until_sec is None else until_sec
        out, run = [], None
        t = 0.0
        while t <= end:
            if self.at(t) < threshold:
                run = t if run is None else run
            elif run is not None:
                out.append((run, t)); run = None
            t += every_sec
        if run is not None:
            out.append((run, end))
        return out


def validate_wind_model(refs: Iterable[str] = ("1", "2", "3"), verbose: bool = True) -> dict:
    """KEY FUNCTIONALITY TEST — does the engine model above actually reproduce the
    wind a real game recorded?

    For every sample that is NOT on a window boundary, rebuild it from the two
    surrounding boundary samples with the smoothstep, and compare. Also scores a
    linear ramp and the wrong periods, so a regression shows up as the wrong shape
    winning rather than as a silently worse fit."""
    games, rows = [], []
    for ref in refs:
        try:
            games.append(RecordedWind.from_game(ref))
        except Exception as e:                                    # noqa: BLE001
            if verbose:
                print(f"  (skipped {ref}: {e})")
    if not games:
        raise FileNotFoundError("no recorded games with wind samples")

    def score(rw: RecordedWind, period: int, shape: str) -> Tuple[float, int]:
        errs = []
        for f, v in rw.samples:
            if f < period or f % period == 0:
                continue
            a, b = (f // period) * period, (f // period + 1) * period
            if a not in rw.by_frame or b not in rw.by_frame:
                continue
            t = (f - a) / period
            m = smooth_step(0.0, 1.0, t) if shape == "smoothstep" else t
            errs.append(abs(mix(rw.by_frame[a], rw.by_frame[b], m).length() - v.length()))
        return (sum(errs) / len(errs), len(errs)) if errs else (float("inf"), 0)

    MIN_SAMPLES = 20        # below this a game cannot distinguish the candidate shapes
    out = {"games": [], "ok": True, "scored": 0}
    for rw in games:
        lo, hi = rw.map_range()
        err, n = score(rw, WIND_UPDATE_FRAMES, "smoothstep")
        lin, _ = score(rw, WIND_UPDATE_FRAMES, "linear")
        measured = rw.average(0, min(900.0, rw.duration_sec()))
        g = {"game": rw.source, "map": rw.map_name, "samples": len(rw.samples), "compared": n,
             "observed_range": rw.observed_range(), "map_range": (lo, hi), "min_known": rw.min_known(),
             "err_smoothstep": err, "err_linear": lin,
             "measured_avg_15min": measured, "table_avg": wind_income(lo, hi),
             "flat_midpoint": flat_wind_income(lo, hi)}
        if n < MIN_SAMPLES:
            g["ok"] = None                      # too short to judge — neither pass nor fail
            g["best_period"], g["best_shape"] = None, None
        else:
            cand = [(score(rw, p, s)[0], p, s) for p in (300, 450, 600, 900)
                    for s in ("smoothstep", "linear") if score(rw, p, s)[1] >= MIN_SAMPLES]
            best = min(cand)
            g["best_period"], g["best_shape"] = best[1], best[2]
            g["ok"] = (best[1] == WIND_UPDATE_FRAMES and best[2] == "smoothstep" and err < 0.5)
            out["ok"] = out["ok"] and g["ok"]
            out["scored"] += 1
        out["games"].append(g)
        if verbose:
            tag = "--" if g["ok"] is None else ("OK " if g["ok"] else "BAD")
            print(f"  {tag} {rw.source}  {rw.map_name}")
            lo_s = f"{lo:g}" if g["min_known"] else f"≤{rw.observed_range()[0]:.2f}, assumed 0"
            print(f"      wind {rw.observed_range()[0]:.2f}–{rw.observed_range()[1]:.2f} E/s"
                  f"  → map max {hi:g} (clamped {rw._clamped_at(rw.observed_range()[1])}×), min {lo_s}")
            if g["ok"] is None:
                print(f"      too short to score the model ({n} in-window samples, need {MIN_SAMPLES})")
            else:
                print(f"      smoothstep@450 err {err:.3f} E/s over {n} samples   (linear@450 {lin:.3f};"
                      f" best of all periods/shapes: {g['best_period']} {g['best_shape']})")
            print(f"      turbine average, first 15 min: measured {measured:.2f} E/s"
                  f"   table {g['table_avg']:.2f}   (min+max)/2 says {g['flat_midpoint']:.2f}")
    if not out["scored"]:
        out["ok"] = False
        if verbose:
            print("\nno game long enough to score the wind model")
    elif verbose:
        print(f"\nwind model OK ({out['scored']} games scored)" if out["ok"] else "\nwind model FAILED")
    return out


# ════════════════════════════════════════════════════════════════════════════
# 4. MAP   (was bar_analytics/map_spots.py — the map file itself, no game needed)
#
# A BAR map archive carries the facts a replay only implies: where every metal
# spot is, where the geovents are, the team start positions, the world size, the
# extractor radius, maxMetal, and the map's REAL wind range. That wind range is
# what §3 needs — a recording only ever shows the max (the walk clamps against
# it), never the floor, so `RecordedWind` asks the map first and falls back to
# inference only when the archive is missing.
#
# Everything here is stdlib. Parsing the SMF (metal map + feature list) and the
# connected-component spot detection are pure Python, so the original numpy and
# scipy dependencies are gone. Only cracking open a NEW .sd7 needs `py7zr`, and
# results are cached to bar-calc/map_data/, so the common path needs nothing.
#
# Positions are exact. Per-spot metal/s is an ESTIMATE (`max_metal * metal_sum
# / 255`); `metal_sum` is the authoritative RELATIVE richness until calibrated
# against a replay with a mex on each spot.
# ════════════════════════════════════════════════════════════════════════════

DEFAULT_MAPS_DIR = os.environ.get(
    "BAR_MAPS", r"C:\Users\codes\AppData\Local\Programs\Beyond-All-Reason\data\maps")
MAP_CACHE_DIR = os.path.join(HERE, "map_data")
SMF_HEADER_FMT = "<iiiiiiiffiiiiiii"      # 16 fields, 64 bytes, after the 16-byte magic


@dataclass
class MexSpot:
    id: int
    x: float
    z: float
    metal_sum: int           # summed metal-map bytes — authoritative RELATIVE richness
    metal_per_s_est: float   # max_metal * metal_sum / 255 — calibrate against a replay
    size_cells: int

    def distance_to(self, x: float, z: float) -> float:
        return math.hypot(self.x - x, self.z - z)

    def metal_per_s(self, reference_sum: float, spot_rate: float = None) -> float:
        """Calibrated income of a x1.0 extractor on this spot.

        `metal_per_s_est` is the raw maxMetal scaling and is NOT in m/s — on All
        That Glitters it reads 7.2 for a spot a T1 mex actually earns 1.825 on.
        `metal_sum` IS trustworthy as relative richness, so scale it against the
        map's standard spot and the measured standard-spot rate (econ_model.json
        `metalSpot`, the same constant the Legion model uses)."""
        rate = _C["metalSpot"] if spot_rate is None else spot_rate
        return round(rate * self.metal_sum / reference_sum, 4) if reference_sum else 0.0


@dataclass
class MapInfo:
    """One BAR map, read from its archive. `wind_min` / `wind_max` are the engine's
    own limits — feed them to WindModel / wind_income rather than guessing."""
    name: str = "?"
    shortname: str = "?"
    version: str = "?"
    author: str = "?"
    source_archive: str = ""
    world_width: int = 0
    world_height: int = 0
    max_metal: float = 1.0
    extractor_radius: float = 50.0
    wind_min: float = 0.0
    wind_max: float = 0.0
    start_positions: List[dict] = field(default_factory=list)
    geo_spots: List[dict] = field(default_factory=list)
    mex_spots: List[MexSpot] = field(default_factory=list)
    features: List[dict] = field(default_factory=list)   # every map feature: rocks, trees, geos

    # ---- the numbers the economy model wants ----
    @property
    def wind_range(self) -> Tuple[float, float]:
        return (self.wind_min, self.wind_max)

    def expected_wind(self) -> float:
        """E/s a turbine averages on this map (the engine's real distribution)."""
        return wind_income(self.wind_min, self.wind_max)

    def standard_spot_sum(self) -> float:
        """The `metal_sum` of this map's typical spot (median) — the reference a
        x1.0 extractor makes `metalSpot` m/s on."""
        if not self.mex_spots:
            return 0.0
        sums = sorted(s.metal_sum for s in self.mex_spots)
        return float(sums[len(sums) // 2])

    def spot_metal_per_s(self, spot: MexSpot) -> float:
        """Calibrated m/s for one spot (see MexSpot.metal_per_s)."""
        return spot.metal_per_s(self.standard_spot_sum())

    def total_metal_per_s(self) -> float:
        """Calibrated m/s if every spot were held by a x1.0 extractor."""
        ref = self.standard_spot_sum()
        return round(sum(s.metal_per_s(ref) for s in self.mex_spots), 3)

    def total_metal_per_s_raw(self) -> float:
        """The uncalibrated maxMetal scaling — kept only for comparison."""
        return round(sum(s.metal_per_s_est for s in self.mex_spots), 3)

    # ---- map-supplied reclaim (rocks), as opposed to wrecks made during a game ----
    def feature_counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for f in self.features:
            out[f["type"]] = out.get(f["type"], 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def rocks(self, pattern: str = r"rock|boulder|stone|metal|crystal|debris|slab") -> List[dict]:
        """Map features that plausibly hold METAL reclaim, as opposed to trees.

        MEASURED CAVEAT (2026-09-22): on every current BAR map checked — All That
        Glitters, Comet Catcher, Supreme Isthmus, Quicksilver, Throne, Tangerine,
        Isidis — the SMF feature section carries ONLY geovents, 0 to 8 of them, and
        no rocks. Modern maps place rocks outside the SMF, so this returns empty
        there and is NOT a rock inventory you can rely on. Track map reclaim from
        the game instead: the widget sees every FeatureDestroyed, including the
        non-wreck features gex.lua currently filters out."""
        rx = re.compile(pattern, re.I)
        return [f for f in self.features if rx.search(f["type"])]

    def rocks_near(self, x: float, z: float, radius: float = 1000.0) -> List[dict]:
        """Map reclaim within `radius` of a point. Subject to the `rocks()` caveat:
        empty on current maps, because the SMF holds no rocks."""
        out = []
        for f in self.rocks():
            d = math.hypot(f["x"] - x, f["z"] - z)
            if d <= radius:
                out.append({**f, "distance": round(d, 1)})
        out.sort(key=lambda r: r["distance"])
        return out

    # ---- spots relative to a position: the walk analysis ----
    def spots_from(self, x: float, z: float, unit: str = "commander",
                   limit: Optional[int] = None) -> List[dict]:
        """Every mex spot ordered by distance from (x, z), with the walk time to
        reach build range (§2). This is the "which mexes can I actually take, and
        what does the 6th and 7th cost me in walking" view."""
        rows, ref = [], self.standard_spot_sum()
        for s in self.mex_spots:
            gap = s.distance_to(x, z)
            rows.append({"spot": s, "id": s.id, "x": s.x, "z": s.z,
                         "distance": round(gap, 1),
                         "walk_sec": round(walk_time(gap, unit), 1),
                         "in_range": can_reach(gap, unit),
                         "metal_per_s": s.metal_per_s(ref),
                         "metal_per_s_est": s.metal_per_s_est})
        rows.sort(key=lambda r: r["distance"])
        return rows[:limit] if limit else rows

    def start_position(self, team: int) -> Optional[Tuple[float, float]]:
        for p in self.start_positions:
            if int(p.get("team", -1)) == int(team):
                return (float(p["x"]), float(p["z"]))
        return None

    def spots_for_team(self, team: int, unit: str = "commander",
                       limit: Optional[int] = None) -> List[dict]:
        pos = self.start_position(team)
        if pos is None:
            raise KeyError(f"map {self.shortname} has no start position for team {team}")
        return self.spots_from(pos[0], pos[1], unit, limit)

    # ---- serialisation (the cache format, same schema map_spots.py wrote) ----
    def to_dict(self) -> dict:
        return {
            "map": self.name, "shortname": self.shortname, "version": self.version,
            "author": self.author, "source_archive": self.source_archive,
            "world_width": self.world_width, "world_height": self.world_height,
            "max_metal": self.max_metal, "extractor_radius": self.extractor_radius,
            "wind": {"min": self.wind_min, "max": self.wind_max},
            "counts": {"mex_spots": len(self.mex_spots), "geo_spots": len(self.geo_spots),
                       "start_positions": len(self.start_positions)},
            "total_metal_per_s": self.total_metal_per_s(),
            "standard_spot_sum": self.standard_spot_sum(),
            "total_metal_per_s_est": self.total_metal_per_s_raw(),
            "calibration_note": ("mex positions are exact. metal_per_s_est = max_metal * "
                                 "metal_sum / 255 is the RAW scaling and is not m/s. Use "
                                 "metal_per_s, which scales metal_sum (authoritative relative "
                                 "richness) against this map's standard spot and the measured "
                                 "standard-spot rate econ_model.json `metalSpot`."),
            "start_positions": self.start_positions,
            "geo_spots": self.geo_spots,
            "features": self.features,
            "feature_counts": self.feature_counts(),
            "mex_spots": [vars(s) for s in self.mex_spots],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MapInfo":
        w = d.get("wind") or {}
        return cls(
            name=d.get("map", "?"), shortname=d.get("shortname", "?"),
            version=d.get("version", "?"), author=d.get("author", "?"),
            source_archive=d.get("source_archive", ""),
            world_width=int(d.get("world_width") or 0),
            world_height=int(d.get("world_height") or 0),
            max_metal=float(d.get("max_metal") or 1.0),
            extractor_radius=float(d.get("extractor_radius") or 50.0),
            wind_min=float(w.get("min") or 0.0), wind_max=float(w.get("max") or 0.0),
            start_positions=d.get("start_positions") or [],
            geo_spots=d.get("geo_spots") or [],
            features=d.get("features") or [],
            mex_spots=[MexSpot(**s) for s in (d.get("mex_spots") or [])],
        )


# ──────────────────────────────────────────────────────────────────────────
# archive access (.sd7 = 7-zip, .sdz = zip)
# ──────────────────────────────────────────────────────────────────────────

def _extract_members(archive: str, members: Sequence[str], dest: str) -> Dict[str, str]:
    """Extract named members (case-insensitively) into `dest`; return member→path."""
    os.makedirs(dest, exist_ok=True)
    ext = os.path.splitext(archive)[1].lower()
    if ext == ".sdz":
        import zipfile
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            picked = [n for n in names if any(n.lower() == m.lower()
                                              or n.lower().endswith("/" + m.lower()) for m in members)]
            for n in picked:
                z.extract(n, dest)
    else:
        try:
            import py7zr
        except ImportError as e:                                       # pragma: no cover
            raise RuntimeError(
                f"reading {os.path.basename(archive)} needs py7zr (pip install py7zr). "
                f"Cached maps in {MAP_CACHE_DIR} need nothing.") from e
        with py7zr.SevenZipFile(archive, "r") as z:
            names = z.getnames()
            picked = [n for n in names if any(n.lower() == m.lower()
                                              or n.lower().endswith("/" + m.lower()) for m in members)]
            if picked:
                z.extract(path=dest, targets=picked)
    found: Dict[str, str] = {}
    for m in members:
        hits = glob.glob(os.path.join(dest, "**", os.path.basename(m)), recursive=True)
        if hits:
            found[m] = hits[0]
    return found


def _archive_names(archive: str) -> List[str]:
    if os.path.splitext(archive)[1].lower() == ".sdz":
        import zipfile
        with zipfile.ZipFile(archive) as z:
            return z.namelist()
    import py7zr
    with py7zr.SevenZipFile(archive, "r") as z:
        return z.getnames()


def _parse_mapinfo(path: str) -> dict:
    """mapinfo.lua scalars by regex — no Lua interpreter needed."""
    txt = open(path, encoding="utf-8", errors="replace").read()

    def num(key: str, default: Optional[float] = None) -> Optional[float]:
        m = re.search(key + r"\s*=\s*(-?[0-9.]+)", txt)
        return float(m.group(1)) if m else default

    def s(key: str) -> Optional[str]:
        m = re.search(key + r'\s*=\s*["\']([^"\']+)["\']', txt)
        return m.group(1) if m else None

    starts: List[dict] = []
    tblk = re.search(r"teams\s*=\s*\{(.*?)\n\t\},", txt, re.S)
    if tblk:
        for tm in re.finditer(
                r"\[(\d+)\]\s*=\s*\{startPos\s*=\s*\{x\s*=\s*(-?[0-9.]+)\s*,\s*z\s*=\s*(-?[0-9.]+)",
                tblk.group(1)):
            starts.append({"team": int(tm.group(1)),
                           "x": float(tm.group(2)), "z": float(tm.group(3))})
    return {"name": s("name") or "?", "shortname": s("shortname") or "?",
            "version": s("version") or "?", "author": s("author") or "?",
            "max_metal": num("maxMetal", 1.0), "extractor_radius": num("extractorRadius", 50.0),
            "min_wind": num("minWind", 0.0), "max_wind": num("maxWind", 0.0),
            "start_positions": starts}


def _read_smf(smf_path: str) -> dict:
    """Spring Map Format: the metal map (1 byte per 16×16-elmo cell) and the
    feature list (geovents carry world coordinates)."""
    with open(smf_path, "rb") as f:
        if not f.read(16).startswith(b"spring map file"):
            raise ValueError(f"not an SMF file: {smf_path}")
        (version, mapid, mapx, mapy, square, texel, tilesize, min_h, max_h,
         height_ptr, type_ptr, tiles_ptr, minimap_ptr, metal_ptr, feature_ptr,
         num_extra) = struct.unpack(SMF_HEADER_FMT, f.read(64))

        mm_w, mm_h = mapx // 2, mapy // 2
        f.seek(metal_ptr)
        metal = f.read(mm_w * mm_h)

        # Every feature the map ships with: geovents, rocks, trees. Rocks matter —
        # they are the map-supplied reclaim a Lazarus or con eats before any wreck
        # exists. Wrecks are NOT here; they are created during the game.
        geos: List[dict] = []
        features: List[dict] = []
        f.seek(feature_ptr)
        n_types, n_feats = struct.unpack("<ii", f.read(8))
        types: List[str] = []
        for _ in range(n_types):
            buf = bytearray()
            while True:
                c = f.read(1)
                if c in (b"\x00", b""):
                    break
                buf += c
            types.append(buf.decode("utf-8", "replace"))
        for _ in range(n_feats):
            ti, x, y, z, rot, rs = struct.unpack("<ifffff", f.read(24))
            tname = types[ti] if 0 <= ti < len(types) else "?"
            features.append({"type": tname, "x": round(x, 1), "z": round(z, 1)})
            if "geo" in tname.lower():
                geos.append({"x": round(x, 1), "z": round(z, 1)})

    return {"mapx": mapx, "mapy": mapy, "square": square, "metal": metal,
            "mm_w": mm_w, "mm_h": mm_h, "cell_size": square * 2,
            "world_width": mapx * square, "world_height": mapy * square,
            "geos": geos, "features": features, "feature_types": types}


def _find_spots(metal: bytes, w: int, h: int, cell: int, max_metal: float,
                min_est: float = 0.25) -> List[MexSpot]:
    """One spot per connected non-zero metal blob (4-connectivity), positioned at
    the metal-weighted centroid. Pure stdlib flood fill — scipy.ndimage.label and
    center_of_mass in the original did exactly this."""
    seen = bytearray(w * h)
    blobs: List[MexSpot] = []
    for start in range(w * h):
        if not metal[start] or seen[start]:
            continue
        seen[start] = 1
        stack, cells = [start], []
        while stack:
            j = stack.pop()
            cells.append(j)
            jx, jy = j % w, j // w
            if jx > 0 and metal[j - 1] and not seen[j - 1]:
                seen[j - 1] = 1; stack.append(j - 1)
            if jx < w - 1 and metal[j + 1] and not seen[j + 1]:
                seen[j + 1] = 1; stack.append(j + 1)
            if jy > 0 and metal[j - w] and not seen[j - w]:
                seen[j - w] = 1; stack.append(j - w)
            if jy < h - 1 and metal[j + w] and not seen[j + w]:
                seen[j + w] = 1; stack.append(j + w)
        total = sum(metal[j] for j in cells)
        if not total:
            continue
        est = max_metal * total / 255.0
        if est < min_est:
            continue
        cx = sum((j % w + 0.5) * metal[j] for j in cells) / total
        cz = sum((j // w + 0.5) * metal[j] for j in cells) / total
        blobs.append(MexSpot(id=0, x=round(cx * cell, 1), z=round(cz * cell, 1),
                             metal_sum=int(total), metal_per_s_est=round(est, 3),
                             size_cells=len(cells)))
    blobs.sort(key=lambda s: (s.z, s.x))          # stable: top-to-bottom, left-to-right
    for i, s in enumerate(blobs):
        s.id = i
    return blobs


# ──────────────────────────────────────────────────────────────────────────
# public API
# ──────────────────────────────────────────────────────────────────────────

def find_map_archive(query: str, maps_dir: Optional[str] = None) -> str:
    """Fuzzy-match a map name to an archive in the BAR maps dir (newest version
    wins). A replay's `mapName` ("All That Glitters v2.2.3") resolves directly."""
    if os.path.isfile(query):
        return query
    maps_dir = maps_dir or DEFAULT_MAPS_DIR
    if not os.path.isdir(maps_dir):
        raise FileNotFoundError(f"BAR maps dir not found: {maps_dir} (set $BAR_MAPS)")
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())                     # noqa: E731
    key = norm(query)
    archives = [p for p in glob.glob(os.path.join(maps_dir, "*.sd7"))
                + glob.glob(os.path.join(maps_dir, "*.sdz"))]
    cands = [p for p in archives if key in norm(os.path.basename(p))]
    if not cands:
        # a replay's mapName carries the version ("Foo v2.2.3"); retry on the stem
        stem = norm(re.sub(r"\s*v?[\d.]+\s*$", "", query))
        cands = [p for p in archives if stem and stem in norm(os.path.basename(p))]
    if not cands:
        raise FileNotFoundError(f"no map archive matching {query!r} in {maps_dir}")
    cands.sort()
    return cands[-1]


def _cache_path(archive: str) -> str:
    key = re.sub(r"[^\w.-]", "_", os.path.splitext(os.path.basename(archive))[0])
    return os.path.join(MAP_CACHE_DIR, key + ".json")


def read_map(query: str, maps_dir: Optional[str] = None, cache: bool = True,
             refresh: bool = False) -> MapInfo:
    """Read a BAR map by name, or by path to its archive or a cached JSON.

    Cached to bar-calc/map_data/<archive>.json, keyed by the archive file so map
    versions never collide (versions differ in spots, geos and wind)."""
    if query.lower().endswith(".json") and os.path.isfile(query):
        with open(query, encoding="utf-8") as f:
            return MapInfo.from_dict(json.load(f))
    archive = find_map_archive(query, maps_dir)
    cpath = _cache_path(archive)
    if cache and not refresh and os.path.isfile(cpath):
        with open(cpath, encoding="utf-8") as f:
            return MapInfo.from_dict(json.load(f))

    scratch = os.path.join(os.environ.get("TEMP", "."), "bar_map_spots",
                           os.path.basename(archive))
    got = _extract_members(archive, ["mapinfo.lua"], scratch)
    info = _parse_mapinfo(got["mapinfo.lua"]) if "mapinfo.lua" in got else {}
    smf_member = None
    if "mapinfo.lua" in got:
        txt = open(got["mapinfo.lua"], encoding="utf-8", errors="replace").read()
        m = re.search(r'mapfile\s*=\s*["\']([^"\']+\.smf)["\']', txt, re.I)
        smf_member = m.group(1) if m else None
    if not smf_member:
        smfs = [n for n in _archive_names(archive) if n.lower().endswith(".smf")]
        if not smfs:
            raise FileNotFoundError(f"no .smf inside {archive}")
        smf_member = smfs[0]
    got = _extract_members(archive, [smf_member], scratch)
    if smf_member not in got:
        raise FileNotFoundError(f"could not extract {smf_member} from {archive}")
    smf = _read_smf(got[smf_member])

    mi = MapInfo(
        name=info.get("name", "?"), shortname=info.get("shortname", "?"),
        version=info.get("version", "?"), author=info.get("author", "?"),
        source_archive=os.path.basename(archive),
        world_width=smf["world_width"], world_height=smf["world_height"],
        max_metal=info.get("max_metal", 1.0) or 1.0,
        extractor_radius=info.get("extractor_radius", 50.0) or 50.0,
        wind_min=info.get("min_wind", 0.0) or 0.0,
        wind_max=info.get("max_wind", 0.0) or 0.0,
        start_positions=info.get("start_positions", []), geo_spots=smf["geos"],
        features=smf["features"],
        mex_spots=_find_spots(smf["metal"], smf["mm_w"], smf["mm_h"],
                              smf["cell_size"], info.get("max_metal", 1.0) or 1.0),
    )
    if cache:
        os.makedirs(MAP_CACHE_DIR, exist_ok=True)
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(mi.to_dict(), f, indent=1)
    return mi


def map_for_game(ref: str = "1", **kw) -> MapInfo:
    """The map a recorded game was played on (reads its `mapName`)."""
    path = resolve_live_jsonl(ref)
    with open(path, encoding="utf-8", errors="ignore") as f:
        for ln in f:
            if '"mapName"' in ln:
                try:
                    name = json.loads(ln).get("mapName")
                except ValueError:
                    continue
                if name:
                    return read_map(name, **kw)
    raise ValueError(f"no mapName in {os.path.basename(path)}")


# ══════════════════════════════════════════════════════════════════════════
# THE MEX BUDGET — the frame every other answer sits inside
#
# A position can only ever hold so many extractors: tech 7, front 12
# (econ_model.json `positions.mexBudget`). That number is the metal CEILING, the
# ceiling sets the phases, and the phases decide which advice is even valid.
#
# A budget is not a count. It is an ordered list of real spots, each with its own
# richness and its own walk time, which `MapInfo.spots_from` already returns. On
# All That Glitters 146 of 152 spots pay 1.825 m/s and six pay 3.16, so
# `count * 1.825` is wrong wherever a rich spot is in reach — and right by accident
# everywhere else, which is worse.
#
# `room` is what matters most. METAL BOUND is the goal only while room remains: it
# then means "build another extractor". With room 0 it means CAPPED, and the answer
# becomes an advanced extractor, reclaim, or a converter. Same regime, opposite
# advice. Nothing may print "add an extractor" when there is none left to add.
# ══════════════════════════════════════════════════════════════════════════

POSITION_MEX: Dict[str, int] = dict(
    (_CFG.get("positions") or {}).get("mexBudget") or {"tech": 7, "front": 12})


def mex_budget(map_query: str = "All That Glitters", team: int = 0,
               count: Optional[int] = None, position: Optional[str] = None,
               standing: int = 0, unit: str = "con_bot", extractor: str = "Mex",
               net: bool = True, verbose: bool = False) -> dict:
    """The ordered spots this position can claim, with each one's own rate and walk.

    `net` prices the extractor's own energy flow as metal at the T1 rate, so
    `m_per_s_*` is what the spot is actually worth (see `effective_metal_rate`).
    The raw figures are kept alongside as `*_raw`, because the exchange is only
    real once surplus energy converts."""
    if count is None:
        key = position or (_CFG.get("positions") or {}).get("default") or "tech"
        count = POSITION_MEX.get(key, 7)
    mp = read_map(map_query)
    pos = mp.start_position(team)
    if pos is None:
        raise KeyError(mp.shortname + " has no start position for team " + str(team))
    rows = mp.spots_from(pos[0], pos[1], unit, count)
    spots = [{"n": i + 1, "id": r["id"], "x": r["x"], "z": r["z"],
              "distance": r["distance"], "walk_sec": r["walk_sec"],
              "metal_per_s": r["metal_per_s"]} for i, r in enumerate(rows)]
    standing = max(0, min(standing, len(spots)))
    # an extractor's energy flow is part of its metal rate: upkeep is a flat per-
    # BUILDING charge, so it is subtracted once per spot, not scaled by richness
    eff = effective_metal_rate(extractor)
    for sp in spots:
        sp["metal_per_s_raw"] = sp["metal_per_s"]
        sp["metal_per_s_net"] = round(sp["metal_per_s"] + eff["energy_as_metal"], 6)
        if net:
            sp["metal_per_s"] = sp["metal_per_s_net"]
    cur = sum(sp["metal_per_s"] for sp in spots[:standing])
    proj = sum(sp["metal_per_s"] for sp in spots)
    cur_raw = sum(sp["metal_per_s_raw"] for sp in spots[:standing])
    proj_raw = sum(sp["metal_per_s_raw"] for sp in spots)
    std = _C["metalSpot"]
    out = {"map": mp.shortname, "team": team, "position": position,
           "spawn": [pos[0], pos[1]], "walk_unit": unit,
           "extractor": extractor, "net": bool(net), "effective": eff,
           "m_per_s_current_raw": round(cur_raw, 4),
           "m_per_s_projected_raw": round(proj_raw, 4),
           "energy_flow_total": round(eff["energy_flow"] * len(spots), 2),
           "count": len(spots), "standing": standing, "room": len(spots) - standing,
           "spots": spots, "m_per_s_current": round(cur, 4),
           "m_per_s_projected": round(proj, 4),
           "m_per_s_remaining": round(proj - cur, 4),
           # from-spawn walks summed is NOT a route; kept only as the raw figure
           "walk_sum_from_spawn_sec": round(sum(sp["walk_sec"] for sp in spots), 1),
           "rich_spots": [sp["n"] for sp in spots
                          if sp["metal_per_s_raw"] > std * 1.25],
           "flat_estimate": round(len(spots) * std, 4)}
    rt = mex_route(out, standing)
    out["route"] = rt["legs"]
    out["walk_routed_sec"] = rt["walk_sec"]
    if verbose:
        print("MEX BUDGET  " + out["map"] + "  team " + str(team) + "  "
              + (position + " = " if position else "") + str(out["count"]) + " spots"
              + "   standing " + str(standing) + "   ROOM " + str(out["room"]))
        print("    n   dist  walk_s    m/s   cumulative")
        c = 0.0
        for sp in spots:
            c += sp["metal_per_s"]
            mark = "  RICH" if sp["metal_per_s"] > std * 1.25 else ""
            print("   " + str(sp["n"]).rjust(2) + ("%7.0f" % sp["distance"])
                  + ("%8.1f" % sp["walk_sec"]) + ("%7.3f" % sp["metal_per_s"])
                  + ("%12.2f" % c) + mark)
        print()
        print("  metal now " + ("%.2f" % out["m_per_s_current"]) + " m/s"
              + "   projected " + ("%.2f" % out["m_per_s_projected"]) + " m/s"
              + "   still to claim " + ("%.2f" % out["m_per_s_remaining"]) + " m/s"
              + ("   [NET of " + extractor + " energy]" if net else "   [raw]"))
        print("  " + extractor + " " + ("%+.0f" % eff["energy_flow"]) + " E/s each -> "
              + ("%+.4f" % eff["energy_as_metal"]) + " m/s at "
              + ("%g" % eff["exchange"]) + ":1"
              + "   raw projected would be "
              + ("%.2f" % out["m_per_s_projected_raw"]) + " m/s"
              + "   whole budget " + ("%+.0f" % out["energy_flow_total"]) + " E/s")
        print("  a flat " + str(out["count"]) + " x " + str(std) + " would say "
              + ("%.2f" % out["flat_estimate"]) + " m/s"
              + ("  (SAME here - no rich spot in reach)"
                 if abs(out["flat_estimate"] - out["m_per_s_projected"]) < 0.01
                 else "  (WRONG by " + ("%.2f" % (out["m_per_s_projected"]
                                                  - out["flat_estimate"])) + ")"))
        print("  walking to claim what is left: " + str(out["walk_routed_sec"])
              + "s routed one builder nearest-next"
              + "  (summing from-spawn distances would say "
              + str(round(sum(sp["walk_sec"] for sp in spots[standing:]), 1)) + "s, "
              + "which is not a route)")
    return out


def mex_route(budget: dict, standing: Optional[int] = None,
              unit: Optional[str] = None) -> dict:
    """Greedy nearest-next route over the unclaimed spots for ONE builder.

    The first leg is measured from the spawn, every later leg from where the builder
    is now standing. This is the leg list the cadence uses, so "how long does the
    ninth extractor take" counts travel from the eighth and not from home."""
    st = budget["standing"] if standing is None else standing
    u = unit or budget.get("walk_unit") or "con_bot"
    left = [dict(sp) for sp in budget["spots"][st:]]
    here = None
    legs, total = [], 0.0
    while left:
        if here is None:
            nxt = min(left, key=lambda sp: sp["walk_sec"])
            leg = nxt["walk_sec"]
        else:
            nxt = min(left, key=lambda sp: math.hypot(sp["x"] - here[0], sp["z"] - here[1]))
            leg = walk_time(math.hypot(nxt["x"] - here[0], nxt["z"] - here[1]), u)
        left.remove(nxt)
        here = (nxt["x"], nxt["z"])
        total += leg
        legs.append({"n": nxt["n"], "walk_sec": round(leg, 1),
                     "metal_per_s": nxt["metal_per_s"], "x": nxt["x"], "z": nxt["z"]})
    return {"legs": legs, "walk_sec": round(total, 1)}


# ════════════════════════════════════════════════════════════════════════════
# 5. METAL SOURCES / RECLAIM   (per-unit decomposition from a gex actions.json)
#
# A team's metal income is one number, but it comes from three places: metal
# extractors, energy converters, and RECLAIM. The engine already separates them
# per unit: `Spring.GetUnitResources(unitID)` returns that unit's own metalMake,
# and a builder shows metalMake only while it is reclaiming. The gex widget
# samples it every frame and accumulates `metalMake / 30`, so the figure it emits
# is the exact metal that unit produced over its life.
#
# MEASURED (2026-09-22, the 16-player sample dump): summing every unit's
# metalMake reproduces the engine's own `team_stats.metalProduced` to within
# 1.4% overall, and 2% for 14 of 16 teams. So the decomposition is trustworthy,
# and reclaim is the residue once extractors and converters are accounted for —
# worth 12% to 25% of a team's metal in that game.
#
# LIMIT — READ BEFORE BUILDING ON THIS: `unit_resources` is emitted ONCE per
# unit, at its death or at game end, as a LIFETIME TOTAL. There is no time
# series, so this answers "how much reclaim did X do all game", never "how much
# by minute 5". Time-resolved reclaim needs the widget to emit periodically.
#
# THE EVENT CARRIES NO SOURCE. `unit_resources` has exactly nine fields —
# action, frame, unitID, defID, teamID, metalMake, metalUse, energyMake,
# energyUse. `defID` names the unit that PRODUCED the metal (armrectr = Lazarus,
# cornecro = Graverobber), never what was consumed. There is no feature id, no
# source name and no position, so this layer alone cannot say rock or wreck.
#
# To classify, join against the other streams: `wreck_removed` carries
# `sourceName` (the original unit's defName), a position, `reclaimerTeam` and
# `isResurrect`, so it names WHAT was eaten but not how much metal it gave.
# Map rocks appear in neither (see MapInfo.rocks). So today: value here,
# composition there, and no exact join between them.
# ════════════════════════════════════════════════════════════════════════════

GEX_ACTIONS_DEFAULT = os.path.join(ED.REPO_ROOT, "gex_research", "sample_output", "actions.json")


def read_actions(path: str, actions: Optional[Iterable[str]] = None) -> Iterable[dict]:
    """Stream a gex `actions.json` (one JSON object per line), optionally keeping
    only the named action types. Large files, so this never loads the whole thing."""
    want = set(actions) if actions else None
    with open(path, encoding="utf-8", errors="ignore") as f:
        for ln in f:
            if '"action"' not in ln:
                continue
            if want and not any(f'"{a}"' in ln for a in want):
                continue
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if want is None or e.get("action") in want:
                yield e


def classify_metal_source(unitdef: dict) -> str:
    """Which bucket a unit's metalMake belongs to. Anything that is neither an
    extractor nor a converter can only be making metal by reclaiming."""
    if unitdef.get("isMetalExtractor"):
        return "mex"
    if (unitdef.get("energyConversionCapacity") or 0) > 0:
        return "converter"
    return "reclaim"


def metal_sources(path: str = GEX_ACTIONS_DEFAULT) -> dict:
    """Split every team's metal production into mex / converter / reclaim, from
    the per-unit figures the engine itself reported.

    Returns {"teams": {id: {...}}, "totals": {...}, "by_def": {...}} where each
    team carries the bucket sums, the engine's own `metal_produced`, and `ratio`
    — the share of the engine total the per-unit figures account for. A ratio
    near 1.0 is the evidence that the split is real rather than an artefact."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"no gex actions file at {path}")
    defs: Dict[int, dict] = {}
    teams: Dict[int, dict] = {}
    by_def: Dict[str, dict] = {}
    last_stats: Dict[int, dict] = {}
    last_frame = 0

    def team(t):
        return teams.setdefault(t, {"team": t, "mex": 0.0, "converter": 0.0, "reclaim": 0.0,
                                    "metal_used": 0.0, "units": 0})

    for e in read_actions(path, ("unit_def", "unit_resources", "team_stats")):
        a = e.get("action")
        last_frame = max(last_frame, e.get("frame", 0) or 0)
        if a == "unit_def":
            defs[e["defID"]] = e
        elif a == "team_stats":
            last_stats[e.get("teamID")] = e
        elif a == "unit_resources":
            make = float(e.get("metalMake") or 0.0)
            t = team(e.get("teamID"))
            t["metal_used"] += float(e.get("metalUse") or 0.0)
            if make <= 0:
                continue
            d = defs.get(e.get("defID"), {})
            n = d.get("defName", f"def{e.get('defID')}")
            bucket = classify_metal_source(d)
            t[bucket] += make
            t["units"] += 1
            # older dumps predate canResurrect / buildPower on unit_def — fall back to
            # the harvested engine defs so Lazarus and Graverobber are still recognised
            ref = ED.unitdef(n) or {}
            can_rez = bool(d.get("canResurrect") or ref.get("canResurrect"))
            bp = float(d.get("buildPower") or ref.get("buildPower") or 0)
            is_fac = bool(d.get("isFactory") or ref.get("isFactory"))
            # anything with build power can reclaim, factories included. Everything else
            # showing metalMake is being CONSUMED, not doing the consuming.
            role = ("resurrect" if can_rez else "factory" if is_fac
                    else "builder" if bp > 0 else "consumed")
            row = by_def.setdefault(n, {"defName": n, "bucket": bucket, "metal": 0.0, "units": 0,
                                        "name": d.get("name", "") or ref.get("name", ""),
                                        "can_resurrect": can_rez, "build_power": bp, "role": role})
            row["metal"] += make
            row["units"] += 1

    for t, row in teams.items():
        row["unit_total"] = row["mex"] + row["converter"] + row["reclaim"]
        st = last_stats.get(t) or {}
        row["metal_produced"] = float(st.get("metalProduced") or 0.0)
        row["ratio"] = (row["unit_total"] / row["metal_produced"]) if row["metal_produced"] else 0.0
        row["reclaim_share"] = (row["reclaim"] / row["unit_total"]) if row["unit_total"] else 0.0

    tot = {k: sum(r[k] for r in teams.values()) for k in ("mex", "converter", "reclaim", "unit_total", "metal_produced")}
    tot["ratio"] = (tot["unit_total"] / tot["metal_produced"]) if tot["metal_produced"] else 0.0
    tot["reclaim_share"] = (tot["reclaim"] / tot["unit_total"]) if tot["unit_total"] else 0.0
    return {"source": path, "last_frame": last_frame, "last_sec": last_frame / GAME_FPS,
            "teams": dict(sorted(teams.items(), key=lambda kv: kv[0] if kv[0] is not None else -1)),
            "totals": tot,
            "by_def": dict(sorted(by_def.items(), key=lambda kv: -kv[1]["metal"]))}


def reclaimers(path: str = GEX_ACTIONS_DEFAULT, team: Optional[int] = None) -> List[dict]:
    """Every unit that produced metal by reclaiming, biggest first. Resurrection
    bots (Lazarus `armrectr`, Graverobber `cornecro`, Zagreus `legrezbot`) are
    flagged, but ANY builder reclaims, so they are never the whole story."""
    ms = metal_sources(path)
    rows = [r for r in ms["by_def"].values() if r["bucket"] == "reclaim"]
    return sorted(rows, key=lambda r: -r["metal"])


# ──────────────────────────────────────────────────────────────────────────
# Reclaim RUNS — one reclaimed object at a time, and what it likely was
#
# MEASURED (2026-09-22, a 10-min 1v1 replayed with the patched widget):
# metalMake does NOT spike in a single frame. The engine holds a CONSTANT rate
# for the whole reclaim and the run lasts 29 to 211 frames, so the quantity that
# identifies an object is the INTEGRAL of a contiguous run, not a frame delta.
# Observed Lazarus runs: 483.3, 182.5, 106.0, 25.0 x4, 10.0 x2, 5.0 metal.
#
# Needs the `reclaim_sample` event, which only the patched gex widget emits
# (gex_research/vendor/gex.lua, search SPLENDID). Older dumps have only the
# lifetime totals in `unit_resources` and cannot be split into runs at all.
#
# Three things blunt value-matching, and the report says so rather than hiding it:
#   1. an interrupted reclaim yields a PARTIAL value that matches nothing;
#   2. two objects eaten back to back with no idle frame MERGE into one run;
#   3. a cancelled build refunds its invested metal through the same channel,
#      which is why factories and half-built structures show up here too.
# ──────────────────────────────────────────────────────────────────────────

# What the run total is matched against. Keys are model names (§6) or engine
# defNames; the metal cost is resolved from the engine defs, never hard-coded.
# Curated rather than "every def with a cost": with ~200 structures in the game
# almost any total would match something by chance and the value fallback would
# become noise. These are the things players actually reclaim.
RECLAIM_CATALOG = [
    # T1 energy / storage / extraction
    "armsolar", "armwin", "armestor", "armmstor", "armadvsol", "armmex", "armgeo",
    "corsolar", "corwin", "corestor", "cormstor", "coradvsol", "cormex", "corgeo",
    "legsolar", "legwin", "legestor", "legmstor", "legadvsol", "legmex",
    # T1 production + build power
    "armlab", "armvp", "armap", "armnanotc", "corlab", "corvp", "corap", "cornanotc",
    "leglab", "legnanotc",
    # T2 — the big ones. Omitting these sent a 2600-metal Advanced Bot Lab into
    # the rock_or_wreck bucket and inflated it by 84%.
    "armalab", "armavp", "armaap", "armfus", "armamd", "armmoho",
    "coralab", "coravp", "coraap", "corfus", "cormoho",
    "legalab", "legavp", "legfus", "legmoho", "legmext15",
    # workers, which are reclaimed often enough to matter
    "armck", "armack", "armcv", "corck", "corack", "corcv", "legck", "legack",
]


@dataclass
class ReclaimRun:
    """One contiguous span of a unit producing metal it did not extract."""
    unit_id: int
    def_name: str
    team: Optional[int]
    start_sec: float
    end_sec: float
    metal: float
    rate: float                 # m/s held during the run
    x: float
    z: float
    by_builder: bool            # False = a refund from the unit itself, not reclaim
    label: str = "?"            # matched defName, or "rock_or_wreck"
    matched_cost: float = 0.0
    delta: float = 0.0
    evidence: str = "value"     # "corpse" = a matching unit died right there; "value" = cost match only
    corpse_def: Optional[str] = None
    corpse_dist: Optional[float] = None
    corpse_sec: Optional[float] = None
    recovered: Optional[float] = None    # metal / the dead unit's cost
    dist_from_base: Optional[float] = None
    zone: str = "?"                      # "home" | "field", by distance from the team's own start
    sanity: List[str] = field(default_factory=list)   # loose plausibility warnings, never rejections

    @property
    def seconds(self) -> float:
        return round(self.end_sec - self.start_sec, 2)


# Loose sanity rules. These never reject a classification, they annotate one that
# looks off, so a wrong answer is visible instead of silently plausible. The hard
# constraint (a thing cannot be reclaimed before it was ever built) comes from the
# stream itself and is applied separately in classify_reclaim_value.
T2_FLOOR_SEC = 300.0        # nobody has a fusion or a T2 lab standing before ~5 min
T2_HINTS = ("fus", "alab", "avp", "aap", "amd", "moho", "ack", "aca", "acv", "advsol")
HOME_RADIUS = 1400.0        # elmos from a team's own start that still counts as "home"


def sanity_notes(label: str, at_sec: float, zone: str, recovered: Optional[float],
                 first_death_sec: Optional[float], is_mobile: bool, is_t2: bool) -> List[str]:
    """Loose plausibility flags for one classified run."""
    out = []
    if is_mobile and (first_death_sec is None or at_sec < first_death_sec):
        out.append("unit wreck before anything had died")
    if is_t2 and at_sec < T2_FLOOR_SEC:
        out.append(f"T2 object before {T2_FLOOR_SEC / 60:.0f} min")
    if label == "rock_or_wreck" and zone == "home" and (first_death_sec is None or at_sec < first_death_sec):
        out.append("unidentified at home with no deaths yet: map rock")
    if recovered is not None and recovered < 0.25:
        out.append(f"only {recovered * 100:.0f}% recovered, likely a fragment")
    return out


def reclaim_catalog(names: Optional[Sequence[str]] = None) -> Dict[str, float]:
    """defName -> metal cost, from the engine defs (§1 data layer)."""
    out = {}
    for n in (names or RECLAIM_CATALOG):
        d = ED.unitdef(n)
        if d and (d.get("metalCost") or 0) > 0:
            out[n] = float(d["metalCost"])
    return out


def classify_reclaim_value(metal: float, catalog: Dict[str, float],
                           tol_frac: float = 0.04, tol_abs: float = 4.0,
                           available: Optional[Dict[str, float]] = None,
                           at_sec: Optional[float] = None) -> Tuple[str, float, float]:
    """Match a run's total against known building costs. Returns
    (label, matched_cost, delta). Unmatched is 'rock_or_wreck'.

    `available` maps defName to the first second a unit of that type existed
    ANYWHERE in the game. A candidate is rejected if it had not been built yet:
    nothing can be reclaimed before it exists. That is what stops a 2600-metal
    run at four minutes being read as an Advanced Bot Lab, without needing a
    hand-tuned "T2 is late game" rule — the stream already knows."""
    best = None
    for name, cost in catalog.items():
        if available is not None and at_sec is not None:
            born = available.get(name)
            if born is None or born > at_sec:
                continue
        d = abs(metal - cost)
        if d <= max(tol_abs, tol_frac * cost) and (best is None or d < best[0]):
            best = (d, name, cost)
    if best is None:
        return ("rock_or_wreck", 0.0, metal)
    return (best[1], best[2], round(metal - best[2], 2))


def reclaim_runs(path: str = GEX_ACTIONS_DEFAULT, gap_frames: int = 2,
                 min_metal: float = 0.5, tol_frac: float = 0.04,
                 tol_abs: float = 4.0, catalog: Optional[Sequence[str]] = None,
                 corpse_radius: float = 250.0, corpse_window: float = 180.0) -> List[ReclaimRun]:
    """Split every unit's `reclaim_sample` stream into runs and identify each.

    A unit's own passive `metalMake` (the commander's +2/s, a mex's extraction) is
    subtracted first, so what remains can only be reclaim or a build refund.

    Identification prefers EVIDENCE over arithmetic. A unit that died next to the
    run, shortly before it, is the thing that was eaten — that beats matching the
    total against a price list, which cannot tell a 470-metal corlab from a
    500-metal armlab once the reclaim is 97% complete. Only when no corpse fits
    does it fall back to value matching, and failing that the run is
    `rock_or_wreck`: map reclaim or wreckage with no death to point at."""
    defs: Dict[int, dict] = {}
    rows: List[tuple] = []
    deaths: List[tuple] = []          # (sec, x, z, defName, cost)
    first_built: Dict[str, float] = {}     # defName -> first second one existed anywhere
    base: Dict[int, Tuple[float, float]] = {}   # team -> its commander's spawn position
    first_death_sec: Optional[float] = None
    seen_sample = False
    for e in read_actions(path, ("unit_def", "reclaim_sample", "unit_killed",
                                 "unit_created", "factory_unit_created")):
        a = e.get("action")
        if a == "unit_def":
            defs[e["defID"]] = e
            continue
        if a in ("unit_created", "factory_unit_created"):
            d = defs.get(e.get("defID"), {})
            n = e.get("defName") or d.get("defName")
            sec = e["frame"] / GAME_FPS
            if n and (n not in first_built or sec < first_built[n]):
                first_built[n] = sec
            if d.get("isCommander") and e.get("teamID") is not None and e.get("teamID") not in base:
                base[e["teamID"]] = (float(e.get("unit_x") or 0), float(e.get("unit_z") or 0))
            continue
        if a == "unit_killed":
            d = defs.get(e.get("defID"), {})
            n = e.get("defName") or d.get("defName")
            if n:
                sec = e["frame"] / GAME_FPS
                deaths.append((sec, float(e.get("killed_x") or 0),
                               float(e.get("killed_z") or 0), n, float(d.get("metalCost") or 0)))
                if first_death_sec is None or sec < first_death_sec:
                    first_death_sec = sec
            continue
        seen_sample = True
        d = defs.get(e.get("defID"), {})
        rate = float(e.get("metalMake") or 0.0) - float(d.get("metalMake") or 0.0)
        if rate > 0.05:
            rows.append((e["unitID"], e["frame"], rate, e["defID"], e.get("x", 0), e.get("z", 0),
                         e.get("teamID")))
    if not seen_sample:
        raise ValueError(
            f"{os.path.basename(path)} has no `reclaim_sample` events. Re-run the replay with the "
            f"patched widget (gex_research/vendor/gex.lua, search SPLENDID); older dumps carry only "
            f"the lifetime totals in `unit_resources`.")

    cat = reclaim_catalog(catalog)
    runs: List[ReclaimRun] = []
    cur = None
    for uid, f, rate, did, x, z, team in sorted(rows):
        if cur and uid == cur["u"] and f - cur["last"] <= gap_frames:
            cur["last"] = f
            cur["m"] += rate / GAME_FPS
            cur["peak"] = max(cur["peak"], rate)
        else:
            if cur:
                runs.append(cur)
            cur = {"u": uid, "d": did, "s": f, "last": f, "m": rate / GAME_FPS,
                   "peak": rate, "x": x, "z": z, "t": team}
    if cur:
        runs.append(cur)

    out: List[ReclaimRun] = []
    for r in runs:
        if r["m"] < min_metal:
            continue
        d = defs.get(r["d"], {})
        name = d.get("defName", f"def{r['d']}")
        secs = max((r["last"] - r["s"] + 1) / GAME_FPS, 1 / GAME_FPS)
        run = ReclaimRun(unit_id=r["u"], def_name=name, team=r["t"],
                         start_sec=round(r["s"] / GAME_FPS, 2), end_sec=round(r["last"] / GAME_FPS, 2),
                         metal=round(r["m"], 2), rate=round(r["m"] / secs, 1), x=r["x"], z=r["z"],
                         by_builder=(float(d.get("buildPower") or 0) > 0))
        # Evidence first: a unit that died next to this run, shortly before it.
        # Nearest is NOT enough — a 20-metal scout dying beside a 500-metal lab is
        # closer but cannot supply 483 metal. Require the corpse to be able to
        # ACCOUNT for the metal, then prefer the one that explains it best.
        best = None
        for sec, dx, dz, dname, dcost in deaths:
            if not (run.start_sec - corpse_window <= sec <= run.end_sec + 2):
                continue
            dist = math.hypot(dx - run.x, dz - run.z)
            if dist > corpse_radius or dcost <= 0 or run.metal > dcost * 1.15:
                continue
            key = (abs(run.metal - dcost), dist)
            if best is None or key < best[0]:
                best = (key, dist, sec, dname, dcost)
        if best and run.by_builder:
            _, dist, sec, dname, dcost = best
            run.corpse_dist, run.corpse_sec, run.corpse_def = round(dist, 1), round(sec, 1), dname
            run.evidence, run.label, run.matched_cost = "corpse", dname, dcost
            run.delta = round(run.metal - dcost, 2)
            run.recovered = round(run.metal / dcost, 3) if dcost else None
        else:
            run.label, run.matched_cost, run.delta = classify_reclaim_value(
                run.metal, cat, tol_frac, tol_abs, available=first_built, at_sec=run.start_sec)
            run.evidence = "value" if run.label != "rock_or_wreck" else "none"

        # where it happened, relative to the reclaiming team's own start
        if run.team in base:
            bx, bz = base[run.team]
            run.dist_from_base = round(math.hypot(run.x - bx, run.z - bz), 1)
            run.zone = "home" if run.dist_from_base <= HOME_RADIUS else "field"
        # loose plausibility flags (never rejections)
        ld = ED.unitdef(run.label) or {}
        run.sanity = sanity_notes(run.label, run.start_sec, run.zone, run.recovered, first_death_sec,
                                  is_mobile=float(ld.get("speed") or 0) > 0,
                                  is_t2=any(h in run.label for h in T2_HINTS))
        out.append(run)
    out.sort(key=lambda r: r.start_sec)
    return out


def reclaim_summary(path: str = GEX_ACTIONS_DEFAULT, **kw) -> dict:
    """Per-team reclaim split into identified buildings and the rock/wreck residue."""
    runs = reclaim_runs(path, **kw)
    teams: Dict[Optional[int], dict] = {}
    for r in runs:
        t = teams.setdefault(r.team, {"team": r.team, "buildings": 0.0, "rock_or_wreck": 0.0,
                                      "refunds": 0.0, "runs": 0, "by_label": collections_counter()})
        t["runs"] += 1
        if not r.by_builder:
            t["refunds"] += r.metal
        elif r.label == "rock_or_wreck":
            t["rock_or_wreck"] += r.metal
        else:
            t["buildings"] += r.metal
            t["by_label"][r.label] += r.metal
    return {"source": path, "runs": runs, "teams": teams}


def collections_counter():
    from collections import Counter
    return Counter()


def print_reclaim_runs(path: str = GEX_ACTIONS_DEFAULT, **kw) -> List[ReclaimRun]:
    runs = reclaim_runs(path, **kw)
    cat = reclaim_catalog(kw.get("catalog"))
    print(f"reclaim runs — {os.path.basename(path)}   "
          f"catalog: {len(cat)} buildings, e.g. armsolar={cat.get('armsolar', 0):g} armwin={cat.get('armwin', 0):g}")
    print(f"  {'t':>7} {'dur':>5} {'by':14} {'metal':>8}  {'identified as':16} {'how':>7} {'got':>6} {'zone':>6} {'from base':>9}  flags")
    for r in runs:
        tag = r.label if r.by_builder else "build refund"
        got = f"{r.recovered * 100:5.0f}%" if r.recovered else ""
        how = {"corpse": "corpse", "value": "value", "none": "-"}[r.evidence] if r.by_builder else "-"
        dist = f"{r.dist_from_base:9.0f}" if r.dist_from_base is not None else " " * 9
        print(f"  {r.start_sec:7.1f} {r.seconds:5.1f} {r.def_name:14} {r.metal:8.1f}  "
              f"{tag:16} {how:>7} {got:>6} {r.zone:>6} {dist}  {'; '.join(r.sanity)}")
    tally: Dict[str, List[float]] = {}
    for r in runs:
        if not r.by_builder or r.label == "rock_or_wreck":
            continue
        tally.setdefault(r.label, []).append(r.metal)
    if tally:
        print(f"\n  what was eaten:")
        for lab, vals in sorted(tally.items(), key=lambda kv: -sum(kv[1])):
            cost = reclaim_catalog().get(lab) or (ED.unitdef(lab) or {}).get("metalCost") or 0
            print(f"    {lab:12} x{len(vals):<3} {sum(vals):9.1f} metal   "
                  f"(cost {cost:g}, recovered {sum(vals) / (cost * len(vals)) * 100 if cost else 0:.0f}%)")
    by_corpse = sum(r.metal for r in runs if r.by_builder and r.evidence == "corpse")
    by_value = sum(r.metal for r in runs if r.by_builder and r.evidence == "value")
    k = sum(r.metal for r in runs if r.by_builder and r.label == "rock_or_wreck")
    f = sum(r.metal for r in runs if not r.by_builder)
    tot = by_corpse + by_value + k + f
    print(f"\n  building reclaim, corpse-confirmed {by_corpse:8.1f} metal")
    print(f"  building reclaim, value-matched     {by_value:8.1f} metal   (weaker: a price match only)")
    print(f"  rock_or_wreck                       {k:8.1f} metal   "
          f"({k / tot * 100 if tot else 0:.0f}% of all) — map reclaim or old wreckage, no death to point at")
    print(f"  build refunds                       {f:8.1f} metal   (not reclaim: a cancelled build returning metal)")
    return runs


# ──────────────────────────────────────────────────────────────────────────
# Build timeline — what got FINISHED, when, and which mex spots were taken
#
# The economic question a build answers is "these are the mexes available to me,
# how fast do I get a worker onto every one of them". So the timeline tracks two
# curves together: eco structures completed, and mex spots claimed with their
# walking distance from spawn. `unit_finished` is the honest completion signal;
# `unit_created` is only the order being placed.
# ──────────────────────────────────────────────────────────────────────────

ECO_KIND = [
    ("mex", ("armmex", "cormex", "legmex")),
    ("t2mex", ("armmoho", "cormoho", "legmoho", "legmext15")),
    ("solar", ("armsolar", "corsolar", "legsolar")),
    ("wind", ("armwin", "corwin", "legwin")),
    ("advsolar", ("armadvsol", "coradvsol", "legadvsol")),
    ("fusion", ("armfus", "corfus", "legfus")),
    ("converter", ("armmakr", "cormakr", "legeconv")),
    ("estorage", ("armestor", "corestor", "legestor")),
    ("worker", ("armck", "corck", "legck")),
    ("t2worker", ("armack", "corack", "legack")),
    ("nano", ("armnanotc", "cornanotc", "legnanotc")),
    ("factory", ("armlab", "corlab", "leglab", "armvp", "corvp", "armap", "corap")),
    ("t2factory", ("armalab", "coralab", "legalab", "armavp", "coravp", "armaap", "coraap")),
    ("rez", ("armrectr", "cornecro", "legrezbot")),
]
_KIND_OF = {n: k for k, names in ECO_KIND for n in names}


def unit_kind(def_name: str) -> Optional[str]:
    return _KIND_OF.get(def_name)


def build_timeline(path: str, team: Optional[int] = None, until_sec: float = 900.0,
                   map_name: Optional[str] = None) -> dict:
    """Completion timeline of the eco units that define an opening, per team.

    Also resolves every metal extractor to the map spot it sits on, with the
    distance from that team's spawn — the "I walked a worker out to 5, 6 and 7"
    signal, which is invisible in a plain unit count."""
    finished: List[tuple] = []          # (sec, team, defName, kind)
    created_pos: Dict[int, tuple] = {}  # unitID -> (x, z)
    base: Dict[int, Tuple[float, float]] = {}
    defs: Dict[int, dict] = {}
    map_seen = map_name
    for e in read_actions(path, ("unit_def", "unit_created", "factory_unit_created",
                                 "unit_finished", "start")):
        a = e.get("action")
        if a == "unit_def":
            defs[e["defID"]] = e
        elif a in ("unit_created", "factory_unit_created"):
            n = e.get("defName") or defs.get(e.get("defID"), {}).get("defName")
            if e.get("unit_x") is not None:
                created_pos[e["unitID"]] = (float(e["unit_x"]), float(e["unit_z"]))
            d = defs.get(e.get("defID"), {})
            if d.get("isCommander") and e.get("teamID") is not None and e["teamID"] not in base:
                base[e["teamID"]] = created_pos.get(e["unitID"], (0.0, 0.0))
        elif a == "unit_finished":
            n = e.get("defName") or defs.get(e.get("defID"), {}).get("defName")
            k = unit_kind(n) if n else None
            sec = e["frame"] / GAME_FPS
            if k and sec <= until_sec:
                finished.append((sec, e.get("teamID"), n, k, created_pos.get(e["unitID"])))
    finished.sort()

    mp = None
    if map_seen:
        try:
            mp = read_map(map_seen)
        except Exception:                                      # noqa: BLE001
            mp = None

    teams = sorted({t for _, t, _, _, _ in finished if t is not None})
    out = {"source": path, "map": map_seen, "teams": {}}
    for t in teams:
        if team is not None and t != team:
            continue
        rows = [r for r in finished if r[1] == t]
        seq: Dict[str, List[float]] = {}
        mexes = []
        for sec, _, n, k, pos in rows:
            seq.setdefault(k, []).append(round(sec, 1))
            if k == "mex" and pos and t in base:
                dist = math.hypot(pos[0] - base[t][0], pos[1] - base[t][1])
                spot = None
                if mp and mp.mex_spots:
                    spot = min(mp.mex_spots, key=lambda s: s.distance_to(*pos))
                mexes.append({"n": len(mexes) + 1, "sec": round(sec, 1), "dist": round(dist),
                              "spot": spot.id if spot else None})
        out["teams"][t] = {"team": t, "counts": {k: len(v) for k, v in sorted(seq.items())},
                           "times": seq, "mexes": mexes, "base": base.get(t)}
    return out


def print_build_timeline(path: str, until_sec: float = 600.0, map_name: str = "All That Glitters") -> dict:
    tl = build_timeline(path, until_sec=until_sec, map_name=map_name)
    for t, r in tl["teams"].items():
        print(f"team {t}   " + "  ".join(f"{k} x{v}" for k, v in r["counts"].items()))
        order = [(s, k) for k, vs in r["times"].items() for s in vs]
        order.sort()
        line, last = [], None
        for s, k in order:
            line.append(f"{int(s // 60)}:{int(s % 60):02d} {k}")
        print("   " + " | ".join(line[:28]))
        if r["mexes"]:
            print(f"   mexes: " + ", ".join(f"#{m['n']}@{int(m['sec'] // 60)}:{int(m['sec'] % 60):02d}"
                                            f"({m['dist']}e)" for m in r["mexes"]))
    return tl


_ROLE_TAG = {"resurrect": "RESURRECT bot", "factory": "factory (reclaims)",
             "builder": "builder", "consumed": "<- being consumed"}


def print_metal_sources(path: str = GEX_ACTIONS_DEFAULT, top: int = 14) -> dict:
    ms = metal_sources(path)
    t = ms["totals"]
    print(f"metal sources — {os.path.basename(ms['source'])}   through {ms['last_sec'] / 60:.1f} min")
    print(f"  {'team':>4} {'mex':>9} {'converter':>10} {'reclaim':>9} {'unit sum':>10} "
          f"{'engine':>9} {'acct':>6} {'rcl%':>6}")
    for r in ms["teams"].values():
        if r["team"] is None:
            continue
        print(f"  {r['team']:>4} {r['mex']:9.0f} {r['converter']:10.0f} {r['reclaim']:9.0f} "
              f"{r['unit_total']:10.0f} {r['metal_produced']:9.0f} {r['ratio'] * 100:5.1f}% {r['reclaim_share'] * 100:5.1f}%")
    print(f"  {'ALL':>4} {t['mex']:9.0f} {t['converter']:10.0f} {t['reclaim']:9.0f} "
          f"{t['unit_total']:10.0f} {t['metal_produced']:9.0f} {t['ratio'] * 100:5.1f}% {t['reclaim_share'] * 100:5.1f}%")
    print(f"\n  'acct' = share of the engine's own metalProduced the per-unit figures account for.")
    print(f"\n  reclaim by unit type:")
    print(f"    {'defName':14} {'metal':>10} {'units':>6}  {'per unit':>9}  what")
    for r in [x for x in ms["by_def"].values() if x["bucket"] == "reclaim"][:top]:
        print(f"    {r['defName']:14} {r['metal']:10.0f} {r['units']:6} {r['metal'] / max(r['units'], 1):9.0f}  "
              f"{r['name'][:24]:24} {_ROLE_TAG[r['role']]}")
    odd = [x for x in ms["by_def"].values() if x["bucket"] == "reclaim" and x["role"] == "consumed"]
    if odd:
        share = sum(x["metal"] for x in odd) / max(ms["totals"]["reclaim"], 1) * 100
        print(f"\n  {len(odd)} types with no build power also show metalMake "
              f"({sum(x['metal'] for x in odd):.0f} metal, {share:.2f}% of reclaim). Those are units "
              f"being CONSUMED, the victim side of the same transfer — so read the reclaim column "
              f"as a team total, not as per-unit credit.")
    rez = [x for x in ms["by_def"].values() if x["role"] == "resurrect"]
    if rez:
        share = sum(x["metal"] for x in rez) / max(ms["totals"]["reclaim"], 1) * 100
        print("\n  resurrection bots: "
              + ", ".join(f"{x['defName']} ({x['name']}) {x['metal']:.0f}m" for x in rez)
              + f"  =  {share:.1f}% of all reclaim")
    return ms


# ════════════════════════════════════════════════════════════════════════════
# 6. OBJECT DATA  (econ_model.json `objectTypes`, resolved from the engine defs)
#    Costs: metal, energy, buildpower(=build work). Income is per-second.
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class ObjectType:
    name: str
    metal_cost: float = 0.0
    energy_cost: float = 0.0
    bp_cost: float = 0.0          # build work (BP-seconds)
    metal_income: float = 0.0
    energy_income: float = 0.0
    bp_income: float = 0.0        # build power this unit contributes (builders)
    is_builder: bool = False
    kind: str = "unit"            # building | builder | unit | reclaim
    stor_e: float = 0.0
    stor_m: float = 0.0
    converter: int = 0
    wind_powered: bool = False
    factory: bool = False
    speed: float = 0.0
    build_range: float = 0.0
    def_name: Optional[str] = None
    provisional: bool = False
    reclaim_of: Optional[str] = None

    @classmethod
    def from_resolved(cls, t: dict) -> "ObjectType":
        return cls(t["name"], t["metal"], t["energy"], t["bp"], t["mInc"], t["eInc"],
                   t.get("builderBp", 0.0), t["kind"] == "builder", t["kind"], t["storE"], t["storM"],
                   t["converter"], t["windPowered"], t["factory"], t.get("speed", 0.0), t.get("range", 0.0),
                   t.get("defName"), t.get("provisional", False), t.get("of"))

    # --- ROI helpers (from eco_calculator) ---
    def build_time(self, builder_bp: float = DEFAULT_BUILDER_BP) -> float:
        return self.bp_cost / builder_bp if builder_bp else float("inf")

    def troi(self, output_e_per_s: float) -> float:
        """Total ROI in T1-converted energy-seconds: (M*70 + E) / output."""
        if output_e_per_s <= 0:
            return float("inf")
        return (self.metal_cost * ENERGY_PER_METAL + self.energy_cost) / output_e_per_s

    def eroi(self, output_e_per_s: float,
             builder_bp: float = DEFAULT_BUILDER_BP) -> float:
        """Time to repay own energy cost (or build time if E_cost == 0)."""
        if self.energy_cost == 0:
            return self.build_time(builder_bp)
        return self.energy_cost / output_e_per_s if output_e_per_s else float("inf")


OBJECTS: Dict[str, ObjectType] = {n: ObjectType.from_resolved(t) for n, t in ED.object_types().items()}
ALIASES: Dict[str, str] = ED.aliases()          # engine defName → OBJECTS key


# ════════════════════════════════════════════════════════════════════════════
# 7. ECONOMY / BUILD-ORDER SIMULATOR
#    Based on bar_calc.Environment, enhanced with calibrated walk time and the
#    per-resource stall reporting from eco_simulator. Semantics mirror
#    splendid_buildSimulator.js (build / constructObject / advance / applyCompletion).
# ════════════════════════════════════════════════════════════════════════════

_BASE = _CFG["baseState"]


@dataclass
class Environment:
    time: float = 0.0
    metal: float = _BASE["metal"]
    energy: float = _BASE["energy"]
    max_metal: float = _BASE["maxMetal"]
    max_energy: float = _BASE["maxEnergy"]
    metal_per_second: float = OBJECTS["Commander"].metal_income
    energy_per_second: float = OBJECTS["Commander"].energy_income
    builders: List[str] = field(default_factory=lambda: ["Commander"])
    buildings: List[str] = field(default_factory=list)
    history: List[Tuple[str, float]] = field(default_factory=list)
    n_converters: int = 0
    wind: float = DEFAULT_WIND
    verbose: bool = True
    converted: float = 0.0
    gathered_m: float = 0.0      # cumulative metal produced, ignoring storage caps
    gathered_e: float = 0.0
    spilled_m: float = 0.0       # production lost to a full bank - metal spent for nothing
    spilled_e: float = 0.0

    # ---- build power ----
    def total_bp(self) -> float:
        return sum(OBJECTS[b].bp_income for b in self.builders if b in OBJECTS)

    # ---- incomes as the model sees them ----
    def income_m(self) -> float:
        return self.metal_per_second

    def income_e(self) -> float:
        """Table wind is swapped for the environment's wind on every standing turbine."""
        e = self.energy_per_second
        for b in self.buildings:
            t = OBJECTS.get(b)
            if t and t.wind_powered:
                e += self.wind - t.energy_income
        return e

    # ---- timing ----
    def build_times(self, name: str, builder_bp: Optional[float] = None,
                    min_add_time: float = 0.0) -> dict:
        """Time gated by build power, energy income, and metal income — the
        actual time is the max of the three (you stall on the slowest)."""
        obj = OBJECTS[name]
        bp = builder_bp if builder_bp else self.total_bp()
        bp_time = (obj.bp_cost / bp if bp else float("inf")) + min_add_time
        m_inc, e_inc = self.income_m(), self.income_e()
        e_time = 0.0 if obj.energy_cost <= self.energy else \
            ((obj.energy_cost - self.energy) / e_inc if e_inc > 0 else float("inf"))
        m_time = 0.0 if obj.metal_cost <= self.metal else \
            ((obj.metal_cost - self.metal) / m_inc if m_inc > 0 else float("inf"))
        total = max(bp_time, e_time, m_time)
        stall = "energy" if e_time > bp_time else ("metal" if m_time > bp_time else None)
        return {"bp": bp_time, "energy": e_time, "metal": m_time, "total": total, "stall": stall}

    calculate_build_times = build_times   # bar_calc spelling

    # ---- one build, optionally preceded by a walk ----
    def build(self, name: str, walk_squares: float = 0.0,
              walker: str = "commander", min_add_time: float = 0.0) -> bool:
        if name not in OBJECTS:
            self._say(f"  ! unknown object: {name}")
            return False

        # Walk to the site first (calibrated from the map grid).
        wt = walk_time_squares(walk_squares, walker) if walk_squares else 0.0
        if wt > 0 and math.isfinite(wt):
            self.advance(wt)

        bt = self.build_times(name, min_add_time=min_add_time)
        if not math.isfinite(bt["total"]):
            self._say(f"  ! cannot build {name}: no income for the missing resource")
            return False
        if bt["energy"] > bt["bp"]:
            self._say(f"  ! energy stall building {name}")
        if bt["metal"] > bt["bp"]:
            self._say(f"  ! metal stall building {name}")

        obj = OBJECTS[name]
        self.metal -= obj.metal_cost
        self.advance(bt["total"], eps=obj.energy_cost / max(bt["total"], 1e-9))
        self.apply_completion(name)
        walk_note = f" (+{wt:.1f}s walk {walk_squares}sq)" if wt else ""
        self._say(f"  {self.time:6.1f}s  built {name:<11}{walk_note}  "
                  f"M={self.metal:6.0f} E={self.energy:6.0f}  "
                  f"+{self.income_m():.1f}M/s +{self.income_e():.0f}E/s")
        return True

    def construct_object(self, name: str, min_add_time: float = 1.0) -> bool:
        """bar_calc.construct_object: same as build(), no walk, +min_add_time s per build."""
        return self.build(name, min_add_time=min_add_time)

    # ---- register a completed object: incomes, storage, converters, new builders ----
    def apply_completion(self, name: str) -> None:
        obj = OBJECTS[name]
        if obj.kind == "reclaim":
            self.remove_completion(obj.reclaim_of, reclaim=True)
            self.history.append((name, self.time))
            return
        (self.builders if obj.is_builder else self.buildings).append(name)
        if obj.converter:
            self.n_converters += obj.converter
        if obj.stor_e:
            self.max_energy += obj.stor_e
        if obj.stor_m:
            self.max_metal += obj.stor_m
        self.metal_per_second += obj.metal_income
        self.energy_per_second += obj.energy_income
        self.history.append((name, self.time))

    def remove_completion(self, name: str, reclaim: bool = False) -> bool:
        obj = OBJECTS[name]
        lst = self.builders if obj.is_builder else self.buildings
        if name not in lst:
            return False
        lst.remove(name)
        if obj.converter:
            self.n_converters = max(0, self.n_converters - obj.converter)
        if obj.stor_e:
            self.max_energy -= obj.stor_e
        if obj.stor_m:
            self.max_metal -= obj.stor_m
        self.metal_per_second -= obj.metal_income
        self.energy_per_second -= obj.energy_income
        if reclaim:
            self.metal = min(self.metal + obj.metal_cost, self.max_metal)
        return True

    # ---- advance the clock, applying income, caps, and converters ----
    def advance(self, dt: float, eps: float = 0.0, conv_floor: float = 0.5) -> None:
        if dt <= 0:
            return
        # cumulative production BEFORE storage capping — what the economy actually
        # made, as opposed to what fitted in the bank. This is the number that
        # compares two openings fairly; a bank total hides overflow.
        self.gathered_m += self.income_m() * dt
        self.gathered_e += self.income_e() * dt
        want_m = self.metal + self.income_m() * dt
        if want_m > self.max_metal:
            self.spilled_m += want_m - self.max_metal
        self.metal = min(want_m, self.max_metal)
        self.energy += (self.income_e() - eps) * dt
        # Energy converters turn surplus energy above conv_floor*cap into metal.
        excess = self.energy - conv_floor * self.max_energy
        if excess > 0 and self.n_converters:
            converted = min(self.n_converters * dt, math.floor(excess / ENERGY_PER_METAL))
            self.metal += converted
            self.energy -= converted * ENERGY_PER_METAL
            self.converted += converted
        if self.energy > self.max_energy:
            self.spilled_e += self.energy - self.max_energy
        self.energy = min(self.energy, self.max_energy)
        self.time += dt

    advance_time = advance   # bar_calc spelling

    def build_order(self, order: List, min_add_time: float = 0.0) -> "Environment":
        """Run a build order. Each entry is either 'Name' or ('Name', walk_sq)."""
        for entry in order:
            name, walk = entry if isinstance(entry, tuple) else (entry, 0.0)
            if not self.build(name, walk_squares=walk, min_add_time=min_add_time):
                break
        return self

    def snapshot(self) -> dict:
        return {"time": self.time, "metal": self.metal, "energy": self.energy,
                "maxMetal": self.max_metal, "maxEnergy": self.max_energy,
                "mInc": self.income_m(), "eInc": self.income_e(), "bp": self.total_bp()}

    def status(self) -> None:
        print(f"\n  t={self.time:.1f}s  M={self.metal:.0f}/{self.max_metal:.0f} "
              f"E={self.energy:.0f}/{self.max_energy:.0f}  "
              f"income +{self.income_m():.1f}M/s +{self.income_e():.0f}E/s  "
              f"BP={self.total_bp():.0f}")
        print(f"  builders: {', '.join(self.builders)}")
        print(f"  buildings: {', '.join(self.buildings) or 'none'}")

    def _say(self, msg: str) -> None:
        if self.verbose:
            print(msg)


# ══════════════════════════════════════════════════════════════════════════
# LAYER 1 — REFERENCING GAMES
#
# Every task here starts with "the Nth most recent game like X". Doing that by
# hand means hunting filenames, and filenames are in UTC while the clock on the
# wall is not. So: `game_ref(1)` is the newest, `game_ref(3)` the third newest,
# optionally filtered by matchup or by who played. Nothing downstream should ever
# need a path typed into it again.
# ══════════════════════════════════════════════════════════════════════════

DEMOS_DIR = os.environ.get(
    "BAR_DEMOS", r"C:\Users\codes\AppData\Local\Programs\Beyond-All-Reason\data\demos")
GAME_DATA_DIR = os.path.join(HERE, "data")
_REPLAY_HELPER = os.path.join(HERE, "replay_demo.mjs")
_ROSTER_HELPER = os.path.join(ED.REPO_ROOT, "gex_research", "tools", "demoparser", "parse.mjs")


@dataclass
class GameRef:
    """One game, found by position rather than by filename."""
    index: int                       # 1 = most recent
    demo: str
    name: str
    started_utc: str                 # from the filename, which is UTC
    written_local: str               # file mtime, which is wall-clock local
    size_kb: int
    map_name: str = ""
    matchup: str = ""
    players: int = 0
    engine: str = ""
    actions: Optional[str] = None    # set once the game has been replayed

    @property
    def game_id(self) -> str:
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})", self.name)
        return f"{m.group(1)}{m.group(2)}{m.group(3)}-{m.group(4)}{m.group(5)}{m.group(6)}" if m else self.name[:20]


def _demo_files() -> List[str]:
    """Newest first. Filenames lead with a UTC timestamp, so a name sort is a
    time sort and does not need the filesystem."""
    if not os.path.isdir(DEMOS_DIR):
        raise FileNotFoundError(f"demos dir not found: {DEMOS_DIR} (set $BAR_DEMOS)")
    return sorted((f for f in os.listdir(DEMOS_DIR) if f.lower().endswith(".sdfz")),
                  reverse=True)


def _node_json(script: str, args: Sequence[str], cwd: Optional[str] = None) -> Optional[dict]:
    import subprocess
    r = subprocess.run(["node", script, *args], cwd=cwd or ED.REPO_ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return None
    out = (r.stdout or "").strip()
    if not out:
        return None
    # helpers print either one JSON object pretty-printed, or a one-line summary
    # as the last line; try whole-output first, then the trailing line
    try:
        return json.loads(out)
    except ValueError:
        pass
    start = out.find("{")
    if start >= 0:
        try:
            return json.loads(out[start:])
        except ValueError:
            pass
    for ln in reversed(out.splitlines()):
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except ValueError:
                continue
    return None


@lru_cache(maxsize=512)
def _demo_header(path: str) -> dict:
    """Map, engine, matchup and roster for one demo, via the demo parser."""
    out = _node_json(_ROSTER_HELPER, [path]) or {}
    players = [p for p in (out.get("players") or []) if p]
    ais = [a for a in (out.get("ais") or []) if a]
    by_ally: Dict[object, int] = {}
    for p in players:
        by_ally[p.get("allyTeamId")] = by_ally.get(p.get("allyTeamId"), 0) + 1
    sizes = sorted(by_ally.values(), reverse=True)
    if len(players) == 1 and ais:
        matchup = f"1vAI" if len(ais) == 1 else f"1v{len(ais)}AI"
    elif len(players) == 1:
        matchup = "1v0"
    else:
        matchup = "v".join(str(x) for x in sizes) or "0"
    return {"map": out.get("map", ""), "engine": out.get("engine", ""),
            "game": out.get("gameVersion", ""), "matchup": matchup,
            "players": players, "ais": ais, "durationMs": out.get("durationMs")}


@dataclass
class PlayerData:
    """Who played, from the demo roster. The replayed `actions.json` carries only
    numeric team ids, so identity has to come from the demo itself."""
    name: str
    team_id: int
    player_id: Optional[int] = None
    user_id: Optional[int] = None
    faction: Optional[str] = None
    ally_team_id: Optional[int] = None
    skill: Optional[float] = None
    start_x: Optional[float] = None
    start_z: Optional[float] = None
    sole_player: bool = False
    chosen_because: str = ""

    @property
    def start(self) -> Optional[Tuple[float, float]]:
        return (self.start_x, self.start_z) if self.start_x is not None else None

    def to_dict(self) -> dict:
        d = dict(vars(self))
        d["start"] = list(self.start) if self.start else None
        return d


# Whose games these are. A name given on the command line wins; then the only
# player in the game (a skirmish has exactly one); then this.
DEFAULT_PLAYER = os.environ.get("BAR_PLAYER", "SplendYoMetal")
FAVORITES_FILE = os.path.join(HERE, "favorites.json")


def roster(ref: "GameRef") -> List[PlayerData]:
    h = _demo_header(ref.demo)
    out = []
    ps = h.get("players") or []
    for p in ps:
        sp = p.get("startPos") or {}
        out.append(PlayerData(
            name=str(p.get("name") or "?"), team_id=int(p.get("teamId") or 0),
            player_id=p.get("playerId"), user_id=p.get("userId"),
            faction=p.get("faction"), ally_team_id=p.get("allyTeamId"),
            skill=p.get("skill"), start_x=sp.get("x"), start_z=sp.get("z"),
            sole_player=len(ps) == 1))
    return out


def resolve_player(ref: "GameRef", name: Optional[str] = None) -> Optional[PlayerData]:
    """Pick whose game to profile, in preference order, and say which applied.

    Preference: an explicit name, then the only player if there is only one, then
    the configured default, then the first on the roster. The choice and its
    reason land on `chosen_because` so a surprising pick is visible rather than
    hidden, and `--player` overrides any of it."""
    rs = roster(ref)
    if not rs:
        return None
    pick, why = None, ""
    if name:
        hits = [p for p in rs if name.lower() in p.name.lower()]
        if hits:
            pick, why = hits[0], f"matched --player {name!r}"
        else:
            pick, why = rs[0], (f"no player matched {name!r}; using first of "
                                f"{[p.name for p in rs]}")
    elif len(rs) == 1:
        pick, why = rs[0], "only player in the game"
    else:
        hits = [p for p in rs if DEFAULT_PLAYER.lower() in p.name.lower()]
        if hits:
            pick, why = hits[0], f"default player {DEFAULT_PLAYER!r}"
        else:
            pick, why = rs[0], (f"no default {DEFAULT_PLAYER!r} on a {len(rs)}-player "
                                f"roster; using first of {[p.name for p in rs]}")
    pick.chosen_because = why
    return pick


# ── Favorites: give a game a name you will remember ────────────────────────

def favorites() -> Dict[str, str]:
    if not os.path.exists(FAVORITES_FILE):
        return {}
    try:
        with open(FAVORITES_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                # noqa: BLE001
        return {}


def add_favorite(label: str, ref: "GameRef") -> str:
    fav = favorites()
    fav[label] = ref.name
    with open(FAVORITES_FILE, "w", encoding="utf-8") as fh:
        json.dump(fav, fh, indent=1)
    return FAVORITES_FILE


def resolve_game(spec: Union[int, str, "GameRef", None] = 1,
                 matchup: Optional[str] = None,
                 player: Optional[str] = None) -> "GameRef":
    """Find a game from whatever the user had to hand.

    Accepted, in the order they are tried:
      GameRef                 passed straight through
      1, "1", "3"             Nth most recent (optionally filtered)
      "<path to .sdfz>"       an explicit file
      a favorite's label      as saved by --favorite
      an extracted game id    e.g. "20260923-180706", already in bar-calc/data
      "11:21" / "2026-09-23 11:21"   local wall-clock time it was played
      any other text          substring of the filename (which is UTC)
    """
    if isinstance(spec, GameRef):
        return spec
    if spec is None:
        return game_ref(1, matchup=matchup, player=player)
    if isinstance(spec, int) or (isinstance(spec, str) and spec.strip().isdigit()):
        return game_ref(int(spec), matchup=matchup, player=player)
    s = str(spec).strip()
    if os.path.isfile(s):
        st = os.stat(s)
        h = _demo_header(s)
        return GameRef(index=0, demo=s, name=os.path.basename(s), started_utc=os.path.basename(s)[:19],
                       written_local=__import__("datetime").datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                       size_kb=st.st_size // 1024, map_name=h.get("map", ""),
                       matchup=h.get("matchup", ""), players=len(h.get("players", [])),
                       engine=h.get("engine", ""))
    fav = favorites()
    if s in fav:
        s = fav[s]
    # a game id previously extracted: 20260923-180706 -> the demo it came from
    m = re.fullmatch(r"(\d{8})-(\d{6})(?:-team\d+)?", s)
    if m:
        d, t = m.group(1), m.group(2)
        want = f"{d[:4]}-{d[4:6]}-{d[6:]}_{t[:2]}-{t[2:4]}-{t[4:]}"
        for f in _demo_files():
            if f.startswith(want):
                return _ref_for(f)
    # local wall-clock time, which is what a person remembers
    tm = re.fullmatch(r"(?:(\d{4}-\d{2}-\d{2})[ _T])?(\d{1,2}):(\d{2})", s)
    if tm:
        want_day, hh, mm = tm.group(1), int(tm.group(2)), int(tm.group(3))
        import datetime as _dt
        for f in _demo_files():
            full = os.path.join(DEMOS_DIR, f)
            lt = _dt.datetime.fromtimestamp(os.stat(full).st_mtime)
            if lt.hour == hh and lt.minute == mm and (
                    want_day is None or lt.strftime("%Y-%m-%d") == want_day):
                return _ref_for(f)
    for f in _demo_files():
        if s in f:
            return _ref_for(f)
    raise FileNotFoundError(f"no game matching {spec!r} (tried index, path, favorite, "
                            f"game id, local time, filename)")


def _ref_for(fname: str) -> "GameRef":
    full = os.path.join(DEMOS_DIR, fname)
    st = os.stat(full)
    h = _demo_header(full)
    return GameRef(index=0, demo=full, name=fname, started_utc=fname[:19].replace("_", " "),
                   written_local=__import__("datetime").datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                   size_kb=st.st_size // 1024, map_name=h.get("map", ""),
                   matchup=h.get("matchup", ""), players=len(h.get("players", [])),
                   engine=h.get("engine", ""))


def recent_games(count: int = 10, matchup: Optional[str] = None,
                 player: Optional[str] = None, scan: int = 200) -> List[GameRef]:
    """The `count` most recent games, newest first, optionally filtered.

    `matchup` is like "1v0" or "8v8". `player` is a case-insensitive substring of
    a player name. Scanning reads demo headers, so `scan` caps how deep it looks."""
    out: List[GameRef] = []
    for i, f in enumerate(_demo_files()[:scan], start=1):
        full = os.path.join(DEMOS_DIR, f)
        need_header = matchup is not None or player is not None
        h = _demo_header(full) if need_header else {}
        if matchup:
            # accepts a list: "1vAI,1v0" is a common pair, since a NullAI opponent is
            # a solo skirmish in everything but the header
            wanted = [m.strip() for m in str(matchup).split(",") if m.strip()]
            if h.get("matchup") not in wanted:
                continue
        if player and not any(player.lower() in str(p.get("name", "")).lower()
                              for p in h.get("players", [])):
            continue
        if not h:
            h = _demo_header(full)
        st = os.stat(full)
        out.append(GameRef(
            index=len(out) + 1, demo=full, name=f,
            started_utc=f[:19].replace("_", " "),
            written_local=__import__("datetime").datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            size_kb=st.st_size // 1024, map_name=h.get("map", ""),
            matchup=h.get("matchup", ""), players=len(h.get("players", [])),
            engine=h.get("engine", "")))
        if len(out) >= count:
            break
    return out


def game_ref(n: int = 1, matchup: Optional[str] = None,
             player: Optional[str] = None) -> GameRef:
    """The Nth most recent game, 1 = newest. This is the handle everything takes."""
    games = recent_games(max(n, 1), matchup=matchup, player=player)
    if len(games) < n:
        raise IndexError(f"only {len(games)} games match (wanted #{n})")
    return games[n - 1]


def ensure_actions(ref: GameRef, force: bool = False, timeout_ms: int = 600000) -> str:
    """The replayed `actions.json` for a game, replaying it headlessly if needed."""
    if ref.actions and os.path.exists(ref.actions) and not force:
        return ref.actions
    wd = os.path.join(os.environ.get("TEMP", "."), "gex_harness",
                      "wd_" + re.sub(r"[^\w.-]", "_", ref.name))
    cached = os.path.join(wd, "actions.json")
    if os.path.exists(cached) and not force:
        # a defs-only harvest is not a gameplay replay; insist on real events
        with open(cached, encoding="utf-8", errors="ignore") as fh:
            head = fh.read(400000)
        if '"unit_finished"' in head:
            ref.actions = cached
            return cached
    got = _node_json(_REPLAY_HELPER, ["--demo", ref.name, "--timeout", str(timeout_ms)])
    if not got or not got.get("actions"):
        raise RuntimeError(f"headless replay failed for {ref.name}")
    ref.actions = got["actions"]
    return ref.actions


def print_recent_games(count: int = 10, matchup: Optional[str] = None,
                       player: Optional[str] = None) -> List[GameRef]:
    gs = recent_games(count, matchup, player)
    print(f"  {'#':>3} {'played (local)':>16} {'matchup':>8} {'size':>7}  {'map':26} replayed")
    for g in gs:
        done = "yes" if (os.path.exists(os.path.join(
            os.environ.get("TEMP", "."), "gex_harness",
            "wd_" + re.sub(r"[^\w.-]", "_", g.name), "actions.json"))) else "-"
        print(f"  {g.index:>3} {g.written_local:>16} {g.matchup:>8} {g.size_kb:>5}KB  "
              f"{g.map_name[:26]:26} {done}")
    return gs


# ══════════════════════════════════════════════════════════════════════════
# LAYER 2 — EXTRACT HARD DATA
#
# One command turns a game into a fixed, durable profile of FACTS: what finished
# and when, where the extractors went, what the wind did, what was reclaimed,
# what died. No interpretation, no derived economy, no judgement — those belong
# to layer 3, which reads this file and never re-reads the replay.
#
# Keeping the split strict means an analysis can be rewritten, or a new one
# added, without replaying anything.
# ══════════════════════════════════════════════════════════════════════════

HARD_DATA_VERSION = 1


def extract_game(n: Union[int, GameRef, str] = 1, player: Optional[str] = None,
                 matchup: Optional[str] = None, team: Optional[int] = None,
                 until_sec: float = 900.0, save: bool = True,
                 force_replay: bool = False) -> dict:
    """Pull the standard fact profile out of a game and write it as hard data.

    `n` is the Nth most recent game, or a GameRef, or a path to an actions.json.
    `player` picks whose team to profile by name substring; for a skirmish there
    is only one and it is chosen automatically."""
    ref = None
    if isinstance(n, str) and n.endswith(".json") and os.path.exists(n):
        actions = n
    else:
        ref = resolve_game(n, matchup=matchup, player=player)
        actions = ensure_actions(ref, force=force_replay)
    who = resolve_player(ref, player) if ref else None
    if who is not None:
        print(f"player: {who.name} (team {who.team_id}, {who.faction}) - {who.chosen_because}")
        if team is None:
            team = who.team_id

    defs: Dict[int, dict] = {}
    finished: List[dict] = []
    created: Dict[int, dict] = {}
    wind: List[dict] = []
    deaths: List[dict] = []
    teams_seen: Dict[int, int] = {}
    econ: List[dict] = []
    for e in read_actions(actions, ("unit_def", "unit_created", "factory_unit_created",
                                    "unit_finished", "wind_update", "unit_killed",
                                    "extra_stat_update")):
        a = e.get("action")
        if a == "extra_stat_update":
            # MEASURED economy, every 15 s: banks, income, storage, build power and
            # the value split. This is the engine's own accounting, not a
            # reconstruction, so it beats anything derived from completions.
            econ.append({"t": round(e["frame"] / GAME_FPS, 1), "team": e.get("teamID"),
                         "metal": e.get("metalCurrent"), "energy": e.get("energyCurrent"),
                         "m_inc": e.get("metalIncome"), "e_inc": e.get("energyIncome"),
                         "m_store": e.get("metalStorage"), "e_store": e.get("energyStorage"),
                         "m_recv": e.get("metalReceived"), "e_recv": e.get("energyReceived"),
                         "bp_avail": e.get("buildPowerAvailable"),
                         "bp_used": e.get("buildPowerUsed"),
                         "value_total": e.get("totalValue"), "value_eco": e.get("ecoValue"),
                         "value_army": e.get("armyValue"), "value_def": e.get("defValue"),
                         "value_util": e.get("utilValue"), "value_other": e.get("otherValue"),
                         "actions": e.get("actions")})
        elif a == "unit_def":
            defs[e["defID"]] = e
        elif a in ("unit_created", "factory_unit_created"):
            created[e["unitID"]] = e
        elif a == "wind_update":
            wind.append({"t": round(e["frame"] / GAME_FPS, 2), "value": e.get("value"),
                         "x": e.get("windX"), "z": e.get("windZ")})
        elif a == "unit_killed":
            deaths.append({"t": round(e["frame"] / GAME_FPS, 2),
                           "def": e.get("defName") or defs.get(e.get("defID"), {}).get("defName"),
                           "team": e.get("teamID"), "x": e.get("killed_x"), "z": e.get("killed_z")})
        elif a == "unit_finished":
            t = e.get("teamID")
            teams_seen[t] = teams_seen.get(t, 0) + 1
            finished.append({"t": round(e["frame"] / GAME_FPS, 2), "unitID": e["unitID"],
                             "def": e.get("defName") or defs.get(e.get("defID"), {}).get("defName"),
                             "team": t})
    if team is None:
        team = max(teams_seen, key=teams_seen.get) if teams_seen else 0

    # spawn = the commander's creation position for that team
    base = None
    for u, e in created.items():
        d = defs.get(e.get("defID"), {})
        if d.get("isCommander") and e.get("teamID") == team and e.get("unit_x") is not None:
            base = (float(e["unit_x"]), float(e["unit_z"]))
            break

    mp = None
    map_name = (ref.map_name if ref else "") or ""
    if map_name:
        try:
            mp = read_map(map_name)
        except Exception:                                            # noqa: BLE001
            mp = None

    mine = [f for f in finished if f["team"] == team and f["t"] <= until_sec]
    mine.sort(key=lambda f: f["t"])
    mexes, n_mex = [], 0
    for f in mine:
        if not f["def"] or ALIASES.get(f["def"]) != "Mex":
            continue
        n_mex += 1
        c = created.get(f["unitID"], {})
        x, z = c.get("unit_x"), c.get("unit_z")
        row = {"n": n_mex, "t": f["t"], "x": x, "z": z}
        if x is not None and base:
            row["dist"] = round(math.hypot(float(x) - base[0], float(z) - base[1]), 1)
            row["walk_sec_conbot"] = round(walk_time(row["dist"], "con_bot"), 1)
        if x is not None and mp and mp.mex_spots:
            sp = min(mp.mex_spots, key=lambda s: s.distance_to(float(x), float(z)))
            row["spot"] = sp.id
            row["spot_metal_per_s"] = mp.spot_metal_per_s(sp)
        mexes.append(row)

    # wind at the engine's own 15 s window boundaries, plus the in-between samples
    by_t = {round(w["t"], 2): w for w in wind}
    windows = []
    step = WIND_UPDATE_FRAMES / GAME_FPS
    k = 0.0
    while k <= until_sec:
        w = by_t.get(round(k, 2))
        if w:
            windows.append({"t": k, "value": w["value"]})
        k += step
    wvals = [w["value"] for w in wind if w["t"] <= until_sec and w["value"] is not None]

    reclaim = []
    try:
        for r in reclaim_runs(actions):
            if r.team is None or r.team == team:
                reclaim.append({"t": r.start_sec, "sec": r.seconds, "metal": r.metal,
                                "by": r.def_name, "label": r.label, "evidence": r.evidence,
                                "recovered": r.recovered, "x": r.x, "z": r.z})
    except Exception as e:                                           # noqa: BLE001
        reclaim = []
        reclaim_note = str(e)
    else:
        reclaim_note = ""

    data = {
        "hard_data_version": HARD_DATA_VERSION,
        "extracted": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "game": {
            "id": ref.game_id if ref else os.path.basename(os.path.dirname(actions)),
            "demo": ref.name if ref else None,
            "played_local": ref.written_local if ref else None,
            "map": map_name, "engine": ref.engine if ref else None,
            "matchup": ref.matchup if ref else None,
            "actions": actions, "team": team, "base": base,
            "map_wind_range": list(mp.wind_range) if mp else None,
            "map_mex_spots": len(mp.mex_spots) if mp else None,
        },
        "player": who.to_dict() if who else None,
        "roster": [p.to_dict() for p in (roster(ref) if ref else [])],
        "mexes": mexes,
        # STARTS are what an order actually looks like on the clock; completions are
        # when it lands. Keeping both, paired by unitID, is what makes a build ledger
        # possible — and the gap between them is the build duration under real
        # resource conditions, not the nominal figure.
        "starts": [{"t": round(e["frame"] / GAME_FPS, 2),
                    "def": e.get("defName") or defs.get(e.get("defID"), {}).get("defName"),
                    "type": ALIASES.get(e.get("defName")
                                        or defs.get(e.get("defID"), {}).get("defName") or ""),
                    "unitID": u, "x": e.get("unit_x"), "z": e.get("unit_z"),
                    "from_factory": e.get("action") == "factory_unit_created"}
                   for u, e in sorted(created.items(), key=lambda kv: kv[1]["frame"])
                   if e.get("teamID") == team and e["frame"] / GAME_FPS <= until_sec],
        "completions": [{"t": f["t"], "def": f["def"],
                         "type": ALIASES.get(f["def"] or ""), "unitID": f["unitID"]}
                        for f in mine],
        "wind": {"samples": [w for w in wind if w["t"] <= until_sec],
                 "windows_15s": windows,
                 "min": min(wvals) if wvals else None,
                 "max": max(wvals) if wvals else None,
                 "mean": round(sum(wvals) / len(wvals), 3) if wvals else None},
        "econ": [r for r in econ if r["team"] == team and r["t"] <= until_sec],
        "reclaim": reclaim, "reclaim_note": reclaim_note,
        "deaths": [d for d in deaths if d["t"] <= until_sec],
    }
    if save:
        os.makedirs(GAME_DATA_DIR, exist_ok=True)
        f = os.path.join(GAME_DATA_DIR, f"{data['game']['id']}-team{team}.json")
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        data["_file"] = f
        print(f"hard data -> {os.path.relpath(f, ED.REPO_ROOT)}  "
              f"({len(data['completions'])} completions, {len(mexes)} mexes, "
              f"{len(data['wind']['samples'])} wind samples, {len(data['econ'])} econ samples, "
              f"{len(reclaim)} reclaim runs)")
    return data


# ══════════════════════════════════════════════════════════════════════════
# BUILD LEDGER — every start and every finish, with the state at that instant
#
# The effective build order is not the list of things that exist, it is the
# interleaving of orders placed and orders landing. Two builds overlapping, a
# worker walking, a structure sitting half-finished through a stall: none of that
# is visible in a completion list, all of it is visible here.
#
# Every row carries a state reading. Banks, income and build power are MEASURED
# every 15 s by the engine, so a reading at an arbitrary event time is linearly
# interpolated between the two surrounding samples and marked as such. Wind and
# the standing counts are exact at any instant.
# ══════════════════════════════════════════════════════════════════════════

def _interp(series: Sequence[dict], t: float, keys: Sequence[str]) -> dict:
    """Linear interpolation between measured samples, flagged."""
    if not series:
        return {k: None for k in keys} | {"measured": False}
    before = after = None
    for r in series:
        if r["t"] <= t:
            before = r
        if r["t"] >= t and after is None:
            after = r
    if before is None:
        return {k: after.get(k) for k in keys} | {"measured": abs(after["t"] - t) < 1e-6}
    if after is None or after is before:
        return {k: before.get(k) for k in keys} | {"measured": abs(before["t"] - t) < 1e-6}
    span = after["t"] - before["t"]
    f = 0.0 if span <= 0 else (t - before["t"]) / span
    out = {}
    for k in keys:
        a, b = before.get(k), after.get(k)
        out[k] = a if (a is None or b is None) else a + (b - a) * f
    out["measured"] = abs(before["t"] - t) < 1e-6
    return out


ECON_KEYS = ("metal", "energy", "m_inc", "e_inc", "bp_avail", "bp_used")


def build_ledger(data: dict, until_sec: float = 480.0,
                 snapshots: Optional[Sequence[float]] = None,
                 include: Optional[Sequence[str]] = None) -> dict:
    """The effective build order: every start and finish in time order, each with a
    state reading. `snapshots` adds rows at times you choose, for comparison."""
    starts = [s for s in (data.get("starts") or []) if s["t"] <= until_sec]
    fins = [c for c in (data.get("completions") or []) if c["t"] <= until_sec]
    econ = data.get("econ") or []
    winds = data.get("wind", {}).get("samples") or []
    if include:
        keep = set(include)
        starts = [s for s in starts if s.get("type") in keep]
        fins = [c for c in fins if c.get("type") in keep]

    start_by_id = {s["unitID"]: s for s in starts}
    fin_by_id = {c["unitID"]: c for c in fins}

    def wind_at(t: float) -> Optional[float]:
        v = None
        for w in winds:
            if w["t"] <= t:
                v = w["value"]
            else:
                break
        return v

    rows: List[dict] = []
    for s in starts:
        rows.append({"t": s["t"], "event": "start", "unit": s.get("type") or s.get("def"),
                     "def": s.get("def"), "unitID": s["unitID"],
                     "from_factory": s.get("from_factory"), "x": s.get("x"), "z": s.get("z")})
    for c in fins:
        st = start_by_id.get(c["unitID"])
        rows.append({"t": c["t"], "event": "finish", "unit": c.get("type") or c.get("def"),
                     "def": c.get("def"), "unitID": c["unitID"],
                     "took": round(c["t"] - st["t"], 2) if st else None})
    for ts in (snapshots or ()):
        if ts <= until_sec:
            rows.append({"t": float(ts), "event": "SNAPSHOT", "unit": "", "def": "",
                         "unitID": None})
    rows.sort(key=lambda r: (r["t"], 0 if r["event"] == "SNAPSHOT" else
                             (1 if r["event"] == "finish" else 2)))

    # walk forward attaching state and the live counts
    standing: Dict[str, int] = {}
    building: Dict[str, int] = {}
    for r in rows:
        if r["event"] == "start":
            u = r["unit"]
            building[u] = building.get(u, 0) + 1
        elif r["event"] == "finish":
            u = r["unit"]
            building[u] = max(0, building.get(u, 0) - 1)
            standing[u] = standing.get(u, 0) + 1
        st = _interp(econ, r["t"], ECON_KEYS)
        r["state"] = {k: (round(st[k], 2) if isinstance(st[k], (int, float)) else st[k])
                      for k in ECON_KEYS}
        r["state"]["measured"] = st["measured"]
        r["wind"] = wind_at(r["t"])
        r["standing"] = dict(standing)
        r["building"] = {k: v for k, v in building.items() if v}
        bp_a, bp_u = r["state"].get("bp_avail"), r["state"].get("bp_used")
        r["bp_util"] = (bp_u / bp_a) if (bp_a and bp_u is not None) else None
    return {"game": data.get("game", {}), "player": data.get("player"),
            "until_sec": until_sec, "rows": rows,
            "unfinished": [s for s in starts if s["unitID"] not in fin_by_id]}


def print_build_ledger(data: dict, until_sec: float = 480.0,
                       snapshots: Optional[Sequence[float]] = None,
                       include: Optional[Sequence[str]] = None,
                       compact: bool = True) -> dict:
    led = build_ledger(data, until_sec, snapshots, include)
    g = led["game"]
    p = led["player"] or {}
    print(f"BUILD LEDGER  {g.get('id')}  {g.get('map')}  "
          f"{p.get('name', '?')} team {g.get('team')}  first {until_sec / 60:.0f} min")
    print(f"  {'time':>7} {'ev':>6} {'unit':12} {'took':>6} {'M':>6} {'E':>7} {'M/s':>6} "
          f"{'E/s':>6} {'BP':>5} {'util':>5} {'wind':>5}  standing")
    for r in led["rows"]:
        s = r["state"]
        mm, ss = divmod(int(r["t"]), 60)
        ev = {"start": "start", "finish": "DONE", "SNAPSHOT": "--SNAP"}[r["event"]]
        took = f"{r['took']:.0f}s" if r.get("took") is not None else ""
        util = f"{r['bp_util'] * 100:.0f}%" if r.get("bp_util") is not None else ""
        stand = ("" if r["event"] == "start" and compact else
                 " ".join(f"{k}{v}" for k, v in sorted(r["standing"].items(),
                                                       key=lambda kv: -kv[1])[:7]))
        f = lambda v, w, d=0: (f"{v:{w}.{d}f}" if isinstance(v, (int, float)) else " " * w)
        mark = "" if s.get("measured") else ""
        print(f"  {mm:>4}:{ss:02d} {ev:>6} {r['unit'][:12]:12} {took:>6} "
              f"{f(s['metal'], 6)} {f(s['energy'], 7)} {f(s['m_inc'], 6, 2)} "
              f"{f(s['e_inc'], 6, 0)} {f(s['bp_avail'], 5, 0)} {util:>5} "
              f"{f(r['wind'], 5, 1)}  {stand}")
    if led["unfinished"]:
        print(f"\n  never finished inside the window: " +
              ", ".join(f"{u['type'] or u['def']}@{u['t']:.0f}s" for u in led["unfinished"][:10]))
    print(f"\n  state is MEASURED every 15 s and interpolated between; wind and counts are exact.")
    print(f"  a factory unit shows took=0s: the engine reports it once, as it pops, so its "
          f"start and finish are the same instant. Structure build times are real.")
    return led


def extract_recent(count: int = 6, matchup: Optional[str] = None, min_kb: int = 40,
                   until_sec: float = 480.0, today_only: bool = False,
                   player: Optional[str] = None, scan: int = 60) -> List[dict]:
    """Extract hard data for several recent games in one call.

    `min_kb` drops games too short to be worth reading — a demo under about 40 KB is
    a few seconds of play. Already-replayed games are reused, so re-running is cheap."""
    import datetime as _dt
    today = _dt.date.today().isoformat()
    out = []
    for f in _demo_files()[:scan]:
        if len(out) >= count:
            break
        full = os.path.join(DEMOS_DIR, f)
        st = os.stat(full)
        if st.st_size // 1024 < min_kb:
            continue
        lt = _dt.datetime.fromtimestamp(st.st_mtime)
        if today_only and lt.date().isoformat() != today:
            continue
        h = _demo_header(full)
        if matchup:
            wanted = [m.strip() for m in matchup.split(",")]
            if h.get("matchup") not in wanted:
                continue
        try:
            ref = _ref_for(f)
            d = extract_game(ref, player=player, until_sec=until_sec)
            out.append(d)
        except Exception as e:                                        # noqa: BLE001
            print(f"  ! {f[:30]}: {type(e).__name__}: {e}")
    return out


def load_game_data(ref: Union[int, str]) -> dict:
    """Read back a hard-data file: by path, by game id, or Nth most recent file."""
    if isinstance(ref, str) and os.path.exists(ref):
        with open(ref, encoding="utf-8") as fh:
            return json.load(fh)
    files = sorted(glob.glob(os.path.join(GAME_DATA_DIR, "*.json")), reverse=True)
    if isinstance(ref, int):
        if len(files) < ref:
            raise IndexError(f"only {len(files)} hard-data files")
        pick = files[ref - 1]
    else:
        hits = [f for f in files if str(ref) in os.path.basename(f)]
        if not hits:
            raise FileNotFoundError(f"no hard data matching {ref!r}")
        pick = hits[0]
    with open(pick, encoding="utf-8") as fh:
        return json.load(fh)


def list_game_data() -> List[dict]:
    out = []
    for f in sorted(glob.glob(os.path.join(GAME_DATA_DIR, "*.json")), reverse=True):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:                                            # noqa: BLE001
            continue
        g = d.get("game", {})
        out.append({"file": f, "id": g.get("id"), "played": g.get("played_local"),
                    "map": g.get("map"), "team": g.get("team"),
                    "completions": len(d.get("completions", [])),
                    "mexes": len(d.get("mexes", []))})
    return out


# ══════════════════════════════════════════════════════════════════════════
# LAYER 3 — ANALYSIS OVER HARD DATA  (functions to be defined with the user)
#
# Everything here takes a hard-data dict and returns numbers. It must never
# touch a replay, a demo or the engine: if an analysis needs a fact that is not
# in the hard data, the fix is to add that fact to layer 2 and re-extract, not
# to reach around the boundary.
#
# Register with @analysis("name"). `run_analyses(data)` runs them all.
# ══════════════════════════════════════════════════════════════════════════

ANALYSES: Dict[str, Callable[[dict], dict]] = {}


def analysis(name: str):
    def deco(fn):
        ANALYSES[name] = fn
        return fn
    return deco


@analysis("mex_timing")
def _an_mex_timing(data: dict) -> dict:
    """Extractor cadence: when each landed and how far it was walked."""
    mx = data.get("mexes", [])
    return {"count": len(mx),
            "times": [m["t"] for m in mx],
            "gaps": [round(b["t"] - a["t"], 1) for a, b in zip(mx, mx[1:])],
            "distances": [m.get("dist") for m in mx],
            "seconds_to_nth": {str(m["n"]): m["t"] for m in mx}}


@analysis("wind_profile")
def _an_wind_profile(data: dict) -> dict:
    """Wind at the engine's 15 s windows, and time spent each side of the two
    algebraic break-evens."""
    be = generator_breakevens()
    ws = data.get("wind", {}).get("samples", [])
    vals = [w["value"] for w in ws if w.get("value") is not None]
    if not vals:
        return {"note": "no wind samples"}
    below = sum(1 for v in vals if v < be["metal_breakeven"])
    mid = sum(1 for v in vals if be["metal_breakeven"] <= v < be["bp_breakeven"])
    above = sum(1 for v in vals if v >= be["bp_breakeven"])
    n = len(vals)
    return {"min": min(vals), "max": max(vals), "mean": round(sum(vals) / n, 2),
            "metal_breakeven": round(be["metal_breakeven"], 2),
            "bp_breakeven": round(be["bp_breakeven"], 2),
            "pct_below_metal_be": round(below / n * 100, 1),
            "pct_between": round(mid / n * 100, 1),
            "pct_above_bp_be": round(above / n * 100, 1),
            "windows_15s": data.get("wind", {}).get("windows_15s", [])}


@analysis("phases")
def _an_phases(data: dict) -> dict:
    """Segment the game into claiming / underpowered / spending / scaling from the
    measured 15 s series, and say which generator break-even applies in each."""
    econ = data.get("econ") or []
    if not econ:
        return {"note": "no econ samples; re-extract (extra_stat_update)"}
    mex_t = sorted(m["t"] for m in data.get("mexes", []))
    target = len(mex_t)
    calls, segs = [], []
    for s in econ:
        done = sum(1 for t in mex_t if t <= s["t"])
        ph = phase_of(s.get("m_inc") or 0, s.get("e_inc") or 0, s.get("bp_avail") or 0,
                      done, target)
        calls.append({"t": s["t"], "phase": ph, "mexes": done,
                      "m_inc": s.get("m_inc"), "e_inc": s.get("e_inc"),
                      "bp_avail": s.get("bp_avail"), "bp_used": s.get("bp_used")})
        if not segs or segs[-1]["phase"] != ph:
            segs.append({"phase": ph, "start": s["t"], "end": s["t"]})
        else:
            segs[-1]["end"] = s["t"]
    first = {}
    for sg in segs:
        first.setdefault(sg["phase"], sg["start"])
    total = {p: 0.0 for p in PHASES}
    for sg in segs:
        total[sg["phase"]] = total.get(sg["phase"], 0.0) + (sg["end"] - sg["start"])
    return {"segments": segs, "first_entered": first, "seconds_in": total,
            "fungible_from": first.get("scaling"),
            "breakeven_by_phase": {p: applicable_breakeven(p) for p in PHASES},
            "samples": calls}


def run_analyses(data: dict, names: Optional[Sequence[str]] = None) -> dict:
    return {n: ANALYSES[n](data) for n in (names or ANALYSES) if n in ANALYSES}


# ══════════════════════════════════════════════════════════════════════════
# BUILD PATHS — two (or more) complete strategies, each run on its own
#
# A build path is NOT a policy with a parameter swapped. It is a whole strategy,
# written out, that stands or falls on its own logic: its own order, its own
# energy plan, its own build-power plan, its own walking. Two paths are run
# SEPARATELY, each producing a full trace, and only afterwards are they laid side
# by side at whatever breakpoints turn out to matter.
#
# That ordering is deliberate. Deciding the comparison metric first, then running
# to it, is how a policy's own assumptions get reported as findings. Here the run
# records everything and commits to nothing; `Breakpoint`s are evaluated against a
# finished trace, so a new question can be asked of an old run without re-running
# and without the run having known the question.
#
#   BuildStep  one thing to build, and the walk to reach where it goes
#   BuildPath  a named, self-contained strategy (a queue, or a rule, or both)
#   PathTrace  everything that happened: full series + events + bounds proof
#   Breakpoint a named question asked of a finished trace
#
# Add a path by putting it in PATHS. Add a question by putting it in BREAKPOINTS.
# Neither requires touching the runner.
# ══════════════════════════════════════════════════════════════════════════

# Walk time, in seconds, from spawn to the Nth metal spot. These are the real All
# That Glitters figures for a standard position: three spots inside build range,
# then a genuine walk out to four more. `mex_walk_from_map` derives them for any
# map and spawn.
DEFAULT_MEX_WALK_SEC = [0.0, 0.0, 2.1, 15.6, 19.3, 20.2, 26.8]

# Metal income one point of build power can absorb, from the calibrated eco rule
# ("need more BP when incM > poolBP * 0.0266").
BP_ABSORB_PER_POINT = 0.0266


@dataclass
class BuildStep:
    """One entry in a build path. `walk_sec` is travel to the site before work
    starts, which is how a forward extractor differs from one under your feet."""
    unit: str
    walk_sec: float = 0.0
    note: str = ""


@dataclass
class BuildPath:
    """A complete strategy. Supply `steps` for an explicit order, or `rule` for a
    reactive one, or both — the rule is consulted only once the queue runs dry,
    which is the usual shape: a scripted opening into an adaptive mid-game.

    A rule is `fn(ctx) -> unit name or None`, where ctx exposes the live state.
    Returning None means "nothing worth starting", and the builder idles."""
    name: str
    steps: List[BuildStep] = field(default_factory=list)
    rule: Optional[Callable] = None
    wind: Optional[float] = None
    crew_start: Sequence[str] = ("Commander",)
    start_metal: Optional[float] = None
    start_energy: Optional[float] = None
    start_sec: float = 3.0
    description: str = ""

    def queue(self) -> List[BuildStep]:
        return [BuildStep(s.unit, s.walk_sec, s.note) for s in self.steps]


@dataclass
class PathTrace:
    """A finished run. `series` is sampled state over time; `events` is every
    completion. Breakpoints are computed from these after the fact."""
    name: str
    path: Optional[BuildPath] = None
    series: List[dict] = field(default_factory=list)
    events: List[dict] = field(default_factory=list)
    min_metal: float = 1e18
    min_energy: float = 1e18
    bounds_ok: bool = True
    idle_bp_sec: float = 0.0          # build-power-seconds that sat doing nothing
    stall_sec: float = 0.0            # seconds where a build was throttled by the bank
    stall_metal_sec: float = 0.0      # ...of which, starved of METAL
    stall_energy_sec: float = 0.0     # ...of which, starved of ENERGY
    spent_m: float = 0.0              # metal actually paid into builds
    spent_e: float = 0.0
    illegal_blocked: int = 0          # times a job waited for a legal builder
    horizon: float = 0.0

    # ---- reading a finished trace ----
    def at(self, sec: float) -> dict:
        """State at (or just before) `sec`."""
        best = None
        for s in self.series:
            if s["t"] <= sec + 1e-9:
                best = s
            else:
                break
        return best or (self.series[0] if self.series else {})

    def when(self, test: Callable[[dict], bool]) -> Optional[float]:
        """First sampled moment the test passes, or None."""
        for s in self.series:
            try:
                if test(s):
                    return s["t"]
            except Exception:                                   # noqa: BLE001
                continue
        return None

    def nth(self, unit: str, n: int = 1) -> Optional[float]:
        """When the nth `unit` finished."""
        hits = [e["t"] for e in self.events if e["unit"] == unit]
        return hits[n - 1] if len(hits) >= n else None

    def count(self, unit: str, by_sec: Optional[float] = None) -> int:
        return sum(1 for e in self.events
                   if e["unit"] == unit and (by_sec is None or e["t"] <= by_sec))

    def built(self, by_sec: Optional[float] = None) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for e in self.events:
            if by_sec is None or e["t"] <= by_sec:
                out[e["unit"]] = out.get(e["unit"], 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def run_path(path: BuildPath, horizon: float = 300.0, dt: float = 0.25,
             sample_sec: float = 1.0, wind_source: Optional[object] = None) -> PathTrace:
    """Run ONE build path on its own and record everything.

    Resources are a shared pool. Work draws metal and energy in proportion to
    progress; when the pool cannot pay, every active build slows by the same
    factor. A bank going negative raises — that would mean the run spent what it
    did not have, and nothing downstream of it would be worth reading."""
    w = path.wind if path.wind is not None else DEFAULT_WIND
    env = Environment(time=path.start_sec, verbose=False, wind=w)
    if path.start_metal is not None:
        env.metal = path.start_metal
    if path.start_energy is not None:
        env.energy = path.start_energy
    tr = PathTrace(name=path.name, path=path, horizon=horizon)

    crew = []
    for unit in path.crew_start:
        t = OBJECTS[unit]
        crew.append({"bp": t.bp_income, "job": None, "walk": 0.0, "factory": bool(t.factory)})
        if unit != "Commander":
            env.builders.append(unit)

    queue = path.queue()
    ctx = {"env": env, "trace": tr, "crew": crew}

    def peek_unit() -> Optional[BuildStep]:
        """The next job WITHOUT consuming it, so an illegal builder can decline and
        leave it for one that can actually make it."""
        if queue:
            return queue[0]
        if path.rule:
            ctx["built"] = tr.built()
            ctx["total_bp"] = sum(b["bp"] for b in crew)
            got = path.rule(ctx)
            if got:
                return got if isinstance(got, BuildStep) else BuildStep(got)
        return None

    def take_unit() -> Optional[BuildStep]:
        if queue:
            return queue.pop(0)
        return peek_unit()

    next_sample = env.time
    while env.time < horizon:
        if wind_source is not None:
            env.wind = wind_source.at(env.time)
        for b in crew:
            if b["job"] is not None:
                continue
            st = peek_unit()
            if st is None:
                continue
            if not builder_can_make(b["factory"], st.unit):
                tr.illegal_blocked += 1        # the job waits for a builder that can
                continue
            st = take_unit()
            t = OBJECTS[st.unit]
            b["job"] = {"unit": st.unit, "work": t.bp_cost, "metal": t.metal_cost,
                        "energy": t.energy_cost, "done": 0.0, "note": st.note}
            b["walk"] = st.walk_sec

        demand_m = demand_e = 0.0
        active = []
        idle_bp = 0.0
        for b in crew:
            if b["job"] is None:
                idle_bp += b["bp"]
                continue
            if b["walk"] > 0:
                idle_bp += b["bp"]
                continue
            j = b["job"]
            frac = min(1.0 - j["done"], (b["bp"] * dt) / max(j["work"], 1e-9))
            if frac <= 0:
                continue
            active.append((b, frac))
            demand_m += j["metal"] * frac
            demand_e += j["energy"] * frac
        tr.idle_bp_sec += idle_bp * dt

        avail_m = env.metal + env.income_m() * dt
        avail_e = env.energy + env.income_e() * dt
        scale = 1.0
        if demand_m > avail_m and demand_m > 0:
            scale = min(scale, avail_m / demand_m)
        if demand_e > avail_e and demand_e > 0:
            scale = min(scale, avail_e / demand_e)
        if scale < 1.0 - 1e-9 and active:
            tr.stall_sec += dt
            # which resource actually bound it: opposite problems, not one column
            m_short = demand_m > avail_m + 1e-9
            e_short = demand_e > avail_e + 1e-9
            if m_short and (not e_short or (avail_m / max(demand_m, 1e-9))
                            <= (avail_e / max(demand_e, 1e-9))):
                tr.stall_metal_sec += dt
            elif e_short:
                tr.stall_energy_sec += dt

        env.advance(dt)
        env.metal -= demand_m * scale
        env.energy -= demand_e * scale
        tr.spent_m += demand_m * scale
        tr.spent_e += demand_e * scale
        tr.min_metal = min(tr.min_metal, env.metal)
        tr.min_energy = min(tr.min_energy, env.energy)
        if env.metal < -1e-6 or env.energy < -1e-6:
            raise AssertionError(f"{path.name}: bounds violated at t={env.time:.2f} "
                                 f"(metal {env.metal:.3f}, energy {env.energy:.3f})")
        env.metal, env.energy = max(0.0, env.metal), max(0.0, env.energy)

        for b, frac in active:
            j = b["job"]
            j["done"] += frac * scale
            if j["done"] >= 1.0 - 1e-9:
                unit = j["unit"]
                env.apply_completion(unit)
                t = OBJECTS[unit]
                if t.is_builder and t.bp_income:
                    crew.append({"bp": t.bp_income, "job": None, "walk": 0.0,
                                 "factory": bool(t.factory)})
                tr.events.append({"t": round(env.time, 2), "unit": unit, "note": j["note"]})
                b["job"] = None
        for b in crew:
            if b["walk"] > 0:
                b["walk"] = max(0.0, b["walk"] - dt)

        if env.time >= next_sample:
            total_bp = sum(b["bp"] for b in crew)
            uv = usable_value_per_s(env.income_m(), env.income_e(), total_bp)
            tr.series.append({
                "t": round(env.time, 2), "metal": round(env.metal, 1),
                "energy": round(env.energy, 1), "m_inc": round(env.income_m(), 3),
                "e_inc": round(env.income_e(), 2), "bp": total_bp,
                "crew": len(crew), "gathered_m": round(env.gathered_m, 1),
                "gathered_e": round(env.gathered_e, 1),
                "spilled_e": round(env.spilled_e, 1), "spilled_m": round(env.spilled_m, 1),
                "kept_e": round(env.gathered_e - env.spilled_e, 1),
                "spent_m": round(tr.spent_m, 1), "spent_e": round(tr.spent_e, 1),
                "net_m": round(env.gathered_m - tr.spent_m, 1),
                "e_cap": round(uv["cap"], 1), "e_wasted": round(uv["wasted"], 1),
                "usable_v_s": round(uv["value_per_s"], 3),
                "built": tr.built(env.time), "queue_left": len(queue),
                "idle_bp_sec": round(tr.idle_bp_sec, 1), "stall_sec": round(tr.stall_sec, 2),
            })
            next_sample += sample_sec
    tr.bounds_ok = tr.min_metal >= -1e-6 and tr.min_energy >= -1e-6
    return tr


# ── A real game, as a PathTrace ────────────────────────────────────────────
# A replay is just another build path — one a person ran. Reconstructing it into
# the same PathTrace shape means every breakpoint, analytical or milestone, reads
# a real game and a simulated one identically, and the two can be laid side by
# side without special-casing either.
#
# What is reconstructed: completions come straight from `unit_finished`, and the
# income series is rebuilt by accumulating each finished unit's contribution, with
# the REAL recorded wind driving the turbines. What is NOT reconstructed: the
# banks, because a replay does not record them per second — so `metal`/`energy`
# read 0 and any breakpoint touching a bank must be marked as simulation-only.

def trace_from_replay(actions_path: str, team: Optional[int] = None,
                      horizon: float = 900.0, sample_sec: float = 1.0,
                      name: Optional[str] = None) -> PathTrace:
    """Rebuild a played game into a PathTrace: real completions, real wind."""
    defs: Dict[int, dict] = {}
    finished: List[Tuple[float, str, Optional[int]]] = []
    wind: List[Tuple[float, float]] = []
    for e in read_actions(actions_path, ("unit_def", "unit_finished", "wind_update")):
        a = e.get("action")
        if a == "unit_def":
            defs[e["defID"]] = e
        elif a == "wind_update":
            wind.append((e["frame"] / GAME_FPS, float(e.get("value") or 0.0)))
        elif a == "unit_finished":
            n = e.get("defName") or defs.get(e.get("defID"), {}).get("defName")
            if n and (team is None or e.get("teamID") == team):
                finished.append((e["frame"] / GAME_FPS, n, e.get("teamID")))
    finished.sort()
    wind.sort()
    if team is None and finished:
        team = finished[0][2]
        finished = [f for f in finished if f[2] == team]

    tr = PathTrace(name=name or os.path.basename(os.path.dirname(actions_path)),
                   horizon=horizon)
    reg = ALIASES

    def wind_at(t: float) -> float:
        lo = 0.0
        for ts, v in wind:
            if ts > t:
                break
            lo = v
        return lo

    # walk the completions forward, accumulating income exactly as the sim does
    m_inc = OBJECTS["Commander"].metal_income
    e_base = OBJECTS["Commander"].energy_income
    bp = OBJECTS["Commander"].bp_income
    n_wind = 0
    idx = 0
    t = 0.0
    gathered_m = gathered_e = 0.0
    while t <= horizon:
        while idx < len(finished) and finished[idx][0] <= t:
            _, dn, _ = finished[idx]
            idx += 1
            key = reg.get(dn)
            if key is None:
                continue
            o = OBJECTS[key]
            if o.wind_powered:
                n_wind += 1
            else:
                e_base += o.energy_income
            m_inc += o.metal_income
            bp += o.bp_income
            tr.events.append({"t": round(t, 2), "unit": key, "note": dn})
        e_inc = e_base + n_wind * wind_at(t)
        gathered_m += m_inc * sample_sec
        gathered_e += e_inc * sample_sec
        uv = usable_value_per_s(m_inc, e_inc, bp)
        tr.series.append({"t": round(t, 2), "metal": 0.0, "energy": 0.0,
                          "m_inc": round(m_inc, 3), "e_inc": round(e_inc, 2), "bp": bp,
                          "crew": 0, "gathered_m": round(gathered_m, 1),
                          "gathered_e": round(gathered_e, 1), "wind": round(wind_at(t), 2),
                          "n_wind": n_wind, "e_cap": round(uv["cap"], 1),
                          "e_wasted": round(uv["wasted"], 1),
                          "usable_v_s": round(uv["value_per_s"], 3),
                          "built": tr.built(t), "queue_left": 0,
                          "idle_bp_sec": 0.0, "stall_sec": 0.0})
        t += sample_sec
    tr.min_metal = tr.min_energy = 0.0
    tr.bounds_ok = True      # nothing was simulated, so nothing could be overspent
    return tr


def path_from_replay(actions_path: str, name: str, team: Optional[int] = None,
                     map_name: str = "All That Glitters",
                     until_sec: float = 600.0) -> BuildPath:
    """Turn a played game into a runnable BuildPath: the same order, with each
    extractor carrying the walk implied by how far out its spot actually was."""
    tl = build_timeline(actions_path, team=team, until_sec=until_sec, map_name=map_name)
    teams = tl["teams"]
    t0 = team if team in teams else (list(teams)[0] if teams else None)
    if t0 is None:
        raise ValueError("no teams in that replay")
    r = teams[t0]
    mex_walk = {m["n"]: m["dist"] for m in r["mexes"]}
    order = sorted((s, k) for k, vs in r["times"].items() for s in vs)
    KIND_TO_UNIT = {"mex": "Mex", "solar": "Solar", "wind": "Wind", "worker": "BotWorker",
                    "factory": "BotFactory", "converter": "EConverter",
                    "estorage": "EStorage", "nano": "ConTurret", "advsolar": "AdvSolar",
                    "t2mex": "AMex"}
    steps, n_mex = [], 0
    for sec, kind in order:
        unit = KIND_TO_UNIT.get(kind)
        if not unit:
            continue
        walk = 0.0
        if unit == "Mex":
            n_mex += 1
            d = mex_walk.get(n_mex, 0)
            walk = walk_time(float(d), "con_bot")
        steps.append(BuildStep(unit, walk, f"replay {sec:.0f}s"))
    return BuildPath(name=name, steps=steps,
                     description=f"observed order from {os.path.basename(os.path.dirname(actions_path))}")


# ── Breakpoints: questions asked of a finished trace ──────────────────────
# Each is `fn(trace) -> seconds or None`. Add one here and every path answers it.

# ANALYTICAL breakpoints: the moments a decision rule CHANGES SIGN. Not "when did
# X happen" but "when did the correct answer flip". Each returns the first second
# the condition holds, so it can be read off a real game or a simulated one.
#
# The three generator break-evens come from generator_breakevens() and are pure
# algebra, so crossing one is a genuine change of regime rather than a threshold
# somebody picked.

def _be() -> dict:
    return generator_breakevens()


def _crossed(tr: PathTrace, up: Callable[[dict], bool], sustain: float = 10.0) -> Optional[float]:
    """First moment a condition becomes true AND stays true for `sustain` seconds.

    A bare "first time above" fires on a single noisy sample. Wind moves every
    tick, so a crossing only counts as a change of regime if it holds."""
    run_from = None
    for s in tr.series:
        if up(s):
            if run_from is None:
                run_from = s["t"]
            elif s["t"] - run_from >= sustain:
                return run_from
        else:
            run_from = None
    return None


def _fell_after(tr: PathTrace, up: Callable[[dict], bool], sustain: float = 10.0) -> Optional[float]:
    """First sustained drop BELOW, but only after a sustained period above."""
    start = _crossed(tr, up, sustain)
    if start is None:
        return None
    run_from = None
    for s in tr.series:
        if s["t"] <= start:
            continue
        if not up(s):
            if run_from is None:
                run_from = s["t"]
            elif s["t"] - run_from >= sustain:
                return run_from
        else:
            run_from = None
    return None


ANALYTICAL: Dict[str, Callable[[PathTrace], Optional[float]]] = {
    # wind crosses the price at which it becomes the cheaper economy in METAL
    "wind > metal BE":   lambda tr: _crossed(tr, lambda s: s.get("wind", 0) > _be()["metal_breakeven"]),
    # wind crosses the price at which it returns more energy per BUILD POWER spent
    "wind > BP BE":      lambda tr: _crossed(tr, lambda s: s.get("wind", 0) > _be()["bp_breakeven"]),
    # and back below it again, which is when a turbine plan stops paying
    "wind back < BP BE": lambda tr: _fell_after(tr, lambda s: s.get("wind", 0) > _be()["bp_breakeven"]),
    # metal arrives faster than the build power can absorb: buy BP, not economy
    "metal outruns BP":  lambda tr: tr.when(lambda s: s["m_inc"] > s["bp"] * BP_ABSORB_PER_POINT),
    # energy income passes what the build power can physically consume: overflow
    "energy overflows":  lambda tr: tr.when(lambda s: s["e_wasted"] > 1.0),
    # the economy is worth more in energy terms than in metal terms
    "energy > metal":    lambda tr: tr.when(lambda s: s["e_inc"] / ENERGY_PER_METAL > s["m_inc"]),
}

BREAKPOINTS: Dict[str, Callable[[PathTrace], Optional[float]]] = {
    "3rd mex":        lambda tr: tr.nth("Mex", 3),
    "5th mex":        lambda tr: tr.nth("Mex", 5),
    "7th mex":        lambda tr: tr.nth("Mex", 7),
    "first factory":  lambda tr: tr.nth("BotFactory", 1),
    "bank hits 0 M":  lambda tr: tr.when(lambda s: s["metal"] <= 1.0),
    "e_inc >= 100":   lambda tr: tr.when(lambda s: s["e_inc"] >= 100),
    "e_inc >= 200":   lambda tr: tr.when(lambda s: s["e_inc"] >= 200),
    "BP >= 600":      lambda tr: tr.when(lambda s: s["bp"] >= 600),
    "m_inc >= 10":    lambda tr: tr.when(lambda s: s["m_inc"] >= 10),
    "m_inc >= 14":    lambda tr: tr.when(lambda s: s["m_inc"] >= 14),
    "energy wasted":  lambda tr: tr.when(lambda s: s["e_wasted"] > 5),
}


def breakpoint_table(traces: Sequence[PathTrace],
                     names: Optional[Sequence[str]] = None,
                     registry: Optional[Dict[str, Callable]] = None) -> dict:
    """When each path reached each breakpoint. Blank means never."""
    registry = registry if registry is not None else BREAKPOINTS
    names = list(names or registry)
    rows = {}
    w = max(14, max(len(t.name) for t in traces) + 2)
    print(f"  {'breakpoint':16}" + "".join(f"{t.name:>{w}}" for t in traces) + f"{'delta':>10}")
    for n in names:
        fn = registry.get(n)
        if not fn:
            continue
        vals = [fn(t) for t in traces]
        rows[n] = vals
        cells = "".join(f"{(f'{v:.1f}s' if v is not None else '-'):>{w}}" for v in vals)
        d = ""
        if len(vals) == 2 and vals[0] is not None and vals[1] is not None:
            d = f"{vals[1] - vals[0]:+.1f}s"
        print(f"  {n:16}" + cells + f"{d:>10}")
    return rows


def path_summary(tr: PathTrace, at: Optional[Sequence[float]] = (60, 120, 180, 240, 300)) -> None:
    s_end = tr.series[-1] if tr.series else {}
    print(f"\n{tr.name}   bounds {'ok' if tr.bounds_ok else 'VIOLATED'} "
          f"(min bank {tr.min_metal:.1f}m / {tr.min_energy:.1f}e)   "
          f"stalled {tr.stall_sec:.1f}s   idle BP {tr.idle_bp_sec:.0f} BP-s")
    if tr.path and tr.path.description:
        print(f"  {tr.path.description}")
    print(f"  {'t':>5} {'mex':>4} {'M/s':>7} {'E/s':>7} {'BP':>6} {'bankM':>7} "
          f"{'madeM':>8} {'Ewaste':>7} {'usable v/s':>10}")
    for t in (at or ()):
        s = tr.at(t)
        if not s:
            continue
        print(f"  {t:5.0f} {s['built'].get('Mex', 0):4} {s['m_inc']:7.2f} {s['e_inc']:7.1f} "
              f"{s['bp']:6.0f} {s['metal']:7.0f} {s['gathered_m']:8.0f} {s['e_wasted']:7.0f} "
              f"{s['usable_v_s']:10.2f}")
    print(f"  built: " + ", ".join(f"{k} x{v}" for k, v in tr.built().items()))


# ── PATHS: add a complete strategy here. These two are PLACEHOLDERS ────────
# They exist to prove the scaffolding runs end to end. Replace the steps with
# the real orders — that is the part that has to come from play, not from me.

def _mex_walks(n: int = 7) -> List[float]:
    return (DEFAULT_MEX_WALK_SEC + [DEFAULT_MEX_WALK_SEC[-1]] * n)[:n]


def _placeholder_path(name: str, generator: str, gen_every: int, desc: str) -> BuildPath:
    walks = _mex_walks(7)
    steps: List[BuildStep] = []
    for i in range(7):
        steps.append(BuildStep("Mex", walks[i], f"mex {i + 1}"))
        if (i + 1) % gen_every == 0:
            steps.append(BuildStep(generator, 0.0, "energy"))
        if i == 2:
            steps.append(BuildStep("BotFactory", 0.0, "build power"))
    return BuildPath(name=name, steps=steps, description=desc,
                     rule=lambda ctx: generator)


# ── Registered paths on disk ───────────────────────────────────────────────
# A path extracted from a replay has to outlive the temp directory the replay was
# unpacked into, so registering one writes it to bar-calc/paths/<name>.json and
# every later run loads it from there. That is what makes a played game a
# first-class path rather than a one-off reading.

PATHS_DIR = os.path.join(HERE, "paths")


def save_path(path: BuildPath, meta: Optional[dict] = None) -> str:
    os.makedirs(PATHS_DIR, exist_ok=True)
    f = os.path.join(PATHS_DIR, re.sub(r"[^\w.-]", "_", path.name) + ".json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump({"name": path.name, "description": path.description,
                   "wind": path.wind, "start_sec": path.start_sec,
                   "crew_start": list(path.crew_start), "meta": meta or {},
                   "steps": [{"unit": s.unit, "walk_sec": round(s.walk_sec, 2), "note": s.note}
                             for s in path.steps]}, fh, indent=1)
    return f


def load_path(file: str) -> BuildPath:
    with open(file, encoding="utf-8") as fh:
        d = json.load(fh)
    return BuildPath(name=d["name"], description=d.get("description", ""),
                     wind=d.get("wind"), start_sec=d.get("start_sec", 3.0),
                     crew_start=tuple(d.get("crew_start") or ("Commander",)),
                     steps=[BuildStep(s["unit"], s.get("walk_sec", 0.0), s.get("note", ""))
                            for s in d.get("steps", [])])


def load_registered_paths() -> Dict[str, BuildPath]:
    out = {}
    for f in sorted(glob.glob(os.path.join(PATHS_DIR, "*.json"))):
        try:
            p = load_path(f)
            out[p.name] = p
        except Exception as e:                                      # noqa: BLE001
            print(f"  (skipped {os.path.basename(f)}: {e})")
    return out


def register_replay(actions_path: str, name: str, team: Optional[int] = None,
                    map_name: str = "All That Glitters") -> BuildPath:
    """Extract a played game into a BuildPath and persist it under bar-calc/paths/."""
    p = path_from_replay(actions_path, name, team=team, map_name=map_name)
    tr = trace_from_replay(actions_path, team=team, name=name)
    meta = {"source": os.path.basename(os.path.dirname(actions_path)),
            "mex_sec": [tr.nth("Mex", i) for i in range(1, 8)],
            "analytical": {k: fn(tr) for k, fn in ANALYTICAL.items()},
            "built": tr.built()}
    f = save_path(p, meta)
    print(f"registered {name} -> {os.path.relpath(f, ED.REPO_ROOT)}  ({len(p.steps)} steps)")
    return p


PATHS: Dict[str, BuildPath] = {
    "placeholder_solar": _placeholder_path(
        "placeholder_solar", "Solar", 2,
        "PLACEHOLDER — not a real build. Proves the runner works."),
    "placeholder_wind": _placeholder_path(
        "placeholder_wind", "Wind", 1,
        "PLACEHOLDER — not a real build. Proves the runner works."),
}


PATHS.update(load_registered_paths())


def run_paths(names: Sequence[str], horizon: float = 300.0,
              wind: Optional[float] = None, verbose: bool = True) -> List[PathTrace]:
    """Run each named path SEPARATELY, then show the breakpoints side by side."""
    traces = []
    for n in names:
        p = PATHS.get(n)
        if p is None:
            raise KeyError(f"unknown path {n!r}; known: {list(PATHS)}")
        if wind is not None:
            p = BuildPath(**{**vars(p), "wind": wind})
        traces.append(run_path(p, horizon=horizon))
    if verbose:
        for tr in traces:
            path_summary(tr)
        print(f"\nBREAKPOINTS")
        breakpoint_table(traces)
    return traces


# ──────────────────────────────────────────────────────────────────────────
# Resource rate algebra — the four quantities together
#
# Build work is denominated in BP-seconds, so a build running at B build power
# finishes in W/B seconds and therefore consumes its metal and its energy at
# FIXED RATES:
#
#     dM/dt = Mc * B / W        dE/dt = Ec * B / W
#
# That is the bridge between the four resources. It says how much energy income
# you must already have to keep B build power busy on a given object, and it is
# the number every "solar or wind" argument is really about.
# ──────────────────────────────────────────────────────────────────────────

def drain_rates(name: str, bp: float) -> dict:
    """Metal and energy per second consumed while building `name` at `bp` build
    power, and how long it takes. Nothing here depends on the current bank."""
    t = OBJECTS[name]
    if t.bp_cost <= 0:
        return {"seconds": 0.0, "m_per_s": 0.0, "e_per_s": 0.0}
    return {"seconds": t.bp_cost / bp if bp else float("inf"),
            "m_per_s": t.metal_cost * bp / t.bp_cost,
            "e_per_s": t.energy_cost * bp / t.bp_cost}


def sustainable_bp(name: str, m_inc: float, e_inc: float) -> dict:
    """How much build power your INCOME can keep busy on `name` indefinitely.

    Anything above this is drawing down the bank and will stall when it empties."""
    t = OBJECTS[name]
    by_m = m_inc * t.bp_cost / t.metal_cost if t.metal_cost > 0 else float("inf")
    by_e = e_inc * t.bp_cost / t.energy_cost if t.energy_cost > 0 else float("inf")
    return {"by_metal": by_m, "by_energy": by_e, "bp": min(by_m, by_e),
            "binding": "metal" if by_m < by_e else "energy"}


def bank_runway(name: str, bp: float, m_bank: float, e_bank: float,
                m_inc: float, e_inc: float) -> dict:
    """Seconds you can keep `bp` busy on `name` before a bank empties, and how many
    copies that buys. This is what the 1000/1000 opening bank actually funds."""
    r = drain_rates(name, bp)
    m_gap, e_gap = r["m_per_s"] - m_inc, r["e_per_s"] - e_inc
    t_m = m_bank / m_gap if m_gap > 0 else float("inf")
    t_e = e_bank / e_gap if e_gap > 0 else float("inf")
    t = min(t_m, t_e)
    return {"seconds": t, "count": t / r["seconds"] if r["seconds"] else 0.0,
            "binding": "metal" if t_m < t_e else ("energy" if t_e < t_m else "neither"),
            "m_gap": m_gap, "e_gap": e_gap}


# ══════════════════════════════════════════════════════════════════════════
# HOW LONG WILL THE NEXT ONE TAKE, FROM HERE
#
# `bp_cost / bp` is the nominal answer and it is only right while the economy can
# pay at that pace. The real duration is piecewise: full pace while a bank still
# has something in it, then whatever income alone will feed, and the two banks do
# not run out together. So this walks the phases analytically — at most two
# bank-emptying events, no fixed timestep — and reports how much of the duration
# was stall and WHICH resource caused it.
#
# `affordable` is the gate the path search needs: the bank plus income covers the
# whole build at nominal pace, with no stall. A con turret you cannot pay for is
# not a move, however saturated your build power is.
# ══════════════════════════════════════════════════════════════════════════

def time_to_build(state: "EcoState", unit: str, bp: Optional[float] = None,
                  tol: float = 1e-9) -> dict:
    """Seconds for the NEXT `unit` from this exact position, not the nominal time."""
    t = OBJECTS[unit]
    b = bp if bp is not None else state.bp
    if t.bp_cost <= 0:
        return {"seconds": 0.0, "nominal": 0.0, "stall": 0.0, "bound": "none",
                "eff_bp": b, "affordable": True, "payable": True, "phases": []}
    if b <= 0:
        return {"seconds": float("inf"), "nominal": float("inf"), "stall": float("inf"),
                "bound": "build power", "eff_bp": 0.0, "affordable": False,
                "payable": False, "phases": []}
    W, T0 = t.bp_cost, t.bp_cost / b
    m_bank, e_bank = max(0.0, state.metal), max(0.0, state.energy)
    m_inc, e_inc = state.m_inc, state.e_inc
    work, el, stall, bound = 0.0, 0.0, 0.0, "none"
    phases: List[dict] = []
    for _ in range(6):
        # the build power this position can support right now: a bank with something
        # in it supports the full rate, an empty one only what its income feeds
        cap, capped_by = b, None
        if m_bank <= tol and t.metal_cost > 0:
            c = m_inc * W / t.metal_cost
            if c < cap:
                cap, capped_by = c, "metal"
        if e_bank <= tol and t.energy_cost > 0:
            c = e_inc * W / t.energy_cost
            if c < cap:
                cap, capped_by = c, "energy"
        if cap <= tol:
            return {"seconds": float("inf"), "nominal": T0, "stall": float("inf"),
                    "bound": capped_by or "none", "eff_bp": 0.0, "affordable": False,
                    "payable": False, "phases": phases}
        if capped_by and bound == "none":
            bound = capped_by
        t_done = (W - work) / cap
        # which bank empties first at this pace
        t_next, who = float("inf"), None
        if m_bank > tol and t.metal_cost > 0:
            net = t.metal_cost * cap / W - m_inc
            if net > tol and m_bank / net < t_next:
                t_next, who = m_bank / net, "metal"
        if e_bank > tol and t.energy_cost > 0:
            net = t.energy_cost * cap / W - e_inc
            if net > tol and e_bank / net < t_next:
                t_next, who = e_bank / net, "energy"
        step = min(t_done, t_next)
        work += cap * step
        m_bank = max(0.0, min(m_bank + (m_inc - t.metal_cost * cap / W) * step, state.m_cap))
        e_bank = max(0.0, min(e_bank + (e_inc - t.energy_cost * cap / W) * step, state.e_cap))
        el += step
        if cap < b - 1e-6:
            stall += step
        phases.append({"sec": round(step, 4), "bp": round(cap, 3), "empties": who})
        if work >= W - 1e-7:
            break
    return {"seconds": el, "nominal": T0, "stall": stall, "bound": bound,
            "eff_bp": min(b, sustainable_bp(unit, m_inc, e_inc)["bp"]),
            "affordable": stall <= 1e-6, "payable": True, "phases": phases}


def _sim_one_build(state: "EcoState", unit: str, bp: Optional[float] = None,
                   dt: float = 0.02) -> dict:
    """Reference simulation of ONE build, same inner loop as `_project_row`.

    Exists only so `time_to_build`'s closed form can be checked against it."""
    t = OBJECTS[unit]
    b = bp if bp is not None else state.bp
    metal, energy = state.metal, state.energy
    m_inc, e_inc = state.m_inc, state.e_inc
    prog, el, stalled = 0.0, 0.0, 0.0
    guard = int(6000.0 / dt)
    while prog < 1.0 - 1e-9 and guard > 0:
        guard -= 1
        need_m = t.metal_cost * b / t.bp_cost * dt
        need_e = t.energy_cost * b / t.bp_cost * dt
        avail_m, avail_e = metal + m_inc * dt, energy + e_inc * dt
        scale = 1.0
        if need_m > 0:
            scale = min(scale, avail_m / need_m)
        if need_e > 0:
            scale = min(scale, avail_e / need_e)
        scale = max(0.0, min(1.0, scale))
        if scale < 0.999:
            stalled += dt
        prog += scale * b * dt / t.bp_cost
        metal = min(metal + m_inc * dt - need_m * scale, state.m_cap)
        energy = min(energy + e_inc * dt - need_e * scale, state.e_cap)
        el += dt
    return {"seconds": el, "stall": stalled, "converged": prog >= 1.0 - 1e-9}


def validate_time_to_build(units: Optional[Sequence[str]] = None, dt: float = 0.02,
                           verbose: bool = True) -> dict:
    """The closed form must reproduce the simulation. Run across every regime.

    This is the one number in the chart that no other test would catch, because a
    plausible-looking duration is indistinguishable from a correct one by eye."""
    units = list(units or ("Mex", "Solar", "Wind", "AdvSolar", "BotWorker",
                           "ConTurret", "EConverter", "EStorage"))
    cases = [
        ("opening bank", dict(metal=1000, energy=1000, m_inc=0.0, e_inc=0.0, bp=300)),
        ("bank dry", dict(metal=0, energy=0, m_inc=7.5, e_inc=70, bp=530)),
        ("metal dry", dict(metal=0, energy=5000, m_inc=2.0, e_inc=400, bp=800)),
        ("energy dry", dict(metal=900, energy=0, m_inc=12.0, e_inc=25, bp=600)),
        ("energy starved", dict(metal=400, energy=120, m_inc=9.0, e_inc=18, bp=450)),
        ("overflowing", dict(metal=20, energy=9000, m_inc=15.7, e_inc=760, bp=2140)),
        ("rich and idle", dict(metal=3000, energy=15000, m_inc=22.0, e_inc=900, bp=1200)),
        ("thin everything", dict(metal=5, energy=5, m_inc=0.4, e_inc=3, bp=300)),
    ]
    rows, worst = [], 0.0
    for label, kw in cases:
        st = EcoState(t=0.0, m_cap=max(1000.0, kw["metal"]),
                      e_cap=max(1000.0, kw["energy"]), **kw)
        for u in units:
            a = time_to_build(st, u)
            r = _sim_one_build(st, u, dt=dt)
            if not r["converged"] or a["seconds"] == float("inf"):
                rows.append({"case": label, "unit": u, "closed": a["seconds"],
                             "sim": None, "err": None, "bound": a["bound"]})
                continue
            err = abs(a["seconds"] - r["seconds"])
            worst = max(worst, err)
            rows.append({"case": label, "unit": u, "closed": a["seconds"],
                         "sim": r["seconds"], "err": err, "bound": a["bound"],
                         "stall": a["stall"], "sim_stall": r["stall"]})
    ok = worst <= dt * 1.5
    if verbose:
        print("TIME TO BUILD - closed form vs simulation (dt=" + str(dt) + ")")
        print("  " + "case".ljust(16) + "unit".ljust(12) + "closed".rjust(9)
              + "sim".rjust(9) + "err".rjust(8) + "  bound")
        for r in rows:
            if r["sim"] is None:
                print("  " + r["case"].ljust(16) + r["unit"].ljust(12)
                      + "never".rjust(9) + "never".rjust(9) + "-".rjust(8)
                      + "  " + str(r["bound"]))
                continue
            flag = "  <-- OVER TOLERANCE" if r["err"] > dt * 1.5 else ""
            print("  " + r["case"].ljust(16) + r["unit"].ljust(12)
                  + ("%.3f" % r["closed"]).rjust(9) + ("%.3f" % r["sim"]).rjust(9)
                  + ("%.4f" % r["err"]).rjust(8) + "  " + str(r["bound"]) + flag)
        print()
        print("  worst error " + ("%.4f" % worst) + "s against a " + str(dt)
              + "s timestep -> " + ("OK" if ok else "FAIL"))
    return {"ok": ok, "worst": worst, "rows": rows, "dt": dt}


# ══════════════════════════════════════════════════════════════════════════
# PHASES — the room left to grow decides which advice is valid
#
# Two axes, measured against the budget rather than asserted.
#
# CLAIMING          to_take   -> budget spots not yet held; room remains
#                   tasked    -> workers exist and are routed to the rest, and the
#                                plan carries an EXPECTED COMPLETION TIME
#                   taken     -> room 0. The metal ceiling can no longer be raised
#                                by claiming, and metal-bound now means CAPPED.
#
# SPENDING          for a target costing Mc metal and Ec energy, spending M metal
#                   per second needs M*Ec/Mc energy per second and M*W/Mc build
#                   power. Two thresholds fall out:
#                   underpowered     -> below what the mexes you HAVE would spend
#                   spend_current    -> can spend all metal from mexes held
#                   spend_projected  -> can spend all metal from the whole budget
#                   scaling          -> past that. Only here is 70:1 defensible.
#
# CAVEAT ON THE CLAIM TIME: `MapInfo.spots_from` measures every walk from the SPAWN,
# so summing those is not a route. `claim_plan` walks spawn -> nearest unclaimed ->
# next nearest from there, splits the chain across the workers that exist, and
# reports the SLOWEST worker, because the phase ends when the last spot lands.
# ══════════════════════════════════════════════════════════════════════════

def claim_plan(budget: dict, workers: int = 1, bp_per_worker: float = 100.0,
               unit: str = "con_bot", verbose: bool = False) -> dict:
    """Route the unclaimed budget spots across the workers that exist.

    Greedy nearest-next per worker from the spawn, which is what a player actually
    does. The phase completes when the LAST spot finishes, so the answer is the
    slowest worker's chain, not the sum."""
    left = [dict(sp) for sp in budget["spots"][budget["standing"]:]]
    w = max(1, int(workers))
    build_sec = OBJECTS["Mex"].bp_cost / bp_per_worker if bp_per_worker > 0 else float("inf")
    chains: List[dict] = [{"worker": i + 1, "spots": [], "sec": 0.0} for i in range(w)]
    # each worker starts at the spawn; hand the next-nearest spot to whichever
    # worker is free soonest, then walk it on from where it now stands
    pos = [None] * w                     # None = still at spawn
    while left:
        c = min(chains, key=lambda r: r["sec"])
        i = c["worker"] - 1
        if pos[i] is None:
            nxt = min(left, key=lambda sp: sp["walk_sec"])
            leg = nxt["walk_sec"]
        else:
            nxt = min(left, key=lambda sp: math.hypot(sp["x"] - pos[i][0],
                                                      sp["z"] - pos[i][1]))
            leg = walk_time(math.hypot(nxt["x"] - pos[i][0], nxt["z"] - pos[i][1]), unit)
        left.remove(nxt)
        pos[i] = (nxt["x"], nxt["z"])
        c["sec"] += leg + build_sec
        c["spots"].append({"n": nxt["n"], "walk_sec": round(leg, 1),
                           "metal_per_s": nxt["metal_per_s"],
                           "done_sec": round(c["sec"], 1)})
    slowest = max(chains, key=lambda r: r["sec"])
    out = {"workers": w, "bp_per_worker": bp_per_worker, "build_sec_each": build_sec,
           "chains": chains, "expected_complete_sec": round(slowest["sec"], 1),
           "slowest_worker": slowest["worker"],
           "spots_remaining": budget["room"],
           "m_per_s_added": round(sum(sp["metal_per_s"] for c in chains
                                      for sp in c["spots"]), 4)}
    if verbose:
        print("CLAIM PLAN  " + str(budget["room"]) + " spots left, " + str(w)
              + " worker(s) at " + str(bp_per_worker) + " BP each"
              + "   (Mex takes " + ("%.1f" % build_sec) + "s to build)")
        for c in chains:
            seq = " ".join("#" + str(sp["n"]) + "@" + str(sp["done_sec"]) + "s"
                           for sp in c["spots"])
            print("  worker " + str(c["worker"]) + ": " + ("%6.1f" % c["sec"]) + "s   " + seq)
        print()
        print("  ALL CLAIMED at +" + str(out["expected_complete_sec"]) + "s"
              + " (worker " + str(out["slowest_worker"]) + " finishes last), adding "
              + ("%.2f" % out["m_per_s_added"]) + " m/s")
    return out


def phase_markers(state: "EcoState", budget: dict, target: str = "Wind",
                  on: str = "Mex", bp: Optional[float] = None,
                  workers: int = 1, bp_per_worker: float = 100.0,
                  verbose: bool = False) -> dict:
    """Where this position sits on both phase axes, and what each threshold is."""
    b = bp if bp is not None else state.bp
    # the ratio is a property of the WORK the metal buys (`on`), not of the generator
    # being added. Using the generator would ask how much energy is needed to spend
    # metal on more generators, which answers nothing.
    T = OBJECTS[on]
    ratio = (T.energy_cost / T.metal_cost) if T.metal_cost > 0 else float("inf")
    bp_per_m = (T.bp_cost / T.metal_cost) if T.metal_cost > 0 else float("inf")
    m_cur = budget["m_per_s_current"]
    m_proj = budget["m_per_s_projected"]
    e_need_cur = m_cur * ratio
    e_need_proj = m_proj * ratio
    room = budget["room"]

    if room <= 0:
        mex_phase = "taken"
        plan = None
    else:
        plan = claim_plan(budget, workers, bp_per_worker)
        mex_phase = "tasked" if workers > 0 else "to_take"

    if state.e_inc < e_need_cur:
        e_phase = "underpowered"
    elif state.e_inc < e_need_proj:
        e_phase = "spend_current"
    elif state.e_inc <= e_need_proj * 1.0000001:
        e_phase = "spend_projected"
    else:
        e_phase = "scaling"
    # spend_projected is the boundary itself; anything above it is scaling
    if state.e_inc >= e_need_proj and e_phase != "scaling":
        e_phase = "spend_projected"

    out = {"mex": {"phase": mex_phase, "room": room, "standing": budget["standing"],
                   "count": budget["count"], "workers": workers,
                   "expected_complete_sec": (plan or {}).get("expected_complete_sec"),
                   "m_per_s_current": m_cur, "m_per_s_projected": m_proj},
           "energy": {"phase": e_phase, "e_inc": state.e_inc,
                      "e_need_current": round(e_need_cur, 1),
                      "e_need_projected": round(e_need_proj, 1),
                      "bp_need_current": round(m_cur * bp_per_m, 0),
                      "bp_need_projected": round(m_proj * bp_per_m, 0),
                      "bp": b, "ratio_e_per_m": ratio, "on": on, "target": target},
           "capped": room <= 0,
           "label": mex_phase + " / " + e_phase,
           "fungible": e_phase == "scaling"}
    if verbose:
        print("PHASES  t=" + ("%.0f" % state.t) + "s   budget " + str(budget["count"])
              + " mex on " + budget["map"] + "   metal is spent on " + on)
        print("  CLAIMING   " + mex_phase.upper() + "   standing "
              + str(budget["standing"]) + " of " + str(budget["count"])
              + "   ROOM " + str(room)
              + ("   all claimed in +" + str(out["mex"]["expected_complete_sec"])
                 + "s with " + str(workers) + " worker(s)" if plan else ""))
        print("             metal now " + ("%.2f" % m_cur) + " m/s, projected "
              + ("%.2f" % m_proj) + " m/s")
        print("  SPENDING   " + e_phase.upper() + "   energy " + ("%.0f" % state.e_inc)
              + " E/s")
        print("             to spend the mexes you HAVE: " + ("%.0f" % e_need_cur)
              + " E/s and " + ("%.0f" % out["energy"]["bp_need_current"]) + " BP")
        print("             to spend the WHOLE budget:   " + ("%.0f" % e_need_proj)
              + " E/s and " + ("%.0f" % out["energy"]["bp_need_projected"]) + " BP")
        print()
        if out["capped"]:
            print("  CAPPED: no room left. Metal bound here does NOT mean 'build another")
            print("  extractor' - it means the ceiling is fixed. AMex upgrades (7.3 m/s),")
            print("  reclaim, or converters are the only ways up.")
        else:
            print("  room " + str(room) + " left, so metal bound still means "
                  + "'take another spot' and is the state to aim for.")
        if out["fungible"]:
            print("  energy past what the whole budget could spend: the 70:1 converter")
            print("  price is defensible here and nowhere earlier.")
    return out


# ── Economic phases: when energy becomes fungible with metal ────────────────
#
# The 70:1 converter rate makes energy and metal interchangeable, but only once
# you are actually in a position to trade them. A game passes through phases, and
# which break-even applies depends on which one you are in:
#
#   claiming      extractors not all taken yet. Every second of energy is a second
#                 of a metal spot you do not own. Energy is NOT fungible: you
#                 cannot buy back the time.
#   underpowered  spots taken, but energy income cannot keep the build power fed,
#                 so metal you own sits unusable. Still not fungible.
#   spending      energy covers the crew and build power can absorb the metal
#                 income. The trade is becoming real.
#   scaling       energy income past what build power can consume. Surplus energy
#                 converts. HERE energy is fungible with metal and the 70:1
#                 approximation is the right one.
#
# The tests below are operational and parameterised, not definitions — they read
# the measured series and can oscillate, which is why the output is segments with
# the sample-level calls kept.

PHASES = ("claiming", "underpowered", "spending", "scaling")

# Build legality. econ_model.json declares `factoryProducts` and
# splendid_buildSimulator.js enforces it; bar_unified did not, which let the
# Commander produce BotWorkers in run_path. Mirrors the JS rule exactly:
# a factory product needs a factory builder, everything else needs a non-factory.
FACTORY_PRODUCTS = set(_CFG.get("factoryProducts") or [])


def wants_factory(unit: str) -> bool:
    t = OBJECTS[unit]
    return (unit in FACTORY_PRODUCTS or t.kind == "unit"
            or (t.kind == "builder" and (t.speed or 0) > 0))


def builder_can_make(is_factory: bool, unit: str) -> bool:
    return bool(is_factory) == wants_factory(unit)


def phase_of(m_inc: float, e_inc: float, bp_avail: float, mexes_done: int,
             mex_target: int, on: str = "Mex",
             absorb: float = BP_ABSORB_PER_POINT) -> str:
    """Which phase one measured sample looks like."""
    if mex_target and mexes_done < mex_target:
        return "claiming"
    cap = energy_ceiling(bp_avail, on) if bp_avail else 0.0
    if e_inc < cap:
        return "underpowered"
    if m_inc > bp_avail * absorb:
        return "spending"
    return "scaling"


def energy_is_fungible(phase: str) -> bool:
    """Whether pricing energy as metal at the converter rate is defensible here."""
    return phase == "scaling"


def applicable_breakeven(phase: str) -> dict:
    """Which generator break-even to quote in this phase, and why."""
    be = generator_breakevens()
    if phase == "scaling":
        return {"use": "metal_breakeven", "value": be["metal_breakeven"],
                "why": "energy converts, so pricing the 175 as metal is fair"}
    if phase == "claiming":
        return {"use": "rate_breakeven + catchup", "value": be["rate_breakeven"],
                "why": "energy buys extractor timing that metal cannot buy back"}
    if phase == "underpowered":
        return {"use": "bp_breakeven", "value": be["bp_breakeven"],
                "why": "build power is idle for want of energy, so energy per BP-second rules"}
    return {"use": "rate_breakeven", "value": be["rate_breakeven"],
            "why": "the trade is real but the build energy is still a debt"}


def generator_energy_race(wind_speed: float, solar: str = "Solar", wind: str = "Wind",
                          bp: Optional[float] = None) -> dict:
    """Net energy DELIVERED per metal spent, over time — the honest comparison.

    Pricing a turbine's 175 build energy as metal at the converter rate assumes the
    two are interchangeable. They are not, least of all in the minutes when energy
    is the scarce resource. The 175 is a DEBT: a turbine has produced nothing until
    it has paid it back out of its own output. A panel starts from zero.

    Per metal spent, from the moment the building finishes:

        solar   net(t) =  (20/155) * t
        wind    net(t) =  (W/40) * t  -  175/40

    so wind is behind by `debt_per_metal` at the start and closes the gap only if
    its rate per metal is higher. Two numbers come out of that, not one:

      rate_breakeven  the wind speed at which the RATES match, 20*40/155. Below
                      it wind never catches up, however long you wait.
      catchup_sec     how long after completion wind takes to pull level, which is
                      the number the one-dimensional answer was hiding.

    `build_work_ratio` is the third dimension: per metal spent, wind needs
    1600/40 = 40 BP-seconds against solar's 2600/155 = 16.8, so 2.4x the build
    power for the same metal. Pass `bp` to fold the build time in as well."""
    s, w = OBJECTS[solar], OBJECTS[wind]
    s_rate = s.energy_income / s.metal_cost                 # E/s per metal
    w_rate = wind_speed / w.metal_cost
    debt = w.energy_cost / w.metal_cost                     # energy owed per metal
    s_work = s.bp_cost / s.metal_cost                       # BP-seconds per metal
    w_work = w.bp_cost / w.metal_cost
    rate_be = s.energy_income * w.metal_cost / s.metal_cost
    gap = w_rate - s_rate
    catchup = debt / gap if gap > 1e-12 else None
    out = {"wind": wind_speed,
           "solar_rate_per_metal": s_rate, "wind_rate_per_metal": w_rate,
           "debt_per_metal": debt, "rate_breakeven": rate_be,
           "catchup_sec": catchup,
           "solar_work_per_metal": s_work, "wind_work_per_metal": w_work,
           "build_work_ratio": w_work / s_work,
           "wind_ahead_on_rate": wind_speed > rate_be}
    if bp:
        # include the time each takes to exist at all: per metal, total build work
        # divided by the build power applied to it
        out["solar_build_sec_per_metal"] = s_work / bp
        out["wind_build_sec_per_metal"] = w_work / bp
        out["catchup_sec_from_commit"] = (
            None if catchup is None
            else catchup + (w_work - s_work) / bp)
    return out


def net_energy_per_metal(wind_speed: float, sec: float, which: str = "Wind") -> float:
    """Net energy one metal of this generator has delivered `sec` after finishing."""
    t = OBJECTS[which]
    rate = (wind_speed if t.wind_powered else t.energy_income) / t.metal_cost
    return rate * sec - t.energy_cost / t.metal_cost


def generator_breakevens(solar: str = "Solar", wind: str = "Wind") -> dict:
    """The wind speed at which wind overtakes solar — on each resource separately.

    They are different numbers, which is the whole point. Which one matters is
    decided by which resource is scarce at that moment in the game."""
    s, w = OBJECTS[solar], OBJECTS[wind]
    s_out = s.energy_income
    # 1. metal, the FUNGIBLE approximation: price the build energy as metal at the
    #    converter rate. Convenient, and wrong in the opening, because it assumes
    #    you could have had that energy as metal. Kept for comparison; prefer
    #    `rate_breakeven` below and the catch-up time from generator_energy_race.
    s_metal_per_e = (s.metal_cost + s.energy_cost / ENERGY_PER_METAL) / s_out
    w_metal_all = w.metal_cost + w.energy_cost / ENERGY_PER_METAL
    be_metal = w_metal_all / s_metal_per_e
    # 1b. the same axis treating the build energy as a DEBT repaid from output:
    #     the rates match here, and below it wind never catches up at all
    be_rate = s_out * w.metal_cost / s.metal_cost
    # 2. build power: energy income bought per BP-second invested
    s_e_per_bp = s_out / s.bp_cost
    be_bp = s_e_per_bp * w.bp_cost
    # 3. energy: solar costs none to erect, so wind never wins this axis; report
    #    instead how long a turbine takes to repay the energy it cost to build
    return {"metal_breakeven": be_metal, "rate_breakeven": be_rate, "bp_breakeven": be_bp,
            "solar_metal_per_e": s_metal_per_e, "solar_e_per_bp_s": s_e_per_bp,
            "wind_metal_all_in": w_metal_all, "wind_build_energy": w.energy_cost,
            "solar_build_energy": s.energy_cost}


def energy_ceiling(bp: float, on: str = "Mex") -> float:
    """The most energy per second `bp` build power can physically consume building
    `on`. Energy income above this is not economy, it is overflow — metal that was
    spent on generators and returns nothing. Any comparison that scores raw E/s
    without this ceiling will prefer whichever generator is cheapest per E/s and
    be wrong about it."""
    return drain_rates(on, bp)["e_per_s"]


def usable_value_per_s(m_inc: float, e_inc: float, bp: float, on: str = "Mex") -> dict:
    """Economy rate counting only the energy the build power can actually spend."""
    cap = energy_ceiling(bp, on)
    used = min(e_inc, cap)
    return {"cap": cap, "used": used, "wasted": max(0.0, e_inc - cap),
            "value_per_s": m_inc + used / ENERGY_PER_METAL}


def cumulative_net_energy(unit: str, bp: float, t: float, wind_speed: float = 0.0,
                          continuous: bool = True) -> dict:
    """Net energy a nonstop build of `unit` has DELIVERED by time `t`.

    Counts three things the single-building comparison leaves out:
      * build TIME — a generator produces nothing until it finishes, and a solar
        takes 2600 BP-seconds against a turbine's 1600, so at the same build power
        you get 1.6x as many turbines in the same window;
      * the energy each one COSTS to erect, drawn continuously while building;
      * compounding — each finished generator keeps producing while the next builds.

    Returns the net figure plus the gross and the build cost, so the debt is visible
    rather than folded in."""
    t_obj = OBJECTS[unit]
    per = t_obj.bp_cost / bp                       # seconds per copy at this build power
    out_each = wind_speed if t_obj.wind_powered else t_obj.energy_income
    n = int(t / per)                               # copies finished by now
    # each copy k finished at k*per, so has run (t - k*per)
    gross = out_each * sum(t - k * per for k in range(1, n + 1))
    # energy spent erecting, drawn at a steady rate while building nonstop
    spent = (t_obj.energy_cost / per) * t if continuous else t_obj.energy_cost * n
    return {"t": t, "finished": n, "gross": gross, "build_energy": spent,
            "net": gross - spent, "sec_each": per,
            "metal_rate": t_obj.metal_cost / per, "energy_rate": t_obj.energy_cost / per}


def energy_balance_time(bp: float = 300.0, wind_speed: float = 12.0,
                        a: str = "Solar", b: str = "Wind",
                        horizon: float = 1800.0, dt: float = 0.25) -> Optional[float]:
    """Seconds until a nonstop `b` build has delivered more net energy than a
    nonstop `a` build, at this build power. None if it never does.

    Analytically, the leading term at large t is (output / build_work), so `b`
    overtakes only when its energy per BP-second exceeds `a`'s. Below that the
    immediacy of the cheaper-to-finish generator is never repaid."""
    t = dt
    while t <= horizon:
        na = cumulative_net_energy(a, bp, t, wind_speed)["net"]
        nb = cumulative_net_energy(b, bp, t, wind_speed)["net"]
        if nb >= na:
            return round(t, 1)
        t += dt
    return None


def energy_balance_table(bp: float = 300.0, a: str = "Solar", b: str = "Wind",
                         wind_speeds: Sequence[float] = tuple(range(1, 17)),
                         m_inc: Optional[float] = None, m_bank: Optional[float] = None,
                         e_inc: Optional[float] = None, e_bank: Optional[float] = None,
                         verbose: bool = True) -> dict:
    """Per wind speed: when does the efficiency of `b` overcome the immediacy of `a`,
    and what income does each pace demand to keep running.

    The sustain columns are the point of the second half. A nonstop solar build at
    300 build power eats 17.9 metal per second; nobody has that in the opening, so
    solar production is bank-limited and will stop. Knowing when it stops is what
    lets you start turbines before the stall rather than after it."""
    A, B = OBJECTS[a], OBJECTS[b]
    a_sec, b_sec = A.bp_cost / bp, B.bp_cost / bp
    a_m, b_m = A.metal_cost / a_sec, B.metal_cost / b_sec
    a_e, b_e = A.energy_cost / a_sec, B.energy_cost / b_sec
    # the leading-term condition: energy bought per BP-second
    a_per_bp = A.energy_income / A.bp_cost
    crossover_wind = a_per_bp * B.bp_cost
    rows = []
    for w in wind_speeds:
        t = energy_balance_time(bp, w, a, b)
        row = {"wind": w, "balance_sec": t}
        if t:
            ca = cumulative_net_energy(a, bp, t, w)
            cb = cumulative_net_energy(b, bp, t, w)
            row.update({"a_built": ca["finished"], "b_built": cb["finished"],
                        "net_at_balance": round(cb["net"]),
                        "a_metal_spent": round(ca["finished"] * A.metal_cost),
                        "b_metal_spent": round(cb["finished"] * B.metal_cost)})
        rows.append(row)
    out = {"bp": bp, "a": a, "b": b, "a_sec_each": a_sec, "b_sec_each": b_sec,
           "a_metal_per_s": a_m, "b_metal_per_s": b_m,
           "a_energy_per_s": a_e, "b_energy_per_s": b_e,
           "crossover_wind": crossover_wind, "rows": rows}
    # how long a bank sustains each pace, if the caller supplies a position
    if m_bank is not None:
        mi = m_inc or 0.0
        out["a_metal_runway"] = (m_bank / (a_m - mi)) if a_m > mi else float("inf")
        out["b_metal_runway"] = (m_bank / (b_m - mi)) if b_m > mi else float("inf")
    if e_bank is not None:
        ei = e_inc or 0.0
        out["b_energy_runway"] = (e_bank / (b_e - ei)) if b_e > ei else float("inf")

    if verbose:
        print(f"TOTAL EFFECTIVE ENERGY BALANCE — {a} vs {b} at {bp:g} build power")
        print(f"  {a}: {A.bp_cost:g} BP-s each -> one every {a_sec:.2f}s, "
              f"costs {A.metal_cost:g}m + {A.energy_cost:g}e, gives "
              f"{A.energy_income:g} E/s")
        print(f"  {b}: {B.bp_cost:g} BP-s each -> one every {b_sec:.2f}s, "
              f"costs {B.metal_cost:g}m + {B.energy_cost:g}e, gives wind E/s")
        print(f"\nTO SUSTAIN A NONSTOP BUILD AT {bp:g} BP")
        print(f"  {a:6} needs {a_m:6.2f} M/s and {a_e:6.1f} E/s")
        print(f"  {b:6} needs {b_m:6.2f} M/s and {b_e:6.1f} E/s")
        print(f"  -> {b} is {a_m / b_m:.2f}x cheaper in metal per second, "
              f"{a_sec / b_sec:.2f}x faster per building, and taxes energy where {a} does not")
        print(f"\n  {'wind':>5} {'balance':>9} {a[:6] + ' n':>8} {b[:6] + ' n':>8} "
              f"{'net E':>8} {a[:5] + ' m':>7} {b[:5] + ' m':>7}")
        for r in rows:
            if r["balance_sec"]:
                print(f"  {r['wind']:5.0f} {r['balance_sec']:8.1f}s {r['a_built']:8} {r['b_built']:8} "
                      f"{r['net_at_balance']:8} {r['a_metal_spent']:7} {r['b_metal_spent']:7}")
            else:
                print(f"  {r['wind']:5.0f} {'never':>9}")
        print(f"\n  {b} only ever overtakes above {crossover_wind:.2f} E/s: below that its "
              f"energy per BP-second is lower, so {a}'s head start is never repaid.")
        if "a_metal_runway" in out:
            print(f"\n  FROM YOUR POSITION ({m_bank:g} metal bank, {m_inc or 0:g} M/s income)")
            for lbl, rw, mps in ((a, out["a_metal_runway"], a_m), (b, out["b_metal_runway"], b_m)):
                if rw == float("inf"):
                    print(f"    {lbl:6} sustainable indefinitely ({mps:.1f} M/s <= income)")
                else:
                    n = int(rw / (a_sec if lbl == a else b_sec))
                    print(f"    {lbl:6} runs {rw:5.1f}s before the metal bank empties = {n} built, "
                          f"then it stalls")
    return out


# ══════════════════════════════════════════════════════════════════════════
# ECONOMIC STATE MACHINE — the five quantities, and what they permit next
#
# The five that decide everything: metal bank, energy bank, metal income, energy
# income, build power. A build is an edge between states. Two questions get asked
# of every state:
#
#   1. how many more of X can I build before this becomes unsustainable, and which
#      resource gives out first;
#   2. once it IS unsustainable, what rate can I actually sustain — because the
#      build no longer runs at nominal build power, it runs at whatever income
#      will feed. That is the EFFECTIVE build power, and it is what scaling really
#      means once the banks are gone.
#
# Build power is the third dimension rather than a parameter: adding it raises the
# ceiling on how fast you can convert, and simultaneously raises the income you
# need to feed it. `scaling_grid` sweeps it to show both effects at once.
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class EcoState:
    """A position: five quantities and what is standing."""
    t: float = 0.0
    metal: float = 1000.0
    energy: float = 1000.0
    m_inc: float = 2.0
    e_inc: float = 30.0
    bp: float = 300.0
    counts: Dict[str, int] = field(default_factory=dict)
    m_cap: float = 1000.0
    e_cap: float = 1000.0
    wind: float = DEFAULT_WIND

    def copy(self) -> "EcoState":
        return EcoState(self.t, self.metal, self.energy, self.m_inc, self.e_inc,
                        self.bp, dict(self.counts), self.m_cap, self.e_cap, self.wind)

    # ---- what a build costs from HERE ----
    def drain(self, unit: str, bp: Optional[float] = None) -> dict:
        """Rates and duration for `unit` at nominal build power."""
        return drain_rates(unit, bp if bp is not None else self.bp)

    def net_drain(self, unit: str, bp: Optional[float] = None) -> dict:
        """Drain minus income: what the banks actually lose per second."""
        d = self.drain(unit, bp)
        return {"m": d["m_per_s"] - self.m_inc, "e": d["e_per_s"] - self.e_inc,
                "seconds": d["seconds"]}

    # ---- the constrained rate ----
    def effective_bp(self, unit: str) -> dict:
        """Build power your INCOME can feed on `unit`, and what binds it.

        Nominal build power is a ceiling, not a rate. Once the banks are empty the
        real rate is this, and scaling anything is scaling this number."""
        t = OBJECTS[unit]
        by_m = self.m_inc * t.bp_cost / t.metal_cost if t.metal_cost > 0 else float("inf")
        by_e = self.e_inc * t.bp_cost / t.energy_cost if t.energy_cost > 0 else float("inf")
        eff = min(self.bp, by_m, by_e)
        binding = "build power" if eff == self.bp else ("metal" if by_m <= by_e else "energy")
        return {"bp": eff, "by_metal": by_m, "by_energy": by_e, "binding": binding,
                "utilisation": eff / self.bp if self.bp else 0.0,
                "sec_each": t.bp_cost / eff if eff > 0 else float("inf"),
                "per_min": 60.0 * eff / t.bp_cost if t.bp_cost else 0.0}

    # ---- transitions ----
    def build(self, unit: str, bp: Optional[float] = None) -> "EcoState":
        """Build one at nominal speed, paying from bank plus income. Does not clamp
        to zero — a negative bank here is the signal, caught by the caller."""
        t = OBJECTS[unit]
        b = bp if bp is not None else self.bp
        sec = t.bp_cost / b
        n = self.copy()
        n.t += sec
        n.metal = min(n.metal + self.m_inc * sec - t.metal_cost, self.m_cap)
        n.energy = min(n.energy + self.e_inc * sec - t.energy_cost, self.e_cap)
        out = self.wind if t.wind_powered else t.energy_income
        n.e_inc += out
        n.m_inc += t.metal_income
        n.bp += t.bp_income
        n.counts[unit] = n.counts.get(unit, 0) + 1
        if t.stor_m:
            n.m_cap += t.stor_m
        if t.stor_e:
            n.e_cap += t.stor_e
        return n

    def coast(self, seconds: float) -> "EcoState":
        """Advance time building nothing: income accrues, banks clamp at their caps."""
        n = self.copy()
        n.t += seconds
        n.metal = min(n.metal + self.m_inc * seconds, self.m_cap)
        n.energy = min(n.energy + self.e_inc * seconds, self.e_cap)
        return n

    def build_fed(self, unit: str, bp: Optional[float] = None, walk_sec: float = 0.0,
                  metal_income: Optional[float] = None) -> Tuple["EcoState", dict]:
        """`build` paced by what the economy can actually pay for.

        Unlike `build`, this does not let a bank go negative to signal trouble — it
        takes longer instead, which is what the game does. Returns the new position
        AND the timing, because the timing is the number the charts are made of.
        `metal_income` overrides the income added, so an extractor can carry its own
        spot's rate rather than a flat map average."""
        t = OBJECTS[unit]
        b = bp if bp is not None else self.bp
        n = self.coast(walk_sec) if walk_sec else self.copy()
        r = time_to_build(n, unit, b)
        sec = r["seconds"]
        if sec == float("inf"):
            return n, r
        n.t += sec
        n.metal = max(0.0, min(n.metal + n.m_inc * sec - t.metal_cost, n.m_cap))
        n.energy = max(0.0, min(n.energy + n.e_inc * sec - t.energy_cost, n.e_cap))
        n.e_inc += (self.wind if t.wind_powered else t.energy_income)
        n.m_inc += (t.metal_income if metal_income is None else metal_income)
        n.bp += t.bp_income
        n.counts[unit] = n.counts.get(unit, 0) + 1
        if t.stor_m:
            n.m_cap += t.stor_m
        if t.stor_e:
            n.e_cap += t.stor_e
        r = dict(r)
        r["walk_sec"] = walk_sec
        r["total_sec"] = walk_sec + sec
        return n, r
    def steps_until_unsustainable(self, unit: str, limit: int = 200) -> dict:
        """How many more `unit` this position supports before a bank runs dry.

        Iterated rather than solved, because each one you finish changes the income
        that funds the next — a generator extends its own runway, an extractor
        extends it further, a worker shortens it."""
        s, steps, trail = self, 0, []
        while steps < limit:
            nxt = s.build(unit)
            if nxt.metal < -1e-9 or nxt.energy < -1e-9:
                out_of = "metal" if nxt.metal < -1e-9 else "energy"
                if nxt.metal < -1e-9 and nxt.energy < -1e-9:
                    out_of = "metal and energy"
                eff = s.effective_bp(unit)
                return {"steps": steps, "seconds": round(s.t - self.t, 1),
                        "runs_out_of": out_of, "trail": trail,
                        "at_limit": s, "effective": eff}
            steps += 1
            s = nxt
            trail.append({"n": steps, "t": round(s.t, 1), "metal": round(s.metal),
                          "energy": round(s.energy), "m_inc": round(s.m_inc, 2),
                          "e_inc": round(s.e_inc, 1), "bp": s.bp})
        return {"steps": steps, "seconds": round(s.t - self.t, 1), "runs_out_of": None,
                "trail": trail, "at_limit": s, "effective": s.effective_bp(unit)}


def state_from_game(data: dict, at_sec: float) -> EcoState:
    """A real position, read from a game's measured 15 s series."""
    econ = data.get("econ") or []
    row = None
    for r in econ:
        if r["t"] <= at_sec:
            row = r
        else:
            break
    if row is None:
        raise ValueError("no econ sample at or before that time")
    counts: Dict[str, int] = {}
    for c in data.get("completions", []):
        if c["t"] <= at_sec and c.get("type"):
            counts[c["type"]] = counts.get(c["type"], 0) + 1
    w = data.get("wind", {}).get("samples") or []
    wind = next((x["value"] for x in reversed(w) if x["t"] <= at_sec), DEFAULT_WIND)
    return EcoState(t=row["t"], metal=row["metal"] or 0, energy=row["energy"] or 0,
                    m_inc=row["m_inc"] or 0, e_inc=row["e_inc"] or 0,
                    bp=row["bp_avail"] or 300, counts=counts,
                    m_cap=row.get("m_store") or 1000, e_cap=row.get("e_store") or 1000,
                    wind=wind or DEFAULT_WIND)


def scaling_report(state: EcoState, units: Sequence[str] = ("Solar", "Wind", "Mex", "BotWorker"),
                   verbose: bool = True) -> dict:
    """From this state: steps until unsustainable for each option, then the rate
    that survives once the banks are gone."""
    out = {}
    for u in units:
        if u not in OBJECTS:
            continue
        su = state.steps_until_unsustainable(u)
        eff = state.effective_bp(u)
        d = state.drain(u)
        out[u] = {"steps": su["steps"], "seconds": su["seconds"],
                  "runs_out_of": su["runs_out_of"], "nominal_sec": d["seconds"],
                  "nominal_m_per_s": d["m_per_s"], "nominal_e_per_s": d["e_per_s"],
                  "eff_bp": eff["bp"], "binding": eff["binding"],
                  "utilisation": eff["utilisation"], "eff_sec": eff["sec_each"],
                  "per_min": eff["per_min"]}
    if verbose:
        print(f"STATE  t={state.t:.0f}s   metal {state.metal:.0f}/{state.m_cap:.0f}  "
              f"energy {state.energy:.0f}/{state.e_cap:.0f}   "
              f"{state.m_inc:.2f} M/s  {state.e_inc:.0f} E/s   BP {state.bp:.0f}   "
              f"wind {state.wind:.1f}")
        if state.counts:
            print("       standing: " + ", ".join(f"{k} x{v}" for k, v in
                                                  sorted(state.counts.items(), key=lambda kv: -kv[1])))
        print(f"\n  {'build':10} {'nominal':>8} {'drain M/s':>10} {'drain E/s':>10} "
              f"{'steps':>6} {'until':>7} {'runs out':>16} {'eff BP':>7} {'util':>6} "
              f"{'sustained':>10}")
        for u, r in out.items():
            ro = r["runs_out_of"] or "sustainable"
            print(f"  {u:10} {r['nominal_sec']:7.1f}s {r['nominal_m_per_s']:10.2f} "
                  f"{r['nominal_e_per_s']:10.1f} {r['steps']:6} {r['seconds']:6.0f}s "
                  f"{ro:>16} {r['eff_bp']:7.0f} {r['utilisation'] * 100:5.0f}% "
                  f"{r['per_min']:6.2f}/min")
        print(f"\n  'steps' = how many more before a bank empties, counting the income each "
              f"one adds.\n  'eff BP' = the build power your INCOME can feed; "
              f"'sustained' is the rate that survives.")
    return out


def scaling_grid(state: EcoState, unit: str = "Solar",
                 bp_levels: Sequence[float] = (300, 450, 610, 890, 1170, 1600),
                 verbose: bool = True) -> dict:
    """Build power as the scaling dimension: what more of it buys, and what it costs.

    Raising build power raises the ceiling on conversion AND the income needed to
    feed it. Both move together, which is why more build power on its own can make
    a position worse."""
    rows = []
    for b in bp_levels:
        s = state.copy()
        s.bp = b
        d = s.drain(unit)
        su = s.steps_until_unsustainable(unit)
        eff = s.effective_bp(unit)
        rows.append({"bp": b, "sec_each": d["seconds"], "need_m": d["m_per_s"],
                     "need_e": d["e_per_s"], "steps": su["steps"],
                     "seconds": su["seconds"], "runs_out_of": su["runs_out_of"],
                     "eff_bp": eff["bp"], "utilisation": eff["utilisation"],
                     "per_min": eff["per_min"], "binding": eff["binding"]})
    if verbose:
        print(f"SCALING {unit} — build power as the third dimension "
              f"(from t={state.t:.0f}s, {state.m_inc:.2f} M/s, {state.e_inc:.0f} E/s, "
              f"banks {state.metal:.0f}m/{state.energy:.0f}e)")
        print(f"  {'BP':>6} {'each':>7} {'needs M/s':>10} {'needs E/s':>10} {'steps':>6} "
              f"{'until':>7} {'runs out':>10} {'eff BP':>7} {'util':>6} {'sustained':>10} {'bound by':>11}")
        for r in rows:
            ro = r["runs_out_of"] or "-"
            print(f"  {r['bp']:6.0f} {r['sec_each']:6.2f}s {r['need_m']:10.2f} {r['need_e']:10.1f} "
                  f"{r['steps']:6} {r['seconds']:6.0f}s {ro:>10} {r['eff_bp']:7.0f} "
                  f"{r['utilisation'] * 100:5.0f}% {r['per_min']:6.2f}/min {r['binding']:>11}")
        print(f"\n  utilisation falling as BP rises means the extra build power is idle: "
              f"you bought a ceiling you cannot feed.")
    return {"unit": unit, "rows": rows}


# ==========================================================================
# SOLAR COUNT SWEEP - the controlled experiment
#
# Replays cannot answer "how many solars" because they are all the same build.
# The only variable that may move is the solar count; everything else is held:
# same start, same mex walks, same factory, same worker schedule, same wind.
#
# The trade each solar makes:
#   COST  build work diverted from extractors, and 155 metal
#   GAIN  energy that stops the NEXT extractor stalling, so the mex line
#         finishes sooner - which is why more solars can produce MORE metal
#
# Compared at a single time AFTER every variant has its full mex line, so the
# comparison is like-for-like rather than at each variant's own milestone.
# Reported as a delta against the chosen baseline, in the terms the decision is
# actually made in: metal produced, energy produced, and the metal you could get
# back by reclaiming the panels.
# ==========================================================================

def solar_variant_path(n_solar: int, target_mex: int = 7, filler: str = "Wind",
                       walks: Optional[Sequence[float]] = None,
                       workers: int = 2, wind: float = 11.9) -> "BuildPath":
    """One variant: 3 home extractors, N panels, factory, N workers, the rest of
    the mex line, then `filler` forever. Only n_solar differs between variants."""
    w = list(walks if walks is not None else DEFAULT_MEX_WALK_SEC)
    while len(w) < target_mex:
        w.append(w[-1] if w else 0.0)
    steps: List[BuildStep] = []
    for i in range(min(3, target_mex)):
        steps.append(BuildStep("Mex", w[i], f"home mex {i + 1}"))
    for k in range(n_solar):
        steps.append(BuildStep("Solar", 0.0, f"solar {k + 1}"))
    steps.append(BuildStep("BotFactory", 0.0, "factory"))
    for k in range(workers):
        steps.append(BuildStep("BotWorker", 0.0, f"worker {k + 1}"))
    for i in range(3, target_mex):
        steps.append(BuildStep("Mex", w[i], f"forward mex {i + 1}"))
    return BuildPath(name=f"{n_solar}solar", steps=steps, wind=wind,
                     rule=lambda ctx: filler,
                     description=f"{n_solar} solar, {workers} worker, {target_mex} mex")


def solar_sweep(counts: Sequence[int] = tuple(range(0, 9)), target_mex: int = 7,
                compare_at: Optional[float] = None, wind: float = 11.9,
                filler: str = "Wind", workers: int = 2,
                walks: Optional[Sequence[float]] = None, baseline: int = 4,
                horizon: Optional[float] = None, verbose: bool = True) -> dict:
    """Run every solar count and compare them at one common time.

    `compare_at` defaults to a little past the slowest variant's last extractor, so
    every variant is judged after it has the same mex line standing."""
    hz = horizon or 420.0
    runs = {}
    for n in counts:
        pth = solar_variant_path(n, target_mex, filler, walks, workers, wind)
        runs[n] = run_path(pth, horizon=hz, sample_sec=1.0)

    def mex_done(tr: "PathTrace") -> Optional[float]:
        return tr.nth("Mex", target_mex)

    last = [mex_done(t) for t in runs.values()]
    slowest = max([x for x in last if x is not None], default=None)
    at = compare_at if compare_at is not None else (
        min(hz, (slowest or 0) + 30.0) if slowest else hz)

    rows = []
    for n, tr in runs.items():
        st = tr.at(at)
        rows.append({
            "solars": n,
            "mex_full": mex_done(tr),
            "at": at,
            "gathered_m": st.get("gathered_m"),
            "gathered_e": st.get("gathered_e"),
            # NET metal: production minus what was paid into builds. The gross figure
            # never subtracted the panels, which is the variable under test.
            "net_m": st.get("net_m"), "spent_m": st.get("spent_m"),
            # energy that survived the storage cap; the gross figure was 73-81% spill
            "kept_e": st.get("kept_e"), "spilled_e": st.get("spilled_e"),
            "m_inc": st.get("m_inc"), "e_inc": st.get("e_inc"),
            "bank_m": st.get("metal"), "bank_e": st.get("energy"),
            "bp": st.get("bp"),
            "wind_built": tr.count(filler, at),
            "reclaim_value": n * OBJECTS["Solar"].metal_cost,
            "wealth": wealth_at(tr, at)["total"],
            "wealth_assets": wealth_at(tr, at)["assets"],
            "stall_sec": tr.stall_sec, "stall_metal": tr.stall_metal_sec,
            "stall_energy": tr.stall_energy_sec, "illegal_blocked": tr.illegal_blocked,
            "bounds_ok": tr.bounds_ok,
            "trace": tr,
        })
    # metal-equivalent first for EVERY row, so the baseline has it before deltas
    for r in rows:
        # LIQUID metal: what is actually spendable now, bank plus what the panels
        # would return if reclaimed. Not added to metal produced - that would count
        # the same metal twice, since the panels were bought out of production.
        r["liquid"] = (r["bank_m"] or 0) + r["reclaim_value"]
        r["metal_equiv"] = r["liquid"]
    base = next((r for r in rows if r["solars"] == baseline), rows[0])
    for r in rows:
        r["d_wealth"] = (r["wealth"] or 0) - (base["wealth"] or 0)
        r["d_metal"] = (r["net_m"] or 0) - (base["net_m"] or 0)
        r["d_gross"] = (r["gathered_m"] or 0) - (base["gathered_m"] or 0)
        r["d_energy"] = (r["kept_e"] or 0) - (base["kept_e"] or 0)
        r["d_mex_full"] = (None if (r["mex_full"] is None or base["mex_full"] is None)
                           else round(r["mex_full"] - base["mex_full"], 1))
        # counting the panels you could reclaim back for 155 each
        r["d_metal_equiv"] = r["metal_equiv"] - base["metal_equiv"]

    if verbose:
        print(f"SOLAR COUNT SWEEP   wind {wind:g} E/s   {target_mex} mex, {workers} workers, "
              f"filler {filler}")
        print(f"  every variant judged at t={at:.0f}s, which is past the slowest variant's "
              f"{target_mex}th extractor ({slowest:.0f}s)" if slowest else "")
        print(f"  baseline = {baseline} solar. Deltas are against it.")
        print()
        print(f"  {'solars':>6} {'mex full':>9} {'vs base':>8} {'WEALTH':>8} {'vs base':>8} "
              f"{'assets':>8} {'banks':>7} {'kept E':>8} {'gross M':>8} {'stall M':>8} "
              f"{'stall E':>8}")
        for r in sorted(rows, key=lambda x: x["solars"]):
            mf = f"{r['mex_full']:.0f}s" if r["mex_full"] else "never"
            dm = f"{r['d_mex_full']:+.0f}s" if r["d_mex_full"] is not None else ""
            print(f"  {r['solars']:>6} {mf:>9} {dm:>8} {(r['wealth'] or 0):8.0f} "
                  f"{r['d_wealth']:+8.0f} {(r['wealth_assets'] or 0):8.0f} "
                  f"{((r['wealth'] or 0) - (r['wealth_assets'] or 0)):7.0f} "
                  f"{(r['kept_e'] or 0):8.0f} {(r['gathered_m'] or 0):8.0f} "
                  f"{r['stall_metal']:7.0f}s {r['stall_energy']:7.0f}s")
        best_m = max(rows, key=lambda r: r["wealth"] or 0)
        best_eq = max(rows, key=lambda r: r["metal_equiv"])
        fast = min([r for r in rows if r["mex_full"]], key=lambda r: r["mex_full"], default=None)
        print()
        print(f"  most WEALTH at t={at:.0f}s         : {best_m['solars']} solar "
              f"({(best_m['wealth'] or 0):.0f} metal-equivalent = banks + everything standing)")
        if fast:
            print(f"  fastest to {target_mex} mex           : {fast['solars']} solar "
                  f"({fast['mex_full']:.0f}s)")
        print(f"  most LIQUID metal (bank+reclaim): {best_eq['solars']} solar "
              f"({best_eq['liquid']:.0f}) - a separate axis, and it does not overturn "
              f"the ranking above")
        bad = [r['solars'] for r in rows if not r['bounds_ok']]
        print(f"  bounds: {'all variants clean' if not bad else 'VIOLATED in ' + str(bad)}")
        print(f"\n  'vs base' on metal is the number the decision turns on: a variant that "
              f"produced\n  MORE metal by the same clock paid for its panels out of earlier "
              f"extractors.")
    return {"at": at, "rows": rows, "baseline": baseline, "wind": wind,
            "target_mex": target_mex}


# ==========================================================================
# BUILD GAP - the dead time between finishing one building and starting the next
#
# A build cycle is not just build work / build power. Between a completion and the
# next placement there is a gap, and over a long chain it is a real tax on
# effective build power.
#
# The stream carries no builder attribution, so the builder is identified from the
# DURATION: a build that finished in exactly build_work / B seconds was done by B
# build power with nothing throttling it. That doubles as the resource test -
# finishing in nominal time is proof the build was neither metal- nor energy-bound,
# with no need to trust an interpolated bank reading.
#
# Walking is excluded by requiring consecutive placements to sit within one
# footprint hop, so the builder never leaves build range.
# ==========================================================================

# ==========================================================================
# IDLE AUDIT - walking is free when the economy could not have fed you anyway
#
# A builder that is walking contributes no build power, so the naive reading is
# that every walked second is lost. It is not. Build power only converts metal, so
# taking a builder offline during a resource dip costs nothing - the economy could
# not have fed it. Timing walks into the dips is what good micro looks like, and it
# is measurable.
#
# For every measured 15 s sample:
#   idle      = bp_avail - bp_used, build power that did no work
#   feedable  = build power the INCOME could have supplied (sustainable_bp)
#   headroom  = feedable - bp_used, how much more work was actually payable
#   COSTLY    = min(idle, headroom)   idle power the economy would have fed
#   FREE      = idle - costly         idle power that had nothing to convert
#
# A high free share means the walking was scheduled into the dips. A high costly
# share means builders sat still while metal was available to spend.
# ==========================================================================

# ==========================================================================
# TARGET ADVISOR - if build power cannot be consumed, change the target
#
# Every structure burns metal and energy in a FIXED RATIO, because at build power B
# it draws Mc*B/W metal per second and Ec*B/W energy per second. So the ratio is
# just Mc : Ec, a property of the thing, and it spans the whole range:
#
#   Solar        155 :    0   pure metal sink. Costs no energy to erect, so it is
#                            the ONLY energy source buildable during an energy famine.
#   Wind          40 :  175   needs energy to make energy - useless when starved.
#   Mex           50 :  500   energy-heavy; the thing energy is FOR.
#   BotWorker    110 : 1600   build power is bought with energy far more than metal.
#   ConTurret    230 : 3200   the most energy-hungry way to buy build power.
#   EConverter     1 : 1150   effectively a pure ENERGY sink at zero metal - the move
#                            when metal is gone and energy is spilling.
#
# So "I cannot spend my build power" is never a dead end, it is a statement about
# the current target only. Pick the structure whose ratio matches the surplus you
# actually have. And when a target CAN absorb all of it, that is the signal to buy
# more build power - or, if energy is what blocks buying it, to buy the
# energy-friendly generator first.
# ==========================================================================

def absorb_profile(state: "EcoState", unit: str, bp: Optional[float] = None) -> dict:
    """How much of this position's build power `unit` can actually consume."""
    b = bp if bp is not None else state.bp
    t = OBJECTS[unit]
    d = drain_rates(unit, b)
    feed = sustainable_bp(unit, state.m_inc, state.e_inc)
    absorbable = min(b, feed["bp"])
    # how long the banks extend the pace beyond what income alone supports
    rw = bank_runway(unit, b, state.metal, state.energy, state.m_inc, state.e_inc)
    ratio = (float("inf") if t.energy_cost == 0
             else t.metal_cost / t.energy_cost)
    return {"unit": unit, "metal_cost": t.metal_cost, "energy_cost": t.energy_cost,
            "ratio_m_per_e": ratio,
            "needs_m": d["m_per_s"], "needs_e": d["e_per_s"], "sec_each": d["seconds"],
            "absorbable_bp": absorbable, "absorb_share": absorbable / b if b else 0.0,
            "binding": feed["binding"], "runway_sec": rw["seconds"],
            "runway_count": rw["count"], "runway_binding": rw["binding"]}


def target_advisor(state: "EcoState", candidates: Optional[Sequence[str]] = None,
                   bp: Optional[float] = None, verbose: bool = True) -> dict:
    """Rank build targets by how much of this position's build power each can eat.

    The top of the list is what to build. If the top entry still absorbs everything,
    the constraint has moved to build power itself."""
    cands = list(candidates or ("Mex", "Solar", "Wind", "AdvSolar", "BotWorker",
                                "ConTurret", "EConverter", "EStorage"))
    b = bp if bp is not None else state.bp
    profs = [absorb_profile(state, u, b) for u in cands if u in OBJECTS]
    profs.sort(key=lambda r: (-r["absorb_share"], r["sec_each"]))
    top = profs[0] if profs else None

    # the surplus ratio this position actually has, to compare against Mc:Ec
    surplus_ratio = (float("inf") if state.e_inc <= 0 else state.m_inc / state.e_inc)
    overflow = state.e_inc > energy_ceiling(b, "Mex")
    metal_dry = state.metal < 50 and state.m_inc < drain_rates("Mex", b)["m_per_s"] * 0.5
    energy_famine = state.e_inc < 20 or state.energy < 100

    advice, why = None, ""
    if energy_famine:
        advice = "Solar"
        why = ("energy famine: Solar is the only generator that costs no energy to "
               "erect, so it is buildable when Wind is not")
    elif metal_dry and overflow:
        advice = "EConverter"
        why = ("metal is gone and energy is spilling: a converter costs 1 metal and "
               "1150 energy, so it converts the spill with nothing else to pay")
    elif top and top["absorb_share"] >= 0.999:
        advice = "BotWorker" if not overflow else "ConTurret"
        why = (f"{top['unit']} already absorbs all {b:.0f} build power, so build power "
               f"is now the limit" + (" - and energy is spilling, so buy the hungrier "
               "turret" if overflow else ""))
    elif top:
        advice = top["unit"]
        why = (f"absorbs {top['absorb_share'] * 100:.0f}% of build power, the most of "
               f"any candidate; bound by {top['binding']}")

    out = {"bp": b, "profiles": profs, "advice": advice, "why": why,
           "surplus_ratio_m_per_e": surplus_ratio, "energy_overflowing": overflow,
           "metal_dry": metal_dry, "energy_famine": energy_famine}

    if verbose:
        print(f"TARGET ADVISOR  t={state.t:.0f}s  {state.m_inc:.2f} M/s  {state.e_inc:.0f} E/s  "
              f"BP {b:.0f}  banks {state.metal:.0f}m/{state.energy:.0f}e  wind {state.wind:.1f}")
        print(f"  your surplus ratio  {state.m_inc:.2f} metal : {state.e_inc:.0f} energy per second"
              + (f"   (= 1 : {state.e_inc / state.m_inc:.0f})" if state.m_inc > 0 else ""))
        print(f"  energy ceiling at this build power {energy_ceiling(b, 'Mex'):.0f} E/s"
              + ("   OVERFLOWING" if overflow else ""))
        print()
        print(f"  {'target':12} {'cost m:e':>12} {'needs M/s':>10} {'needs E/s':>10} "
              f"{'can eat BP':>11} {'share':>6} {'bound by':>11} {'runway':>9}")
        for r in profs:
            rt = "pure metal" if r["energy_cost"] == 0 else f"1 : {r['energy_cost'] / max(r['metal_cost'], 1e-9):.0f}"
            rw = ("forever" if r["runway_sec"] == float("inf")
                  else f"{r['runway_sec']:.0f}s")
            print(f"  {r['unit']:12} {rt:>12} {r['needs_m']:10.2f} {r['needs_e']:10.1f} "
                  f"{r['absorbable_bp']:11.0f} {r['absorb_share'] * 100:5.0f}% "
                  f"{r['binding']:>11} {rw:>9}")
        print()
        print(f"  BUILD: {advice}")
        print(f"  WHY:   {why}")
        print()
        print(f"  a target that eats a small share leaves build power idle; that is a fact")
        print(f"  about the TARGET, not about the position. Pick one whose m:e ratio matches")
        print(f"  the surplus above. When the best one eats 100%, buy build power instead -")
        print(f"  and if energy is what blocks buying it, buy Solar first, since it is the")
        print(f"  only generator that needs no energy to erect.")
    return out


def target_timeline(data: dict, until_sec: float = 300.0,
                    candidates: Optional[Sequence[str]] = None) -> List[dict]:
    """What the advisor would have said at each measured point of a real game."""
    rows = []
    print(f"TARGET ADVICE OVER TIME  {(data.get('game') or {}).get('id')}")
    print(f"  {'t':>5} {'M/s':>6} {'E/s':>6} {'BP':>5} {'ovf':>4} {'best target':>12} "
          f"{'eats':>5}  built instead")
    comps = data.get("completions") or []
    for r in (data.get("econ") or []):
        if r["t"] > until_sec:
            break
        st = EcoState(t=r["t"], metal=r["metal"] or 0, energy=r["energy"] or 0,
                      m_inc=r["m_inc"] or 0, e_inc=r["e_inc"] or 0,
                      bp=r["bp_avail"] or 300)
        a = target_advisor(st, candidates, verbose=False)
        nxt = [c["type"] for c in comps if r["t"] < c["t"] <= r["t"] + 15 and c.get("type")]
        top = a["profiles"][0] if a["profiles"] else {}
        rows.append({"t": r["t"], "advice": a["advice"], "actual": nxt})
        print(f"  {r['t']:5.0f} {st.m_inc:6.2f} {st.e_inc:6.0f} {st.bp:5.0f} "
              f"{('YES' if a['energy_overflowing'] else '-'):>4} {str(a['advice']):>12} "
              f"{top.get('absorb_share', 0) * 100:4.0f}%  "
              + " ".join(dict.fromkeys(nxt))[:44])
    return rows


def idle_audit(data: dict, until_sec: float = 480.0, on: str = "Mex",
               verbose: bool = True) -> dict:
    """Split idle build power into the part the economy could have fed and the part
    it could not. Uses only the engine's own measured series."""
    econ = [r for r in (data.get("econ") or []) if r["t"] <= until_sec]
    if len(econ) < 2:
        return {"note": "need at least two econ samples"}
    rows = []
    for a, b in zip(econ, econ[1:]):
        dt = b["t"] - a["t"]
        avail = a.get("bp_avail") or 0.0
        used = a.get("bp_used") or 0.0
        idle = max(0.0, avail - used)
        feed = sustainable_bp(on, a.get("m_inc") or 0.0, a.get("e_inc") or 0.0)
        feedable = min(feed["bp"], avail)
        headroom = max(0.0, feedable - used)
        costly = min(idle, headroom)
        free = idle - costly
        rows.append({"t": a["t"], "dt": dt, "avail": avail, "used": used, "idle": idle,
                     "feedable": feedable, "headroom": headroom,
                     "costly": costly, "free": free,
                     "binding": feed["binding"],
                     "costly_bps": costly * dt, "free_bps": free * dt,
                     "util": (used / avail) if avail else 0.0})
    tot_idle = sum(r["idle"] * r["dt"] for r in rows)
    tot_costly = sum(r["costly_bps"] for r in rows)
    tot_free = sum(r["free_bps"] for r in rows)
    worked = sum(r["used"] * r["dt"] for r in rows)
    mex_bps = OBJECTS[on].bp_cost
    out = {"until": until_sec, "rows": rows, "idle_bps": tot_idle,
           "costly_bps": tot_costly, "free_bps": tot_free, "worked_bps": worked,
           "free_share": (tot_free / tot_idle) if tot_idle else 0.0,
           "costly_in_units": tot_costly / mex_bps, "unit": on}
    if verbose:
        g = data.get("game", {})
        print(f"IDLE AUDIT  {g.get('id')}  first {until_sec / 60:.0f} min  "
              f"(work measured against {on})")
        print(f"  {'t':>5} {'avail':>6} {'used':>6} {'util':>5} {'idle':>6} {'feedable':>9} "
              f"{'FREE':>6} {'COSTLY':>7}  bound by")
        for r in rows:
            print(f"  {r['t']:5.0f} {r['avail']:6.0f} {r['used']:6.0f} {r['util'] * 100:4.0f}% "
                  f"{r['idle']:6.0f} {r['feedable']:9.0f} {r['free']:6.0f} {r['costly']:7.0f}  "
                  f"{r['binding']}")
        print()
        print(f"  build power that DID work      {worked:9.0f} BP-seconds")
        print(f"  idle                           {tot_idle:9.0f} BP-seconds")
        print(f"    of which FREE (dip)          {tot_free:9.0f}  ({out['free_share'] * 100:.0f}% of idle)")
        print(f"    of which COSTLY (feedable)   {tot_costly:9.0f}  "
              f"= {out['costly_in_units']:.1f} x {on} of missed work")
        print()
        print(f"  FREE means the income could not have fed that build power, so walking or")
        print(f"  repositioning in those windows cost nothing. COSTLY means metal was")
        print(f"  available and the builders were not converting it.")
    return out


def idle_audit_many(ids: Optional[Sequence[str]] = None, until_sec: float = 480.0,
                    on: str = "Mex") -> dict:
    """The same audit across games, to see whether the timing is habitual."""
    ids = ids or [r["id"] for r in list_game_data()]
    print(f"IDLE AUDIT across games, first {until_sec / 60:.0f} min")
    print(f"  {'game':>18} {'worked':>9} {'idle':>9} {'free':>9} {'costly':>9} "
          f"{'free share':>11} {'missed ' + on:>12}")
    out = {}
    for gid in ids:
        d = load_game_data(gid)
        if len(d.get("econ") or []) < 2:
            continue
        a = idle_audit(d, until_sec, on, verbose=False)
        if "note" in a:
            continue
        out[gid] = a
        print(f"  {gid:>18} {a['worked_bps']:9.0f} {a['idle_bps']:9.0f} {a['free_bps']:9.0f} "
              f"{a['costly_bps']:9.0f} {a['free_share'] * 100:10.0f}% {a['costly_in_units']:12.1f}")
    if out:
        fs = [a["free_share"] for a in out.values()]
        cu = [a["costly_in_units"] for a in out.values()]
        print()
        print(f"  free share: mean {sum(fs) / len(fs) * 100:.0f}%  "
              f"range {min(fs) * 100:.0f}-{max(fs) * 100:.0f}%")
        print(f"  missed {on} equivalent: mean {sum(cu) / len(cu):.1f}  "
              f"range {min(cu):.1f}-{max(cu):.1f}")
    return out


def build_gaps(games: Optional[Sequence[Union[str, int, dict]]] = None,
               unit: str = "Wind", bp: float = 300.0, tol: float = 0.05,
               max_move: float = 120.0, max_gap: float = 2.0,
               verbose: bool = True) -> dict:
    """Measure the finish-to-start gap for chains of `unit` built at `bp`.

    Only links where BOTH builds finished within `tol` of nominal time are counted,
    so every measured gap is from an unthrottled chain. Returns the gap population
    plus the effective build power it implies."""
    nominal = OBJECTS[unit].bp_cost / bp
    if games is None:
        games = [r["id"] for r in list_game_data()]
    links: List[dict] = []
    seen_games = 0
    for g in games:
        d = g if isinstance(g, dict) else load_game_data(g)
        if not d.get("starts"):
            continue
        gid = (d.get("game") or {}).get("id", "?")
        st = {x["unitID"]: x for x in d["starts"]}
        fin = {c["unitID"]: c for c in d["completions"]}
        chain = sorted(
            ({"s": x["t"], "f": fin[u]["t"], "x": x.get("x"), "z": x.get("z")}
             for u, x in st.items() if x.get("type") == unit and u in fin),
            key=lambda r: r["s"])
        prev, n = None, 0
        for cur in chain:
            dur = cur["f"] - cur["s"]
            ok_now = abs(dur - nominal) < tol
            if prev is not None and ok_now and abs((prev["f"] - prev["s"]) - nominal) < tol:
                if cur["x"] is None or prev["x"] is None:
                    move = None
                else:
                    move = math.hypot(cur["x"] - prev["x"], cur["z"] - prev["z"])
                gap = cur["s"] - prev["f"]
                if -0.01 <= gap <= max_gap and (move is None or move <= max_move):
                    links.append({"game": gid, "t": round(cur["s"], 2),
                                  "gap": round(gap, 4), "frames": round(gap * GAME_FPS, 1),
                                  "move": None if move is None else round(move, 1),
                                  "dur": round(dur, 4)})
                    n += 1
            prev = cur
        if n:
            seen_games += 1
    if not links:
        return {"unit": unit, "bp": bp, "nominal": nominal, "links": [], "note":
                "no unthrottled chains found; try another unit, bp, or a longer game"}

    def _stats(vals):
        vs = sorted(vals)
        mid = len(vs) // 2
        med = vs[mid] if len(vs) % 2 else (vs[mid - 1] + vs[mid]) / 2
        mean = sum(vs) / len(vs)
        var = sum((v - mean) ** 2 for v in vs) / len(vs)
        return {"n": len(vs), "mean": mean, "median": med, "min": vs[0], "max": vs[-1],
                "stdev": var ** 0.5}

    # the gap is quantised; split the tight mode from any slower one rather than
    # averaging two different behaviours into one meaningless number
    tight = [l for l in links if l["frames"] <= 10]
    wide = [l for l in links if l["frames"] > 10]
    gs = _stats([l["gap"] for l in (tight or links)])
    cycle = nominal + gs["mean"]
    eff = OBJECTS[unit].bp_cost / cycle
    out = {"unit": unit, "bp": bp, "nominal": nominal, "links": links,
           "tight": tight, "wide": wide, "games": seen_games,
           "gap": gs, "gap_frames": gs["mean"] * GAME_FPS,
           "cycle": cycle, "effective_bp": eff, "efficiency": eff / bp,
           "modes": {}}
    buckets: Dict[float, int] = {}
    for l in links:
        buckets[l["frames"]] = buckets.get(l["frames"], 0) + 1
    out["modes"] = dict(sorted(buckets.items()))

    if verbose:
        print(f"BUILD GAP - {unit} at {bp:g} build power, across {seen_games} games")
        print(f"  nominal build {OBJECTS[unit].bp_cost:g} BP-s / {bp:g} BP = {nominal:.4f}s")
        print(f"  {len(links)} links counted; both builds finished within {tol}s of nominal,")
        print(f"  so neither was metal- or energy-throttled, and placements within "
              f"{max_move:g} elmos, so no walking.")
        print()
        print(f"  gap distribution, in frames:")
        for fr, n in out["modes"].items():
            bar = "#" * min(40, n)
            print(f"    {fr:6.1f} frames ({fr / GAME_FPS:6.3f}s)  x{n:<3} {bar}")
        if wide:
            print(f"  -> a second, slower mode at ~{_stats([l['frames'] for l in wide])['median']:.0f} "
                  f"frames ({len(wide)} links) is reported separately, not averaged in")
        print()
        print(f"  GAP            mean {gs['mean']:.3f}s  median {gs['median']:.3f}s  "
              f"({gs['mean'] * GAME_FPS:.1f} frames)  spread {gs['min']:.3f}-{gs['max']:.3f}")
        print(f"  cycle per {unit:<6} {cycle:.3f}s = {nominal:.3f} build + {gs['mean']:.3f} gap")
        print(f"  effective BP   {eff:.1f} of {bp:g} nominal ({out['efficiency'] * 100:.1f}%)")
        print(f"  the gap costs   {gs['mean'] * 10:.1f}s per 10 built, "
              f"{gs['mean'] * 50:.1f}s per 50")
    return out


# ══════════════════════════════════════════════════════════════════════════
# THE CADENCE TABLE — every cell is one copy, carrying its own +time
#
# The question is "how long will the next one take from HERE", asked repeatedly.
# So each cell is one completion and its number is the seconds THAT copy took,
# computed from the state at that moment by `time_to_build` — not `bp_cost / bp`,
# which is only the answer while the economy can pay at that pace.
#
# Rows are build-power tiers. Row i stops to buy i copies of the scaling source
# first, so its first target lands later; afterwards its cells are narrower. The
# rows share one time axis, so the lateral distance between them IS the cost of
# stopping to scale, and where a lower row overtakes row 0 is the crossover.
#
# A cell's WIDTH is its +time, which is why the chart cannot misreport density the
# way the old one did: it placed marks at `int(t * chars_per_second)` and two
# completions inside one character silently overwrote each other.
#
# When the target is an extractor the budget supplies each spot's OWN rate and walk,
# and the row stops when the budget runs out, because there is no 13th spot.
# ══════════════════════════════════════════════════════════════════════════

def cadence_row(state: "EcoState", target: str = "Wind",
                scale_source: str = "ConTurret", n_scale: int = 0,
                horizon: float = 240.0, budget: Optional[dict] = None,
                bp: Optional[float] = None, max_items: int = 400,
                workers: int = 1, stop_after: Optional[int] = None,
                share: float = 1.0, pools: Optional["BpPools"] = None,
                assign: str = "base") -> dict:
    """One row: buy `n_scale` of the scaling source, then `target`.

    Stops at `horizon` seconds, or after `stop_after` copies of the target if given.
    Counting copies is usually what you want: "how long until the next eight" keeps
    the cells wide enough to read, where a fixed time window on a fast target packs
    fifty of them into a line and can label none."""
    st = state.copy()
    if bp is not None:
        st.bp = bp
    # POOLS supersede `share`. A turbine is base work and an extractor is expand work,
    # so each target draws only on the pool that may legally build it - which is what
    # `share` was a scalar stand-in for. With no pools, `share` still applies.
    pl = pools.copy() if pools is not None else None
    if pl is not None:
        share = 1.0
    else:
        share = max(1e-6, min(1.0, float(share)))
        if share < 1.0:
            st.bp *= share
    t0 = st.t
    segs: List[dict] = []
    stopped = None

    def phase_now(cur: "EcoState", standing: int) -> str:
        if not budget:
            return "?"
        b2 = dict(budget)
        b2["standing"] = standing
        b2["m_per_s_current"] = round(
            sum(sp["metal_per_s"] for sp in budget["spots"][:standing]), 4)
        b2["room"] = budget["count"] - standing
        return phase_markers(cur, b2, target=target, workers=workers)["label"]

    standing = (budget or {}).get("standing", 0)
    for _ in range(max(0, int(n_scale))):
        prev_t = st.t
        bp_now = None
        if pl is not None:
            bp_now = pool_bp_for(scale_source, pl)["bp"]
            if bp_now <= 0:
                stopped = ("no build power in the "
                           + pool_bp_for(scale_source, pl)["work_pool"]
                           + " pool for " + scale_source)
                break
        nxt, r = st.build_fed(scale_source, bp=bp_now)
        if r["seconds"] == float("inf"):
            stopped = "cannot pay for " + scale_source
            break
        st = nxt
        if pl is not None:
            pl = pools_after(pl, scale_source, assign)
        segs.append({"kind": "invest", "unit": scale_source, "n": None,
                     "t_start": round(prev_t - t0, 3), "t_end": round(st.t - t0, 3),
                     "dt": round(r["total_sec"], 3), "nominal": round(r["nominal"], 3),
                     "stall": round(r["stall"], 3), "bound": r["bound"],
                     "walk_sec": r["walk_sec"],
                     "bp": (bp_now if bp_now is not None else st.bp),
                     "pool": (pool_bp_for(scale_source, pl)["work_pool"]
                              if pl is not None else None),
                     "m_inc": round(st.m_inc, 3), "e_inc": round(st.e_inc, 2),
                     "phase": phase_now(st, standing)})
        if st.t - t0 >= horizon:
            break

    n = 0
    route = (mex_route(budget, standing)["legs"]
             if (budget and OBJECTS[target].metal_income > 0) else [])
    leg_i = 0
    while len(segs) < max_items:
        if stop_after is not None:
            if n >= stop_after:
                break
        elif st.t - t0 >= horizon:
            break
        walk, minc = 0.0, None
        if route:
            if leg_i >= len(route):
                stopped = ("budget exhausted: all " + str(budget["count"])
                           + " spots claimed, there is no spot "
                           + str(budget["count"] + 1))
                break
            leg = route[leg_i]
            leg_i += 1
            walk, minc = leg["walk_sec"], leg["metal_per_s"]
        prev_t = st.t
        bp_now = None
        if pl is not None:
            bp_now = pool_bp_for(target, pl)["bp"]
            if bp_now <= 0:
                stopped = ("no build power in the " + pool_bp_for(target, pl)["work_pool"]
                           + " pool for " + target)
                break
        nxt, r = st.build_fed(target, bp=bp_now, walk_sec=walk, metal_income=minc)
        if r["seconds"] == float("inf"):
            stopped = "cannot pay for " + target
            break
        st = nxt
        n += 1
        if pl is not None:
            pl = pools_after(pl, target, assign)
        if route:
            standing += 1
        segs.append({"kind": "target", "unit": target, "n": n,
                     "t_start": round(prev_t - t0, 3), "t_end": round(st.t - t0, 3),
                     "dt": round(r["total_sec"], 3), "nominal": round(r["nominal"], 3),
                     "stall": round(r["stall"], 3), "bound": r["bound"],
                     "walk_sec": r["walk_sec"],
                     "bp": (bp_now if bp_now is not None else st.bp),
                     "pool": (pool_bp_for(target, pl)["work_pool"]
                              if pl is not None else None),
                     "m_inc": round(st.m_inc, 3), "e_inc": round(st.e_inc, 2),
                     "phase": phase_now(st, standing)})

    tg = [x for x in segs if x["kind"] == "target"]
    first_bound = next((x for x in tg if x["bound"] != "none"), None)
    return {"n_scale": n_scale, "scale_source": scale_source, "target": target,
            "segments": segs, "targets": n, "end_bp": st.bp,
            "end_m_inc": round(st.m_inc, 3), "end_e_inc": round(st.e_inc, 2),
            "invest_sec": round(sum(x["dt"] for x in segs if x["kind"] == "invest"), 2),
            "stall_sec": round(sum(x["stall"] for x in segs), 2),
            "nominal_each": (round(OBJECTS[target].bp_cost
                                   / (pool_bp_for(target, pl)["bp"] if pl is not None
                                      else st.bp), 3)
                             if (pl is None and st.bp) or
                                (pl is not None and pool_bp_for(target, pl)["bp"] > 0)
                             else None),
            "pools_end": (None if pl is None else
                          {"expand": pl.expand, "factory": pl.factory, "base": pl.base}),
            "first_bound": (None if not first_bound else
                            {"n": first_bound["n"], "t": first_bound["t_end"],
                             "bound": first_bound["bound"]}),
            "at": {k: next((x["t_end"] for x in tg if x["n"] == k), None)
                   for k in (1, 5, 10, 20)},
            "standing_end": standing, "stopped": stopped, "state_end": st}


# ══════════════════════════════════════════════════════════════════════════
# FIND A GAME WITH EVERY FACTION IN IT
#
# The def harvest replays one game, and a game only defines the factions the lobby
# actually enabled. That is why Legion had to be CARRIED THROUGH from an older file:
# the 8v8 the harvest picked was Armada and Cortex only, so Legion's numbers aged
# quietly while everything else refreshed.
#
# The fix is to pick the demo on purpose. Demo headers carry each player's faction, so
# scanning newest-first finds a game with all three in it and the harvest gets one
# consistent, current picture. The scan is cached to `demo_index.json` because parsing
# a header costs about a sixth of a second and there are thousands of demos.
# ══════════════════════════════════════════════════════════════════════════

FACTIONS = ("Armada", "Cortex", "Legion")
DEMO_INDEX_PATH = os.path.join(HERE, "demo_index.json")


def demo_index(limit: int = 200, refresh: bool = False,
               verbose: bool = False) -> Dict[str, dict]:
    """Newest `limit` demos -> the factions, players and map in each. Cached."""
    idx: Dict[str, dict] = {}
    if os.path.exists(DEMO_INDEX_PATH) and not refresh:
        try:
            with open(DEMO_INDEX_PATH, encoding="utf-8") as fh:
                idx = json.load(fh) or {}
        except (OSError, ValueError):
            idx = {}
    files = _demo_files()[:limit]
    added = 0
    for f in files:
        if f in idx and not refresh:
            continue
        try:
            h = _demo_header(os.path.join(DEMOS_DIR, f))
        except Exception as exc:                                   # noqa: BLE001
            idx[f] = {"error": str(exc)[:120]}
            continue
        players = h.get("players") or []
        facs = sorted({str(pl.get("faction") or "?") for pl in players})
        idx[f] = {"factions": facs, "players": len(players),
                  "ais": len(h.get("ais") or []), "map": h.get("map"),
                  "engine": h.get("engine"), "matchup": h.get("matchup"),
                  "game": h.get("game")}
        added += 1
    if added:
        try:
            with open(DEMO_INDEX_PATH, "w", encoding="utf-8") as fh:
                json.dump(idx, fh, indent=1, sort_keys=True)
        except OSError:
            pass
    if verbose:
        print("demo index: " + str(len(idx)) + " demos, " + str(added) + " newly parsed")
    return idx


def installed_games(verbose: bool = False) -> Dict[str, str]:
    """Game archives this machine can actually load, name -> rapid tag.

    rapid keeps one .sdp per installed package and a `versions.gz` mapping
    tag,hash,,name. Intersecting the two answers "can spring-headless replay a demo
    recorded on this game version", which is the difference between a 40-second harvest
    and a Fatal content_error four seconds in."""
    import gzip
    bar = os.path.dirname(DEMOS_DIR)                        # ...\data\demos -> ...\data
    have = {os.path.splitext(os.path.basename(x))[0].lower()
            for x in glob.glob(os.path.join(bar, "packages", "*.sdp"))}
    out: Dict[str, str] = {}
    for v in glob.glob(os.path.join(bar, "rapid", "**", "versions.gz"), recursive=True):
        try:
            with gzip.open(v, "rt", encoding="utf-8", errors="replace") as fh:
                for ln in fh:
                    parts = ln.strip().split(",")
                    if len(parts) >= 4 and parts[1].lower() in have and parts[3]:
                        out.setdefault(parts[3], parts[0])
        except OSError:
            continue
    for sdd in glob.glob(os.path.join(bar, "games", "*.sdd")):
        out.setdefault(os.path.basename(sdd), "local sdd")
    if verbose:
        print("INSTALLED GAMES  " + str(len(out)) + " loadable archive(s)")
        for name, tag in sorted(out.items()):
            print("  " + name.ljust(42) + str(tag)[:52])
    return out


def find_faction_demo(need: Sequence[str] = FACTIONS, limit: int = 200,
                      min_players: int = 1, refresh: bool = False,
                      replayable_only: bool = True,
                      verbose: bool = True) -> dict:
    """The newest REPLAYABLE demo containing every faction in `need`.

    Replayable means the game version it was recorded on is still installed; a demo on
    a version rapid has replaced cannot be harvested at all, so by default those are
    excluded rather than returned and failed on."""
    want = {str(x).lower() for x in need}
    idx = demo_index(limit, refresh)
    games = installed_games()
    ranked: List[dict] = []
    for f in sorted(idx, reverse=True):                            # names sort by time
        r = idx[f]
        if r.get("error") or (r.get("players") or 0) < min_players:
            continue
        got = {str(x).lower() for x in (r.get("factions") or [])}
        hits = want & got
        # a game played on the local sdd build records an unexpanded "$VERSION", which
        # is not a missing archive - it is BAR.sdd, and BAR.sdd is installed
        gname = str(r.get("game") or "")
        playable = (not gname) or (gname in games) or ("$VERSION" in gname)
        ranked.append({"file": f, "path": os.path.join(DEMOS_DIR, f),
                       "factions": r.get("factions"), "players": r.get("players"),
                       "map": r.get("map"), "matchup": r.get("matchup"),
                       "engine": r.get("engine"), "game": r.get("game"),
                       "replayable": playable,
                       "have": sorted(hits), "missing": sorted(want - got),
                       "complete": not (want - got)})
    pool = [r for r in ranked if r["replayable"]] if replayable_only else ranked
    # how often each wanted faction appears in the pool: the rare one is the one worth
    # harvesting for, so a candidate carrying it outranks a bigger game without it
    freq = {f: 0 for f in want}
    for r in pool:
        for f in r["have"]:
            freq[f] = freq.get(f, 0) + 1
    for r in pool:
        r["rarity_score"] = round(sum(1.0 / max(1, freq.get(f, 1)) for f in r["have"]), 6)
    best = next((r for r in pool if r["complete"]), None)
    if best is None and pool:
        best = max(pool, key=lambda r: (r["rarity_score"], r["players"]))
    blocked = [r for r in ranked if r["complete"] and not r["replayable"]]
    out = {"need": sorted(want), "scanned": len(ranked),
           "replayable": len(pool), "best": best,
           "faction_frequency": dict(sorted(freq.items())),
           "complete": bool(best and best["complete"]),
           "blocked_by_game_version": [
               {"file": r["file"], "game": r["game"]} for r in blocked[:5]],
           "installed_games": sorted(games),
           "candidates": [r for r in pool if r["have"]][:10]}
    if verbose:
        print("FIND FACTION DEMO  need " + ", ".join(sorted(want))
              + "   scanned " + str(len(ranked)) + " demos (newest first)")
        if not best:
            print("  nothing usable found; raise --limit or check $BAR_DEMOS")
            return out
        print("  " + ("COMPLETE" if out["complete"] else "BEST NEAR MISS")
              + ": " + best["file"])
        print("    " + str(best["players"]) + " players, " + str(best["matchup"])
              + " on " + str(best["map"]) + ", engine " + str(best["engine"]))
        print("    factions present: " + ", ".join(best["factions"] or []))
        if best["missing"]:
            print("    no PLAYER picked: " + ", ".join(best["missing"]))
            print("    That is usually fine. Measured 2026-09-28: a 1-player Legion game")
            print("    harvested 844 defs with factionsMissing [] - arm 253, cor 260,")
            print("    leg 244. Player choice does not gate def loading; the Legion")
            print("    MODOPTION does, and a Legion player implies it was on. Check the")
            print("    harvest's own factionsMissing rather than trusting this line.")
        print("    game " + str(best.get("game")) + "  -> replayable")
        print("    how common each wanted faction is here: "
              + ", ".join(k + " " + str(v) + "/" + str(len(pool))
                          for k, v in sorted(out["faction_frequency"].items())))
        if out["blocked_by_game_version"]:
            print()
            print("  NOT USABLE - complete on factions but the game version is gone:")
            for r in out["blocked_by_game_version"]:
                print("    " + r["file"][:46] + "  needs " + str(r["game"]))
            print("  installed: " + "; ".join(out["installed_games"][:3]))
        if len(out["candidates"]) > 1:
            print()
            print("  other replayable games carrying at least one wanted faction:")
            for r in out["candidates"][1:6]:
                print("    " + r["file"][:46] + "  " + ",".join(r["factions"] or []))
    return out


# ══════════════════════════════════════════════════════════════════════════
# THE EFFECTIVE EXTRACTOR RATE — an extractor's energy flow IS part of its metal
#
# A spot's m/s is not what the spot is worth. An Armada extractor burns 3 E/s to
# run; a Legion one PRODUCES 7 E/s. At the T1 converter rate those are metal:
#
#     net m/s  =  spot m/s  +  energy_flow / 70
#
#     armmex   1.825 - 3/70   = 1.782   (-2.3%)
#     legmex   1.369 + 7/70   = 1.469   (+7.3%)   <- a GAIN, not a cost
#     armmoho  7.300 - 20/70  = 7.014   (-3.9%)
#
# That moves a real comparison: raw, a Legion extractor is 75% of an Armada one; net,
# it is 82%. The energy it hands back closes a quarter of the gap.
#
# THE PENALTY IS FLAT, THE RATE IS NOT. Upkeep is per BUILDING, so a rich spot pays
# the same 3 E/s as a poor one and loses proportionally less by it: -1.4% on a 3.16
# spot against -2.3% on a 1.825. Poor spots are worse than their raw number says.
#
# WHEN THIS IS LEGITIMATE. The 70:1 rate is only real once surplus energy is actually
# convertible — the `scaling` phase (`energy_is_fungible`). Before that, energy spent
# on upkeep is not metal you could have had, it is build power you could not feed. So
# both figures are always carried, and `phase` says which one to read.
# ══════════════════════════════════════════════════════════════════════════

def _extractor_facts(unit: str) -> tuple:
    """(m/s on the reference spot, energy flow) for a model object OR any engine def.

    Legion is half of this question and is not a modelled ObjectType, so a raw def
    name resolves from the dump: `legmex` produces 7 E/s where `armmex` burns 3."""
    if unit in OBJECTS:
        t = OBJECTS[unit]
        return float(t.metal_income), float(t.energy_income), (t.def_name or unit)
    d = (ED.engine_defs() or {}).get(unit)
    if not d:
        raise KeyError("no object or engine def named " + unit)
    prod, upkeep = ED.energy_flows(d)
    return float(ED.mex_income(d)), float(prod) - float(upkeep), unit


def effective_metal_rate(unit: str = "Mex", spot_rate: Optional[float] = None,
                         exchange: float = ENERGY_PER_METAL) -> dict:
    """An extractor's metal rate with its own energy flow priced in at `exchange`.

    `spot_rate` is the REFERENCE extractor's rate on the spot in question; this scales
    it by `unit`'s own multiplier, so an advanced extractor is not credited with a T1
    rate. The energy flow is per BUILDING and is added once, not scaled."""
    base, flow, def_name = _extractor_facts(unit)
    std = _C["metalSpot"]
    mult = (base / std) if std else 1.0
    raw = base if spot_rate is None else float(spot_rate) * mult
    equiv = (flow / exchange) if exchange else 0.0
    net = raw + equiv
    return {"unit": unit, "def": def_name, "raw_m_per_s": round(raw, 6),
            "multiplier": round(mult, 4), "spot_rate": spot_rate,
            "energy_flow": flow, "energy_as_metal": round(equiv, 6),
            "net_m_per_s": round(net, 6),
            "pct_change": round((net / raw - 1.0) * 100.0, 4) if raw else None,
            "exchange": exchange, "direction": ("gain" if flow > 0 else
                                                ("upkeep" if flow < 0 else "neutral"))}


def extractor_rates(units: Sequence[str] = ("Mex", "AMex", "legmex", "legmoho"),
                    spot_rates: Sequence[float] = (1.825, 3.16),
                    exchange: float = ENERGY_PER_METAL,
                    verbose: bool = True) -> dict:
    """The effective rate for each extractor, and on each class of spot."""
    out: Dict[str, dict] = {}
    for u in units:
        try:
            base = effective_metal_rate(u, None, exchange)
        except KeyError:
            continue
        base["on_spots"] = [effective_metal_rate(u, r, exchange) for r in spot_rates]
        out[u] = base
    if verbose:
        print("EFFECTIVE EXTRACTOR RATE   energy priced as metal at "
              + ("%g" % exchange) + ":1")
        print("  " + "unit".ljust(9) + "raw m/s".rjust(9) + "E/s".rjust(7)
              + "as metal".rjust(10) + "net m/s".rjust(9) + "change".rjust(9)
              + "  flow    def")
        for u, r in out.items():
            print("  " + u.ljust(9) + ("%9.3f" % r["raw_m_per_s"])
                  + ("%+7.0f" % r["energy_flow"]) + ("%+10.4f" % r["energy_as_metal"])
                  + ("%9.4f" % r["net_m_per_s"])
                  + ("%+8.2f" % r["pct_change"]) + "%  " + r["direction"].ljust(7)
                  + " " + str(r["def"]))
        # the comparison the energy flow actually moves
        if "Mex" in out and "legmex" in out:
            a, l = out["Mex"], out["legmex"]
            print()
            print("  Legion against Armada, T1: raw "
                  + ("%.1f" % (l["raw_m_per_s"] / a["raw_m_per_s"] * 100)) + "%, net "
                  + ("%.1f" % (l["net_m_per_s"] / a["net_m_per_s"] * 100)) + "%"
                  + "  - the energy it hands back closes "
                  + ("%.0f" % ((l["net_m_per_s"] / a["net_m_per_s"]
                               - l["raw_m_per_s"] / a["raw_m_per_s"])
                              / (1 - l["raw_m_per_s"] / a["raw_m_per_s"]) * 100))
                  + "% of the gap")
        print()
        print("  upkeep is per BUILDING, so the SAME energy is paid on every spot and")
        print("  a poor spot loses proportionally more of its value to it:")
        for u, r in out.items():
            print("  " + u + "  (x" + ("%.2f" % r["multiplier"])
                  + " the reference extractor)")
            for sr in r["on_spots"]:
                print("    reference spot " + ("%5.3f" % (sr["spot_rate"] or 0))
                      + " -> this extractor makes " + ("%6.3f" % sr["raw_m_per_s"])
                      + " m/s, net " + ("%6.3f" % sr["net_m_per_s"]) + "  ("
                      + ("%+.2f" % sr["pct_change"]) + "%)")
        print()
        print("  legitimate only where surplus energy actually converts - the `scaling`")
        print("  phase. Earlier, upkeep is build power you cannot feed, not metal lost.")
    return out


# ══════════════════════════════════════════════════════════════════════════
# PLACEMENT SPREAD — is the pool split a real partition, or one roaming crew?
#
# `split_bp` divides build power into expand, factory and base, and the stream carries
# no builder position, so that division is a STATED policy. But every placement DOES
# carry coordinates, and that is enough to test the policy's central assumption.
#
# If an extractor goes down 495 elmos out and a turbine goes down 480 elmos out eleven
# seconds later, the same crew almost certainly did both. Repeat that and the pools are
# not disjoint: base and expand share hands, and reading "the expand pool is empty" as a
# fact about the position is wrong - it is a fact about the policy that was stated.
#
# The test is deliberately weak. It reports co-location as EVIDENCE with a threshold you
# can move, not as a verdict, because two crews working the same forward area produce the
# same signature as one crew doing both jobs.
# ══════════════════════════════════════════════════════════════════════════

def placement_spread(data: dict, from_sec: float = 0.0, until_sec: float = 600.0,
                     same_place: float = 150.0, same_time: float = 30.0,
                     home_radius: float = 250.0, verbose: bool = True) -> dict:
    """Where the build work went, and whether the pools look like separate crews."""
    pl = data.get("player") or {}
    sx, sz = pl.get("start_x"), pl.get("start_z")
    if sx is None or sz is None:
        return {"note": "this game's hard data has no spawn position"}
    rows = []
    for c in (data.get("starts") or []):
        if c.get("x") is None or not (from_sec <= c["t"] <= until_sec):
            continue
        u, dn = c.get("type"), c.get("def")
        pool = def_work_pool(dn, u)
        rows.append({"t": round(c["t"], 1), "type": u or dn, "pool": pool,
                     "dist": round(math.hypot(c["x"] - sx, c["z"] - sz), 0),
                     "zone": "home" if math.hypot(c["x"] - sx, c["z"] - sz) <= home_radius
                             else "field"})
    if not rows:
        return {"note": "no placements with coordinates in that window"}
    rows.sort(key=lambda r: r["t"])

    def med(vals):
        v = sorted(vals)
        if not v:
            return None
        m = len(v) // 2
        return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2

    per_pool = {}
    for pool in ("expand", "base", "factory"):
        ds = [r["dist"] for r in rows if r["pool"] == pool]
        if ds:
            per_pool[pool] = {"n": len(ds), "median_dist": med(ds),
                              "min": min(ds), "max": max(ds),
                              "home": sum(1 for r in rows
                                          if r["pool"] == pool and r["zone"] == "home"),
                              "field": sum(1 for r in rows
                                           if r["pool"] == pool and r["zone"] == "field")}

    # co-location: an expand placement and a base placement close in space AND time
    pairs, near = 0, []
    exp = [r for r in rows if r["pool"] == "expand"]
    bas = [r for r in rows if r["pool"] == "base"]
    for e in exp:
        for b in bas:
            if abs(b["t"] - e["t"]) <= same_time:
                pairs += 1
                if abs(b["dist"] - e["dist"]) <= same_place:
                    near.append({"expand": e["type"], "base": b["type"],
                                 "t": e["t"], "dt": round(b["t"] - e["t"], 1),
                                 "dist_e": e["dist"], "dist_b": b["dist"]})
    share = (len(near) / pairs) if pairs else 0.0
    out = {"from": from_sec, "until": until_sec, "placements": len(rows),
           "per_pool": per_pool, "rows": rows,
           "pairs_in_time": pairs, "pairs_colocated": len(near),
           "colocated_share": round(share, 4), "examples": near[:8],
           "same_place": same_place, "same_time": same_time,
           "one_crew_evidence": share >= 0.5 and pairs >= 4}

    if verbose:
        g = data.get("game") or {}
        print("PLACEMENT SPREAD  " + str(g.get("id")) + "   "
              + ("%.0f" % from_sec) + "-" + ("%.0f" % until_sec) + "s   spawn "
              + str(int(sx)) + "," + str(int(sz)))
        print("  " + "pool".ljust(9) + "n".rjust(4) + "median".rjust(8) + "min".rjust(7)
              + "max".rjust(7) + "   home/field")
        for pool, r in per_pool.items():
            print("  " + pool.ljust(9) + str(r["n"]).rjust(4)
                  + ("%8.0f" % (r["median_dist"] or 0)) + ("%7.0f" % r["min"])
                  + ("%7.0f" % r["max"]) + "   " + str(r["home"]) + "/" + str(r["field"]))
        print()
        print("  co-location test: an extractor and a base building placed within "
              + ("%.0f" % same_place) + " elmos")
        print("  of each other and " + ("%.0f" % same_time) + "s apart.")
        print("  " + str(len(near)) + " of " + str(pairs) + " time-adjacent pairs = "
              + ("%.0f" % (share * 100)) + "% co-located")
        for x in near[:6]:
            print("    t=" + ("%.0f" % x["t"]) + "s  " + str(x["expand"]) + " at "
                  + ("%.0f" % x["dist_e"]) + "  and  " + str(x["base"]) + " at "
                  + ("%.0f" % x["dist_b"]) + "  (" + ("%+.0f" % x["dt"]) + "s)")
        print()
        if out["one_crew_evidence"]:
            print("  EVIDENCE OF ONE ROAMING CREW doing both jobs. The pool split is")
            print("  then not a partition for this player, so an 'empty expand pool'")
            print("  reading comes from the stated policy, not from the position.")
        else:
            print("  no strong co-location: the pools look like separate crews, so the")
            print("  stated split is a reasonable description of this position.")
        print("  Weak by design: two crews working the same forward area leave the same")
        print("  signature as one crew doing both.")
    return out


def placement_windows(data: dict, step: float = 60.0, until_sec: float = 420.0,
                      same_place: float = 150.0, same_time: float = 30.0,
                      verbose: bool = True) -> dict:
    """The co-location test per window, which is the only way it means anything.

    Run over a whole game the test averages a home cluster where one crew does everything
    against a late game where the crews really are separate, and lands on a number that
    describes neither. Per window it shows the transition."""
    out = []
    t = 0.0
    while t < until_sec:
        r = placement_spread(data, t, min(t + step, until_sec), same_place, same_time,
                             verbose=False)
        if not r.get("note"):
            pp = r.get("per_pool") or {}
            out.append({"from": t, "until": min(t + step, until_sec),
                        "placements": r["placements"],
                        "pairs": r["pairs_in_time"],
                        "colocated": r["pairs_colocated"],
                        "share": r["colocated_share"],
                        "one_crew": r["one_crew_evidence"],
                        "expand_median": (pp.get("expand") or {}).get("median_dist"),
                        "base_median": (pp.get("base") or {}).get("median_dist")})
        t += step
    verdicts = [w for w in out if w["pairs"] >= 4]
    early = [w for w in verdicts if w["one_crew"]]
    res = {"windows": out, "step": step,
           "one_crew_windows": [[w["from"], w["until"]] for w in early],
           "switches_at": (early[-1]["until"] if early and
                           len(early) < len(verdicts) else None)}
    if verbose:
        g = data.get("game") or {}
        print("PLACEMENT WINDOWS  " + str(g.get("id")) + "   " + ("%.0f" % step)
              + "s windows")
        print("  " + "window".ljust(12) + "placed".rjust(7) + "pairs".rjust(7)
              + "co-loc".rjust(8) + "share".rjust(8) + "  expand@  base@   reading")
        for w in out:
            reading = ("ONE CREW" if w["one_crew"] else
                       ("separate" if w["pairs"] >= 4 else "too few to say"))
            print("  " + (("%.0f" % w["from"]) + "-" + ("%.0f" % w["until"]) + "s").ljust(12)
                  + str(w["placements"]).rjust(7) + str(w["pairs"]).rjust(7)
                  + str(w["colocated"]).rjust(8)
                  + (("%7.0f" % (w["share"] * 100)) + "%")
                  + ("%9.0f" % (w["expand_median"] or 0))
                  + ("%7.0f" % (w["base_median"] or 0))
                  + "   " + reading)
        print()
        if res["switches_at"] is not None:
            print("  the crews separate around " + ("%.0f" % res["switches_at"]) + "s.")
            print("  Before that the pool split is NOT a partition, so an 'empty expand")
            print("  pool' there is a fact about the stated policy and not about the game.")
        elif early:
            print("  one crew throughout the measured window: treat the pool split as a")
            print("  lens on one crew's attention, not as separate sets of hands.")
        else:
            print("  no window shows strong co-location, so the split looks real.")
    return res


# ══════════════════════════════════════════════════════════════════════════
# GOAL PLANNER — "four advanced solars from here": when, and is a detour worth it
#
# A fixed end state makes the question definite in a way the open-ended walk never
# was. There is no exit rule to argue about: the objective is the time to N copies,
# and a detour is worth it exactly when it lowers that number.
#
# TWO DIMENSIONS, AND THEY ARE NOT THE SAME QUESTION.
#
#   ABLE      can I pay for the build-power source right now, out of bank plus income,
#             with no stall? `time_to_build(...)["affordable"]`. This is a property of
#             the POSITION and it flips on as income grows.
#   SENSIBLE  does it arrive early enough to repay its own build time out of the copies
#             that are still to come? A turret bought before the last unit saves nothing.
#             This is a property of HOW MUCH WORK IS LEFT and it flips OFF as the goal
#             approaches.
#
# One rises, the other falls, so they cross. Before the crossing you cannot afford it;
# after it, it no longer pays. The window between is where the detour belongs, and it
# can be empty — which is itself the answer.
#
# The grid is (how many sources) x (insert after which copy), every cell a full
# re-simulation, so the recommendation is read off measured finish times rather than
# argued from a rate.
# ══════════════════════════════════════════════════════════════════════════

def _run_goal(state: "EcoState", goal: str, count: int, bp_source: str, n_src: int,
              after: int, pools: Optional["BpPools"], assign: str,
              budget: Optional[dict]) -> dict:
    """Build `after` copies, then `n_src` build-power sources, then the rest."""
    st = state.copy()
    pl = pools.copy() if pools is not None else None
    t0 = st.t
    legs: List[dict] = []
    stalled_src = False
    src_start_t = None

    def bp_for(unit):
        return pool_bp_for(unit, pl)["bp"] if pl is not None else None

    def one(unit, kind):
        nonlocal st, pl, stalled_src, src_start_t
        b = bp_for(unit)
        if b is not None and b <= 0:
            return False
        info = time_to_build(st, unit, b)
        if info["seconds"] == float("inf"):
            return False
        if kind == "source":
            if src_start_t is None:
                src_start_t = round(st.t - t0, 2)
            if not info["affordable"]:
                stalled_src = True
        nxt, r = st.build_fed(unit, bp=b)
        st = nxt
        if pl is not None:
            pl = pools_after(pl, unit, assign)
        legs.append({"kind": kind, "unit": unit, "t": round(st.t - t0, 2),
                     "dt": round(r["total_sec"], 2), "bound": r["bound"],
                     "stall": round(r["stall"], 2), "bp": (b if b is not None else st.bp),
                     "affordable": info["affordable"]})
        return True

    made = 0
    for _ in range(min(after, count)):
        if not one(goal, "goal"):
            return {"ok": False, "why": "cannot build " + goal}
        made += 1
    for _ in range(max(0, n_src)):
        if not one(bp_source, "source"):
            return {"ok": False, "why": "cannot build " + bp_source}
    while made < count:
        if not one(goal, "goal"):
            return {"ok": False, "why": "cannot build " + goal}
        made += 1
    gl = [l for l in legs if l["kind"] == "goal"]
    return {"ok": True, "n_src": n_src, "after": after, "legs": legs,
            "total": round(st.t - t0, 2), "src_start_t": src_start_t,
            "src_stalled": stalled_src, "end": st,
            "goal_stall": round(sum(l["stall"] for l in gl), 2),
            "goal_bound": sorted({l["bound"] for l in gl if l["bound"] != "none"}),
            "goal_times": [l["t"] for l in legs if l["kind"] == "goal"]}


def goal_plan(state: "EcoState", goal: str = "AdvSolar", count: int = 4,
              bp_source: str = "ConTurret", max_sources: int = 3,
              pools: Optional["BpPools"] = None, assign: str = "base",
              budget: Optional[dict] = None, verbose: bool = True) -> dict:
    """Time to `count` copies of `goal`, and where a build-power detour pays."""
    mism = cross_relieves(bp_source, goal, assign) if pools is not None else None
    grid: Dict[int, Dict[int, dict]] = {}
    for k in range(max_sources + 1):
        grid[k] = {}
        for j in range(count + 1):
            if k == 0 and j > 0:
                continue
            r = _run_goal(state, goal, count, bp_source, k, j, pools, assign, budget)
            grid[k][j] = r
    base = grid[0].get(0) or {}
    base_t = base.get("total")

    cells = [(k, j, r) for k, d in grid.items() for j, r in d.items() if r.get("ok")]
    feasible = [(k, j, r) for k, j, r in cells if not r["src_stalled"]]
    best = min(feasible or cells, key=lambda x: x[2]["total"]) if cells else None

    # DIMENSION 1: the earliest insertion point where the source is payable with no stall
    able_at = None
    for j in range(count + 1):
        r = grid.get(1, {}).get(j)
        if r and r.get("ok") and not r["src_stalled"]:
            able_at = j
            break
    # DIMENSION 2: the latest insertion point that still beats the baseline
    sensible_to = None
    for j in range(count + 1):
        r = grid.get(1, {}).get(j)
        if r and r.get("ok") and base_t is not None and r["total"] < base_t - 1e-9:
            sensible_to = j
    window = ([] if able_at is None or sensible_to is None or able_at > sensible_to
              else list(range(able_at, sensible_to + 1)))

    out = {"goal": goal, "count": count, "bp_source": bp_source,
           "baseline_total": base_t, "grid": grid, "best": None if not best else
           {"sources": best[0], "after": best[1], "total": best[2]["total"],
            "saved": (None if base_t is None else round(base_t - best[2]["total"], 2))},
           "able_from": able_at, "sensible_until": sensible_to, "window": window,
           "mismatch": mism}

    if verbose:
        T = OBJECTS[goal]
        S = OBJECTS[bp_source]
        bp_goal = (pool_bp_for(goal, pools)["bp"] if pools is not None else state.bp)
        print("GOAL  " + str(count) + " x " + goal + "  from t=" + ("%.0f" % state.t)
              + "s   " + ("%.2f" % state.m_inc) + " M/s  " + ("%.0f" % state.e_inc)
              + " E/s   " + ("%.0f" % bp_goal) + " BP on it"
              + ("  (" + pool_bp_for(goal, pools)["work_pool"] + " pool)"
                 if pools is not None else ""))
        print("  " + goal + " costs " + ("%g" % T.metal_cost) + "m "
              + ("%g" % T.energy_cost) + "e " + ("%g" % T.bp_cost) + " BP-s;  "
              + bp_source + " costs " + ("%g" % S.metal_cost) + "m "
              + ("%g" % S.energy_cost) + "e and adds " + ("%g" % S.bp_income) + " BP")
        if mism and not mism["relieves"]:
            print()
            print("  *** " + bp_source + " CANNOT SPEED THIS UP: " + mism["why"])
        if base_t is None:
            print("  the baseline cannot even be built from here")
            return out
        print()
        print("  baseline, no detour: " + ("%.1f" % base_t) + "s to all "
              + str(count) + "   (" + ", ".join(("%.0f" % t) + "s"
                                                for t in base["goal_times"]) + ")")
        nominal = OBJECTS[goal].bp_cost / bp_goal if bp_goal else float("inf")
        if base.get("goal_stall", 0) > 0.5:
            print("  THE GOAL ITSELF IS STALLING: " + ("%.0f" % base["goal_stall"])
                  + "s of the " + ("%.0f" % base_t) + "s, bound by "
                  + ", ".join(base["goal_bound"]) + ".")
            print("  " + ("%.0f" % bp_goal) + " BP on " + goal + " would want "
                  + ("%.0f" % drain_rates(goal, bp_goal)["e_per_s"]) + " E/s and "
                  + ("%.2f" % drain_rates(goal, bp_goal)["m_per_s"]) + " M/s; income is "
                  + ("%.0f" % state.e_inc) + " E/s and " + ("%.2f" % state.m_inc) + " M/s.")
            print("  More build power cannot help a build that income already cannot feed,")
            print("  which is why the detour column below only ever adds time.")
        else:
            print("  nominal " + ("%.1f" % nominal) + "s each and no stall: build power"
                  + " is the binding constraint, so a detour can pay")
        print()
        print("  total time to the goal, by detour  (rows = how many " + bp_source
              + ", columns = insert after the jth " + goal + ")")
        print("  " + "".ljust(8) + "".join(("j=" + str(j)).rjust(9)
                                           for j in range(count + 1)))
        for k in range(max_sources + 1):
            line = ("k=" + str(k)).ljust(8)
            for j in range(count + 1):
                r = grid.get(k, {}).get(j)
                if not r:
                    line += "".rjust(9)
                elif not r.get("ok"):
                    line += "n/a".rjust(9)
                else:
                    mark = "!" if r["src_stalled"] else (
                        "*" if best and (k, j) == (best[0], best[1]) else " ")
                    line += (("%.0f" % r["total"]) + "s" + mark).rjust(9)
            print("  " + line)
        print("  * = best   ! = the " + bp_source + " would STALL there (not payable yet)")
        print()
        print("  DIMENSION 1 - ABLE:     " + (
            "payable with no stall from j=" + str(able_at) + " onward"
            if able_at is not None else
            "never payable without stalling inside this goal"))
        print("  DIMENSION 2 - SENSIBLE: " + (
            "still beats the baseline up to j=" + str(sensible_to)
            if sensible_to is not None else
            "never beats the baseline - the detour costs more than it returns"))
        if window:
            print("  CROSSOVER: both true for j=" + str(window[0])
                  + (" to j=" + str(window[-1]) if len(window) > 1 else "")
                  + "  -> that is where the " + bp_source + " belongs")
        else:
            print("  CROSSOVER: EMPTY. Able and sensible never overlap inside this goal,")
            print("  so build the " + str(count) + " " + goal
                  + " straight through and buy build power for the NEXT job.")
        if best:
            print()
            print("  BEST: " + str(best[0]) + " x " + bp_source + " after "
                  + str(best[1]) + " x " + goal + "  ->  "
                  + ("%.1f" % best[2]["total"]) + "s"
                  + ("  (" + ("%+.1f" % (best[2]["total"] - base_t)) + "s vs baseline)"))
            if best[0] > 0:
                print("  " + ", ".join(
                    (l["unit"][:9] + " +" + ("%.0f" % l["dt"]) + "s")
                    for l in best[2]["legs"]))
    return out


# ══════════════════════════════════════════════════════════════════════════
# CONCENTRATION — n workers on ONE project, or one project each
#
# Both policies finish the n-th copy at the same instant, so a count at the end
# shows nothing. The difference is entirely in WHEN the earlier copies land, and an
# earlier generator generates.
#
#   together      one completion every tau = W / (n*b)
#   independent   n completions together every n*tau = W / b
#
# So the extra copies STANDING at time t is
#
#     D(t) = floor(t / tau)  mod  n
#
# which for two workers is 0, +1, 0, +1, ... and averages (n-1)/2 forever. Two
# workers on one wind are permanently half a wind ahead; three workers are a full
# wind ahead. Nothing is built faster in total — the lead is bought purely by
# ordering, and it never decays.
#
# WHAT THE LEAD IS WORTH. Half a turbine of output, held forever, is income; income
# reinvested is growth. A turbine repays its whole price in TROI seconds
# (`ObjectType.troi` = (metal*70 + energy) / output = 250 s for wind at 11.9 E/s),
# so the natural unit is the ROI segment, and one worker's build time W/b is
# W/b / TROI of one — 20/250 = 1/12.5 for a con bot on a wind.
#
# Compounding that lead gives extra standing output
#
#     (n-1)/2 * exp(t / TROI)
#
# because reinvesting at a rate of one price per TROI is exponential by definition.
# Stepping it a segment at a time with a fixed +1 segment/TROI per step is the Euler
# approximation of that exponential: right to first order, and it undershoots later.
# ══════════════════════════════════════════════════════════════════════════

def concentration_advantage(unit: str = "Wind", workers: int = 2,
                            bp_each: Optional[float] = None,
                            wind: Optional[float] = None, segments: int = 12,
                            state: Optional["EcoState"] = None,
                            builder: str = "BotWorker",
                            verbose: bool = True) -> dict:
    """What concentrating n builders on one `unit` is worth against splitting them.

    Timing only — both policies deliver the same build work. `state`, if given, is
    checked for the one way concentration can actually lose: n builders on one
    target draw n times the metal and energy per second, so the pooled build can
    stall where the split builds would not."""
    t = OBJECTS[unit]
    n = max(1, int(workers))
    b = float(bp_each if bp_each is not None else
              (OBJECTS[builder].bp_income if builder in OBJECTS else DEFAULT_BUILDER_BP))
    W = t.bp_cost
    if W <= 0 or b <= 0:
        return {"note": unit + " has no build work, or the builder has no build power"}
    tau = W / (n * b)                      # together: one completion every tau
    t_alone = W / b                        # independent: one completion per builder
    out = wind if (t.wind_powered and wind is not None) else (
        state.wind if (t.wind_powered and state is not None) else
        (DEFAULT_WIND if t.wind_powered else t.energy_income))
    cost_ee = t.metal_cost * ENERGY_PER_METAL + t.energy_cost
    troi = (cost_ee / out) if out > 0 else float("inf")

    # the pattern, and the exact integral of it
    pattern = [k % n for k in range(int(segments))]
    mean_lead = (n - 1) / 2.0
    lead_sec_per_cycle = tau * n * (n - 1) / 2.0        # unit-seconds gained per cycle
    cycle = n * tau
    extra_e_per_s = out * mean_lead

    # discrete check: integrate D(t) rather than trusting the closed form
    dt = tau / 400.0
    acc, steps = 0.0, int(round(cycle * 6 / dt))
    for i in range(steps):
        tt = (i + 0.5) * dt
        acc += ((int(tt // tau)) % n) * dt
    sim_mean = acc / (steps * dt)

    ws_worker = (t_alone / troi) if troi else 0.0       # the user's WS: 20/250 = 1/12.5
    ws_segment = (tau / troi) if troi else 0.0          # per pattern segment: 10/250
    free_unit_sec = (troi / mean_lead) if mean_lead > 0 else float("inf")

    rows = []
    for k, d in enumerate(pattern):
        t_end = (k + 1) * tau
        linear = mean_lead * (1.0 + t_end / troi) if troi else mean_lead
        exact = mean_lead * math.exp(t_end / troi) if troi else mean_lead
        rows.append({"segment": k, "t_start": round(k * tau, 3),
                     "t_end": round(t_end, 3), "lead": d,
                     "lead_compounded_linear": round(linear, 4),
                     "lead_compounded_exact": round(exact, 4),
                     "ws_elapsed": round(t_end / troi, 4) if troi else None})

    res = {"unit": unit, "workers": n, "bp_each": b, "bp_cost": W,
           "tau": tau, "t_alone": t_alone, "output": out,
           "cost_energy_equiv": cost_ee, "troi": troi,
           "pattern": pattern, "mean_lead": mean_lead,
           "mean_lead_simulated": round(sim_mean, 6),
           "lead_unit_seconds_per_cycle": lead_sec_per_cycle, "cycle": cycle,
           "extra_energy_per_s": extra_e_per_s,
           "ws_per_worker_build": ws_worker, "ws_per_segment": ws_segment,
           "segments_per_roi": (troi / t_alone) if t_alone else None,
           "free_unit_after_sec": free_unit_sec,
           "rows": rows, "stall": None}

    # the one way concentration loses: n times the drain on one target
    if state is not None:
        one = time_to_build(state, unit, b)
        many = time_to_build(state, unit, n * b)
        res["stall"] = {
            "split": {"seconds": one["seconds"], "stall": one["stall"],
                      "bound": one["bound"], "affordable": one["affordable"]},
            "pooled": {"seconds": many["seconds"], "stall": many["stall"],
                       "bound": many["bound"], "affordable": many["affordable"]},
            "pooled_loses": bool(many["stall"] > 1e-6 and one["stall"] <= 1e-6),
            "effective_tau": many["seconds"]}

    if verbose:
        print("CONCENTRATION  " + str(n) + " x " + str(builder) + " at "
              + ("%g" % b) + " BP on " + unit + " (" + ("%g" % W) + " BP-s, "
              + ("%g" % t.metal_cost) + "m " + ("%g" % t.energy_cost) + "e, "
              + ("%.1f" % out) + " E/s)")
        print("  together     one every " + ("%.2f" % tau) + "s")
        print("  independent  " + str(n) + " every " + ("%.2f" % t_alone) + "s")
        print("  both finish copy #" + str(n) + " at " + ("%.2f" % t_alone)
              + "s, so a count at the end shows nothing")
        print()
        print("  extra copies STANDING, per " + ("%.2f" % tau) + "s segment:")
        print("    [" + ", ".join(("+" + str(d)) if d else "0" for d in pattern) + "]")
        print("    mean " + ("%.3f" % mean_lead) + " (simulated "
              + ("%.3f" % sim_mean) + ")   = (n-1)/2, held forever")
        print("    " + ("%.1f" % lead_sec_per_cycle) + " " + unit
              + "-seconds gained per " + ("%.0f" % cycle) + "s cycle = "
              + ("%.2f" % extra_e_per_s) + " E/s on average")
        print()
        print("  " + unit + " repays " + ("%g" % cost_ee)
              + " energy-equivalents (" + ("%g" % t.metal_cost) + " metal x "
              + str(ENERGY_PER_METAL) + " + " + ("%g" % t.energy_cost) + " energy)")
        print("    TROI " + ("%.1f" % troi) + "s   one worker-build "
              + ("%.0f" % t_alone) + "s = 1/" + ("%.1f" % (troi / t_alone))
              + " of it   (WS = " + ("%.4f" % ws_worker) + ")")
        print("    one pattern segment " + ("%.0f" % tau) + "s = "
              + ("%.4f" % ws_segment) + " of an ROI = half a WS")
        print()
        print("  " + "seg".rjust(4) + "t_end".rjust(8) + "lead".rjust(6)
              + "WS elapsed".rjust(12) + "linear".rjust(9) + "exact".rjust(9))
        for r in rows:
            print("  " + str(r["segment"]).rjust(4) + ("%8.0f" % r["t_end"])
                  + ("%6d" % r["lead"]) + ("%12.3f" % (r["ws_elapsed"] or 0))
                  + ("%9.3f" % r["lead_compounded_linear"])
                  + ("%9.3f" % r["lead_compounded_exact"]))
        print()
        print("  a free " + unit + " every " + ("%.0f" % free_unit_sec)
              + "s from the lead alone (TROI / " + ("%.1f" % mean_lead) + ")")
        if res["stall"]:
            st = res["stall"]
            print()
            print("  RESOURCES: pooling draws " + str(n) + "x per second.")
            print("    split  " + ("%.2f" % st["split"]["seconds"]) + "s, stall "
                  + ("%.2f" % st["split"]["stall"]) + "s, bound "
                  + str(st["split"]["bound"]))
            print("    pooled " + ("%.2f" % st["pooled"]["seconds"]) + "s, stall "
                  + ("%.2f" % st["pooled"]["stall"]) + "s, bound "
                  + str(st["pooled"]["bound"]))
            if st["pooled_loses"]:
                print("    -> POOLING STALLS HERE AND SPLITTING DOES NOT. The timing")
                print("       lead is real but this position cannot pay for it yet.")
            else:
                print("    -> both affordable, so the timing lead is the whole story")
    return res


# ══════════════════════════════════════════════════════════════════════════
# BUILD POWER IS THREE POOLS
#
# One "BP" number is a fiction: the points are not interchangeable, because what a
# point may legally build and what it is standing next to both matter.
#
#   EXPAND    claiming metal spots. Highest priority: it raises the ceiling every
#             other pool works under, and it is the only work that contains a walk.
#   FACTORY   a factory's own points. They can build ONLY factory products
#             (econ_model.json `factoryProducts`), and the pool is BINARY - a factory
#             is producing or it is idle. Base points may ASSIST it.
#   BASE      con turrets, workers at home, the commander when it is at home. Builds
#             infrastructure and energy generation, assists the factory, or gives up a
#             worker to the expand pool, which then walks to the next spot.
#
# WHERE A BUILDER SITS IS NOT IN THE STREAM, so the split is a stated policy, not a
# measurement — `split_bp` takes it as arguments and prints what it assumed. What CAN
# be measured is how much build power a recorded game actually applied to each kind of
# work, which is `bp_delivered`, and it is cross-checked against the engine's own
# `bp_used`.
# ══════════════════════════════════════════════════════════════════════════

# which pool a piece of work belongs to. Factory products are decided by
# FACTORY_PRODUCTS, extractors are the expansion, everything else is base work.
EXPAND_UNITS = ("Mex", "AMex")


def work_pool(unit: str) -> str:
    """Which pool's work this is."""
    if wants_factory(unit):
        return "factory"
    if unit in EXPAND_UNITS:
        return "expand"
    return "base"


@dataclass
class BpPools:
    """Build power split by what it may legally do and where it is standing."""
    expand: float = 0.0
    factory: float = 0.0
    base: float = 0.0
    factory_on: bool = True
    assist: float = 0.0          # fraction of BASE lent to the factory
    detail: Dict[str, dict] = field(default_factory=dict)
    policy: Dict[str, object] = field(default_factory=dict)

    @property
    def total(self) -> float:
        return self.expand + self.factory + self.base

    @property
    def factory_live(self) -> float:
        return self.factory if self.factory_on else 0.0

    def copy(self) -> "BpPools":
        return BpPools(self.expand, self.factory, self.base, self.factory_on,
                       self.assist, {k: dict(v) for k, v in self.detail.items()},
                       dict(self.policy))


def split_bp(counts: Dict[str, int], expanding: int = 0,
             commander: str = "base", factory_on: bool = True,
             assist: float = 0.0, bp_override: Optional[float] = None) -> BpPools:
    """Assign the standing builders to pools under a STATED policy.

    `expanding` is how many mobile workers are out claiming; `commander` is "base" or
    "expand". Nothing here infers position from the stream, because the stream does not
    carry it — the policy is an argument and is reported back in `policy`."""
    pools = BpPools(factory_on=factory_on, assist=max(0.0, min(1.0, assist)))
    left_to_expand = max(0, int(expanding))
    for unit, n in sorted(counts.items()):
        t = OBJECTS.get(unit)
        if not t or not t.bp_income or n <= 0:
            continue
        bp = t.bp_income * n
        if t.factory:
            pools.factory += bp
            where = "factory"
        elif unit == "Commander":
            if commander == "expand":
                pools.expand += bp
                where = "expand"
            else:
                pools.base += bp
                where = "base"
        elif (t.speed or 0) > 0:
            take = min(n, left_to_expand)
            left_to_expand -= take
            pools.expand += t.bp_income * take
            pools.base += t.bp_income * (n - take)
            where = ("expand x" + str(take) + " / base x" + str(n - take)
                     if take else "base")
        else:
            pools.base += bp
            where = "base"
        pools.detail[unit] = {"count": n, "bp_each": t.bp_income, "bp": bp,
                              "where": where, "mobile": bool((t.speed or 0) > 0),
                              "factory": bool(t.factory)}
    pools.policy = {"expanding": int(expanding), "commander": commander,
                    "factory_on": bool(factory_on), "assist": pools.assist,
                    "unassigned_expand_slots": left_to_expand}
    if bp_override is not None and pools.total > 0:
        k = float(bp_override) / pools.total
        pools.expand *= k
        pools.factory *= k
        pools.base *= k
        pools.policy["scaled_to"] = float(bp_override)
    return pools


def pool_bp_for(unit: str, pools: BpPools) -> dict:
    """The build power that may legally work on `unit`, and where it comes from."""
    w = work_pool(unit)
    if w == "factory":
        live = pools.factory_live
        lent = pools.base * pools.assist
        return {"bp": live + lent, "work_pool": w,
                "from": {"factory": live, "base_assist": lent},
                "why": ("only a factory can make " + unit
                        + (" - the factory is OFF" if not pools.factory_on else "")
                        + (", base is assisting" if lent else ""))}
    if w == "expand":
        return {"bp": pools.expand, "work_pool": w,
                "from": {"expand": pools.expand},
                "why": "expansion work, done by the builders that are out walking"}
    usable = pools.base * (1.0 - pools.assist)
    return {"bp": usable, "work_pool": w, "from": {"base": usable},
            "why": ("base work" + (", less the "
                    + ("%.0f" % (pools.assist * 100)) + "% lent to the factory"
                    if pools.assist else ""))}


def reassign_to_expand(pools: BpPools, n: int = 1,
                       worker: str = "BotWorker") -> BpPools:
    """Send `n` base workers out to claim: their points move base -> expand.

    This is the transition the base pool can always make, and it is why base build
    power is worth more than its raw number suggests."""
    out = pools.copy()
    t = OBJECTS.get(worker)
    if not t or not t.bp_income:
        return out
    move = min(out.base, t.bp_income * max(0, int(n)))
    out.base -= move
    out.expand += move
    out.policy = dict(out.policy)
    out.policy["reassigned"] = out.policy.get("reassigned", 0) + move / t.bp_income
    return out


def joins_pool(unit: str, assign: str = "base") -> str:
    """Which pool this unit's build power would join once it is standing."""
    t = OBJECTS.get(unit)
    if not t or not t.bp_income:
        return "none"
    if t.factory:
        return "factory"
    if (t.speed or 0) > 0 and assign == "expand":
        return "expand"
    return "base"


def cross_relieves(bp_source: str, on: str, assign: str = "base") -> dict:
    """Can buying `bp_source` actually relieve the pool that does `on` work?

    A con turret is immobile: its points join BASE and can never claim a metal spot. So
    with expansion as the reference work, a con-turret cross never touches the binding
    pool, the saturation ratio stays pinned, and the walk buys hands that cannot do the
    job. The ratio that comes out looks like an answer and is not one."""
    joins = joins_pool(bp_source, assign)
    needs = work_pool(on)
    ok = (joins == needs)
    return {"source": bp_source, "joins": joins, "work": on, "needs": needs,
            "relieves": ok,
            "why": ("" if ok else
                    (bp_source + "'s build power joins the " + joins + " pool, but "
                     + on + " is " + needs + " work. Buying it cannot relieve the pool "
                     + "that is bound"
                     + (". A con turret is immobile, so it can never claim a spot"
                        if joins == "base" and needs == "expand" else "")
                     + (". Try --assign expand with a mobile builder"
                        if needs == "expand" and (OBJECTS.get(bp_source)
                                                  and (OBJECTS[bp_source].speed or 0) > 0)
                        else "")))}


def pools_after(pools: "BpPools", unit: str, assign: str = "base") -> "BpPools":
    """The pools once `unit` is standing.

    A con turret is fixed at home, so it joins BASE. A mobile worker can go either way,
    which is what `assign` decides - and that choice is the whole difference between
    buying hands for the base and buying hands for the expansion."""
    out = pools.copy()
    t = OBJECTS.get(unit)
    if not t or not t.bp_income:
        return out
    if t.factory:
        out.factory += t.bp_income
    elif (t.speed or 0) > 0 and assign == "expand":
        out.expand += t.bp_income
    else:
        out.base += t.bp_income
    d = dict(out.detail.get(unit) or {"count": 0, "bp_each": t.bp_income, "bp": 0.0,
                                      "mobile": bool((t.speed or 0) > 0),
                                      "factory": bool(t.factory)})
    d["count"] = int(d.get("count", 0)) + 1
    d["bp"] = float(d.get("bp", 0.0)) + t.bp_income
    d["where"] = ("factory" if t.factory
                  else ("expand" if ((t.speed or 0) > 0 and assign == "expand") else "base"))
    out.detail[unit] = d
    return out


def pools_from_game(data: dict, at_sec: float, expanding: int = 0,
                    commander: str = "base", factory_on: bool = True,
                    assist: float = 0.0, scale_to_measured: bool = True) -> BpPools:
    """The pools for a recorded position, scaled to the engine's own bp_avail."""
    st = state_from_game(data, at_sec)
    return split_bp(st.counts, expanding=expanding, commander=commander,
                    factory_on=factory_on, assist=assist,
                    bp_override=(st.bp if scale_to_measured else None))


_DEF_DB: Dict[str, dict] = {}


def def_db() -> Dict[str, dict]:
    """The unit-def table, from the database, loaded once.

    Build times live in `econ.db` (see econ_db.py), not in a JSON dump: the dumps are
    still the source on disk, but a lookup is a query and the row carries the file it
    won from. If the database has not been seeded this falls back to the dumps so
    nothing breaks, and says nothing, because the answer is identical."""
    global _DEF_DB
    if _DEF_DB:
        return _DEF_DB
    try:
        import econ_db as _DB
        _DB.ensure_defs(verbose=False)
        _DEF_DB = _DB.defs_table()
    except Exception:                                              # noqa: BLE001
        _DEF_DB = {k: {"build_time": v.get("buildTime"),
                       "speed": v.get("speed"),
                       "is_extractor": 1 if (v.get("isMetalExtractor")
                                             or v.get("extractsMetal")) else 0}
                   for k, v in (ED.engine_defs() or {}).items()}
    return _DEF_DB


def def_build_work(def_name: Optional[str], unit_type: Optional[str] = None) -> float:
    """Build work in BP-seconds for any engine def, modelled or not."""
    if unit_type and unit_type in OBJECTS and OBJECTS[unit_type].bp_cost > 0:
        return OBJECTS[unit_type].bp_cost
    row = def_db().get(def_name or "") or {}
    try:
        return float(row.get("build_time") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def def_work_pool(def_name: Optional[str], unit_type: Optional[str] = None) -> str:
    """Which pool built it, decided from engine data rather than a hand list.

    An extractor is expansion. Anything that moves came out of a factory. Everything
    else is base work - including a factory itself, which base builds and which only
    then has a pool of its own."""
    if unit_type == "Commander":
        return "base"
    if unit_type and unit_type in OBJECTS:
        return work_pool(unit_type)
    row = def_db().get(def_name or "") or {}
    if row.get("work_pool"):
        return str(row["work_pool"])
    if row.get("is_extractor"):
        return "expand"
    try:
        if float(row.get("speed") or 0) > 0:
            return "factory"
    except (TypeError, ValueError):
        pass
    return "base"


def bp_delivered(data: dict, from_sec: float = 0.0, until_sec: float = 600.0,
                 verbose: bool = True) -> dict:
    """How much build power the game ACTUALLY applied to each pool's work.

    Build work is conserved: a completion delivered exactly its `bp_cost`. Summing the
    completions in a window and dividing by the window is therefore the average build
    power that was working, and splitting that sum by `work_pool` is the real pool
    split — measured, not assumed.

    Two caveats stated rather than hidden: a unit still under construction when the
    window closes contributes nothing, and one that started before it opened
    contributes all of its work here, so short windows are noisy. The total is
    cross-checked against the engine's own `bp_used`, which is the honest referee."""
    span = max(1e-9, until_sec - from_sec)
    per_unit: Dict[str, dict] = {}
    per_pool = {"expand": 0.0, "factory": 0.0, "base": 0.0}
    unresolved: Dict[str, int] = {}
    done_ids = set()
    for c in (data.get("completions") or []):
        if not (from_sec <= c["t"] <= until_sec):
            continue
        done_ids.add(c.get("unitID"))
        u, dn = c.get("type"), c.get("def")
        w = def_build_work(dn, u)
        if w <= 0:
            unresolved[dn or "?"] = unresolved.get(dn or "?", 0) + 1
            continue
        pool = def_work_pool(dn, u)
        per_pool[pool] += w
        key = u or (dn or "?")
        r = per_unit.setdefault(key, {"count": 0, "bp_work": 0.0, "pool": pool,
                                      "modelled": bool(u)})
        r["count"] += 1
        r["bp_work"] += w
    # work still inside a nanoframe when the window shuts: counted as an explicit
    # upper bound, never folded into the measurement
    wip_work = 0.0
    wip: Dict[str, int] = {}
    for c in (data.get("starts") or []):
        if not (from_sec <= c["t"] <= until_sec):
            continue
        if c.get("unitID") in done_ids:
            continue
        w = def_build_work(c.get("def"), c.get("type"))
        if w <= 0:
            continue
        wip_work += w
        k = c.get("type") or c.get("def") or "?"
        wip[k] = wip.get(k, 0) + 1
    econ = [r for r in (data.get("econ") or []) if from_sec <= r["t"] <= until_sec]
    used = [r.get("bp_used") or 0.0 for r in econ]
    avail = [r.get("bp_avail") or 0.0 for r in econ]
    mean_used = sum(used) / len(used) if used else None
    mean_avail = sum(avail) / len(avail) if avail else None
    total_bp = sum(per_pool.values()) / span
    out = {"from": from_sec, "until": until_sec, "span": span,
           "unresolved": unresolved,
           "wip_units": wip, "wip_bp_upper": round(wip_work / span, 1),
           "bp_applied": {k: round(v / span, 1) for k, v in per_pool.items()},
           "bp_applied_total": round(total_bp, 1),
           "share": {k: (round(v / sum(per_pool.values()), 4)
                         if sum(per_pool.values()) else 0.0)
                     for k, v in per_pool.items()},
           "mean_bp_used": (None if mean_used is None else round(mean_used, 1)),
           "mean_bp_avail": (None if mean_avail is None else round(mean_avail, 1)),
           "per_unit": {k: {"count": v["count"], "pool": v["pool"],
                            "modelled": v.get("modelled", True),
                            "bp": round(v["bp_work"] / span, 1)}
                        for k, v in sorted(per_unit.items(),
                                           key=lambda kv: -kv[1]["bp_work"])}}
    if mean_used:
        out["vs_engine"] = round(total_bp / mean_used, 3)
        out["vs_engine_with_wip"] = round((total_bp + wip_work / span) / mean_used, 3)
    if mean_avail:
        out["utilisation"] = round(total_bp / mean_avail, 3)
    if verbose:
        g = data.get("game") or {}
        print("BUILD POWER DELIVERED  " + str(g.get("id")) + "   "
              + ("%.0f" % from_sec) + "-" + ("%.0f" % until_sec) + "s")
        print("  work finished in the window, divided by the window = the build power")
        print("  that was really working, split by which pool's work it was.")
        print()
        print("  " + "pool".ljust(10) + "BP applied".rjust(11) + "share".rjust(8)
              + "   what was built")
        for k in ("expand", "factory", "base"):
            units = [u + " x" + str(v["count"]) for u, v in out["per_unit"].items()
                     if v["pool"] == k]
            print("  " + k.ljust(10) + ("%11.0f" % out["bp_applied"][k])
                  + ("%7.0f" % (out["share"][k] * 100)) + "%"
                  + "   " + (", ".join(units) if units else "-"))
        print("  " + "TOTAL".ljust(10) + ("%11.0f" % out["bp_applied_total"]))
        if wip:
            print("  " + "in progress".ljust(10) + ("%11.0f" % out["wip_bp_upper"])
                  + "          upper bound, unfinished at the window edge: "
                  + ", ".join(k + " x" + str(v) for k, v in sorted(wip.items())))
        print()
        if mean_used is not None:
            print("  engine's own bp_used averaged " + ("%.0f" % mean_used)
                  + " over the window; completions alone say "
                  + ("%.0f" % total_bp) + " ("
                  + ("%.2f" % out.get("vs_engine", 0)) + "x), and "
                  + ("%.0f" % (total_bp + wip_work / span)) + " ("
                  + ("%.2f" % out.get("vs_engine_with_wip", 0))
                  + "x) if every unfinished nanoframe were complete")
            print("  the rest is assist, repair and reclaim, which bp_used also counts")
        if unresolved:
            print("  NOT COUNTED - no buildTime in the dump: "
                  + ", ".join(k + " x" + str(v) for k, v in sorted(unresolved.items())))
        if mean_avail is not None:
            print("  bp_avail averaged " + ("%.0f" % mean_avail)
                  + ", so utilisation was " + ("%.0f" % (out["utilisation"] * 100)) + "%")
        print()
        print("  per unit:")
        print("  " + "unit".ljust(12) + "pool".ljust(9) + "count".rjust(6)
              + "BP applied".rjust(12) + "   ")
        for u, v in out["per_unit"].items():
            print("  " + u.ljust(12) + v["pool"].ljust(9) + ("%6d" % v["count"])
                  + ("%12.0f" % v["bp"])
                  + ("" if v.get("modelled", True) else "   (engine def, not modelled)"))
    return out


def print_pools(pools: BpPools, targets: Sequence[str] = ("Mex", "Wind", "Solar",
                                                          "BotWorker", "ConTurret")) -> None:
    """The split, the policy behind it, and what each pool may legally build."""
    print("BUILD POWER POOLS   total " + ("%.0f" % pools.total)
          + ("   (scaled to the engine's bp_avail)"
             if "scaled_to" in pools.policy else ""))
    print("  EXPAND  " + ("%6.0f" % pools.expand) + "   highest priority: claiming spots")
    print("  FACTORY " + ("%6.0f" % pools.factory) + "   "
          + ("PRODUCING" if pools.factory_on else "IDLE - binary, and it is off")
          + ", factory products only")
    print("  BASE    " + ("%6.0f" % pools.base) + "   infrastructure and energy"
          + (", " + ("%.0f" % (pools.assist * 100)) + "% lent to the factory"
             if pools.assist else ""))
    print()
    print("  policy: " + ", ".join(str(k) + "=" + str(v)
                                   for k, v in sorted(pools.policy.items())))
    print("  (where a builder stands is not in the stream, so this is stated, not measured)")
    print()
    print("  " + "builder".ljust(12) + "count".rjust(6) + "bp each".rjust(9)
          + "total".rjust(8) + "   assigned to")
    for u, v in sorted(pools.detail.items()):
        print("  " + u.ljust(12) + ("%6d" % v["count"]) + ("%9.0f" % v["bp_each"])
              + ("%8.0f" % v["bp"]) + "   " + str(v["where"]))
    print()
    print("  what each target may draw on:")
    print("  " + "target".ljust(12) + "pool".ljust(9) + "BP".rjust(7) + "   why")
    for u in targets:
        if u not in OBJECTS:
            continue
        r = pool_bp_for(u, pools)
        print("  " + u.ljust(12) + r["work_pool"].ljust(9) + ("%7.0f" % r["bp"])
              + "   " + r["why"])


def implied_share(data: dict, unit: str = "Wind", from_sec: float = 0.0,
                  until_sec: float = 900.0, min_pairs: int = 3,
                  verbose: bool = False) -> dict:
    """What fraction of build power a recorded game actually pointed at `unit`.

    Between two consecutive completions the player delivered one unit's build work, so
    the build power ON THAT WORK was bp_cost / gap. Against the build power the team
    HAD at that moment, that is the share. Back-to-back completions inside a second are
    parallel builds finishing together, not a fast one, so they are excluded."""
    comps = sorted((c for c in (data.get("completions") or [])
                    if c.get("type") == unit and from_sec <= c["t"] <= until_sec),
                   key=lambda c: c["t"])
    W = OBJECTS[unit].bp_cost
    econ = data.get("econ") or []
    rows = []
    for a, b in zip(comps, comps[1:]):
        gap = b["t"] - a["t"]
        if gap < 1.0:                      # parallel finish, not a cadence
            continue
        avail = None
        for r in econ:
            if r["t"] <= b["t"]:
                avail = r.get("bp_avail")
            else:
                break
        if not avail:
            continue
        rows.append({"t": round(b["t"], 1), "gap": round(gap, 2),
                     "bp_on_work": round(W / gap, 1), "bp_avail": avail,
                     "share": round(min(1.0, W / gap / avail), 4)})
    if len(rows) < min_pairs:
        return {"unit": unit, "pairs": len(rows), "share": None, "rows": rows,
                "note": "not enough spaced completions to measure"}
    sh = sorted(r["share"] for r in rows)
    gaps = sorted(r["gap"] for r in rows)
    med = sh[len(sh) // 2] if len(sh) % 2 else (sh[len(sh) // 2 - 1] + sh[len(sh) // 2]) / 2
    mg = gaps[len(gaps) // 2] if len(gaps) % 2 else (gaps[len(gaps) // 2 - 1] + gaps[len(gaps) // 2]) / 2
    out = {"unit": unit, "pairs": len(rows), "share": round(med, 4),
           "share_range": [sh[0], sh[-1]], "median_gap": round(mg, 2),
           "mean_share": round(sum(sh) / len(sh), 4), "rows": rows}
    if verbose:
        print("IMPLIED SHARE  " + unit + "  from " + str(len(rows)) + " spaced completions")
        print("    at     gap   BP on work   BP had   share")
        for r in rows:
            print("  " + ("%5.0f" % r["t"]) + ("%8.1f" % r["gap"])
                  + ("%13.0f" % r["bp_on_work"]) + ("%9.0f" % r["bp_avail"])
                  + ("%8.0f" % (r["share"] * 100)) + "%")
        print()
        print("  median gap " + ("%.1f" % mg) + "s -> median share "
              + ("%.0f" % (med * 100)) + "%  (range "
              + ("%.0f" % (sh[0] * 100)) + "-" + ("%.0f" % (sh[-1] * 100)) + "%)")
        print("  so a cadence drawn at 100% share runs about "
              + ("%.1f" % (1.0 / max(med, 1e-9))) + "x faster than this game did.")
    return out


def validate_cadence_vs_replay(data: Optional[dict] = None, unit: str = "Wind",
                               game: Union[int, str] = 1, position: str = "front",
                               verbose: bool = True) -> dict:
    """Hold the chart against the game it came from. Dedicated vs measured share.

    The dedicated figure is an upper bound and will always look too fast. What has to
    hold is the cadence at the MEASURED share: if that still disagrees, the model is
    wrong about something other than how the build power was divided."""
    d = data or load_game_data(int(game) if str(game).isdigit() else game)
    comps = sorted((c for c in (d.get("completions") or [])
                    if c.get("type") == unit), key=lambda c: c["t"])
    if len(comps) < 4:
        return {"ok": None, "note": "game has too few " + unit + " completions"}
    imp = implied_share(d, unit)
    st = state_from_game(d, max(0.0, comps[0]["t"] - 1.0))
    g = d.get("game") or {}
    pl = d.get("player") or {}
    b = mex_budget(map_query=g.get("map") or "All That Glitters",
                   team=int(pl.get("team_id") or 0), position=position,
                   standing=int(st.counts.get("Mex", 0)))
    rec = [round(comps[i + 1]["t"] - comps[i]["t"], 1)
           for i in range(min(12, len(comps) - 1))]
    spaced = [x for x in rec if x >= 1.0]
    med_rec = sorted(spaced)[len(spaced) // 2] if spaced else None
    runs = {}
    for label, sh in (("dedicated", 1.0), ("measured", imp.get("share") or 1.0)):
        r = cadence_row(st, target=unit, scale_source="ConTurret", n_scale=0,
                        budget=b, stop_after=len(rec) + 1, share=sh)
        dts = sorted(x["dt"] for x in r["segments"] if x["kind"] == "target")
        runs[label] = {"share": sh, "dts": [round(x["dt"], 1) for x in r["segments"]],
                       "median": round(dts[len(dts) // 2], 2) if dts else None}
    # The falsifiable claim is the BOUND, not the fit. The measured-share figure is
    # derived from these same gaps, so its agreement is circular and is reported for
    # information only.
    ok = None
    ratio = None
    bound_ok = None
    if med_rec and runs["dedicated"]["median"]:
        bound_ok = runs["dedicated"]["median"] <= med_rec + 1e-6
        ok = bound_ok
    if med_rec and runs["measured"]["median"]:
        ratio = runs["measured"]["median"] / med_rec
    if verbose:
        print("CADENCE vs REPLAY  " + str(g.get("id")) + "  " + unit)
        print("  state read at " + ("%.0f" % st.t) + "s: " + ("%.2f" % st.m_inc)
              + " M/s  " + ("%.0f" % st.e_inc) + " E/s  BP " + ("%.0f" % st.bp))
        print("  recorded gaps   " + " ".join(("%.1f" % x) for x in rec))
        print("  median recorded " + (("%.1f" % med_rec) + "s" if med_rec else "-")
              + "   (gaps under 1s are parallel finishes and are excluded)")
        print()
        for label in ("dedicated", "measured"):
            r = runs[label]
            print("  " + label.ljust(10) + " share " + ("%3.0f" % (r["share"] * 100))
                  + "%   median " + (("%.1f" % r["median"]) + "s" if r["median"] else "-")
                  + "   " + " ".join(("%.1f" % x) for x in r["dts"][:12]))
        print()
        print("  THE TEST: the dedicated figure must be an upper bound - every point of")
        print("  build power on one " + unit + " at a time can never be slower than a real")
        print("  game managed. " + ("%.1f" % runs["dedicated"]["median"]) + "s vs "
              + ("%.1f" % med_rec) + "s recorded -> "
              + ("BOUND HOLDS" if bound_ok else "BOUND VIOLATED - the model is wrong"))
        print()
        if ratio is not None:
            print("  FOR INFORMATION ONLY: at the measured share the prediction is "
                  + ("%.2f" % ratio) + "x the")
            print("  recorded median. That is not a test - the share is derived from these")
            print("  same gaps, so it cannot disagree with them in any interesting way.")
        print("  What the split actually buys you is `bp_delivered`, which measures where")
        print("  the build power went without being told.")
    return {"ok": ok, "bound_ok": bound_ok, "recorded": rec,
            "median_recorded": med_rec, "dedicated_median": runs["dedicated"]["median"],
            "implied": imp, "runs": runs, "ratio": ratio,
            "ratio_is_circular": True}


def cadence_table(state: "EcoState", target: str = "Wind",
                  scale_source: str = "ConTurret", rows: int = 4,
                  items: Optional[int] = 10, horizon: Optional[float] = None,
                  budget: Optional[dict] = None, width: int = 104,
                  workers: int = 1, share: float = 1.0,
                  pools: Optional["BpPools"] = None, assign: str = "base",
                  verbose: bool = True) -> dict:
    """Rows of cadence on one shared time axis, each cell labelled with its +time.

    `items` frames the chart by how many copies to show and the axis is fitted to
    the slowest row, so every cell has room for its number. Pass `horizon` instead
    to fix the window in seconds."""
    big = 1e7
    out = [cadence_row(state, target, scale_source, i,
                       horizon if horizon else big, budget, workers=workers,
                       stop_after=None if horizon else items, share=share,
                       pools=pools, assign=assign)
           for i in range(rows + 1)]
    if horizon is None:
        ends = [r["segments"][-1]["t_end"] for r in out if r["segments"]]
        horizon = max(ends) * 1.02 if ends else 60.0
    base = out[0]

    for r in out:
        r["crossover"] = None
        if not r["n_scale"]:
            continue
        for x in r["segments"]:
            if x["kind"] != "target":
                continue
            b = next((y["t_end"] for y in base["segments"]
                      if y["kind"] == "target" and y["n"] == x["n"]), None)
            if b is not None and x["t_end"] <= b:
                r["crossover"] = {"t": x["t_end"], "n": x["n"], "base_t": b}
                break

    # phase bands off row 0, computed whether or not we print
    bands, last = [], None
    for x in base["segments"]:
        if x["phase"] != last:
            bands.append({"t": x["t_start"], "phase": x["phase"]})
            last = x["phase"]

    if not verbose:
        return {"rows": out, "bands": bands, "horizon": horizon}

    T = OBJECTS[target]
    per = width / horizon                      # characters per second
    print("CADENCE  target " + target + " (" + ("%g" % T.metal_cost) + "m "
          + ("%g" % T.energy_cost) + "e " + ("%g" % T.bp_cost) + " BP-s)"
          + "   scale with " + scale_source
          + "   from t=" + ("%.0f" % state.t) + "s")
    if pools is not None:
        tb = pool_bp_for(target, pools)
        sb = pool_bp_for(scale_source, pools)
        print("  POOLS: expand " + ("%.0f" % pools.expand) + "  factory "
              + ("%.0f" % pools.factory) + "  base " + ("%.0f" % pools.base)
              + "   -> " + target + " draws " + ("%.0f" % tb["bp"]) + " ("
              + tb["work_pool"] + "), " + scale_source + " draws "
              + ("%.0f" % sb["bp"]) + " (" + sb["work_pool"] + ")")
        print("  a cross joins " + ("EXPAND" if assign == "expand" else "BASE"))
    else:
        print("  build power pointed at this work: " + ("%.0f" % (share * 100)) + "% of "
              + ("%.0f" % state.bp) + " BP = " + ("%.0f" % (state.bp * share))
              + (" - DEDICATED, an upper bound on the pace" if share >= 0.999
                 else " (measured share)"))
    print("  here: " + ("%.2f" % state.m_inc) + " M/s  " + ("%.0f" % state.e_inc)
          + " E/s  BP " + ("%.0f" % state.bp) + "  banks "
          + ("%.0f" % state.metal) + "m/" + ("%.0f" % state.energy) + "e"
          + ("   budget " + str(budget["count"]) + " mex, standing "
             + str(budget["standing"]) + ", ROOM " + str(budget["room"])
             if budget else ""))
    # ticks on the chart, names in a legend, so that two boundaries a second apart
    # cannot scribble over each other
    if bands and bands[0]["phase"] != "?":
        line = [" "] * (width + 2)
        for k, bd in enumerate(bands):
            i = int(round(bd["t"] * per))
            if 0 <= i <= width:
                line[i] = chr(ord("a") + k) if k < 26 else "|"
        print("  " + "phase".ljust(13) + "".join(line).rstrip())
        print("  " + " " * 13 + "  ".join(
            chr(ord("a") + k) + " " + ("%.0f" % bd["t"]) + "s " + bd["phase"]
            for k, bd in enumerate(bands[:6])))
    step = 15
    for cand in (5, 10, 15, 30, 60, 120, 300):
        if horizon / cand <= 9:
            step = cand
            break
    axis = [" "] * (width + 2)
    for t in range(0, int(horizon) + 1, step):
        i = int(round(t * per))
        for k, ch in enumerate(str(t)):
            if 0 <= i + k <= width:
                axis[i + k] = ch
    print("  " + " " * 13 + "".join(axis).rstrip() + "   seconds")

    for r in out:
        cells = [" "] * (width + 2)
        cursor = 0
        for x in r["segments"]:
            i = max(cursor, int(round(x["t_start"] * per)))
            j = max(i + 1, int(round(x["t_end"] * per)))
            if i > width:
                break
            j = min(j, width)
            w = j - i
            lab = ("B" if x["kind"] == "invest"
                   else ("+" + ("%.0f" % x["dt"]) if x["dt"] >= 9.5
                         else "+" + ("%.1f" % x["dt"])))
            if x["kind"] == "invest":
                fill = "=" * w
                mid = max(0, (w - 1) // 2)
                body = fill[:mid] + "B" + fill[mid + 1:]
            elif w >= len(lab) + 1:
                pad = w - 1 - len(lab)
                body = "|" + lab + " " * pad
            elif w >= 2:
                body = "|" + ("*" if x["bound"] != "none" else " ") * (w - 1)
            else:
                body = "|"
            for k in range(w):
                if i + k <= width:
                    cells[i + k] = body[k] if k < len(body) else " "
            cursor = j
        if cursor <= width:
            cells[min(cursor, width)] = "|"
        tag = "+" + str(r["n_scale"]) + " " + scale_source[:8]
        print("  " + tag.ljust(13) + "".join(cells).rstrip()
              + "  " + str(r["targets"]) + "x")
        # the numbers, always, whatever the density. 'm'/'e' marks a bound copy.
        marks = {"none": "", "metal": "m", "energy": "e", "build power": "b"}
        strip = " ".join(
            (("[" + ("%.0f" % x["dt"]) + "]") if x["kind"] == "invest"
             else ("%.1f" % x["dt"]) + marks.get(x["bound"], "?"))
            for x in r["segments"])
        print("  " + " " * 13 + "+s " + strip[:width + 20])

    print("  " + " " * 13 + "-" * (width + 1))
    print("  each cell is ONE " + target + " and its WIDTH is the seconds that one took;")
    print("  the '+s' line under each row lists those same seconds in order, with 'm' or")
    print("  'e' marking a copy that went metal- or energy-bound, and [n] the investment.")
    print()
    hdr = ("row".ljust(14) + target.rjust(5) + "nominal".rjust(9) + "invest".rjust(8)
           + "1st".rjust(8) + "5th".rjust(8) + "10th".rjust(8) + "20th".rjust(8)
           + "stall".rjust(7) + "  first bound      catches +0")
    print("  " + hdr)
    for r in out:
        a = r["at"]
        co = ("-" if not r["n_scale"] else
              (("%.0f" % r["crossover"]["t"]) + "s at #" + str(r["crossover"]["n"])
               if r["crossover"] else "no"))
        if not r["n_scale"]:
            co = "baseline"
        fb = ("never" if not r["first_bound"] else
              "#" + str(r["first_bound"]["n"]) + " " + r["first_bound"]["bound"]
              + " @" + ("%.0f" % r["first_bound"]["t"]) + "s")
        def g(k):
            v = a.get(k)
            return "-" if v is None else ("%.0f" % v) + "s"
        print("  " + ("+" + str(r["n_scale"]) + " " + scale_source[:9]).ljust(14)
              + str(r["targets"]).rjust(5)
              + (("%.1f" % r["nominal_each"]) + "s").rjust(9)
              + (("%.0f" % r["invest_sec"]) + "s").rjust(8)
              + g(1).rjust(8) + g(5).rjust(8) + g(10).rjust(8) + g(20).rjust(8)
              + (("%.0f" % r["stall_sec"]) + "s").rjust(7)
              + "  " + fb.ljust(17) + co)
    stops = [(r["n_scale"], r["stopped"]) for r in out if r["stopped"]]
    if stops:
        print()
        for k, why in stops:
            print("  row +" + str(k) + " stopped early: " + why)
    return {"rows": out, "bands": bands, "horizon": horizon}


# ══════════════════════════════════════════════════════════════════════════
# THE PATH, AND THE BUILD RATIO IT YIELDS
#
# One walk across the cadence grid. Going OVER is building one more energy
# generator. Going CROOSS is buying one more build-power source, which costs time
# and pushes everything right. The ratio of overs per cross is the answer a player
# can actually use: "four winds per con turret".
#
# WHEN TO CROSS, two conditions and both are needed:
#   1. the target can already absorb every point of build power you own, so more
#      hands would actually be used (`absorb_profile` share at the threshold), and
#   2. you can PAY for the build-power source out of bank plus income with no stall
#      (`time_to_build(...)["affordable"]`).
# Saturation alone would tell you to buy a con turret you cannot afford, which is
# not a move. The threshold in 1 is the policy knob the objectives are scored over;
# 1.0 is "only when it is completely saturated".
#
# METAL BOUND IS THE GOAL, BUT ONLY WHILE THERE IS ROOM. With the mex budget spent,
# metal bound means capped, so `hold_metal_bound` only counts metal-bound seconds
# while `room > 0`.
# ══════════════════════════════════════════════════════════════════════════

PATH_OBJECTIVES: Dict[str, Callable[..., dict]] = {}


def objective(name: str):
    """Register a path-scoring function. Higher score wins."""
    def deco(fn):
        PATH_OBJECTIVES[name] = fn
        fn.objective_name = name
        return fn
    return deco


def should_cross(state: "EcoState", target: str = "Wind",
                 bp_source: str = "ConTurret", on: str = "Mex",
                 bp: Optional[float] = None, source_bp: Optional[float] = None,
                 threshold: float = 1.0) -> dict:
    """Is buying build power the move here? Saturation AND affordability.

    Saturation is measured on `on`, the work the metal is for - not on `target`, the
    generator being added. Asking whether income could feed more hands building more
    generators answers nothing; the hands are wanted for the work."""
    # TWO different pools are in play and conflating them is wrong: saturation is
    # measured against the hands doing the WORK, affordability against the hands that
    # would BUILD the source. With one BP number they coincide; with pools they do not,
    # and testing a con turret's affordability against an empty expand pool says
    # "unaffordable" when base could pay for it comfortably.
    b = bp if bp is not None else state.bp
    sb = source_bp if source_bp is not None else b
    # UNCAPPED. absorb_profile's share is min(bp, feedable)/bp and tops out at 1.0,
    # so it can never express "my income could feed MORE hands than I own", which is
    # exactly the condition that makes buying hands correct.
    feed = sustainable_bp(on, state.m_inc, state.e_inc)["bp"]
    feed_ratio = (feed / b) if b > 0 else float("inf")
    saturated = feed_ratio >= threshold - 1e-9
    aff = time_to_build(state, bp_source, sb)
    cross = bool(saturated and aff["affordable"])
    pct = ("the pool is EMPTY, so any hands help"
           if feed_ratio == float("inf") else ("%.0f" % (feed_ratio * 100) + "%"))
    if cross:
        why = ("income could feed " + pct + " of " + ("%.0f" % b) + " BP on "
               + on + " and " + bp_source + " is payable in "
               + ("%.0f" % aff["seconds"]) + "s with no stall")
    elif not saturated:
        why = ("income only feeds " + pct + " of build power on " + on
               + ", so more hands would sit idle")
    else:
        why = (bp_source + " would stall on " + str(aff["bound"]) + " for "
               + ("%.0f" % aff["stall"]) + "s of its "
               + ("%.0f" % aff["seconds"]) + "s: cannot pay for it yet")
    return {"cross": cross, "saturated": saturated,
            "affordable": aff["affordable"], "feed_ratio": feed_ratio,
            "absorb_share": min(1.0, feed_ratio), "feedable_bp": feed,
            "bp_source_sec": aff["seconds"], "bp_source_stall": aff["stall"],
            "work_bp": b, "source_bp": sb,
            "bound": aff["bound"], "threshold": threshold, "why": why}


def walk_path(state: "EcoState", budget: Optional[dict] = None, target: str = "Wind",
              bp_source: str = "ConTurret", on: str = "Mex", horizon: float = 240.0,
              threshold: float = 1.0, max_steps: int = 300,
              workers: int = 1, pools: Optional["BpPools"] = None,
              assign: str = "base") -> dict:
    """Walk over/cross from here until the horizon, recording every decision."""
    st = state.copy()
    t0 = st.t
    steps: List[dict] = []
    overs = crosses = 0
    metal_sec = 0.0
    overflow_sec = 0.0
    exit_reason = None
    off_chart = None
    waited = 0.0
    pl = pools.copy() if pools is not None else None
    mismatch = (cross_relieves(bp_source, on, assign) if pl is not None else None)
    room = (budget or {}).get("room", 1)
    # the energy income that would let this position spend every drop of metal the
    # WHOLE budget will produce, on the work the metal is for
    W = OBJECTS[on]
    m_proj = (budget or {}).get("m_per_s_projected") or state.m_inc
    e_need_proj = (m_proj * W.energy_cost / W.metal_cost
                   if W.metal_cost > 0 else float("inf"))
    standing = (budget or {}).get("standing", 0)
    # the workers claim the budget in PARALLEL - that is what 'tasked' means. Each
    # spot lands at its own time and raises metal income by its OWN rate.
    pending: List[dict] = []
    # st is rebound by coast/build_fed, so the claim helper declares it nonlocal
    if budget and budget.get("room", 0) > 0 and workers > 0:
        for ch in claim_plan(budget, workers)["chains"]:
            for sp in ch["spots"]:
                pending.append({"t": sp["done_sec"], "m": sp["metal_per_s"],
                                "n": sp["n"]})
        pending.sort(key=lambda r: r["t"])
    claimed: List[dict] = []

    def apply_claims(now: float) -> List[dict]:
        """Land every spot whose worker has finished by `now`."""
        nonlocal st
        got = []
        while pending and pending[0]["t"] <= now + 1e-9:
            sp = pending.pop(0)
            st.m_inc += sp["m"]
            st.counts["Mex"] = st.counts.get("Mex", 0) + 1
            got.append(sp)
            claimed.append(sp)
        return got

    def note_claims(landed: List[dict]) -> None:
        nonlocal standing, room
        if landed:
            standing += len(landed)
            room = max(0, room - len(landed))

    while st.t - t0 < horizon and len(steps) < max_steps:
        note_claims(apply_claims(st.t - t0))
        # with pools, saturation is judged against the pool that does the WORK
        work_bp = pool_bp_for(on, pl)["bp"] if pl is not None else None
        src_bp = pool_bp_for(bp_source, pl)["bp"] if pl is not None else None
        dec = should_cross(st, target, bp_source, on, bp=work_bp, source_bp=src_bp,
                           threshold=threshold)
        # would another generator be waste? Energy income already past what this build
        # power can burn means the next one returns nothing.
        if st.e_inc >= e_need_proj and not dec["cross"]:
            # energy is done and hands are not yet justified. If workers are still
            # walking to spots, the right move is to WAIT for them - that is the
            # 'tasked' phase finishing, and it changes the decision.
            if pending:
                wait_to = pending[0]["t"]
                if wait_to > st.t - t0:
                    gap = wait_to - (st.t - t0)
                    st = st.coast(gap)
                    steps.append({"kind": "wait", "t_start": round(st.t - t0 - gap, 2),
                                  "t_end": round(st.t - t0, 2), "dt": round(gap, 2),
                                  "why": ("energy covers the budget and hands are not "
                                          "justified yet: waiting for extractor #"
                                          + str(pending[0]["n"]) + " to land")})
                    waited += gap
                    continue
                apply_claims(st.t - t0)
                continue
            exit_why = ("energy income " + ("%.0f" % st.e_inc) + " E/s already covers "
                        + "the " + ("%.0f" % e_need_proj) + " E/s needed to spend all "
                        + ("%.2f" % m_proj) + " m/s the budget will make on " + on
                        + " - that is the SCALING marker, so another " + target
                        + " returns nothing. And " + dec["why"])
            nxt_move = ("EConverter or AMex" if room <= 0 else "Mex")
            steps.append({"kind": "exit", "t": round(st.t - t0, 2),
                          "why": exit_why, "off_chart": nxt_move})
            exit_reason = exit_why
            off_chart = nxt_move
            break
        unit = bp_source if dec["cross"] else target
        prev_t = st.t
        bp_now = pool_bp_for(unit, pl)["bp"] if pl is not None else None
        if bp_now is not None and bp_now <= 0:
            steps.append({"kind": "stuck", "unit": unit, "t": round(prev_t - t0, 2),
                          "why": ("no build power in the "
                                  + pool_bp_for(unit, pl)["work_pool"] + " pool")})
            exit_reason = "a pool with no build power in it"
            break
        nxt, r = st.build_fed(unit, bp=bp_now)
        if r["seconds"] == float("inf"):
            steps.append({"kind": "stuck", "unit": unit, "t": round(prev_t - t0, 2),
                          "why": dec["why"]})
            exit_reason = dec["why"]
            break
        st = nxt
        if pl is not None:
            pl = pools_after(pl, unit, assign)
        reg = regime_of(st.m_inc, st.e_inc,
                        (pool_bp_for(on, pl)["bp"] if pl is not None else st.bp), on)
        dt = st.t - prev_t
        spilling = st.e_inc > energy_ceiling(st.bp, on)
        if spilling:
            overflow_sec += dt
        # metal bound is the goal, but only when it is CLEAN: room left to grow into,
        # and no energy pouring away while you sit there
        if reg["regime"] == "metal" and room > 0 and not spilling:
            metal_sec += dt
        if dec["cross"]:
            crosses += 1
        else:
            overs += 1
        steps.append({"kind": "cross" if dec["cross"] else "over", "unit": unit,
                      "t_start": round(prev_t - t0, 2), "t_end": round(st.t - t0, 2),
                      "dt": round(dt, 2), "bound": r["bound"],
                      "stall": round(r["stall"], 2),
                      "absorb_share": round(dec["absorb_share"], 4),
                      "feed_ratio": (None if dec["feed_ratio"] == float("inf")
                                     else round(dec["feed_ratio"], 4)),
                      "mex": standing, "room": room, "spilling": spilling,
                      "bp_used": bp_now, "pool": (pool_bp_for(unit, pl)["work_pool"]
                                                  if pl is not None else None),
                      "bp": st.bp, "m_inc": round(st.m_inc, 3),
                      "e_inc": round(st.e_inc, 2), "regime": reg["regime"],
                      "overs": overs, "crosses": crosses, "why": dec["why"]})
    ratio = build_ratio(overs, crosses, target, bp_source)
    val = usable_value_per_s(st.m_inc, st.e_inc, st.bp, on)
    return {"threshold": threshold, "steps": steps, "overs": overs, "crosses": crosses,
            "ratio": ratio, "end": st, "elapsed": round(st.t - t0, 2),
            "metal_bound_sec": round(metal_sec, 2),
            "overflow_sec": round(overflow_sec, 2), "room": room,
            "exit_reason": exit_reason, "off_chart": off_chart,
            "waited_sec": round(waited, 2),
            "pools_end": (None if pl is None else
                          {"expand": pl.expand, "factory": pl.factory, "base": pl.base}),
            "cross_relieves": mismatch,
            "e_need_projected": round(e_need_proj, 1), "m_projected": m_proj,
            "claimed": claimed, "claims_pending": len(pending),
            "standing": standing, "target": target, "bp_source": bp_source,
            "end_value_per_s": round(val["value_per_s"], 4),
            "end_wasted_e": round(val["wasted"], 1),
            "end_m_inc": round(st.m_inc, 3), "end_e_inc": round(st.e_inc, 2),
            "end_bp": st.bp}


def build_ratio(overs: int, crosses: int, target: str = "Wind",
                bp_source: str = "ConTurret") -> dict:
    """Overs per cross, as the ratio a player can read off and follow."""
    if crosses <= 0:
        return {"overs": overs, "crosses": 0, "per_cross": None,
                "label": "all " + target + ", no " + bp_source + " earned its place"}
    per = overs / crosses
    return {"overs": overs, "crosses": crosses, "per_cross": round(per, 2),
            "label": ("%.1f" % per) + " " + target + " : 1 " + bp_source}


@objective("hold_metal_bound")
def _obj_metal_bound(path: dict, **kw) -> dict:
    """Seconds spent CLEANLY metal-bound: room left to grow, and nothing spilling."""
    el = max(1e-9, path["elapsed"])
    share = path["metal_bound_sec"] / el
    spill = path["overflow_sec"] / el
    return {"score": share, "detail": ("%.0f" % (share * 100))
            + "% of " + ("%.0f" % el) + "s cleanly metal-bound, "
            + ("%.0f" % (spill * 100)) + "% spilling"}


@objective("most_economy_at")
def _obj_economy(path: dict, **kw) -> dict:
    """Usable value per second at the end, which discounts energy that spills."""
    return {"score": path["end_value_per_s"],
            "detail": ("%.2f" % path["end_value_per_s"]) + " usable value/s, "
            + ("%.0f" % path["end_wasted_e"]) + " E/s wasted"}


@objective("fastest_to_goal")
def _obj_goal(path: dict, goal: Optional[dict] = None, **kw) -> dict:
    """Soonest to a stated goal. Higher score = sooner, so the score is negated time."""
    goal = goal or {"e_inc": 600.0}
    key, want = next(iter(goal.items()))
    hit = None
    for x in path["steps"]:
        if x.get("kind") in ("stuck", "exit"):
            break
        got = x.get(key if key != "targets" else "overs")
        if got is None:
            continue
        if got >= want:
            hit = x["t_end"]
            break
    if hit is None:
        return {"score": -1e9, "detail": "never reached " + key + " >= " + str(want)}
    return {"score": -hit, "detail": key + " >= " + str(want) + " at " + ("%.0f" % hit) + "s"}


def path_search(state: "EcoState", budget: Optional[dict] = None, target: str = "Wind",
                bp_source: str = "ConTurret", on: str = "Mex", horizon: float = 240.0,
                objective_name: str = "hold_metal_bound",
                thresholds: Sequence[float] = (0.6, 0.7, 0.8, 0.9, 1.0),
                goal: Optional[dict] = None, workers: int = 1,
                pools: Optional["BpPools"] = None, assign: str = "base",
                verbose: bool = True) -> dict:
    """Walk the grid at several cross thresholds and score them with one objective.

    The user's own rule is threshold 1.0 — cross only when the target already
    absorbs everything. The sweep exists so the rule can be checked rather than
    assumed, and so the objectives have something to choose between."""
    if objective_name not in PATH_OBJECTIVES:
        raise KeyError("no objective " + objective_name + "; have "
                       + ", ".join(sorted(PATH_OBJECTIVES)))
    fn = PATH_OBJECTIVES[objective_name]
    runs = []
    for th in thresholds:
        pth = walk_path(state, budget, target, bp_source, on, horizon, th,
                        workers=workers, pools=pools, assign=assign)
        sc = fn(pth, goal=goal)
        pth["score"] = sc["score"]
        pth["score_detail"] = sc["detail"]
        runs.append(pth)
    # on a tie prefer the STRICTER threshold: "cross only when the target already
    # absorbs everything" is the stated rule, so it wins unless a looser one scores
    # strictly better.
    best = max(runs, key=lambda r: (round(r["score"], 9), r["threshold"]))
    if verbose:
        print("PATH  over = one more " + target + "   cross = one more " + bp_source)
        print("  from t=" + ("%.0f" % state.t) + "s  " + ("%.2f" % state.m_inc)
              + " M/s  " + ("%.0f" % state.e_inc) + " E/s  BP " + ("%.0f" % state.bp)
              + "   horizon " + ("%.0f" % horizon) + "s"
              + ("   room " + str(budget["room"]) + " of " + str(budget["count"]) + " mex"
                 if budget else ""))
        _r0 = runs[0]
        print("  metal is spent on " + on + ", so going right pays until energy covers "
              + ("%.0f" % _r0["e_need_projected"]) + " E/s"
              + " (all " + ("%.2f" % _r0["m_projected"]) + " m/s the budget will make)")
        print("  objective " + objective_name + "  (" + ", ".join(sorted(PATH_OBJECTIVES)) + ")")
        print()
        print("  " + "cross at".ljust(10) + "overs".rjust(6) + "crosses".rjust(8)
              + "ratio".rjust(9) + "score".rjust(9) + "  what the score says")
        for r in runs:
            mark = " <-- best" if r is best else ""
            per = "-" if r["ratio"]["per_cross"] is None else ("%.2f" % r["ratio"]["per_cross"])
            print("  " + (("%.0f" % (r["threshold"] * 100)) + "%").ljust(10)
                  + str(r["overs"]).rjust(6) + str(r["crosses"]).rjust(8)
                  + per.rjust(9) + ("%.3f" % r["score"]).rjust(9)
                  + "  " + r["score_detail"] + mark)
        mm = best.get("cross_relieves")
        if mm and not mm["relieves"]:
            print()
            print("  *** THE CROSS DOES NOT RELIEVE THE BOUND POOL ***")
            print("  " + mm["why"])
            print("  The ratio below is an artifact of that, not an answer.")
        print()
        print("  SUGGESTED BUILD RATIO:  " + best["ratio"]["label"]
              + ("   [ARTIFACT - see above]" if (mm and not mm["relieves"]) else ""))
        print()
        print("  the walk at the best threshold:")
        print("  " + "t".rjust(7) + "  move   unit".ljust(18) + "+s".rjust(7)
              + "feeds".rjust(7) + "mex".rjust(5) + "  regime      why")
        shown = 0
        for x in best["steps"]:
            if x.get("kind") == "stuck":
                print("  " + ("%7.0f" % x["t"]) + "  STUCK  " + x["unit"] + "  " + x["why"])
                break
            if x.get("kind") == "exit":
                break
            if x.get("kind") == "wait":
                print("  " + ("%7.0f" % x["t_end"]) + "  WAIT   "
                      + ("%.0f" % x["dt"]) + "s   " + x["why"])
                shown += 1
                continue
            if x["kind"] == "cross" or shown < 14:
                fr = x.get("feed_ratio")
                print("  " + ("%7.0f" % x["t_end"]) + "  "
                      + ("CROSS" if x["kind"] == "cross" else "over ") + "  "
                      + x["unit"].ljust(11) + ("%7.1f" % x["dt"])
                      + (("%6.0f" % (fr * 100)) + "%" if fr is not None else "   inf")
                      + ("%5d" % x.get("mex", 0))
                      + "  " + x["regime"].ljust(10)
                      + ("  " + x["why"] if x["kind"] == "cross" else ""))
                shown += 1
        if len(best["steps"]) > shown:
            print("  ... " + str(len(best["steps"]) - shown) + " more overs")
        if best.get("exit_reason"):
            print()
            print("  WALK ENDED at " + ("%.0f" % best["elapsed"]) + "s: "
                  + best["exit_reason"])
            if best.get("off_chart"):
                print("  next move is off this chart: " + best["off_chart"]
                      + ("  (no mex room left, so the metal ceiling is fixed)"
                         if best["room"] <= 0 else
                         "  (there is still mex room, so claim before converting)"))
    return {"runs": runs, "best": best, "objective": objective_name,
            "ratio": best["ratio"]}


def wealth_at(tr: "PathTrace", at: float) -> dict:
    """Total metal-equivalent WEALTH held at `at`: banks plus everything standing,
    priced at build cost.

    This is the metric that survives scrutiny. Gross production rewards only the
    extractor timing and ignores what the panels cost. Net production (gross minus
    spend) rewards building nothing at all, since spending zero maximises it.
    Wealth counts what the spending BOUGHT, so converting income into useful assets
    scores and idling does not."""
    row = tr.at(at)
    banks = (row.get("metal") or 0.0) + (row.get("energy") or 0.0) / ENERGY_PER_METAL
    assets = 0.0
    breakdown = {}
    for unit, n in (row.get("built") or {}).items():
        t = OBJECTS.get(unit)
        if t is None:
            continue
        each = t.metal_cost + t.energy_cost / ENERGY_PER_METAL
        assets += each * n
        breakdown[unit] = round(each * n, 1)
    return {"at": at, "banks": round(banks, 1), "assets": round(assets, 1),
            "total": round(banks + assets, 1), "breakdown": breakdown}


def state_from_trace(tr: "PathTrace", at: float) -> "EcoState":
    """The position a simulated variant is in at time `at`, as a state you can carry
    forward - so a sweep result becomes the input to the next decision rather than
    the end of the analysis."""
    row = tr.at(at)
    counts = dict(row.get("built") or {})
    return EcoState(t=row.get("t", at), metal=row.get("metal", 0.0),
                    energy=row.get("energy", 0.0), m_inc=row.get("m_inc", 0.0),
                    e_inc=row.get("e_inc", 0.0), bp=row.get("bp", 300.0),
                    counts=counts,
                    wind=(tr.path.wind if tr.path and tr.path.wind else DEFAULT_WIND))


def reclaim_option(state: "EcoState", unit: str, count: int = 1,
                   bp: Optional[float] = None) -> dict:
    """What reclaiming `count` of `unit` from this position buys and costs.

    Building reclaim returns 100% of metal cost (measured across several games), so
    the metal is certain. What it costs is the income that building was providing and
    the build work spent tearing it down."""
    t = OBJECTS[unit]
    b = bp if bp is not None else state.bp
    have = state.counts.get(unit, 0)
    n = min(count, have)
    out = state.wind if t.wind_powered else t.energy_income
    secs = (t.bp_cost / b) * n if b else float("inf")
    return {"unit": unit, "requested": count, "available": have, "reclaiming": n,
            "metal_returned": n * t.metal_cost,
            "seconds": round(secs, 1),
            "metal_per_sec": round(n * t.metal_cost / secs, 2) if secs > 0 else 0.0,
            "e_inc_lost": round(n * out, 1),
            "m_inc_lost": round(n * t.metal_income, 3),
            "bp_lost": n * t.bp_income,
            "short_by": max(0, count - have)}


def compare_variants(sweep: dict, a: int, b: int, at: Optional[float] = None,
                     reclaim: Sequence[str] = ("Solar", "BotWorker"),
                     verbose: bool = True) -> dict:
    """Two solar counts, same clock, expressed as the difference and what you could
    do with it. `a` is the reference, `b` the alternative."""
    at = at if at is not None else sweep["at"]
    rows = {r["solars"]: r for r in sweep["rows"]}
    if a not in rows or b not in rows:
        raise KeyError(f"variants {a} and {b} must both be in the sweep "
                       f"({sorted(rows)})")
    ra, rb = rows[a], rows[b]
    sa, sb = state_from_trace(ra["trace"], at), state_from_trace(rb["trace"], at)
    delta = {
        "metal_made": (rb["gathered_m"] or 0) - (ra["gathered_m"] or 0),
        "energy_made": (rb["gathered_e"] or 0) - (ra["gathered_e"] or 0),
        "bank_metal": (rb["bank_m"] or 0) - (ra["bank_m"] or 0),
        "bank_energy": (rb["bank_e"] or 0) - (ra["bank_e"] or 0),
        "m_inc": (rb["m_inc"] or 0) - (ra["m_inc"] or 0),
        "e_inc": (rb["e_inc"] or 0) - (ra["e_inc"] or 0),
        "bp": (rb["bp"] or 0) - (ra["bp"] or 0),
        "mex_full": (None if (ra["mex_full"] is None or rb["mex_full"] is None)
                     else round(rb["mex_full"] - ra["mex_full"], 1)),
    }
    opts = {}
    for u in reclaim:
        opts[f"{a}solar"] = opts.get(f"{a}solar", {})
        opts[f"{b}solar"] = opts.get(f"{b}solar", {})
        opts[f"{a}solar"][u] = reclaim_option(sa, u, 99)
        opts[f"{b}solar"][u] = reclaim_option(sb, u, 99)

    if verbose:
        print(f"VARIANT COMPARISON at t={at:.0f}s   {a} solar (reference) vs {b} solar")
        print(f"  {'':16} {str(a) + ' solar':>12} {str(b) + ' solar':>12} {'delta':>10}")
        for lab, key, fmt in (("metal produced", "metal_made", "10.0f"),
                              ("energy produced", "energy_made", "10.0f"),
                              ("metal bank", "bank_metal", "10.0f"),
                              ("energy bank", "bank_energy", "10.0f"),
                              ("metal income", "m_inc", "10.2f"),
                              ("energy income", "e_inc", "10.1f"),
                              ("build power", "bp", "10.0f")):
            va = {"metal_made": ra["gathered_m"], "energy_made": ra["gathered_e"],
                  "bank_metal": ra["bank_m"], "bank_energy": ra["bank_e"],
                  "m_inc": ra["m_inc"], "e_inc": ra["e_inc"], "bp": ra["bp"]}[key] or 0
            vb = {"metal_made": rb["gathered_m"], "energy_made": rb["gathered_e"],
                  "bank_metal": rb["bank_m"], "bank_energy": rb["bank_e"],
                  "m_inc": rb["m_inc"], "e_inc": rb["e_inc"], "bp": rb["bp"]}[key] or 0
            print(f"  {lab:16} {va:12.2f} {vb:12.2f} {delta[key]:+{fmt}}")
        mf = delta["mex_full"]
        print(f"  {'7th mex':16} {(ra['mex_full'] or 0):12.0f} {(rb['mex_full'] or 0):12.0f} "
              f"{('' if mf is None else f'{mf:+10.0f}')}")
        print()
        print(f"  WHAT THE DIFFERENCE CAN BECOME - reclaim options from each position")
        print(f"  {'position':>10} {'reclaim':>11} {'have':>5} {'metal back':>11} "
              f"{'takes':>7} {'M/s while':>10} {'E/s given up':>13}")
        for pos, byunit in opts.items():
            for u, o in byunit.items():
                if not o["available"]:
                    continue
                print(f"  {pos:>10} {u:>11} {o['available']:>5} {o['metal_returned']:>11.0f} "
                      f"{o['seconds']:>6.0f}s {o['metal_per_sec']:>10.2f} {o['e_inc_lost']:>13.1f}")
        print()
        print(f"  reclaim returns 100% of metal cost, so the metal is certain; what it")
        print(f"  costs is the income that building was providing plus the build work")
        print(f"  spent tearing it down.")
    return {"at": at, "a": a, "b": b, "delta": delta, "states": {a: sa, b: sb},
            "reclaim_options": opts}


def solar_sweep_wind_planes(winds: Sequence[float] = (4, 8, 11.9, 16),
                            counts: Sequence[int] = tuple(range(0, 9)),
                            **kw) -> dict:
    """The same sweep at several wind speeds - the depth axis. A low-wind plane
    should favour more panels, a high-wind plane fewer."""
    out = {}
    print(f"{'wind':>6} {'best by metal':>14} {'fastest mex':>12} {'best w/ reclaim':>16}")
    for w in winds:
        r = solar_sweep(counts=counts, wind=w, verbose=False, **kw)
        rows = r["rows"]
        bm = max(rows, key=lambda x: x["gathered_m"] or 0)
        fm = min([x for x in rows if x["mex_full"]], key=lambda x: x["mex_full"], default=None)
        be = max(rows, key=lambda x: x["metal_equiv"])
        out[w] = r
        print(f"{w:6.1f} {bm['solars']:>14} {(fm['solars'] if fm else '-'):>12} {be['solars']:>16}")
    return out


# ══════════════════════════════════════════════════════════════════════════
# SCALING MAP — one energy source, one build-power source, one position
#
# Four regimes, and each one names its own fix:
#
#   BUILD POWER BOUND   both incomes exceed what the builders can consume. The
#                       limit is hands, not resources -> add the BP source.
#   METAL BOUND         build power idles for want of metal -> add an extractor.
#                       An extractor also eats 500 energy, so it doubles as the
#                       answer when metal is short AND energy is spilling.
#   ENERGY BOUND        build power idles for want of energy -> add the energy
#                       source.
#   ENERGY OVERFLOW     income exceeds what the builders can burn. Spilling energy
#                       is metal already spent returning nothing. Build power is
#                       the hungrier consumer per point, so it is the first answer;
#                       an extractor if metal is also short; a converter only once
#                       metal is genuinely all being spent and it still spills.
#
# The map sweeps both sources from the given position so the breakpoints are
# visible as boundaries rather than inferred from single numbers.
# ══════════════════════════════════════════════════════════════════════════

# METAL BOUND IS THE GOAL. It means build power and energy are both sufficient and
# the only thing limiting you is the resource you actually want more of. The other
# three are all forms of waste: idle builders, idle metal, or spilled energy.
REGIME_STYLE = {
    "metal":    ("M", "\033[42m", "METAL BOUND - on target", "raise the ceiling: another extractor"),
    "bp":       ("B", "\033[44m", "build power bound", "metal and energy idle -> add build power"),
    "energy":   ("E", "\033[43m", "energy bound", "builders idle -> add energy"),
    "overflow": ("O", "\033[45m", "energy overflow", "energy wasted -> add build power, or an extractor to eat it"),
}
_RESET = "\033[0m"


def regime_of(m_inc: float, e_inc: float, bp: float, on: str = "Mex",
              overflow_margin: float = 1.25) -> dict:
    """Which of the four regimes a position is in, for work of type `on`.

    The reference build sets the ratio in which build power consumes metal and
    energy; extractors are the default because that is what the build power is
    for in the phase this matters most."""
    d = drain_rates(on, bp)
    need_m, need_e = d["m_per_s"], d["e_per_s"]
    short_m = m_inc < need_m
    short_e = e_inc < need_e
    if short_m and short_e:
        # whichever is proportionally further behind is the one actually binding
        r = "metal" if (m_inc / need_m if need_m else 1) < (e_inc / need_e if need_e else 1) else "energy"
    elif short_m:
        r = "metal"
    elif short_e:
        r = "energy"
    elif need_e > 0 and e_inc > need_e * overflow_margin:
        r = "overflow"
    else:
        r = "bp"
    return {"regime": r, "need_m": need_m, "need_e": need_e,
            "m_ratio": (m_inc / need_m) if need_m else float("inf"),
            "e_ratio": (e_inc / need_e) if need_e else float("inf")}


def recommend(state: "EcoState", on: str = "Mex", energy_source: str = "Solar",
              bp_source: str = "BotWorker") -> dict:
    """The single next purchase this position argues for, and why."""
    r = regime_of(state.m_inc, state.e_inc, state.bp, on)
    reg = r["regime"]
    if reg == "bp":
        pick, why = bp_source, "metal and energy are both idle; buy hands to spend them"
    elif reg == "energy":
        pick, why = energy_source, "builders idle for want of energy"
    elif reg == "metal":
        pick, why = "Mex", ("on target - metal-bound is where you want to be. "
                            "Nothing is being wasted, so the only gain left is a higher "
                            "ceiling: another extractor")
    else:
        # overflow: spend the spill on the hungriest consumer that also helps
        if r["m_ratio"] < 1.5:
            pick, why = "Mex", "energy spilling and metal is the tighter of the two; an extractor eats 500 E and pays metal"
        elif state.metal > 0.6 * state.m_cap:
            pick, why = bp_source, "energy spilling and metal banking; buy hands to spend both"
        else:
            pick, why = "EConverter", "metal is being spent and energy still spills; convert the remainder"
    return {"regime": reg, "build": pick, "why": why, **r}


def scaling_map(state: "EcoState", energy_source: str = "Solar",
                bp_source: str = "BotWorker", on: str = "Mex",
                n_energy: int = 10, n_bp: int = 7, color: bool = True,
                verbose: bool = True) -> dict:
    """Sweep both scaling sources from this position and colour the regimes.

    Rows add the build-power source, columns add the energy source. Each cell is
    the regime that combination lands in, so the boundaries between them are the
    breakpoints."""
    ES, BS = OBJECTS[energy_source], OBJECTS[bp_source]
    e_out = state.wind if ES.wind_powered else ES.energy_income
    grid, cells = [], {}
    for i in range(n_bp + 1):
        row = []
        for j in range(n_energy + 1):
            bp = state.bp + i * BS.bp_income
            m_inc = state.m_inc + i * BS.metal_income
            e_inc = state.e_inc + j * e_out + i * BS.energy_income
            r = regime_of(m_inc, e_inc, bp, on)
            row.append(r["regime"])
            cells[(i, j)] = {"bp": bp, "m_inc": m_inc, "e_inc": e_inc, **r}
        grid.append(row)

    if verbose:
        print(f"SCALING MAP   energy = {energy_source} ({e_out:g} E/s each), "
              f"build power = {bp_source} (+{BS.bp_income:g} BP, {BS.energy_income:+g} E/s each)")
        print(f"  from t={state.t:.0f}s: {state.m_inc:.2f} M/s, {state.e_inc:.0f} E/s, "
              f"BP {state.bp:.0f}, banks {state.metal:.0f}m/{state.energy:.0f}e   "
              f"(work measured against {on})")
        print(f"\n  {'':10}" + "".join(f"{j:>3}" for j in range(n_energy + 1))
              + f"   <- {energy_source} added")
        for i, row in enumerate(grid):
            line = ""
            for reg in row:
                ch, col, _, _ = REGIME_STYLE[reg]
                line += (f"{col} {ch}{_RESET}" if color else f"  {ch}")
            bp_now = state.bp + i * BS.bp_income
            print(f"  +{i:<2}{bp_source[:6]:7}" + line + f"   BP {bp_now:.0f}")
        print(f"  ^ {bp_source} added")
        print()
        for k, (ch, col, name, act) in REGIME_STYLE.items():
            swatch = f"{col} {ch}{_RESET}" if color else f"[{ch}]"
            print(f"   {swatch}  {name:18} -> {act}")
        rec = recommend(state, on, energy_source, bp_source)
        print(f"\n  HERE: {REGIME_STYLE[rec['regime']][2]}  "
              f"(metal at {rec['m_ratio']:.2f}x need, energy at {rec['e_ratio']:.2f}x)")
        print(f"  BUILD: {rec['build']} — {rec['why']}")
    return {"grid": grid, "cells": cells, "energy_source": energy_source,
            "bp_source": bp_source, "on": on,
            "recommendation": recommend(state, on, energy_source, bp_source)}


# ══════════════════════════════════════════════════════════════════════════
# BUILD HORIZON — the 3-D state machine, charged outward from one position
#
# Three axes:
#   DEPTH   wind speed. Fixed for a view, so one plane is one wind condition.
#           Change it and the whole picture slides toward or away from you: the
#           same rules, a different plane, priorities re-sorted.
#   ROW     time. "Keep building at the build power I have" runs to the right.
#           Cells sit at their real COMPLETION time, so rows are sequential but
#           columns deliberately do NOT line up — that misalignment is the point.
#   COLUMN  build power. Going down a column is "scale build power first, then
#           build". Each row down invests in one more BP source before starting.
#
# What the picture shows is the lateral distance: how far right you are pushed by
# stopping to build build power, against how much tighter the spacing becomes
# afterwards, and where the two lines cross.
#
# ROI definitions used, and the correction that matters:
#   BPROI     bp_cost / bp_income — seconds of build work a BP source returns per
#             point it adds. ConTurret 5300/200 = 26.5s, BotWorker 3450/80 = 43.1s.
#   EFFECTIVE BPROI   nominal BPROI is a lie when metal or energy is short, because
#             the new build power cannot be fed. Scale by effectiveBP/oldBP, not
#             totalBP/oldBP — buying 200 BP you cannot feed returns nothing.
#   EROI      energy_cost / output — seconds after completion for an energy source
#             to repay the energy it cost to erect.
#   TOTAL ROI metal + energy_cost/70 — the all-in metal-equivalent price, valid
#             once converters make the exchange real.
# ══════════════════════════════════════════════════════════════════════════

def roi_figures(unit: str, wind: float = DEFAULT_WIND) -> dict:
    """BPROI, EROI and total ROI for one building."""
    t = OBJECTS[unit]
    out = wind if t.wind_powered else t.energy_income
    return {
        "unit": unit,
        "bproi": (t.bp_cost / t.bp_income) if t.bp_income else None,
        # only a PRODUCER has an energy payback. A consumer's energy_income is negative
        # upkeep, and energy_cost / -upkeep is not a time.
        "eroi": (t.energy_cost / out) if out and out > 0 else None,
        "energy_upkeep": (-out if out and out < 0 else 0.0),
        "total_roi_metal": t.metal_cost + t.energy_cost / ENERGY_PER_METAL,
        "output": out, "bp_cost": t.bp_cost,
        "metal_cost": t.metal_cost, "energy_cost": t.energy_cost,
    }


def effective_bproi(unit: str, old_bp: float, effective_bp: float,
                    nominal_bp: float) -> dict:
    """BPROI corrected for build power you cannot feed.

    The nominal figure assumes every point added gets used. If metal or energy
    caps the usable build power, the return scales by the EFFECTIVE gain."""
    t = OBJECTS[unit]
    nominal = (t.bp_cost / t.bp_income) if t.bp_income else float("inf")
    gain_nominal = (nominal_bp / old_bp) if old_bp else 1.0
    gain_effective = (effective_bp / old_bp) if old_bp else 1.0
    factor = (gain_nominal / gain_effective) if gain_effective > 0 else float("inf")
    return {"nominal_sec": nominal, "effective_sec": nominal * factor,
            "gain_nominal": gain_nominal, "gain_effective": gain_effective,
            "wasted_fraction": max(0.0, 1.0 - gain_effective / gain_nominal)
            if gain_nominal else 0.0}


def _project_row(state: "EcoState", target: str, bp_source: str, n_bp: int,
                 wind: float, horizon: float, dt: float = 0.25) -> dict:
    """Charge forward from `state`: build `n_bp` build-power sources first, then
    `target` forever. Banks and incomes are respected, so a build that cannot be
    paid for slows instead of pretending."""
    s = state.copy()
    s.wind = wind
    metal, energy = s.metal, s.energy
    m_inc, e_inc, bp = s.m_inc, s.e_inc, s.bp
    m_cap, e_cap = s.m_cap, s.e_cap
    queue = [bp_source] * n_bp
    events: List[dict] = []
    t, cur, prog, stalled = 0.0, None, 0.0, 0.0
    n_target = 0
    while t < horizon:
        if cur is None:
            cur = queue.pop(0) if queue else target
            prog = 0.0
        o = OBJECTS[cur]
        need_m = o.metal_cost * bp / o.bp_cost * dt
        need_e = o.energy_cost * bp / o.bp_cost * dt
        avail_m, avail_e = metal + m_inc * dt, energy + e_inc * dt
        scale = 1.0
        if need_m > 0:
            scale = min(scale, avail_m / need_m)
        if need_e > 0:
            scale = min(scale, avail_e / need_e)
        scale = max(0.0, min(1.0, scale))
        if scale < 0.999:
            stalled += dt
        prog += scale * bp * dt / o.bp_cost
        metal = min(metal + m_inc * dt - need_m * scale, m_cap)
        energy = min(energy + e_inc * dt - need_e * scale, e_cap)
        t += dt
        if prog >= 1.0 - 1e-9:
            out = wind if o.wind_powered else o.energy_income
            e_inc += out
            m_inc += o.metal_income
            bp += o.bp_income
            if o.stor_m:
                m_cap += o.stor_m
            if o.stor_e:
                e_cap += o.stor_e
            is_target = (cur == target)
            if is_target:
                n_target += 1
            events.append({"t": round(t, 2), "unit": cur, "target": is_target,
                           "n": n_target if is_target else None, "bp": bp,
                           "m_inc": round(m_inc, 2), "e_inc": round(e_inc, 1)})
            cur = None
    eff = min(bp,
              (m_inc * OBJECTS[target].bp_cost / OBJECTS[target].metal_cost)
              if OBJECTS[target].metal_cost else float("inf"),
              (e_inc * OBJECTS[target].bp_cost / OBJECTS[target].energy_cost)
              if OBJECTS[target].energy_cost else float("inf"))
    return {"n_bp": n_bp, "events": events, "targets": n_target, "end_bp": bp,
            "effective_bp": eff, "stalled": round(stalled, 1),
            "m_inc": m_inc, "e_inc": e_inc, "metal": metal, "energy": energy}


def build_horizon(state: "EcoState", target: str = "Wind", bp_source: str = "ConTurret",
                  wind: float = 11.9, n_rows: int = 5, horizon: float = 240.0,
                  width: int = 92, verbose: bool = True) -> dict:
    """The 2-D plane at one wind speed: build power down, time right.

    Row i invests in i build-power sources before starting on `target`. Marks are
    placed at true completion times, so you can read straight off the chart how far
    right the investment pushes you and where the tighter spacing catches up."""
    rows = [_project_row(state, target, bp_source, i, wind, horizon) for i in range(n_rows + 1)]
    base = rows[0]

    # crossover: first time row i has completed as many targets as row 0
    for r in rows:
        r["crossover"] = None
        if r["n_bp"] == 0:
            continue
        for ev in r["events"]:
            if not ev["target"]:
                continue
            k = ev["n"]
            base_t = next((e["t"] for e in base["events"] if e["target"] and e["n"] == k), None)
            if base_t is not None and ev["t"] <= base_t:
                r["crossover"] = {"t": ev["t"], "n": k, "base_t": base_t}
                break

    if verbose:
        T = OBJECTS[target]
        B = OBJECTS[bp_source]
        rt, rb = roi_figures(target, wind), roi_figures(bp_source, wind)
        print(f"BUILD HORIZON   plane at wind {wind:g} E/s   "
              f"target {target}   scale with {bp_source}")
        print(f"  from t={state.t:.0f}s: {state.m_inc:.2f} M/s, {state.e_inc:.0f} E/s, "
              f"BP {state.bp:.0f}, banks {state.metal:.0f}m/{state.energy:.0f}e")
        print(f"  {target}: {T.metal_cost:g}m {T.energy_cost:g}e {T.bp_cost:g}BP-s -> "
              f"{rt['output']:.1f} E/s | EROI {rt['eroi']:.1f}s | "
              f"total ROI {rt['total_roi_metal']:.1f} metal-equivalent")
        print(f"  {bp_source}: {B.metal_cost:g}m {B.energy_cost:g}e {B.bp_cost:g}BP-s -> "
              f"+{B.bp_income:g} BP | BPROI {rb['bproi']:.1f}s nominal")
        print()
        # The ASCII chart this used to draw placed marks at int(t * chars_per_second) and
        # labelled them n % 10, so two completions inside one character overwrote each
        # other and copy 12 printed as "2". It is gone rather than fixed, because
        # `cadence_table` already draws one segment per copy at its true width.
        print(f"  chart: use --cadence (one segment per {target}, width = its own +time)."
              f"{'':2}This view keeps the ROI table below, which cadence does not compute.")

        print(f"\n  {'row':>14} {'targets':>8} {'end BP':>7} {'eff BP':>7} {'fed':>5} "
              f"{'stall':>6} {'BPROI eff':>10} {'catches row 0':>16}")
        for r in rows:
            eb = effective_bproi(bp_source, state.bp, r["effective_bp"], r["end_bp"])
            fed = eb["gain_effective"] / eb["gain_nominal"] if eb["gain_nominal"] else 1.0
            co = (f"{r['crossover']['t']:.0f}s at #{r['crossover']['n']}"
                  if r.get("crossover") else ("-" if r["n_bp"] else "baseline"))
            bproi = "-" if not r["n_bp"] else (
                "never" if eb["effective_sec"] == float("inf") else f"{eb['effective_sec']:.0f}s")
            print(f"  {'+' + str(r['n_bp']) + ' ' + bp_source[:9]:>14} {r['targets']:>8} "
                  f"{r['end_bp']:>7.0f} {r['effective_bp']:>7.0f} {fed * 100:>4.0f}% "
                  f"{r['stalled']:>5.0f}s {bproi:>10} {co:>16}")
        print(f"\n  'fed' is the share of the build power added that income can actually "
              f"use.\n  BPROI eff = nominal {rb['bproi']:.0f}s scaled by that share; "
              f"unfed build power never pays back.")
    return {"wind": wind, "target": target, "bp_source": bp_source, "rows": rows}


def _e(v: float) -> str:
    """Compact energy figure so a 16-row table still fits a terminal."""
    if abs(v) >= 100000:
        return f"{v / 1000:.0f}k"
    if abs(v) >= 10000:
        return f"{v / 1000:.1f}k"
    return f"{v:.0f}"


def balance_tables(bp: float = 300.0, a: str = "Solar", b: str = "Wind",
                   wind_speeds: Sequence[float] = tuple(range(1, 17)),
                   n_a: int = 8, n_b: int = 12, verbose: bool = True) -> dict:
    """Three views of the same thing, joined on TIME.

      1. the wind grid   — wind speed down the side, turbines built across, and the
                           net energy delivered once that many are standing
      2. the solar row   — one row, because solar does not care what the wind does
      3. the overlay     — the two laid on the same clock: at the moment the Nth
                           panel finishes, how many turbines could have been up
                           instead, what each cost, and the energy difference

    The overlay is the one that answers the question directly. A positive cell means
    the turbines are ahead by that much energy at that moment."""
    A, B = OBJECTS[a], OBJECTS[b]
    a_sec, b_sec = A.bp_cost / bp, B.bp_cost / bp
    a_cols = list(range(1, n_a + 1))
    b_cols = list(range(1, n_b + 1))
    # a wind-speed axis only means anything if the compared structure runs on wind;
    # otherwise its output is fixed and one row says everything
    speeds = list(wind_speeds) if B.wind_powered else [B.energy_income]
    axis = "wind" if B.wind_powered else "E/s"

    # 1. wind grid: net energy when the Nth turbine completes
    grid_b = {}
    for w in speeds:
        grid_b[w] = [cumulative_net_energy(b, bp, n * b_sec, w)["net"] for n in b_cols]
    # 2. solar row: no wind dependence
    row_a = [cumulative_net_energy(a, bp, n * a_sec, 0.0)["net"] for n in a_cols]
    # 3. overlay on the solar clock
    overlay = {}
    anchors = []
    for n in a_cols:
        t = n * a_sec
        anchors.append({"n_a": n, "t": t, "n_b": int(t / b_sec),
                        "metal_a": n * A.metal_cost,
                        "metal_b": int(t / b_sec) * B.metal_cost})
    for w in speeds:
        overlay[w] = [cumulative_net_energy(b, bp, x["t"], w)["net"]
                      - cumulative_net_energy(a, bp, x["t"], 0.0)["net"] for x in anchors]

    if verbose:
        a_mps, a_eps = A.metal_cost / a_sec, A.energy_cost / a_sec
        b_mps, b_eps = B.metal_cost / b_sec, B.energy_cost / b_sec
        print(f"{bp:g} BUILD POWER")
        print(f"  {a:9} {A.bp_cost:g} BP-s -> one every {a_sec:5.2f}s   "
              f"{A.metal_cost:>4g}m {A.energy_cost:>5g}e each   gives {A.energy_income:g} E/s")
        print(f"  {b:9} {B.bp_cost:g} BP-s -> one every {b_sec:5.2f}s   "
              f"{B.metal_cost:>4g}m {B.energy_cost:>5g}e each   gives "
              f"{'wind' if B.wind_powered else f'{B.energy_income:g}'} E/s")
        print(f"  NONSTOP COSTS   {a}: {a_mps:6.2f} M/s + {a_eps:5.1f} E/s      "
              f"{b}: {b_mps:6.2f} M/s + {b_eps:5.1f} E/s")
        print(f"  (assumed affordable below. {b} is {a_mps / b_mps:.2f}x cheaper in metal "
              f"per second and {a_sec / b_sec:.2f}x faster per building, "
              f"but taxes energy where {a} does not.)")

        print(f"\n1. {b.upper()} — net energy delivered once N are standing")
        print(f"   {'':6}" + "".join(f"{n:>7}" for n in b_cols) + f"   {b.lower()}s standing")
        print(f"   {'':6}" + "".join(f"{n * b_sec:>7.0f}" for n in b_cols) + "   seconds")
        print(f"   {'':6}" + "".join(f"{n * B.metal_cost:>7.0f}" for n in b_cols) + "   metal spent")
        print(f"   {axis:>6}" + "".join(f"{n * B.energy_cost:>7.0f}" for n in b_cols) + "   energy spent building")
        print("   " + "-" * (6 + 7 * len(b_cols)))
        for w in speeds:
            print(f"   {w:>6.0f}" + "".join(f"{_e(v):>7}" for v in grid_b[w]))

        print(f"\n2. {a.upper()} — one row, independent of the axis above")
        print(f"   {'':6}" + "".join(f"{n:>7}" for n in a_cols) + f"   {a.lower()}s standing")
        print(f"   {'':6}" + "".join(f"{n * a_sec:>7.0f}" for n in a_cols) + "   seconds")
        print(f"   {'':6}" + "".join(f"{n * A.metal_cost:>7.0f}" for n in a_cols) + "   metal spent")
        print(f"   {'':6}" + "".join(f"{n * A.energy_cost:>7.0f}" for n in a_cols) + "   energy spent building")
        print(f"   {'net E':>6}" + "".join(f"{_e(v):>7}" for v in row_a))

        print(f"\n3. OVERLAY — same clock. Cell = {b} net energy minus {a} net energy.")
        print(f"   positive means {b} is ahead at that moment.")
        print(f"   {'':6}" + "".join(f"{x['n_a']:>8}" for x in anchors) + f"   {a} built")
        print(f"   {'':6}" + "".join(f"{x['t']:>8.0f}" for x in anchors) + "   seconds")
        print(f"   {'':6}" + "".join(f"{x['n_b']:>8}" for x in anchors) + f"   {b} instead")
        print(f"   {'':6}" + "".join(f"{x['metal_a']:>8}" for x in anchors) + f"   metal on {a}")
        print(f"   {'':6}" + "".join(f"{x['metal_b']:>8.0f}" for x in anchors) + f"   metal on {b}")
        print(f"   {axis:>6}" + "".join(f"{x['n_b'] * B.energy_cost:>8.0f}" for x in anchors)
              + f"   energy on {b} (build)")
        print("   " + "-" * (6 + 8 * len(anchors)) + "   crosses at")
        for w in speeds:
            cells = "".join(f"{_e(v):>8}" for v in overlay[w])
            bt = energy_balance_time(bp, w, a, b)
            tail = f"{bt:.0f}s ({bt / a_sec:.0f} {a.lower()}s in)" if bt else "never"
            print(f"   {w:>6.0f}{cells}   {tail}")
        cross = A.energy_income / A.bp_cost * B.bp_cost
        if B.wind_powered:
            print()
            print(f"   Sign flips for good above {cross:.2f} E/s. Below it every cell stays "
                  f"negative however far right you go, because {b} buys less energy "
                  f"per BP-second than {a}.")
        else:
            print()
            print(f"   {b} would need more than {cross:.2f} E/s of output to overtake {a} "
                  f"at equal build power; it makes {B.energy_income:g}.")
    return {"bp": bp, "wind_grid": grid_b, "solar_row": row_a,
            "overlay": overlay, "anchors": anchors,
            "a_sec": a_sec, "b_sec": b_sec}


def rate_report(bp_levels: Sequence[float] = (300, 450, 610, 1000),
                wind: Optional[float] = None) -> dict:
    """Print the four-resource picture: drain rates, what income sustains them,
    what the opening bank funds, and the three separate break-evens."""
    w = DEFAULT_WIND if wind is None else wind
    com = OBJECTS["Commander"]
    print("DRAIN RATES — metal and energy consumed per second while building")
    print(f"  {'object':11} {'M/BP-s':>8} {'E/BP-s':>8}   " +
          "  ".join(f"{'@' + str(int(b)) + 'BP':>16}" for b in bp_levels))
    for n in ("Mex", "Solar", "Wind", "BotWorker", "BotFactory"):
        t = OBJECTS[n]
        cells = []
        for b in bp_levels:
            r = drain_rates(n, b)
            cells.append(f"{r['m_per_s']:6.1f}M {r['e_per_s']:6.0f}E")
        print(f"  {n:11} {t.metal_cost / t.bp_cost:8.4f} {t.energy_cost / t.bp_cost:8.4f}   "
              + "  ".join(f"{c:>16}" for c in cells))
    print(f"\nTO KEEP BUILD POWER BUSY ON EXTRACTORS you need this much ENERGY INCOME")
    for b in bp_levels:
        r = drain_rates("Mex", b)
        print(f"  {b:5.0f} BP -> {r['e_per_s']:6.1f} E/s and {r['m_per_s']:5.1f} M/s "
              f"(one every {r['seconds']:.1f}s)")
    print(f"  the commander alone supplies {com.energy_income:g} E/s, so at 300 BP it covers "
          f"{com.energy_income / drain_rates('Mex', 300)['e_per_s'] * 100:.0f}% of continuous extractor building")
    rw = bank_runway("Mex", 300, _BASE["metal"], _BASE["energy"], com.metal_income, com.energy_income)
    print(f"\nWHAT THE {_BASE['metal']:g}/{_BASE['energy']:g} OPENING BANK FUNDS at 300 BP, nonstop extractors:")
    print(f"  {rw['seconds']:.1f}s of building = {rw['count']:.1f} extractors before the "
          f"{rw['binding']} bank empties (gap {rw['e_gap']:.0f} E/s)")
    be = generator_breakevens()
    print(f"\nBREAK-EVENS (wind overtakes solar above each)")
    print(f"  energy rate  : {be['rate_breakeven']:5.2f} E/s   rates per metal match here; below it "
          f"wind NEVER catches up")
    print(f"  build power  : {be['bp_breakeven']:5.2f} E/s   "
          f"(solar buys {be['solar_e_per_bp_s'] * 1000:.2f} E/s per 1000 BP-s invested)")
    print(f"  build energy : never        "
          f"(solar costs {be['solar_build_energy']:g} E to erect, wind costs {be['wind_build_energy']:g})")
    print(f"  metal, fungible approx: {be['metal_breakeven']:5.2f} E/s  "
          f"(prices the 175 as metal at {ENERGY_PER_METAL}:1 - convenient, misleading early)")

    print(f"\nHOW LONG WIND TAKES TO HAVE DELIVERED MORE ENERGY, per metal spent")
    print(f"  a turbine owes {generator_energy_race(w)['debt_per_metal']:.3f} energy per metal before it "
          f"has produced anything; a panel owes nothing")
    print(f"  {'wind E/s':>9} {'solar E/s/m':>12} {'wind E/s/m':>11} {'catch-up':>10} {'+build@600BP':>13} {'BP work vs solar':>17}")
    for wv in (4, 5, 5.5, 6, 8, 10, 12, 14, 16, 20):
        r = generator_energy_race(wv, bp=600)
        cu = f"{r['catchup_sec']:.0f}s" if r["catchup_sec"] else "never"
        cf = f"{r['catchup_sec_from_commit']:.0f}s" if r.get("catchup_sec_from_commit") else "never"
        print(f"  {wv:9.1f} {r['solar_rate_per_metal']:12.4f} {r['wind_rate_per_metal']:11.4f} "
              f"{cu:>10} {cf:>13} {r['build_work_ratio']:16.2f}x")
    r = generator_energy_race(w, bp=600)
    cu = f"{r['catchup_sec']:.0f}s after it finishes" if r["catchup_sec"] else "never"
    print(f"\n  at this map's {w:g} E/s: wind's rate per metal is "
          f"{'higher' if r['wind_ahead_on_rate'] else 'LOWER'}, and it pulls level {cu}. "
          f"It needs {r['build_work_ratio']:.1f}x solar's build work for the same metal.")
    return {"breakevens": be, "wind": w, "race": r}


# ──────────────────────────────────────────────────────────────────────────
# Opening comparison — solar vs wind, held to the same plan
#
# The question is usually posed as "which generator is more efficient", which is
# the wrong frame. A mex costs 500 ENERGY. In the first minutes energy is the
# binding resource, so every point of energy you spend erecting a turbine is a
# point you cannot spend claiming a metal spot. That is the whole trade:
#
#   solar  155 metal,   0 energy  -> +20 E/s        costs no energy to place
#   wind    40 metal, 175 energy  -> +wind E/s      cheaper in metal, but the
#                                                   175 competes with the mex
#
# So solar buys EARLIER METAL at a worse metal price, and wind buys a CHEAPER
# ECONOMY that arrives later because it taxes the same energy the mexes need.
#
# The simulation holds everything else identical between the two branches — same
# starting bank, same mex walk distances, same build-power schedule, same policy
# — and varies only the generator. Anything it reports is therefore attributable
# to the generator and nothing else.
#
# LIMIT: Environment builds SERIALLY on one pooled build power. A real opening
# overlaps a walking worker with a building commander, so absolute times run
# late. Both branches are serialised identically, so the COMPARISON holds even
# though the clock does not match a replay.
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class OpeningStep:
    sec: float
    what: str
    why: str
    metal: float
    energy: float
    m_inc: float
    e_inc: float
    bp: float


@dataclass
class OpeningResult:
    label: str
    generator: str
    wind: float
    steps: List[OpeningStep] = field(default_factory=list)
    mex_sec: List[float] = field(default_factory=list)
    t_target: Optional[float] = None       # when the last wanted mex finished
    generators: int = 0
    metal_on_energy: float = 0.0
    bp_buys: int = 0
    has_factory: bool = False
    min_metal: float = 1e18       # lowest bank seen; negative means the sim cheated
    min_energy: float = 1e18
    gathered: float = 0.0                  # cumulative metal produced, ignoring caps
    checkpoint: Dict[float, dict] = field(default_factory=dict)
    end: Optional[dict] = None

    def at_target(self) -> str:
        return f"{self.t_target:.1f}s" if self.t_target else "not reached"




def mex_walk_from_map(map_name: str = "All That Glitters", team: int = 0,
                      count: int = 7, unit: str = "commander") -> List[float]:
    """Walk seconds to the `count` nearest metal spots for a team's spawn."""
    mp = read_map(map_name)
    pos = mp.start_position(team)
    if pos is None:
        raise KeyError(f"{mp.shortname} has no start position for team {team}")
    return [r["walk_sec"] for r in mp.spots_from(pos[0], pos[1], unit, count)]


def simulate_opening(generator: str = "Solar", *, wind: Optional[float] = None,
                     mex_walk_sec: Optional[Sequence[float]] = None, target_mex: int = 7,
                     horizon: float = 300.0, start_sec: float = 3.0,
                     checkpoints: Optional[Sequence[float]] = (60.0, 120.0, 180.0, 240.0, 300.0),
                     label: Optional[str] = None) -> OpeningResult:
    """Expand to `target_mex` extractors using `generator` as the only energy source.

    Both branches run the SAME RULE, not the same build. That distinction is the
    whole point: a solar opening and a wind opening face different resource
    situations, so the same rule produces different builds, which is what a player
    actually does. Forcing an identical build order makes one side sit on metal it
    would obviously have spent, and the comparison becomes meaningless.

    The rule, in the order it is asked each time:

      1. Would the next thing stall waiting for ENERGY? Buy a generator.
      2. Is metal arriving faster than the builders can spend it
         (`m_inc > bp * BP_ABSORB_PER_POINT`)? Buy build power — a factory the
         first time, workers after. This is the "never bank metal" rule.
      3. Otherwise take the next metal spot.

    So build-power count, generator count and their timing are all OUTPUTS here,
    decided by each branch's own circumstances, not inputs held equal."""
    walks = list(mex_walk_sec if mex_walk_sec is not None else DEFAULT_MEX_WALK_SEC)
    while len(walks) < target_mex:
        walks.append(walks[-1] if walks else 0.0)
    w = DEFAULT_WIND if wind is None else wind
    env = Environment(time=start_sec, verbose=False, wind=w)
    res = OpeningResult(label=label or f"{generator} opening", generator=generator, wind=w)

    def record(what: str, why: str) -> None:
        res.steps.append(OpeningStep(round(env.time, 1), what, why, round(env.metal, 1),
                                     round(env.energy, 1), round(env.income_m(), 2),
                                     round(env.income_e(), 1), env.total_bp()))

    guard = 0
    marks = sorted(checkpoints or ())
    while env.time < horizon and guard < 400:
        guard += 1
        while marks and env.time >= marks[0]:
            res.checkpoint[marks.pop(0)] = _snap(env, len(res.mex_sec), res.generators)
        # what are we trying to build next? mexes first, then build power.
        goal = "Mex" if len(res.mex_sec) < target_mex else generator
        bt = env.build_times(goal)
        if not math.isfinite(bt["total"]):
            break
        # 1. would it stall waiting for ENERGY? then buy a generator first. This is
        #    the only place the two branches differ.
        if bt["energy"] > bt["bp"] + 1e-9:
            before = env.income_e()
            if not env.build(generator):
                break
            res.generators += 1
            res.metal_on_energy += OBJECTS[generator].metal_cost
            record(generator, f"{goal} would wait {bt['energy'] - bt['bp']:.1f}s on energy "
                              f"({before:.0f}->{env.income_e():.0f} E/s)")
            continue
        # 2. is metal arriving faster than the builders can spend it? buy build power.
        #    Each branch hits this at its own moment, from its own metal position.
        absorb = env.total_bp() * BP_ABSORB_PER_POINT
        if env.income_m() > absorb:
            unit = "BotFactory" if not res.has_factory else "BotWorker"
            if env.build(unit):
                res.has_factory = True
                res.bp_buys += 1
                record(unit, f"{env.income_m():.1f} M/s > {absorb:.1f} the pool can spend")
                continue
        # 3. otherwise build the goal. An extractor walks to its spot FIRST.
        if goal == "Mex":
            idx = len(res.mex_sec)
            if walks[idx] > 0:
                env.advance(walks[idx])
            if not env.build("Mex"):
                break
            res.mex_sec.append(round(env.time, 1))
            record(f"Mex #{idx + 1}", f"after {walks[idx]:.1f}s walk")
        else:
            if not env.build(generator):
                break
            res.generators += 1
            res.metal_on_energy += OBJECTS[generator].metal_cost
            record(generator, "mexes done, scaling energy")
    for m in marks:
        res.checkpoint[m] = _snap(env, len(res.mex_sec), res.generators)
    if len(res.mex_sec) >= target_mex:
        res.t_target = res.mex_sec[target_mex - 1]
    res.gathered = round(env.gathered_m, 1)
    res.end = env.snapshot()
    res.end["gathered_m"] = round(env.gathered_m, 1)
    res.end["gathered_e"] = round(env.gathered_e, 1)
    return res


def simulate_opening_parallel(generator: str = "Solar", *, wind: Optional[float] = None,
                              mex_walk_sec: Optional[Sequence[float]] = None, target_mex: int = 7,
                              horizon: float = 300.0, start_sec: float = 3.0, dt: float = 0.25,
                              checkpoints: Optional[Sequence[float]] = (60.0, 120.0, 180.0, 240.0, 300.0),
                              wind_source: Optional[object] = None, gen_walk_sec: float = 0.0,
                              label: Optional[str] = None) -> OpeningResult:
    """The same rule, but with builders working CONCURRENTLY.

    The serial model idles the whole economy during a 27-second walk to the
    seventh spot, so metal piles up in a bank no real player would carry. Here
    each builder holds its own task: a worker can be walking out to a spot while
    the commander keeps building at home, which is what actually happens and what
    lets a real opening spend down toward zero.

    Resources are a shared pool. A build draws metal and energy in proportion to
    the work done, and when the pool cannot pay, every builder slows together —
    that is the stall, and it is the mechanism the solar/wind question turns on."""
    walks = list(mex_walk_sec if mex_walk_sec is not None else DEFAULT_MEX_WALK_SEC)
    while len(walks) < target_mex:
        walks.append(walks[-1] if walks else 0.0)
    w = DEFAULT_WIND if wind is None else wind
    env = Environment(time=start_sec, verbose=False, wind=w)
    res = OpeningResult(label=label or f"{generator} (parallel)", generator=generator, wind=w)
    marks = sorted(checkpoints or ())

    # each builder: bp, and its current job
    crew = [{"bp": OBJECTS["Commander"].bp_income, "job": None, "walk": 0.0}]
    mex_started = 0

    def draw_e(name: str, bp: float) -> float:
        """E/s this builder would pull if it worked `name` at full speed."""
        t = OBJECTS[name]
        return t.energy_cost * bp / max(t.bp_cost, 1e-9)

    def want(b: dict, buffer_sec: float = 25.0) -> str:
        """The rule, asked whenever a builder needs a job.

        What it WANTS comes first (spend the metal), then energy is checked as a
        feasibility constraint rather than a threshold: if the crew's draw would
        outrun income and the bank cannot cover the gap for `buffer_sec`, put up a
        generator instead. That is self-tuning — it buys energy exactly when the
        plan is about to be throttled by it, so neither generator gets an
        arbitrary head start."""
        total_bp = sum(x["bp"] for x in crew)
        absorb = total_bp * BP_ABSORB_PER_POINT
        if env.income_m() > absorb:
            desired = "BotFactory" if not res.has_factory else "BotWorker"
        elif mex_started < target_mex:
            desired = "Mex"
        else:
            # mexes done and metal is inside what the crew can spend: keep turning
            # metal into CAPACITY, never into generators. Energy above what build
            # power can consume is overflow, and a rule that defaults to building
            # more of it will happily bury both branches in dead turbines.
            desired = "BotWorker"
        current = sum(draw_e(x["job"]["name"], x["bp"]) for x in crew
                      if x["job"] and x["walk"] <= 0)
        gap = current + draw_e(desired, b["bp"]) - env.income_e()
        if gap > 0 and env.energy / gap < buffer_sec:
            return generator
        return desired

    def start(b: dict, name: str) -> None:
        nonlocal mex_started
        t = OBJECTS[name]
        b["job"] = {"name": name, "work": t.bp_cost, "metal": t.metal_cost, "energy": t.energy_cost}
        b["walk"] = 0.0
        if name == "Mex":
            b["walk"] = walks[mex_started] if mex_started < len(walks) else walks[-1]
            mex_started += 1
        elif name == generator:
            # placing a generator is not free: the builder has to reach open ground.
            # Wind needs roughly twice as many buildings as solar for the same
            # income, so this cost falls on wind twice as often.
            b["walk"] = gen_walk_sec

    while env.time < horizon:
        # live wind: a constant average flatters turbines, because the cost of wind
        # is not its mean, it is the lulls that stall a build mid-way
        if wind_source is not None:
            env.wind = wind_source.at(env.time)
        while marks and env.time >= marks[0]:
            res.checkpoint[marks.pop(0)] = _snap(env, len(res.mex_sec), res.generators)
        for b in crew:
            if b["job"] is None:
                n = want(b)
                if n:
                    start(b, n)
        # how much work each builder wants to do this tick, and what it costs
        demand_m = demand_e = 0.0
        active = []
        for b in crew:
            if b["job"] is None:
                continue
            if b["walk"] > 0:
                continue
            j = b["job"]
            frac = min(1.0, (b["bp"] * dt) / max(j["work"], 1e-9))
            active.append((b, frac))
            demand_m += j["metal"] * frac
            demand_e += j["energy"] * frac
        # pay what we can; everyone slows by the same factor (the stall)
        avail_m = env.metal + env.income_m() * dt
        avail_e = env.energy + env.income_e() * dt
        scale = 1.0
        if demand_m > avail_m and demand_m > 0:
            scale = min(scale, avail_m / demand_m)
        if demand_e > avail_e and demand_e > 0:
            scale = min(scale, avail_e / demand_e)
        env.advance(dt)
        # progress is tracked as a fraction of each job; cost is drawn in the same
        # proportion, so a job that is 40% built has paid 40% of its metal and energy
        # spend, then VERIFY. A negative bank would mean the simulation paid for
        # work with resources it did not have, and every number after it is fiction.
        env.metal -= demand_m * scale
        env.energy -= demand_e * scale
        res.min_metal = min(res.min_metal, env.metal)
        res.min_energy = min(res.min_energy, env.energy)
        if env.metal < -1e-6 or env.energy < -1e-6:
            raise AssertionError(f"bounds violated at t={env.time:.2f}: "
                                 f"metal {env.metal:.3f}, energy {env.energy:.3f}")
        env.metal = max(0.0, env.metal)
        env.energy = max(0.0, env.energy)
        for b, frac in active:
            j = b["job"]
            j.setdefault("done", 0.0)
            j["done"] += frac * scale
            if j["done"] >= 1.0 - 1e-9:
                name = j["name"]
                env.apply_completion(name)
                if name == "Mex":
                    res.mex_sec.append(round(env.time, 1))
                elif name in ("BotFactory", "BotWorker"):
                    res.has_factory = True
                    res.bp_buys += 1
                    crew.append({"bp": OBJECTS[name].bp_income, "job": None, "walk": 0.0})
                else:
                    res.generators += 1
                    res.metal_on_energy += OBJECTS[name].metal_cost
                res.steps.append(OpeningStep(round(env.time, 1), name, "", round(env.metal, 1),
                                             round(env.energy, 1), round(env.income_m(), 2),
                                             round(env.income_e(), 1), sum(x["bp"] for x in crew)))
                b["job"] = None
        for b in crew:
            if b["walk"] > 0:
                b["walk"] = max(0.0, b["walk"] - dt)
    for m in marks:
        res.checkpoint[m] = _snap(env, len(res.mex_sec), res.generators)
    if len(res.mex_sec) >= target_mex:
        res.t_target = res.mex_sec[target_mex - 1]
    res.gathered = round(env.gathered_m, 1)
    res.end = env.snapshot()
    res.end["gathered_m"] = round(env.gathered_m, 1)
    res.end["crew"] = len(crew)
    res.end["min_metal"] = round(res.min_metal, 3)
    res.end["min_energy"] = round(res.min_energy, 3)
    res.end["bounds_ok"] = res.min_metal >= -1e-6 and res.min_energy >= -1e-6
    return res


def compare_at_time(at_sec: float = 180.0, wind: Optional[float] = None,
                    target_mex: int = 7, gen_walk_sec: float = 0.0,
                    verbose: bool = True) -> dict:
    """Both branches, same elapsed TIME, same rule, bounds verified.

    Not "four solars against eight winds" — that normalisation smuggles in an
    answer. Each branch simply runs the clock to `at_sec` and we look at what it
    is holding, having checked that neither ever went below zero on metal or
    energy (which would mean the simulation was spending resources it did not
    have and the whole comparison was fiction)."""
    out = {}
    for gen in ("Solar", "Wind"):
        r = simulate_opening_parallel(gen, wind=wind, target_mex=target_mex,
                                      horizon=at_sec, gen_walk_sec=gen_walk_sec,
                                      checkpoints=(at_sec,))
        out[gen] = r
    if verbose:
        w = out["Wind"].wind
        print(f"EVEN-TIME COMPARISON at t={at_sec:g}s   (map wind {w:g} E/s, "
              f"generator placement {gen_walk_sec:g}s)")
        print(f"  {'':8} {'mex':>4} {'gens':>5} {'BP':>6} {'M/s':>7} {'E/s':>7} {'E cap':>7} "
              f"{'E wasted':>9} {'bank M':>7} {'made M':>8} {'usable v/s':>10} {'bounds':>7}")
        for gen, r in out.items():
            e = r.end or {}
            uv = usable_value_per_s(e.get("mInc", 0), e.get("eInc", 0), e.get("bp", 0))
            ok = "ok" if e.get("bounds_ok") else f"BAD"
            print(f"  {gen:8} {len(r.mex_sec):4} {r.generators:5} {e.get('bp', 0):6.0f} "
                  f"{e.get('mInc', 0):7.2f} {e.get('eInc', 0):7.1f} {uv['cap']:7.0f} "
                  f"{uv['wasted']:9.0f} {e.get('metal', 0):7.0f} {r.gathered:8.0f} "
                  f"{uv['value_per_s']:10.2f} {ok:>7}")
        s, wd = out["Solar"], out["Wind"]
        se, we = s.end or {}, wd.end or {}
        print(f"  delta (wind - solar): mex {len(wd.mex_sec) - len(s.mex_sec):+d}  "
              f"BP {we.get('bp', 0) - se.get('bp', 0):+.0f}  "
              f"M/s {we.get('mInc', 0) - se.get('mInc', 0):+.2f}  "
              f"E/s {we.get('eInc', 0) - se.get('eInc', 0):+.1f}  "
              f"bank M {we.get('metal', 0) - se.get('metal', 0):+.0f}  "
              f"made M {wd.gathered - s.gathered:+.0f}")
    return out


def _snap(env: "Environment", mexes: int, generators: int) -> dict:
    return {"sec": round(env.time, 1), "mexes": mexes, "generators": generators,
            "m_inc": round(env.income_m(), 2), "e_inc": round(env.income_e(), 1),
            "bank_m": round(env.metal), "bank_e": round(env.energy),
            "bp": env.total_bp(), "gathered_m": round(env.gathered_m, 1),
            "value_per_s": round(env.income_m() + env.income_e() / ENERGY_PER_METAL, 2)}


def run_opening(env_after: OpeningResult, extra_sec: float) -> dict:
    """Not used directly — kept as the seam for extending a finished opening."""
    return dict(env_after.end or {})


def compare_openings(wind: Optional[float] = None, target_mex: int = 7,
                     mex_walk_sec: Optional[Sequence[float]] = None,
                     verbose: bool = True) -> Dict[str, OpeningResult]:
    """Solar branch vs wind branch, same plan, same build power, same walks."""
    out = {}
    for gen in ("Solar", "Wind"):
        out[gen] = simulate_opening(gen, wind=wind, target_mex=target_mex,
                                    mex_walk_sec=mex_walk_sec)
    if verbose:
        w = out["Wind"].wind
        print(f"Opening to {target_mex} mex — solar vs wind at {w:g} E/s per turbine")
        print(f"  start {_BASE['metal']:g}/{_BASE['energy']:g} metal/energy at t={out['Solar'].steps[0].sec if out['Solar'].steps else 3:g}s, "
              f"walks {', '.join(f'{x:.0f}s' for x in (mex_walk_sec or DEFAULT_MEX_WALK_SEC)[:target_mex])}")
        for gen, r in out.items():
            e = r.end or {}
            print(f"\n  {gen:6} {target_mex} mex at {r.at_target():>8}   "
                  f"{r.generators} x {gen} = {r.metal_on_energy:.0f} metal on energy")
            print(f"         end: {e.get('mInc', 0):.2f} M/s, {e.get('eInc', 0):.0f} E/s, "
                  f"bank {e.get('metal', 0):.0f}m/{e.get('energy', 0):.0f}e, BP {e.get('bp', 0):.0f}")
            print(f"         mex times: " + ", ".join(f"{t:.0f}" for t in r.mex_sec))
        s, wd = out["Solar"], out["Wind"]
        if s.t_target and wd.t_target:
            d = wd.t_target - s.t_target
            faster, slower = ("solar", "wind") if d > 0 else ("wind", "solar")
            print(f"\n  => {faster} reaches {target_mex} mex {abs(d):.1f}s before {slower}")
    return out


# ════════════════════════════════════════════════════════════════════════════
# 8. ROI REPORT  (was eco_calculator.main)
# ════════════════════════════════════════════════════════════════════════════

def generator_roi_report(builder_bp: float = DEFAULT_BUILDER_BP,
                         wind_avg: Optional[float] = None) -> None:
    print(f"Generator ROI  ({ENERGY_PER_METAL} E = 1 M, builder {builder_bp:.0f} BP)")
    print(f"  {'gen':<10} {'out E/s':>8} {'BuildT':>8} {'EROI':>10} {'TROI':>8}")
    rows = [("Solar", OBJECTS["Solar"].energy_income),
            ("Wind", wind_avg if wind_avg is not None else OBJECTS["Wind"].energy_income),
            ("AdvSolar", OBJECTS["AdvSolar"].energy_income)]
    for name, out in rows:
        o = OBJECTS[name]
        eroi = "build" if o.energy_cost == 0 else f"{o.eroi(out, builder_bp):.1f}s"
        print(f"  {name:<10} {out:>8.1f} {o.build_time(builder_bp):>7.1f}s "
              f"{eroi:>10} {o.troi(out):>7.0f}s")


# ════════════════════════════════════════════════════════════════════════════
# 9. PARITY  — the contract between this file, splendid_buildSimulator.js and
#    positions/state_api.py: all three resolve the same files to these numbers.
# ════════════════════════════════════════════════════════════════════════════

# The demo opening (walk distances in grid squares, measured off the map).
DEMO_ORDER = [("Mex", 2.0), ("Mex", 2.0), ("Solar", 1.0),
              ("Mex", 2.0), ("Solar", 1.0), ("BotFactory", 1.5),
              ("Mex", 4.0), ("Mex", 4.0)]
# bar_calc.py's __main__: same opening, no walks, t starts at 3, +1 s per build (its min_add_time).
BAR_CALC_ORDER = ["Mex", "Mex", "Solar", "Mex", "Solar", "BotFactory", "Mex", "Mex"]


def compute_parity() -> dict:
    u = Environment(verbose=False).build_order(DEMO_ORDER)
    c = Environment(time=3.0, verbose=False)
    for name in BAR_CALC_ORDER:
        c.construct_object(name, min_add_time=1.0)
    objs = {}
    for n, o in OBJECTS.items():
        objs[n] = {"kind": o.kind, "metal": o.metal_cost, "energy": o.energy_cost, "bp": o.bp_cost,
                   "mInc": o.metal_income, "eInc": o.energy_income, "storE": o.stor_e, "storM": o.stor_m,
                   "builderBp": o.bp_income, "speed": o.speed, "range": o.build_range,
                   "converter": o.converter, "windPowered": o.wind_powered, "factory": o.factory,
                   "defName": o.def_name, "provisional": o.provisional}
    wind_out = OBJECTS["Wind"].energy_income
    solar_out = OBJECTS["Solar"].energy_income
    return {
        "generatedBy": "bar-calc/bar_unified.py --write-parity",
        "config": os.path.relpath(ED.CONFIG_PATH, ED.REPO_ROOT).replace("\\", "/"),
        "engineDefs": [s["path"] for s in ED.engine_sources() if s["present"]],
        "constants": {"energyPerMetal": ENERGY_PER_METAL, "defaultBuilderBp": DEFAULT_BUILDER_BP,
                      "defaultWind": DEFAULT_WIND, "gameFps": GAME_FPS,
                      "buildRangeInGridSquares": BUILD_RANGE_IN_GRID_SQUARES,
                      "elmosPerGridSquare": ELMOS_PER_GRID_SQUARE},
        "profiles": {k: {"buildRange": p["build_range"], "speed": p["speed"], "bp": p["bp"]}
                     for k, p in UNIT_PROFILES.items()},
        "objects": objs,
        "aliases": ALIASES,
        "roi": {"solarTroi": OBJECTS["Solar"].troi(solar_out), "windTroi": OBJECTS["Wind"].troi(wind_out),
                "windEroi": OBJECTS["Wind"].eroi(wind_out), "solarBuildTime": OBJECTS["Solar"].build_time(),
                "walkCon400": walk_time(400.0, "con_bot")},
        "unifiedDemo": {"order": [list(e) for e in DEMO_ORDER], "result": u.snapshot()},
        "barCalcDemo": {"start": {"time": 3.0}, "minAddTime": 1.0, "order": BAR_CALC_ORDER, "result": c.snapshot()},
        "legion": {"constants": ED.legion_constants(), "actions": ED.legion_actions(),
                   "unitCosts": {k: list(v) for k, v in ED.legion_unit_costs().items()}},
    }


def write_parity(path: str = ED.PARITY_PATH) -> str:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(compute_parity(), f, indent=1, ensure_ascii=False)
        f.write("\n")
    return path


def _flatten(prefix: str, v, out: dict) -> None:
    if isinstance(v, dict):
        for k, x in v.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), x, out)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            _flatten(f"{prefix}[{i}]", x, out)
    else:
        out[prefix] = v


def selftest_time_to_build(verbose: bool = False) -> bool:
    """Part of `--selftest`: the analytic duration must still match the simulation."""
    r = validate_time_to_build(verbose=verbose)
    if not r["ok"]:
        print("selftest FAILED: time_to_build drifted from the simulation, worst "
              + ("%.4f" % r["worst"]) + "s")
    return bool(r["ok"])


def selftest_goal(verbose: bool = False) -> bool:
    """Part of `--selftest`: the two dimensions must cross where they should.

    Energy-bound: the goal itself stalls, so no amount of build power helps and the
    window must be EMPTY. Build-power-bound: the detour must pay, and the window must
    close before the last copy because a source bought too late cannot repay itself."""
    ok, bad = True, []

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            bad.append(msg)

    # 1. income cannot feed the build power already standing -> detour is pointless
    tight = EcoState(t=0.0, metal=1500, energy=1500, m_inc=29.6, e_inc=313.0, bp=1250,
                     m_cap=4000, e_cap=8000, wind=12.0)
    a = goal_plan(tight, "AdvSolar", 4, "ConTurret", 3, verbose=False)
    check(a["baseline_total"] is not None, "the energy-bound baseline should still build")
    check(a["window"] == [], "energy-bound: the crossover window must be EMPTY, got "
          + str(a["window"]))
    check(a["best"]["sources"] == 0, "energy-bound: the best plan is no detour")
    base = a["grid"][0][0]
    check(base["goal_stall"] > 1.0 and "energy" in base["goal_bound"],
          "energy-bound: the goal itself should stall on energy")

    # 2. income ample, hands short -> the detour must pay, and stop paying near the end
    loose = EcoState(t=0.0, metal=2000, energy=8000, m_inc=25.0, e_inc=900.0, bp=300,
                     m_cap=4000, e_cap=20000, wind=12.0)
    b = goal_plan(loose, "AdvSolar", 6, "ConTurret", 3, verbose=False)
    check(b["grid"][0][0]["goal_stall"] < 0.5,
          "build-power-bound: the goal should NOT stall")
    check(b["able_from"] == 0, "build-power-bound: the source is payable immediately")
    check(b["sensible_until"] is not None and b["sensible_until"] < 6,
          "the detour must stop paying before the last copy, got "
          + str(b["sensible_until"]))
    check(b["window"], "build-power-bound: the window must NOT be empty")
    check(b["best"]["sources"] > 0, "build-power-bound: the best plan uses the detour")
    check(b["best"]["saved"] > 10.0, "the detour should save real time, got "
          + str(b["best"]["saved"]))
    # inserting after the last copy can never beat inserting before it
    check(b["grid"][1][6]["total"] > b["grid"][1][0]["total"],
          "a source bought after the last copy cannot help")
    if not ok:
        print("selftest FAILED: goal planner")
        for m in bad:
            print("  " + m)
    return ok


def selftest_pools(verbose: bool = False) -> bool:
    """Part of `--selftest`: a cross must relieve the pool that is bound.

    Measured regression: with `on=Mex` and `bp_source=ConTurret` the walk returned
    4.5 Wind : 1 ConTurret, which is an artifact - a con turret is immobile, joins BASE,
    and can never claim a metal spot, so the expand pool stays empty and the walk keeps
    buying hands that cannot do the job."""
    ok = True
    bad = []

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            bad.append(msg)

    check(joins_pool("ConTurret") == "base", "a con turret's BP joins base")
    check(joins_pool("BotWorker", "expand") == "expand",
          "a mobile worker assigned to expand joins expand")
    check(joins_pool("BotWorker", "base") == "base",
          "a mobile worker assigned to base joins base")
    check(joins_pool("BotFactory") == "factory", "a factory's BP joins factory")
    check(joins_pool("Solar") == "none", "a solar contributes no build power")

    check(work_pool("Mex") == "expand", "extractors are expand work")
    check(work_pool("Wind") == "base", "turbines are base work")
    check(work_pool("BotWorker") == "factory", "a factory product is factory work")

    check(not cross_relieves("ConTurret", "Mex")["relieves"],
          "a con turret must NOT be reported as relieving expansion")
    check(cross_relieves("BotWorker", "Mex", "expand")["relieves"],
          "a con bot assigned to expand DOES relieve expansion")
    check(cross_relieves("ConTurret", "Wind")["relieves"],
          "a con turret does relieve base work")
    check("immobile" in cross_relieves("ConTurret", "Mex")["why"],
          "the mismatch should say why a con turret cannot claim")

    # an empty pool must stop the cadence rather than silently using total BP
    st = EcoState(t=0.0, metal=1000, energy=1000, m_inc=5.0, e_inc=60.0, bp=530,
                  counts={"Commander": 1, "BotFactory": 1})
    pl = split_bp(st.counts, expanding=0, commander="base", bp_override=530)
    check(pl.expand == 0.0, "no mobile builder means an empty expand pool")
    r = cadence_row(st, target="Mex", scale_source="ConTurret", n_scale=0,
                    stop_after=3, pools=pl)
    check(r["targets"] == 0 and r["stopped"] and "expand" in r["stopped"],
          "a Mex cadence with an empty expand pool must stop and say so, got "
          + str(r["stopped"]))
    r2 = cadence_row(st, target="Wind", scale_source="ConTurret", n_scale=0,
                     stop_after=3, pools=pl)
    check(r2["targets"] == 3, "a Wind cadence should run on the base pool")
    check(all(x.get("pool") == "base" for x in r2["segments"]),
          "every Wind segment should draw on base")
    if not ok:
        print("selftest FAILED: build-power pools")
        for m in bad:
            print("  " + m)
    return ok


def selftest(path: str = ED.PARITY_PATH, tol: float = 1e-6) -> bool:
    """Recompute everything from econ_model.json + the engine dumps and compare with parity.json."""
    if not os.path.exists(path):
        print(f"no parity file at {path}; run: python bar-calc/bar_unified.py --write-parity")
        return False
    with open(path, encoding="utf-8") as f:
        want = json.load(f)
    got = compute_parity()
    w, g = {}, {}
    _flatten("", want, w)
    _flatten("", got, g)
    bad = []
    for k in sorted(set(w) | set(g)):
        if k == "generatedBy":
            continue
        a, b = w.get(k, "<missing>"), g.get(k, "<missing>")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
            ok = (math.isinf(a) and math.isinf(b)) or abs(a - b) <= tol * max(1.0, abs(a))
        else:
            ok = a == b
        if not ok:
            bad.append((k, a, b))
    n = len(w)
    for sec in ("unifiedDemo", "barCalcDemo"):
        r = got[sec]["result"]
        print(f"  {sec:13} t={r['time']:.2f}s  M={r['metal']:.1f}  E={r['energy']:.1f}  "
              f"+{r['mInc']:.3f}M/s +{r['eInc']:.1f}E/s  BP={r['bp']:.0f}")
    if bad:
        for k, a, b in bad[:40]:
            print(f"  ✘ {k}: parity {a!r}  now {b!r}")
        print(f"\nselftest FAILED: {len(bad)} of {n} values differ from {os.path.basename(path)} "
              f"(data changed? re-run --write-parity after checking)")
        return False
    if not selftest_time_to_build():
        return False
    if not selftest_pools():
        return False
    if not selftest_goal():
        return False
    print(f"\nselftest OK: {n} values match {os.path.basename(path)}, "
          f"and time_to_build reproduces the simulation")
    return True


# ════════════════════════════════════════════════════════════════════════════
# 10. HARVEST ENGINE DEFS  — refresh the unit stats from a real game
# ════════════════════════════════════════════════════════════════════════════

HARVEST_HELPER = os.path.join(HERE, "harvest_defs.mjs")


def harvest_unit_defs(demo: str = "8v8", engine: Optional[str] = None, out: Optional[str] = None,
                      full: bool = False, timeout_ms: int = 300000, parity: bool = True) -> dict:
    """Pull the stats and properties of every unit, structure and object straight from the game engine.

    Replays a demo headlessly (default: the most recent 8v8 in the BAR demos folder) with gex.lua,
    which reports every unit def at frame 0, and saves them as bar-calc/units_<dateTime>.json
    (dateTime = the game's start time). econ_model.json's `engineDefs` glob picks the newest
    units_*.json and applies it last, so the harvested file becomes the default for bar_unified.py,
    positions/state_api.py and splendid_buildSimulator.js immediately; parity.json is regenerated
    so the three selftests pin the new numbers. Returns the helper's summary dict (out, count, …).
    Node does the demo-side work (sdfz-demo-parser + spring-headless): see harvest_defs.mjs."""
    import subprocess
    args = ["node", HARVEST_HELPER, "--demo", demo, "--timeout", str(int(timeout_ms))]
    if engine:
        args += ["--engine", engine]
    if out:
        args += ["--out", out]
    if full:
        args.append("--full")
    print(f"harvesting engine defs: {' '.join(args[1:])}")
    r = subprocess.run(args, cwd=ED.REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    # the helper prints unicode status marks; a cp1252 console cannot encode them and
    # an UnicodeEncodeError here would throw away a replay that already succeeded
    _enc = (sys.stdout.encoding or "utf-8")
    for ln in (r.stderr or "").splitlines():
        print("  " + ln.encode(_enc, "replace").decode(_enc, "replace"))
    if r.returncode != 0:
        raise RuntimeError(f"harvest_defs.mjs failed (rc {r.returncode})")
    summary = json.loads((r.stdout or "").strip().splitlines()[-1])
    print(f"wrote {summary['count']} defs -> {os.path.relpath(summary['out'], ED.REPO_ROOT)}  "
          f"({summary['demo']}, {summary['game']}, engine {summary['engine']})")
    ED.reload()
    latest = ED.latest_units_file()
    if latest and os.path.abspath(latest) != os.path.abspath(summary["out"]):
        print(f"  note: econ_model.json now resolves the newest units file to {os.path.basename(latest)}, "
              f"not the one just written (a later dateTime exists)")
    if parity:
        # the object tables in this module were built at import; regenerate parity in a fresh process
        r2 = subprocess.run([sys.executable, os.path.abspath(__file__), "--write-parity"], cwd=ED.REPO_ROOT,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        print((r2.stdout or "").rstrip())
        if r2.returncode != 0:
            raise RuntimeError("parity regeneration failed:\n" + (r2.stderr or ""))
    return summary


# ════════════════════════════════════════════════════════════════════════════
# 11. CLI / DEMO
# ════════════════════════════════════════════════════════════════════════════

def _demo() -> None:
    print("=" * 72)
    print("BAR unified calculator - demo")
    print(f"grid calibration: 1 square = {ELMOS_PER_GRID_SQUARE:.1f} elmos "
          f"(commander range {UNIT_PROFILES['commander']['build_range']:.0f} "
          f"= {BUILD_RANGE_IN_GRID_SQUARES} squares)")
    print(f"data: {os.path.relpath(ED.CONFIG_PATH, ED.REPO_ROOT)} + "
          f"{', '.join(s['path'] for s in ED.engine_sources() if s['present'])}")
    print("=" * 72)

    generator_roi_report()

    print("\nStandard opening (walk distances in grid squares, measured off map):")
    env = Environment()
    # The 3 start mexes are ~2 squares out (inside build range → ~0 walk);
    # later structures need real hops.
    env.build_order(DEMO_ORDER)
    env.status()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:]

    def _opt(flag, default=None, cast=float):
        """Value after `flag`. A following token that is itself a flag counts as
        absent, so `--map --game 1` reads as "--map with no value"."""
        if flag in argv:
            i = argv.index(flag)
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                return cast(argv[i + 1])
        return default

    if "--selftest" in argv:
        sys.exit(0 if selftest() else 1)
    elif "--harvest-defs" in argv:
        harvest_unit_defs(demo=_opt("--demo", "8v8", str), engine=_opt("--engine", None, str),
                          out=_opt("--out", None, str), full="--full" in argv,
                          timeout_ms=int(_opt("--timeout", 300000)), parity="--no-parity" not in argv)
    elif "--write-parity" in argv:
        p = write_parity()
        print(f"wrote {os.path.relpath(p, ED.REPO_ROOT)}")
        selftest()
    elif "--games" in argv:
        print_recent_games(int(_opt("--games", 10)), matchup=_opt("--matchup", None, str),
                           player=_opt("--player", None, str))
    elif "--favorite" in argv:
        lab = _opt("--favorite", None, str)
        g = resolve_game(_opt("--game", 1, str), matchup=_opt("--matchup", None, str))
        print(f"saved favorite {lab!r} -> {g.name}  ({os.path.relpath(add_favorite(lab, g), ED.REPO_ROOT)})")
    elif "--extract" in argv:
        extract_game(_opt("--extract", 1, str), player=_opt("--player", None, str),
                     matchup=_opt("--matchup", None, str),
                     team=(int(_opt("--team", -1)) if _opt("--team", None) else None),
                     until_sec=_opt("--until", 900.0), force_replay="--force" in argv)
    elif "--data" in argv:
        for r in list_game_data():
            print(f"  {r['id']:>18}  team {r['team']}  {str(r['played']):>16}  "
                  f"{r['completions']:4} completions  {r['mexes']} mex  {r['map'][:24]}")
    elif "--analyze" in argv:
        d = load_game_data(_opt("--analyze", 1, str) if not str(_opt("--analyze", "1")).isdigit()
                           else int(_opt("--analyze", 1)))
        print(json.dumps(run_analyses(d), indent=1)[:4000])
    elif "--paths" in argv:
        sel = _opt("--paths", None, str)
        names = [x.strip() for x in sel.split(",")] if sel else list(PATHS)
        run_paths(names, horizon=_opt("--until", 300.0), wind=_opt("--wind", None))
    elif "--list-paths" in argv:
        for n, p in PATHS.items():
            print(f"  {n:22} {len(p.steps):3} steps  {p.description}")
        print()
        print(f"  breakpoints: {', '.join(BREAKPOINTS)}")
    elif "--even-time" in argv:
        compare_at_time(_opt("--at", 180.0), wind=_opt("--wind", None),
                        gen_walk_sec=_opt("--place", 0.0))
    elif "--viz" in argv:
        import horizon_viz as _HV
        _depth = [float(x) for x in str(_opt("--depth", "", str)).split(",") if x]
        _HV.viz(game=_opt("--game", 1, str), at=_opt("--at", 30.0),
                out=_opt("--out", None, str), open_browser="--open" in argv,
                target=_opt("--target", "Wind", str),
                bp_source=_opt("--bpsrc", "ConTurret", str),
                energy_source=_opt("--energy", "Solar", str),
                on=_opt("--on", "Mex", str),
                depth=_depth or list(_HV.DEFAULT_DEPTH),
                horizon=_opt("--until", 240.0))
    elif "--installed-games" in argv:
        installed_games(verbose=True)
    elif "--find-demo" in argv:
        find_faction_demo(need=[x for x in str(_opt("--need", ",".join(FACTIONS), str)).split(",") if x],
                          limit=int(_opt("--limit", 200)),
                          refresh="--refresh" in argv)
    elif "--extractor-rate" in argv:
        extractor_rates(units=[x for x in str(_opt("--units", "Mex,legmex,AMex,legmoho", str)).split(",") if x],
                        exchange=_opt("--exchange", ENERGY_PER_METAL))
    elif "--goal" in argv:
        _sj = _opt("--state", None, str)
        if _sj:
            _b0 = json.loads(_sj)
            _st = EcoState(t=float(_b0.get("t", 0.0)),
                           metal=float(_b0.get("metal", 1000)),
                           energy=float(_b0.get("energy", 1000)),
                           m_inc=float(_b0.get("m_inc", 0)),
                           e_inc=float(_b0.get("e_inc", 0)),
                           bp=float(_b0.get("bp", 300)),
                           counts=dict(_b0.get("counts") or {}),
                           m_cap=float(_b0.get("m_cap", max(1000, _b0.get("metal", 1000)))),
                           e_cap=float(_b0.get("e_cap", max(1000, _b0.get("energy", 1000)))),
                           wind=float(_b0.get("wind", DEFAULT_WIND)))
        else:
            _g = _opt("--game", 1, str)
            _d = load_game_data(int(_g) if str(_g).isdigit() else _g)
            _st = state_from_game(_d, _opt("--at", 180.0))
        _pl = None
        if "--pools" in argv:
            _pl = split_bp(_st.counts, expanding=int(_opt("--expanding", 0)),
                           commander=_opt("--commander", "base", str),
                           factory_on="--factory-off" not in argv,
                           assist=_opt("--assist", 0.0),
                           bp_override=_st.bp if _st.counts else None)
        goal_plan(_st, goal=_opt("--goal-unit", "AdvSolar", str),
                  count=int(_opt("--count", 4)),
                  bp_source=_opt("--bpsrc", "ConTurret", str),
                  max_sources=int(_opt("--max-sources", 3)),
                  pools=_pl, assign=_opt("--assign", "base", str))
    elif "--spread" in argv:
        _g = _opt("--game", 1, str)
        _dd = load_game_data(int(_g) if str(_g).isdigit() else _g)
        if "--windows" in argv:
            placement_windows(_dd, step=_opt("--step", 60.0),
                              until_sec=_opt("--until", 420.0),
                              same_place=_opt("--same-place", 150.0),
                              same_time=_opt("--same-time", 30.0))
        else:
            placement_spread(_dd,
                             from_sec=_opt("--from", 0.0),
                             until_sec=_opt("--until", 600.0),
                             same_place=_opt("--same-place", 150.0),
                             same_time=_opt("--same-time", 30.0))

    elif "--concentrate" in argv:
        _stt = None
        if "--game" in argv:
            _g = _opt("--game", 1, str)
            _dd = load_game_data(int(_g) if str(_g).isdigit() else _g)
            _stt = state_from_game(_dd, _opt("--at", 60.0))
        concentration_advantage(unit=_opt("--unit", "Wind", str),
                                workers=int(_opt("--workers", 2)),
                                bp_each=_opt("--bp", None),
                                wind=_opt("--wind", None),
                                segments=int(_opt("--segments", 12)),
                                state=_stt,
                                builder=_opt("--builder", "BotWorker", str))
    elif "--budget" in argv:
        mex_budget(map_query=_opt("--map", "All That Glitters", str),
                   team=int(_opt("--team", 0)),
                   count=(int(_opt("--mex", 0)) or None),
                   position=_opt("--position", None, str),
                   standing=int(_opt("--standing", 0)), verbose=True)
    elif "--phases" in argv:
        _g = _opt("--game", 1, str)
        _d = load_game_data(int(_g) if str(_g).isdigit() else _g)
        _st = state_from_game(_d, _opt("--at", 60.0))
        _b = mex_budget(map_query=_opt("--map", (_d.get("game") or {}).get("map")
                                       or "All That Glitters", str),
                        team=int(_opt("--team", (_d.get("player") or {}).get("team_id") or 0)),
                        count=(int(_opt("--mex", 0)) or None),
                        position=_opt("--position", "front", str),
                        standing=int(_opt("--standing", _st.counts.get("Mex", 0))))
        phase_markers(_st, _b, target=_opt("--target-unit", "Wind", str),
                      on=_opt("--on", "Mex", str),
                      workers=int(_opt("--workers", 1)), verbose=True)
    elif "--cadence" in argv:
        _g = _opt("--game", 1, str)
        _d = load_game_data(int(_g) if str(_g).isdigit() else _g)
        _st = state_from_game(_d, _opt("--at", 60.0))
        _b = mex_budget(map_query=_opt("--map", (_d.get("game") or {}).get("map")
                                       or "All That Glitters", str),
                        team=int(_opt("--team", (_d.get("player") or {}).get("team_id") or 0)),
                        count=(int(_opt("--mex", 0)) or None),
                        position=_opt("--position", "front", str),
                        standing=int(_opt("--standing", _st.counts.get("Mex", 0))))
        _h = _opt("--until", None)
        _pl = None
        if "--pools" in argv:
            _pl = split_bp(_st.counts, expanding=int(_opt("--expanding", 0)),
                           commander=_opt("--commander", "base", str),
                           factory_on="--factory-off" not in argv,
                           assist=_opt("--assist", 0.0),
                           bp_override=_st.bp if _st.counts else None)
        _sh = _opt("--share", None)
        if _sh is None and "--measured" in argv:
            _sh = implied_share(_d, _opt("--target-unit", "Wind", str)).get("share") or 1.0
        cadence_table(_st, target=_opt("--target-unit", "Wind", str),
                      scale_source=_opt("--bpsrc", "ConTurret", str),
                      rows=int(_opt("--rows", 3)),
                      items=(None if _h else int(_opt("--items", 10))),
                      horizon=_h, budget=_b,
                      width=int(_opt("--width", 104)),
                      workers=int(_opt("--workers", 1)),
                      share=(1.0 if _sh is None else float(_sh)),
                      pools=_pl, assign=_opt("--assign", "base", str))
    elif "--cadence-check" in argv:
        validate_cadence_vs_replay(game=_opt("--game", 1, str),
                                   unit=_opt("--unit", "Wind", str),
                                   position=_opt("--position", "front", str))
    elif "--share" in argv:
        _g = _opt("--game", 1, str)
        implied_share(load_game_data(int(_g) if str(_g).isdigit() else _g),
                      unit=_opt("--unit", "Wind", str), verbose=True)
    elif "--path" in argv:
        _g = _opt("--game", 1, str)
        _d = load_game_data(int(_g) if str(_g).isdigit() else _g)
        _st = state_from_game(_d, _opt("--at", 60.0))
        _b = mex_budget(map_query=_opt("--map", (_d.get("game") or {}).get("map")
                                       or "All That Glitters", str),
                        team=int(_opt("--team", (_d.get("player") or {}).get("team_id") or 0)),
                        count=(int(_opt("--mex", 0)) or None),
                        position=_opt("--position", "front", str),
                        standing=int(_opt("--standing", _st.counts.get("Mex", 0))))
        _pl = None
        if "--pools" in argv:
            _pl = split_bp(_st.counts, expanding=int(_opt("--expanding", 0)),
                           commander=_opt("--commander", "base", str),
                           factory_on="--factory-off" not in argv,
                           assist=_opt("--assist", 0.0),
                           bp_override=_st.bp if _st.counts else None)
        path_search(_st, _b, target=_opt("--target-unit", "Wind", str),
                    bp_source=_opt("--bpsrc", "ConTurret", str),
                    on=_opt("--on", "Mex", str),
                    horizon=_opt("--until", 600.0),
                    objective_name=_opt("--objective", "hold_metal_bound", str),
                    workers=int(_opt("--workers", 1)),
                    pools=_pl, assign=_opt("--assign", "base", str))
    elif "--target" in argv:
        _g = _opt("--game", 1, str)
        _d = load_game_data(int(_g) if str(_g).isdigit() else _g)
        if "--timeline" in argv:
            target_timeline(_d, until_sec=_opt("--until", 300.0))
        else:
            target_advisor(state_from_game(_d, _opt("--at", 60.0)))
    elif "--idle" in argv:
        _g = _opt("--game", None, str)
        if _g:
            idle_audit(load_game_data(int(_g) if str(_g).isdigit() else _g),
                       until_sec=_opt("--until", 480.0), on=_opt("--on", "Mex", str))
        else:
            idle_audit_many(until_sec=_opt("--until", 480.0), on=_opt("--on", "Mex", str))
    elif "--gaps" in argv:
        build_gaps(unit=_opt("--unit", "Wind", str), bp=_opt("--bp", 300.0),
                   max_move=_opt("--max-move", 120.0))
    elif "--variants" in argv:
        _pair = [int(x) for x in str(_opt("--variants", "3,8", str)).split(",") if x]
        _sw = solar_sweep(counts=sorted(set(list(range(0, 9)) + _pair)),
                          wind=_opt("--wind", 11.9),
                          workers=int(_opt("--workers", 2)), verbose=False)
        compare_variants(_sw, _pair[0], _pair[1], at=_opt("--at", None))
    elif "--solar-sweep" in argv:
        if "--planes" in argv:
            solar_sweep_wind_planes(winds=[float(x) for x in
                                           str(_opt("--planes", "4,8,11.9,16", str)).split(",") if x],
                                    target_mex=int(_opt("--mex", 7)),
                                    workers=int(_opt("--workers", 2)))
        else:
            solar_sweep(counts=[int(x) for x in str(_opt("--counts", "0,1,2,3,4,5,6,7,8", str)).split(",") if x],
                        target_mex=int(_opt("--mex", 7)), wind=_opt("--wind", 11.9),
                        workers=int(_opt("--workers", 2)),
                        baseline=int(_opt("--baseline", 4)),
                        compare_at=_opt("--at", None),
                        filler=_opt("--filler", "Wind", str))
    elif "--ledger" in argv:
        _snaps = [float(x) for x in str(_opt("--snap", "", str)).replace(";", ",").split(",") if x]
        _g = _opt("--ledger", 1, str)
        _d = load_game_data(int(_g) if str(_g).isdigit() else _g)
        print_build_ledger(_d, until_sec=_opt("--until", 480.0), snapshots=_snaps or None,
                           include=[x for x in str(_opt("--only", "", str)).split(",") if x] or None)
    elif "--horizon" in argv:
        _d = load_game_data(_opt("--game", 1, str) if not str(_opt("--game", "1")).isdigit()
                            else int(_opt("--game", 1)))
        _st = state_from_game(_d, _opt("--at", 30.0))
        _w = _opt("--wind", None)
        _winds = [float(x) for x in str(_opt("--depth", "", str)).split(",") if x] or \
                 ([_w] if _w else [11.9])
        for _wi in _winds:
            build_horizon(_st, target=_opt("--target", "Wind", str),
                          bp_source=_opt("--bpsrc", "ConTurret", str), wind=_wi,
                          n_rows=int(_opt("--rows", 4)), horizon=_opt("--until", 240.0))
            print()
    elif "--map-scaling" in argv:
        _d = load_game_data(_opt("--game", 1, str) if not str(_opt("--game", "1")).isdigit()
                            else int(_opt("--game", 1)))
        _st = state_from_game(_d, _opt("--at", 60.0))
        scaling_map(_st, energy_source=_opt("--energy", "Solar", str),
                    bp_source=_opt("--bpsrc", "BotWorker", str),
                    on=_opt("--on", "Mex", str), color="--no-color" not in argv)
    elif "--state" in argv:
        _d = load_game_data(_opt("--game", 1, str) if not str(_opt("--game", "1")).isdigit()
                            else int(_opt("--game", 1)))
        _st = state_from_game(_d, _opt("--at", 60.0))
        scaling_report(_st)
    elif "--scaling" in argv:
        _d = load_game_data(_opt("--game", 1, str) if not str(_opt("--game", "1")).isdigit()
                            else int(_opt("--game", 1)))
        _st = state_from_game(_d, _opt("--at", 60.0))
        scaling_grid(_st, _opt("--scaling", "Solar", str))
    elif "--tables" in argv:
        balance_tables(bp=_opt("--bp", 300.0), a=_opt("--a", "Solar", str),
                       b=_opt("--b", "Wind", str), n_a=int(_opt("--na", 8)),
                       n_b=int(_opt("--nb", 12)))
    elif "--balance" in argv:
        energy_balance_table(bp=_opt("--bp", 300.0), a=_opt("--a", "Solar", str),
                             b=_opt("--b", "Wind", str),
                             m_bank=_opt("--bank", None), m_inc=_opt("--minc", None),
                             e_bank=_opt("--ebank", None), e_inc=_opt("--einc", None))
    elif "--rates" in argv:
        rate_report(wind=_opt("--wind", None))
    elif "--openings" in argv:
        wv = _opt("--wind", None)
        tgt = int(_opt("--mex", 7))
        hz = _opt("--until", 300.0)
        if "--sweep" in argv:
            sol = simulate_opening("Solar", wind=10, target_mex=tgt, horizon=hz)
            se = OBJECTS["Solar"].metal_cost + OBJECTS["Solar"].energy_cost / ENERGY_PER_METAL
            we = OBJECTS["Wind"].metal_cost + OBJECTS["Wind"].energy_cost / ENERGY_PER_METAL
            print(f"theory: solar {se:.1f} metal per {OBJECTS['Solar'].energy_income:g} E/s "
                  f"= {se / OBJECTS['Solar'].energy_income:.2f} m per E/s; wind {we:.1f}/W. "
                  f"wind is cheaper above {we / (se / OBJECTS['Solar'].energy_income):.2f} E/s")
            print(f"practice: solar reaches {tgt} mex at {sol.t_target}s")
            print(f"  {'wind':>6} {'{} mex'.format(tgt):>8} {'vs solar':>9} {'turbines':>9}")
            for w in (4, 6, 8, 10, 12, 14, 16, 18, 20):
                r = simulate_opening("Wind", wind=w, target_mex=tgt, horizon=hz)
                t = r.t_target if r.t_target else float("nan")
                print(f"  {w:6.1f} {t:8.1f} {t - (sol.t_target or 0):+9.1f} {r.generators:9}")
        else:
            compare_openings(wind=wv, target_mex=tgt)
    elif "--reclaim-runs" in argv:
        print_reclaim_runs(_opt("--reclaim-runs", GEX_ACTIONS_DEFAULT, str),
                           tol_frac=_opt("--tol", 0.04), tol_abs=_opt("--tol-abs", 4.0),
                           min_metal=_opt("--min-metal", 0.5))
    elif "--metal-sources" in argv or "--reclaim" in argv:
        print_metal_sources(_opt("--metal-sources", GEX_ACTIONS_DEFAULT, str),
                            int(_opt("--top", 14)))
    elif "--map" in argv:
        q = _opt("--map", None, str) or (_opt("--game", None, str) and None)
        m = map_for_game(_opt("--game", "1", str)) if not q else read_map(q, refresh="--refresh" in argv)
        print("=" * 70)
        print(f"  {m.name}   v{m.version} by {m.author}   [{m.source_archive}]")
        print("=" * 70)
        print(f"  world      : {m.world_width} x {m.world_height} elmos")
        print(f"  wind       : {m.wind_min:g} - {m.wind_max:g} E/s   "
              f"→ a turbine averages {m.expected_wind():.2f} E/s  ((min+max)/2 would say {flat_wind_income(*m.wind_range):.2f})")
        print(f"  maxMetal {m.max_metal:g}   extractorRadius {m.extractor_radius:g}")
        print(f"  mex spots  : {len(m.mex_spots)}   geos {len(m.geo_spots)}   starts {len(m.start_positions)}"
              f"   all held = {m.total_metal_per_s():.1f} M/s")
        fc = m.feature_counts()
        print(f"  features   : {len(m.features)}  " + (", ".join(f"{k}x{v}" for k, v in list(fc.items())[:6]) or "none")
              + ("" if m.rocks() else "   (no rocks in the SMF — see MapInfo.rocks)"))
        team = int(_opt("--team", 0))
        if m.start_position(team):
            x, z = m.start_position(team)
            print()
            print(f"  nearest mex spots to team {team} ({x:.0f},{z:.0f}) — walk is to build range:")
            print(f"    {'#':>4} {'x':>7} {'z':>7} {'elmos':>8} {'walk':>7}    M/s")
            for r in m.spots_from(x, z, "commander", int(_opt("--spots", 10))):
                print(f"    {r['id']:>4} {r['x']:7.0f} {r['z']:7.0f} {r['distance']:8.0f} {r['walk_sec']:6.1f}s  {r['metal_per_s']:.3f}")
    elif "--wind-validate" in argv:
        refs = [_opt("--game", None, str)] if _opt("--game", None, str) else ["1", "2", "3"]
        sys.exit(0 if validate_wind_model(refs)["ok"] else 1)
    elif "--wind" in argv:
        ref = _opt("--game", None, str)
        if ref:
            rw = RecordedWind.from_game(ref)
            lo, hi = rw.map_range()
            win = _opt("--until", 900.0)
            print(f"{rw.source}  {rw.map_name}   {len(rw.samples)} wind samples, {rw.duration_sec() / 60:.1f} min")
            print(f"  map range [{lo:g}, {hi:g}] E/s (observed {rw.observed_range()[0]:.2f}–{rw.observed_range()[1]:.2f})")
            print(f"  turbine average  first {win / 60:g} min {rw.average(0, min(win, rw.duration_sec())):.2f} E/s"
                  f" · whole game {rw.average():.2f} E/s"
                  f" · table {wind_income(lo, hi):.2f} · (min+max)/2 {flat_wind_income(lo, hi):.2f}")
            thr = _opt("--drought", 5.0)
            dr = [d for d in rw.droughts(thr, min(win, rw.duration_sec())) if d[1] - d[0] >= 5]
            print(f"  below {thr:g} E/s in the first {win / 60:.0f} min: "
                  + (", ".join(f"{a:.0f}–{b:.0f}s" for a, b in dr) if dr else "never"))
            print(f"  {'t':>6} {'E/s':>6}   window")
            for t in range(0, int(min(win, rw.duration_sec())) + 1, 30):
                f = rw.forecast(t)
                print(f"  {t:6d} {f['now']:6.2f}   → {f['target']:5.2f} in {f['seconds_left']:4.1f}s"
                      f" ({'rising' if f['rising'] else 'falling'})")
        else:
            lo, hi = _opt("--min", 0.0), _opt("--max", 16.0)
            print(f"Engine wind model — map [{lo:g}, {hi:g}] E/s, {WIND_UPDATE_SEC:g}s windows")
            print(f"  expected per turbine : {wind_income(lo, hi):.2f} E/s")
            print(f"  (min+max)/2 would say: {flat_wind_income(lo, hi):.2f} E/s")
            m = WindModel(lo, hi, seed=int(_opt("--seed", 0)))
            print(f"  {'t':>6} {'E/s':>6}")
            for t in range(0, int(_opt("--until", 300.0)) + 1, 15):
                print(f"  {t:6d} {m.at(t):6.2f}")
    elif "--objects" in argv:
        print(ED._table_objects())
    elif "--roi" in argv:
        generator_roi_report(_opt("--bp", DEFAULT_BUILDER_BP), _opt("--wind", None))
    else:
        _demo()

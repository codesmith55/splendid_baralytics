"""
BAR (Beyond All Reason) distance & worker walk-time model.
=========================================================

Turns *map distances* into *worker walk times* so the eco simulator can stop
using hand-guessed `walk_delay` constants and instead derive them from where
things actually are on the map.

------------------------------------------------------------------------------
Ground-truth engine constants
------------------------------------------------------------------------------
Pulled directly from the BAR game unit definitions (units/*.lua). All distances
are in *elmos* (the Spring engine world unit); speeds are elmos/second.

    Unit                       build range   move speed
    Commander      (armcom)        145          37.5
    Construction Bot (armck)       130          36.0
    Construction Turret (armnanotc) 400         0  (static)

`build range` matters because a builder does NOT need to reach the build site —
it only needs to get *within build range* of it, then it stops and builds. So
the distance actually walked is `max(0, gap - build_range)`.

------------------------------------------------------------------------------
Grid calibration  (THE one tunable assumption)
------------------------------------------------------------------------------
The bright green start-position grid squares are guidelines that show "true
distance" in game. We calibrate the square size against a known engine value:

    Observed in-game: the Commander's build-range circle is "just larger than
    3 grid squares".

Reading "build range" as the circle's RADIUS (= 145 elmos):

        ELMOS_PER_GRID_SQUARE = 145 / 3  ~= 48.3 elmos

If you instead meant the build-range *diameter* spans ~3 squares, set
`BUILD_RANGE_IN_GRID_SQUARES = 1.5` and the square becomes ~96.7 elmos — every
walk time below then doubles. This is the single number to verify against the
map; everything else is engine ground truth.

Usage:
    from bar_distance import walk_time_squares, walk_time, can_reach
    walk_time_squares(2.0, "commander")   # seconds to walk to a target 2 squares away
    walk_time(300, "con_bot")             # seconds to walk to a target 300 elmos away
"""

from __future__ import annotations

# ── Engine ground truth (units/*.lua) ───────────────────────────────────────
GAME_FPS = 30  # sim frames/second; speeds below are already elmos/second

UNIT_PROFILES = {
    "commander":  {"build_range": 145.0, "speed": 37.5},
    "con_bot":    {"build_range": 130.0, "speed": 36.0},
    "con_turret": {"build_range": 400.0, "speed": 0.0},   # static
}

# ── Grid calibration ────────────────────────────────────────────────────────
COMMANDER_BUILD_RANGE = UNIT_PROFILES["commander"]["build_range"]  # 145 elmos
BUILD_RANGE_IN_GRID_SQUARES = 3.0          # "just larger than 3 squares" (radius)
ELMOS_PER_GRID_SQUARE = COMMANDER_BUILD_RANGE / BUILD_RANGE_IN_GRID_SQUARES  # ~48.3

# Typical observed distances at a standard 3-mex start (see map screenshots).
# The two side mexes sit ~1 build-range out from the commander; expressed in
# grid squares for easy re-measurement off any screenshot.
MEX_DISTANCE_SQUARES = 2.0


# ── Unit resolution ─────────────────────────────────────────────────────────
def resolve_unit(unit: str) -> str:
    """Map a free-text builder name (e.g. 'Armada Commander', 'Construction
    Bot', 'con_turret') to a profile key. Defaults to 'con_bot'."""
    u = unit.strip().lower()
    if "commander" in u or u == "commander":
        return "commander"
    if "turret" in u or "nano" in u or u == "con_turret":
        return "con_turret"
    return "con_bot"


# ── Conversions ─────────────────────────────────────────────────────────────
def squares_to_elmos(squares: float) -> float:
    return squares * ELMOS_PER_GRID_SQUARE


def elmos_to_squares(elmos: float) -> float:
    return elmos / ELMOS_PER_GRID_SQUARE


def can_reach(gap_elmos: float, unit: str = "commander") -> bool:
    """True if a target `gap_elmos` away is already inside build range (no walk
    needed)."""
    return gap_elmos <= UNIT_PROFILES[resolve_unit(unit)]["build_range"]


def walk_time(gap_elmos: float, unit: str = "con_bot",
              account_build_range: bool = True) -> float:
    """Seconds the builder spends walking before it can start building a target
    `gap_elmos` away (centre-to-centre).

    Because the builder stops once the target is within build range, the walked
    distance is `max(0, gap - build_range)`. A static builder (con turret,
    speed 0) returns 0 if already in range, else +inf (can never reach)."""
    p = UNIT_PROFILES[resolve_unit(unit)]
    gap = max(0.0, gap_elmos - p["build_range"]) if account_build_range else gap_elmos
    if gap <= 0:
        return 0.0
    if p["speed"] <= 0:
        return float("inf")
    return gap / p["speed"]


def walk_time_squares(gap_squares: float, unit: str = "con_bot",
                      account_build_range: bool = True) -> float:
    """Same as walk_time() but the distance is given in grid squares measured
    off the map."""
    return walk_time(squares_to_elmos(gap_squares), unit, account_build_range)


def mex_walk_time(unit: str = "commander", n_mex: int = 1,
                  distance_squares: float = MEX_DISTANCE_SQUARES) -> float:
    """Total walk time to claim `n_mex` nearby metal spots, one after another,
    each `distance_squares` from the previous build position. The first mex is
    often in range already; subsequent ones each cost one hop."""
    per_hop = walk_time_squares(distance_squares, unit)
    return per_hop * max(0, n_mex)


# ── Self-test / quick reference table ───────────────────────────────────────
if __name__ == "__main__":
    print("BAR distance model")
    print(f"  calibration: 1 grid square = {ELMOS_PER_GRID_SQUARE:.1f} elmos "
          f"(commander build range {COMMANDER_BUILD_RANGE:.0f} = "
          f"{BUILD_RANGE_IN_GRID_SQUARES} squares)\n")
    print(f"  {'distance':>10} | {'commander':>10} | {'con_bot':>10}")
    print(f"  {'(squares)':>10} | {'walk (s)':>10} | {'walk (s)':>10}")
    print("  " + "-" * 36)
    for sq in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0):
        c = walk_time_squares(sq, "commander")
        b = walk_time_squares(sq, "con_bot")
        print(f"  {sq:>10.1f} | {c:>10.1f} | {b:>10.1f}")
    print(f"\n  commander claiming 2 side mexes (~{MEX_DISTANCE_SQUARES} sq each): "
          f"{mex_walk_time('commander', n_mex=2):.1f}s")

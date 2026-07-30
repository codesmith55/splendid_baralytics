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

The originals remain in their subfolders for reference; this file is the
intended single entry point going forward. See STATUS.md.

Run `python bar_unified.py` for a demo build order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ════════════════════════════════════════════════════════════════════════════
# 1. CONSTANTS
# ════════════════════════════════════════════════════════════════════════════

ENERGY_PER_METAL = 70          # T1 energy-converter exchange rate (eco_calculator)
DEFAULT_BUILDER_BP = 300       # T1 constructor / commander build power

# ── Distance & movement (engine ground truth from units/*.lua) ──────────────
GAME_FPS = 30
UNIT_PROFILES = {
    # build_range and speed in elmos / elmos-per-second
    "commander":  {"build_range": 145.0, "speed": 37.5, "bp": 300},
    "con_bot":    {"build_range": 130.0, "speed": 36.0, "bp": 80},
    "con_turret": {"build_range": 400.0, "speed": 0.0,  "bp": 200},
}

# Grid calibration: the commander's build-range circle is ~3 start-grid squares
# (radius). build range 145 elmos / 3 squares ≈ 48.3 elmos per square.
# Flip to 1.5 if "3 squares" meant the diameter (then 1 square ≈ 96.7 elmos).
BUILD_RANGE_IN_GRID_SQUARES = 3.0
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
# 3. WIND INCOME   (was wind_simulator.py)
# ════════════════════════════════════════════════════════════════════════════

def wind_income(min_wind: float, max_wind: float) -> float:
    """Average E/s of a wind turbine on a map with the given wind range.
    BAR turbines output linearly between the map's min and max wind."""
    return (min_wind + max_wind) / 2.0


# ════════════════════════════════════════════════════════════════════════════
# 4. OBJECT DATA  (merged from bar_calc.object_types + eco_calculator outputs)
#    Costs: metal, energy, buildpower(=buildtime cost). Income is per-second.
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class ObjectType:
    name: str
    metal_cost: float = 0.0
    energy_cost: float = 0.0
    bp_cost: float = 0.0          # build-time cost (BP-seconds)
    metal_income: float = 0.0
    energy_income: float = 0.0
    bp_income: float = 0.0        # build power this unit contributes (builders)
    is_builder: bool = False

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


OBJECTS: Dict[str, ObjectType] = {
    "Wind":       ObjectType("Wind", 40, 175, 1600, energy_income=10),
    "Solar":      ObjectType("Solar", 155, 0, 2600, energy_income=20),
    "AdvSolar":   ObjectType("AdvSolar", 370, 0, 8200, energy_income=75),
    "Mex":        ObjectType("Mex", 50, 500, 1800, metal_income=1.8, energy_income=-3),
    "AMex":       ObjectType("AMex", 620, 7700, 14900, metal_income=7.3),
    "EConverter": ObjectType("EConverter", 1, 1150, 2600),
    "EStorage":   ObjectType("EStorage", 160, 0, 1800),
    "Commander":  ObjectType("Commander", 0, 0, 0, metal_income=2, energy_income=25,
                             bp_income=300, is_builder=True),
    "BotFactory": ObjectType("BotFactory", 620, 1200, 6500, bp_income=100, is_builder=True),
    "BotWorker":  ObjectType("BotWorker", 110, 1600, 3450, bp_income=80, is_builder=True),
}


# ════════════════════════════════════════════════════════════════════════════
# 5. ECONOMY / BUILD-ORDER SIMULATOR
#    Based on bar_calc.Environment, enhanced with calibrated walk time and the
#    per-resource stall reporting from eco_simulator.
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class Environment:
    time: float = 0.0
    metal: float = 1000.0
    energy: float = 1000.0
    max_metal: float = 1000.0
    max_energy: float = 1000.0
    metal_per_second: float = 2.0
    energy_per_second: float = 25.0
    builders: List[str] = field(default_factory=lambda: ["Commander"])
    buildings: List[str] = field(default_factory=list)
    history: List[Tuple[str, float]] = field(default_factory=list)
    n_converters: int = 0
    verbose: bool = True

    # ---- build power ----
    def total_bp(self) -> float:
        return sum(OBJECTS[b].bp_income for b in self.builders if b in OBJECTS)

    # ---- timing ----
    def build_times(self, name: str, builder_bp: Optional[float] = None) -> dict:
        """Time gated by build power, energy income, and metal income — the
        actual time is the max of the three (you stall on the slowest)."""
        obj = OBJECTS[name]
        bp = builder_bp if builder_bp else self.total_bp()
        bp_time = obj.bp_cost / bp if bp else float("inf")
        e_time = 0.0 if obj.energy_cost <= self.energy else \
            (obj.energy_cost - self.energy) / max(self.energy_per_second, 1e-9)
        m_time = 0.0 if obj.metal_cost <= self.metal else \
            (obj.metal_cost - self.metal) / max(self.metal_per_second, 1e-9)
        return {"bp": bp_time, "energy": e_time, "metal": m_time,
                "total": max(bp_time, e_time, m_time)}

    # ---- one build, optionally preceded by a walk ----
    def build(self, name: str, walk_squares: float = 0.0,
              walker: str = "commander") -> bool:
        if name not in OBJECTS:
            print(f"  ! unknown object: {name}")
            return False

        # Walk to the site first (calibrated from the map grid).
        wt = walk_time_squares(walk_squares, walker) if walk_squares else 0.0
        if wt > 0:
            self.advance(wt)

        bt = self.build_times(name)
        if bt["energy"] > bt["bp"]:
            print(f"  ! energy stall building {name}")
        if bt["metal"] > bt["bp"]:
            print(f"  ! metal stall building {name}")

        obj = OBJECTS[name]
        self.metal -= obj.metal_cost
        self.advance(bt["total"], eps=obj.energy_cost / max(bt["total"], 1e-9))
        if name == "EConverter":
            self.n_converters += 1

        (self.builders if obj.is_builder else self.buildings).append(name)
        self.history.append((name, self.time))
        self.metal_per_second += obj.metal_income
        self.energy_per_second += obj.energy_income
        if self.verbose:
            walk_note = f" (+{wt:.1f}s walk {walk_squares}sq)" if wt else ""
            print(f"  {self.time:6.1f}s  built {name:<11}{walk_note}  "
                  f"M={self.metal:6.0f} E={self.energy:6.0f}  "
                  f"+{self.metal_per_second:.1f}M/s +{self.energy_per_second:.0f}E/s")
        return True

    # ---- advance the clock, applying income, caps, and converters ----
    def advance(self, dt: float, eps: float = 0.0, conv_floor: float = 0.5) -> None:
        if dt <= 0:
            return
        self.metal = min(self.metal + self.metal_per_second * dt, self.max_metal)
        self.energy += (self.energy_per_second - eps) * dt
        # Energy converters turn surplus energy above conv_floor*cap into metal.
        excess = self.energy - conv_floor * self.max_energy
        if excess > 0 and self.n_converters:
            converted = min(self.n_converters * dt, math.floor(excess / ENERGY_PER_METAL))
            self.metal += converted
            self.energy -= converted * ENERGY_PER_METAL
        self.energy = min(self.energy, self.max_energy)
        self.time += dt

    def build_order(self, order: List) -> "Environment":
        """Run a build order. Each entry is either 'Name' or ('Name', walk_sq)."""
        for entry in order:
            name, walk = entry if isinstance(entry, tuple) else (entry, 0.0)
            if not self.build(name, walk_squares=walk):
                break
        return self

    def status(self) -> None:
        print(f"\n  t={self.time:.1f}s  M={self.metal:.0f}/{self.max_metal:.0f} "
              f"E={self.energy:.0f}/{self.max_energy:.0f}  "
              f"income +{self.metal_per_second:.1f}M/s +{self.energy_per_second:.0f}E/s  "
              f"BP={self.total_bp():.0f}")
        print(f"  builders: {', '.join(self.builders)}")
        print(f"  buildings: {', '.join(self.buildings) or 'none'}")


# ════════════════════════════════════════════════════════════════════════════
# 6. ROI REPORT  (was eco_calculator.main)
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
# 7. DEMO
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 72)
    print("BAR unified calculator - demo")
    print(f"grid calibration: 1 square = {ELMOS_PER_GRID_SQUARE:.1f} elmos "
          f"(commander range {UNIT_PROFILES['commander']['build_range']:.0f} "
          f"= {BUILD_RANGE_IN_GRID_SQUARES} squares)")
    print("=" * 72)

    generator_roi_report()

    print("\nStandard opening (walk distances in grid squares, measured off map):")
    env = Environment()
    # The 3 start mexes are ~2 squares out (inside build range → ~0 walk);
    # later structures need real hops.
    env.build_order([
        ("Mex", 2.0), ("Mex", 2.0), ("Solar", 1.0),
        ("Mex", 2.0), ("Solar", 1.0), ("BotFactory", 1.5),
        ("Mex", 4.0), ("Mex", 4.0),
    ])
    env.status()

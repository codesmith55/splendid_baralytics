"""
BAR Eco Planner — build-pattern intent → forward projection
===========================================================

A high-level front end over ``eco_simulator.BuildPowerEngine``. You describe a
*plan* in the language of a BAR opening —

    "Start here, scale energy via solar→wind up to targets, scale build power
     via workers / con-turrets up to targets, take N mex at this walk pattern,
     com-explode yes/no"

— and the planner compiles it into the engine's low-level build queue, runs the
tick simulation, and reports the forward projection: when each target is hit,
final income, and where it stalls.

Nothing here re-implements game physics. The engine (`eco_simulator.py`) owns
per-builder build power, passive income, resource stalls, and walk delays. This
module is the translator + reporter on top.

------------------------------------------------------------------------------
The BuildPlan fields
------------------------------------------------------------------------------
Starting situation:
    start_metal, start_energy   — resources in the bank at t0
    m_cap, e_cap                — storage caps (raise these as you build storage)
    start_time                  — game clock at t0 (e.g. 3s after com plops)
    start_assets                — eco already on the map, e.g. {"mex": 1}
    has_commander               — commander present as a 300-BP builder + income

Scaling choices:
    energy_source       — "solar" | "wind": what the eco scales energy on
    build_power_source  — "worker" | "con_turret": what the eco scales BP on

Mex:
    mex_count           — how many mex to take
    mex_walk_seconds    — EXPLICIT per-mex walk delay list (seconds), one entry
                          per mex, e.g. [0, 4, 8, 15, 22]. ***These are
                          replay-calibrated placeholders — confirm against real
                          replays before trusting absolute timings.*** Missing
                          entries default to the last given value (or 0).

Build-pattern targets (the "upto5 solar, into wind upto N, workers upto N,
con turrets upto N" phrasing):
    solar_target        — build solar up to this many (before switching to wind)
    wind_target         — then build wind up to this many
    worker_target       — build T1 workers up to this many (a lab is auto-added)
    con_turret_target   — build construction turrets up to this many

Commander explode (full tradeoff model):
    commander_explode        — if True, at explode_time the com wreck's reclaim
                               metal is injected AND the commander is removed
                               (loses its 300 BP + 2M/30E passive income).
    commander_explode_time   — game-clock seconds to trigger it
    commander_wreck_metal    — reclaim yielded by the wreck (~ a large chunk;
                               tune to the unit + resurrect/reclaim rules)

Sim:
    target_time         — how many game seconds to simulate

------------------------------------------------------------------------------
Usage
------------------------------------------------------------------------------
    from bar_analytics.eco_planner import BuildPlan, plan_and_simulate

    plan = BuildPlan(
        start_metal=1000, start_energy=1000, start_time=3,
        energy_source="solar", build_power_source="worker",
        mex_count=4, mex_walk_seconds=[0, 4, 9, 16],
        solar_target=5, wind_target=12, worker_target=3, con_turret_target=2,
        commander_explode=False, target_time=180,
    )
    result = plan_and_simulate(plan)
    result.print_report()

CLI:
    python bar_analytics/eco_planner.py                 # runs the demo plan
    python bar_analytics/eco_planner.py --ledger        # + full tick ledger
"""

# NOTE: intentionally NOT using `from __future__ import annotations`. The
# capabilities auto-discovery imports this module via exec_module without
# registering it in sys.modules, and stringized annotations + @dataclass then
# fail to resolve. All annotations here evaluate fine at definition time.

import argparse
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from eco_simulator import (
    Builder,
    BuildPowerEngine,
    EngineState,
    GAME_RULES,
    make_initial_state,
)

# Map the planner's build-power vocabulary onto engine item keys.
BP_SOURCE_KEY = {"worker": "t1_worker", "con_turret": "con_turret"}
ENERGY_SOURCE_KEYS = ("solar", "wind")


@dataclass
class BuildPlan:
    # ---- starting situation ------------------------------------------------
    start_metal: float = 1000.0
    start_energy: float = 1000.0
    m_cap: float = 1300.0
    e_cap: float = 1450.0
    start_time: float = 3.0
    start_assets: Dict[str, int] = field(default_factory=dict)
    has_commander: bool = True

    # ---- scaling choices ---------------------------------------------------
    energy_source: str = "solar"          # "solar" | "wind"
    build_power_source: str = "worker"    # "worker" | "con_turret"

    # ---- mex ---------------------------------------------------------------
    mex_count: int = 4
    mex_walk_seconds: List[float] = field(default_factory=list)  # per-mex walk delay

    # ---- build-pattern targets --------------------------------------------
    solar_target: int = 5
    wind_target: int = 0
    worker_target: int = 2
    con_turret_target: int = 0

    # ---- commander explode (full tradeoff) --------------------------------
    commander_explode: bool = False
    commander_explode_time: float = 300.0
    commander_wreck_metal: float = 1200.0

    # ---- sim ---------------------------------------------------------------
    target_time: float = 180.0

    def validate(self) -> List[str]:
        """Return a list of human-readable problems (empty == OK)."""
        problems: List[str] = []
        if self.energy_source not in ENERGY_SOURCE_KEYS:
            problems.append(f"energy_source must be one of {ENERGY_SOURCE_KEYS}")
        if self.build_power_source not in BP_SOURCE_KEY:
            problems.append(
                f"build_power_source must be one of {tuple(BP_SOURCE_KEY)}")
        if self.mex_count < 0:
            problems.append("mex_count cannot be negative")
        if self.commander_explode and not self.has_commander:
            problems.append("commander_explode set but has_commander is False")
        return problems


# ──────────────────────────────────────────────────────────────────────────
# Compilation: BuildPlan → engine queue + events
# ──────────────────────────────────────────────────────────────────────────
def _walk_delay_for(plan: BuildPlan, index: int) -> float:
    """Walk delay (seconds) for the ``index``-th mex.

    Uses the explicit per-mex list; if the list is shorter than mex_count the
    last supplied value is reused (0 if the list is empty).
    """
    if not plan.mex_walk_seconds:
        return 0.0
    if index < len(plan.mex_walk_seconds):
        return float(plan.mex_walk_seconds[index])
    return float(plan.mex_walk_seconds[-1])


def compile_plan(plan: BuildPlan) -> Tuple[
        List[Tuple[str, str]], List[Tuple[float, Callable[[EngineState], None]]]]:
    """Translate a BuildPlan into ``(queue, events)`` for BuildPowerEngine.

    Queue ordering encodes the build pattern:
      1. Mex, each gated by its walk delay (mobile builder must walk there).
      2. Solar up to solar_target  (energy phase, part 1).
      3. Wind  up to wind_target   (energy phase, part 2 — "into wind").
      4. A lab (only if workers are wanted and none is already down), then
         workers up to worker_target, dispatched as factory products.
      5. Construction turrets up to con_turret_target.

    ``build_power_source`` decides which of workers / con-turrets is the
    *primary* BP scaler and is queued first among (4)/(5); the other still
    builds up to its own target but after the primary.
    """
    queue: List[Tuple[str, str]] = []

    # 1) Mex, walk-gated.
    for i in range(plan.mex_count):
        delay = _walk_delay_for(plan, i)
        if delay > 0:
            queue.append((str(delay), "walk_delay"))
        queue.append(("mex", "build"))

    # 2/3) Energy phase — lead with the chosen source, still allow the other.
    energy_phases: List[Tuple[str, int]]
    if plan.energy_source == "wind":
        energy_phases = [("wind", plan.wind_target), ("solar", plan.solar_target)]
    else:
        energy_phases = [("solar", plan.solar_target), ("wind", plan.wind_target)]
    for key, target in energy_phases:
        for _ in range(max(0, target)):
            queue.append((key, "build"))

    # 4/5) Build-power phase.
    def worker_block() -> List[Tuple[str, str]]:
        if plan.worker_target <= 0:
            return []
        block: List[Tuple[str, str]] = []
        has_lab = plan.start_assets.get("t1_lab", 0) > 0
        if not has_lab:
            block.append(("t1_lab", "build"))
        block += [("t1_worker", "build")] * plan.worker_target
        return block

    def turret_block() -> List[Tuple[str, str]]:
        return [("con_turret", "build")] * max(0, plan.con_turret_target)

    if plan.build_power_source == "con_turret":
        queue += turret_block() + worker_block()
    else:
        queue += worker_block() + turret_block()

    # Events: commander explode = inject wreck metal + remove commander.
    events: List[Tuple[float, Callable[[EngineState], None]]] = []
    if plan.commander_explode:
        events.append((plan.commander_explode_time,
                       _make_com_explode(plan.commander_wreck_metal)))

    return queue, events


def _make_com_explode(wreck_metal: float) -> Callable[[EngineState], None]:
    def explode(state: EngineState) -> None:
        # Wreck reclaim lands in the bank (capped by storage).
        state.metal = min(state.m_cap, state.metal + wreck_metal)
        # Commander is gone: drop it as a builder and as a passive-income asset.
        state.builders = [b for b in state.builders if b.name != "Commander"]
        state.assets.pop("_commander", None)
        state.completed_log.append("com_explode")
    return explode


# ──────────────────────────────────────────────────────────────────────────
# Result + runner
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class PlanResult:
    plan: BuildPlan
    run_id: str
    final_state: EngineState
    engine: BuildPowerEngine
    queue: List[Tuple[str, str]]
    completion_times: Dict[str, List[float]]  # item_key -> sorted finish times

    # ---- derived metrics ---------------------------------------------------
    def income(self) -> Tuple[float, float]:
        """Final passive (metal/s, energy/s) from standing assets."""
        m, e = 0.0, 0.0
        for key, n in self.final_state.assets.items():
            rule = GAME_RULES.get(key)
            if rule:
                m += n * rule["m_out"]
                e += n * rule["e_out"]
        return m, e

    def effective_metal_income(self, e_to_m: float = 70.0) -> float:
        """Metal/s if all *surplus* energy is run through T1 econverters."""
        m, e = self.income()
        return m + max(0.0, e) / e_to_m

    def total_build_power(self) -> float:
        return sum(b.bp for b in self.final_state.builders)

    def count(self, key: str) -> int:
        return self.final_state.assets.get(key, 0)

    def time_to_nth(self, key: str, n: int) -> Optional[float]:
        """Game-clock time the n-th (1-based) unit of ``key`` finished."""
        times = self.completion_times.get(key, [])
        return times[n - 1] if 0 < n <= len(times) else None

    def stalled(self) -> Tuple[bool, bool]:
        recs = self.engine.ledger[self.run_id]
        return (any(r.m_stalled for r in recs), any(r.e_stalled for r in recs))

    # ---- reporting ---------------------------------------------------------
    def print_report(self) -> None:
        p = self.plan
        m_inc, e_inc = self.income()
        m_stall, e_stall = self.stalled()
        print("\n" + "═" * 78)
        print(f"  BAR ECO PLAN — {self.run_id}")
        print("═" * 78)
        print(f"  Window        : {p.start_time:.0f}s → {p.target_time:.0f}s "
              f"({p.target_time - p.start_time:.0f}s simulated)")
        print(f"  Energy scaler : {p.energy_source}    "
              f"BP scaler : {p.build_power_source}")
        print(f"  Mex plan      : {p.mex_count} taken, walk delays "
              f"{p.mex_walk_seconds or '[none]'}  "
              f"(⚠ replay-calibrate these)")
        if p.commander_explode:
            print(f"  Com explode   : t={p.commander_explode_time:.0f}s, "
                  f"+{p.commander_wreck_metal:.0f}M wreck, com removed after")
        print("─" * 78)
        print("  Targets reached (game clock):")
        for label, key, target in (
            ("Mex",        "mex",        p.mex_count),
            ("Solar",      "solar",      p.solar_target),
            ("Wind",       "wind",       p.wind_target),
            ("Worker",     "t1_worker",  p.worker_target),
            ("Con turret", "con_turret", p.con_turret_target),
        ):
            if target <= 0:
                continue
            got = self.count(key)
            t_last = self.time_to_nth(key, min(got, target))
            when = f"{t_last:6.1f}s" if t_last is not None else "  —   "
            flag = "" if got >= target else f"  ⚠ only {got}/{target}"
            print(f"    {label:<11} {got:>2}/{target:<2}   last finished @ {when}{flag}")
        print("─" * 78)
        print(f"  Final income  : {m_inc:+.2f} M/s , {e_inc:+.2f} E/s")
        print(f"  Eff. metal    : {self.effective_metal_income():.2f} M/s "
              f"(surplus E → converters @ 70:1)")
        print(f"  Build power   : {self.total_build_power():.0f} BP across "
              f"{len(self.final_state.builders)} builder(s)")
        print(f"  Bank @ end    : {self.final_state.metal:.0f} M , "
              f"{self.final_state.energy:.0f} E")
        stalls = ", ".join(s for s, on in
                           (("M-STALL", m_stall), ("E-STALL", e_stall)) if on)
        print(f"  Stalls        : {stalls or 'none'}")
        print("═" * 78)


def _extract_completion_times(engine: BuildPowerEngine, run_id: str,
                              abbrev_to_key: Dict[str, str]) -> Dict[str, List[float]]:
    """Walk the tick ledger and record when each item finished.

    The engine logs completions via the tick ``event`` (an abbrev). We map the
    abbrev back to the item key and collect timestamps in order.
    """
    times: Dict[str, List[float]] = {}
    for rec in engine.ledger[run_id]:
        if rec.event in ("-", ""):
            continue
        key = abbrev_to_key.get(rec.event, rec.event)
        times.setdefault(key, []).append(rec.t)
    return times


def plan_and_simulate(plan: BuildPlan, run_id: str = "plan",
                      time_step: float = 0.1) -> PlanResult:
    """Compile ``plan``, run the engine, and return a PlanResult."""
    problems = plan.validate()
    if problems:
        raise ValueError("Invalid BuildPlan:\n  - " + "\n  - ".join(problems))

    init = make_initial_state({
        "time": plan.start_time,
        "metal": plan.start_metal, "energy": plan.start_energy,
        "m_cap": plan.m_cap, "e_cap": plan.e_cap,
        "has_commander": plan.has_commander,
        "assets": dict(plan.start_assets),
    })

    queue, events = compile_plan(plan)
    engine = BuildPowerEngine(time_step=time_step)
    final = engine.simulate(run_id, init, queue, plan.target_time, events=events)

    # Build abbrev→key map from the engine's ABBREV table (invert it).
    from eco_simulator import ABBREV
    abbrev_to_key = {v: k for k, v in ABBREV.items()}
    completion_times = _extract_completion_times(engine, run_id, abbrev_to_key)

    return PlanResult(plan=plan, run_id=run_id, final_state=final,
                      engine=engine, queue=queue,
                      completion_times=completion_times)


# ──────────────────────────────────────────────────────────────────────────
# Capability registration (auto-discovered by bar_analytics/capabilities.py)
# ──────────────────────────────────────────────────────────────────────────
CAPABILITY = {
    "id": "bar_eco_planner",
    "name": "BAR Eco Planner",
    "description": (
        "Forward-projection planner for a BAR opening. Describe a plan in "
        "build-pattern language — starting bank, scale energy via solar→wind "
        "up to targets, scale build power via workers/con-turrets up to "
        "targets, take N mex at an explicit walk-delay pattern, and optionally "
        "commander-explode (inject wreck metal + drop the commander). Compiles "
        "onto the BuildPowerEngine tick simulator and reports when each target "
        "is hit, final M/s and E/s income, effective metal income, total build "
        "power, and any stalls. Mex walk delays are replay-calibrated "
        "placeholders — confirm against replays before trusting timings."
    ),
    "usage": "python bar_analytics/eco_planner.py            # demo plan\n"
             "python bar_analytics/eco_planner.py --ledger   # + tick ledger",
    "inputs": {
        "BuildPlan": "Dataclass of starting situation + scaling choices + "
                     "targets + mex walk list + com-explode flag",
        "Combined_Bar_Stats.csv": "Unit stats loaded by eco_simulator",
    },
    "outputs": {
        "PlanResult": "Completion times, final income, build power, stalls",
        "stdout": "Formatted plan report (and optional tick ledger)",
    },
    "tags": ["bar", "economics", "planner", "simulation", "build-order"],
}


# ──────────────────────────────────────────────────────────────────────────
# Demo / CLI
# ──────────────────────────────────────────────────────────────────────────
def _demo_plan() -> BuildPlan:
    return BuildPlan(
        start_metal=1000.0, start_energy=1000.0, start_time=3.0,
        energy_source="solar", build_power_source="worker",
        mex_count=4, mex_walk_seconds=[0.0, 4.0, 9.0, 16.0],
        solar_target=5, wind_target=8, worker_target=3, con_turret_target=1,
        commander_explode=False, target_time=180.0,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="BAR eco build-pattern planner.")
    ap.add_argument("--ledger", action="store_true",
                    help="Also print the full per-tick engine ledger.")
    ap.add_argument("--explode", action="store_true",
                    help="Enable commander-explode in the demo plan.")
    args = ap.parse_args()

    # Windows consoles default to cp1252, which can't encode the box-drawing
    # characters in the report. Best-effort switch stdout to UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    plan = _demo_plan()
    if args.explode:
        plan.commander_explode = True
        plan.commander_explode_time = 120.0

    result = plan_and_simulate(plan)
    result.print_report()

    print("\n  Compiled queue:")
    for i, (key, mode) in enumerate(result.queue):
        print(f"    {i:>2}. {mode:<10} {key}")

    if args.ledger:
        result.engine.print_ledger(result.run_id, every=5.0)
        result.engine.print_stall_trace(result.run_id)


if __name__ == "__main__":
    main()

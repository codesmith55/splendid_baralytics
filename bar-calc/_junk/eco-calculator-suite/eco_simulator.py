"""
BAR build-power engine — state-based, per-builder resource tracking.

Tick loop:
  1. Add the economy's passive metal and energy income to a tick-local pool.
  2. Walk every builder in insertion order. Each builder spends
        (bp / target.bp_cost) * target.m_cost   metal  per second
        (bp / target.bp_cost) * target.e_cost   energy per second
     against its current build target.  The pool is drawn down as we go, so a
     builder later in the list sees whatever is left after the earlier ones
     have already paid in (or drawn out).
  3. If the pool can't cover what a builder requested, that builder is
     throttled to the limiting-resource ratio and the corresponding stall
     flag (`m_stalled` / `e_stalled`) is set on the builder *and* on the
     tick aggregate.  Subsequent builders see the now-empty pool and stall
     too — that's the "all subsequent builders slow down" behaviour.
  4. Cap the pool at storage and commit it back to state.

Each source of build power is its own `Builder` object (commander, mobile cons,
factories).  The commander's passive income is folded into the economy via a
synthetic asset key so the income loop is symmetric.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Calibrated map-distance → walk-time model. Optional: if the module is missing
# the simulator still runs, it just can't convert grid-distance walk steps.
try:
    import bar_distance
except ImportError:  # pragma: no cover
    bar_distance = None


# ──────────────────────────────────────────────────────────────────────────
# Game rules (loaded from the bundled stats CSV; fallback defaults below)
# ──────────────────────────────────────────────────────────────────────────
SHORT_KEY_MAP = {
    "mex":         "Metal Extractor",
    "solar":       "Solar Collector",
    "wind":        "Wind Turbine",
    "t1_lab":      "T1 Bot Lab",
    "t1_worker":   "Construction Bot",
    "lazarus":     "Lazarus",
    "con_turret":  "Construction Turret",
}

ABBREV = {
    "mex": "Mex", "solar": "Solar", "wind": "Wind",
    "t1_lab": "Lab", "t1_worker": "Con Bot",
    "lazarus": "Lazarus", "walk_delay": "Walk",
    "con_turret": "Con Turret",
}

# Items the factory produces.  Anything else is a building/structure built
# by a mobile builder.
FACTORY_PRODUCTS = {"t1_worker", "lazarus"}

GAME_RULES: Dict[str, dict] = {}
COMMANDER_PROFILE = {
    "name": "Armada Commander",
    "m_out": 2.0,
    "e_out": 30.0,
    "bp_out": 300,
}


def load_game_rules_from_csv(file_path: str = "Combined_Bar_Stats.csv",
                             faction: str = "Armada") -> None:
    """Seed fallback rules, then overlay *exact* name matches from the CSV.

    Combined_Bar_Stats.csv covers units (bots, vehicles) but does NOT list the
    static buildings (Metal Extractor, Solar Collector, Wind Turbine, Bot
    Lab).  Substring matching also conflates `Construction Bot` with
    `Advanced Construction Bot`, so we require exact-name matches here.

    `faction` controls which mirror-unit stats win when both Armada and
    Cortex have a row with the same name.  Defaults to Armada to stay
    consistent with the default Armada commander profile.
    """
    global COMMANDER_PROFILE

    # Always seed defaults first so building rules exist even if the CSV is
    # missing or only contains unit rows.
    _seed_fallback_rules()

    if not os.path.exists(file_path):
        return

    rows: List[dict] = []
    with open(file_path, mode="r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("Faction") and row.get("Name"):
                rows.append(row)
    # Preferred faction first so its rows overlay last and aren't overwritten
    # by the opposite faction's mirror unit further down the CSV.
    rows.sort(key=lambda r: 0 if r["Faction"].strip().lower() != faction.lower() else 1)

    # Commander baseline — first row of the preferred faction whose name
    # contains "commander".
    for row in rows:
        if "commander" not in row["Name"].lower():
            continue
        if row["Faction"].strip().lower() != faction.lower():
            continue
        try:
            COMMANDER_PROFILE = {
                "name":  row["Name"].strip(),
                "m_out": float(row.get("MetalProduced", 0) or 0),
                "e_out": float(row.get("EnergyProduced", 0) or 0),
                "bp_out": int(float(row.get("BuildPower", 0) or 0)),
            }
        except ValueError:
            pass
        break

    # Exact-name overlay for the items we know about.
    for row in rows:
        name = row["Name"].strip()
        for short_key, expected in SHORT_KEY_MAP.items():
            if name.lower() != expected.lower():
                continue
            try:
                m_cost  = float(row.get("MetalCost", 0)     or 0)
                e_cost  = float(row.get("EnergyCost", 0)    or 0)
                bp_cost = float(row.get("BuildCost", 0)     or 0)
                m_prod  = float(row.get("MetalProduced", 0) or 0)
                e_prod  = float(row.get("EnergyProduced", 0) or 0)
                bp_out  = float(row.get("BuildPower", 0)    or 0)
            except ValueError:
                continue

            e_out_net = e_prod if short_key != "mex" else -2.0
            m_out_net = m_prod if short_key == "mex" else 0.0

            GAME_RULES[short_key] = {
                "name":    name,
                "m_cost":  m_cost,
                "e_cost":  e_cost,
                "bp_cost": bp_cost,
                "m_out":   m_out_net,
                "e_out":   e_out_net,
                "bp_out":  int(bp_out or 0),
            }


def _seed_fallback_rules() -> None:
    GAME_RULES.update({
        "mex":       {"name": "Metal Extractor",  "m_cost":  50, "e_cost":  500, "bp_cost": 1800, "m_out": 1.85, "e_out": -2.0, "bp_out":   0},
        "solar":     {"name": "Solar Collector",  "m_cost": 150, "e_cost":    0, "bp_cost": 2800, "m_out": 0.0,  "e_out": 20.0, "bp_out":   0},
        "wind":      {"name": "Wind Turbine",     "m_cost":  43, "e_cost":  175, "bp_cost": 1600, "m_out": 0.0,  "e_out": 11.9, "bp_out":   0},
        "t1_lab":    {"name": "T1 Bot Lab",       "m_cost": 620, "e_cost": 1300, "bp_cost": 6500, "m_out": 0.0,  "e_out":  0.0, "bp_out": 150},
        "t1_worker": {"name": "Construction Bot", "m_cost": 110, "e_cost": 1600, "bp_cost": 3453, "m_out": 0.0,  "e_out":  7.0, "bp_out":  80},
        "lazarus":   {"name": "Lazarus",          "m_cost": 110, "e_cost": 1400, "bp_cost": 2400, "m_out": 0.0,  "e_out":  0.0, "bp_out": 200},
        "con_turret":{"name": "Construction Turret","m_cost": 230,"e_cost": 3200, "bp_cost": 5300, "m_out": 0.0,  "e_out":  0.0, "bp_out": 200},
    })


load_game_rules_from_csv()


# ──────────────────────────────────────────────────────────────────────────
# Core data model
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class BuildTarget:
    """A unit or structure that one or more builders are working on."""
    item_key: str
    bp_remaining: float
    mode: str  # "build" or "assist"

    @property
    def rule(self) -> dict:
        return GAME_RULES[self.item_key]

    @property
    def bp_cost(self) -> float:
        return self.rule["bp_cost"]


@dataclass
class Builder:
    """A single source of build power."""
    name: str
    bp:   float
    kind: str  # "mobile" or "factory"
    target:     Optional[BuildTarget] = None
    walk_delay: float = 0.0

    # Refreshed every tick — convenient for the reporting layer.
    last_bp_applied: float = 0.0
    last_efficiency: float = 1.0
    last_m_stalled:  bool  = False
    last_e_stalled:  bool  = False


@dataclass
class TickRecord:
    t: float
    event:        str
    metal:        float
    energy:       float
    m_inc:        float   # +M/s passive income
    e_inc:        float   # +E/s passive income
    m_drain:      float   # -M/s spent on construction
    e_drain:      float   # -E/s spent on construction
    m_stalled:    bool    # any builder M-stalled this tick
    e_stalled:    bool    # any builder E-stalled this tick
    builder_status: List[Tuple[str, str, float, float, bool, bool]] = field(default_factory=list)
    # Each tuple: (builder_name, target_item, bp_applied, efficiency, m_stall, e_stall)


@dataclass
class EngineState:
    time:           float = 0.0
    metal:          float = 1000.0
    energy:         float = 1000.0
    m_cap:          float = 1300.0
    e_cap:          float = 1450.0
    assets:         Dict[str, int] = field(default_factory=dict)
    builders:       List[Builder]  = field(default_factory=list)
    completed_log:  List[str]      = field(default_factory=list)
    # Queue items waiting for a compatible builder.  Ordering within each
    # builder kind (mobile / factory) is preserved, but the two kinds can
    # dispatch independently — a lab can start a worker while the commander
    # is still finishing a solar later in the queue.
    pending:        List[Tuple[str, str]] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────
class BuildPowerEngine:
    def __init__(self, time_step: float = 0.1, handoff_lag: float = 0.25):
        self.dt = time_step
        self.handoff_lag = handoff_lag
        self.ledger: Dict[str, List[TickRecord]] = {}

    # ---------- Income ----------------------------------------------------
    def _passive_income(self, state: EngineState) -> Tuple[float, float]:
        m, e = 0.0, 0.0
        for key, n in state.assets.items():
            rule = GAME_RULES.get(key)
            if rule is None:
                continue
            m += n * rule["m_out"]
            e += n * rule["e_out"]
        return m, e

    # ---------- Queue → builder assignment --------------------------------
    def _try_assign(self, state: EngineState) -> None:
        """Walk the pending queue and dispatch any items we can right now.

        Items are processed in order, but the two builder kinds (mobile and
        factory) are independent: when an item can't dispatch because its
        builder kind is busy, we mark *that kind* as blocked and keep
        walking — items of the other kind can still go through.  This lets
        the lab build workers while the commander is still finishing solars
        further down the queue.
        """
        new_pending: List[Tuple[str, str]] = []
        blocked = {"mobile": False, "factory": False}

        for item_key, mode in state.pending:
            if mode in ("walk_delay", "walk_squares", "walk_elmos"):
                # Applies to the next idle mobile builder.  If mobile is
                # blocked or no mobile is idle, the walk stays pending and we
                # mark mobile blocked (so subsequent mobile items remain queued
                # behind it).
                #   walk_delay   : item_key is seconds (legacy, hand-entered)
                #   walk_squares : item_key is grid squares  -> converted
                #   walk_elmos   : item_key is elmos          -> converted
                # The grid-distance modes derive the time from the *walking*
                # builder's real speed and build range via bar_distance, so the
                # number tracks the unit instead of being guessed.
                if blocked["mobile"]:
                    new_pending.append((item_key, mode))
                    continue
                victim = self._next_idle_builder(state, "mobile")
                if victim is None:
                    blocked["mobile"] = True
                    new_pending.append((item_key, mode))
                    continue
                victim.walk_delay = max(victim.walk_delay,
                                        self._walk_seconds(item_key, mode, victim))
                continue

            if item_key not in GAME_RULES:
                continue   # silently drop unknown items

            target_kind = "factory" if item_key in FACTORY_PRODUCTS else "mobile"

            if mode == "assist":
                # Assist gates on its natural builder kind for ordering, but
                # any idle builder (mobile or factory) can join in as helper.
                if blocked[target_kind]:
                    new_pending.append((item_key, mode))
                    continue
                primary = self._next_idle_builder(state, target_kind)
                if primary is None:
                    primary = (self._next_idle_builder(state, "mobile")
                               or self._next_idle_builder(state, "factory"))
                if primary is None:
                    blocked[target_kind] = True
                    new_pending.append((item_key, mode))
                    continue
                tgt = BuildTarget(item_key=item_key,
                                  bp_remaining=GAME_RULES[item_key]["bp_cost"],
                                  mode="assist")
                primary.target = tgt
                for b in state.builders:
                    if b is primary or b.target is not None or b.walk_delay > 0:
                        continue
                    b.target = tgt
                continue

            # mode == "build"
            if blocked[target_kind]:
                new_pending.append((item_key, mode))
                continue
            b = self._next_idle_builder(state, target_kind)
            if b is None:
                blocked[target_kind] = True
                new_pending.append((item_key, mode))
                continue
            b.target = BuildTarget(item_key=item_key,
                                   bp_remaining=GAME_RULES[item_key]["bp_cost"],
                                   mode="build")

        state.pending = new_pending

    @staticmethod
    def _walk_seconds(item_key: str, mode: str, victim: Builder) -> float:
        """Resolve a walk step to seconds.

        `walk_delay` is already seconds.  `walk_squares` / `walk_elmos` are map
        distances converted via bar_distance using the walking unit's real
        speed and build range (so a Commander hop differs from a Con Bot hop).
        Falls back to treating the value as raw seconds if bar_distance is
        unavailable."""
        seconds = float(item_key)
        if mode == "walk_delay" or bar_distance is None:
            return seconds
        if mode == "walk_squares":
            return bar_distance.walk_time_squares(seconds, victim.name)
        if mode == "walk_elmos":
            return bar_distance.walk_time(seconds, victim.name)
        return seconds

    def _next_idle_builder(self, state: EngineState, kind: str) -> Optional[Builder]:
        for b in state.builders:
            if b.kind == kind and b.target is None and b.walk_delay <= 0:
                return b
        return None

    # ---------- One tick of work ------------------------------------------
    def _do_tick(self, state: EngineState) -> TickRecord:
        dt = self.dt

        # 1) Passive economy income into a tick-local pool.
        m_inc, e_inc = self._passive_income(state)
        pool_m = state.metal  + m_inc * dt
        pool_e = state.energy + e_inc * dt

        # Tick cooldowns down for idle builders.
        for b in state.builders:
            if b.target is None and b.walk_delay > 0:
                b.walk_delay = max(0.0, b.walk_delay - dt)
            # reset per-tick reporting fields
            b.last_bp_applied = 0.0
            b.last_efficiency = 1.0
            b.last_m_stalled  = False
            b.last_e_stalled  = False

        # 2) Sequential per-builder resource allocation.
        m_drain_total = 0.0
        e_drain_total = 0.0
        any_m_stall   = False
        any_e_stall   = False
        statuses: List[Tuple[str, str, float, float, bool, bool]] = []
        # We track targets to handle assist-mode completions correctly:
        # the first builder may finish the target, subsequent helpers see
        # bp_remaining == 0 and skip.
        targets_touched: Dict[int, BuildTarget] = {}

        for b in state.builders:
            if b.target is None or b.walk_delay > 0:
                continue
            tgt  = b.target
            rule = tgt.rule

            nominal_bp = min(b.bp * dt, tgt.bp_remaining)
            if nominal_bp <= 0:
                continue

            ratio  = nominal_bp / tgt.bp_cost
            m_need = rule["m_cost"] * ratio
            e_need = rule["e_cost"] * ratio

            # Throttle this builder to whatever the pool can actually cover.
            efficiency = 1.0
            m_stall = False
            e_stall = False
            if m_need > 1e-9 and pool_m < m_need:
                efficiency = min(efficiency, max(0.0, pool_m / m_need))
                m_stall = True
            if e_need > 1e-9 and pool_e < e_need:
                efficiency = min(efficiency, max(0.0, pool_e / e_need))
                e_stall = True

            actual_bp = nominal_bp * efficiency
            actual_m  = m_need     * efficiency
            actual_e  = e_need     * efficiency

            pool_m -= actual_m
            pool_e -= actual_e
            tgt.bp_remaining -= actual_bp
            m_drain_total += actual_m
            e_drain_total += actual_e
            any_m_stall = any_m_stall or m_stall
            any_e_stall = any_e_stall or e_stall

            b.last_bp_applied = actual_bp
            b.last_efficiency = efficiency
            b.last_m_stalled  = m_stall
            b.last_e_stalled  = e_stall

            statuses.append((b.name, tgt.item_key,
                             actual_bp, efficiency, m_stall, e_stall))

            targets_touched[id(tgt)] = tgt

        # 3) Promote completed targets to assets / new builders.
        completions: List[str] = []
        for tgt in targets_touched.values():
            if tgt.bp_remaining > 1e-6:
                continue
            item_key = tgt.item_key
            state.assets[item_key] = state.assets.get(item_key, 0) + 1
            state.completed_log.append(item_key)
            completions.append(item_key)

            # Free every builder pointing at this target.
            for b in state.builders:
                if b.target is tgt:
                    b.target = None
                    if b.kind == "mobile":
                        b.walk_delay = self.handoff_lag

            self._spawn_builder_from_item(state, item_key)

        event = ABBREV.get(completions[0], completions[0]) if completions else "-"

        # 4) Cap & commit.
        state.metal  = max(0.0, min(pool_m, state.m_cap))
        state.energy = max(0.0, min(pool_e, state.e_cap))
        state.time  += dt

        return TickRecord(
            t=state.time, event=event,
            metal=state.metal, energy=state.energy,
            m_inc=m_inc, e_inc=e_inc,
            m_drain=m_drain_total / dt, e_drain=e_drain_total / dt,
            m_stalled=any_m_stall, e_stalled=any_e_stall,
            builder_status=statuses,
        )

    def _spawn_builder_from_item(self, state: EngineState, item_key: str) -> None:
        """If the completed item produces BP, add it to the builder lineup."""
        rule = GAME_RULES.get(item_key, {})
        bp = rule.get("bp_out", 0)
        if not bp:
            return
        if item_key == "t1_lab":
            idx = sum(1 for b in state.builders if b.kind == "factory") + 1
            state.builders.append(Builder(name=f"Lab_{idx}", bp=bp, kind="factory"))
        else:
            idx = sum(1 for b in state.builders
                      if b.kind == "mobile" and b.name != "Commander") + 1
            label = ABBREV.get(item_key, item_key)
            state.builders.append(Builder(name=f"{label}_{idx}", bp=bp, kind="mobile"))

    # ---------- Public driver --------------------------------------------
    def simulate(self, run_id: str, init: EngineState,
                 queue: List[Tuple[str, str]], target_time: float) -> EngineState:
        state = EngineState(
            time=init.time, metal=init.metal, energy=init.energy,
            m_cap=init.m_cap, e_cap=init.e_cap,
            assets=dict(init.assets),
            builders=[Builder(name=b.name, bp=b.bp, kind=b.kind,
                              walk_delay=b.walk_delay) for b in init.builders],
            completed_log=list(init.completed_log),
            pending=list(queue),
        )
        records: List[TickRecord] = []
        self.ledger[run_id] = records

        while state.time < target_time:
            self._try_assign(state)
            records.append(self._do_tick(state))
        return state

    # ---------- Reporting -------------------------------------------------
    def print_ledger(self, run_id: str, every: float = 1.0) -> None:
        records = self.ledger[run_id]
        print("\n" + "═" * 150)
        print(f"  BUILD-POWER LEDGER — {run_id}")
        print("═" * 150)
        print(f"{'Time':>7} | {'Event':<10} | {'Metal':>22} | {'+M/s : -M/s':>16} | "
              f"{'Energy':>22} | {'+E/s : -E/s':>16} | {'Stall':<10}")
        print("─" * 150)

        last_t = -1e9
        for r in records:
            interesting = (r.event != "-") or r.m_stalled or r.e_stalled
            time_due    = (r.t - last_t) >= (every - 1e-6)
            if not (interesting or time_due):
                continue
            last_t = r.t

            net_m = r.m_inc - r.m_drain
            net_e = r.e_inc - r.e_drain
            m_col = f"{r.metal:>7.1f} ({'+' if net_m >= 0 else ''}{net_m:.2f}/s)"
            e_col = f"{r.energy:>7.1f} ({'+' if net_e >= 0 else ''}{net_e:.2f}/s)"
            m_flow = f"+{r.m_inc:.1f} : -{r.m_drain:.1f}"
            e_flow = f"+{r.e_inc:.1f} : -{r.e_drain:.1f}"
            flags = []
            if r.m_stalled: flags.append("M-STALL")
            if r.e_stalled: flags.append("E-STALL")
            stall = ",".join(flags) if flags else "-"
            print(f"{r.t:>6.1f}s | {r.event:<10} | {m_col:>22} | {m_flow:>16} | "
                  f"{e_col:>22} | {e_flow:>16} | {stall:<10}")
        print("═" * 150)

    def print_stall_trace(self, run_id: str) -> None:
        """Per-builder detail for every tick that flagged a stall."""
        records = self.ledger[run_id]
        stall_ticks = [r for r in records if r.m_stalled or r.e_stalled]
        if not stall_ticks:
            print("\n  (no stalls observed)")
            return
        print("\n" + "─" * 96)
        print("  PER-BUILDER STALL TRACE")
        print("─" * 96)
        print(f"{'Time':>7} | {'Builder':<14} | {'Target':<10} | {'BP':>6} | {'Eff':>5} | {'Flags':<6}")
        print("─" * 96)
        for r in stall_ticks:
            for (name, tgt, bp, eff, m_s, e_s) in r.builder_status:
                if not (m_s or e_s):
                    continue   # only the stalled builders on these ticks
                flag = (("M" if m_s else "") + ("E" if e_s else "")) or "-"
                print(f"{r.t:>6.1f}s | {name:<14} | {tgt:<10} | "
                      f"{bp:>6.2f} | {eff:>5.2f} | {flag:<6}")
        print("─" * 96)


# ──────────────────────────────────────────────────────────────────────────
# Initial-state helper
# ──────────────────────────────────────────────────────────────────────────
def make_initial_state(config: Dict[str, any]) -> EngineState:
    state = EngineState(
        time=float(config.get("time",     0.0)),
        metal=float(config.get("metal",   1000.0)),
        energy=float(config.get("energy", 1000.0)),
        m_cap=float(config.get("m_cap",   1300.0)),
        e_cap=float(config.get("e_cap",   1450.0)),
        assets=dict(config.get("assets", {})),
    )
    if config.get("has_commander", True):
        state.builders.append(Builder(
            name="Commander", bp=COMMANDER_PROFILE["bp_out"], kind="mobile"))
        # Inject the commander's passive income through the same path as
        # any other asset by registering a synthetic income-only rule.
        state.assets["_commander"] = 1
        GAME_RULES.setdefault("_commander", {
            "name":    "Commander baseline income",
            "m_cost":  0, "e_cost": 0, "bp_cost": 0,
            "m_out":   COMMANDER_PROFILE["m_out"],
            "e_out":   COMMANDER_PROFILE["e_out"],
            "bp_out":  0,
        })
    return state


# Demo run -----------------------------------------------------------------
if __name__ == "__main__":
    init = make_initial_state({
        "time":   3.0,
        "metal":  1000.0,  "energy": 1000.0,
        "m_cap":  1300.0,  "e_cap":  1450.0,
        "has_commander": True,
        "assets": {},
    })

    solar_opening = [
        ("mex",       "build"),
        ("mex",       "build"),
        ("mex",       "build"),
        ("solar",     "build"),
        ("3.5",       "walk_delay"),
        ("mex",       "build"),
        ("solar",     "build"),
        ("t1_lab",    "build"),
        ("solar",     "build"),
        ("solar",     "build"),
        ("t1_worker", "assist"),
        ("solar",     "build"),
        ("t1_worker", "assist"),
    ]

    engine = BuildPowerEngine(time_step=0.1)
    engine.simulate("Solar Strategy", init, solar_opening, target_time=120.0)
    engine.print_ledger("Solar Strategy", every=2.0)
    engine.print_stall_trace("Solar Strategy")

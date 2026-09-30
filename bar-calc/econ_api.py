#!/usr/bin/env python3
"""ECON API — state in, one perspective out, and the answer is recorded.

Every analysis in this repo now has the same shape:

    Context  ->  capability(**params)  ->  dict

A Context is the STATE IN. It is either a recorded game at a moment, or a hand-written
position, plus the framing that every economic question needs: how many metal spots this
position can ever hold, how many workers are out claiming them, whether the factory is
producing. A capability is one PERSPECTIVE on that state. Its output is a plain dict, so
it serialises, and it is recorded in `econ.db` with the function's version, which is what
makes a stored conclusion checkable rather than merely cached.

Adding a perspective is one decorated function. The decorator carries the documentation,
so `--spec` is always current and an agent can read the whole surface without reading the
code.

    python bar-calc/econ_api.py --spec
    python bar-calc/econ_api.py --list
    python bar-calc/econ_api.py --game 1 --at 60 --run "state,budget,phases,next_build"
    python bar-calc/econ_api.py --game 1 --at 60 --run "cadence,path" --build wind-conversion
    python bar-calc/econ_api.py --state '{"m_inc":9.3,"e_inc":97,"bp":610,"metal":175,"energy":508}' --run next_build
    python bar-calc/econ_api.py --game 1 --run all --quiet        # every perspective
    python bar-calc/econ_api.py --selftest
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass, field, is_dataclass, asdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bar_unified as U                                            # noqa: E402
import econ_db as DB                                              # noqa: E402
import econ_data as ED                                            # noqa: E402
import unit_catalog as UC                                         # noqa: E402

VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_FILE = os.path.join(HERE, "bar_unified.py")
NL = chr(10)


# ══════════════════════════════════════════════════════════════════════════
# STATE IN
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Context:
    """The state a question is asked about, plus the framing it needs to be answerable.

    Either `game` (+ `at`) to read a real position, or `state` to write one by hand.
    The framing fields are not decoration: a mex budget decides the metal ceiling, and
    the pool policy decides which build power may legally do which work. Both are
    reported back in `describe()` so a recorded answer says what it assumed."""
    # where the position comes from
    game: Optional[Union[int, str]] = None
    at: float = 60.0
    state: Optional[dict] = None
    # the frame
    position: str = "front"
    mex: Optional[int] = None
    team: Optional[int] = None
    map_name: Optional[str] = None
    standing: Optional[int] = None
    # the build-power policy
    workers: int = 1
    expanding: int = 0
    commander: str = "base"
    factory_on: bool = True
    assist: float = 0.0
    # what is being built and what the metal is for
    target: str = "Wind"
    bp_source: str = "ConTurret"
    energy_source: str = "Solar"
    on: str = "Mex"
    # naming, for the record
    user_name: Optional[str] = None
    build_name: Optional[str] = None
    _cache: dict = field(default_factory=dict, repr=False)

    # ---- resolution, each done once ----
    def data(self) -> Optional[dict]:
        if self.game is None:
            return None
        if "data" not in self._cache:
            g = self.game
            self._cache["data"] = U.load_game_data(
                int(g) if str(g).isdigit() else g)
        return self._cache["data"]

    def eco_state(self) -> U.EcoState:
        if "state" in self._cache:
            return self._cache["state"]
        if self.state:
            base = dict(self.state)
            st = U.EcoState(
                t=float(base.get("t", self.at)),
                metal=float(base.get("metal", 1000.0)),
                energy=float(base.get("energy", 1000.0)),
                m_inc=float(base.get("m_inc", 0.0)),
                e_inc=float(base.get("e_inc", 0.0)),
                bp=float(base.get("bp", 300.0)),
                counts=dict(base.get("counts") or {}),
                m_cap=float(base.get("m_cap", max(1000.0, base.get("metal", 1000.0)))),
                e_cap=float(base.get("e_cap", max(1000.0, base.get("energy", 1000.0)))),
                wind=float(base.get("wind", U.DEFAULT_WIND)))
        else:
            d = self.data()
            if d is None:
                raise ValueError("a Context needs either `game` or `state`")
            st = U.state_from_game(d, self.at)
        self._cache["state"] = st
        return st

    def budget(self) -> dict:
        if "budget" in self._cache:
            return self._cache["budget"]
        d = self.data() or {}
        g = d.get("game") or {}
        pl = d.get("player") or {}
        st = self.eco_state()
        standing = (self.standing if self.standing is not None
                    else int(st.counts.get("Mex", 0)))
        b = U.mex_budget(
            map_query=self.map_name or g.get("map") or "All That Glitters",
            team=int(self.team if self.team is not None else (pl.get("team_id") or 0)),
            count=self.mex, position=self.position, standing=standing)
        self._cache["budget"] = b
        return b

    def pools(self) -> U.BpPools:
        if "pools" in self._cache:
            return self._cache["pools"]
        st = self.eco_state()
        p = U.split_bp(st.counts, expanding=self.expanding, commander=self.commander,
                       factory_on=self.factory_on, assist=self.assist,
                       bp_override=st.bp if st.counts else None)
        self._cache["pools"] = p
        return p

    def game_id(self) -> Optional[str]:
        d = self.data()
        return ((d or {}).get("game") or {}).get("id")

    def describe(self) -> dict:
        """Exactly what went in, for the provenance row. No derived values."""
        st = self.eco_state()
        return {"source": ("game" if self.game is not None else "state"),
                "game": self.game_id(), "at": round(st.t, 2),
                "state": {"metal": st.metal, "energy": st.energy, "m_inc": st.m_inc,
                          "e_inc": st.e_inc, "bp": st.bp, "m_cap": st.m_cap,
                          "e_cap": st.e_cap, "wind": st.wind,
                          "counts": dict(st.counts)},
                "frame": {"position": self.position, "mex": self.mex,
                          "team": self.team, "map": self.map_name,
                          "standing": self.standing},
                "policy": {"workers": self.workers, "expanding": self.expanding,
                           "commander": self.commander, "factory_on": self.factory_on,
                           "assist": self.assist},
                "choices": {"target": self.target, "bp_source": self.bp_source,
                            "energy_source": self.energy_source, "on": self.on}}


# ══════════════════════════════════════════════════════════════════════════
# CAPABILITIES
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Capability:
    name: str
    fn: Callable[..., dict]
    version: str
    summary: str
    question: str
    params: Dict[str, str]
    returns: Dict[str, str]
    needs: Sequence[str]
    tags: Sequence[str]
    notes: str = ""

    def spec(self) -> dict:
        return {"name": self.name, "version": self.version, "summary": self.summary,
                "question": self.question, "params": self.params,
                "returns": self.returns, "needs": list(self.needs),
                "tags": list(self.tags), "notes": self.notes}


CAPABILITIES: Dict[str, Capability] = {}


def capability(name: str, version: str, summary: str, question: str,
               params: Optional[Dict[str, str]] = None,
               returns: Optional[Dict[str, str]] = None,
               needs: Sequence[str] = ("state",), tags: Sequence[str] = (),
               notes: str = ""):
    """Register one perspective.

    `version` is the contract: bump it whenever the meaning of the output changes, and
    every recorded run at the old version becomes visibly stale instead of quietly
    wrong. `needs` says what the Context must supply - "state" or "game"."""
    def deco(fn):
        CAPABILITIES[name] = Capability(name, fn, version, summary, question,
                                        dict(params or {}), dict(returns or {}),
                                        tuple(needs), tuple(tags), notes)
        fn.capability_name = name
        return fn
    return deco


def _clean(v: Any, depth: int = 0) -> Any:
    """Make an output JSON-safe: drop the live objects, keep the numbers."""
    if depth > 8:
        return str(v)
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, U.EcoState):
        return {"t": v.t, "metal": v.metal, "energy": v.energy, "m_inc": v.m_inc,
                "e_inc": v.e_inc, "bp": v.bp, "m_cap": v.m_cap, "e_cap": v.e_cap,
                "wind": v.wind, "counts": dict(v.counts)}
    if isinstance(v, U.BpPools):
        return {"expand": v.expand, "factory": v.factory, "base": v.base,
                "factory_on": v.factory_on, "assist": v.assist,
                "total": v.total, "detail": v.detail, "policy": v.policy}
    if is_dataclass(v):
        try:
            return _clean(asdict(v), depth + 1)
        except (TypeError, ValueError):
            return str(v)
    if isinstance(v, dict):
        return {str(k): _clean(x, depth + 1) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_clean(x, depth + 1) for x in v]
    if isinstance(v, float) and v != v:
        return None
    return str(v)


# ---------------------------------------------------------------- perspectives

@capability(
    "state", "1.0.0",
    "The position itself: the five quantities, which regime it is in, and the rate it "
    "can actually sustain.",
    "Where am I, and what is limiting me right now?",
    params={"on": "the work the metal is for (default the Context's `on`)"},
    returns={"quantities": "metal, energy, their incomes, build power, caps, wind",
             "regime": "metal | bp | energy | overflow, with the ratios behind it",
             "sustained": "per candidate: nominal time, effective build power, "
                          "steps until a bank empties, the rate that survives",
             "usable": "value per second counting only energy the builders can burn"},
    tags=("core",))
def cap_state(ctx: Context, on: Optional[str] = None) -> dict:
    st = ctx.eco_state()
    work = on or ctx.on
    reg = U.regime_of(st.m_inc, st.e_inc, st.bp, work)
    return {"quantities": _clean(st),
            "regime": reg,
            "regime_meaning": U.REGIME_STYLE[reg["regime"]][2],
            "regime_fix": U.REGIME_STYLE[reg["regime"]][3],
            "sustained": U.scaling_report(st, verbose=False),
            "usable": U.usable_value_per_s(st.m_inc, st.e_inc, st.bp, work),
            "energy_ceiling": U.energy_ceiling(st.bp, work)}


@capability(
    "budget", "1.0.0",
    "The metal spots this position can ever hold, each with its own richness and walk.",
    "How much room do I have left to grow, and what is each remaining spot worth?",
    params={"position": "tech (7) or front (12), from econ_model.json positions.mexBudget",
            "mex": "an explicit spot count, overriding the position",
            "standing": "how many are already held (default: counted from the game)"},
    returns={"spots": "ordered by distance, with metal_per_s and walk_sec each",
             "room": "spots left. Metal-bound is the GOAL only while this is above zero",
             "m_per_s_current": "income from the spots held",
             "m_per_s_projected": "income if the whole budget were held",
             "walk_routed_sec": "routed nearest-next, not the sum of from-spawn walks",
             "flat_estimate": "what count x 1.825 would have said, for comparison"},
    needs=("state",), tags=("core", "frame"),
    notes="Richness is real: 146 of All That Glitters' 152 spots pay 1.825 m/s and six "
          "pay 3.16, so a flat count is wrong wherever a rich spot is in reach.")
def cap_budget(ctx: Context) -> dict:
    b = dict(ctx.budget())
    b.pop("route", None)
    return b


@capability(
    "phases", "1.0.0",
    "Both phase axes, measured against the budget rather than asserted.",
    "What phase am I in, and what does that phase say is worth doing?",
    params={"workers": "how many builders are out claiming",
            "on": "the work the metal is for, which sets the energy thresholds"},
    returns={"mex": "to_take | tasked | taken, with the expected completion time",
             "energy": "underpowered | spend_current | spend_projected | scaling, "
                       "with the E/s and BP each threshold needs",
             "capped": "true when there is no room left, which inverts the advice",
             "fungible": "whether the 70:1 converter price is defensible here"},
    tags=("core", "frame"))
def cap_phases(ctx: Context, workers: Optional[int] = None,
               on: Optional[str] = None) -> dict:
    return U.phase_markers(ctx.eco_state(), ctx.budget(), target=ctx.target,
                           on=on or ctx.on, workers=workers or ctx.workers)


@capability(
    "claim", "1.0.0",
    "Route the unclaimed spots across the workers that exist.",
    "If I task my workers with taking every remaining spot, when is it done?",
    params={"workers": "how many builders", "bp_per_worker": "build power each"},
    returns={"chains": "per worker: the spots in order, each with its walk and finish",
             "expected_complete_sec": "when the LAST spot lands, which is when the "
                                      "claiming phase ends",
             "slowest_worker": "the one that decides it"},
    tags=("expand",),
    notes="Walks are routed nearest-next from where each builder is standing. Summing "
          "the from-spawn distances instead overstates it badly: 302s against 167s.")
def cap_claim(ctx: Context, workers: Optional[int] = None,
              bp_per_worker: float = 100.0) -> dict:
    return U.claim_plan(ctx.budget(), workers=workers or ctx.workers,
                        bp_per_worker=bp_per_worker)


@capability(
    "pools", "1.0.0",
    "Build power split into expand, factory and base, under a stated policy.",
    "Which of my build power may legally do this work, and how much of it?",
    params={"expanding": "mobile workers out claiming",
            "commander": "base or expand", "factory_on": "the factory is binary",
            "assist": "fraction of base lent to the factory",
            "targets": "which units to report legality for"},
    returns={"expand": "highest priority: claiming spots",
             "factory": "factory products only, and binary",
             "base": "infrastructure and energy, or assist, or become expand",
             "legality": "per target: which pool may build it and how much BP that is",
             "policy": "what was assumed, because position is not in the stream"},
    tags=("core", "bp"),
    notes="One BP number is a fiction. What a point may build and where it stands both "
          "matter, and the stream carries no builder position, so the split is stated.")
def cap_pools(ctx: Context, expanding: Optional[int] = None,
              commander: Optional[str] = None, factory_on: Optional[bool] = None,
              assist: Optional[float] = None,
              targets: Sequence[str] = ("Mex", "Wind", "Solar", "BotWorker",
                                        "ConTurret", "EConverter")) -> dict:
    st = ctx.eco_state()
    p = U.split_bp(st.counts,
                   expanding=ctx.expanding if expanding is None else expanding,
                   commander=commander or ctx.commander,
                   factory_on=ctx.factory_on if factory_on is None else factory_on,
                   assist=ctx.assist if assist is None else assist,
                   bp_override=st.bp if st.counts else None)
    out = _clean(p)
    out["legality"] = {u: U.pool_bp_for(u, p) for u in targets if u in U.OBJECTS}
    out["reassign_one_worker"] = _clean(U.reassign_to_expand(p, 1))
    # an empty pool with work pointed at it is the most misleading thing this can
    # return, so it is named rather than left as a zero
    empty = []
    for u, v in out["legality"].items():
        if v["bp"] <= 0:
            empty.append({"target": u, "pool": v["work_pool"],
                          "why": ("the " + v["work_pool"] + " pool has no builder "
                                  "assigned to it under this policy"
                                  + (" (the factory is switched off)"
                                     if v["work_pool"] == "factory" and not p.factory_on
                                     else ""))})
    out["unbuildable"] = empty
    mobile = sum(1 for u, d in p.detail.items()
                 if d.get("mobile") and not d.get("factory"))
    out["note"] = ("expand is empty: " + str(mobile) + " mobile builder type(s) exist and "
                   + str(p.policy.get("expanding", 0)) + " were asked for, commander is "
                   + str(p.policy.get("commander")) if p.expand <= 0 else None)
    return out


@capability(
    "bp_measured", "1.0.0",
    "The build power a recorded game actually applied to each pool's work.",
    "Where did my build power really go?",
    params={"from_sec": "window start", "until_sec": "window end"},
    returns={"bp_applied": "per pool, in build power",
             "share": "per pool, as a fraction",
             "per_unit": "every def built, with the build power it represents",
             "wip_bp_upper": "an upper bound on work still in a nanoframe",
             "vs_engine": "against the engine's own bp_used, the referee",
             "unresolved": "defs with no build time, counted nowhere"},
    needs=("game",), tags=("bp", "measure"),
    notes="Build work is conserved, so completions in a window divided by the window is "
          "the build power that was working. Resolves every engine def, not just the "
          "modelled ones: an unmodelled advanced lab is 25000 BP-seconds.")
def cap_bp_measured(ctx: Context, from_sec: float = 0.0,
                    until_sec: float = 480.0) -> dict:
    d = ctx.data()
    if d is None:
        return {"error": "bp_measured needs a recorded game"}
    return U.bp_delivered(d, from_sec, until_sec, verbose=False)


@capability(
    "next_build", "1.0.0",
    "How long the next one of each candidate takes from this exact position.",
    "How long will it take to build the next X from here?",
    params={"candidates": "which units to price", "bp": "build power to assume",
            "use_pools": "price each candidate with the build power its POOL has"},
    returns={"per_unit": "seconds, the nominal time, the stall inside it, which "
                         "resource bound it, and whether it is affordable with no stall",
             "fastest": "the quickest candidate", "pool_bp": "the BP each pool offered"},
    tags=("core", "primitive"),
    notes="Not bp_cost/bp. That is only right while the economy can pay at that pace. "
          "This walks the phases analytically: full rate while a bank has something in "
          "it, then whatever income alone feeds. Checked against a simulation to 0.018s.")
def cap_next_build(ctx: Context, candidates: Optional[Sequence[str]] = None,
                   bp: Optional[float] = None, use_pools: bool = False) -> dict:
    st = ctx.eco_state()
    cands = list(candidates or ("Mex", "Solar", "Wind", "AdvSolar", "BotWorker",
                                "ConTurret", "EConverter", "EStorage"))
    pools = ctx.pools() if use_pools else None
    per: Dict[str, dict] = {}
    pool_bp: Dict[str, float] = {}
    for u in cands:
        if u not in U.OBJECTS:
            continue
        b = bp
        if use_pools and pools is not None:
            pb = U.pool_bp_for(u, pools)
            b = pb["bp"]
            pool_bp[u] = b
        if b is not None and b <= 0:
            per[u] = {"seconds": None, "bound": "no build power in that pool",
                      "work_pool": U.work_pool(u)}
            continue
        r = U.time_to_build(st, u, b)
        r["work_pool"] = U.work_pool(u)
        r["bp_used"] = b if b is not None else st.bp
        per[u] = r
    live = {u: r for u, r in per.items() if r.get("seconds")}
    fastest = min(live, key=lambda u: live[u]["seconds"]) if live else None
    return {"per_unit": per, "fastest": fastest, "pool_bp": pool_bp or None,
            "bp": bp if bp is not None else st.bp}


@capability(
    "cadence", "1.1.0",
    "Rows of one-copy-per-cell, each cell carrying the seconds THAT copy took, "
    "positioned by accumulated time.",
    "If I keep building this, how far apart do they land, and what does stopping to "
    "buy build power cost me?",
    params={"target": "what to build repeatedly", "scale_source": "what a row invests in",
            "rows": "how many build-power tiers", "items": "copies per row",
            "share": "fraction of build power pointed at this work (1.0 = dedicated)",
            "horizon": "fix the window in seconds instead of counting copies"},
    returns={"rows": "per tier: segments with dt, nominal, stall, bound and phase; "
                     "the crossover where the tier catches tier 0; times to the "
                     "1st/5th/10th/20th copy",
             "bands": "phase boundaries along the time axis"},
    tags=("core", "chart"),
    notes="At share 1.0 this is a DEDICATED figure and an upper bound: it points every "
          "point of build power at one copy at a time. Measured against a real game it "
          "ran 2.4x fast, which is what the three pools explain. Use `share`, or price "
          "the target through its pool with `next_build --use-pools`.")
def cap_cadence(ctx: Context, target: Optional[str] = None,
                scale_source: Optional[str] = None, rows: int = 3,
                items: Optional[int] = 10, share: float = 1.0,
                horizon: Optional[float] = None) -> dict:
    r = U.cadence_table(ctx.eco_state(), target=target or ctx.target,
                        scale_source=scale_source or ctx.bp_source, rows=rows,
                        items=items, horizon=horizon, budget=ctx.budget(),
                        workers=ctx.workers, share=share, verbose=False)
    for row in r["rows"]:
        row.pop("state_end", None)
    return _clean(r)


@capability(
    "path", "1.1.0",
    "The over/cross walk across the grid, and the build ratio it yields.",
    "How many generators per build-power source should I actually be building?",
    params={"target": "what an OVER builds", "bp_source": "what a CROSS buys",
            "on": "the work the metal is for", "objective": "which scorer to use",
            "horizon": "how far to walk", "thresholds": "cross thresholds to sweep",
            "goal": "for fastest_to_goal, e.g. an e_inc target"},
    returns={"ratio": "overs per cross, with a label you can follow",
             "best": "the chosen walk: every over, cross, wait and the exit",
             "runs": "every threshold scored, so the choice is visible",
             "off_chart": "what to build when neither axis is the answer any more"},
    tags=("core", "decision"),
    notes="A cross needs BOTH that income could feed more hands than you own on the "
          "work, and that the source is payable with no stall. Saturation alone would "
          "buy a con turret you cannot afford. The walk waits for workers rather than "
          "quitting, and exits when energy already covers the whole budget.")
def cap_path(ctx: Context, target: Optional[str] = None,
             bp_source: Optional[str] = None, on: Optional[str] = None,
             objective: str = "hold_metal_bound", horizon: float = 600.0,
             thresholds: Sequence[float] = (0.6, 0.8, 1.0),
             goal: Optional[dict] = None) -> dict:
    r = U.path_search(ctx.eco_state(), ctx.budget(), target=target or ctx.target,
                      bp_source=bp_source or ctx.bp_source, on=on or ctx.on,
                      horizon=horizon, objective_name=objective,
                      thresholds=thresholds, goal=goal, workers=ctx.workers,
                      verbose=False)
    best = dict(r["best"])
    best.pop("end", None)
    return {"ratio": r["ratio"], "objective": r["objective"],
            "best": _clean(best),
            "runs": [{k: _clean(v) for k, v in run.items()
                      if k not in ("steps", "end", "claimed")} for run in r["runs"]],
            "objectives_available": sorted(U.PATH_OBJECTIVES)}


@capability(
    "advisor", "1.0.0",
    "Every candidate ranked by how much of this build power it can consume.",
    "My build power is idle. What can actually absorb it?",
    params={"candidates": "which units to rank", "bp": "build power to assume"},
    returns={"advice": "what to build", "why": "the reason in one line",
             "profiles": "per candidate: the m:e ratio, what it needs per second, the "
                         "share of build power it can eat, and what binds it",
             "surplus": "your own metal:energy ratio, to compare against"},
    tags=("decision",),
    notes="Every structure burns metal and energy in a FIXED ratio Mc:Ec, so 'I cannot "
          "spend my build power' is a statement about the target, never the position. "
          "Solar 155:0 is a pure metal sink; a converter is 1:1150, a pure energy sink.")
def cap_advisor(ctx: Context, candidates: Optional[Sequence[str]] = None,
                bp: Optional[float] = None) -> dict:
    a = U.target_advisor(ctx.eco_state(), candidates, bp, verbose=False)
    return _clean(a)


@capability(
    "lattice", "1.0.0",
    "Sweep both scaling sources from here and colour every combination by regime.",
    "If I add N energy and M build power, what becomes the constraint?",
    params={"energy_source": "what a column adds", "bp_source": "what a row adds",
            "on": "the reference work", "n_energy": "columns", "n_bp": "rows"},
    returns={"grid": "regime per cell", "cells": "the incomes and ratios behind each",
             "recommendation": "the single next purchase this position argues for"},
    tags=("chart",))
def cap_lattice(ctx: Context, energy_source: Optional[str] = None,
                bp_source: Optional[str] = None, on: Optional[str] = None,
                n_energy: int = 10, n_bp: int = 7) -> dict:
    r = U.scaling_map(ctx.eco_state(), energy_source=energy_source or ctx.energy_source,
                      bp_source=bp_source or ctx.bp_source, on=on or ctx.on,
                      n_energy=n_energy, n_bp=n_bp, color=False, verbose=False)
    return {"grid": r["grid"], "recommendation": r["recommendation"],
            "energy_source": r["energy_source"], "bp_source": r["bp_source"],
            "on": r["on"],
            "cells": {str(k[0]) + "," + str(k[1]): v for k, v in r["cells"].items()}}


@capability(
    "idle", "1.0.0",
    "Idle build power split into the part the economy could have fed and the part it "
    "could not.",
    "Was my build power idle because I was slow, or because there was nothing to spend?",
    params={"until_sec": "window", "on": "the reference work"},
    returns={"free_share": "idle build power the income could NOT have fed, so walking "
                           "in those windows cost nothing",
             "costly_bps": "idle build power that metal was available for",
             "rows": "per measured sample"},
    needs=("game",), tags=("measure",))
def cap_idle(ctx: Context, until_sec: float = 480.0, on: Optional[str] = None) -> dict:
    d = ctx.data()
    if d is None:
        return {"error": "idle needs a recorded game"}
    r = U.idle_audit(d, until_sec=until_sec, on=on or ctx.on, verbose=False)
    return _clean(r)


@capability(
    "cadence_check", "1.0.0",
    "Hold the predicted cadence against the game it came from.",
    "Does this chart actually match reality?",
    params={"unit": "which unit to check"},
    returns={"recorded": "the real gaps between completions",
             "median_recorded": "their median, parallel finishes excluded",
             "runs": "the prediction at dedicated and at the measured share",
             "ratio": "measured-share prediction over recorded median",
             "ok": "true inside a 0.6-1.6x tolerance"},
    needs=("game",), tags=("validate",),
    notes="The dedicated row is an upper bound by construction and will always look "
          "too fast. What has to hold is the measured-share row.")
def cap_cadence_check(ctx: Context, unit: str = "Wind") -> dict:
    d = ctx.data()
    if d is None:
        return {"error": "cadence_check needs a recorded game"}
    r = U.validate_cadence_vs_replay(d, unit=unit, position=ctx.position, verbose=False)
    return _clean(r)


@capability(
    "roi", "1.0.0",
    "Return on investment per unit, and the correction that matters.",
    "Is this thing worth building, and does more build power pay for itself?",
    params={"units": "which to price", "wind": "wind speed for turbines"},
    returns={"per_unit": "BPROI, EROI and the all-in metal-equivalent price",
             "breakevens": "the three separate generator break-evens"},
    tags=("reference",),
    notes="Nominal BPROI is a lie when income cannot feed the points you bought. "
          "Scale it by effectiveBP/oldBP, not totalBP/oldBP.")
def cap_roi(ctx: Context, units: Optional[Sequence[str]] = None,
            wind: Optional[float] = None) -> dict:
    st = ctx.eco_state()
    w = wind if wind is not None else st.wind
    us = list(units or ("Solar", "Wind", "AdvSolar", "Mex", "BotWorker", "ConTurret",
                        "EConverter"))
    return {"wind": w,
            "per_unit": {u: U.roi_figures(u, w) for u in us if u in U.OBJECTS},
            "breakevens": _clean(U.generator_breakevens())}


@capability(
    "concentration", "1.0.0",
    "Two builders on ONE project against one project each: what the ordering is worth.",
    "Should my workers build together or separately?",
    params={"unit": "what they build", "workers": "how many builders",
            "bp_each": "build power each", "wind": "E/s per turbine",
            "segments": "how many segments of the pattern to show"},
    returns={"pattern": "extra copies STANDING per segment, floor(t/tau) mod n",
             "mean_lead": "(n-1)/2, held forever - two workers are half a copy ahead",
             "troi": "seconds for the copy to repay its whole price at 70:1",
             "ws_per_worker_build": "one worker-build as a fraction of the ROI",
             "rows": "the lead compounded, linear (Euler) against exact exponential",
             "free_unit_after_sec": "when the lead alone has paid for a free copy",
             "stall": "the one way pooling loses - n times the drain per second"},
    tags=("decision", "primitive"),
    notes="Both policies finish the n-th copy at the same instant, so a count at the "
          "end shows nothing. The whole difference is WHEN the earlier copies land, and "
          "an earlier generator generates. Reinvesting at one price per TROI is "
          "exponential by definition; a fixed +1 segment/TROI per step is its Euler "
          "approximation, right to first order and undershooting later.")
def cap_concentration(ctx: Context, unit: Optional[str] = None, workers: int = 2,
                      bp_each: Optional[float] = None, wind: Optional[float] = None,
                      segments: int = 8) -> dict:
    st = None
    try:
        st = ctx.eco_state()
    except ValueError:
        pass
    r = U.concentration_advantage(unit=unit or ctx.target, workers=workers,
                                  bp_each=bp_each, wind=wind, segments=segments,
                                  state=st, verbose=False)
    return _clean(r)


@capability(
    "extractor_rate", "1.0.0",
    "An extractor's energy flow priced as metal at the T1 rate, netted into its m/s.",
    "What is a metal spot actually worth once the extractor's energy is counted?",
    params={"units": "which extractors, model objects or raw engine defs",
            "spot_rates": "reference-spot rates to evaluate on",
            "exchange": "energy per metal, 70 at T1"},
    returns={"per_unit": "raw m/s, the energy flow, that flow as metal, the net rate "
                         "and the percentage it moves",
             "on_spots": "the same on each class of spot, scaled by the extractor's "
                         "own multiplier"},
    tags=("reference", "expand"),
    notes="An Armada extractor burns 3 E/s, a Legion one PRODUCES 7. Net, Legion T1 "
          "goes from 75% of Armada to 82%. Upkeep is per BUILDING and flat, so a poor "
          "spot loses proportionally more of its value to it. Only legitimate where "
          "surplus energy actually converts, which is the scaling phase.")
def cap_extractor_rate(ctx: Context, units: Optional[Sequence[str]] = None,
                       spot_rates: Sequence[float] = (1.825, 3.16),
                       exchange: Optional[float] = None) -> dict:
    us = list(units or ("Mex", "legmex", "AMex", "legmoho"))
    r = U.extractor_rates(units=us, spot_rates=spot_rates,
                          exchange=(exchange if exchange is not None
                                    else U.ENERGY_PER_METAL), verbose=False)
    return {"per_unit": _clean(r), "exchange": exchange or U.ENERGY_PER_METAL}


@capability(
    "catalog", "1.0.0",
    "Every unit and structure, grouped by faction and then by what it is.",
    "What exists in this game, per faction?",
    params={"faction": "Armada, Cortex, Legion, Other, or omit for all"},
    returns={"faction": "kind -> the defs in it, where kind is commander / extractor / "
                        "energy / converter / storage / factory / worker / defence / "
                        "unit / other"},
    needs=(), tags=("reference", "catalog"),
    notes="Faction comes from the defName prefix because BAR leaves customParams.faction "
          "empty on all 844 defs. Role beats economics in the classification: a bot lab "
          "holds 100 metal and a con bot makes 7 E/s, and neither is what it IS.")
def cap_catalog(ctx: Context, faction: Optional[str] = None) -> dict:
    return UC.catalog(faction)


@capability(
    "tiers", "1.0.0",
    "The tier structure, breadth-first from the commander.",
    "What gates what, and in which order does the tech open up?",
    params={"faction": "whose tree to walk"},
    returns={"layers": "per depth: what gates it, the products by kind, the tech levels, "
                       "and which of those products are themselves builders"},
    needs=(), tags=("catalog", "reference"),
    notes="Derived from the engine's own buildOptions, so it is not a rule anyone wrote "
          "down: commander -> mex, solar, wind, T1 factories, storage, converter; "
          "factory -> workers and T1 units; T1 worker -> con turret, advanced solar, T2 "
          "factory; T2 factory -> T2 worker and T2 units; T2 worker -> Moho, fusion, "
          "advanced converter, T3. Rebalance the game and the layers move with it.")
def cap_tiers(ctx: Context, faction: str = "Armada") -> dict:
    return UC.tiers(faction)


@capability(
    "lab", "1.0.0",
    "What one builder can make, and what gates a given product.",
    "What comes out of this lab, and what do I need before I can build that?",
    params={"builder": "a defName, human name or user alias",
            "product": "instead, ask what builds this"},
    returns={"builder": "its products, by kind",
             "product": "every builder that can make it"},
    needs=(), tags=("catalog",),
    notes="Aliases resolve here, so 'air lab', 'nano' and 'moho' work. They live in "
          "bar-calc/unit_aliases.json, hand-edited and never overwritten by a harvest.")
def cap_lab(ctx: Context, builder: Optional[str] = None,
            product: Optional[str] = None) -> dict:
    out: Dict[str, Any] = {}
    if not builder and not product:
        builder = "armlab"
    if builder:
        b = DB.resolve_name(builder) or builder
        rows = UC._rows()
        d = rows.get(b) or {}
        ps = UC.products(b)
        by_kind: Dict[str, List[str]] = {}
        for x in ps:
            if x in rows:
                by_kind.setdefault(rows[x]["kind"], []).append(x)
        out["builder"] = {"def": b, "name": d.get("human_name"),
                          "faction": d.get("faction"), "tech": d.get("tech_level"),
                          "is_factory": bool(d.get("is_factory")),
                          "aliases": d.get("alias_list"),
                          "products": sorted(ps),
                          "by_kind": {k: sorted(v) for k, v in sorted(by_kind.items())}}
    if product:
        pd = DB.resolve_name(product) or product
        out["product"] = {"def": pd, "gated_by": UC.who_builds(pd)}
    return out


@capability(
    "unlocks", "1.0.0",
    "What is buildable right now from what is standing, and what one more builder opens.",
    "Given what I have built, what are my options?",
    params={"have": "defNames, human names or aliases; omit to read the game state",
            "faction": "override the inferred faction"},
    returns={"buildable_now": "everything the standing builders can make, by kind",
             "unlocks": "per candidate builder, how many NEW options it would open",
             "unknown": "names that matched nothing, so an alias is missing"},
    tags=("catalog", "decision"),
    notes="With no `have`, the standing units are read from the recorded position and "
          "mapped through econ_model's objectTypes, so this answers what the player "
          "could actually have built at that moment.")
def cap_unlocks(ctx: Context, have: Optional[Sequence[str]] = None,
                faction: Optional[str] = None) -> dict:
    names = list(have or [])
    if not names:
        try:
            st = ctx.eco_state()
        except ValueError:
            st = None
        if st is not None:
            types = ED.object_types() or {}
            for obj, n in (st.counts or {}).items():
                if n <= 0:
                    continue
                dn = (types.get(obj) or {}).get("defName")
                if dn:
                    names.append(dn)
    if not names:
        return {"error": "nothing standing; pass `have` or use a game Context"}
    return UC.options(names, faction)


@capability(
    "goal", "1.0.0",
    "Time to a stated end state, and where a build-power detour pays for itself.",
    "How long until I have four advanced solars, and should I stop to build hands first?",
    params={"goal": "what to build repeatedly", "count": "how many",
            "bp_source": "the build-power source to consider detouring for",
            "max_sources": "how many to try", "use_pools": "draw on the legal pool only"},
    returns={"baseline_total": "seconds to the goal with no detour",
             "grid": "(sources x insertion point) -> total time, every cell simulated",
             "able_from": "DIMENSION 1: the first insertion point where the source is "
                          "payable with no stall",
             "sensible_until": "DIMENSION 2: the last insertion point that still beats "
                               "the baseline",
             "window": "where both hold. Empty is a real answer",
             "best": "the fastest plan and what it saves"},
    tags=("decision", "chart"),
    notes="The two dimensions move in opposite directions: ABLE switches ON as income "
          "grows, SENSIBLE switches OFF as the goal approaches, so they cross. An empty "
          "window means build straight through. Measured: at 1250 BP on 313 E/s the goal "
          "itself stalls 42 of 45 seconds on energy, so every detour only adds time; at "
          "300 BP on 900 E/s three turrets first cut 159s to 89s.")
def cap_goal(ctx: Context, goal: Optional[str] = None, count: int = 4,
             bp_source: Optional[str] = None, max_sources: int = 3,
             use_pools: bool = False) -> dict:
    r = U.goal_plan(ctx.eco_state(), goal=goal or "AdvSolar", count=count,
                    bp_source=bp_source or ctx.bp_source, max_sources=max_sources,
                    pools=(ctx.pools() if use_pools else None),
                    assign="base", verbose=False)
    g = {}
    for k, d in (r.get("grid") or {}).items():
        for j, cell in d.items():
            if not cell.get("ok"):
                continue
            g[str(k) + "," + str(j)] = {"total": cell["total"],
                                        "src_stalled": cell["src_stalled"],
                                        "goal_stall": cell.get("goal_stall"),
                                        "goal_bound": cell.get("goal_bound"),
                                        "goal_times": cell["goal_times"]}
    return {"goal": r["goal"], "count": r["count"], "bp_source": r["bp_source"],
            "baseline_total": r["baseline_total"], "grid": g,
            "able_from": r["able_from"], "sensible_until": r["sensible_until"],
            "window": r["window"], "best": r["best"],
            "mismatch": _clean(r.get("mismatch"))}


# ══════════════════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════════════════

def _parse_request(req: Union[str, dict]) -> tuple:
    """"cadence", "path:most_economy_at", or {"name":..., "params": {...}}."""
    if isinstance(req, dict):
        return req["name"], dict(req.get("params") or {})
    if ":" in req:
        name, arg = req.split(":", 1)
        cap = CAPABILITIES.get(name)
        if not cap:
            return name, {}
        # the shorthand fills the first declared parameter
        key = next(iter(cap.params), None)
        if name == "path":
            key = "objective"
        elif name in ("idle", "cadence_check"):
            key = "unit" if name == "cadence_check" else "until_sec"
        if key is None:
            return name, {}
        try:
            val: Any = float(arg)
            if val.is_integer() and key not in ("share",):
                val = int(val)
        except ValueError:
            val = arg
        return name, {key: val}
    return req, {}


def run(ctx: Context, requests: Union[str, Sequence[Union[str, dict]]] = "state",
        record: bool = True, db_path: str = DB.DB_PATH) -> dict:
    """Run one or more perspectives on one Context and record each answer."""
    if isinstance(requests, str):
        requests = ["all"] if requests == "all" else [
            r.strip() for r in requests.split(",") if r.strip()]
    names: List[Union[str, dict]] = []
    for r in requests:
        if r == "all":
            names.extend(sorted(CAPABILITIES))
        else:
            names.append(r)
    inputs_base = ctx.describe()
    fh = DB.file_hash(MODEL_FILE)
    out: Dict[str, Any] = {}
    for req in names:
        name, params = _parse_request(req)
        cap = CAPABILITIES.get(name)
        if not cap:
            out[name] = {"error": "no capability named " + name,
                         "available": sorted(CAPABILITIES)}
            continue
        if "game" in cap.needs and ctx.game is None:
            out[name] = {"skipped": name + " needs a recorded game"}
            continue
        payload = {"context": inputs_base, "params": params}
        try:
            res = _clean(cap.fn(ctx, **params))
            ok, err = True, None
        except Exception as exc:                                   # noqa: BLE001
            res = {"error": str(exc), "traceback": traceback.format_exc()[-1200:]}
            ok, err = False, str(exc)
        out[name] = res
        if record:
            try:
                DB.record_run(name, cap.version, "bar_unified.py", U_VERSION(),
                              payload, res, user_name=ctx.user_name,
                              build_name=ctx.build_name, game_id=ctx.game_id(),
                              at_sec=inputs_base.get("at"), ok=ok, error=err,
                              file_path=MODEL_FILE, path=db_path)
            except Exception as exc:                               # noqa: BLE001
                out.setdefault("_record_errors", []).append(str(exc))
    out["_meta"] = {"api_version": VERSION, "model_hash": fh,
                    "context": inputs_base, "recorded": bool(record)}
    return out


def U_VERSION() -> str:
    """The model file's version stamp. It has no __version__, so the hash is it."""
    return getattr(U, "VERSION", None) or DB.file_hash(MODEL_FILE)


def spec() -> dict:
    """The whole surface, machine-readable, always current."""
    return {"api": "bar-calc econ_api", "version": VERSION,
            "model": {"file": "bar-calc/bar_unified.py", "hash": U_VERSION()},
            "database": DB.DB_PATH,
            "context": {
                "state_in": "either `game` (+ `at`) for a recorded position, or `state` "
                            "for a hand-written one",
                "fields": {k: v for k, v in {
                    "game": "game id, 1-based index, or omit",
                    "at": "seconds into the game",
                    "state": "metal, energy, m_inc, e_inc, bp, wind, caps, counts",
                    "position": "tech (7 mex) or front (12 mex)",
                    "mex": "explicit spot count",
                    "standing": "spots already held",
                    "workers": "builders out claiming",
                    "expanding": "mobile workers assigned to the expand pool",
                    "commander": "base or expand",
                    "factory_on": "the factory pool is binary",
                    "assist": "fraction of base lent to the factory",
                    "target": "what an over builds",
                    "bp_source": "what a cross buys",
                    "energy_source": "what a lattice column adds",
                    "on": "the work the metal is for, which sets every threshold",
                    "user_name": "recorded with the answer",
                    "build_name": "recorded with the answer, so builds are searchable",
                }.items()}},
            "objectives": sorted(U.PATH_OBJECTIVES),
            "capabilities": [c.spec() for _, c in sorted(CAPABILITIES.items())]}


def stale(db_path: str = DB.DB_PATH) -> List[dict]:
    """Recorded runs a newer version of their capability supersedes."""
    return DB.stale_runs({n: c.version for n, c in CAPABILITIES.items()}, path=db_path)


def selftest(verbose: bool = True) -> bool:
    """Every capability must run on a real game and on a bare state, and serialise."""
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "econ_api_selftest.db")
    if os.path.exists(tmp):
        os.unlink(tmp)
    DB.ensure_defs(tmp)
    ok = True
    problems: List[str] = []

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            problems.append(msg)

    ctx = Context(game=1, at=60.0, position="front", workers=3, expanding=2,
                  user_name="selftest", build_name="selftest-build")
    res = run(ctx, "all", record=True, db_path=tmp)
    for name, cap in sorted(CAPABILITIES.items()):
        r = res.get(name)
        check(r is not None, name + " produced nothing")
        if isinstance(r, dict) and "error" in r:
            check(False, name + " errored: " + str(r["error"])[:160])
        if isinstance(r, dict) and "skipped" in r:
            check(False, name + " was skipped on a game context")
        try:
            json.dumps(r)
        except (TypeError, ValueError) as exc:
            check(False, name + " does not serialise: " + str(exc)[:120])
        check(bool(cap.summary and cap.question and cap.returns),
              name + " is missing documentation")

    # a bare hand-written state must work for every state-only capability
    bare = Context(state={"m_inc": 9.3, "e_inc": 97, "bp": 610, "metal": 175,
                          "energy": 508, "wind": 13.0,
                          "counts": {"Mex": 5, "BotWorker": 3, "Commander": 1}},
                   at=90.0, position="tech", workers=2)
    res2 = run(bare, "all", record=False, db_path=tmp)
    for name, cap in sorted(CAPABILITIES.items()):
        if "game" in cap.needs:
            check("skipped" in (res2.get(name) or {}),
                  name + " needs a game and should have been skipped")
            continue
        r = res2.get(name) or {}
        check("error" not in r, name + " failed on a hand-written state: "
              + str(r.get("error"))[:160])

    rows = DB.find_runs(build="selftest-build", limit=200, path=tmp)
    check(len(rows) >= len(CAPABILITIES) - 1,
          "expected a recorded row per capability, got " + str(len(rows)))
    st = DB.stale_runs({n: "999" for n in CAPABILITIES}, path=tmp)
    check(len(st) >= 1, "a version bump should mark recorded runs stale")
    sp = spec()
    check(len(sp["capabilities"]) == len(CAPABILITIES), "spec is incomplete")
    json.dumps(sp)
    os.unlink(tmp)
    if verbose:
        if ok:
            print("selftest OK: " + str(len(CAPABILITIES))
                  + " capabilities run on a game and on a bare state, all serialise, "
                  + "all recorded, staleness detected")
        else:
            print("selftest FAILED")
            for pr in problems:
                print("  " + pr)
    return ok


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def _render(name: str, res: Any, quiet: bool = False) -> None:
    """A short human line per capability. `--json` gives the full dict instead."""
    if not isinstance(res, dict):
        print("  " + name + ": " + str(res)[:160])
        return
    if "error" in res:
        print("  " + name.ljust(15) + "ERROR  " + str(res["error"])[:140])
        return
    if "skipped" in res:
        print("  " + name.ljust(15) + "skipped (" + str(res["skipped"]) + ")")
        return
    lines: List[str] = []
    if name == "state":
        q, r = res["quantities"], res["regime"]
        lines.append(("%.2f" % q["m_inc"]) + " M/s  " + ("%.0f" % q["e_inc"])
                     + " E/s  BP " + ("%.0f" % q["bp"]) + "  -> " + res["regime_meaning"])
        lines.append("fix: " + res["regime_fix"])
    elif name == "budget":
        lines.append(str(res["standing"]) + " of " + str(res["count"]) + " held, ROOM "
                     + str(res["room"]) + "   " + ("%.2f" % res["m_per_s_current"])
                     + " -> " + ("%.2f" % res["m_per_s_projected"]) + " m/s")
        rich = res.get("rich_spots") or []
        lines.append("routed walk to claim the rest " + str(res["walk_routed_sec"])
                     + "s   rich spots: "
                     + (", ".join("#" + str(n) for n in rich) if rich
                        else "none in reach, so a flat count happens to agree"))
    elif name == "phases":
        lines.append(res["label"].upper() + ("   CAPPED" if res["capped"] else ""))
        lines.append("energy needs " + ("%.0f" % res["energy"]["e_need_current"])
                     + " E/s now, " + ("%.0f" % res["energy"]["e_need_projected"])
                     + " E/s for the whole budget")
    elif name == "claim":
        lines.append("all " + str(res["spots_remaining"]) + " spots claimed in +"
                     + str(res["expected_complete_sec"]) + "s with "
                     + str(res["workers"]) + " worker(s), adding "
                     + ("%.2f" % res["m_per_s_added"]) + " m/s")
    elif name == "pools":
        lines.append("expand " + ("%.0f" % res["expand"]) + "   factory "
                     + ("%.0f" % res["factory"])
                     + ("" if res["factory_on"] else " (OFF)")
                     + "   base " + ("%.0f" % res["base"])
                     + "   total " + ("%.0f" % res["total"]))
        leg = res.get("legality") or {}
        lines.append("legality: " + ", ".join(
            u + " " + ("%.0f" % v["bp"]) + " (" + v["work_pool"] + ")"
            for u, v in list(leg.items())[:5]))
        if res.get("note"):
            lines.append(str(res["note"]))
        for e in (res.get("unbuildable") or [])[:3]:
            lines.append("cannot build " + e["target"] + ": " + e["why"])
    elif name == "bp_measured":
        a = res["bp_applied"]
        lines.append("expand " + ("%.0f" % a["expand"]) + "   factory "
                     + ("%.0f" % a["factory"]) + "   base " + ("%.0f" % a["base"])
                     + "   total " + ("%.0f" % res["bp_applied_total"]))
        lines.append("engine bp_used " + str(res.get("mean_bp_used")) + " -> "
                     + str(res.get("vs_engine")) + "x, "
                     + str(res.get("vs_engine_with_wip")) + "x with nanoframes")
    elif name == "next_build":
        per = res["per_unit"]
        best = sorted((v["seconds"], u) for u, v in per.items() if v.get("seconds"))
        lines.append("fastest " + str(res["fastest"]))
        for sec, u in best[:5]:
            v = per[u]
            lines.append("  " + u.ljust(11) + ("%7.1f" % sec) + "s  nominal "
                         + ("%.1f" % v["nominal"]) + "s  bound " + str(v["bound"])
                         + ("  affordable" if v.get("affordable") else "  STALLS"))
    elif name == "cadence":
        for r in res["rows"][:4]:
            dts = [sg["dt"] for sg in r["segments"] if sg["kind"] == "target"][:8]
            lines.append("+" + str(r["n_scale"]) + " invest "
                         + ("%.0f" % r["invest_sec"]) + "s  +s "
                         + " ".join(("%.1f" % x) for x in dts))
    elif name == "path":
        lines.append("RATIO  " + res["ratio"]["label"])
        b = res["best"]
        lines.append("objective " + res["objective"] + ": " + str(b.get("score_detail")))
        if b.get("off_chart"):
            lines.append("then off this chart: " + str(b["off_chart"]))
    elif name == "advisor":
        lines.append("build " + str(res["advice"]))
        lines.append(str(res["why"])[:150])
    elif name == "lattice":
        rec = res["recommendation"]
        lines.append("here " + rec["regime"] + " -> build " + rec["build"])
        lines.append("rows " + str(len(res["grid"])) + " x cols "
                     + str(len(res["grid"][0])) + " regimes mapped")
    elif name == "idle":
        lines.append("free share " + ("%.0f" % (res["free_share"] * 100))
                     + "% of idle build power, costly "
                     + ("%.0f" % res["costly_bps"]) + " BP-s = "
                     + ("%.1f" % res["costly_in_units"]) + "x " + str(res["unit"]))
    elif name == "cadence_check":
        lines.append("recorded median " + str(res.get("median_recorded"))
                     + "s   dedicated bound " + str(res.get("dedicated_median")) + "s -> "
                     + ("BOUND HOLDS" if res.get("bound_ok") else "BOUND VIOLATED"))
        lines.append("measured-share figure "
                     + str((res["runs"]["measured"] or {}).get("median"))
                     + "s is circular (the share comes from these gaps), "
                     + "so it is information, not a test")
    elif name == "roi":
        per = res["per_unit"]
        order = sorted(per, key=lambda u: (per[u]["bproi"] is None,
                                           per[u]["eroi"] is None))
        for u in order[:6]:
            v = per[u]
            up = v.get("energy_upkeep") or 0
            lines.append("  " + u.ljust(11)
                         + ("BPROI " + ("%.0f" % v["bproi"]) + "s  " if v["bproi"]
                            else "".ljust(13))
                         + ("EROI " + ("%.0f" % v["eroi"]) + "s  "
                            if v["eroi"] else
                            ("costs 0 energy to erect  " if v["eroi"] == 0
                             else ("upkeep -" + ("%.0f" % up) + " E/s  " if up
                                   else "not a generator  ")))
                         + "all-in " + ("%.0f" % v["total_roi_metal"]) + " metal-eq")
    elif name == "catalog":
        for f, kinds in sorted(res.items()):
            tot = sum(len(v) for v in kinds.values())
            lines.append(f.ljust(9) + str(tot).rjust(4) + " defs   "
                         + ", ".join(k + " " + str(len(v))
                                     for k, v in sorted(kinds.items())))
    elif name == "tiers":
        lines.append("root " + str(res.get("root")) + "   "
                     + str(len(res.get("layers") or [])) + " layers")
        for L in (res.get("layers") or [])[:5]:
            kinds = L.get("by_kind") or {}
            lines.append("  depth " + str(L["depth"]) + "  " + ", ".join(
                k + " " + str(len(v)) for k, v in sorted(kinds.items()))
                + "   gated by " + ", ".join(L["gated_by"][:3]))
    elif name == "lab":
        b = res.get("builder")
        if b:
            lines.append(str(b["def"]) + " " + str(b["name"]) + "  T"
                         + str(b["tech"]) + "  builds " + str(len(b["products"])))
            for k, v in sorted((b.get("by_kind") or {}).items()):
                lines.append("  " + k.ljust(10) + ", ".join(v[:9]))
        pr = res.get("product")
        if pr:
            lines.append(str(pr["def"]) + " is gated by: "
                         + (", ".join(pr["gated_by"]) or "nothing in the tree"))
    elif name == "unlocks":
        lines.append("standing " + ", ".join(res.get("have") or [])[:90])
        lines.append("buildable now " + str(len(res.get("buildable_now") or []))
                     + ": " + ", ".join(k + " " + str(v) for k, v
                                        in sorted((res.get("counts") or {}).items())))
        for u in (res.get("unlocks") or [])[:3]:
            lines.append("  " + u["build"] + " (" + u["kind"] + ") would open +"
                         + str(u["count"]))
        if res.get("unknown"):
            lines.append("unknown names: " + ", ".join(res["unknown"]))
    elif name == "goal":
        lines.append(str(res["count"]) + " x " + str(res["goal"]) + ": baseline "
                     + fmt(res["baseline_total"], 1) + "s")
        b = res.get("best") or {}
        lines.append("best " + str(b.get("sources")) + " x " + str(res["bp_source"])
                     + " after " + str(b.get("after")) + " -> " + fmt(b.get("total"), 1)
                     + "s (" + fmt(b.get("saved"), 1) + "s saved)")
        lines.append("able from j=" + str(res.get("able_from")) + ", sensible until j="
                     + str(res.get("sensible_until")) + ", window "
                     + (str(res["window"]) if res.get("window") else "EMPTY"))
    elif name == "concentration":
        lines.append(str(res["workers"]) + " workers: together one every "
                     + ("%.1f" % res["tau"]) + "s, apart "
                     + str(res["workers"]) + " every " + ("%.1f" % res["t_alone"]) + "s")
        lines.append("lead pattern ["
                     + ", ".join(("+" + str(d)) if d else "0" for d in res["pattern"][:8])
                     + "]  mean +" + ("%.2f" % res["mean_lead"]) + " standing, forever")
        lines.append("TROI " + ("%.0f" % res["troi"]) + "s   WS = 1/"
                     + ("%.1f" % res["segments_per_roi"]) + " per worker-build   "
                     + "a free " + res["unit"] + " every "
                     + ("%.0f" % res["free_unit_after_sec"]) + "s")
        if res.get("stall") and res["stall"].get("pooled_loses"):
            lines.append("BUT pooling stalls here and splitting does not")
    elif name == "extractor_rate":
        for u, v in res["per_unit"].items():
            lines.append("  " + u.ljust(9) + ("%7.3f" % v["raw_m_per_s"]) + " m/s "
                         + ("%+5.0f" % v["energy_flow"]) + " E/s -> net "
                         + ("%7.4f" % v["net_m_per_s"]) + "  ("
                         + ("%+.2f" % v["pct_change"]) + "%, " + v["direction"] + ")")
    else:
        lines.append(", ".join(sorted(k for k in res if not k.startswith("_")))[:150])
    print("  " + name.upper())
    for ln in lines:
        print("    " + ln)


def _cli(argv: Sequence[str]) -> None:
    def opt(flag, default=None, cast=str):
        if flag in argv:
            i = list(argv).index(flag)
            if i + 1 < len(argv):
                return cast(argv[i + 1])
        return default

    if "--selftest" in argv:
        sys.exit(0 if selftest() else 1)
    if "--spec" in argv:
        print(json.dumps(spec(), indent=1))
        return
    if "--stale" in argv:
        rows = stale()
        if not rows:
            print("nothing stale")
            return
        for r in rows:
            print("  " + str(r["function"]).ljust(16) + "recorded "
                  + str(r["recorded"]).ljust(9) + "current "
                  + str(r["current"] or "-").ljust(9) + str(r["runs"]).rjust(5)
                  + " runs  " + r["status"])
        return
    if "--list" in argv:
        print("CAPABILITIES  (" + str(len(CAPABILITIES)) + ")   state in -> dict out")
        for n, c in sorted(CAPABILITIES.items()):
            print()
            print("  " + n + "  v" + c.version
                  + ("   [needs a game]" if "game" in c.needs else "")
                  + ("   tags: " + ",".join(c.tags) if c.tags else ""))
            print("    Q: " + c.question)
            print("    " + c.summary)
            if c.params:
                print("    params: " + ", ".join(sorted(c.params)))
        return

    DB.ensure_defs()
    st = opt("--state")
    ctx = Context(
        game=(None if st else opt("--game", 1)),
        at=opt("--at", 60.0, float),
        state=(json.loads(st) if st else None),
        position=opt("--position", "front"),
        mex=opt("--mex", None, int),
        team=opt("--team", None, int),
        map_name=opt("--map", None),
        standing=opt("--standing", None, int),
        workers=opt("--workers", 3, int),
        expanding=opt("--expanding", 2, int),
        commander=opt("--commander", "base"),
        factory_on=("--factory-off" not in argv),
        assist=opt("--assist", 0.0, float),
        target=opt("--target", "Wind"),
        bp_source=opt("--bpsrc", "ConTurret"),
        energy_source=opt("--energy", "Solar"),
        on=opt("--on", "Mex"),
        user_name=opt("--name"),
        build_name=opt("--build"))
    req = opt("--run", "state")
    res = run(ctx, req, record=("--no-record" not in argv))
    if "--json" in argv:
        print(json.dumps(res, indent=1))
        return
    meta = res.pop("_meta", {})
    c = meta.get("context", {})
    print("ECON API v" + VERSION + "   model " + str(meta.get("model_hash")))
    print("  state in: " + str(c.get("source")) + " " + str(c.get("game") or "")
          + " at " + str(c.get("at")) + "s"
          + "   position " + str((c.get("frame") or {}).get("position"))
          + "   workers " + str((c.get("policy") or {}).get("workers")))
    if ctx.build_name or ctx.user_name:
        print("  recorded as: " + str(ctx.user_name or "-") + " / build "
              + str(ctx.build_name or "-"))
    print()
    for name in [k for k in res if not k.startswith("_")]:
        _render(name, res[name])
    if res.get("_record_errors"):
        print()
        print("  record errors: " + "; ".join(res["_record_errors"][:3]))


if __name__ == "__main__":
    _cli(sys.argv[1:])

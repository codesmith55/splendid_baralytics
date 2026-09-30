"""
Run every branch through eco_simulator and emit `builds.json` for the
dashboard.  The JSON is intentionally compact — one record per branch with:
  - the queue
  - per-event entries (asset completion, stall starts, break-even moment)
  - a sparse per-second resource trace for the chart
  - a final asset summary
The dashboard reads this file directly with fetch().
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

import build_db
import eco_simulator as eng

# Patch up rules the CSV doesn't fully populate, and register the T2 chain
# the engine fallback rules don't yet know about.
if "con_turret" in eng.GAME_RULES:
    eng.GAME_RULES["con_turret"]["bp_out"] = 200

# T2 chain — Armada values from Combined_Bar_Stats.csv + worker_analysis.py.
eng.GAME_RULES["t2_lab"] = {
    "name": "Advanced Bot Lab", "m_cost": 2900, "e_cost": 15000,
    "bp_cost": 16224, "m_out": 0.0, "e_out": 0.0, "bp_out": 600,
}
eng.GAME_RULES["t2_con"] = {
    "name": "Advanced Construction Bot", "m_cost": 430, "e_cost": 6900,
    "bp_cost": 9500, "m_out": 0.0, "e_out": 14.0, "bp_out": 210,
}
eng.GAME_RULES["t2_mex"] = {
    "name": "Advanced Metal Extractor", "m_cost": 620, "e_cost": 7700,
    "bp_cost": 14938, "m_out": 7.4, "e_out": -20.0, "bp_out": 0,
}
eng.SHORT_KEY_MAP["t2_lab"] = "Advanced Bot Lab"
eng.SHORT_KEY_MAP["t2_con"] = "Advanced Construction Bot"
eng.SHORT_KEY_MAP["t2_mex"] = "Advanced Metal Extractor"
eng.ABBREV["t2_lab"]  = "T2 Lab"
eng.ABBREV["t2_con"]  = "T2 Con"
eng.ABBREV["t2_mex"]  = "T2 Mex"
eng.FACTORY_PRODUCTS.add("t2_con")     # T2 cons are factory-built


WORKSPACE_JSON = os.path.join(os.path.dirname(__file__), "builds.json")
SIM_HORIZON_S = 180.0     # seconds to simulate each branch
TRACE_EVERY_S = 1.0       # sparse sample for the resource chart


def simulate_branch(queue, target_time: float = SIM_HORIZON_S) -> Dict:
    init = eng.make_initial_state({
        "time": 3.0, "metal": 1000.0, "energy": 1000.0,
        "m_cap": 1300.0, "e_cap": 1450.0,
        "has_commander": True, "assets": {},
    })
    engine = eng.BuildPowerEngine(time_step=0.1)
    engine.simulate("run", init, queue, target_time=target_time)
    records = engine.ledger["run"]

    events = []         # asset completions + stall transitions
    trace = []          # sparse per-second snapshot for the chart
    last_trace_t = -1e9
    prev_m_stall = False
    prev_e_stall = False
    assets_running: Dict[str, int] = {}
    # Break-even = sustained positive net income while construction is
    # active.  A single positive tick during a handoff is not break-even —
    # we require N consecutive ticks of (no stall AND net > 0 AND something
    # is being built).  At 0.1s/tick a 4s window = 40 ticks.
    breakeven_t = None
    streak = 0
    REQUIRED_STREAK_TICKS = 40

    for r in records:
        # 1) Asset completion events
        if r.event != "-":
            # Map abbrev back to key — we read it off the rule store.
            for k, v in eng.ABBREV.items():
                if v == r.event:
                    assets_running[k] = assets_running.get(k, 0) + 1
                    events.append({
                        "t": round(r.t, 2),
                        "kind": "complete",
                        "item": k,
                        "label": v,
                        "assets": dict(assets_running),
                        "metal": round(r.metal, 1),
                        "energy": round(r.energy, 1),
                    })
                    break

        # 2) Stall edge events
        if r.m_stalled and not prev_m_stall:
            events.append({"t": round(r.t, 2), "kind": "m_stall_on"})
        elif prev_m_stall and not r.m_stalled:
            events.append({"t": round(r.t, 2), "kind": "m_stall_off"})
        if r.e_stalled and not prev_e_stall:
            events.append({"t": round(r.t, 2), "kind": "e_stall_on"})
        elif prev_e_stall and not r.e_stalled:
            events.append({"t": round(r.t, 2), "kind": "e_stall_off"})
        prev_m_stall = r.m_stalled
        prev_e_stall = r.e_stalled

        # 3) Break-even: sustained positive net income while construction
        # is actively spending.  Requires a streak so we ignore the
        # one-tick blip during handoffs.
        net_m = r.m_inc - r.m_drain
        net_e = r.e_inc - r.e_drain
        actively_building = r.m_drain > 0 or r.e_drain > 0
        if (not r.m_stalled and not r.e_stalled
                and net_m > 0 and net_e > 0 and actively_building):
            streak += 1
            if streak >= REQUIRED_STREAK_TICKS and breakeven_t is None:
                # Mark the *start* of the qualifying streak, not its end.
                breakeven_t = round(r.t - REQUIRED_STREAK_TICKS * 0.1, 2)
        else:
            streak = 0

        # 4) Sparse trace
        if r.t - last_trace_t >= TRACE_EVERY_S - 1e-6:
            trace.append({
                "t": round(r.t, 2),
                "m": round(r.metal, 1),
                "e": round(r.energy, 1),
                "m_inc": round(r.m_inc, 2),
                "e_inc": round(r.e_inc, 2),
                "m_drain": round(r.m_drain, 2),
                "e_drain": round(r.e_drain, 2),
                "stall": ("M" if r.m_stalled else "") + ("E" if r.e_stalled else ""),
            })
            last_trace_t = r.t

    return {
        "events": events,
        "trace": trace,
        "final_assets": assets_running,
        "breakeven_t": breakeven_t,
        "horizon": target_time,
    }


def target_first_met_t(events: List[Dict], composition: Dict[str, int]) -> float | None:
    """Return the earliest event-time at which the running asset map meets
    or exceeds every key in `composition`."""
    for ev in events:
        if ev.get("kind") != "complete":
            continue
        assets = ev["assets"]
        if all(assets.get(k, 0) >= v for k, v in composition.items()):
            return ev["t"]
    return None


def main() -> None:
    conn = build_db.connect()
    builds = build_db.list_builds(conn)
    targets = build_db.list_targets(conn)

    out_builds = []
    for b in builds:
        branches = build_db.list_branches(conn, b["id"])
        out_branches = []
        for br in branches:
            queue = build_db.branch_queue(conn, br["id"])
            sim = simulate_branch(queue)
            # Per-target first-met
            target_hits = {}
            for t in targets:
                target_hits[t["name"]] = target_first_met_t(sim["events"], t["composition"])
            out_branches.append({
                "id":            br["id"],
                "label":         br["label"],
                "parent_id":     br["parent_id"],
                "fork_at_step":  br["fork_at_step"],
                "queue":         [{"step": i, "item": k, "mode": m}
                                  for i, (k, m) in enumerate(queue)],
                "events":        sim["events"],
                "trace":         sim["trace"],
                "final_assets":  sim["final_assets"],
                "breakeven_t":   sim["breakeven_t"],
                "target_hits":   target_hits,
                "horizon":       sim["horizon"],
            })
        out_builds.append({
            "id":          b["id"],
            "name":        b["name"],
            "description": b["description"],
            "branches":    out_branches,
        })

    snapshot = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "horizon_s":    SIM_HORIZON_S,
        "rules":        {k: v for k, v in eng.GAME_RULES.items() if not k.startswith("_")},
        "abbrev":       eng.ABBREV,
        "factory_products": list(eng.FACTORY_PRODUCTS),
        "targets":      targets,
        "builds":       out_builds,
    }

    with open(WORKSPACE_JSON, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=1)
    size_kb = os.path.getsize(WORKSPACE_JSON) / 1024
    print(f"Wrote {WORKSPACE_JSON} ({size_kb:.1f} KB)")
    print(f"  {len(out_builds)} builds, "
          f"{sum(len(b['branches']) for b in out_builds)} branches, "
          f"{len(targets)} targets")
    for b in out_builds:
        for br in b["branches"]:
            be = br["breakeven_t"]
            be_str = f"break-even @ {be:.1f}s" if be is not None else "never breaks even"
            print(f"  {b['name']:<14}/{br['label']:<14}  {be_str}")


if __name__ == "__main__":
    main()
            be = br["breakeven_t"]
            be_str = f"break-even @ {be:.1f}s" if be is not None else "never breaks even"
            print(f"  {b['name']:<18}/{br['label']:<14}  {be_str}")


if __name__ == "__main__":
    main()

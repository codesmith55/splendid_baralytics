"""barbots/decider/profiles.py — playstyle profiles: priority weighting over actions.

Same game state + same candidate list (positions/navigator.step_options),
different weighting → different build orders → different bot personalities.

A profile is data, not code:
    bias          {action_id: multiplier} — >1 makes an action MORE attractive
                  (candidate score = roi_s / bias, lower score wins)
    energy_floor  reject actions whose resulting e_net falls below this
    bank_target   metal we're willing to sit on; above it, prefer expensive
                  actions (spend-down pressure)
    horizon_bias  patience: >1 rewards long-payback builds (greed/tech),
                  <1 punishes them (tempo)
    energy_relax  penalty on energy builds while energy is NOT gating a
                  metal build (1.0 = always happy to overbuild energy)

Add a playstyle = add a dict entry. Nothing else changes.
"""
from __future__ import annotations

PROFILES: dict[str, dict] = {

    "balanced": {
        "desc": "Take the best ROI on the board, keep a small energy buffer.",
        "bias": {},
        "energy_floor": 5.0,
        "bank_target": 300.0,
        "horizon_bias": 1.0,
        "energy_relax": 4.0,
    },

    "greedy_expand": {
        "desc": "Metal above all — mex first, upgrades early, energy only when starved.",
        "bias": {"leg_mex": 1.6, "leg_medmex": 1.35, "upgrade_med_moho": 1.3,
                 "upgrade_t1_moho": 1.2, "solar": 0.75, "wind": 0.75},
        "energy_floor": -5.0,          # tolerates brief stalls
        "bank_target": 150.0,
        "horizon_bias": 1.25,
        "energy_relax": 5.0,
    },

    "energy_first": {
        "desc": "Overbuild energy, never stall, convert surplus later.",
        "bias": {"wind": 1.5, "solar": 1.4, "leg_medmex": 0.85},
        "energy_floor": 25.0,
        "bank_target": 350.0,
        "horizon_bias": 0.9,
        "energy_relax": 1.15,
    },

    "tech_rush": {
        "desc": "Shortest path to T2 wealth — medmex/moho ladder over width.",
        "bias": {"leg_medmex": 1.5, "upgrade_med_moho": 1.6, "upgrade_t1_moho": 1.4,
                 "leg_mex": 0.9},
        "energy_floor": 0.0,
        "bank_target": 500.0,          # banks toward big-ticket upgrades
        "horizon_bias": 1.4,
        "energy_relax": 4.0,
    },

    "tempo": {
        "desc": "Fast-payback builds only; cash stays deployed, nothing banks.",
        "bias": {"wind": 1.2, "leg_mex": 1.2},
        "energy_floor": 10.0,
        "bank_target": 100.0,
        "horizon_bias": 0.7,
        "energy_relax": 3.0,
    },
}

DEFAULT_PROFILE = "balanced"


def get_profile(name: str) -> dict:
    p = PROFILES.get(name)
    if p is None:
        raise KeyError(f"unknown profile {name!r}; available: {list(PROFILES)}")
    return {"name": name, **p}

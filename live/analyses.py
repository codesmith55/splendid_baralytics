#!/usr/bin/env python3
"""analyses.py — registry of independent, source-agnostic game-analysis functions.

Each analysis is a PURE function  fn(game, **params) -> dict  where `game` is any object
exposing the read API a replayed BAR game provides (the live server's Live, OR a Live
produced by replaying a saved/archived JSONL):
    game.minutes()            -> [int]            recallable game-minutes
    game.recall(minute)       -> snapshot | None  full per-team state at minute N
    game.snapshot()           -> snapshot         current/last state
    game.shares_named()       -> [flow]           donation/overflow X>Y
    game.build_log            -> {teamID: [{frame,defID,defName}]}
    game.unit_defs            -> {defID: meta}
    game.wind, game.teams

The SAME function therefore runs unchanged on a live game, a recalled minute, or a
DB-archived game replayed from disk. REGISTRY + run() compose them; the server
(POST /api/run) and replay_jsonl.py (--run) are thin front-ends over this one registry.
"""
from __future__ import annotations
import os, sys

_POS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "positions"))
if _POS not in sys.path:
    sys.path.insert(0, _POS)
try:
    from state_api import state_from_dict, state_to_dict     # noqa: E402
    from navigator import step_options                        # noqa: E402
    _ANALYSIS_AVAILABLE = True
except ImportError as _e:
    _ANALYSIS_AVAILABLE = False
    print(f"[analyses] eco projection unavailable: {_e}")

from build_classifier import classify_build, first_t2_frame   # noqa: E402


# ── shared per-team state extraction ────────────────────────────────────────────
def team_state(team_id, snap):
    """Extract one team from a snapshot as an eco-engine state dict (state_api format)."""
    t = next((x for x in snap.get("teams", []) if x.get("teamID") == team_id), None)
    if not t:
        return {}
    return {
        "t":         snap.get("gameSeconds", 0),
        "wind_e":    snap.get("wind") or 10.0,
        "m_inc":     t.get("metalIncome", 0),
        "e_net":     t.get("energyIncome", 0),
        "metal":     t.get("metalCurrent", 0),
        "energy":    t.get("energyCurrent", 0),
        "e_cap":     t.get("energyStorage", 200),
        "bp":        t.get("bpAvail", 300),
        "n_mex":     t.get("nMex", 0),
        "n_workers": t.get("nConv", 0),
    }


# ── minute-to-minute compare ────────────────────────────────────────────────────
COMPARE_FIELDS = [
    "total", "totalPlayerValue", "metalIncome", "energyIncome",
    "metalCurrent", "energyCurrent", "nMex", "bpAvail", "bpUsed",
    "nUnitsCompleted", "constructionValue", "storageValue",
]


def compare_minutes(a, b):
    """Per-team delta between two recalled minute snapshots (a -> b)."""
    ta = {t["teamID"]: t for t in a.get("teams", [])}
    tb = {t["teamID"]: t for t in b.get("teams", [])}
    rows = []
    for tid in sorted(set(ta) | set(tb)):
        x, y = ta.get(tid, {}), tb.get(tid, {})
        base = y or x
        delta = {f: round((y.get(f, 0) or 0) - (x.get(f, 0) or 0), 1) for f in COMPARE_FIELDS}
        bx, by = x.get("buckets", {}), y.get("buckets", {})
        bdelta = {k: round((by.get(k, 0) or 0) - (bx.get(k, 0) or 0), 1) for k in set(bx) | set(by)}
        rows.append({
            "teamID": tid, "name": base.get("name", str(tid)),
            "side": base.get("side", ""), "allyTeamID": base.get("allyTeamID", 0),
            "from":  {f: round(x.get(f, 0) or 0, 1) for f in COMPARE_FIELDS},
            "to":    {f: round(y.get(f, 0) or 0, 1) for f in COMPARE_FIELDS},
            "delta": delta, "bucketDelta": bdelta,
        })
    return {"fromMinute": a.get("minute"), "toMinute": b.get("minute"), "teams": rows}


# ── eco projection vs actual ────────────────────────────────────────────────────
def project_team(sn, snp1, horizon=60.0):
    """Project a team's eco state at minute N forward and grade it against actual N+1."""
    s   = state_from_dict(sn)
    nxt = state_from_dict(snp1)
    best = []
    try:
        for o in step_options(sn, wind_e=s.wind_e)[:3]:
            r = o["roi"]
            best.append({
                "action": o["action_id"], "label": r["label"], "roi_s": r["roi_s"],
                "net_metal": r["net_metal"], "income_gain": r["income_gain"],
                "e_delta": r["e_delta"], "build_wall_s": r["build_wall_s"],
            })
    except Exception as e:
        best = [{"error": str(e)}]

    passive = s.copy(); passive.tick(horizon); pas = state_to_dict(passive)
    delta = {
        "m_inc": round(nxt.m_inc - s.m_inc, 3),
        "e_net": round(nxt.e_net - s.e_net, 1),
        "n_mex": nxt.n_mex - s.n_mex,
        "metal": round(nxt.metal - s.metal, 1),
    }
    metal_deployed = round(pas["metal"] - nxt.metal, 1)
    flags = []
    if pas["metal"] >= 1999 and nxt.metal >= 1999:
        flags.append("metal_overflow")
    if delta["m_inc"] > 0.05:
        flags.append("eco_growth")
    elif metal_deployed >= 50:
        flags.append("spent_non_eco")
    else:
        flags.append("idle")
    return {
        "stateN": state_to_dict(s), "bestOptions": best,
        "passiveNext": {"metal": pas["metal"], "energy": pas["energy"],
                        "generatedMetal": pas["m_gen"]},
        "actualNext": state_to_dict(nxt), "delta": delta,
        "metalDeployedVsPassive": metal_deployed, "flags": flags,
    }


# ── registry wrappers: every analysis is fn(game, **params) -> dict ─────────────
def _minutes(game):
    return {"minutes": game.minutes()}

def _recall(game, minute=0):
    s = game.recall(int(minute))
    return s if s else {"error": f"no snapshot at minute {minute}", "available": game.minutes()}

def _compare(game, minute=0):
    n = int(minute); a, b = game.recall(n), game.recall(n + 1)
    if not a or not b:
        return {"error": f"need minute {n} and {n+1}", "available": game.minutes()}
    return compare_minutes(a, b)

def _project(game, minute=0):
    if not _ANALYSIS_AVAILABLE:
        return {"error": "eco projection unavailable (positions/ import failed)"}
    n = int(minute); a, b = game.recall(n), game.recall(n + 1)
    if not a or not b:
        return {"error": f"need minute {n} and {n+1}", "available": game.minutes()}
    teams = []
    for t in a.get("teams", []):
        tid = t["teamID"]; snd = team_state(tid, a); snp1 = team_state(tid, b)
        if not snd or not snp1:
            continue
        try:
            pr = project_team(snd, snp1)
        except Exception as e:
            pr = {"error": str(e)}
        pr["teamID"], pr["name"] = tid, t.get("name", str(tid))
        teams.append(pr)
    return {"fromMinute": n, "toMinute": n + 1, "horizonSec": 60, "teams": teams}

def _build(game, team=None):
    defs, wind, metas = game.unit_defs, (game.wind or 12.0), game.teams
    # per-allyteam first-T2 frame ends each team's phase 2. Authoritative source = the
    # widget's t2_reached poll (game.t2_frame); fall back to the build log for allyteams
    # without an event (old recordings, or before the poll fired).
    ally_t2 = dict(getattr(game, "t2_frame", {}) or {})
    for tid, log in game.build_log.items():
        ally = metas.get(tid, {}).get("allyTeamID", 0)
        if ally in ally_t2:
            continue
        f = first_t2_frame(log, defs)
        if f is not None:
            ally_t2[ally] = min(ally_t2.get(ally, f), f)
    out = []
    for tid, log in sorted(game.build_log.items()):
        if team is not None and str(tid) != str(team):
            continue
        ally = metas.get(tid, {}).get("allyTeamID", 0)
        try:
            r = classify_build(log, defs, wind_e=wind, t2_frame=ally_t2.get(ally))
        except Exception as e:
            r = {"error": str(e)}
        r["teamID"], r["name"], r["allyTeamID"] = tid, metas.get(tid, {}).get("name", str(tid)), ally
        out.append(r)
    return {"teams": out, "allyT2Frame": {str(k): v for k, v in ally_t2.items()}}

def _shares(game):
    return {"shares": game.shares_named()}


REGISTRY = {
    "minutes": {"fn": _minutes, "params": [],         "desc": "recallable game-minutes"},
    "recall":  {"fn": _recall,  "params": ["minute"], "desc": "full per-team state at minute N"},
    "compare": {"fn": _compare, "params": ["minute"], "desc": "per-team delta minute N -> N+1"},
    "project": {"fn": _project, "params": ["minute"], "desc": "eco projection from N, graded vs actual N+1"},
    "build":   {"fn": _build,   "params": ["team?"],  "desc": "opening build cadence + phase2 + bp split (ARM/COR/Legion)"},
    "shares":  {"fn": _shares,  "params": [],         "desc": "energy/metal donation+overflow flows X>Y"},
}


def _parse_request(req):
    """'project:7' | 'build' | {'name':'project','params':{'minute':7}} -> (name, params)."""
    if isinstance(req, dict):
        return req.get("name"), dict(req.get("params", {}))
    s = str(req)
    if ":" in s:
        name, val = s.split(":", 1)
        p = REGISTRY.get(name, {}).get("params", [])
        key = (p[0].rstrip("?") if p else "minute")
        return name, {key: val}
    return s, {}


def run(game, requests):
    """Run a SET of analyses on one game. requests: list of str/dict. -> {name: result}."""
    out = {}
    for req in requests:
        name, params = _parse_request(req)
        spec = REGISTRY.get(name)
        if not spec:
            out[name or "?"] = {"error": f"unknown analysis '{name}'", "available": list(REGISTRY)}
            continue
        try:
            out[name] = spec["fn"](game, **params)
        except TypeError as e:
            out[name] = {"error": f"bad params for {name}: {e}"}
        except Exception as e:
            out[name] = {"error": str(e)}
    return out

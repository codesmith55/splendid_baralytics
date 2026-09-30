#!/usr/bin/env python3
"""barbots/decider/decider.py — the Decider: game state → next reasonable choice.

Pure pipeline, every stage reused from existing tooling:

    /api/state snapshot ──analyses.team_state──▶ eco state dict
        ──navigator.step_options──▶ ROI-ranked candidate actions
        ──profiles weighting──▶ chosen action  ──▶ intent

An intent is what flows to the adapter (which turns it into keyboard/mouse
transcripts). It names WHAT to do, never how:

    {"type": "build", "action_id": "wind", "label": "...", "team": 3,
     "t": 312.4, "profile": "energy_first", "score": 41.2,
     "roi_s": 49.4, "considered": 5}

CLI (offline first — no BAR needed):
    python decider.py --game <jsonl|archive-id|1> [--minute N] [--team N] [--profile P]
    python decider.py --game 1 --all-profiles      # same state, every playstyle
    python decider.py --live [--loop SECS]         # against the running server
"""
from __future__ import annotations
import argparse, json, math, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (os.path.join(REPO, "positions"), os.path.join(REPO, "live"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from analyses import team_state                      # noqa: E402  (live/)
from navigator import step_options                    # noqa: E402  (positions/)
from profiles import PROFILES, DEFAULT_PROFILE, get_profile  # noqa: E402


# ── core decision function ─────────────────────────────────────────────────
def decide(snap: dict, team_id: int, profile: str | dict = DEFAULT_PROFILE,
           mex_cap: int = 7) -> dict:
    """One decision for one team from one snapshot. Pure: dict in, dict out.

    mex_cap — spots the team can still claim (the eco model has no map, so
    unlimited leg_mex would dominate forever; navigator's own strategies gate
    at 7). Wire real map data here when a position source exists.
    """
    prof = get_profile(profile) if isinstance(profile, str) else profile
    st = team_state(team_id, snap)
    if not st:
        return {"type": "none", "reason": f"team {team_id} not in snapshot"}

    try:
        cands = step_options(st, wind_e=st.get("wind_e"))
    except Exception as e:
        return {"type": "none", "reason": f"step_options failed: {e}", "state": st}
    if st.get("n_mex", 0) >= mex_cap:
        cands = [c for c in cands if c["action_id"] != "leg_mex"]
    if not cands:
        return {"type": "wait", "reason": "no available actions", "state": st}

    # pass 1: income builds; note whether the energy floor blocked any of them
    scored, energy_cands, blocked_by_energy = [], [], False
    for c in cands:
        rs = c.get("resulting_state", {})
        is_energy = c["action_id"] in ("wind", "solar")
        if rs.get("e_net", 0) < prof["energy_floor"]:
            blocked_by_energy = blocked_by_energy or not is_energy
            continue
        if is_energy:
            energy_cands.append(c)
            continue
        scored.append((_score(c, c["roi"]["roi_s"], st, prof), c))

    # pass 2: energy builds compete on metal-per-E/s, but only urgently when
    # energy actually gates a metal build (otherwise relaxed = deprioritized)
    for c in energy_cands:
        e_gain = c["roi"].get("e_delta") or 0
        if e_gain <= 0:
            continue
        r_s = 12.0 * c["roi"].get("net_metal", 0) / e_gain
        if not blocked_by_energy:
            r_s *= prof.get("energy_relax", 4.0)
        scored.append((_score(c, r_s, st, prof), c))

    if not scored:
        # every candidate violated the energy floor → energy is the emergency
        energy = [c for c in cands if c["action_id"] in ("wind", "solar")]
        pick = min(energy, key=lambda c: c["roi"]["roi_s"]) if energy else cands[0]
        return _intent(pick, st, prof, score=-1.0, considered=len(cands),
                       note="energy_floor override")

    score, pick = min(scored, key=lambda x: x[0])
    return _intent(pick, st, prof, score=score, considered=len(cands))


def _score(cand, r_s, st, prof):
    """Lower wins. Bias>1 always improves rank; patience shapes long paybacks."""
    if r_s > 120:
        r_s /= prof["horizon_bias"]     # patience >1 rewards long payback, <1 punishes
    bias = prof["bias"].get(cand["action_id"], 1.0)
    score = r_s / bias if r_s >= 0 else r_s * bias
    # spend-down pressure: sitting above bank_target discounts expensive builds
    if st.get("metal", 0) > prof["bank_target"] and \
            cand["roi"].get("net_metal", 0) > 100 and score >= 0:
        score *= 0.85
    return score


def _intent(cand, st, prof, score, considered, note=""):
    out = {
        "type": "build",
        "action_id": cand["action_id"],
        "label": cand["roi"]["label"],
        "roi_s": cand["roi"]["roi_s"],
        "build_wall_s": cand.get("build_wall_s"),
        "score": round(score, 2),
        "considered": considered,
        "profile": prof["name"],
        "t": st.get("t"),
        "state": {k: st.get(k) for k in ("m_inc", "e_net", "metal", "n_mex", "bp")},
    }
    if note:
        out["note"] = note
    if cand.get("notables"):
        out["notables"] = [n.get("label") for n in cand["notables"]]
    return out


def decide_all_teams(snap: dict, profile=DEFAULT_PROFILE) -> dict:
    """Intent per living team — the spectator/analysis view."""
    out = {}
    for t in snap.get("teams", []):
        if t.get("dead"):
            continue
        d = decide(snap, t["teamID"], profile)
        d["team"] = t["teamID"]
        d["name"] = t.get("name", "")
        out[t["teamID"]] = d
    return out


# ── snapshot sources ───────────────────────────────────────────────────────
def snapshot_from_live(server="http://localhost:8787"):
    with urllib.request.urlopen(f"{server}/api/state", timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def snapshot_from_game(source, minute=None):
    from bar_analytic_server import load_game        # live/ already on path
    game = load_game(source)
    if minute is not None:
        snap = game.recall(int(minute))
        if snap is None:
            raise SystemExit(f"minute {minute} not recallable; have {game.minutes()}")
        return snap
    return game.snapshot()


# ── CLI ────────────────────────────────────────────────────────────────────
def _print_intent(d):
    if d.get("type") != "build":
        print(f"  {d.get('type')}: {d.get('reason', '')}")
        return
    n = f"  ← {', '.join(d['notables'])}" if d.get("notables") else ""
    note = f"  [{d['note']}]" if d.get("note") else ""
    print(f"  [{d['profile']:<14}] {d['action_id']:<18} score {d['score']:>7.1f}  "
          f"ROI {d['roi_s']:>6.1f}s{note}{n}")


def main():
    ap = argparse.ArgumentParser(description="BAR decider — state → intent")
    ap.add_argument("--game", default=None, help="jsonl path, archive id, or 1-based index")
    ap.add_argument("--minute", type=int, default=None)
    ap.add_argument("--live", action="store_true", help="poll the running analytics server")
    ap.add_argument("--server", default="http://localhost:8787")
    ap.add_argument("--team", type=int, default=None)
    ap.add_argument("--profile", default=DEFAULT_PROFILE)
    ap.add_argument("--all-profiles", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    snap = snapshot_from_live(a.server) if a.live else snapshot_from_game(a.game or 1, a.minute)
    gs = snap.get("gameSeconds", 0)
    print(f"snapshot t={int(gs)//60}:{int(gs)%60:02d}  "
          f"teams={[t['teamID'] for t in snap.get('teams', [])]}")

    teams = [a.team] if a.team is not None else \
            [t["teamID"] for t in snap.get("teams", []) if not t.get("dead")]
    profs = list(PROFILES) if a.all_profiles else [a.profile]

    results = {}
    for tid in teams:
        name = next((t.get("name", "") for t in snap.get("teams", [])
                     if t.get("teamID") == tid), "")
        print(f"\nteam {tid} {name}")
        results[tid] = {}
        for pn in profs:
            d = decide(snap, tid, pn)
            results[tid][pn] = d
            if not a.json:
                _print_intent(d)
    if a.json:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

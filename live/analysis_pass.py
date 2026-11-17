#!/usr/bin/env python3
"""analysis_pass.py — full-game analysis pass: metrics table + own conclusions.

One pass over a game (archived JSONL, replayed stream, or the LIVE game — the
same `game` read API everywhere) produces:

  table        tabular JSON: one row per (minute, team) with every computed
               metric point — economy, flows, balance scores, rule flags —
               recallable later without replaying anything
  conclusions  the pass's own general understanding: per-team playstyle reads,
               traits, trade efficiency, imbalance episodes; game-level lead
               changes, verdicts

Saved to live/passes/<game_id>.json. The server runs a pass automatically at
game end; on the live game it computes on demand (GET /api/pass or the `pass`
registry analysis via POST /api/run / replay_jsonl.py --run pass).

CLI:
    python analysis_pass.py run <game|1|live-jsonl-path> [--no-save]
    python analysis_pass.py show <game_id|1>       # recall a saved pass
    python analysis_pass.py list
"""
from __future__ import annotations
import argparse, glob, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import eco_viz            # noqa: E402
import display_hex        # noqa: E402
import player_db          # noqa: E402

PASSES_DIR = os.path.join(HERE, "passes")

TABLE_COLUMNS = [
    "minute", "teamID", "name", "ally", "m_inc", "e_inc", "metal", "energy",
    "bp_avail", "bp_util", "n_mex", "n_conv", "value", "construction",
    "eco_added", "army_added", "eco_lost_d", "army_lost_d", "enemy_killed_d",
    "bank_delta", "bal_metal", "bal_bp", "bal_energy", "imbalance", "heavy",
    "reclaim_flag",
]


def stable_game_id(game):
    """Same rule as player_db: widget gameID > archive stem > wall clock."""
    gid = getattr(game, "game_id", None)
    if not gid:
        src = os.path.basename(getattr(game, "source", "") or "")
        if src and src != "bar_analytic_live.jsonl":
            gid = os.path.splitext(src)[0]
    return str(gid or f"game-{int(getattr(game, 'started_wall', 0) or time.time())}")


# ── the metric table ───────────────────────────────────────────────────────
def metric_table(game):
    """One row per (minute, team): every metric point, flat and tabular."""
    rows = []
    prev_flow = {}
    prev_bank = {}
    for m in game.minutes():
        snap = game.recall(m)
        if not snap:
            continue
        for t in snap.get("teams", []):
            if t.get("dead"):
                continue
            tid = t["teamID"]
            f = t.get("flow") or {}
            pf = prev_flow.get(tid, {})
            bank = eco_viz.player_layers(t)["bank"]
            ba, bu = t.get("bpAvail", 0) or 0, t.get("bpUsed", 0) or 0
            scores = display_hex.team_scores(t)
            mean = sum(scores.values()) / 3 or 1.0
            mags = {k: round(v / mean, 3) for k, v in scores.items()}
            heavy = max(mags, key=mags.get)
            imb = round(mags[heavy] / max(min(mags.values()), 1e-9), 2)
            reclaim, _ = display_hex.check_reclaim_overload(t)

            def d(key):
                return round((f.get(key, 0) or 0) - (pf.get(key, 0) or 0), 1) if pf else None

            rows.append({
                "minute": m, "teamID": tid, "name": t.get("name", str(tid)),
                "ally": t.get("allyTeamID", 0),
                "m_inc": round(t.get("metalIncome", 0) or 0, 2),
                "e_inc": round(t.get("energyIncome", 0) or 0, 1),
                "metal": round(t.get("metalCurrent", 0) or 0, 1),
                "energy": round(t.get("energyCurrent", 0) or 0),
                "bp_avail": round(ba), "bp_util": round(100.0 * bu / ba, 1) if ba else 0.0,
                "n_mex": t.get("nMex", 0), "n_conv": t.get("nConv", 0),
                "value": round(t.get("total", 0) or 0),
                "construction": round(t.get("constructionValue", 0) or 0),
                "eco_added": d("eco_made"), "army_added": d("army_made"),
                "eco_lost_d": d("eco_lost"), "army_lost_d": d("army_lost"),
                "enemy_killed_d": d("enemy_killed"),
                "bank_delta": round(bank - prev_bank[tid], 1) if tid in prev_bank else None,
                "bal_metal": mags["metal"], "bal_bp": mags["bp"],
                "bal_energy": mags["energy"], "imbalance": imb, "heavy": heavy,
                "reclaim_flag": bool(reclaim),
            })
            prev_flow[tid] = f
            prev_bank[tid] = bank
    return rows


# ── the pass's own conclusions ─────────────────────────────────────────────
def _playstyle(rows_t, final):
    """Read a playstyle from the numbers: conversion-teching / fast-expander /
    army-forward / balanced (heuristic, honest to what the table shows)."""
    if not rows_t:
        return "unknown"
    # baseline mex AFTER the opening (everyone claims lane mexes early);
    # conversion-teching = spots frozen from there while converters stack
    mex0 = next((r["n_mex"] for r in rows_t if r["minute"] >= 5), rows_t[0]["n_mex"])
    mexN = final["n_mex"]
    conv = final["n_conv"]
    army = sum(r["army_added"] or 0 for r in rows_t)
    eco = sum(r["eco_added"] or 0 for r in rows_t)
    if conv >= 10 and mexN - mex0 <= 2:
        return "conversion-teching (long-T1 archetype)"
    if mexN - mex0 >= 5:
        return "fast-expander"
    if army > 1.5 * max(eco, 1):
        return "army-forward"
    return "balanced eco"


def conclusions(game, table):
    by_team = {}
    for r in table:
        by_team.setdefault(r["teamID"], []).append(r)
    teams, lines = {}, []
    lanes = eco_viz.lane_positions(game.snapshot())
    for tid, rows_t in by_team.items():
        final = rows_t[-1]
        name = final["name"]
        lost = sum(r["army_lost_d"] or 0 for r in rows_t)
        killed = sum(r["enemy_killed_d"] or 0 for r in rows_t)
        trade = round(killed / lost, 2) if lost > 100 else None
        episodes = [r["minute"] for r in rows_t if r["imbalance"] > 1.3]
        reclaim_min = [r["minute"] for r in rows_t if r["reclaim_flag"]]
        style = _playstyle(rows_t, final)
        traits = []
        fs = eco_viz.flow_series(game, tid)
        if fs:
            for trait, spec in player_db.TRAITS.items():
                obs = spec["fn"](fs)
                if obs:
                    traits.append(trait)
        teams[tid] = {
            "name": name, "ally": final["ally"],
            "position": lanes.get(tid, {}).get("position_class", ""),
            "playstyle": style,
            "final_value": final["value"], "final_m_inc": final["m_inc"],
            "final_e_inc": final["e_inc"], "n_conv": final["n_conv"],
            "trade_ratio": trade, "traits": traits,
            "imbalance_minutes": episodes[:20],
            "reclaim_flag_minutes": reclaim_min[:20],
        }
        bits = [style]
        if trade is not None:
            bits.append(f"trade {trade}x" + (" (metal sink)" if trade < 0.6 else
                                             " (winning)" if trade >= 1.3 else ""))
        if traits:
            bits.append("traits: " + ", ".join(traits))
        if reclaim_min:
            bits.append(f"reclaim-overload at min {reclaim_min[:3]}")
        lines.append(f"{name}: " + " · ".join(bits))

    # game level: ally value lead over time -> flips
    ally_val = {}
    for r in table:
        ally_val.setdefault(r["minute"], {}).setdefault(r["ally"], 0)
        ally_val[r["minute"]][r["ally"]] += r["value"]
    leader, flips = None, []
    for m in sorted(ally_val):
        v = ally_val[m]
        top = max(v, key=v.get)
        if leader is not None and top != leader:
            flips.append({"minute": m, "to_ally": top,
                          "lead": round(v[top] - min(v.values()))})
        leader = top
    last = ally_val.get(max(ally_val)) if ally_val else {}
    game_c = {
        "duration_min": max((r["minute"] for r in table), default=0),
        "winner": getattr(game, "winners", None),
        "value_leader_ally": leader,
        "lead_flips": flips,
        "final_ally_value": {str(k): round(v) for k, v in (last or {}).items()},
    }
    if flips:
        lines.append(f"lead changed {len(flips)}x, last to ally {flips[-1]['to_ally']} "
                     f"at min {flips[-1]['minute']}")
    elif leader is not None:
        lines.append(f"ally {leader} led wire-to-wire")
    return {"teams": teams, "game": game_c, "summary_lines": lines}


# ── run / persist / recall ─────────────────────────────────────────────────
def run_pass(game, save=True):
    gid = stable_game_id(game)
    table = metric_table(game)
    conc = conclusions(game, table)
    out = {
        "game_id": gid,
        "map": game.snapshot().get("session", {}).get("mapName", ""),
        "created_at": time.time(),
        "columns": TABLE_COLUMNS,
        "rows": len(table),
        "table": table,
        "conclusions": conc,
    }
    if save:
        os.makedirs(PASSES_DIR, exist_ok=True)
        p = os.path.join(PASSES_DIR, f"{gid}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(out, f)
        out["saved_to"] = p
    return out


def list_passes():
    return sorted(glob.glob(os.path.join(PASSES_DIR, "*.json")), key=os.path.getmtime,
                  reverse=True)


def load_pass(ref):
    files = list_passes()
    for p in files:
        if os.path.splitext(os.path.basename(p))[0] == str(ref):
            return json.load(open(p, encoding="utf-8"))
    try:
        return json.load(open(files[int(ref) - 1], encoding="utf-8"))
    except (ValueError, IndexError):
        raise FileNotFoundError(f"no saved pass: {ref} (have {len(files)})")


def main():
    ap = argparse.ArgumentParser(description="full-game analysis pass")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("game", nargs="?", default=1)
    r.add_argument("--no-save", action="store_true")
    s = sub.add_parser("show")
    s.add_argument("ref")
    s.add_argument("--table", action="store_true", help="dump the metric rows too")
    sub.add_parser("list")
    a = ap.parse_args()

    if a.cmd == "run":
        from bar_analytic_server import load_game
        out = run_pass(load_game(a.game), save=not a.no_save)
        print(f"pass {out['game_id']}: {out['rows']} metric rows, "
              f"{len(out['conclusions']['teams'])} teams"
              + (f"  -> {out['saved_to']}" if out.get("saved_to") else ""))
        for ln in out["conclusions"]["summary_lines"]:
            print("  " + ln)
    elif a.cmd == "show":
        out = load_pass(a.ref)
        show = dict(out)
        if not a.table:
            show["table"] = f"[{out['rows']} rows — use --table]"
        print(json.dumps(show, indent=1))
    elif a.cmd == "list":
        for p in list_passes():
            print(os.path.splitext(os.path.basename(p))[0])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""replay_jsonl.py — replay a bar_analytic_live JSONL through the snapshot pipeline.

The activatable validation process for the per-minute snapshot / recall / project
feature. Instead of launching BAR (or hand-writing throwaway test scripts), this
feeds any JSONL stream — the live file or a saved game — through the same Live state
machine the server uses, captures per-minute snapshots, and runs recall / compare /
project on real data offline.

Usage:
  python replay_jsonl.py [--path FILE] [ACTION] [--json]

  ACTION (default = summary + project the mid-game minute):
    --minutes        list the captured game-minutes
    --snapshot N     dump the full recalled state at minute N
    --compare  N     per-team delta minute N -> N+1
    --project  N     project minute N forward, grade vs actual N+1

  --path defaults to the widget's live JSONL (bar_analytic_server.DEFAULT_PATH).
  --json prints raw JSON instead of the formatted table.

Examples:
  python replay_jsonl.py --project 7
  python replay_jsonl.py --path ../live/saved_game.jsonl --compare 5
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bar_analytic_server import (              # noqa: E402  (path set above)
    Live, compare_minutes, project_team, team_state,
    DEFAULT_PATH, _ANALYSIS_AVAILABLE,
)


def replay(path):
    """Feed every JSONL line through Live, capturing a snapshot at each game-minute."""
    live = Live()
    live.apply({"action": "init"})
    n = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                live.apply(json.loads(line))
            except json.JSONDecodeError:
                continue
            n += 1
            live.capture_due_snapshots()
    return live, n


def print_status(path):
    """One-screen game report from a JSONL: capture health, widget version, teams +
    economy, openings, and resource sharing. Composed from the same Live + registry
    everything else uses — not a raw event dump."""
    import time
    from build_classifier import classify_build
    live = Live(); live.apply({"action": "init"})
    acts = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        acts[e.get("action")] = acts.get(e.get("action"), 0) + 1
        live.apply(e)
        live.capture_due_snapshots()

    snap = live.snapshot(); sess = snap["session"]; gs = int(snap["gameSeconds"])
    age = time.time() - os.path.getmtime(path)
    state = ("ENDED" if ("shutdown" in acts or snap.get("over"))
             else "LIVE" if age < 10 else f"stale {int(age)}s")
    widget = ("NEW · resource_share" if acts.get("resource_share")
              else "OLD · energy_share (redeploy needed)" if acts.get("energy_share")
              else "no share events yet")
    print(f"GAME   {sess.get('mapName','?')}  |  {gs//60}:{gs%60:02d}  |  {state}  |  "
          f"spec={sess.get('isSpectator')} fullView={sess.get('fullView')}  |  {sum(acts.values())} events")
    print(f"WIDGET {widget}")

    teams = snap["teams"]
    print(f"TEAMS  ({len(teams)})")
    for t in teams:
        flag = "  DEAD" if t["dead"] else ""
        print(f"  a{t['allyTeamID']} {t['name'][:16]:16} {t['side'][:3]:<3}  "
              f"val {t['total']:>6.0f}  m+{t['metalIncome']:>5.1f}  e+{t['energyIncome']:>5.0f}  "
              f"mex {t['nMex']:>2}  bp {t['bpAvail']:>4.0f}{flag}")

    if live.build_log:
        print("OPENINGS")
        for tid, log in sorted(live.build_log.items()):
            o = classify_build(log, live.unit_defs, wind_e=live.wind or 12)["opening"]
            nm = live.teams.get(tid, {}).get("name", str(tid))
            print(f"  {nm[:16]:16} {o['cadence']:<30} [{o['label']}]")

    sh = live.shares_named()
    if sh:
        print("SHARING (X > Y)")
        for s in sh[:10]:
            print(f"  {s['label']:<34} donation {s['donation']:>6.0f}  "
                  f"overflow {s['overflow']:>6.0f}  taxed {s.get('taxed',0):>5.0f}")
    else:
        print("SHARING  (none detected)")


def _fmt_minute(m):
    return f"{m}:00"


def _need(live, n):
    """Both minute n and n+1 must exist; report what is available otherwise."""
    a, b = live.recall(n), live.recall(n + 1)
    if not a or not b:
        print(f"need snapshots at minute {n} and {n+1}; available: {live.minutes()}")
        return None, None
    return a, b


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--path", default=DEFAULT_PATH)
    ap.add_argument("--minutes",  action="store_true")
    ap.add_argument("--snapshot", type=int, metavar="N")
    ap.add_argument("--compare",  type=int, metavar="N")
    ap.add_argument("--project",  type=int, metavar="N")
    ap.add_argument("--shares",   action="store_true",
                    help="energy donation/overflow flows between teammates (X > Y)")
    ap.add_argument("--build",    nargs="?", const="*", metavar="TEAM",
                    help="classify each team's opening build (optional teamID to filter)")
    ap.add_argument("--run",      metavar="LIST",
                    help="CLI runner: comma list of registry analyses, e.g. build,shares,project:7")
    ap.add_argument("--status",   action="store_true",
                    help="quick health check of the JSONL: freshness, event histogram, share sample")
    ap.add_argument("--json",     action="store_true", help="raw JSON output")
    args = ap.parse_args()

    if not os.path.isfile(args.path):
        print(f"no such JSONL: {args.path}")
        sys.exit(1)

    if args.status:
        print_status(args.path)
        return

    live, n = replay(args.path)
    mins = live.minutes()
    snap = live.snapshot()
    print(f"replayed {n} events from {os.path.basename(args.path)}  "
          f"({snap['session'].get('mapName','?')})  "
          f"minutes captured: {mins[0] if mins else '-'}..{mins[-1] if mins else '-'} "
          f"({len(mins)} total)")

    # ---- minute-independent actions (work even with no economy frames) -------------
    if args.run:
        from analyses import run as run_analyses
        funcs = [f.strip() for f in args.run.split(",") if f.strip()]
        print(json.dumps(run_analyses(live, funcs), indent=2))
        return

    if args.shares:
        flows = live.shares_named()
        if args.json:
            print(json.dumps(flows, indent=2)); return
        if not flows:
            print("no energy sharing/overflow detected in this game."); return
        print("\nresource sharing (X > Y, cumulative; donation=chat, overflow=auto-spill):")
        print(f"  {'flow':34} {'donation':>9} {'overflow':>9} {'taxed':>7} {'total':>8}")
        print("  " + "-" * 70)
        for fl in flows:
            print(f"  {fl['label'][:34]:34} {fl['donation']:>9.0f} {fl['overflow']:>9.0f} "
                  f"{fl.get('taxed',0):>7.0f} {fl['total']:>8.0f}")
        return

    if args.build is not None:
        from analyses import _build as build_fn
        res  = build_fn(live, team=(None if args.build == "*" else args.build))
        rows = res["teams"]
        if args.json:
            print(json.dumps(res, indent=2)); return
        if not rows:
            print("no build log captured."); return
        print("\nopening + phase-2 (post-factory → team's first T2) classification:")
        for r in rows:
            o, p2 = r["opening"], r["phase2"]
            fac = f"{o['factorySec']}s" if o.get("factorySec") else "—"
            t2  = f"T2 {p2['t2Sec']}s" if p2.get("t2Sec") else "no T2 yet"
            ps  = p2["split"]["pct"]
            print(f"\n  {r['name'][:16]:16} {o['cadence']}  [{o['label']}, factory {fac}]")
            print(f"    phase2 (→{t2}, {p2['split']['nBuilds']} builds): "
                  f"expand {ps['expanding']}%  bp {ps['build_power']}%  egen {ps['egen']}%  "
                  f"mil {ps['military']}%  other {ps['other']}%")
            if p2["deviations"]:
                print(f"    deviations: {p2['deviations']}")
        return

    if args.minutes:
        print("minutes:", mins)
        return

    if not mins:
        print("no per-minute snapshots — stream had no economy frames.")
        sys.exit(2)

    # ---- minute-based actions ------------------------------------------------------
    if args.snapshot is not None:
        s = live.recall(args.snapshot)
        print(json.dumps(s, indent=2) if s
              else f"no snapshot at minute {args.snapshot}; available: {mins}")
        return

    if args.compare is not None:
        a, b = _need(live, args.compare)
        if a is None:
            return
        res = compare_minutes(a, b)
        if args.json:
            print(json.dumps(res, indent=2)); return
        print(f"\ncompare minute {_fmt_minute(args.compare)} -> {_fmt_minute(args.compare+1)}:")
        for t in res["teams"]:
            d = t["delta"]
            print(f"  {t['name'][:14]:14} | total {t['from']['total']:>7.0f} -> {t['to']['total']:>7.0f} "
                  f"(Δ{d['total']:+.0f})  m_inc Δ{d['metalIncome']:+.2f}  nMex Δ{d['nMex']:+d}")
        return

    # default action = project the mid-game minute if none specified
    target = args.project if args.project is not None else mins[len(mins)//2]
    if not _ANALYSIS_AVAILABLE:
        print("economy analysis unavailable (state_api/navigator import failed) — "
              "cannot project. compare/snapshot still work.")
        return
    a, b = _need(live, target)
    if a is None:
        return
    rows = []
    for t in a["teams"]:
        tid = t["teamID"]
        sn, snp1 = team_state(tid, a), team_state(tid, b)
        if not sn or not snp1:
            continue
        proj = project_team(sn, snp1)
        proj["teamID"], proj["name"], proj["side"] = tid, t.get("name", str(tid)), t.get("side", "")
        rows.append(proj)

    out = {"fromMinute": target, "toMinute": target + 1, "horizonSec": 60,
           "model": "legion-eco (state_api)", "teams": rows}
    if args.json:
        print(json.dumps(out, indent=2)); return

    print(f"\n/api/project?minute={target}  (project {_fmt_minute(target)} -> grade vs actual "
          f"{_fmt_minute(target+1)}):")
    print(f"  {'player':14} | {'best move @N':22} {'Δm_inc':>7} {'ΔnMex':>6} "
          f"{'deployed':>9}   verdict")
    print("  " + "-" * 78)
    for p in rows:
        bo = (p["bestOptions"][0] if p.get("bestOptions") else {}) or {}
        move = f"{bo.get('action','?')} (roi {bo.get('roi_s','?')}s)" if "action" in bo else "?"
        print(f"  {p['name'][:14]:14} | {move[:22]:22} {p['delta']['m_inc']:>+7.2f} "
              f"{p['delta']['n_mex']:>+6d} {p['metalDeployedVsPassive']:>+8.0f}m   {','.join(p['flags'])}")


if __name__ == "__main__":
    main()

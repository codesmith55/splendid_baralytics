#!/usr/bin/env python3
"""Reads the games.db, lists active games, targets one or many for actions.

Actions available:
    list                — show tracked games
    active              — only currently-running watchers
    tail <battle_id>    — dump last N snapshots + events
    target-list         — output the battle_ids of running qualifiers
    target-json         — same, but full metadata as JSON
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchers_schema import connect

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("active")
    sp = sub.add_parser("tail")
    sp.add_argument("battle_id", type=int)
    sp.add_argument("--n", type=int, default=5)
    sub.add_parser("target-list")
    sub.add_parser("target-json")
    args = p.parse_args()

    conn = connect()
    if args.cmd in ("list", "active"):
        where = "WHERE watcher_status='running'" if args.cmd == "active" else ""
        rows = conn.execute(f"""SELECT battle_id, title, map_name, founder, initial_avg_os,
                                       peak_avg_os, watcher_status,
                                       (last_seen - first_seen) AS age_s,
                                       watcher_pid
                                FROM games {where} ORDER BY last_seen DESC""").fetchall()
        print(f"{'BID':<6} {'TITLE':<26} {'MAP':<30} {'FOUNDER':<20} "
              f"{'AVG':<5} {'PEAK':<5} {'STATUS':<8} {'AGE':<8} {'PID'}")
        for r in rows:
            bid, t, m, f, ios, pos, st, age, pid = r
            print(f"#{bid:<5} {(t or '')[:26]:<26} {(m or '')[:30]:<30} {(f or '')[:20]:<20} "
                  f"{ios or 0:<5.1f} {pos or 0:<5.1f} {st or '':<8} {int(age or 0):<8} {pid or ''}")
    elif args.cmd == "tail":
        snaps = conn.execute("""SELECT ts, game_time_s, active_count, spec_count, avg_os, top_os
                                FROM snapshots WHERE battle_id=? ORDER BY ts DESC LIMIT ?""",
                             (args.battle_id, args.n)).fetchall()
        print(f"--- snapshots for #{args.battle_id} (newest first) ---")
        for ts, gt, ac, sc, ao, to in snaps:
            print(f"  {time.strftime('%H:%M:%S', time.localtime(ts))}  gameTime={gt//60}m{gt%60:02d}s  active={ac} spec={sc}  avgOS={ao:.2f} top={to:.2f}")
        events = conn.execute("""SELECT ts, kind, subject, detail FROM events
                                 WHERE battle_id=? ORDER BY ts DESC LIMIT ?""",
                              (args.battle_id, args.n)).fetchall()
        print(f"--- events (newest first) ---")
        for ts, kind, sub, det in events:
            print(f"  {time.strftime('%H:%M:%S', time.localtime(ts))}  {kind:<12} {sub or '':<18} {det[:60]}")
    elif args.cmd in ("target-list", "target-json"):
        rows = conn.execute("""SELECT battle_id, title, map_name, founder, initial_avg_os, peak_avg_os
                               FROM games WHERE watcher_status='running'""").fetchall()
        if args.cmd == "target-list":
            for r in rows: print(r[0])
        else:
            out = [{"battle_id": r[0], "title": r[1], "map": r[2], "founder": r[3],
                    "initial_avg_os": r[4], "peak_avg_os": r[5]} for r in rows]
            print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()

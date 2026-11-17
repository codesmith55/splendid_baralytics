#!/usr/bin/env python3
"""Watches ONE running BAR battle, writing periodic snapshots + derived
events to the shared games.db.

Usage:
    game_watcher.py <battle_id> [--interval 20] [--max-runtime 7200]

Self-terminates when:
    - the battle 404s (game closed)
    - `gameTime` disappears (game ended without an id change — rare)
    - max_runtime reached
"""
from __future__ import annotations
import argparse, json, os, sys, time, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchers_schema import connect, parse_os, summarize_players

API = "https://api.bar-rts.com/battles/{id}"

def fetch(battle_id, timeout=10):
    req = urllib.request.Request(API.format(id=battle_id),
                                 headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            if not body.strip(): return None
            return json.loads(body)
    except urllib.error.HTTPError as e:
        if e.code == 404: return None
        raise
    except Exception:
        return None

def diff_players(prev, curr):
    """Yield (kind, subject, detail) events for the delta between rosters."""
    def names(ps): return {p.get("username",""): p for p in ps if isinstance(p, dict)}
    a, b = names(prev or []), names(curr or [])
    for u in b.keys() - a.keys():
        yield ("joined", u, json.dumps({"team": b[u].get("team"), "spec": b[u].get("gameStatus","")=="Spectating"}))
    for u in a.keys() - b.keys():
        yield ("left", u, "")
    for u in a.keys() & b.keys():
        was_spec = str(a[u].get("gameStatus","")).lower() == "spectating"
        is_spec  = str(b[u].get("gameStatus","")).lower() == "spectating"
        if was_spec != is_spec:
            yield ("spec_flip", u, json.dumps({"now_spec": is_spec}))
        if a[u].get("team") != b[u].get("team") and not was_spec and not is_spec:
            yield ("swapped_team", u, json.dumps({"from": a[u].get("team"), "to": b[u].get("team")}))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("battle_id", type=int)
    p.add_argument("--interval", type=float, default=20.0)
    p.add_argument("--max-runtime", type=float, default=7200.0, help="seconds")
    args = p.parse_args()

    conn = connect()
    start = time.time()
    last_players = []

    # Register/refresh game row
    conn.execute("UPDATE games SET watcher_pid=?, watcher_status='running' WHERE battle_id=?",
                 (os.getpid(), args.battle_id))
    conn.commit()

    print(f"[watcher] battle={args.battle_id} interval={args.interval}s pid={os.getpid()}")

    while time.time() - start < args.max_runtime:
        b = fetch(args.battle_id)
        now = time.time()
        if b is None:
            # 404 or empty — game ended
            conn.execute("""UPDATE games SET ended_at=?, watcher_status='ended' WHERE battle_id=?""",
                         (now, args.battle_id))
            conn.execute("INSERT INTO events (battle_id, ts, kind, subject, detail) VALUES (?,?,?,?,?)",
                         (args.battle_id, now, "game_end", "", "api_empty_or_404"))
            conn.commit()
            print("[watcher] game ended, exiting")
            break

        stats = summarize_players(b.get("players", []))
        conn.execute("""INSERT INTO snapshots
            (battle_id, ts, game_time_s, active_count, spec_count, avg_os, top_os, players_json, raw_json)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (args.battle_id, now, int(b.get("gameTime") or 0),
             stats["active_count"], stats["spec_count"], stats["avg_os"], stats["top_os"],
             json.dumps(b.get("players", []))[:10000], json.dumps(b)[:20000]))

        # events
        for kind, subj, detail in diff_players(last_players, b.get("players", [])):
            conn.execute("INSERT INTO events (battle_id, ts, kind, subject, detail) VALUES (?,?,?,?,?)",
                         (args.battle_id, now, kind, subj, detail))
        last_players = b.get("players", [])

        # keep peak_avg_os current
        conn.execute("""UPDATE games SET last_seen=?, peak_avg_os = MAX(COALESCE(peak_avg_os, 0), ?)
                        WHERE battle_id=?""", (now, stats["avg_os"], args.battle_id))
        conn.commit()

        gt = int(b.get("gameTime") or 0)
        print(f"[watcher] t+{int(now-start)}s  gameTime={gt//60}m{gt%60:02d}s  active={stats['active_count']} spec={stats['spec_count']}  avgOS={stats['avg_os']:.2f}")

        time.sleep(args.interval)
    else:
        conn.execute("UPDATE games SET watcher_status='ended' WHERE battle_id=?", (args.battle_id,))
        conn.commit()
        print("[watcher] max runtime reached, exiting")

if __name__ == "__main__":
    main()

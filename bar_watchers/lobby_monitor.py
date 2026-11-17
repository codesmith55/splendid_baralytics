#!/usr/bin/env python3
"""Polls BAR battle list, decides which running games qualify for watching,
spawns a game_watcher subprocess per new qualifier.

Default qualifiers (adjustable via CLI):
    - Map name contains a required substring (default: "glitters")
    - Battle is running (gameTime present + non-null)
    - avg_os > MIN_AVG_OS (default 20)
    - at least one non-spec player OS > MIN_TOP_OS (default 30)
"""
from __future__ import annotations
import argparse, json, subprocess, sys, time, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchers_schema import connect, summarize_players, parse_os

API_ALL = "https://api.bar-rts.com/battles"
HERE = Path(__file__).resolve().parent

def fetch_all(timeout=15):
    req = urllib.request.Request(API_ALL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def qualifies(b: dict, args) -> bool:
    if b.get("gameTime") is None: return False
    map_str = (b.get("mapFileName") or b.get("map") or "").lower()
    if args.map_contains and args.map_contains.lower() not in map_str:
        return False
    stats = summarize_players(b.get("players", []))
    if stats["avg_os"] <= args.min_avg_os: return False
    if stats["top_os"] <= args.min_top_os: return False
    return True

def spawn_watcher(battle_id: int, args) -> int:
    """Fire game_watcher.py as a detached subprocess. Returns pid."""
    cmd = [sys.executable, str(HERE / "game_watcher.py"),
           str(battle_id), "--interval", str(args.watcher_interval),
           "--max-runtime", str(args.watcher_max_runtime)]
    log = HERE / "context" / f"watcher_{battle_id}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    lf = open(log, "ab")
    proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL,
                            start_new_session=True)
    return proc.pid

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=float, default=30.0, help="seconds between lobby polls")
    p.add_argument("--map-contains", default="glitters")
    p.add_argument("--min-avg-os", type=float, default=20.0)
    p.add_argument("--min-top-os", type=float, default=30.0)
    p.add_argument("--watcher-interval", type=float, default=20.0)
    p.add_argument("--watcher-max-runtime", type=float, default=7200.0)
    p.add_argument("--once", action="store_true", help="single pass, don't loop")
    args = p.parse_args()

    conn = connect()

    def one_pass():
        try:
            battles = fetch_all()
        except Exception as e:
            print(f"[monitor] fetch failed: {e}"); return

        qual_ids = []
        for b in battles:
            bid = b.get("battleId") or b.get("id")
            if bid is None: continue
            if not qualifies(b, args): continue
            qual_ids.append(bid)
            stats = summarize_players(b.get("players", []))
            founder = b.get("founder", {})
            fn = founder.get("username","") if isinstance(founder, dict) else str(founder)

            # Insert or refresh games row
            row = conn.execute("SELECT battle_id, watcher_status FROM games WHERE battle_id=?", (bid,)).fetchone()
            now = time.time()
            if not row:
                conn.execute("""INSERT INTO games
                    (battle_id, title, map_name, map_slug, founder, game_version,
                     max_players, first_seen, last_seen, initial_avg_os, peak_avg_os,
                     watcher_status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (bid, b.get("title",""), b.get("map",""), b.get("mapFileName",""),
                     fn, b.get("game",""), b.get("maxPlayers",0),
                     now, now, stats["avg_os"], stats["avg_os"], "idle"))
                print(f"[monitor] NEW qualifier #{bid}  {b.get('title','')[:30]}  avgOS={stats['avg_os']:.1f}  top={stats['top_os']:.1f}")
                pid = spawn_watcher(bid, args)
                conn.execute("UPDATE games SET watcher_pid=?, watcher_status='running' WHERE battle_id=?", (pid, bid))
                print(f"[monitor]   spawned watcher pid={pid}")
            else:
                conn.execute("UPDATE games SET last_seen=? WHERE battle_id=?", (now, bid))
                # respawn if watcher died
                cur = conn.execute("SELECT watcher_pid, watcher_status FROM games WHERE battle_id=?", (bid,)).fetchone()
                if cur and cur[1] not in ("running",) and args.map_contains:
                    pid = spawn_watcher(bid, args)
                    conn.execute("UPDATE games SET watcher_pid=?, watcher_status='running' WHERE battle_id=?", (pid, bid))
                    print(f"[monitor]   respawned watcher pid={pid} for #{bid}")
            conn.commit()
        print(f"[monitor] pass done: {len(battles)} battles fetched, {len(qual_ids)} qualifiers ({qual_ids})")

    if args.once:
        one_pass()
    else:
        print(f"[monitor] running every {args.interval}s (map~{args.map_contains}, avgOS>{args.min_avg_os}, topOS>{args.min_top_os})")
        while True:
            one_pass()
            time.sleep(args.interval)

if __name__ == "__main__":
    main()

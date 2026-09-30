#!/usr/bin/env python3
"""After a watched game ends, fetch its .sdfz replay from bar-rts.com.

Runs periodically (called by supervisor or a scheduled task).
For every game with ended_at set and no replay_path yet, try to find its
replay. bar-rts API path: /replays?battleId=<id> (or listReplays).
Falls back to searching /replays for recent uploads that match founder/map.
"""
from __future__ import annotations
import json, sys, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchers_schema import connect
from config import load as load_cfg

def _add_column_if_missing(conn, table, col, decl):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        conn.commit()

def main():
    cfg = load_cfg()
    conn = connect()
    _add_column_if_missing(conn, "games", "replay_path", "TEXT")
    _add_column_if_missing(conn, "games", "replay_attempts", "INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "games", "replay_last_attempt", "REAL")

    now = time.time()
    delay = cfg["replay_fetch_delay_s"]
    backoff = cfg["replay_fetch_backoff_s"]
    max_att = cfg["replay_fetch_max_attempts"]

    candidates = conn.execute("""SELECT battle_id, founder, map_name, ended_at,
                                        replay_attempts, replay_last_attempt
                                 FROM games
                                 WHERE ended_at IS NOT NULL
                                   AND (replay_path IS NULL OR replay_path='')
                                 ORDER BY ended_at DESC LIMIT 200""").fetchall()

    fetched, skipped = 0, 0
    for bid, founder, m, ended, att, last in candidates:
        att = att or 0
        if att >= max_att:
            skipped += 1; continue
        if (now - (ended or 0)) < delay:
            skipped += 1; continue
        if last and (now - last) < backoff:
            skipped += 1; continue

        conn.execute("UPDATE games SET replay_attempts=?, replay_last_attempt=? WHERE battle_id=?",
                     (att + 1, now, bid))
        conn.commit()

        # Attempt: query /replays?battleId=NNN
        try:
            url = f"{cfg['api_replays']}?battleId={bid}"
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read().decode())
        except Exception as e:
            print(f"[replay] #{bid} query failed: {e}"); continue

        # data may be an array; look for a fileName / url
        entries = data if isinstance(data, list) else data.get("data", [])
        picked = None
        for e in entries:
            if not isinstance(e, dict): continue
            if e.get("battleId") == bid or e.get("id") == bid:
                picked = e; break
        if not picked and entries:
            picked = entries[0]
        if not picked:
            print(f"[replay] #{bid} no replay found yet"); continue

        fname = picked.get("fileName") or picked.get("filename") or f"battle_{bid}.sdfz"
        dl_url = picked.get("url") or picked.get("downloadUrl") or f"{cfg['cdn_replays']}{fname}"
        dest = Path(__file__).resolve().parent / "replays" / fname
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            with urllib.request.urlopen(dl_url, timeout=60) as r, open(dest, "wb") as f:
                f.write(r.read())
        except Exception as e:
            print(f"[replay] #{bid} download failed: {e}"); continue

        conn.execute("UPDATE games SET replay_path=? WHERE battle_id=?", (str(dest), bid))
        conn.commit()
        fetched += 1
        print(f"[replay] #{bid} → {dest}")

    print(f"[replay] fetched: {fetched}  skipped: {skipped}  candidates: {len(candidates)}")

if __name__ == "__main__":
    main()

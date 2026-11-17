#!/usr/bin/env python3
"""Verify the watcher stack is healthy.
Exits 0 if OK, 1 if problems (stale watchers, missing DB, etc.)."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchers_schema import connect, DB_PATH
from config import load as load_cfg

def main():
    cfg = load_cfg()
    problems = []
    now = time.time()

    if not Path(DB_PATH).exists():
        problems.append(f"db missing: {DB_PATH}")
        print(json.dumps({"ok": False, "problems": problems})); sys.exit(1)

    conn = connect()
    stale = conn.execute("""SELECT battle_id, last_seen FROM games
                            WHERE watcher_status='running'
                              AND (?  - last_seen) > ?""",
                         (now, cfg["stale_after_s"])).fetchall()
    for bid, ls in stale:
        problems.append(f"stale watcher #{bid}: {int(now-ls)}s since last snapshot")

    counts = {
        "games": conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
        "running": conn.execute("SELECT COUNT(*) FROM games WHERE watcher_status='running'").fetchone()[0],
        "snapshots": conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
        "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "stale": len(stale),
    }
    result = {"ok": not problems, "problems": problems, "counts": counts}
    print(json.dumps(result, indent=2))
    sys.exit(0 if not problems else 1)

if __name__ == "__main__":
    main()

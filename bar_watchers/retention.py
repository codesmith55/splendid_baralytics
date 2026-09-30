#!/usr/bin/env python3
"""Prune old snapshots, old events, old replay files per config TTLs."""
from __future__ import annotations
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchers_schema import connect
from config import load as load_cfg

def main():
    cfg = load_cfg()
    conn = connect()
    now = time.time()
    day = 86400

    snap_cut = now - cfg["snapshot_ttl_days"] * day
    evt_cut  = now - cfg["events_ttl_days"] * day
    rep_cut  = now - cfg["replay_ttl_days"] * day

    n_snap = conn.execute("DELETE FROM snapshots WHERE ts < ?", (snap_cut,)).rowcount
    n_evt  = conn.execute("DELETE FROM events    WHERE ts < ?", (evt_cut,)).rowcount
    conn.commit()

    n_rep = 0
    rep_dir = Path(__file__).resolve().parent / "replays"
    if rep_dir.exists():
        for p in rep_dir.glob("*.sdfz"):
            if p.stat().st_mtime < rep_cut:
                p.unlink(); n_rep += 1

    print(f"[retention] snapshots pruned: {n_snap}  events pruned: {n_evt}  replays deleted: {n_rep}")

if __name__ == "__main__":
    main()

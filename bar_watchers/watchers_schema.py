#!/usr/bin/env python3
"""Shared SQLite schema + connection helper for the BAR watcher stack.

Tiers using this DB:
    lobby_monitor.py    — inserts/updates games rows, spawns watchers
    game_watcher.py     — inserts snapshots + derived events for one game
    game_coordinator.py — reads across all games; targets a subset
"""
from __future__ import annotations
import os, sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get(
    "BAR_WATCHERS_DB",
    str(Path(__file__).resolve().parent / "context" / "games.db")))

DDL = """
CREATE TABLE IF NOT EXISTS games (
    battle_id     INTEGER PRIMARY KEY,
    title         TEXT,
    map_name      TEXT,
    map_slug      TEXT,
    founder       TEXT,
    game_version  TEXT,
    max_players   INTEGER,
    first_seen    REAL NOT NULL,   -- unix ts we started watching
    last_seen     REAL NOT NULL,   -- last successful snapshot
    ended_at      REAL,            -- set when the game vanishes / API 404
    initial_avg_os REAL,           -- avg OS at first snapshot
    peak_avg_os   REAL,            -- highest avg OS observed
    watcher_pid   INTEGER,         -- child process id (nullable)
    watcher_status TEXT DEFAULT 'idle'  -- idle | running | ended | error
);
CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_id     INTEGER NOT NULL,
    ts            REAL NOT NULL,
    game_time_s   INTEGER,
    active_count  INTEGER,
    spec_count    INTEGER,
    avg_os        REAL,
    top_os        REAL,
    players_json  TEXT,             -- full player array as captured
    raw_json      TEXT              -- full battle object (optional, may be trimmed)
);
CREATE INDEX IF NOT EXISTS idx_snap_battle_ts ON snapshots(battle_id, ts);
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_id     INTEGER NOT NULL,
    ts            REAL NOT NULL,
    kind          TEXT NOT NULL,    -- joined | left | swapped_team | game_end | spec_flip
    subject       TEXT,             -- usually a username
    detail        TEXT              -- JSON-encoded extra
);
CREATE INDEX IF NOT EXISTS idx_evt_battle_ts ON events(battle_id, ts);
"""

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(DDL)
    return conn

def parse_os(skill_str: str) -> float:
    """`.skill` from bar-rts.com is a string like "[34.27 ??]". Return the leading float."""
    if not skill_str: return 0.0
    s = skill_str.strip().lstrip("[").rstrip("]").split()
    try: return float(s[0])
    except (IndexError, ValueError): return 0.0

def summarize_players(players: list) -> dict:
    """Return active_count, spec_count, avg_os (non-spec), top_os (non-spec)."""
    active, spec, active_os = 0, 0, []
    for p in players or []:
        if not isinstance(p, dict): continue
        os_val = parse_os(p.get("skill", ""))
        if str(p.get("gameStatus", "")).lower() == "spectating":
            spec += 1
        else:
            active += 1
            active_os.append(os_val)
    return {
        "active_count": active,
        "spec_count": spec,
        "avg_os": (sum(active_os) / len(active_os)) if active_os else 0.0,
        "top_os": max(active_os) if active_os else 0.0,
    }

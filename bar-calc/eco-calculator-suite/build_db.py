"""
SQLite store for BAR build paths.

Schema:
  builds      — top-level named build (e.g. "Solar Opener")
  branches    — each build is a tree of branches; a branch has a parent
                (NULL for the root) and a list of queue items.  Forks of an
                existing build copy its queue up to the fork point.
  queue_items — ordered list of (item_key, mode) entries on a branch
  targets     — named target asset compositions (the goal we measure
                break-even against)

This module is the canonical store.  Run `build_export.py` afterward to
simulate every branch and write `builds.json` for the dashboard.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from typing import Dict, List, Optional, Tuple

# SQLite over the workspace's 9p mount errors with "disk I/O error" on the
# locking syscalls it expects, so we keep the live DB in tmp and copy a
# snapshot into the workspace folder at the end.
WORKSPACE_DB = os.path.join(os.path.dirname(__file__), "builds.db")
DB_PATH = os.path.join(tempfile.gettempdir(), "bar_builds.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS builds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS branches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id        INTEGER NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    parent_id       INTEGER REFERENCES branches(id) ON DELETE CASCADE,
    label           TEXT NOT NULL,
    fork_at_step    INTEGER DEFAULT 0,
    UNIQUE(build_id, label)
);

CREATE TABLE IF NOT EXISTS queue_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id   INTEGER NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    step_idx    INTEGER NOT NULL,
    item_key    TEXT NOT NULL,
    mode        TEXT NOT NULL,
    UNIQUE(branch_id, step_idx)
);

CREATE TABLE IF NOT EXISTS targets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    composition TEXT NOT NULL,
    description TEXT
);
"""


# ─── DB connection ────────────────────────────────────────────────────────
def connect(path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Workspace mount doesn't support some SQLite locking ops; relax both
    # the journal and synchronous settings so writes land cleanly.
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA synchronous = OFF")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# ─── Builds ───────────────────────────────────────────────────────────────
def add_build(conn: sqlite3.Connection, name: str, description: str,
              queue: List[Tuple[str, str]],
              root_label: str = "main") -> int:
    """Create a build with one root branch holding the given queue."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO builds (name, description) VALUES (?, ?)",
        (name, description),
    )
    if cur.lastrowid:
        build_id = cur.lastrowid
    else:
        build_id = conn.execute("SELECT id FROM builds WHERE name = ?", (name,)).fetchone()["id"]

    cur = conn.execute(
        "INSERT OR IGNORE INTO branches (build_id, parent_id, label, fork_at_step) "
        "VALUES (?, NULL, ?, 0)",
        (build_id, root_label),
    )
    branch_id = cur.lastrowid or conn.execute(
        "SELECT id FROM branches WHERE build_id = ? AND label = ?",
        (build_id, root_label),
    ).fetchone()["id"]

    # Replace any existing items on the root branch (idempotent reseed).
    conn.execute("DELETE FROM queue_items WHERE branch_id = ?", (branch_id,))
    for i, (item_key, mode) in enumerate(queue):
        conn.execute(
            "INSERT INTO queue_items (branch_id, step_idx, item_key, mode) VALUES (?, ?, ?, ?)",
            (branch_id, i, item_key, mode),
        )
    conn.commit()
    return build_id


def fork_branch(conn: sqlite3.Connection, build_id: int, parent_label: str,
                new_label: str, fork_at_step: int,
                continuation: List[Tuple[str, str]]) -> int:
    """Fork a parent branch at step N and continue with new queue items.

    The forked branch inherits the parent's items up to and *including* step
    `fork_at_step - 1`, then appends the supplied continuation.
    """
    parent = conn.execute(
        "SELECT id FROM branches WHERE build_id = ? AND label = ?",
        (build_id, parent_label),
    ).fetchone()
    if parent is None:
        raise ValueError(f"No branch '{parent_label}' on build {build_id}")
    parent_id = parent["id"]

    cur = conn.execute(
        "INSERT INTO branches (build_id, parent_id, label, fork_at_step) "
        "VALUES (?, ?, ?, ?)",
        (build_id, parent_id, new_label, fork_at_step),
    )
    new_branch_id = cur.lastrowid

    # Copy parent items up to the fork point
    inherited = conn.execute(
        "SELECT item_key, mode FROM queue_items "
        "WHERE branch_id = ? AND step_idx < ? ORDER BY step_idx",
        (parent_id, fork_at_step),
    ).fetchall()
    items = [(r["item_key"], r["mode"]) for r in inherited] + list(continuation)
    for i, (item_key, mode) in enumerate(items):
        conn.execute(
            "INSERT INTO queue_items (branch_id, step_idx, item_key, mode) VALUES (?, ?, ?, ?)",
            (new_branch_id, i, item_key, mode),
        )
    conn.commit()
    return new_branch_id


# ─── Targets ──────────────────────────────────────────────────────────────
def add_target(conn: sqlite3.Connection, name: str,
               composition: Dict[str, int], description: str = "") -> None:
    conn.execute(
        "INSERT OR REPLACE INTO targets (name, composition, description) VALUES (?, ?, ?)",
        (name, json.dumps(composition), description),
    )
    conn.commit()


# ─── Read accessors ───────────────────────────────────────────────────────
def list_builds(conn: sqlite3.Connection) -> List[Dict]:
    rows = conn.execute("SELECT id, name, description FROM builds ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def list_branches(conn: sqlite3.Connection, build_id: int) -> List[Dict]:
    rows = conn.execute(
        "SELECT id, parent_id, label, fork_at_step FROM branches "
        "WHERE build_id = ? ORDER BY id",
        (build_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def branch_queue(conn: sqlite3.Connection, branch_id: int) -> List[Tuple[str, str]]:
    rows = conn.execute(
        "SELECT item_key, mode FROM queue_items WHERE branch_id = ? ORDER BY step_idx",
        (branch_id,),
    ).fetchall()
    return [(r["item_key"], r["mode"]) for r in rows]


def list_targets(conn: sqlite3.Connection) -> List[Dict]:
    rows = conn.execute("SELECT name, composition, description FROM targets ORDER BY name").fetchall()
    out = []
    for r in rows:
        out.append({"name": r["name"],
                    "composition": json.loads(r["composition"]),
                    "description": r["description"]})
    return out


# ─── Seed: canonical builds for the BAR opener space ─────────────────────
def seed(conn: sqlite3.Connection) -> None:
    """Populate the DB with the build paths used in eco_guide.md / eco_simulator.py."""

    # Solar opener — matches the demo in eco_simulator.py
    solar = [
        ("mex",       "build"),
        ("mex",       "build"),
        ("mex",       "build"),
        ("solar",     "build"),
        ("3.5",       "walk_delay"),
        ("mex",       "build"),
        ("solar",     "build"),
        ("t1_lab",    "build"),
        ("solar",     "build"),
        ("solar",     "build"),
        ("t1_worker", "assist"),
        ("solar",     "build"),
        ("t1_worker", "assist"),
    ]
    sb = add_build(conn, "Solar Opener",
                   "Three mex, four solars, lab, two workers. Default reference build.",
                   solar)

    # Fork: longer commander walk to match the user's observed 48s timing
    fork_branch(conn, sb, "main", "longer-walk", fork_at_step=4,
                continuation=[
                    ("10.0",      "walk_delay"),
                    ("mex",       "build"),
                    ("solar",     "build"),
                    ("t1_lab",    "build"),
                    ("solar",     "build"),
                    ("solar",     "build"),
                    ("t1_worker", "assist"),
                    ("solar",     "build"),
                    ("t1_worker", "assist"),
                ])

    # Wind opener — same metal but swap solars for winds
    wind = [
        ("mex",       "build"),
        ("mex",       "build"),
        ("mex",       "build"),
        ("wind",      "build"),
        ("wind",      "build"),
        ("3.5",       "walk_delay"),
        ("mex",       "build"),
        ("wind",      "build"),
        ("wind",      "build"),
        ("t1_lab",    "build"),
        ("wind",      "build"),
        ("wind",      "build"),
        ("t1_worker", "assist"),
        ("wind",      "build"),
        ("t1_worker", "assist"),
    ]
    add_build(conn, "Wind Opener",
              "Wind instead of solar — cheaper metal, faster up-front, swingy income.",
              wind)

    # Lab rush — minimum eco, lab as fast as possible
    rush = [
        ("mex",       "build"),
        ("mex",       "build"),
        ("solar",     "build"),
        ("t1_lab",    "build"),
        ("t1_worker", "assist"),
        ("solar",     "build"),
        ("mex",       "build"),
        ("t1_worker", "assist"),
        ("solar",     "build"),
        ("solar",     "build"),
    ]
    add_build(conn, "Lab Rush",
              "Skip the third mex and the walk — lab ASAP at the cost of slower eco.",
              rush)

    # ─── Energy-source vs. first-BP comparison ────────────────────────────
    # Each pair below races a Solar path against a Wind path to the first
    # piece of build-power production (a lab/worker, or a Con Turret).  The
    # wind value the engine uses is 11.9 E/s — a high / windy-map assumption.
    add_build(conn, "Worker Rush: Solar",
              "2 mex + 2 solar → lab → 1 worker.  Goal: first BP unit fastest.",
              [
                  ("mex",       "build"),
                  ("solar",     "build"),
                  ("mex",       "build"),
                  ("solar",     "build"),
                  ("t1_lab",    "build"),
                  ("t1_worker", "assist"),
              ])

    add_build(conn, "Worker Rush: Wind",
              "2 mex + 3 wind then lab + first worker. Wind = 11.9 E/s (windy map).",
              [
                  ("mex",       "build"),
                  ("wind",      "build"),
                  ("mex",       "build"),
                  ("wind",      "build"),
                  ("wind",      "build"),
                  ("t1_lab",    "build"),
                  ("t1_worker", "assist"),
              ])

    add_build(conn, "Turret Rush: Solar",
              "3 mex + 3 solar then a Con Turret. Commander builds it directly.",
              [
                  ("mex",       "build"),
                  ("mex",       "build"),
                  ("solar",     "build"),
                  ("solar",     "build"),
                  ("mex",       "build"),
                  ("solar",     "build"),
                  ("con_turret","build"),
              ])

    add_build(conn, "Turret Rush: Wind",
              "3 mex + 4 wind then a Con Turret. Wind = 11.9 E/s (windy map).",
              [
                  ("mex",       "build"),
                  ("mex",       "build"),
                  ("wind",      "build"),
                  ("wind",      "build"),
                  ("mex",       "build"),
                  ("wind",      "build"),
                  ("wind",      "build"),
                  ("con_turret","build"),
              ])

    add_target(conn, "Light eco",
               {"mex": 4, "solar": 4, "t1_lab": 1, "t1_worker": 2},
               "Standard opener target.")
    add_target(conn, "Pre-T2",
               {"mex": 7, "solar": 4, "wind": 12, "t1_lab": 1, "t1_worker": 4},
               "What you want sitting on before queuing a T2 lab.")
    add_target(conn, "Wind 25",
               {"mex": 4, "wind": 25, "t1_lab": 1, "t1_worker": 3},
               "25 wind from worker_analysis.py — windy-map default.")
    add_target(conn, "First Worker",
               {"t1_worker": 1},
               "Time to first piece of factory-built BP (80 BP/s).")
    add_target(conn, "First Turret",
               {"con_turret": 1},
               "Time to first piece of stationary BP (200 BP/s).")


def main() -> None:
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = connect()
    init_schema(conn)
    seed(conn)
    print(f"Initialised {DB_PATH}")
    for b in list_builds(conn):
        branches = list_branches(conn, b["id"])
        print(f"  Build #{b['id']:>2}  {b['name']:<22}  ({len(branches)} branch(es))")
    conn.close()
    try:
        shutil.copy(DB_PATH, WORKSPACE_DB)
        print(f"Copied to {WORKSPACE_DB}")
    except OSError as e:
        print(f"(could not copy: {e})")


if __name__ == "__main__":
    main()

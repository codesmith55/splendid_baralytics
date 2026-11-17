#!/usr/bin/env python3
"""ECON DB — build times in a database, and every analysis run recorded with provenance.

Two tables, two jobs.

UNIT DEFS. The engine dumps stay on disk as the source of truth, but nothing should have
to parse a JSON dump to ask "how long does an advanced lab take". `ingest_defs()` walks
the configured sources in `econ_model.json` order (later files win, exactly as the model
resolves them), writes one row per def, and records WHICH file each row won from. So a
lookup is a query, and the answer carries its own provenance.

RUNS. Every analysis is recorded as

    file_name, file_version, function_name, function_version,
    user_name, build_name, input_state, output

so the table can be searched across builds and games, and so a row whose
`function_version` no longer matches the registry is visibly STALE and can be re-run.
That is the difference between a cache and a record: a record knows when it is out of
date. `stale_runs()` lists them and `--stale` prints them.

    python bar-calc/econ_db.py --ingest              # (re)load the unit defs
    python bar-calc/econ_db.py --defs armalab armack  # look one up
    python bar-calc/econ_db.py --runs [--function cadence] [--build wind-conversion]
    python bar-calc/econ_db.py --stale               # rows a newer function version supersedes
    python bar-calc/econ_db.py --builds              # what build names have been recorded
    python bar-calc/econ_db.py --stats
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import econ_data as ED                                              # noqa: E402

VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DB_PATH = os.environ.get("BAR_ECON_DB") or os.path.join(HERE, "econ.db")
NL = chr(10)

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS unit_defs (
        def_name TEXT PRIMARY KEY,
        name TEXT,
        build_time REAL,
        metal_cost REAL,
        energy_cost REAL,
        speed REAL,
        build_power REAL,
        is_extractor INTEGER,
        metal_make REAL,
        wind_generator REAL,
        energy_production REAL,
        energy_upkeep REAL,
        available INTEGER DEFAULT 1,
        unavailable_note TEXT,
        metal_storage REAL,
        energy_storage REAL,
        size_x INTEGER,
        size_z INTEGER,
        work_pool TEXT,
        faction TEXT,
        tech_level REAL,
        is_builder INTEGER,
        is_factory INTEGER,
        can_assist INTEGER,
        build_distance REAL,
        build_options TEXT,
        aliases TEXT,
        human_name TEXT,
        source_file TEXT,
        source_version TEXT,
        ingested_at TEXT,
        raw TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS def_sources (
        source_file TEXT PRIMARY KEY,
        source_format TEXT,
        source_version TEXT,
        defs INTEGER,
        ingested_at TEXT,
        note TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        file_name TEXT NOT NULL,
        file_version TEXT NOT NULL,
        file_hash TEXT,
        function_name TEXT NOT NULL,
        function_version TEXT NOT NULL,
        user_name TEXT,
        build_name TEXT,
        game_id TEXT,
        at_sec REAL,
        input_hash TEXT NOT NULL,
        input_json TEXT NOT NULL,
        output_json TEXT NOT NULL,
        ok INTEGER NOT NULL DEFAULT 1,
        error TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS build_edges (
        builder TEXT NOT NULL,
        product TEXT NOT NULL,
        PRIMARY KEY (builder, product)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_edges_product ON build_edges(product)",
    "CREATE INDEX IF NOT EXISTS ix_defs_faction ON unit_defs(faction)",
    "CREATE INDEX IF NOT EXISTS ix_defs_tech ON unit_defs(tech_level)",
    "CREATE INDEX IF NOT EXISTS ix_runs_fn ON runs(function_name)",
    "CREATE INDEX IF NOT EXISTS ix_runs_build ON runs(build_name)",
    "CREATE INDEX IF NOT EXISTS ix_runs_game ON runs(game_id)",
    "CREATE INDEX IF NOT EXISTS ix_runs_input ON runs(input_hash)",
    "CREATE INDEX IF NOT EXISTS ix_runs_ver ON runs(function_name, function_version)",
]


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    """Open the database, creating the schema if this is the first time."""
    fresh = not os.path.exists(path)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    for stmt in SCHEMA:
        con.execute(stmt)
    con.commit()
    if fresh:
        con.execute("PRAGMA journal_mode=WAL")
    return con


# ══════════════════════════════════════════════════════════════════════════
# versions — what makes a recorded run checkable rather than merely stored
# ══════════════════════════════════════════════════════════════════════════

def file_hash(path: str) -> str:
    """Short content hash, so a run knows the exact file text it came from."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except OSError:
        return "?"


def input_hash(payload: Any) -> str:
    """Stable hash of an input, so the same question asked twice is findable."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ══════════════════════════════════════════════════════════════════════════
# unit defs
# ══════════════════════════════════════════════════════════════════════════

# Faction is derived from the defName prefix because BAR leaves
# `customParams.faction` empty on every def (843 of 844 blank in the newest harvest).
# The prefixes are the engine's own naming convention and are stable.
FACTION_PREFIXES = {"arm": "Armada", "cor": "Cortex", "leg": "Legion"}
ALIASES_PATH = os.path.join(HERE, "unit_aliases.json")
OVERRIDES_PATH = os.path.join(HERE, "unit_overrides.json")


def faction_of(def_name: str) -> str:
    """Armada, Cortex, Legion, or Other, from the def name's prefix."""
    return FACTION_PREFIXES.get((def_name or "")[:3].lower(), "Other")


def load_aliases(path: str = ALIASES_PATH) -> Dict[str, List[str]]:
    """User-given names, hand-edited. The harvest never touches this file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    except (OSError, ValueError):
        return {}
    out: Dict[str, List[str]] = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        out[k] = [str(x) for x in (v if isinstance(v, list) else [v])]
    return out


def save_aliases(aliases: Dict[str, List[str]], path: str = ALIASES_PATH) -> str:
    """Write the alias file back, keeping its note."""
    body = {"_note": ("user-given names for engine defs. Hand-edited and never "
                      "overwritten by the def harvest; econ_db.ingest_defs merges it "
                      "into the unit_defs table so every reader resolves the same "
                      "names. Add an entry as \"defName\": [\"alias\", ...].")}
    for k in sorted(aliases):
        body[k] = sorted(set(aliases[k]))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=1, ensure_ascii=False)
        fh.write(NL)
    return path


def load_overrides(path: str = OVERRIDES_PATH) -> dict:
    """Hand-edited corrections. A dump is a snapshot of one build, not the live game.

    `unavailable` names defs the live game does not offer even though a harvest found
    them, which is what happens when the dump came from a local sdd build."""
    if not os.path.exists(path):
        return {"unavailable": {}}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    except (OSError, ValueError):
        return {"unavailable": {}}
    un = raw.get("unavailable") or {}
    if isinstance(un, list):
        un = {k: "marked unavailable" for k in un}
    return {"unavailable": {str(k): str(v) for k, v in un.items()}}


def energy_flow(def_name: str, path: str = DB_PATH) -> dict:
    """Production and upkeep in E/s, from the database.

    A T1 solar reports energyProduction 0 and carries its 20 E/s as NEGATIVE upkeep, so
    this reads the resolved columns rather than the raw field."""
    r = get_def(def_name, path)
    if not r:
        return {"def": def_name, "production": None, "upkeep": None, "net": None}
    prod = float(r.get("energy_production") or 0.0)
    upk = float(r.get("energy_upkeep") or 0.0)
    return {"def": def_name, "production": prod, "upkeep": upk, "net": prod - upk}


def resolve_name(name: str, path: str = DB_PATH) -> Optional[str]:
    """A defName, a human name, or any user alias -> the defName."""
    if not name:
        return None
    con = connect(path)
    q = name.strip()
    row = con.execute("SELECT def_name FROM unit_defs WHERE def_name = ?",
                      (q,)).fetchone()
    if not row:
        row = con.execute("""SELECT def_name FROM unit_defs
                             WHERE LOWER(def_name) = LOWER(?)
                                OR LOWER(human_name) = LOWER(?)""", (q, q)).fetchone()
    if not row:
        like = "%\"" + q.lower() + "\"%"
        row = con.execute("""SELECT def_name FROM unit_defs
                             WHERE LOWER(aliases) LIKE ? LIMIT 1""", (like,)).fetchone()
    con.close()
    return row[0] if row else None


def _read_source(src: dict) -> Dict[str, dict]:
    """One configured source's defs, using econ_data's own readers.

    `engine_sources()` reports an absent glob as None, which the resolver treats as a
    path, so the keys are dropped rather than passed through as nulls."""
    clean = {k: v for k, v in src.items() if v is not None}
    paths = ED._resolve_source(clean)
    out: Dict[str, dict] = {}
    for p in paths:
        if src.get("format") == "jsonl-unit_def":
            out.update(ED._read_jsonl_unit_defs(p))
        else:
            out.update(ED._read_defs_array(p))
    return out


def _eprod(d: dict) -> float:
    """E/s produced. Negative upkeep IS production - a T1 solar's whole 20 E/s is there."""
    return max(0.0, float(d.get("energyProduction") or 0)) \
        + max(0.0, -float(d.get("energyUpkeep") or 0))


def _eupkeep(d: dict) -> float:
    """E/s consumed to run."""
    return max(0.0, float(d.get("energyUpkeep") or 0))


def _pool_of(d: dict) -> str:
    """Which build-power pool makes this: extractor -> expand, mobile -> factory."""
    if d.get("isMetalExtractor") or d.get("extractsMetal"):
        return "expand"
    try:
        if float(d.get("speed") or 0) > 0:
            return "factory"
    except (TypeError, ValueError):
        pass
    return "base"


def _num(d: dict, *keys) -> Optional[float]:
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return None


def ingest_defs(path: str = DB_PATH, verbose: bool = True) -> dict:
    """Load every configured engine dump into the database, later sources winning."""
    con = connect(path)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    srcs = ED.engine_sources()
    con.execute("DELETE FROM unit_defs")
    con.execute("DELETE FROM def_sources")
    con.execute("DELETE FROM build_edges")
    aliases = load_aliases()
    overrides = load_overrides()
    gone = overrides.get("unavailable") or {}
    total = 0
    for src in srcs:
        if not src.get("present"):
            continue
        defs = _read_source(src)
        rel = src.get("path")
        ver = os.path.basename(ED.latest_units_file() or "") if src.get("glob") else rel
        for name, d in defs.items():
            opts = str(d.get("buildOptions") or "")
            con.execute(
                """INSERT INTO unit_defs (def_name, name, build_time, metal_cost,
                   energy_cost, speed, build_power, is_extractor, metal_make,
                   wind_generator, metal_storage, energy_storage, size_x, size_z,
                   work_pool, faction, tech_level, is_builder, is_factory, can_assist,
                   build_distance, build_options, aliases, human_name,
                   energy_production, energy_upkeep, available, unavailable_note,
                   source_file, source_version, ingested_at, raw)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(def_name) DO UPDATE SET
                     faction=excluded.faction, tech_level=excluded.tech_level,
                     is_builder=excluded.is_builder, is_factory=excluded.is_factory,
                     can_assist=excluded.can_assist,
                     build_distance=excluded.build_distance,
                     build_options=excluded.build_options,
                     aliases=excluded.aliases, human_name=excluded.human_name,
                     energy_production=excluded.energy_production,
                     energy_upkeep=excluded.energy_upkeep,
                     available=excluded.available,
                     unavailable_note=excluded.unavailable_note,
                     name=excluded.name, build_time=excluded.build_time,
                     metal_cost=excluded.metal_cost, energy_cost=excluded.energy_cost,
                     speed=excluded.speed, build_power=excluded.build_power,
                     is_extractor=excluded.is_extractor, metal_make=excluded.metal_make,
                     wind_generator=excluded.wind_generator,
                     metal_storage=excluded.metal_storage,
                     energy_storage=excluded.energy_storage,
                     size_x=excluded.size_x, size_z=excluded.size_z,
                     work_pool=excluded.work_pool, source_file=excluded.source_file,
                     source_version=excluded.source_version,
                     ingested_at=excluded.ingested_at, raw=excluded.raw""",
                (name, d.get("name") or d.get("tooltip"),
                 _num(d, "buildTime"), _num(d, "metalCost"), _num(d, "energyCost"),
                 _num(d, "speed"), _num(d, "buildPower", "builderBp"),
                 1 if (d.get("isMetalExtractor") or d.get("extractsMetal")) else 0,
                 _num(d, "metalMake"), _num(d, "windGenerator"),
                 _num(d, "metalStorage"), _num(d, "energyStorage"),
                 _num(d, "sizeX"), _num(d, "sizeZ"), _pool_of(d),
                 faction_of(name), _num(d, "techLevel"),
                 1 if d.get("isBuilder") else 0, 1 if d.get("isFactory") else 0,
                 1 if d.get("canAssist") else 0, _num(d, "buildDistance"),
                 opts, json.dumps(aliases.get(name, [])), d.get("name"),
                 _eprod(d), _eupkeep(d),
                 0 if name in gone else 1, gone.get(name),
                 rel, ver, now,
                 json.dumps(d, separators=(",", ":"), default=str)))
            for prod in (x.strip() for x in opts.split(",")):
                if prod:
                    con.execute("""INSERT OR IGNORE INTO build_edges (builder, product)
                                   VALUES (?,?)""", (name, prod))
        con.execute("""INSERT INTO def_sources
                       (source_file, source_format, source_version, defs, ingested_at, note)
                       VALUES (?,?,?,?,?,?)
                       ON CONFLICT(source_file) DO UPDATE SET
                         defs=excluded.defs, ingested_at=excluded.ingested_at""",
                    (rel, src.get("format"), ver, len(defs), now, src.get("note")))
        total += len(defs)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM unit_defs").fetchone()[0]
    miss = con.execute(
        "SELECT COUNT(*) FROM unit_defs WHERE build_time IS NULL OR build_time <= 0"
    ).fetchone()[0]
    edges = con.execute("SELECT COUNT(*) FROM build_edges").fetchone()[0]
    builders = con.execute(
        "SELECT COUNT(*) FROM unit_defs WHERE build_options <> ''").fetchone()[0]
    unavail = con.execute(
        "SELECT COUNT(*) FROM unit_defs WHERE available = 0").fetchone()[0]
    out = {"db": path, "sources": len(srcs), "rows_written": total, "defs": n,
           "without_build_time": miss, "build_edges": edges,
           "defs_with_options": builders, "aliases": len(aliases),
           "unavailable": unavail, "overrides": len(gone)}
    if verbose:
        print("INGEST  " + path)
        for r in con.execute("SELECT * FROM def_sources ORDER BY rowid"):
            print("  " + str(r["defs"]).rjust(5) + " defs from " + r["source_file"]
                  + "   (" + str(r["source_format"]) + ")")
        print("  -> " + str(n) + " distinct defs, " + str(miss) + " with no build time")
        by = con.execute("""SELECT work_pool, COUNT(*) n FROM unit_defs
                            GROUP BY work_pool ORDER BY n DESC""").fetchall()
        print("  pools: " + ", ".join(r["work_pool"] + " " + str(r["n"]) for r in by))
        fa = con.execute("""SELECT faction, COUNT(*) n FROM unit_defs
                            GROUP BY faction ORDER BY n DESC""").fetchall()
        print("  factions: " + ", ".join(str(r["faction"]) + " " + str(r["n"])
                                         for r in fa))
        tl = con.execute("""SELECT tech_level, COUNT(*) n FROM unit_defs
                            WHERE tech_level IS NOT NULL AND tech_level > 0
                            GROUP BY tech_level ORDER BY tech_level""").fetchall()
        print("  tech levels: " + ", ".join("T" + ("%g" % r["tech_level"]) + " "
                                            + str(r["n"]) for r in tl))
        print("  build tree: " + str(edges) + " edges from " + str(builders)
              + " builders" + ("   (" + str(len(aliases)) + " alias entries merged)"
                               if aliases else "   (no alias file yet)"))
        sol = con.execute("""SELECT def_name, energy_production, wind_generator
                             FROM unit_defs
                             WHERE def_name IN ('armsolar','armadvsol','armfus','armwin')
                             ORDER BY def_name""").fetchall()
        if sol:
            # a turbine has no fixed output: windGenerator is the map-wind CEILING, and
            # the real figure is the wind vector's length (bar_unified section 3)
            parts = []
            for r in sol:
                if (r["wind_generator"] or 0) > 0:
                    parts.append(str(r["def_name"]) + " up to "
                                 + ("%g" % r["wind_generator"]) + " E/s on map wind")
                else:
                    parts.append(str(r["def_name"]) + " "
                                 + ("%g" % (r["energy_production"] or 0)) + " E/s")
            print("  energy check: " + ", ".join(parts))
        if unavail:
            print("  marked UNAVAILABLE by unit_overrides.json: " + str(unavail))
            for r in con.execute("""SELECT def_name, unavailable_note FROM unit_defs
                                    WHERE available = 0"""):
                print("    " + str(r["def_name"]) + ": "
                      + str(r["unavailable_note"])[:96])
        if not edges:
            print("  NO BUILD TREE: the dump predates the buildOptions patch. Re-harvest")
            print("  with a Legion-enabled game: --find-demo then --harvest-defs")
    con.close()
    return out


def build_time(def_name: str, path: str = DB_PATH) -> Optional[float]:
    """Build work in BP-seconds for one engine def, from the database."""
    con = connect(path)
    r = con.execute("SELECT build_time FROM unit_defs WHERE def_name = ?",
                    (def_name,)).fetchone()
    con.close()
    return None if not r or r[0] is None else float(r[0])


def get_def(def_name: str, path: str = DB_PATH) -> Optional[dict]:
    """One def's row, with the file it won from."""
    con = connect(path)
    r = con.execute("SELECT * FROM unit_defs WHERE def_name = ?", (def_name,)).fetchone()
    con.close()
    return dict(r) if r else None


def defs_table(path: str = DB_PATH) -> Dict[str, dict]:
    """Every def as a dict, for callers that want the whole table in memory."""
    con = connect(path)
    rows = {r["def_name"]: dict(r) for r in con.execute("SELECT * FROM unit_defs")}
    con.close()
    return rows


def ensure_defs(path: str = DB_PATH, verbose: bool = False) -> int:
    """Ingest on first use, so no caller has to remember to seed the database."""
    con = connect(path)
    n = con.execute("SELECT COUNT(*) FROM unit_defs").fetchone()[0]
    con.close()
    if n == 0:
        ingest_defs(path, verbose=verbose)
        con = connect(path)
        n = con.execute("SELECT COUNT(*) FROM unit_defs").fetchone()[0]
        con.close()
    return n


# ══════════════════════════════════════════════════════════════════════════
# runs
# ══════════════════════════════════════════════════════════════════════════

def record_run(function_name: str, function_version: str, file_name: str,
               file_version: str, inputs: dict, output: Any,
               user_name: Optional[str] = None, build_name: Optional[str] = None,
               game_id: Optional[str] = None, at_sec: Optional[float] = None,
               ok: bool = True, error: Optional[str] = None,
               file_path: Optional[str] = None, path: str = DB_PATH) -> int:
    """Record one analysis: who ran, at what version, on what state, and what came out."""
    con = connect(path)
    cur = con.execute(
        """INSERT INTO runs (ts, file_name, file_version, file_hash, function_name,
           function_version, user_name, build_name, game_id, at_sec, input_hash,
           input_json, output_json, ok, error)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (time.strftime("%Y-%m-%d %H:%M:%S"), file_name, file_version,
         file_hash(file_path) if file_path else None, function_name, function_version,
         user_name, build_name, game_id, at_sec, input_hash(inputs),
         json.dumps(inputs, sort_keys=True, separators=(",", ":"), default=str),
         json.dumps(output, separators=(",", ":"), default=str),
         1 if ok else 0, error))
    con.commit()
    rid = int(cur.lastrowid)
    con.close()
    return rid


def find_runs(function: Optional[str] = None, build: Optional[str] = None,
              user: Optional[str] = None, game: Optional[str] = None,
              inputs: Optional[dict] = None, limit: int = 50,
              with_output: bool = False, path: str = DB_PATH) -> List[dict]:
    """Search the record. Any combination of function, build name, user, game, input."""
    con = connect(path)
    where, args = [], []
    if function:
        where.append("function_name = ?")
        args.append(function)
    if build:
        where.append("build_name LIKE ?")
        args.append("%" + build + "%")
    if user:
        where.append("user_name LIKE ?")
        args.append("%" + user + "%")
    if game:
        where.append("game_id LIKE ?")
        args.append("%" + game + "%")
    if inputs is not None:
        where.append("input_hash = ?")
        args.append(input_hash(inputs))
    sql = "SELECT * FROM runs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    rows = []
    for r in con.execute(sql, args):
        d = dict(r)
        d["input"] = json.loads(d["input_json"])
        if with_output:
            d["output"] = json.loads(d["output_json"])
        d.pop("input_json", None)
        d.pop("output_json", None)
        rows.append(d)
    con.close()
    return rows


def latest_run(function: str, inputs: dict, function_version: Optional[str] = None,
               path: str = DB_PATH) -> Optional[dict]:
    """The most recent answer to this exact question, optionally at a given version.

    Passing `function_version` is how a caller says "only if it is not stale"."""
    con = connect(path)
    sql = """SELECT * FROM runs WHERE function_name = ? AND input_hash = ? AND ok = 1"""
    args: List[Any] = [function, input_hash(inputs)]
    if function_version:
        sql += " AND function_version = ?"
        args.append(function_version)
    sql += " ORDER BY id DESC LIMIT 1"
    r = con.execute(sql, args).fetchone()
    con.close()
    if not r:
        return None
    d = dict(r)
    d["input"] = json.loads(d.pop("input_json"))
    d["output"] = json.loads(d.pop("output_json"))
    return d


def stale_runs(current: Dict[str, str], limit: int = 200,
               path: str = DB_PATH) -> List[dict]:
    """Recorded runs a newer version of their function supersedes.

    `current` maps function name to the version the registry now declares. A row whose
    recorded version differs is not wrong, it is OLD, and the conclusion drawn from it
    should be recomputed before it is trusted again."""
    con = connect(path)
    rows = []
    for r in con.execute("""SELECT function_name, function_version, COUNT(*) n,
                                   MIN(ts) first_ts, MAX(ts) last_ts
                            FROM runs GROUP BY function_name, function_version"""):
        now = current.get(r["function_name"])
        if now is None:
            rows.append({"function": r["function_name"], "recorded": r["function_version"],
                         "current": None, "runs": r["n"], "status": "function gone",
                         "first": r["first_ts"], "last": r["last_ts"]})
        elif now != r["function_version"]:
            rows.append({"function": r["function_name"], "recorded": r["function_version"],
                         "current": now, "runs": r["n"], "status": "STALE - rerun",
                         "first": r["first_ts"], "last": r["last_ts"]})
    con.close()
    return rows[:limit]


def builds(path: str = DB_PATH) -> List[dict]:
    """Every build name the record has seen, and what has been computed for it."""
    con = connect(path)
    rows = [dict(r) for r in con.execute(
        """SELECT build_name, COUNT(*) runs, COUNT(DISTINCT function_name) functions,
                  COUNT(DISTINCT game_id) games, MIN(ts) first_ts, MAX(ts) last_ts
           FROM runs WHERE build_name IS NOT NULL
           GROUP BY build_name ORDER BY runs DESC""")]
    con.close()
    return rows


def compare_runs(function: str, field: str, group_by: str = "build_name",
                 limit: int = 500, path: str = DB_PATH) -> List[dict]:
    """Pull one output field out of every recorded run of a function and group it.

    This is what turns the record into a dataset: ask for `path` / `ratio.per_cross`
    grouped by build, and the table answers across every game it has seen. `field` is a
    dotted path into the stored output. Rows carry the recorded version, so a mixed-
    version comparison is visible rather than silent."""
    con = connect(path)
    rows = []
    for r in con.execute("""SELECT * FROM runs WHERE function_name = ? AND ok = 1
                            ORDER BY id DESC LIMIT ?""", (function, int(limit))):
        try:
            val: Any = json.loads(r["output_json"])
        except (TypeError, ValueError):
            continue
        for part in field.split("."):
            if isinstance(val, dict) and part in val:
                val = val[part]
            elif isinstance(val, list) and part.isdigit() and int(part) < len(val):
                val = val[int(part)]
            else:
                val = None
                break
        rows.append({"group": r[group_by], "value": val, "game_id": r["game_id"],
                     "at_sec": r["at_sec"], "version": r["function_version"],
                     "ts": r["ts"], "id": r["id"]})
    con.close()
    return rows


def print_compare(function: str, field: str, group_by: str = "build_name",
                  path: str = DB_PATH) -> List[dict]:
    """The comparison as a table, with per-group numeric summaries where possible."""
    rows = compare_runs(function, field, group_by, path=path)
    if not rows:
        print("no recorded runs of " + function + " carry " + field)
        return rows
    print("COMPARE  " + function + " -> " + field + "   grouped by " + group_by)
    groups: Dict[str, list] = {}
    for r in rows:
        groups.setdefault(str(r["group"]), []).append(r)
    print("  " + "group".ljust(28) + "n".rjust(4) + "  versions   value(s)")
    for g, rs in sorted(groups.items()):
        vers = sorted({r["version"] for r in rs})
        nums = [r["value"] for r in rs if isinstance(r["value"], (int, float))]
        if nums:
            lo, hi = min(nums), max(nums)
            summary = ("mean " + ("%.2f" % (sum(nums) / len(nums)))
                       + "  range " + ("%.2f" % lo) + "-" + ("%.2f" % hi))
        else:
            vals = [str(r["value"]) for r in rs if r["value"] is not None]
            uniq = sorted(set(vals))
            summary = ", ".join(uniq[:3]) + (" ..." if len(uniq) > 3 else "")
        print("  " + g.ljust(28) + str(len(rs)).rjust(4) + "  "
              + ",".join(vers).ljust(10) + "  " + summary)
        if len(vers) > 1:
            print("  " + " " * 28 + "      MIXED VERSIONS - rerun before comparing")
    return rows


def stats(path: str = DB_PATH) -> dict:
    """What is in the database."""
    con = connect(path)

    def one(sql: str, *a):
        r = con.execute(sql, a).fetchone()
        return r[0] if r else 0

    out = {"db": path, "defs": one("SELECT COUNT(*) FROM unit_defs"),
           "def_sources": one("SELECT COUNT(*) FROM def_sources"),
           "runs": one("SELECT COUNT(*) FROM runs"),
           "functions": one("SELECT COUNT(DISTINCT function_name) FROM runs"),
           "builds": one("SELECT COUNT(DISTINCT build_name) FROM runs WHERE build_name IS NOT NULL"),
           "games": one("SELECT COUNT(DISTINCT game_id) FROM runs WHERE game_id IS NOT NULL"),
           "size_kb": round(os.path.getsize(path) / 1024, 1) if os.path.exists(path) else 0}
    out["by_function"] = [dict(r) for r in con.execute(
        """SELECT function_name, function_version, COUNT(*) n, MAX(ts) last_ts
           FROM runs GROUP BY function_name, function_version ORDER BY n DESC""")]
    con.close()
    return out


def selftest(path: Optional[str] = None, verbose: bool = True) -> bool:
    """Round-trip the schema on a scratch database: defs, a run, search, staleness."""
    import tempfile
    tmp = path or os.path.join(tempfile.gettempdir(), "econ_db_selftest.db")
    if os.path.exists(tmp):
        os.unlink(tmp)
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print("  FAIL " + msg)

    ing = ingest_defs(tmp, verbose=False)
    check(ing["defs"] > 500, "expected the full def table, got " + str(ing["defs"]))
    check(build_time("armalab", tmp) == 25000.0,
          "armalab build time should be 25000, got " + str(build_time("armalab", tmp)))
    check(build_time("armmex", tmp) == 1800.0,
          "armmex build time should be 1800, got " + str(build_time("armmex", tmp)))
    row = get_def("armmex", tmp)
    check(row and row["work_pool"] == "expand", "armmex should be expand work")
    row = get_def("armck", tmp)
    check(row and row["work_pool"] == "factory", "armck should be factory work")
    row = get_def("armnanotc", tmp)
    check(row and row["work_pool"] == "base", "a con turret should be base work")
    check(build_time("no_such_def", tmp) is None, "an unknown def should return None")

    # a T1 solar makes 20 E/s and reports it as NEGATIVE upkeep. Any reader that trusts
    # `energyProduction` alone sees a solar producing nothing, which is what the first
    # cut of this table did.
    sol = energy_flow("armsolar", tmp)
    check(sol["production"] == 20.0, "armsolar should produce 20 E/s, got "
          + str(sol["production"]))
    check(sol["net"] == 20.0, "armsolar net should be +20 E/s")
    check(energy_flow("armadvsol", tmp)["production"] == 80.0,
          "advanced solar should produce 80 E/s")
    check(energy_flow("armmex", tmp)["net"] == -3.0,
          "an Armada extractor should net -3 E/s")
    check(energy_flow("legmex", tmp)["net"] == 7.0,
          "a Legion extractor should net +7 E/s, it PRODUCES energy")
    wind = get_def("armwin", tmp)
    check((wind or {}).get("energy_production") == 0.0
          and (wind or {}).get("wind_generator") == 25.0,
          "a turbine has no fixed output: 0 production, windGenerator 25 as the ceiling")

    inp = {"state": {"m_inc": 9.0, "bp": 610}, "target": "Wind"}
    rid = record_run("cadence", "1.0", "bar_unified.py", "1.0.0", inp,
                     {"median": 2.6}, user_name="me", build_name="wind-conversion",
                     game_id="g1", at_sec=90.0, path=tmp)
    check(rid > 0, "record_run returned no id")
    found = find_runs(function="cadence", path=tmp, with_output=True)
    check(len(found) == 1 and found[0]["build_name"] == "wind-conversion",
          "the run did not come back from a search")
    check(found[0]["output"]["median"] == 2.6, "the output did not round-trip")
    check(latest_run("cadence", inp, "1.0", tmp) is not None,
          "latest_run missed an exact input match")
    check(latest_run("cadence", inp, "9.9", tmp) is None,
          "latest_run must not return a different version when one is demanded")
    check(latest_run("cadence", {"state": {"m_inc": 1.0}}, None, tmp) is None,
          "a different input must not match")
    st = stale_runs({"cadence": "2.0"}, path=tmp)
    check(len(st) == 1 and st[0]["status"].startswith("STALE"),
          "a version bump must show as stale")
    check(not stale_runs({"cadence": "1.0"}, path=tmp),
          "the same version must not be stale")
    check(stale_runs({}, path=tmp)[0]["status"] == "function gone",
          "a removed function should be reported")
    b = builds(tmp)
    check(len(b) == 1 and b[0]["runs"] == 1, "build listing is wrong")
    check(stats(tmp)["runs"] == 1, "stats miscounted runs")
    os.unlink(tmp)
    print("selftest OK: defs, runs, search, versioning" if ok else "selftest FAILED")
    return ok


def _cli(argv: Sequence[str]) -> None:
    def opt(flag, default=None, cast=str):
        if flag in argv:
            i = list(argv).index(flag)
            if i + 1 < len(argv):
                return cast(argv[i + 1])
        return default

    if "--selftest" in argv:
        sys.exit(0 if selftest() else 1)
    if "--ingest" in argv:
        ingest_defs()
        return
    if "--defs" in argv:
        ensure_defs()
        names = [a for a in argv[list(argv).index("--defs") + 1:] if not a.startswith("-")]
        if not names:
            print("usage: --defs <defName> [defName ...]")
            return
        print("  " + "def".ljust(14) + "build".rjust(8) + "metal".rjust(7)
              + "energy".rjust(8) + "  pool     from")
        for n in names:
            r = get_def(n)
            if not r:
                print("  " + n.ljust(14) + "  not in the database")
                continue
            print("  " + n.ljust(14) + ("%8.0f" % (r["build_time"] or 0))
                  + ("%7.0f" % (r["metal_cost"] or 0))
                  + ("%8.0f" % (r["energy_cost"] or 0))
                  + "  " + str(r["work_pool"]).ljust(8) + " " + str(r["source_file"]))
        return
    if "--runs" in argv:
        rows = find_runs(function=opt("--function"), build=opt("--build"),
                         user=opt("--user"), game=opt("--game"),
                         limit=int(opt("--limit", 30, int)))
        if not rows:
            print("no recorded runs match")
            return
        print("  " + "id".rjust(5) + "  " + "when".ljust(20) + "function".ljust(18)
              + "ver".ljust(7) + "build".ljust(22) + "game".ljust(18) + "at")
        for r in rows:
            print("  " + str(r["id"]).rjust(5) + "  " + str(r["ts"]).ljust(20)
                  + str(r["function_name"]).ljust(18)
                  + str(r["function_version"]).ljust(7)
                  + str(r["build_name"] or "-").ljust(22)
                  + str(r["game_id"] or "-").ljust(18)
                  + (("%.0f" % r["at_sec"]) + "s" if r["at_sec"] is not None else "-"))
        return
    if "--stale" in argv:
        try:
            import econ_api
            current = {n: c.version for n, c in econ_api.CAPABILITIES.items()}
        except Exception as exc:                                   # noqa: BLE001
            print("could not read the capability registry: " + str(exc))
            current = {}
        rows = stale_runs(current)
        if not rows:
            print("nothing stale: every recorded run matches the current version")
            return
        print("  " + "function".ljust(18) + "recorded".ljust(10) + "current".ljust(10)
              + "runs".rjust(6) + "  status")
        for r in rows:
            print("  " + str(r["function"]).ljust(18) + str(r["recorded"]).ljust(10)
                  + str(r["current"] or "-").ljust(10) + str(r["runs"]).rjust(6)
                  + "  " + r["status"])
        return
    if "--compare" in argv:
        fn = opt("--compare")
        fld = opt("--field", "ratio.per_cross")
        print_compare(fn, fld, opt("--group", "build_name"))
        return
    if "--builds" in argv:
        rows = builds()
        if not rows:
            print("no build names recorded yet")
            return
        print("  " + "build".ljust(30) + "runs".rjust(6) + "functions".rjust(10)
              + "games".rjust(7) + "  last")
        for r in rows:
            print("  " + str(r["build_name"]).ljust(30) + str(r["runs"]).rjust(6)
                  + str(r["functions"]).rjust(10) + str(r["games"]).rjust(7)
                  + "  " + str(r["last_ts"]))
        return
    st = stats()
    print("ECON DB  " + st["db"] + "   " + str(st["size_kb"]) + " kb")
    print("  " + str(st["defs"]) + " unit defs from " + str(st["def_sources"])
          + " sources   " + str(st["runs"]) + " recorded runs across "
          + str(st["functions"]) + " functions, " + str(st["builds"]) + " builds, "
          + str(st["games"]) + " games")
    if st["by_function"]:
        print()
        print("  " + "function".ljust(20) + "ver".ljust(8) + "runs".rjust(6) + "  last")
        for r in st["by_function"]:
            print("  " + str(r["function_name"]).ljust(20)
                  + str(r["function_version"]).ljust(8) + str(r["n"]).rjust(6)
                  + "  " + str(r["last_ts"]))


if __name__ == "__main__":
    _cli(sys.argv[1:])

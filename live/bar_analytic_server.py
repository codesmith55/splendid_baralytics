#!/usr/bin/env python3
"""bar_analytic_server.py — realtime consumer for bar_analytic_live.lua.

Tails the widget's JSONL stream, maintains per-team economy state, and serves:
  GET /            -> dashboard.html (live SVG dashboard)
  GET /api/state   -> current aggregated snapshot (JSON), polled by the dashboard

Stdlib only.  Run:  python bar_analytic_server.py [--path FILE] [--port 8787]
"""
import argparse, glob, json, os, shutil, subprocess, sys, threading, time, urllib.parse
from datetime import datetime, timezone
try: sys.stdout.reconfigure(encoding="utf-8")   # Windows console defaults to cp1252
except Exception: pass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Optional: economy analysis (positions/state_api.py, meta_log.py, navigator.py)
_POSITIONS_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'positions'))
if _POSITIONS_DIR not in sys.path:
    sys.path.insert(0, _POSITIONS_DIR)
try:
    from state_api import (
        state_from_dict, state_to_dict, api_all_roi, api_t2_wealth,
        t2_wealth, project_to_t2,
    )
    from meta_log  import check as notable_check, summarize as notable_summarize
    from navigator import step_options, project_strategies, STRATEGIES
    _ANALYSIS_AVAILABLE = True
except ImportError as _e:
    _ANALYSIS_AVAILABLE = False
    print(f'[bar_analytic_server] economy analysis unavailable: {_e}')

try:
    from aberrant_log import (
        check_aberrant, check_unit_event, load_chat_context,
        AberrantStore, total_player_value,
        WEAPON_RECLAIM, WEAPON_SELFDEST,
    )
    _ABERRANT_AVAILABLE = True
except ImportError as _e:
    _ABERRANT_AVAILABLE = False
    print(f'[bar_analytic_server] aberrant detection unavailable: {_e}')

DEFAULT_PATH = "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data/bar_analytic_live.jsonl"
HERE = os.path.dirname(os.path.abspath(__file__))

BUCKET_FIELDS = [
    ("military", "militaryValue"), ("defense", "defenseValue"),
    ("build_power", "buildPowerValue"), ("economy", "ecoValue"),
    ("infrastructure", "infraValue"), ("commander", "commanderValue"),
    ("support", "supportValue"), ("other", "otherValue"),
]

# Per-minute snapshot recall: directory + the team fields a minute-to-minute diff reports on.
SNAP_DIR = os.path.join(HERE, "snapshots")
GAMES_DIR = os.path.join(HERE, "games")   # archived per-game JSONL recordings (re-analyzable)
FRAMES_PER_MINUTE = 30 * 60        # engine runs at 30 fps → 1800 frames per game-minute
EARLY_FRAME_LIMIT = 30 * 60 * 8    # retain unit-creation log for the first 8 min (build classify)

try:
    from build_classifier import classify_build
    _BUILD_AVAILABLE = True
except ImportError as _e:
    _BUILD_AVAILABLE = False
    print(f"[bar_analytic_server] build classifier unavailable: {_e}")
# Pure analysis functions (team_state / compare_minutes / project_team) and the analysis
# REGISTRY now live in analyses.py — the source-agnostic registry. Imported here so the
# existing GET endpoints keep working; POST /api/run composes the registry.
from analyses import (                                       # noqa: E402
    team_state, compare_minutes, project_team, REGISTRY, run as run_analyses,
)


class Live:
    def __init__(self):
        self.lock = threading.Lock()
        self.source = None        # file currently being tailed (set by tail_thread)
        self.aberrant_store = AberrantStore() if _ABERRANT_AVAILABLE else None
        self.reset()

    def reset(self):
        self.session = {"isSpectator": None, "fullView": None, "mapName": "",
                        "mapSizeX": 0, "mapSizeZ": 0}
        self.teams = {}          # teamID -> meta {name, allyTeamID, side, isAI}
        self.stats = {}          # teamID -> latest extra_stat_update
        self.prev_stats = {}     # teamID -> previous extra_stat_update (for delta detection)
        self.unit_defs = {}      # defID  -> {defName, metalCost, value, bucket}
        self.builders = {}   # uid -> {teamID, defID, x, z, idle, building, frame}
        self.dead = set()
        self.frame = 0
        self.wind = None
        self.over = False
        self.game_id = None
        self.winners = None
        self.shares = {}          # "fromTeam>toTeam" -> {fromTeam,toTeam,donation,overflow,total,lastFrame}
        self.build_log = {}       # teamID -> ordered [{frame,defID,defName}] for build classification
        self.t2_frame = {}        # allyTeamID -> frame the team first reached T2 (from t2_reached poll)
        self.minute_snaps = {}    # game-minute (int) -> full snapshot dict, for recall + compare
        self._last_min = -1       # highest game-minute captured so far
        self.started_wall = time.time()   # wall-clock when tracking of this game began
        if self.aberrant_store is not None:
            self.aberrant_store.clear()

    def apply(self, ev):
        a = ev.get("action")
        ab_detected  = []    # from extra_stat_update delta checks
        ab_unit_info = None  # (ev, unit_info) for unit_killed events

        with self.lock:
            if a == "init":
                self.reset()
            elif a == "session":
                self.session.update({k: ev.get(k) for k in ("isSpectator", "fullView", "mapName")})
            elif a == "session_team":
                self.teams[ev["teamID"]] = {
                    "name": ev.get("name", "?"), "allyTeamID": ev.get("allyTeamID"),
                    "side": ev.get("side", ""), "isAI": ev.get("isAI", False),
                    "startX": ev.get("startX", -1), "startZ": ev.get("startZ", -1),
                }
            elif a == "unit_def":
                did = ev.get("defID")
                if did is not None:
                    self.unit_defs[did] = {
                        "defName":   ev.get("defName", ""),
                        "metalCost": ev.get("metalCost", 0) or 0,
                        "value":     ev.get("value", 0) or 0,
                        "bucket":    ev.get("bucket", "other"),
                        "isFactory":        ev.get("isFactory", False),
                        "isMetalExtractor": ev.get("isMetalExtractor", False),
                        "isCommander":      ev.get("isCommander", False),
                        "energyConversionCapacity": ev.get("energyConversionCapacity", 0) or 0,
                        "buildPower":       ev.get("buildPower", 0) or 0,
                    }
            elif a == "extra_stat_update":
                tid  = ev["teamID"]
                prev = self.stats.get(tid)
                self.stats[tid] = ev
                self.frame = max(self.frame, ev.get("frame", 0))
                if _ABERRANT_AVAILABLE and self.aberrant_store is not None and prev is not None:
                    ab_detected = check_aberrant(prev, ev)
            elif a == "team_spawn":
                m = self.teams.setdefault(ev["teamID"], {})
                m["startX"] = ev.get("startX", -1); m["startZ"] = ev.get("startZ", -1)
            elif a == "wind_update":
                self.wind = ev.get("value")
            elif a == "builder_status":
                uid = ev["unitID"]
                self.builders[uid] = {
                    "unitID": uid, "teamID": ev["teamID"],
                    "defID": ev.get("defID"), "x": ev.get("x", -1), "z": ev.get("z", -1),
                    "building": ev.get("building", False), "idle": ev.get("idle", False),
                    "frame": ev.get("frame", self.frame),
                }
            elif a == "t2_reached":
                ally = ev.get("allyTeamID")
                fr   = ev.get("frame", self.frame)
                if ally is not None:
                    self.t2_frame[ally] = min(self.t2_frame.get(ally, fr), fr)
            elif a == "unit_created":
                tid = ev.get("teamID")
                fr  = ev.get("frame", self.frame)
                if tid is not None and fr <= EARLY_FRAME_LIMIT:
                    log = self.build_log.setdefault(tid, [])
                    if len(log) < 400:           # bound: opening + early army is plenty
                        log.append({"frame": fr, "defID": ev.get("defID"),
                                    "defName": ev.get("defName", "")})
            elif a == "unit_killed":
                self.builders.pop(ev.get("unitID"), None)
                if _ABERRANT_AVAILABLE and self.aberrant_store is not None:
                    did = ev.get("defID")
                    ab_unit_info = (ev, dict(self.unit_defs.get(did, {})))
            elif a in ("resource_share", "energy_share"):   # energy_share kept for back-compat
                frm, to = ev.get("fromTeam"), ev.get("toTeam")
                res  = ev.get("resource", "energy")
                amt  = ev.get("amount", ev.get("energy", 0)) or 0
                kind = ev.get("kind", "overflow")
                rec  = self.shares.setdefault(f"{frm}>{to}>{res}", {
                    "fromTeam": frm, "toTeam": to, "resource": res,
                    "donation": 0.0, "overflow": 0.0, "total": 0.0,
                    "sent": 0.0, "received": 0.0, "taxed": 0.0, "lastFrame": 0,
                })
                rec[kind] = rec.get(kind, 0.0) + amt
                rec["total"]    += amt
                rec["sent"]     += ev.get("sent", amt) or amt
                rec["received"] += ev.get("received", amt) or amt
                rec["taxed"]    += ev.get("taxed", 0) or 0
                rec["lastFrame"] = max(rec["lastFrame"], ev.get("frame", self.frame))
            elif a == "team_died":
                self.dead.add(ev["teamID"])
            elif a == "game_id":
                self.game_id = ev.get("gameID")
            elif a == "end":
                self.over = True
                self.winners = ev.get("winners")
            elif a == "start":
                if ev.get("mapSizeX"): self.session["mapSizeX"] = ev.get("mapSizeX")
                if ev.get("mapSizeZ"): self.session["mapSizeZ"] = ev.get("mapSizeZ")

        # Outside lock: process detections (no IO under the game-state lock)
        if _ABERRANT_AVAILABLE and self.aberrant_store is not None:
            for ab_ev in ab_detected:
                self.aberrant_store.add(ab_ev)
            if ab_unit_info is not None:
                unit_ev, unit_info = ab_unit_info
                for ab_ev in check_unit_event(unit_ev, unit_info):
                    self.aberrant_store.add(ab_ev)

    def snapshot(self):
        with self.lock:
            teams = []
            max_total = 1.0
            max_inc = 1.0
            for tid, s in self.stats.items():
                meta = self.teams.get(tid, {})
                buckets = {name: s.get(field, 0) or 0 for name, field in BUCKET_FIELDS}
                total = s.get("totalValue", 0) or 0
                mi = s.get("metalIncome", 0) or 0
                ei = s.get("energyIncome", 0) or 0
                max_total = max(max_total, total)
                max_inc = max(max_inc, mi, ei)
                team_builders = [b for b in self.builders.values() if b["teamID"] == tid]
                teams.append({
                    "teamID": tid,
                    "name": meta.get("name", str(tid)),
                    "allyTeamID": meta.get("allyTeamID", 0),
                    "side": meta.get("side", ""),
                    "startX": meta.get("startX", -1), "startZ": meta.get("startZ", -1),
                    "dead": tid in self.dead,
                    "total": total,
                    "buckets": buckets,
                    "constructionValue": s.get("constructionValue", 0) or 0,
                    "storageValue": s.get("storageValue", 0) or 0,
                    "metalCurrent": s.get("metalCurrent", 0) or 0,
                    "metalStorage": s.get("metalStorage", 0) or 0,
                    "energyCurrent": s.get("energyCurrent", 0) or 0,
                    "energyStorage": s.get("energyStorage", 0) or 0,
                    "metalIncome": mi, "energyIncome": ei,
                    "bpAvail": s.get("buildPowerAvailable", 0) or 0,
                    "bpUsed": s.get("buildPowerUsed", 0) or 0,
                    "nMex": s.get("nMex", 0) or 0,
                    "nConv": s.get("nConv", 0) or 0,
                    "nUnitsCompleted": s.get("nUnitsCompleted", 0) or 0,
                    "totalPlayerValue": (s.get("totalPlayerValue")
                                         or (total + (s.get("storageValue", 0) or 0))),
                    "builders": team_builders,
                    "idleBuilderCount": sum(1 for b in team_builders if b["idle"]),
                })
            teams.sort(key=lambda t: (t["allyTeamID"], t["teamID"]))
            return {
                "session": self.session,
                "gameSeconds": round(self.frame / 30, 1),
                "frame": self.frame,
                "wind": self.wind,
                "over": self.over,
                "source": self.source,
                "maxTotal": max_total,
                "maxIncome": max_inc,
                "teams": teams,
                "shares": sorted(self.shares.values(), key=lambda r: -r["total"]),
            }

    def shares_named(self):
        """Energy share/overflow flows with player names resolved: 'X > Y'."""
        with self.lock:
            name = lambda tid: self.teams.get(tid, {}).get("name", str(tid))
            out = []
            for r in sorted(self.shares.values(), key=lambda r: -r["total"]):
                res = r.get("resource", "energy")
                out.append({
                    "from": name(r["fromTeam"]), "to": name(r["toTeam"]),
                    "fromTeam": r["fromTeam"], "toTeam": r["toTeam"], "resource": res,
                    "donation": round(r["donation"]), "overflow": round(r["overflow"]),
                    "total": round(r["total"]), "taxed": round(r.get("taxed", 0)),
                    "label": f'{name(r["fromTeam"])} > {name(r["toTeam"])} ({res})',
                    "lastFrame": r["lastFrame"],
                })
            return out

    # ---- per-minute snapshot recall ---------------------------------------------------
    def capture_due_snapshots(self):
        """Store a full snapshot at each newly-crossed game-minute boundary.

        Called from the tail loop only. Reads self.frame locklessly (atomic int),
        builds the snapshot via snapshot() (which locks internally — so we must NOT
        already hold the lock here), then records it under the minute lock.
        Returns True if at least one new minute was captured.
        """
        cur_min = self.frame // FRAMES_PER_MINUTE
        if cur_min <= self._last_min:
            return False
        snap = self.snapshot()                       # locks/unlocks internally
        with self.lock:
            for m in range(self._last_min + 1, cur_min + 1):
                s = dict(snap)
                s["minute"] = m
                self.minute_snaps[m] = s
            self._last_min = cur_min
        return True

    def recall(self, minute):
        with self.lock:
            return self.minute_snaps.get(minute)

    def minutes(self):
        with self.lock:
            return sorted(self.minute_snaps)

    def persist_snapshots(self):
        """Atomically dump the minute snapshots to snapshots/game-<startedWall>.json."""
        with self.lock:
            if not self.minute_snaps:
                return
            data = json.dumps({
                "startedWall": self.started_wall,
                "gameID": self.game_id,
                "map": self.session.get("mapName", ""),
                "minutes": sorted(self.minute_snaps),
                "snapshots": self.minute_snaps,
            })
            key = int(self.started_wall or 0)
        try:
            os.makedirs(SNAP_DIR, exist_ok=True)
            path = os.path.join(SNAP_DIR, f"game-{key}.json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except Exception as e:
            print(f"[bar_analytic_server] snapshot persist failed: {e}")


def newest_source(default_path, watch_glob):
    """Freshest existing file among the default path and the watch glob (by mtime)."""
    cands = set()
    if os.path.isfile(default_path):
        cands.add(default_path)
    for p in glob.glob(watch_glob, recursive=True):
        if os.path.isfile(p):
            cands.add(p)
    return max(cands, key=os.path.getmtime) if cands else None


# ---- end-of-game logging into the local player database -----------------------------
DB_PATH = os.path.normpath(os.path.join(HERE, "..", "gex_research", "analysis_db.json"))
TAX_PATH = os.path.normpath(os.path.join(HERE, "..", "gex_research", "metrics", "unit_taxonomy.json"))


def _iso(ts=None):
    return (datetime.fromtimestamp(ts, timezone.utc) if ts else datetime.now(timezone.utc)).isoformat()


def _tax_version():
    try:
        with open(TAX_PATH, encoding="utf-8") as f:
            return json.load(f).get("version", 0)
    except (OSError, json.JSONDecodeError):
        return 0


def build_game_record(live):
    """Final outcome + per-player insights from the last live snapshot. Marks gameID, gametimes,
    and which insights are available here (live-final) vs. pending the batch/replay pipeline."""
    snap = live.snapshot()
    teams = snap["teams"]
    allies = {}
    for t in teams:
        allies.setdefault(t["allyTeamID"], []).append(t)
    survivors = {a: [t["name"] for t in ts if not t["dead"]] for a, ts in allies.items()}
    survivors = {str(a): names for a, names in survivors.items() if names}
    winner = live.winners if live.winners else (list(survivors)[0] if len(survivors) == 1 else None)

    players = []
    for t in teams:
        b = t["buckets"]
        eco_core = sum(b.get(k, 0) for k in ("economy", "build_power", "infrastructure", "support", "other"))
        unspent, construction = t.get("storageValue", 0), t.get("constructionValue", 0)
        eco_total = eco_core + unspent + construction
        mil = b.get("military", 0) + b.get("defense", 0)
        total = (eco_total + mil) or 1
        share = mil / total
        players.append({
            "name": t["name"], "side": t["side"], "allyTeamID": t["allyTeamID"],
            "dead": t["dead"], "commanderAlive": b.get("commander", 0) > 0,
            "ecoCore": round(eco_core), "unspent": round(unspent), "construction": round(construction),
            "military": round(b.get("military", 0)), "defense": round(b.get("defense", 0)),
            "metalIncome": round(t.get("metalIncome", 0), 1), "energyIncome": round(t.get("energyIncome", 0), 1),
            "nMex": t.get("nMex", 0),
            "role": "military" if share >= 0.6 else "eco" if share <= 0.25 else "hybrid",
            "wastePct": round((unspent + construction) / eco_total * 100) if eco_total else 0,
        })

    return {
        "gameID": live.game_id or f"live-{int(live.started_wall or 0)}",
        "map": snap["session"].get("mapName", ""),
        "startedAt": _iso(live.started_wall), "endedAt": _iso(),
        "durationSec": round(snap["frame"] / 30, 1), "endedAtFrame": snap["frame"],
        "winnerAllyTeam": winner, "survivors": survivors,
        "players": players,
        "taxonomyVersion": _tax_version(),
        "source": "live-final",
        "insightsAvailable": ["final eco/military split", "waste %", "role (eco/military/hybrid)",
                              "commander survival", "income", "mex count"],
        "insightsPending": ["timeline / peaks (needs batch replay analysis)",
                            "unit-type tech/class breakdown (needs widget unit composition)"],
        "createdAt": _iso(), "createdBy": "bar_analytic_server",
    }


def log_game(live):
    """Upsert the game record into analysis_db.json (atomic write)."""
    rec = build_game_record(live)
    try:
        with open(DB_PATH, encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, json.JSONDecodeError):
        db = {"schema": 1, "taxonomyVersion": None, "updated": None, "games": {}}
    db["games"][rec["gameID"]] = rec
    db["taxonomyVersion"] = max(db.get("taxonomyVersion") or 0, rec["taxonomyVersion"])
    db["updated"] = rec["createdAt"]
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)
    os.replace(tmp, DB_PATH)
    return rec


def tail_thread(default_path, watch_glob, scan_interval, end_grace, idle_end, live, srv):
    """Tail the freshest source, auto-following new games. When a game ends (explicit `end` event
    or the stream going idle), log outcome+insights to the player DB. Then, unless a new game
    starts within `end_grace`, shut the server down — so it never hangs past end of game."""
    f, buf, current, last_scan = None, "", None, 0.0
    seen_frame, last_advance, ever_live, ended_at = 0, None, False, None
    bulk_done, grew = False, False   # grew = stream appended *after* the initial bulk read (= live)

    def open_source(path):
        nonlocal f, buf, current, seen_frame, last_advance, ever_live, ended_at, bulk_done, grew
        if f:
            try: f.close()
            except OSError: pass
        f = open(path, "r", encoding="utf-8", errors="replace")
        buf, current = "", path
        live.source = path
        live.apply({"action": "init"})          # reset state for the new game/file
        seen_frame, last_advance, ever_live, ended_at = 0, None, False, None
        bulk_done, grew = False, False
        print(f"[bar_analytic_server] tailing {path}")

    def finish_game(reason):
        nonlocal ended_at
        with live.lock:
            has_data = bool(live.stats)
        if has_data:
            try:
                rec = log_game(live)
                print(f"[bar_analytic_server] game ended ({reason}): {rec['gameID']} · {rec['durationSec']}s · "
                      f"winner allyTeam {rec['winnerAllyTeam']} · {len(rec['players'])} players  ->  {DB_PATH}")
            except Exception as e:   # logging must never wedge the loop
                print(f"[bar_analytic_server] end-of-game logging failed: {e}")
        live.persist_snapshots()   # final flush of the per-minute recall timeline
        try:                       # archive the raw JSONL so this game stays re-analyzable
            if live.source and os.path.isfile(live.source):
                os.makedirs(GAMES_DIR, exist_ok=True)
                key = live.game_id or f"game-{int(live.started_wall or 0)}"
                shutil.copy2(live.source, os.path.join(GAMES_DIR, f"{key}.jsonl"))
        except Exception as e:
            print(f"[bar_analytic_server] game archive failed: {e}")
        ended_at = time.monotonic()

    while True:
        now = time.monotonic()
        # eager rescan while ended/over so a new game is picked up before the grace timer fires.
        interval = 5.0 if (live.over or ended_at is not None) else scan_interval
        if current is None or (now - last_scan) >= interval:
            last_scan = now
            newest = newest_source(default_path, watch_glob)
            if newest and newest != current and (
                    current is None or os.path.getmtime(newest) > os.path.getmtime(current) + 0.5):
                open_source(newest); continue

        if f is not None:
            chunk = f.read()
            if chunk:
                if bulk_done:
                    grew = True          # appended after the first read = a live, growing game
                bulk_done = True
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        live.apply(json.loads(line))
                    except json.JSONDecodeError:
                        pass
                # capture a recall snapshot for any game-minute crossed in this chunk
                if live.capture_due_snapshots():
                    live.persist_snapshots()
            else:
                try:
                    if os.path.getsize(current) < f.tell():   # truncated in place = new game
                        open_source(current); continue
                except OSError:
                    pass

        # track frame advance (a stale file loads as one big jump, then goes idle → counts as ended)
        if live.frame > seen_frame:
            seen_frame, last_advance, ever_live = live.frame, now, True
            if not live.over:
                ended_at = None   # live activity resumed (e.g. after a pause) → cancel pending exit

        # end of game: explicit `end`, or the stream gone idle after having been live.
        if ended_at is None and ever_live:
            idle = now - (last_advance or now)
            if live.over or idle >= idle_end:
                if grew:
                    finish_game("end event" if live.over else f"idle {idle:.0f}s")  # live game → log it
                else:
                    ended_at = now   # historical/completed file loaded — nothing live to log; just wait + clean up
                    print("[bar_analytic_server] source is an already-finished game — waiting for a new one.")

        # self-terminate after the grace window, unless a new game started (which clears ended_at)
        if ended_at is not None and (now - ended_at) >= end_grace:
            print(f"[bar_analytic_server] no new game within {end_grace:.0f}s of game end — shutting down.")
            srv.shutdown()
            return

        time.sleep(0.25)


_GEX_ROOT = os.path.normpath(os.path.join(HERE, "..", "gex_research"))
_MILESTONE_SCRIPT = os.path.join(_GEX_ROOT, "tools", "milestone_check.mjs")
_DEMOS_DIR = "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data/demos"


def _resolve_demo_path(game_ref):
    """Resolve a game reference dict to a .sdfz file path (Python-side, no roster filter).

    game_ref examples:
        {"index": 1}          last game
        {"index": 2}          second-to-last
        {"name": "pattern"}   most recent filename containing pattern
        {"since": "2026-06-22", "index": 1}  most recent after date
    Returns absolute path string or None.
    """
    demos = sorted(
        glob.glob(os.path.join(_DEMOS_DIR, "*.sdfz")),
        key=os.path.getmtime, reverse=True,
    )
    if not demos:
        return None

    if "name" in game_ref:
        demos = [d for d in demos if game_ref["name"].lower() in os.path.basename(d).lower()]

    if "since" in game_ref:
        since_ts = datetime.fromisoformat(game_ref["since"]).timestamp()
        demos = [d for d in demos if os.path.getmtime(d) >= since_ts]

    idx = int(game_ref.get("index", 1)) - 1   # 1-based → 0-based
    if idx < 0 or idx >= len(demos):
        return None
    return demos[idx]


def _kill_tree(pid):
    """Kill a process and all its children so nothing lingers after a timeout.

    On Windows spring-headless.exe is a grandchild of this server; a plain
    process.kill() only kills Node.js, leaving spring-headless.exe as an orphan.
    taskkill /F /T walks the whole child tree before any reparenting can happen.
    """
    if sys.platform == 'win32':
        subprocess.run(
            ['taskkill', '/F', '/T', '/PID', str(pid)],
            capture_output=True, timeout=10,
        )
    else:
        try:
            import signal as _signal, os as _os
            _os.killpg(_os.getpgid(pid), _signal.SIGKILL)
        except Exception:
            pass


def _run_milestones(payload):
    """Dispatch milestone analysis to Node.js milestone_check.mjs.

    payload keys:
        game      {index, name, since}  — game reference (default: {index:1})
        player    str                   — player name filter (default "splendi")
        triggers  list[str]             — ordered milestone phrases
        snapshots list[str]             — phrases (or indices) to snapshot on fire
        window    int                   — analysis window in seconds (default 900)
    Returns JSON string (MilestoneResult or {error}).
    """
    game_ref  = payload.get("game", {"index": 1})
    player    = payload.get("player", "splendi")
    triggers  = payload.get("triggers", [])
    snapshots = payload.get("snapshots", [])
    window    = int(payload.get("window", 900))

    if not triggers:
        return json.dumps({"error": "no triggers provided"})

    game_idx = int(game_ref.get("index", 1))
    if game_idx == 0:
        return json.dumps({"error": "live game (index 0) not supported for milestone analysis yet"})

    # Build node args
    cmd = ["node", _MILESTONE_SCRIPT, "--json",
           "--player", player,
           "--window", str(window),
           "--game",   str(game_idx)]

    if "name" in game_ref:
        cmd += ["--game", game_ref["name"]]   # overrides index
    if "since" in game_ref:
        cmd += ["--since", game_ref["since"]]
    if snapshots:
        cmd += ["--snapshots", ",".join(str(s) for s in snapshots)]

    # Positional trigger phrases last
    cmd += triggers

    # Use Popen directly so we can kill the whole process tree on timeout.
    # subprocess.run() kills only Node.js on timeout, leaving spring-headless.exe
    # as an orphan.  We call _kill_tree BEFORE killing node so the PID is still
    # present and taskkill can walk its children.
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=_GEX_ROOT,
    )
    try:
        stdout, stderr = proc.communicate(timeout=900)
        if stdout.strip():
            return stdout
        err = (stderr or "").strip()[-500:] or "(no output)"
        return json.dumps({"error": f"milestone_check exited {proc.returncode}: {err}"})
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid)   # kill Node + spring-headless.exe while PID still valid
        proc.kill()
        proc.communicate()
        return json.dumps({"error": "milestone analysis timed out (900s)"})
    except Exception as e:
        try: _kill_tree(proc.pid)
        except Exception: pass
        try: proc.kill(); proc.communicate()
        except Exception: pass
        return json.dumps({"error": str(e)})


def replay_into_live(path):
    """Replay a JSONL recording through a fresh Live, capturing minute snapshots. -> Live."""
    g = Live()
    g.apply({"action": "init"})
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                g.apply(json.loads(line))
            except json.JSONDecodeError:
                continue
            g.capture_due_snapshots()
    return g


def load_game(source, live=None):
    """Resolve a game source to a Live game object (source-agnostic for the analysis registry).

    source:  'live'/0/None -> the running game;  a path to *.jsonl;  an archived game id;
             a 1-based index into the archives (1 = most recent);  or a filename substring.
    """
    if source in (None, "", "live", 0, "0"):
        if live is None:
            raise ValueError("no live game available")
        return live
    if isinstance(source, str) and source.lower().endswith(".jsonl") and os.path.isfile(source):
        return replay_into_live(source)
    games = sorted(glob.glob(os.path.join(GAMES_DIR, "*.jsonl")), key=os.path.getmtime, reverse=True)
    for g in games:                                           # exact archived id
        if os.path.splitext(os.path.basename(g))[0] == str(source):
            return replay_into_live(g)
    try:                                                      # 1-based recency index
        idx = int(source) - 1
        if 0 <= idx < len(games):
            return replay_into_live(games[idx])
    except (ValueError, TypeError):
        pass
    matches = [g for g in games if str(source).lower() in os.path.basename(g).lower()]
    if matches:
        return replay_into_live(matches[0])
    raise FileNotFoundError(f"game not found: {source!r} (archives in {GAMES_DIR})")


def make_handler(live):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _team_state(self, team_id: int, snap: dict) -> dict:
            return team_state(team_id, snap)   # module-level, shared with replay_jsonl.py

        def do_GET(self):
            path, _, qs = self.path.partition('?')
            params = dict(urllib.parse.parse_qsl(qs))

            if path.startswith("/api/state"):
                self._send(json.dumps(live.snapshot()).encode("utf-8"), "application/json")

            elif path == "/api/snapshots":
                # index of recallable game-minutes
                mins = live.minutes()
                self._send(json.dumps({
                    "minutes": mins, "count": len(mins),
                    "latestMinute": (mins[-1] if mins else None),
                    "gameSeconds": live.snapshot().get("gameSeconds"),
                }).encode("utf-8"), "application/json")

            elif path == "/api/snapshot":
                # recall the full game state at minute=N
                try:
                    m = int(params.get("minute", -1))
                except ValueError:
                    m = -1
                snap = live.recall(m)
                body = snap if snap else {"error": f"no snapshot at minute {m}",
                                          "available": live.minutes()}
                self._send(json.dumps(body).encode("utf-8"), "application/json")

            elif path == "/api/compare":
                # per-team delta minute A -> B (default B = A+1): how the game moved that minute
                try:
                    frm = int(params.get("minute", params.get("from", -1)))
                    to  = int(params.get("to", frm + 1))
                except ValueError:
                    frm, to = -1, -1
                a, b = live.recall(frm), live.recall(to)
                if not a or not b:
                    body = {"error": f"need snapshots at both minute {frm} and {to}",
                            "available": live.minutes()}
                else:
                    body = compare_minutes(a, b)
                self._send(json.dumps(body).encode("utf-8"), "application/json")

            elif path == "/api/project":
                # Recall minute N, project each team's eco forward, grade vs actual N+1.
                if not _ANALYSIS_AVAILABLE:
                    self._send(json.dumps({"error": "economy analysis unavailable "
                        "(state_api/navigator import failed)"}).encode("utf-8"), "application/json")
                    return
                try:
                    frm = int(params.get("minute", -1))
                except ValueError:
                    frm = -1
                to = frm + 1
                a, b = live.recall(frm), live.recall(to)
                if not a or not b:
                    body = {"error": f"need snapshots at minute {frm} and {to} to project+compare",
                            "available": live.minutes()}
                else:
                    teams = []
                    for t in a.get("teams", []):
                        tid  = t["teamID"]
                        sn   = self._team_state(tid, a)
                        snp1 = self._team_state(tid, b)
                        if not sn or not snp1:
                            continue
                        try:
                            proj = project_team(sn, snp1)
                        except Exception as e:
                            proj = {"error": str(e)}
                        proj["teamID"] = tid
                        proj["name"]   = t.get("name", str(tid))
                        proj["side"]   = t.get("side", "")
                        teams.append(proj)
                    body = {"fromMinute": frm, "toMinute": to, "horizonSec": 60,
                            "model": "legion-eco (state_api)", "teams": teams}
                self._send(json.dumps(body).encode("utf-8"), "application/json")

            elif path == "/api/shares":
                # energy donation/overflow flows between teammates, "X > Y"
                self._send(json.dumps({"shares": live.shares_named()}).encode("utf-8"),
                           "application/json")

            elif path == "/api/functions":
                # discovery: the analysis registry (names + params) for /api/run
                self._send(json.dumps({"functions": [
                    {"name": n, "params": s["params"], "desc": s["desc"]}
                    for n, s in REGISTRY.items()
                ]}).encode("utf-8"), "application/json")

            elif path == "/api/games":
                # archived games available to /api/run as a `game` source
                gs = sorted(glob.glob(os.path.join(GAMES_DIR, "*.jsonl")),
                            key=os.path.getmtime, reverse=True)
                self._send(json.dumps({"games": [
                    os.path.splitext(os.path.basename(g))[0] for g in gs]}).encode("utf-8"),
                    "application/json")

            elif path == "/api/build":
                # opening + phase-2 split (post-factory → team T2), via the registry function
                if not _BUILD_AVAILABLE:
                    self._send(json.dumps({"error": "build classifier unavailable"}).encode("utf-8"),
                               "application/json")
                    return
                want = params.get("team")
                fn = REGISTRY["build"]["fn"]
                body = fn(live, team=want) if want is not None else fn(live)
                self._send(json.dumps(body).encode("utf-8"), "application/json")

            elif path == "/api/notable" and _ANALYSIS_AVAILABLE:
                snap = live.snapshot()
                try:
                    tid  = int(params.get('team', 0))
                    s_d  = self._team_state(tid, snap)
                    notables = notable_check(s_d) if s_d else []
                    body = json.dumps({
                        'team': tid, 't': snap.get('gameSeconds'),
                        'state': s_d, 'notables': notables,
                        'summary': notable_summarize(notables),
                    })
                except Exception as e:
                    body = json.dumps({'error': str(e)})
                self._send(body.encode('utf-8'), 'application/json')

            elif path == "/api/t2" and _ANALYSIS_AVAILABLE:
                snap = live.snapshot()
                try:
                    tid  = int(params.get('team', 0))
                    s_d  = self._team_state(tid, snap)
                    w    = api_t2_wealth(s_d) if s_d else {}
                    body = json.dumps({'team': tid, 'wealth': w})
                except Exception as e:
                    body = json.dumps({'error': str(e)})
                self._send(body.encode('utf-8'), 'application/json')

            elif path == "/api/analyze" and _ANALYSIS_AVAILABLE:
                snap = live.snapshot()
                try:
                    tid    = int(params.get('team', 0))
                    s_d    = self._team_state(tid, snap)
                    if not s_d:
                        raise ValueError(f'team {tid} not in snapshot')
                    rois     = api_all_roi(s_d)
                    notables = notable_check(s_d)
                    wealth   = api_t2_wealth(s_d)
                    steps    = step_options(s_d, wind_e=s_d.get('wind_e', 10))[:5]
                    body = json.dumps({
                        'team': tid, 't': snap.get('gameSeconds'),
                        'state': s_d,
                        'notables': notables,
                        'notable_summary': notable_summarize(notables),
                        't2_wealth': wealth,
                        'top_actions': steps,
                    })
                except Exception as e:
                    body = json.dumps({'error': str(e)})
                self._send(body.encode('utf-8'), 'application/json')

            elif path == "/api/aberrant":
                try:
                    team   = int(params.get('team', -1))
                    limit  = int(params.get('limit', 20))
                    window = float(params.get('window', 30))
                    if _ABERRANT_AVAILABLE and live.aberrant_store is not None:
                        tid_filter = team if team >= 0 else None
                        events  = live.aberrant_store.all_with_context(
                            team_id=tid_filter, limit=limit, window_s=window)
                        summary = live.aberrant_store.summary()
                    else:
                        events, summary = [], {}
                    body = json.dumps({
                        'team': team, 'count': len(events),
                        'events': events, 'summary': summary,
                    })
                except Exception as e:
                    body = json.dumps({'error': str(e)})
                self._send(body.encode('utf-8'), 'application/json')

            elif path in ("/", "/index.html", "/dashboard.html"):
                p = os.path.join(HERE, "dashboard.html")
                try:
                    with open(p, "rb") as fh:
                        self._send(fh.read(), "text/html; charset=utf-8")
                except FileNotFoundError:
                    self._send(b"dashboard.html not found next to server", "text/plain")

            else:
                self.send_response(404); self.end_headers()

        def do_POST(self):
            """POST endpoints: /api/analyze (full state), /api/aberrant/explain (add explanation)."""
            path = self.path.split('?')[0]

            if path == '/api/run':
                # compose a SET of registry analyses over one game source.
                # body: {"game": "live"|<id>|<index>|<path.jsonl>, "functions": ["build","project:7",...]}
                try:
                    length  = int(self.headers.get('Content-Length', 0))
                    payload = json.loads(self.rfile.read(length)) if length else {}
                    src     = payload.get('game', 'live')
                    funcs   = payload.get('functions', [])
                    if not funcs:
                        body = {"error": "no functions requested", "available": list(REGISTRY)}
                    else:
                        game = load_game(src, live=live)
                        body = {"game": str(src), "results": run_analyses(game, funcs)}
                except Exception as e:
                    body = {"error": str(e)}
                self._send(json.dumps(body).encode('utf-8'), 'application/json')

            elif path == '/api/aberrant/explain' and _ABERRANT_AVAILABLE and live.aberrant_store is not None:
                try:
                    length  = int(self.headers.get('Content-Length', 0))
                    payload = json.loads(self.rfile.read(length))
                    ev_id   = payload.get('id', '')
                    expl    = payload.get('explanation', '')
                    found   = live.aberrant_store.add_explanation(ev_id, expl)
                    body    = json.dumps({'ok': found, 'id': ev_id,
                                         'message': 'explanation saved' if found else 'event id not found'})
                except Exception as e:
                    body = json.dumps({'error': str(e)})
                self._send(body.encode('utf-8'), 'application/json')

            elif path == '/api/analyze' and _ANALYSIS_AVAILABLE:
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    s_d    = json.loads(self.rfile.read(length))
                    rois     = api_all_roi(s_d)
                    notables = notable_check(s_d)
                    wealth   = api_t2_wealth(s_d)
                    steps    = step_options(s_d, wind_e=s_d.get('wind_e', 10))[:8]
                    body = json.dumps({
                        'state': s_d, 'notables': notables,
                        'notable_summary': notable_summarize(notables),
                        't2_wealth': wealth,
                        'all_roi': rois,
                        'top_actions': steps,
                    })
                except Exception as e:
                    body = json.dumps({'error': str(e)})
                self._send(body.encode('utf-8'), 'application/json')
            elif path == '/api/milestones':
                # POST body: {game, player, triggers, snapshots, window}
                # Delegates to gex_research/tools/milestone_check.mjs via Node subprocess.
                #
                # game:      {index: 1}  | {name: "..."} | {since: "YYYY-MM-DD"}
                #            index 0 = live (not yet supported), 1 = last, 2 = second-to-last
                # player:    player name substring (default "splendi")
                # triggers:  ["5 mex", "7 mex", "each medmex", "TPV 6000", "T2 factory", "T2 mex"]
                # snapshots: ["T2 mex"]  triggers that should emit economy snapshots on fire
                # window:    analysis window in seconds (default 900)
                try:
                    length  = int(self.headers.get('Content-Length', 0))
                    payload = json.loads(self.rfile.read(length))
                    body    = _run_milestones(payload)
                except Exception as e:
                    body = json.dumps({'error': str(e)})
                self._send(body.encode('utf-8'), 'application/json')
            else:
                self.send_response(404); self.end_headers()
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=DEFAULT_PATH)
    ap.add_argument("--watch", default=None,
                    help="glob of source files to auto-follow the freshest of (default: *.jsonl beside --path)")
    ap.add_argument("--scan", type=float, default=60.0,
                    help="seconds between source rescans; drops to 5s once a game ends (default 60)")
    ap.add_argument("--end-grace", type=float, default=240.0,
                    help="seconds to wait for a new game after one ends before self-terminating (default 240)")
    ap.add_argument("--idle-end", type=float, default=45.0,
                    help="no-new-frames seconds that mark a game ended if no explicit end event (default 45)")
    ap.add_argument("--no-exit", action="store_true",
                    help="never self-terminate (legacy always-on behavior)")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    watch = args.watch or os.path.join(os.path.dirname(os.path.abspath(args.path)), "*.jsonl")
    grace = float("inf") if args.no_exit else args.end_grace

    live = Live()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(live))
    threading.Thread(target=tail_thread,
                     args=(args.path, watch, args.scan, grace, args.idle_end, live, srv),
                     daemon=True).start()
    print(f"[bar_analytic_server] watching {watch}  (rescan {args.scan:.0f}s; eager on game-end)")
    print(f"[bar_analytic_server] end-of-game -> log to {DB_PATH}; self-exit after {grace:.0f}s idle"
          f"{' (disabled)' if args.no_exit else ''}")
    print(f"[bar_analytic_server] dashboard -> http://localhost:{args.port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[bar_analytic_server] stopped")
    print("[bar_analytic_server] exited")


if __name__ == "__main__":
    main()

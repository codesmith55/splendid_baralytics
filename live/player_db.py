#!/usr/bin/env python3
"""player_db.py — internal cross-game player-behavior database.

Accumulates per-game behavioral observations into SQLite (live/players.db) and
aggregates them into pseudo-subjective tendency tags, split by geometric
position class ("plays like X as back-corner in NN% of games").

    appearances   one row per (game, player): name, position class, lane,
                  factories built, outcome context
    observations  one row per detected trait per game: trait id + evidence

Traits are pure detector functions over eco_viz.flow_series (per-minute
behavioral deltas). Adding a trait = adding one entry to TRAITS; every
front-end (CLI report, tags, `tags` registry analysis) picks it up.

CLI:
    python player_db.py ingest <game>        # jsonl path | archive id | 1-based index
    python player_db.py ingest --all         # every archived game in live/games/
    python player_db.py player "name"        # full profile: positions, traits, tags
    python player_db.py tags ["name"]        # tendency tag lines
    python player_db.py traits               # detector catalog
    python player_db.py games                # ingested games
"""
from __future__ import annotations
import argparse, glob, json, os, sqlite3, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import eco_viz  # noqa: E402

DB_PATH = os.path.join(HERE, "players.db")
GAMES_DIR = os.path.join(HERE, "games")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id     TEXT PRIMARY KEY,
    map         TEXT,
    mode        TEXT,
    minutes     INTEGER,
    started     REAL,
    ingested_at REAL
);
CREATE TABLE IF NOT EXISTS appearances (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id        TEXT NOT NULL REFERENCES games(game_id),
    team_id        INTEGER,
    player         TEXT NOT NULL,
    ally_id        INTEGER,
    lane_i         INTEGER,
    lane_n         INTEGER,
    position_class TEXT DEFAULT '',
    factories      TEXT DEFAULT '',
    end_value      REAL,
    UNIQUE(game_id, team_id)
);
CREATE TABLE IF NOT EXISTS observations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    appearance_id INTEGER NOT NULL REFERENCES appearances(id),
    trait         TEXT NOT NULL,
    start_min     INTEGER,
    end_min       INTEGER,
    evidence      TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_app_player ON appearances(player);
CREATE INDEX IF NOT EXISTS idx_obs_trait ON observations(trait);
"""


def _db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(_SCHEMA)
    return con


# ── trait detectors ────────────────────────────────────────────────────────
# Each detector: fn(fs) -> [ {start_min, end_min, evidence-dict} ]
# fs = eco_viz.flow_series rows. Thresholds are metal-equivalent value/minute.

def _runs(fs, pred, min_len=3):
    """Maximal runs of consecutive minutes where pred(row) holds."""
    out, run = [], []
    for r in fs:
        if pred(r):
            run.append(r)
        else:
            if len(run) >= min_len:
                out.append(run)
            run = []
    if len(run) >= min_len:
        out.append(run)
    return out


def det_techs_over_t1(fs):
    """Stops making units to tech/eco (army production ~0 while eco keeps
    growing), from minute 4 on. Evidence notes whether they were under fire
    at the time (losing army while not replacing it) or peacefully greeding."""
    body = [r for r in fs if r["minute"] >= 4]
    obs = []
    for run in _runs(body, lambda r: r["army_added"] < 60 and r["eco_added"] > 250):
        losing = sum(r["army_lost_d"] for r in run) > 200
        obs.append({"start_min": run[0]["minute"], "end_min": run[-1]["minute"],
                    "evidence": {"avg_eco_added": round(sum(r["eco_added"] for r in run) / len(run)),
                                 "army_lost_during": round(sum(r["army_lost_d"] for r in run)),
                                 "while_losing": losing}})
    return obs


def det_hoards_while_ecoing(fs):
    """Stops making units AND banks metal while still expanding eco — the
    double sin: value sits in storage instead of the field."""
    body = [r for r in fs if r["minute"] >= 3]
    obs = []
    for run in _runs(body, lambda r: r["army_added"] < 60 and r["bank_delta"] > 120
                     and r["eco_added"] > 150):
        obs.append({"start_min": run[0]["minute"], "end_min": run[-1]["minute"],
                    "evidence": {"banked": round(sum(r["bank_delta"] for r in run)),
                                 "eco_added": round(sum(r["eco_added"] for r in run))}})
    return obs


def det_feeds_cheap_units(fs):
    """The tick-spam metal sink: sustained army losses trading below 0.6x."""
    body = [r for r in fs if r["army_lost_d"] >= 200]
    bad = [r for r in body if r["enemy_killed_d"] < 0.6 * r["army_lost_d"]]
    if len(bad) < 2:
        return []
    lost = sum(r["army_lost_d"] for r in bad)
    killed = sum(r["enemy_killed_d"] for r in bad)
    return [{"start_min": bad[0]["minute"], "end_min": bad[-1]["minute"],
             "evidence": {"minutes": len(bad), "lost": round(lost),
                          "killed": round(killed),
                          "ratio": round(killed / max(lost, 1), 2)}}]


def det_chronic_idle_bp(fs):
    """Build power idle while resources are banked, for stretches — the
    not-queued state (idle BP with an EMPTY bank is fine and not flagged)."""
    body = [r for r in fs if r["minute"] >= 3]
    obs = []
    for run in _runs(body, lambda r: r["bp_util"] < 60 and r["bank"] > 400):
        obs.append({"start_min": run[0]["minute"], "end_min": run[-1]["minute"],
                    "evidence": {"avg_util": round(sum(r["bp_util"] for r in run) / len(run)),
                                 "avg_bank": round(sum(r["bank"] for r in run) / len(run))}})
    return obs


def det_recycles_eco(fs):
    """Reclaims/self-removes own eco in meaningful amounts (solar recycling)."""
    total = sum(r["self_removed_d"] for r in fs)
    if total < 200:
        return []
    hot = [r for r in fs if r["self_removed_d"] > 0]
    return [{"start_min": hot[0]["minute"], "end_min": hot[-1]["minute"],
             "evidence": {"self_removed": round(total)}}]


def _front_or_corner(pc):
    return bool(pc) and ("corner" in pc or pc.startswith("front"))


# A trait may carry `notable_at`: a predicate on position_class deciding where
# the behavior is actually OUT of role. Observations are recorded for everyone
# (the data stays queryable); only notable positions produce tendency TAGS —
# e.g. abandoning T1 to tech is the tech role's job (back-mid), but a tell
# when the front/corner player does it.
TRAITS = {
    "techs_over_t1": {
        "fn": det_techs_over_t1,
        "desc": "stops making T1 units and techs/ecos up "
                "(expected from a tech role; tagged only from front/corner)",
        "tag": "abandons T1 production to tech up out of role",
        "notable_at": _front_or_corner,
    },
    "hoards_while_ecoing": {
        "fn": det_hoards_while_ecoing,
        "desc": "stops making units and hoards metal while still ecoing",
        "tag": "hoards metal while ecoing",
    },
    "feeds_cheap_units": {
        "fn": det_feeds_cheap_units,
        "desc": "sustained cheap-unit losses trading below 0.6x (metal sink)",
        "tag": "feeds cheap units into losing trades",
    },
    "chronic_idle_bp": {
        "fn": det_chronic_idle_bp,
        "desc": "leaves build power idle while resources are banked",
        "tag": "sits on idle build power",
    },
    "recycles_eco": {
        "fn": det_recycles_eco,
        "desc": "reclaims own eco (e.g. solars) back into the bank",
        "tag": "recycles own eco for metal",
    },
}


# ── ingestion ──────────────────────────────────────────────────────────────
def _factories(game, team_id):
    """Factory def-names this team built (from the early build log)."""
    defs = game.unit_defs
    out = []
    for e in (game.build_log.get(team_id) or []):
        d = defs.get(e.get("defID"), {})
        if d.get("isFactory"):
            out.append(d.get("defName") or e.get("defName", ""))
    return out


def ingest_game(game, game_id=None, mode=None):
    """Detect traits for every player of one game and store them. Re-ingesting
    the same game_id replaces its rows."""
    snap = game.snapshot()
    mins = game.minutes()
    # stable id: widget gameID > archived-file stem > wall clock. The widget's
    # game_id event doesn't always fire (spectated games), and replay-start
    # wall time would mint a new id every re-ingest.
    gid = game_id or getattr(game, "game_id", None)
    if not gid:
        src = os.path.basename(getattr(game, "source", "") or "")
        if src and src != "bar_analytic_live.jsonl":
            gid = os.path.splitext(src)[0]
    gid = str(gid or f"game-{int(getattr(game, 'started_wall', 0) or time.time())}")
    teams = snap.get("teams", [])
    lanes = eco_viz.lane_positions(snap)
    sizes = sorted((len([t for t in teams if t.get("allyTeamID") == a])
                    for a in {t.get("allyTeamID") for t in teams}), reverse=True)
    con = _db()
    with con:
        old = [r[0] for r in con.execute(
            "SELECT id FROM appearances WHERE game_id=?", (gid,))]
        if old:
            con.execute("DELETE FROM observations WHERE appearance_id IN (%s)"
                        % ",".join("?" * len(old)), old)
            con.execute("DELETE FROM appearances WHERE game_id=?", (gid,))
        con.execute("INSERT OR REPLACE INTO games VALUES (?,?,?,?,?,?)",
                    (gid, snap.get("session", {}).get("mapName", ""),
                     "v".join(str(s) for s in sizes), len(mins),
                     getattr(game, "started_wall", None), time.time()))
        n_obs = 0
        for t in teams:
            tid = t["teamID"]
            lane = lanes.get(tid, {})
            cur = con.execute(
                "INSERT INTO appearances (game_id, team_id, player, ally_id, lane_i,"
                " lane_n, position_class, factories, end_value) VALUES (?,?,?,?,?,?,?,?,?)",
                (gid, tid, t.get("name", str(tid)), t.get("allyTeamID"),
                 lane.get("lane_i"), lane.get("lane_n"),
                 lane.get("position_class", ""),
                 ",".join(_factories(game, tid)), t.get("total", 0)))
            app_id = cur.lastrowid
            fs = eco_viz.flow_series(game, tid)
            if not fs:
                continue
            for trait, spec in TRAITS.items():
                for o in spec["fn"](fs):
                    n_obs += 1
                    con.execute(
                        "INSERT INTO observations (appearance_id, trait, start_min,"
                        " end_min, evidence) VALUES (?,?,?,?,?)",
                        (app_id, trait, o.get("start_min"), o.get("end_min"),
                         json.dumps(o.get("evidence", {}))))
    con.close()
    return {"game_id": gid, "players": len(teams), "observations": n_obs}


# ── aggregation / tags ─────────────────────────────────────────────────────
def player_tendencies(player=None):
    """Trait rates per (player, position_class): in how many of the games a
    player appeared (in that position) did each trait show up."""
    con = _db()
    q = """
    SELECT a.player, a.position_class, o.trait,
           COUNT(DISTINCT a.game_id) AS hit_games
    FROM observations o JOIN appearances a ON a.id = o.appearance_id
    {where} GROUP BY a.player, a.position_class, o.trait"""
    tot_q = """
    SELECT player, position_class, COUNT(DISTINCT game_id)
    FROM appearances {where} GROUP BY player, position_class"""
    args = (player,) if player else ()
    where = "WHERE a.player=?" if player else ""
    where_t = "WHERE player=?" if player else ""
    totals = {(p, pc): n for p, pc, n in con.execute(tot_q.format(where=where_t), args)}
    out = []
    for p, pc, trait, hits in con.execute(q.format(where=where), args):
        total = totals.get((p, pc), 0)
        if total:
            out.append({"player": p, "position_class": pc or "unknown", "trait": trait,
                        "games_with_trait": hits, "games_at_position": total,
                        "rate": round(100 * hits / total)})
    con.close()
    out.sort(key=lambda r: (r["player"], -r["rate"]))
    return out


def tag_lines(player=None, min_games=1):
    """Human tendency tags: 'hoards metal while ecoing as back-corner — 3/4 games (75%)'.
    Traits with a `notable_at` predicate only tag positions where the behavior
    is out of role (the raw observations remain queryable for every position)."""
    lines = []
    for r in player_tendencies(player):
        if r["games_at_position"] < min_games:
            continue
        spec = TRAITS.get(r["trait"], {})
        notable = spec.get("notable_at")
        if notable and not notable(r["position_class"]):
            continue
        tag = spec.get("tag", r["trait"])
        lines.append(f'{r["player"]}: {tag} as {r["position_class"]} — '
                     f'{r["games_with_trait"]}/{r["games_at_position"]} games ({r["rate"]}%)')
    return lines


def player_profile(player):
    con = _db()
    apps = list(con.execute(
        "SELECT game_id, position_class, lane_i, lane_n, factories, end_value"
        " FROM appearances WHERE player=? ORDER BY rowid", (player,)))
    obs = list(con.execute(
        "SELECT o.trait, o.start_min, o.end_min, o.evidence, a.game_id, a.position_class"
        " FROM observations o JOIN appearances a ON a.id=o.appearance_id"
        " WHERE a.player=? ORDER BY a.game_id, o.start_min", (player,)))
    con.close()
    return {"player": player, "appearances": [
        {"game": g, "position": pc, "lane": f"{li}/{ln}", "factories": f,
         "end_value": v} for g, pc, li, ln, f, v in apps],
        "observations": [
        {"trait": t, "minutes": f"{a}-{b}", "evidence": json.loads(e or "{}"),
         "game": g, "position": pc} for t, a, b, e, g, pc in obs],
        "tags": tag_lines(player)}


# ── CLI ────────────────────────────────────────────────────────────────────
def _load(ref):
    from bar_analytic_server import load_game
    return load_game(ref)


def main():
    ap = argparse.ArgumentParser(description="cross-game player-behavior DB")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("ingest")
    g.add_argument("game", nargs="?", default=None)
    g.add_argument("--all", action="store_true", help="every archive in live/games/")
    p = sub.add_parser("player"); p.add_argument("name")
    t = sub.add_parser("tags"); t.add_argument("name", nargs="?", default=None)
    t.add_argument("--min-games", type=int, default=1)
    sub.add_parser("traits")
    sub.add_parser("games")
    a = ap.parse_args()

    if a.cmd == "ingest":
        refs = (sorted(glob.glob(os.path.join(GAMES_DIR, "*.jsonl")))
                if a.all else [a.game or 1])
        for ref in refs:
            try:
                r = ingest_game(_load(ref))
                print(f"ingested {r['game_id']}: {r['players']} players, "
                      f"{r['observations']} observations")
            except Exception as e:
                print(f"FAILED {ref}: {e}")
    elif a.cmd == "player":
        print(json.dumps(player_profile(a.name), indent=2))
    elif a.cmd == "tags":
        lines = tag_lines(a.name, a.min_games)
        print("\n".join(lines) if lines else "no tendencies recorded yet")
    elif a.cmd == "traits":
        for k, s in TRAITS.items():
            print(f"{k:22} {s['desc']}")
    elif a.cmd == "games":
        con = _db()
        for gid, m, mode, mins, *_ in con.execute(
                "SELECT * FROM games ORDER BY ingested_at"):
            print(f"{gid:28} {mode:6} {mins:>3} min  {m}")
        con.close()


if __name__ == "__main__":
    main()

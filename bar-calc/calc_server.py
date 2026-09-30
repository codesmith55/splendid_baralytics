#!/usr/bin/env python3
"""
bar-calc/calc_server.py — a long-running local service over bar_unified.

Replaying a demo takes a minute and extraction spawns node, so doing it as a fresh
subprocess per game means a permission prompt per game. Start this once and drive it
with requests instead.

    cd bar-calc && python calc_server.py [--port 8799] [--no-exit]

Anything slow (replay, extract, batch) is a JOB: POST it, get an id back, poll it.
Anything cheap (reading hard data, ledgers, analyses, tables) answers immediately.

  GET  /                          this list
  GET  /health                    port, uptime, job counts
  GET  /games?count=10&matchup=1vAI,1v0&today=1&min_kb=40
                                  recent demos, newest first, 1-based index
  GET  /data                      hard-data files already extracted
  GET  /hard?game=<id|N>          one hard-data document
  GET  /ledger?game=<id|N>&until=480&snap=60,120&only=Mex,Solar
                                  effective build order: starts, finishes, state at each
  GET  /analyze?game=<id|N>&names=mex_timing,phases
  GET  /state?game=<id|N>&at=60   the five quantities plus what each option permits
  GET  /rates?wind=11.9           drain rates, sustainable BP, break-evens
  GET  /balance?bp=300            per wind speed: when efficiency beats immediacy
  GET  /tables?bp=300             the three joined tables
  GET  /horizon?game=<id|N>&at=30&wind=11.9&target=Wind&bpsrc=ConTurret

  POST /jobs   {"action":"extract","game":1,"until":480}
               {"action":"extract_recent","count":6,"matchup":"1vAI,1v0","today":true}
               {"action":"replay","game":1}
  GET  /jobs                      every job
  GET  /jobs/<id>                 one job: state, log, result

Jobs run one at a time on a worker thread, so replays queue rather than fighting
over spring-headless.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import threading
import time
import traceback
import uuid
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Queue
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import bar_unified as U            # noqa: E402

STARTED = time.time()
JOBS: dict = {}
JOBQ: "Queue[str]" = Queue()
LOCK = threading.Lock()


# ── job plumbing ───────────────────────────────────────────────────────────

def _job(action: str, params: dict) -> str:
    jid = uuid.uuid4().hex[:12]
    with LOCK:
        JOBS[jid] = {"id": jid, "action": action, "params": params, "state": "queued",
                     "queued_at": time.time(), "started_at": None, "ended_at": None,
                     "log": "", "result": None, "error": None}
    JOBQ.put(jid)
    return jid


def _run_job(jid: str) -> None:
    with LOCK:
        j = JOBS[jid]
        j["state"] = "running"
        j["started_at"] = time.time()
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            j["result"] = _dispatch(j["action"], j["params"])
        with LOCK:
            j["state"] = "done"
    except Exception as e:                                            # noqa: BLE001
        with LOCK:
            j["state"] = "error"
            j["error"] = f"{type(e).__name__}: {e}"
            j["traceback"] = traceback.format_exc()[-4000:]
    finally:
        with LOCK:
            j["log"] = buf.getvalue()[-20000:]
            j["ended_at"] = time.time()


def _worker() -> None:
    while True:
        jid = JOBQ.get()
        try:
            _run_job(jid)
        finally:
            JOBQ.task_done()


def _summary(d: dict) -> dict:
    """A hard-data document reduced to what a caller wants to see in a job result."""
    g = d.get("game", {})
    return {"id": g.get("id"), "map": g.get("map"), "matchup": g.get("matchup"),
            "team": g.get("team"), "played": g.get("played_local"),
            "player": (d.get("player") or {}).get("name"),
            "file": d.get("_file"),
            "counts": {"starts": len(d.get("starts", [])),
                       "completions": len(d.get("completions", [])),
                       "mexes": len(d.get("mexes", [])),
                       "econ": len(d.get("econ", [])),
                       "wind": len(d.get("wind", {}).get("samples", [])),
                       "reclaim": len(d.get("reclaim", []))}}


def _dispatch(action: str, p: dict):
    if action == "extract":
        d = U.extract_game(p.get("game", 1), player=p.get("player"),
                           matchup=p.get("matchup"), until_sec=float(p.get("until", 480)),
                           force_replay=bool(p.get("force")))
        return _summary(d)
    if action == "extract_recent":
        ds = U.extract_recent(count=int(p.get("count", 6)), matchup=p.get("matchup"),
                              min_kb=int(p.get("min_kb", 40)),
                              until_sec=float(p.get("until", 480)),
                              today_only=bool(p.get("today")),
                              player=p.get("player"))
        return {"extracted": len(ds), "games": [_summary(d) for d in ds]}
    if action == "replay":
        ref = U.resolve_game(p.get("game", 1), matchup=p.get("matchup"))
        return {"actions": U.ensure_actions(ref, force=bool(p.get("force"))),
                "demo": ref.name, "matchup": ref.matchup}
    raise ValueError(f"unknown action {action!r}")


# ── cheap reads ────────────────────────────────────────────────────────────

def _game_arg(q: dict, key: str = "game", default="1"):
    v = (q.get(key, [default]) or [default])[0]
    return int(v) if str(v).isdigit() else v


def _captured(fn, *a, **kw) -> dict:
    """Run a printing function and return both its text and its return value."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        r = fn(*a, **kw)
    return {"text": buf.getvalue(), "data": r}


def _floats(q: dict, key: str) -> list:
    raw = (q.get(key, [""]) or [""])[0]
    return [float(x) for x in raw.replace(";", ",").split(",") if x.strip()]


def _strs(q: dict, key: str) -> list:
    raw = (q.get(key, [""]) or [""])[0]
    return [x.strip() for x in raw.split(",") if x.strip()]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):        # quieter than the default
        sys.stderr.write(f"[calc] {self.address_string()} {fmt % args}\n")

    def _send(self, obj, code: int = 200, ctype: str = "application/json"):
        body = (obj if isinstance(obj, (bytes, bytearray))
                else json.dumps(obj, indent=1, default=str).encode("utf-8"))
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, s: str, code: int = 200):
        self._send(s.encode("utf-8"), code, "text/plain; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path.rstrip("/") or "/"
        try:
            if path == "/":
                return self._text(__doc__)
            if path == "/health":
                with LOCK:
                    states: dict = {}
                    for j in JOBS.values():
                        states[j["state"]] = states.get(j["state"], 0) + 1
                return self._send({"ok": True, "uptime_sec": round(time.time() - STARTED, 1),
                                   "jobs": states, "queue": JOBQ.qsize(),
                                   "player_default": U.DEFAULT_PLAYER,
                                   "data_dir": U.GAME_DATA_DIR})
            if path == "/games":
                gs = U.recent_games(count=int((q.get("count", ["10"]))[0]),
                                    matchup=(q.get("matchup", [None]))[0],
                                    player=(q.get("player", [None]))[0])
                today = (q.get("today", ["0"]))[0] not in ("0", "", "false")
                min_kb = int((q.get("min_kb", ["0"]))[0])
                import datetime as _dt
                td = _dt.date.today().isoformat()
                rows = []
                for g in gs:
                    if min_kb and g.size_kb < min_kb:
                        continue
                    if today and not g.written_local.startswith(td):
                        continue
                    rows.append({"index": g.index, "played_local": g.written_local,
                                 "matchup": g.matchup, "size_kb": g.size_kb,
                                 "map": g.map_name, "demo": g.name, "id": g.game_id})
                return self._send({"games": rows})
            if path == "/data":
                return self._send({"data": U.list_game_data()})
            if path == "/hard":
                return self._send(U.load_game_data(_game_arg(q)))
            if path == "/ledger":
                d = U.load_game_data(_game_arg(q))
                out = _captured(U.print_build_ledger, d,
                                until_sec=float((q.get("until", ["480"]))[0]),
                                snapshots=_floats(q, "snap") or None,
                                include=_strs(q, "only") or None)
                if (q.get("fmt", ["text"]))[0] == "json":
                    return self._send(out["data"])
                return self._text(out["text"])
            if path == "/analyze":
                d = U.load_game_data(_game_arg(q))
                return self._send(U.run_analyses(d, _strs(q, "names") or None))
            if path == "/state":
                d = U.load_game_data(_game_arg(q))
                st = U.state_from_game(d, float((q.get("at", ["60"]))[0]))
                return self._text(_captured(U.scaling_report, st)["text"])
            if path == "/rates":
                w = (q.get("wind", [None]))[0]
                return self._text(_captured(U.rate_report,
                                            wind=float(w) if w else None)["text"])
            if path == "/balance":
                return self._text(_captured(
                    U.energy_balance_table, bp=float((q.get("bp", ["300"]))[0]))["text"])
            if path == "/tables":
                return self._text(_captured(
                    U.balance_tables, bp=float((q.get("bp", ["300"]))[0]),
                    n_a=int((q.get("na", ["12"]))[0]),
                    n_b=int((q.get("nb", ["12"]))[0]), color=False)["text"])
            if path == "/horizon":
                d = U.load_game_data(_game_arg(q))
                st = U.state_from_game(d, float((q.get("at", ["30"]))[0]))
                return self._text(_captured(
                    U.build_horizon, st, target=(q.get("target", ["Wind"]))[0],
                    bp_source=(q.get("bpsrc", ["ConTurret"]))[0],
                    wind=float((q.get("wind", ["11.9"]))[0]),
                    n_rows=int((q.get("rows", ["4"]))[0]),
                    horizon=float((q.get("until", ["240"]))[0]))["text"])
            if path in ("/viz", "/viz/horizon"):
                import horizon_viz as HV
                depth = _floats(q, "depth") or list(HV.DEFAULT_DEPTH)
                pay = HV.build_payload(
                    game=_game_arg(q), at=float((q.get("at", ["30"]))[0]),
                    target=(q.get("target", ["Wind"]))[0],
                    bp_source=(q.get("bpsrc", ["ConTurret"]))[0],
                    energy_source=(q.get("energy", ["Solar"]))[0],
                    on=(q.get("on", ["Mex"]))[0], depth=depth,
                    horizon=float((q.get("until", ["240"]))[0]))
                if (q.get("fmt", ["html"]))[0] == "json":
                    return self._send(pay)
                return self._send(HV.render(pay).encode("utf-8"), 200,
                                  "text/html; charset=utf-8")
            if path == "/jobs":
                with LOCK:
                    return self._send({"jobs": [
                        {k: v for k, v in j.items() if k not in ("log", "traceback")}
                        for j in sorted(JOBS.values(), key=lambda x: x["queued_at"])]})
            if path.startswith("/jobs/"):
                jid = path.split("/", 2)[2]
                with LOCK:
                    j = JOBS.get(jid)
                if not j:
                    return self._send({"error": f"no job {jid}"}, 404)
                return self._send(j)
            return self._send({"error": f"no route {path}"}, 404)
        except Exception as e:                                        # noqa: BLE001
            return self._send({"error": f"{type(e).__name__}: {e}",
                               "traceback": traceback.format_exc()[-3000:]}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send({"error": "body must be JSON"}, 400)
        if path != "/jobs":
            return self._send({"error": f"no route {path}"}, 404)
        action = body.pop("action", None)
        if not action:
            return self._send({"error": "need an action"}, 400)
        jid = _job(action, body)
        return self._send({"job": jid, "action": action, "params": body,
                           "poll": f"/jobs/{jid}"}, 202)


def main() -> None:
    ap = argparse.ArgumentParser(description="bar-calc service")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--workers", type=int, default=1,
                    help="parallel jobs; keep at 1 so replays do not fight over the engine")
    ap.add_argument("--no-exit", action="store_true", help="kept for symmetry; server always stays up")
    a = ap.parse_args()
    for _ in range(max(1, a.workers)):
        threading.Thread(target=_worker, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"[calc] listening on http://127.0.0.1:{a.port}  "
          f"({a.workers} worker) data -> {U.GAME_DATA_DIR}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("[calc] stopping", flush=True)


if __name__ == "__main__":
    main()

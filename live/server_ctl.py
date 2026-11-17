#!/usr/bin/env python3
"""server_ctl.py — manage the live analytics server process.

    python server_ctl.py status              # who is on the port + health probe
    python server_ctl.py start [--port P]    # start detached (--no-exit), log to server_output.log
    python server_ctl.py stop
    python server_ctl.py restart             # stop (if running) + start fresh code

Restart is how new code gets ACTIVATED: a running server keeps the module
versions it was started with.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "server_output.log")


def port_pid(port):
    out = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
            return int(parts[4])
    return None


def probe(port, timeout=3):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/snapshots",
                                    timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def status(port):
    pid = port_pid(port)
    if not pid:
        print(f"stopped (nothing listening on {port})")
        return False
    h = probe(port)
    if h:
        print(f"running: PID {pid} on {port} · minutes={h.get('count')} "
              f"gameSeconds={h.get('gameSeconds')}")
    else:
        print(f"PID {pid} owns port {port} but /api/snapshots does not answer "
              f"(wedged or not our server)")
    return True


def stop(port):
    pid = port_pid(port)
    if not pid:
        print(f"already stopped ({port} free)")
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    for _ in range(20):
        if not port_pid(port):
            print(f"stopped PID {pid}")
            return
        time.sleep(0.25)
    print(f"WARNING: PID {pid} did not release port {port}")


def start(port, extra=()):
    if port_pid(port):
        print(f"already running on {port} — use restart to activate new code")
        return
    logf = open(LOG, "a", encoding="utf-8")
    logf.write(f"\n=== server_ctl start {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    p = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "bar_analytic_server.py"),
         "--no-exit", "--port", str(port), *extra],
        cwd=HERE, stdout=logf, stderr=subprocess.STDOUT,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    for _ in range(24):
        if probe(port):
            print(f"started: PID {p.pid} on {port} · log -> {LOG}")
            return
        time.sleep(0.5)
    print(f"started PID {p.pid} but no health answer yet — check {LOG}")


def main():
    ap = argparse.ArgumentParser(description="analytics server control")
    ap.add_argument("cmd", choices=["status", "start", "stop", "restart"])
    ap.add_argument("--port", type=int, default=8787)
    a, extra = ap.parse_known_args()
    if a.cmd == "status":
        status(a.port)
    elif a.cmd == "stop":
        stop(a.port)
    elif a.cmd == "start":
        start(a.port, extra)
    elif a.cmd == "restart":
        stop(a.port)
        start(a.port, extra)


if __name__ == "__main__":
    main()

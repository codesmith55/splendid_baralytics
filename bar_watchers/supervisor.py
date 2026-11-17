#!/usr/bin/env python3
"""Top-level supervisor for the watcher stack.
Keeps lobby_monitor alive, periodically runs replay_fetcher / retention /
dashboard / alerter / healthcheck.

Meant to be run as a Windows scheduled task at logon, or via install_service.
"""
from __future__ import annotations
import argparse, os, subprocess, sys, time, signal
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable

def spawn(script: str) -> subprocess.Popen:
    log = HERE / "context" / "supervisor.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    lf = open(log, "ab")
    return subprocess.Popen([PY, str(HERE / script)],
                            stdout=lf, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL,
                            start_new_session=True)

def maybe_run(script: str):
    """Run a one-shot script, best-effort."""
    try:
        subprocess.run([PY, str(HERE / script)], timeout=180, check=False)
    except Exception as e:
        print(f"[supervisor] {script} failed: {e}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dashboard-every-s", type=float, default=60.0)
    p.add_argument("--replay-every-s",    type=float, default=600.0)
    p.add_argument("--retention-every-s", type=float, default=86400.0)
    p.add_argument("--alerter-every-s",   type=float, default=60.0)
    p.add_argument("--health-every-s",    type=float, default=120.0)
    args = p.parse_args()

    print(f"[supervisor] starting under pid {os.getpid()}")
    lobby = spawn("lobby_monitor.py")

    stop = [False]
    def shutdown(_signum, _frame):
        print("[supervisor] shutdown requested"); stop[0] = True
    for s in (signal.SIGINT, signal.SIGTERM):
        try: signal.signal(s, shutdown)
        except Exception: pass

    schedule = {
        "dashboard.py":      time.time(),
        "alerter.py":        time.time(),
        "healthcheck.py":    time.time(),
        "replay_fetcher.py": time.time() + args.replay_every_s,
        "retention.py":      time.time() + args.retention_every_s,
    }
    intervals = {
        "dashboard.py":      args.dashboard_every_s,
        "alerter.py":        args.alerter_every_s,
        "healthcheck.py":    args.health_every_s,
        "replay_fetcher.py": args.replay_every_s,
        "retention.py":      args.retention_every_s,
    }

    while not stop[0]:
        if lobby.poll() is not None:
            print(f"[supervisor] lobby_monitor died (rc={lobby.returncode}), restarting")
            lobby = spawn("lobby_monitor.py")

        now = time.time()
        for s, due in list(schedule.items()):
            if now >= due:
                maybe_run(s)
                schedule[s] = now + intervals[s]
        time.sleep(10)

    print("[supervisor] terminating children...")
    try: lobby.terminate()
    except Exception: pass
    print("[supervisor] done")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""barbots/bots/run_bot.py — the bot loop: Watcher → Decider → Adapter → Acter.

Distributed roles over the ryan_adapter relay; each can run on a different PC:

    watcher   live/bar_analytic_server.py (widget JSONL → /api/state)   [exists]
    decider   THIS process — polls /api/state, emits playstyle intents
    adapter   barbots/adapter/bar_adapter.py — intent → input transcript
    acter     ryan_adapter `python -m relay acter` — injects the input

Modes:
    --offline GAME       decide every recallable minute of an archived game,
                         expand each to a transcript, print. No hub, no BAR.
    --demo GAME          same game, but run hub + adapter + dry acter
                         in-process and push everything through the real relay.
    (default: live)      poll the running analytics server, send intents to
                         the hub; adapter + acter run as their own processes.

    python run_bot.py --offline "C:/path/game.jsonl" --profile tech_rush
    python run_bot.py --demo 1
    python run_bot.py --profile energy_first --team 3 --cooldown 20
"""
from __future__ import annotations
import argparse, json, os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
BARBOTS = os.path.normpath(os.path.join(HERE, ".."))
RYAN_ADAPTER = os.path.normpath(os.path.join(BARBOTS, "..", "..", "ryan_adapter"))
for p in (os.path.join(BARBOTS, "decider"), os.path.join(BARBOTS, "adapter"), RYAN_ADAPTER):
    if p not in sys.path:
        sys.path.insert(0, p)

import decider as D                            # noqa: E402
from profiles import DEFAULT_PROFILE, PROFILES  # noqa: E402
from transcript import expand                   # noqa: E402


def _pick_team(snap, team):
    if team is not None:
        return team
    alive = [t["teamID"] for t in snap.get("teams", []) if not t.get("dead")]
    return alive[0] if alive else None


def _fmt_t(gs):
    return f"{int(gs) // 60}:{int(gs) % 60:02d}"


# ── offline: archived game, minute by minute, no relay ────────────────────
def offline(game_ref, profile, team):
    from bar_analytic_server import load_game
    game = load_game(game_ref)
    minutes = game.minutes()
    print(f"offline run: {len(minutes)} minutes, profile={profile}")
    last = None
    for m in minutes:
        snap = game.recall(m)
        if not snap:
            continue
        tid = _pick_team(snap, team)
        if tid is None:
            continue
        d = D.decide(snap, tid, profile)
        if d.get("type") != "build":
            print(f"  m{m:>2} team {tid}: {d.get('type')} ({d.get('reason', '')})")
            continue
        try:
            batch = expand(d)
            n = len(batch["actions"])
        except KeyError as e:
            batch, n = None, 0
        marker = "" if d["action_id"] == last else "  ← change"
        last = d["action_id"]
        print(f"  m{m:>2} team {tid}: [{d['profile']}] {d['action_id']:<18} "
              f"score {d['score']:>7.1f} → {n:>2} input actions{marker}")


# ── live: poll /api/state, push intents to the hub ────────────────────────
def live(server, profile, team, interval, cooldown, host, port, channel):
    from relay.client import RelayClient
    c = RelayClient(role="decider", name=f"barbot-{profile}",
                    channel=channel, host=host, port=port).connect()
    print(f"[bot] {c.client_id} profile={profile} polling {server} every {interval}s")
    last_action, last_sent = None, 0.0
    try:
        while True:
            try:
                snap = D.snapshot_from_live(server)
            except OSError as e:
                print(f"[bot] watcher unreachable: {e}")
                time.sleep(interval)
                continue
            if snap.get("over"):
                print("[bot] game over")
                break
            tid = _pick_team(snap, team)
            if tid is None:
                time.sleep(interval)
                continue
            d = D.decide(snap, tid, profile)
            now = time.time()
            if d.get("type") == "build" and \
                    (d["action_id"] != last_action or now - last_sent >= cooldown):
                d["team"] = tid
                mid = c.send("intent", d)
                ack = c.ack_of(mid, timeout=5)
                dst = ack.get("delivered") if ack else None
                print(f"[bot] t={_fmt_t(snap.get('gameSeconds', 0))} team {tid}: "
                      f"{d['action_id']} (score {d['score']}) -> {dst or 'NO ADAPTER'}")
                res = c.wait_for("result", re=mid, timeout=10)
                if res:
                    print(f"[bot]   enacted: {json.dumps(res.get('payload'))}")
                last_action, last_sent = d["action_id"], now
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        c.close()


# ── demo: whole distributed chain in one process, dry acter ───────────────
def demo(game_ref, profile, team, port=8899):
    from relay import hub as hubmod, acter as actermod
    from relay.client import RelayClient
    import bar_adapter
    from bar_analytic_server import load_game

    threading.Thread(target=hubmod.serve,
                     kwargs=dict(host="127.0.0.1", port=port), daemon=True).start()
    time.sleep(0.4)
    threading.Thread(target=actermod.run,
                     kwargs=dict(backend="dry", channel="bar", port=port),
                     daemon=True).start()
    threading.Thread(target=bar_adapter.run,
                     kwargs=dict(host="127.0.0.1", port=port, channel="bar"),
                     daemon=True).start()
    time.sleep(0.4)

    game = load_game(game_ref)
    c = RelayClient(role="decider", name=f"barbot-{profile}",
                    channel="bar", port=port).connect()
    print(f"\n=== demo: {len(game.minutes())} minutes through the full relay chain ===\n")
    last = None
    for m in game.minutes():
        snap = game.recall(m)
        tid = _pick_team(snap, team) if snap else None
        if tid is None:
            continue
        d = D.decide(snap, tid, profile)
        if d.get("type") != "build" or d["action_id"] == last:
            continue
        last = d["action_id"]
        print(f"--- minute {m}: decider chose {d['action_id']} ---")
        mid = c.send("intent", d)
        res = c.wait_for("result", re=mid, timeout=10)
        print(f"--- enacted: {json.dumps(res.get('payload')) if res else 'TIMEOUT'} ---\n")
    c.close()
    print("=== demo done (ledger recorded on the hub) ===")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="BAR bot loop (watcher→decider→adapter→acter)")
    ap.add_argument("--profile", default=DEFAULT_PROFILE, choices=list(PROFILES))
    ap.add_argument("--team", type=int, default=None)
    ap.add_argument("--offline", default=None, metavar="GAME")
    ap.add_argument("--demo", default=None, metavar="GAME")
    ap.add_argument("--server", default="http://localhost:8787")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--cooldown", type=float, default=30.0,
                    help="min seconds between repeats of the same intent")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--channel", default="bar")
    a = ap.parse_args()

    if a.offline:
        offline(a.offline, a.profile, a.team)
    elif a.demo:
        demo(a.demo, a.profile, a.team)
    else:
        live(a.server, a.profile, a.team, a.interval, a.cooldown,
             a.host, a.port, a.channel)

#!/usr/bin/env python3
"""barbots/adapter/bar_adapter.py — the BAR Adapter role on the relay.

Sits between decider and acter: receives `intent` envelopes, expands each to
a keyboard/mouse transcript (transcript.py + keymap.json), sends the
`actions` batch onward, and confirms the acter's `result` back to whoever
sent the intent.

    python bar_adapter.py [--host HUB] [--port 8765] [--channel bar]
    python bar_adapter.py --once '{"type":"build","action_id":"wind","count":3}'

Requires a running relay hub (ryan_adapter: `python -m relay hub`).
"""
from __future__ import annotations
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RYAN_ADAPTER = os.path.normpath(os.path.join(HERE, "..", "..", "..", "ryan_adapter"))
if RYAN_ADAPTER not in sys.path:
    sys.path.insert(0, RYAN_ADAPTER)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from relay.client import RelayClient          # noqa: E402
from transcript import expand, load_keymap    # noqa: E402


def run(host="127.0.0.1", port=8765, channel="bar", keymap_path=None):
    keymap = load_keymap(keymap_path) if keymap_path else load_keymap()
    c = RelayClient(role="adapter", name="bar-adapter", channel=channel,
                    host=host, port=port).connect()
    print(f"[adapter] {c.client_id} on '{channel}' — waiting for intents")

    try:
        while True:
            env = c.recv(timeout=1.0)
            if env is None or env.get("kind") != "intent":
                continue
            intent = env.get("payload", {})
            src = env.get("from", {})
            try:
                batch = expand(intent, keymap)
            except KeyError as e:
                print(f"[adapter] cannot expand intent: {e}")
                c.send("result", {"ok": False, "error": str(e)}, re=env.get("id"))
                continue
            print(f"[adapter] intent from {src.get('role')}/{src.get('name')}: "
                  f"{batch['label']} -> {len(batch['actions'])} actions")
            mid = c.send("actions", batch)
            ack = c.ack_of(mid, timeout=5)
            if not (ack and ack.get("delivered")):
                print("[adapter]   no acter connected — batch not delivered")
                c.send("result", {"ok": False, "error": "no acter connected",
                                  "label": batch["label"]}, re=env.get("id"))
                continue
            res = c.wait_for("result", re=mid, timeout=30)
            payload = res.get("payload") if res else {"ok": False, "error": "acter timeout"}
            print(f"[adapter]   result: {json.dumps(payload)}")
            # close the loop: the intent sender learns what actually happened
            c.send("result", payload, re=env.get("id"), to=src.get("role"))
    except KeyboardInterrupt:
        pass
    finally:
        c.close()


def once(intent_json, host, port, channel):
    """Expand one intent and push it through the relay (or print if no hub)."""
    intent = json.loads(intent_json)
    batch = expand(intent)
    print(json.dumps(batch, indent=2))
    try:
        c = RelayClient(role="adapter", name="bar-adapter-once",
                        channel=channel, host=host, port=port).connect()
    except OSError:
        print("\n[adapter] no hub running — printed transcript only")
        return
    mid = c.send("actions", batch)
    ack = c.ack_of(mid, timeout=5)
    print(f"[adapter] delivered -> {ack.get('delivered') if ack else 'NO ACK'}")
    res = c.wait_for("result", re=mid, timeout=30)
    print(f"[adapter] result: {json.dumps(res.get('payload')) if res else 'none'}")
    c.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="BAR intent → input-transcript adapter")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--channel", default="bar")
    ap.add_argument("--keymap", default=None)
    ap.add_argument("--once", default=None, metavar="INTENT_JSON",
                    help="expand one intent, send it, exit")
    a = ap.parse_args()
    if a.once:
        once(a.once, a.host, a.port, a.channel)
    else:
        run(a.host, a.port, a.channel, a.keymap)

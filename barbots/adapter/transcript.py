#!/usr/bin/env python3
"""barbots/adapter/transcript.py — intent → executor-dialect action transcript.

Turns a decider intent (WHAT: "build wind ×3") into the exact keyboard/mouse
sequence (HOW) in the relay/executors action dialect:

    mouse_move, left_click, right_click, double_click, left_mouse_down/up,
    key, key_down, key_up, type, wait

Complex composites (shift-held queue clicks, select→menu→place chains,
chat lines) are assembled here from keymap.json, so the decider stays
input-free and the acter stays game-free.

    python transcript.py '{"type":"build","action_id":"wind","count":3}'
"""
from __future__ import annotations
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
KEYMAP_PATH = os.path.join(HERE, "keymap.json")


def load_keymap(path=KEYMAP_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _resolve_place(place_id, keymap, jitter=0):
    """Screen coordinate for a placement id. Placeholder resolution: anchors +
    offsets on the configured screen. Replace with world→screen projection
    when a camera-state source exists."""
    scr = keymap.get("screen", {"width": 1920, "height": 1080})
    cx, cy = scr["width"] // 2, scr["height"] // 2
    p = keymap.get("places", {}).get(place_id, {"anchor": "center", "offset": [0, 0]})
    ox, oy = p.get("offset", [0, 0])
    return [cx + ox + jitter, cy + oy]


def _settle(keymap):
    return {"action": "wait", "duration": keymap.get("settle_s", 0.15)}


# ── transcript builders ────────────────────────────────────────────────────
def build_transcript(intent: dict, keymap: dict) -> dict:
    """`build` intent → select builder, open grid item, place (queued if count>1)."""
    aid = intent["action_id"]
    spec = keymap.get("builds", {}).get(aid)
    if spec is None:
        raise KeyError(f"no keymap entry for build {aid!r}")
    count = int(intent.get("count", 1))
    mod = keymap.get("queue_modifier", "shift")

    actions = list(keymap.get("select_idle_builder", []))
    actions.append(_settle(keymap))
    for k in spec.get("grid", []):
        actions.append({"action": "key", "text": k})
    actions.append(_settle(keymap))

    if count > 1:
        actions.append({"action": "key_down", "text": mod})
    for i in range(count):
        xy = _resolve_place(spec.get("place", "center"), keymap, jitter=i * 40)
        actions += [{"action": "mouse_move", "coordinate": xy},
                    {"action": "left_click", "coordinate": xy},
                    _settle(keymap)]
    if count > 1:
        actions.append({"action": "key_up", "text": mod})
    actions.append({"action": "right_click",
                    "coordinate": _resolve_place("center", keymap)})  # drop build cursor

    return {"label": f"build {aid} x{count}", "actions": actions,
            "intent": {k: intent.get(k) for k in ("type", "action_id", "profile", "team", "t")}}


def chat_transcript(intent: dict, keymap: dict) -> dict:
    """`chat` intent → open chat, type, send."""
    msg = intent.get("text", "")
    c = keymap.get("chat", {})
    actions = list(c.get("open", [])) + [
        {"action": "type", "text": msg},
        _settle(keymap),
    ] + list(c.get("send", []))
    return {"label": f"chat: {msg[:40]}", "actions": actions,
            "intent": {"type": "chat"}}


def raw_transcript(intent: dict, keymap: dict) -> dict:
    """`raw` intent passes a hand-built action list straight through."""
    return {"label": intent.get("label", "raw"), "actions": intent["actions"],
            "intent": {"type": "raw"}}


BUILDERS = {
    "build": build_transcript,
    "chat": chat_transcript,
    "raw": raw_transcript,
}


def expand(intent: dict, keymap: dict | None = None) -> dict:
    """Intent dict → actions payload for the relay (`actions` kind)."""
    keymap = keymap or load_keymap()
    kind = intent.get("type")
    fn = BUILDERS.get(kind)
    if fn is None:
        raise KeyError(f"no transcript builder for intent type {kind!r}; "
                       f"have {list(BUILDERS)}")
    return fn(intent, keymap)


if __name__ == "__main__":
    import sys
    intent = json.loads(sys.argv[1]) if len(sys.argv) > 1 else \
        {"type": "build", "action_id": "wind", "count": 3}
    out = expand(intent)
    print(json.dumps(out, indent=2))

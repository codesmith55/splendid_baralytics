#!/usr/bin/env python3
"""Central config for bar_watchers. Reads config.json if present, else defaults.
Every tier imports from here."""
from __future__ import annotations
import json, os
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG_PATH = Path(os.environ.get("BAR_WATCHERS_CFG", str(HERE / "config.json")))

DEFAULTS = {
    "api_all": "https://api.bar-rts.com/battles",
    "api_one": "https://api.bar-rts.com/battles/{id}",
    "api_replays": "https://api.bar-rts.com/replays",
    "cdn_replays": "https://storage.uk.cloud.ovh.net/v1/AUTH_10286efc0d334efd917d476d7183232e/BAR/demos/",

    # lobby_monitor qualifiers
    "qualifiers": {
        "map_contains": "glitters",
        "min_avg_os": 20.0,
        "min_top_os": 30.0,
    },
    "monitor_interval_s": 30.0,
    "watcher_interval_s": 20.0,
    "watcher_max_runtime_s": 7200.0,

    # replay fetcher
    "replay_fetch_delay_s": 900,     # 15 min wait after game_end before first attempt
    "replay_fetch_max_attempts": 6,
    "replay_fetch_backoff_s": 600,   # 10 min between retries

    # dashboard
    "dashboard_interval_s": 60.0,
    "dashboard_html": "dashboard_out/index.html",

    # alerter (optional)
    "alerts": {
        "enabled": False,
        "channels": [],   # list of "toast" | "discord:<webhook>" | "file:<path>"
        "watchlist_usernames": [],    # substring match; alert if any player matches
    },

    # retention
    "snapshot_ttl_days": 14,
    "events_ttl_days": 90,
    "replay_ttl_days": 60,

    # healthcheck
    "stale_after_s": 300,     # if last_seen > this old for a running watcher, flag
}

def _deep_merge(a, b):
    """b overrides a; both are dicts (recursively)."""
    out = dict(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def load():
    cfg = DEFAULTS
    if CFG_PATH.exists():
        try:
            cfg = _deep_merge(DEFAULTS, json.loads(CFG_PATH.read_text()))
        except Exception as e:
            print(f"[config] error loading {CFG_PATH}: {e}, using defaults")
    return cfg

# Write default config if none present, for user editing
if not CFG_PATH.exists():
    try:
        CFG_PATH.write_text(json.dumps(DEFAULTS, indent=2))
    except Exception:
        pass

if __name__ == "__main__":
    import sys
    if "--dump" in sys.argv:
        print(json.dumps(load(), indent=2))
    else:
        print(f"config path: {CFG_PATH}")
        print(f"loaded from: {'file' if CFG_PATH.exists() else 'defaults'}")

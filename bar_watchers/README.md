# bar_watchers — long-running BAR game analytics service

Watches BAR's public battle list continuously, spawns per-game watchers on
qualifiers, archives snapshots + events + replays, renders an HTML dashboard,
optionally alerts on watchlist matches. Zero admin, single scheduled task.

## Architecture

```
   ┌────────────────────────────────────────────────────────────────┐
   │  Windows Scheduled Task ("BAR-watchers-supervisor")            │
   │  Runs supervisor.py at every logon, restarts on crash          │
   └────────────────────────────────┬───────────────────────────────┘
                                    │
                                    ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  supervisor.py                                                 │
   │  - keeps lobby_monitor alive                                   │
   │  - periodically runs dashboard, alerter, healthcheck,          │
   │    replay_fetcher, retention                                   │
   └───┬──────────────────────────┬─────────────┬──────┬────────────┘
       │                          │             │      │
       ▼                          ▼             ▼      ▼
   ┌───────────────┐   ┌────────────────┐   dashboard  alerter
   │lobby_monitor  │   │per-game        │   ↑          ↑
   │polls /battles │──►│game_watcher    │   │          │
   │qualifiers etc │   │polls /battles/N│   ▼          ▼
   └───────┬───────┘   └────┬───────────┘   healthcheck retention
           │                │
           │  writes        │  writes
           ▼                ▼
   ┌────────────────────────────────────────┐
   │  games.db                              │
   │  games / snapshots / events            │
   └───────────────┬────────────────────────┘
                   │  reads
                   ▼
   ┌────────────────────────────────────────┐
   │  game_coordinator.py                   │
   │  list / active / tail / target-json    │
   │  ↑ any downstream program reads here   │
   └────────────────────────────────────────┘
```

## Components

| File | Purpose |
|---|---|
| `config.py` / `config.json`   | Central knobs — qualifiers, intervals, alerts, retention. |
| `watchers_schema.py`          | SQLite schema + `parse_os()` / `summarize_players()`. |
| `lobby_monitor.py`            | Tier 1 — polls lobby list, spawns watchers on qualifiers. |
| `game_watcher.py`             | Tier 2 — polls one battle, writes snapshots + derived events. |
| `game_coordinator.py`         | Tier 3 — read/target CLI for other programs. |
| `supervisor.py`               | Runs everything, self-heals, dispatches maintenance tasks. |
| `dashboard.py`                | Generates `dashboard_out/index.html` (auto-refresh 30s). |
| `alerter.py`                  | Fires toast/Discord/file alerts on new watchlist matches. |
| `replay_fetcher.py`           | After game end, pulls `.sdfz` from bar-rts.com to `replays/`. |
| `retention.py`                | Prunes stale snapshots/events/replays per TTL config. |
| `healthcheck.py`              | JSON status; exits non-zero if stale watchers or missing DB. |
| `install_supervisor_task.ps1` | One-shot Windows scheduled-task installer (no admin needed). |
| `install_supervisor_task.bat` | Double-click launcher for the above. |

## Install (no admin, no reboot)

```
cd splendid_baralytics\bar_watchers
install_supervisor_task.bat        # registers scheduled task at logon
Start-ScheduledTask -TaskName BAR-watchers-supervisor   # start now
```

The task runs as the current user at "Limited" run-level — no UAC prompt.
It auto-restarts every 5 min on failure, up to 999 times. Logs to
`context/supervisor.log`.

## Config (`config.json`)

Every setting in `config.py` `DEFAULTS` can be overridden. Common changes:

```json
{
    "qualifiers": {
        "map_contains": "glitters",
        "min_avg_os": 20.0,
        "min_top_os": 30.0
    },
    "monitor_interval_s": 30,
    "watcher_interval_s": 20,
    "alerts": {
        "enabled": true,
        "channels": ["toast", "file:C:\\Users\\codes\\Desktop\\bar_alerts.log"],
        "watchlist_usernames": ["dolan", "hayaji"]
    }
}
```

Env override: `BAR_WATCHERS_CFG=path\to\alt.json`.

## Data flow

```
lobby_monitor sees new game → INSERT games row → spawn game_watcher
game_watcher polls /battles/{id} every 20s → INSERT snapshots + derived events
game ends (404 or empty)     → UPDATE games.ended_at + watcher_status='ended'
supervisor triggers replay_fetcher 10-15min after ended_at →
    → GET /replays?battleId=N → download .sdfz to replays/ → UPDATE games.replay_path
retention prunes: snapshots older than N days, events older than M, replays L.
```

## Read the state

```bash
python game_coordinator.py list                # everything, active + ended
python game_coordinator.py active              # currently-running watchers
python game_coordinator.py tail 2628 --n 20    # last 20 snapshots + events for a game
python game_coordinator.py target-json         # JSON for downstream consumers
python healthcheck.py                          # {ok, problems, counts}
```

Open `dashboard_out/index.html` in a browser — auto-refreshes every 30s.

## Alerting

Channels (`alerts.channels` in config):
- `"toast"` — Windows 10/11 notification via PowerShell BurntToast (if installed) or a MessageBox fallback.
- `"discord:https://discord.com/api/webhooks/…"` — POST to a Discord webhook.
- `"file:C:\path\alert.log"` — append a line.

`watchlist_usernames` is optional. When set, alerts fire only for games whose
snapshot contains a matching username (case-insensitive substring). Otherwise
alerts fire on every new qualifier.

## Bridging to other systems

- `game_coordinator.py target-json` is the stable interface. Any consumer
  can `subprocess.check_output` it and pick a battle to act on.
- After a game ends, its `.sdfz` sits in `replays/`. Downstream:
  `python ../sdfz-demo-parser/parse.py replays/<file>.sdfz`
  for full unit/resource analysis (the parser ships in this repo).

## Env vars

| Var | Default | Effect |
|---|---|---|
| `BAR_WATCHERS_DB`  | `bar_watchers/context/games.db` | SQLite DB path |
| `BAR_WATCHERS_CFG` | `bar_watchers/config.json`      | Config file path |

## Uninstall

```
Unregister-ScheduledTask -TaskName BAR-watchers-supervisor -Confirm:$false
```

Data in `context/`, `replays/`, `dashboard_out/` remains — delete manually
if desired.

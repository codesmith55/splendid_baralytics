# next_todo.md

_Project: `splendid_baralytics/live`._ _Realtime BAR economy dashboard — Lua widget → JSONL → Python server → browser SVG pies._

_Status: **live v1 shipped.** Widget (bar_analytic_live.lua), server (bar_analytic_server.py), dashboard (dashboard.html) all working. 8-bucket classifier (military / defense / build_power / economy / infrastructure / commander / support / other) + construction + storage slices. Auto-exits after game ends._

---

## Tier 1 — Next up

### T-001 [proposed:M] Classifier sync — propagate live buckets to batch pipeline

`live/` classifier (lua) has `support`, `construction`, `storage` buckets that
`../process/lib/classify.mjs` (canonical batch pipeline) does not yet have.
Propagating touches `economy_composition`, `eco_advisor` metric consumers.
Tracked in `others_to_be_classified.md`.

### T-002 [proposed:S] Pending classifier decisions

Resolve the 5 pending defs in `others_to_be_classified.md`:
- `armdf` / `cordf` — Decoy Fusion (defense? keep other?)
- `armhvytrans` / `corhvytrans` / `corvalk` / `armatlas` — air transports (military?)
- `armfort` / `corfort` / `armdrag` / `cordrag` (+ female variants) — walls/obstacles (defense?)

### T-003 [proposed:M] Role-ordered pie cells

Map start positions to ATG `positionRoles` (all-that-glitters.json) so cells sort
by role (metal-heavy → eco side → fight side) rather than teamID order.

### T-004 [proposed:S] Cosmetic defs — zero-value or ignore bucket

`comeffigylvl1`–`lvl5` (1057–5286 value) and `cor_hat_*` (~1143) would silently
inflate a player's pie if they appear. Add an `ignore` bucket or force value=0.

---

## Tier 2 — Backlog

- **T-005** Per-player history sparklines in hover panel (value/income over time)
- **T-006** WebSocket/SSE push (replace 1 Hz poll for sub-100 ms latency)
- **T-007** UDP transport from widget (<100 ms end-to-end)
- **T-008** Derived KPIs: BP idle %, eco efficiency (metalUsed/metalProduced), army-value slope
- **T-009** Multi-game session log — persist finished game snapshots alongside the JSONL

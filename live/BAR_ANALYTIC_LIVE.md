# bar_analytic_live — realtime BAR economy dashboard

A new entity (superseding the `gex_live` prototype): a live BAR client **widget** that
streams per-team economy state, a Python **consumer/server** that ingests it in
realtime, and a browser **dashboard** that renders it with colorful,
magnitude-encoded indicators.

```
 BAR client                     local machine                         browser
 ┌────────────────────┐  append ┌───────────────────────────┐  HTTP  ┌──────────────────┐
 │ bar_analytic_live   │ ──────▶ │ bar_analytic_live.jsonl    │        │ dashboard.html    │
 │ .lua (widget)        │        └────────────┬──────────────┘        │  2×4 pie grids,   │
 │  per-team value      │           tail +     │ aggregate              │  sized by value,  │
 │  buckets @ 2 Hz      │        ┌─────────────▼──────────────┐ /api   │  hover toplines   │
 └────────────────────┘        │ bar_analytic_server.py       │◀──────▶│  poll 1 Hz        │
                                 │  state + ThreadingHTTPServer │        └──────────────────┘
                                 └─────────────────────────────┘
```

## Components & files
- `bar_analytic_live.lua` — client widget. Emits line-delimited JSON (`actions.json`
  schema, extended with value buckets). Install to `…\data\LuaUI\Widgets\`.
- `bar_analytic_server.py` — tails the JSONL, maintains live state, serves the dashboard
  and a `/api/state` JSON snapshot. Stdlib only.
- `dashboard.html` — the visual dashboard (SVG, no build step).

## Event schema additions (widget → consumer)

The widget keeps the gex schema and **adds a per-team value breakdown** to
`extra_stat_update`, classified with the repo's canonical buckets
(`process/lib/classify.mjs`): value = `metalCost + energyCost/70`, commander = 1200.

| field | meaning | pie slice |
|---|---|---|
| `militaryValue` | mobile combat units (weapon + speed>0) | Military |
| `defenseValue` | static defenses (weapon + speed 0) + radar/jam | Defense |
| `buildPowerValue` | constructors + nano turrets (buildPower, no weapon, not factory) | Build Power |
| `ecoValue` | mexes, energy producers, converters, storage structures | Economy |
| `infraValue` | factories / labs | Infrastructure |
| `commanderValue` | commander(s) (flat 1200 each) | Commander |
| `supportValue` | global-effect multipliers (pinpointers; seeded by name) | Support |
| `otherValue` | uncategorized | Other |
| `constructionValue` | Σ over unfinished units of `value × buildProgress` (invested-but-inert) | Construction (hatched) |
| `storageValue` | `metalCurrent + energyCurrent/70` (held resources) | Storage (grey) |
| `totalValue` | Σ value of **completed** units only (assets); partial units live in `constructionValue` | (in pie pool) |
| topline | `metalIncome`,`energyIncome`,`metalCurrent/Storage`,`energyCurrent/Storage`,`buildPowerAvailable/Used`,`nMex`,`nConv`,`nUnits` | hover panel |

## Dashboard design

### Layout (ATG 8v8 base)
- Two **2×4 grids** of pie charts — one grid per ally team (top = AT0, bottom = AT1).
  16 pies total, one per player. Cells ordered by teamID (role-ordering is a future
  enhancement once the server maps start positions to `all-that-glitters.json` roles).
- A slim header: map, game clock (from latest frame), spectator/fullView badge
  (greyed pies + a "player view — enemy hidden" note when not spectating).

### Encodings (the visual language)
1. **Magnitude = area.** Each pie's **radius ∝ √(totalValue)** so *area* is proportional
   to total asset value — a richer player is a visibly bigger pie ("more, and the scale
   of more"). Radii normalized to the current max across all players, re-scaled each tick.
2. **Composition = slice angle.** Each pie is a donut whose wedges are the value buckets
   (Military/Defense/Build Power/Economy/Infrastructure/Commander/Other), so you read a
   player's strategy at a glance (army-heavy vs eco-heavy vs teching).
3. **Storage = outer ring.** A thin arc ring around each donut, filled 0–100% =
   `storageValue` relative to that player's max storage capacity, two-tone
   (metal arc + energy arc). Full ring → about to overflow; empty → starved.
4. **Income = twin sparkbars** under each pie: a metal bar (light) and energy bar
   (yellow), width ∝ `metalIncome` / `energyIncome` vs the grid max. Quick "who's
   out-producing whom."
5. **Color palette** (consistent across pies):
   - Military `#e5484d` · Defense `#f76b15` · Build Power `#4493f8` ·
     Economy `#30a46c` · Infrastructure `#8e4ec6` · Commander `#ffb224` ·
     Storage(metal) `#c0c5ce` / Storage(energy) `#f5d90a` · Other `#6b7280`.
   - Dead/eliminated team → desaturated + skull glyph.

### Inspection (toplines)
- **Hover** a pie → a topline panel: player name · faction · total value · each bucket
  (value + %) · metal income & stored/capacity · energy income & stored/capacity ·
  build power used/available · #mex · #converters.
- **Always-on mini labels** under each pie: player name + total value (compact, e.g.
  `12.0k`) so the grid is readable without hovering.

### Realtime
- Widget emits every **0.5 s** (15 frames). Server keeps the latest snapshot; dashboard
  **polls `/api/state` at 1 Hz** and tweens pie radii/arcs for smooth growth.
  (Polling chosen over WebSocket/SSE for zero-config robustness.)

### Fog-of-war handling
- If `session.fullView` is false (you're a player, not spectator), only your own/allied
  teams have real data; enemy pies render hollow with a "hidden" hatch and the header
  shows a warning. Spectating a game yields full data for all 16.

## Run
1. Install widget → `…\Beyond-All-Reason\data\LuaUI\Widgets\bar_analytic_live.lua`
   (edit `CONFIG.outPath` if desired). Enable in F11; **spectate** for full data.
2. `python live/bar_analytic_server.py`  (defaults: reads the widget's
   JSONL, serves http://localhost:8787).
3. Open `http://localhost:8787` — start/spectate a game; the grid fills in live.

## Future enhancements
- Role-ordered cells (map start positions → ATG `positionRoles`).
- Per-player history sparklines (value/income over time) in the hover panel.
- WebSocket/SSE push; UDP transport from the widget for <100 ms latency.
- Derived KPIs: BP idle %, eco efficiency (metalUsed/metalProduced), army-value slope.

# Vendored from gex

These two Lua files are the **only content-level dependency** of our headless harness
(see `../headless_harness.md`). They define every stat that lands in `actions.json`.

| File | Upstream path | Role |
|---|---|---|
| `gex.lua` | `gex/gex/gex.lua` | the `game_event_extractor` widget — hooks engine call-ins, writes `actions.json` |
| `BYAR.lua` | `gex/gex/BYAR.lua` | LuaUI config that force-enables the widget (`order = { game_event_extractor = 1 }`) |

- **Source repo:** `C:\Users\codes\Documents\GitHub\gex`
- **Vendored at commit:** `d28c87c`
- **Vendored on:** 2026-06-09

## Install at runtime (per `headless_harness.md` step 5)
- `gex.lua`  → `<ENGINE>/LuaUI/Widgets/gex.lua`
- `BYAR.lua` → `<WRITE_DIR>/LuaUI/Config/BYAR.lua`

## Updating
Re-copy from upstream and bump the commit above when gex changes the widget. A new
`writeJson("<event>", …)` call upstream = a new stat available; mirror it in our `actions.json` parser.
Diff before adopting — the widget is the contract for the whole stat catalog.

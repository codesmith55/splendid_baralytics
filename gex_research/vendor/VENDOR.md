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

## Local patch — do not lose this when re-vendoring

`gex.lua` carries one **local change** on top of upstream, marked `SPLENDID` in the source
(2026-09-22). It adds a `reclaim_sample` event: the per-frame `metalMake` of any unit whose
metal income cannot be passive, i.e. everything except metal extractors and energy converters
(`UNIT_DEF_METAL_PASSIVE`).

Why: upstream's `unit_resources` fires ONCE per unit, at death or game end, as a lifetime
total. That cannot show the SHAPE of a reclaim or separate one reclaimed object from the next.
Measured with the patch: reclaim is a CONSTANT rate held for 29 to 211 frames, never a
one-frame spike, so a single reclaimed object is the integral of one contiguous run.

Consumed by `bar-calc/bar_unified.py` §5 (`reclaim_runs`, `--reclaim-runs`). Re-apply the patch
after any re-vendor, or that analysis stops working and says so.

## Updating
Re-copy from upstream and bump the commit above when gex changes the widget. A new
`writeJson("<event>", …)` call upstream = a new stat available; mirror it in our `actions.json` parser.
Diff before adopting — the widget is the contract for the whole stat catalog.

### Local patch 2 — the BUILD TREE (2026-09-28)

`gex.lua`'s `unit_def` block gained six fields, marked `SPLENDID`:

| field | why |
|---|---|
| `buildOptions` | **the whole point.** Comma-joined defNames of everything this def can build. Upstream emits nothing, so every reader had to hard-code its gates: that an air con needs an air lab, that a Moho needs a T2 con. 5210 edges over 846 defs now come from the engine. |
| `isBuilder` | upstream only derives `isReclaimer = isBuilder and not isFactory`, which throws the flag away for factories |
| `canAssist` | base build power lending itself to a factory |
| `buildDistance` | reach, for the pather |
| `techLevel` | the engine's own T1/T1.5/T2/T3, instead of inferring from names |
| `faction` | emitted, but BAR leaves it empty on 843 of 844 defs, so `econ_db.faction_of` falls back to the defName prefix |

`buildOptions` is a **string**, not an array, because `writeJsonRaw` serialises only
strings, numbers and booleans — handing `io.write` a table crashes the widget.

Consumers: `bar-calc/econ_db.py` (the `build_edges` table) and
`bar-calc/unit_catalog.py`. A dump harvested before this patch has no tree, and
`econ_db --ingest` says so rather than silently returning an empty graph.

# next_todo — barbots

Live BAR bot. Third leg of the analytics stack. Located inside splendid_baralytics.

## Active

- T-001 **Stall + mitigation pass** (planner layer 4) — take `project.mjs` output, annotate goals with stall spans + mitigations in the preference order from `docs/intent-language.md`.
- T-002 **Finish the Legion fusion-path experiment** — the objective-state planner is a work-in-progress (`experiments/legion-t2-fusion-path.mjs`). Consider whether to hardcode 3 medmex as the empirical optimum vs. keep the sweep.
- T-003 **Reader (layer 1)** — start `reader/gexbot.lua` — the fog-honest widget emitting `unit_created`, `extra_stat_update`, `wind_update`, `enemy_seen`, `order_issued` events.
- T-004 **Live adapter (layer 3)** — divergence detection + re-plan-from-live-state.

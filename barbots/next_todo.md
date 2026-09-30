# next_todo — barbots

Live BAR bot. Third leg of the analytics stack. Located inside splendid_baralytics.
Status 2026-07-31: **Watcher→Decider→Acter chain shipped v1** — `decider/` (playstyle
profiles over navigator.step_options), `adapter/` (intent → input transcript),
`bots/run_bot.py` (offline / demo / live modes) over the `ryan_adapter/relay` hub.
Full dry-run round-trip validated on an archived game.

## Active

- T-001 **Stall + mitigation pass** (planner layer 4) — take `project.mjs` output, annotate goals with stall spans + mitigations in the preference order from `docs/intent-language.md`.
- T-002 **Finish the Legion fusion-path experiment** — the objective-state planner is a work-in-progress (`experiments/legion-t2-fusion-path.mjs`). Consider whether to hardcode 3 medmex as the empirical optimum vs. keep the sweep.
- T-003 **Reader (layer 1)** — start `reader/gexbot.lua` — the fog-honest widget emitting `unit_created`, `extra_stat_update`, `wind_update`, `enemy_seen`, `order_issued` events.
- T-004 **Live adapter (layer 3)** — divergence detection + re-plan-from-live-state.
  Partial: `adapter/bar_adapter.py` + `bots/run_bot.py` close the intent→input loop;
  divergence/re-plan still open.
- T-005 **Verify `adapter/keymap.json`** against actual in-game grid bindings + record
  a real Interception-backed session (acter `--backend interception`).
- T-006 **World→screen placement** — replace screen-anchor placeholder clicks in
  `adapter/transcript.py::_resolve_place` with camera-state projection (needs a
  camera source in the widget or reader).
- T-007 **Decider beyond economy** — military/positional intents once `reader/gexbot.lua`
  (T-003) supplies enemy_seen; also replace `mex_cap=7` with real map spot data.

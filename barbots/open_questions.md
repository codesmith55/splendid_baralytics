# open_questions — barbots

- The Legion fusion-path sweep uses cost data sourced from `gex_research/legion/legion_unitdefs.json` — is that the canonical source we want everywhere, or should the planner import from a separate stable schema?
- Commander explosion in the sweep: -25 e/s energy loss. Is that the right number for Legion commander (vs. +25 e/s baseline production)?
- The 4 medmex "trap" (extra medmex slows fusion) — is this real BAR behavior, or an artifact of the eco_engine model?
- Reader will run in the player's unsynced context (fog-honest). What's the plan for testing it without a live game — replay mode + `/globallos` off?
- `adapter/keymap.json` grid keys (`z`+`w/e/r/t/y`) are guesses — what are the actual default grid-menu bindings, and should the adapter read them from BAR's uikeys config instead of hand-maintaining them?
- Placement clicks need world→screen projection — can camera state (`Spring.GetCameraState`) be emitted by the analytics widget, or does the acter machine need its own screen-reading watcher?
- Decider `mex_cap=7` is a stand-in for map mex spots — source real spot counts from map data or from the reader once it exists?
- Relay coupling: `adapter/` and `bots/` import `ryan_adapter/relay` by relative path (`../../../ryan_adapter`) — package it or vendor a sync copy like capabilities_core?

# open_questions — barbots

- The Legion fusion-path sweep uses cost data sourced from `gex_research/legion/legion_unitdefs.json` — is that the canonical source we want everywhere, or should the planner import from a separate stable schema?
- Commander explosion in the sweep: -25 e/s energy loss. Is that the right number for Legion commander (vs. +25 e/s baseline production)?
- The 4 medmex "trap" (extra medmex slows fusion) — is this real BAR behavior, or an artifact of the eco_engine model?
- Reader will run in the player's unsynced context (fog-honest). What's the plan for testing it without a live game — replay mode + `/globallos` off?

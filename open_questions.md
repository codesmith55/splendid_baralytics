# open_questions — splendid_baralytics

- Should barbots move OUT of splendid_baralytics into its own top-level repo now that it's the primary active sub-project? Cross-repo imports of `gex_research/process/lib/sim/eco_engine.mjs` would need packaging.
- gex_research's `_PROVISIONAL` unit costs (con, laz, t2lab) are still hand-typed — should we source everything from `legion_unitdefs.json` like the new fusion-path experiment does?
- Barbots' commander-explosion model: is `-25 e/s` the right number for Legion commander (vs. +25 e/s production)? Verify against actual commander unit-def.

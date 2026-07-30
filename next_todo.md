# next_todo — splendid_baralytics

Monorepo. Four sub-projects: sdfz-demo-parser (top-level npm), bar-calc, gex_research, barbots.

## Active (barbots — most recent activity)

- T-001 **Stall + mitigation pass** (planner layer 4) — consume `project.mjs` output, annotate each goal with stalls and mitigations (pre-walked build power, bank thresholds, reclaim passes). Preference order in `docs/intent-language.md`.
- T-002 **Live adapter** — pair projected vs actual state during play, re-plan on divergence.
- T-003 Extend the Legion fusion-path sweep with commander-explosion and per-decision projection (in progress in `experiments/legion-t2-fusion-path.mjs`).

## gex_research

- T-004 Run more replays through `bar_run_metric` to grow the corpus for position-role priors.
- T-005 Wire `bar_self_reclaim` into the standard run pipeline (currently opt-in via `run_002`).

## sdfz-demo-parser

- T-006 Ship v5.12: cover the recent engine format changes flagged in the last 3 replays.

## bar-calc

- T-007 Publish the wind sim as a callable API for barbots' projection layer (currently only bar_distance is imported).

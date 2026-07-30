# BAR metrics process — dispatch guide

A variable-input pipeline that turns a BAR replay into per-player / per-team metrics over time.
Built on the gex headless extractor (see `headless_harness.md`, `run_report.md`). Designed to be driven
**by dispatch** (phone/remote) — the toolchain is pre-authorized so runs don't stall on prompts.

```
pick demo ──▶ [spring-headless + gex.lua] ──▶ actions.json ──▶ parse ──▶ metrics ──▶ situations ──▶ JSON + HTML
              (only if not already extracted)        (+ demo header → player roster)
```

## TL;DR — run it

```bash
cd C:/Users/codes/Documents/GitHub/splendid_baralytics/gex_research
node process/run.mjs metrics/runs/run-001-economy-composition.json
# outputs → output/run-001/{report.html, metrics.json, situations.json, context.json}
```

The current run reuses the already-extracted 8v8 game. To process a **new** demo, copy the run config,
set `input.source:"headless"` and `input.demoFile` to a `.sdfz` path, and run it — Node drives the whole
chain (replay → parse → metrics) itself.

## The three inputs the process accepts

| Input | File | Command | What it does |
|---|---|---|---|
| **A run** (which metrics + situations over which replay) | `metrics/runs/*.json` | `node process/run.mjs <run.json>` | Executes the run, writes JSON + HTML |
| **Criteria for a NEW metric** | `metrics/criteria-examples/metric.example.json` | `node process/addMetric.mjs <criteria.json>` | Validates, appends a `draft` entry to `catalog.json`, scaffolds `process/lib/metrics/<id>.mjs` |
| **Criteria for a NEW situation** | `metrics/criteria-examples/situation.example.json` | `node process/addSituation.mjs <criteria.json>` | Validates, appends to `situations.json`, scaffolds `process/lib/situations/<id>.mjs` |

After scaffolding a metric/situation, implement its `compute()`/`apply()` (use `economy_composition.mjs` /
`mirror_by_start_position.mjs` as references), flip `status:"draft"→"active"`, then reference its `id` in a
run config.

## Master lists (the catalog)

- **`metrics/catalog.json`** — every metric ever created (the master list you asked to keep). Currently: `economy_composition` (active).
- **`metrics/situations.json`** — every situation (slice/compare/pair). Currently: `per_user`, `mirror_by_start_position` (active).

> Terminology: the engine calls each army a **team**; we present output **per user** (the user controlling that team). Each row carries `userId` + name and the `teamID` they control.

These are the source of truth; `addMetric`/`addSituation` append to them — don't hand-edit unless you know the shape.

## What run-001 computes (your spec)

**Metric `economy_composition`** — per team, per time (every 450 frames = 15 s), the **% of total economy
value by category**, where `value(unit) = metalCost + energyCost/70`:

| bucket | how a unit lands here (field-driven, patch-robust) |
|---|---|
| `build_power` | `buildPower>0` & not a factory — workers (corca/corck/corcv/armca/armck/armcv, butlers/consuls, T2 cons), construction turrets, + commander's build contribution |
| `economy` | energy producers (solar/wind/advsol/fusion), converters, metal extractors, dedicated storage buildings |
| `infrastructure` | `isFactory` — labs / plants |
| `military` | has weapon or radar — units, defenses, radar; **+ commander double-counted at flat 1200** |
| `storage` | resources currently held: `metalCurrent + energyCurrent/70` (from `extra_stat_update`) |
| `other` | fallback |

Commander = 1200, added to **both** build_power and military (your "dbl count"); the denominator includes
both copies so per-category % still sums to 100.

**Situations:** `per_user` (one chart per user / the team they control) and `mirror_by_start_position`
(pairs each user with the opponent at the reflected start spot — 8 pairs for the 8v8). Comparisons use each player's **peak-economy**
snapshot (avoids the degenerate all-dead final frame).

Example result (run-001): at peak, mirror pair **JIN12 vs SUNTZ** → JIN12 +17.3pp economy, SUNTZ +18.9pp
military. The winning side (allyTeam 0) consistently shows fuller economy curves.

## Permissions (already set for dispatch)

Added to `~/.claude/settings.json` allow-list: `Bash(node:*)`, `Bash(npm install:*)`. Because the entire
pipeline runs through Node (it spawns `spring-headless.exe` as a child process), **`Bash(node:*)` is the only
exec permission dispatch needs.** Caveats for unattended runs:
- The machine must stay **powered on and logged in** (headless replay is a real local process).
- First run of a new demo costs ~137 s of CPU (≈10× realtime) for a ~13-min game.

## Directory map

```
gex_research/
  DISPATCH.md                 ← this file
  gex_process.md, headless_harness.md, run_report.md   ← research + recipe + first-run writeup
  vendor/gex.lua, BYAR.lua    ← the stat-extraction widget (the contract; do not drift silently)
  metrics/
    catalog.json              ← MASTER metric list
    situations.json           ← MASTER situation list
    runs/run-001-*.json       ← per-run configs (variable input)
    criteria-examples/        ← templates for addMetric / addSituation
  process/
    run.mjs                   ← execute a run
    addMetric.mjs, addSituation.mjs   ← register new metric/situation from criteria
    lib/
      parseActions.mjs        ← actions.json → grouped events + defMap
      classify.mjs            ← unit → bucket + value (metal+energy/70, commander)
      context.mjs             ← start positions, ally inference, roster join, map center
      headless.mjs            ← spawn spring-headless on a demo (isolated write-dir)
      roster.mjs              ← load/produce player roster
      registry.mjs            ← resolve metric/situation id → module
      chart.mjs               ← self-contained HTML report (inline SVG)
      metrics/economy_composition.mjs
      situations/per_team.mjs, mirror_by_start_position.mjs
  tools/demoparser/           ← npm sdfz-demo-parser wrapper → roster JSON (names/faction/ally/startPos)
  sample_output/actions.json  ← the extracted 8v8 game (fixture)
  output/run-001/             ← run outputs
```

## Dispatch recipes (copy-paste briefs)

- **New economy run on demo X:** copy `metrics/runs/run-001-economy-composition.json` → set
  `input.source:"headless"`, `input.demoFile:"<X.sdfz>"`, `output.dir:"../../output/<name>"`, run
  `node process/run.mjs metrics/runs/<name>.json`.
- **Batch many demos:** loop the above over a list of `.sdfz` paths (one run config each, or extend run.mjs
  to accept a glob — currently one replay per run).
- **Add a metric (e.g. eco efficiency, army timing, expansion count):** edit
  `metrics/criteria-examples/metric.example.json`, run `addMetric.mjs`, implement the scaffold.
- **Add a situation (e.g. by_faction, by_skill_bucket, winners_vs_losers):** edit the situation template,
  run `addSituation.mjs`, implement the scaffold.

## Known limitations / next steps

1. **One replay per run** — batching is a loop today; could fold into run.mjs.
2. **Unit→bucket edge cases** — classification is field-driven with seed names; spot-check exotic units
   (drones, shields, nukes) against `catalog.json` seedNames and tune `classify.mjs` if needed.
3. **`infrastructure` excludes the commander** (it's not a factory) — intended.
4. **Mirror pairing** uses start-position reflection across the centroid; for maps with asymmetric starts,
   verify pair `distance` is small (run-001 pairs were gap < 100 = near-exact mirrors).
5. **HTML chart shows the peak snapshot**; the full per-time series lives in `metrics.json` (53 samples/team)
   for plotting eco curves / build-order timing.

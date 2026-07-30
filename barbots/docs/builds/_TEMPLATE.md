<!--
  Copy this file to docs/builds/<slug>.md and fill it in. Keep the section order:
  it mirrors first-unit-rush.md and gunslinger-turnaround.md so builds stay diffable
  and an AI process can populate them mechanically. Delete these HTML comments as you go.

  Honesty discipline (non-negotiable): every number is either sourced from
  planner/data/units.json (cite the key) or flagged a placeholder. Never invent unit
  stats. Unknowns go in "Values still needed", mirroring the _PROVISIONAL convention.
-->
---
build: <slug>                      # kebab-case, == filename stem
status: idea                       # idea | analysis | intent-ready | scored
question: <the one-sentence question this build answers>
checkpoint: <the shared finish line builds are graded to, e.g. "1-2 gunslingers on field">
gate: <unknown until analysed>     # build-power | metal | energy | mixed — the binding clock
needs: []                          # list of missing canonical values (see last section)
patch: {}                          # optional: { unit: { field: [old, new] } } if patch-sized
sources: [planner/data/units.json] # cost tables / refs this analysis leans on
---

# Build: <name>

> <One- or two-sentence statement of the build and the bet it makes.>

Shared model and currency: [README.md](README.md).

## The reframe / the maneuver

<!-- What is this build *actually* doing, economically? State it as a machine: what it
spends, what it produces, what it liquidates. Call out which of the three clocks you
expect to bind, and why — this is where most builds reveal they're not what they look
like (see first-unit-rush's "BP isn't the bottleneck, energy is"). -->

## Phases / ledger

<!-- Break the build into phases. For each: the build-work lump, and the metal/energy
ledger entry (+reclaim, −cost). A table is usually clearest:

| # | phase | build-work | metal | energy |
|---|---|---|---|---|
-->

## The three clocks, applied

<!-- Write the formulas with symbols for anything not yet known:
T_bp(n)   = [ Σ build-work ] / B
M_out(n)  / M_in(n)   (income·T + reclaim lumps)
E_out(n)  / E_in(n)
T(n)      = max( T_bp , E_out/E_f , metal-stall if M_out > M_in )
-->

### Worked example (placeholders flagged)

<!-- Pick concrete inputs (eco, BP, counts). Tabulate the target(s) vs the gate. Mark
every guessed number as a placeholder; cite the rest to units.json. -->

## Findings

<!-- 2-4 numbered findings that answer the `question`. Each should name the gate, the
lever (what makes it faster/viable), and any threshold that flips the verdict (e.g. a
patch number, a contested-resource amount, a crossover count). -->

## Values still needed

<!-- The canonical numbers that turn this from symbolic to exact. Mirror the `needs:`
front-matter. Cite where each lives (unit def file, live reader emit, replay calibration).
Until these land, the build's `status` cannot pass `analysis`. -->

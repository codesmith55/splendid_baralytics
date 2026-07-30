# Build analysis

Build *ideas* worked out as economic comparators. Each one states a build, derives its
critical-path math, names the resource that gates it, and lists the values still needed
to turn a symbolic estimate into a real number.

These are not committed plans — they are candidates the planner will eventually **score
against each other in lost-seconds** (the gex_research convention: every build is judged
by projected time to a shared checkpoint). The eco_engine projection bridge (the next
planner dev task) is the machinery that will turn each candidate's costed action list
into a timeline; the docs here define the *value terms* that get added on top of raw
checkpoint time.

## The shared model: the three clocks

Every build job has a metal cost `m`, an energy cost `e`, and **build-work** `w`
(buildpower-seconds, `units/*.lua` `buildTime`), and is run by a builder of power `BP`.
Once your starting banks drain, the job's wall-clock time is the **slowest of three
clocks**:

| clock | formula | bound by |
|---|---|---|
| build-power | `w / BP` | how fast the builder can work |
| metal | `m / M_income` | metal to feed it |
| energy | `e / E_income` | energy to feed it |

Worked for the commander (BP 300) on a ~3-mex opening (≈6 M/s; **≈20–25 E/s with no
solar** — calibrate against true com base income), costs from
[`planner/data/units.json`](../../planner/data/units.json):

| build | BP clock | metal clock @6 M/s | energy clock @20 E/s |
|---|---|---|---|
| mex (50 m / 500 e / 1800 w) | 6 s | 8.3 s | **25 s** ← |
| solar (155 m / 0 e / 2600 w) | 8.7 s | 25.8 s | 0 |
| botlab (620 m / 1200 e / 6500 w) | 21.7 s | **103 s** ← | 60 s |

Two consequences drive everything in the scenario docs:

1. **Early game, build power is not the bottleneck.** The com (BP 300) can spend ~28
   metal/s on a factory but a small eco delivers ~6 M/s. "Rushing build power" rarely
   speeds the opening — the com is already BP-saturated. What you rush is *what the BP
   produces*: the first unit, the first T2 unit.
2. **Energy is the sneaky gate.** A mex is 500 energy to build; with no solar it runs on
   the 25 s energy clock, not the 6 s BP clock. Solar/wind exist to *unlock the energy
   clock*, not to "run" the eco. A build that skips solar only survives if its remaining
   steps are energy-light.

## Currency: lost-seconds

A build A beats B if it reaches the shared checkpoint sooner. Non-eco payoffs (rock
metal captured, enemy eco destroyed, denial of a contested resource) convert to seconds
via a **compound-weighting factor**: early metal is worth its later self *plus* the
income it could have seeded. That factor is calibratable from gex_research replay eco
curves (not yet measured).

## Cost source & honesty

Costs come from [`planner/data/units.json`](../../planner/data/units.json): buildings are
canonical (transcribed from `bar-calc`); bot units and the T2 lab are flagged
`_PROVISIONAL` (bar-calc only tables buildings). Numbers here inherit those flags, and
each doc ends with the canonical values it still needs.

## Scenarios

- [first-unit-rush.md](first-unit-rush.md) — skip mexes / skip-or-delay solar, stand the
  factory up cheaper, bet on the first unit out (Lazarus on rocks, aggression, or
  workers).
- [gunslinger-turnaround.md](gunslinger-turnaround.md) — front-player pivot: reclaim T1
  labs, build a T2 lab, pop one Consul, sell the lab, and stabilize on 1–2 Gunslingers
  (sized to a community patch).
- [comm-reclaim-t2-rush.md](comm-reclaim-t2-rush.md) — reclaim the commander + T1 lab to
  fund a **standing** (not sold) T2 lab + T2 con + metal storage for a sustained Gunslinger
  or Persecutor rush. Gated on whether commander-reclaim is legal in context before any
  economics apply.

## How to add a build

- [`_TEMPLATE.md`](_TEMPLATE.md) — copy-me skeleton (front-matter + section order every
  build follows, so they stay diffable).
- [PROCESS.md](PROCESS.md) — the investigation loop: question → economic machine → pull
  costs → three clocks → worked example → find the flip → findings → unknowns → (when
  concrete) emit an intent and compile-check it.
- [DISPATCH.md](DISPATCH.md) — design for running that loop from a terse **mobile dispatch
  prompt**: an AI process reads the cost tables, fills the template, compile-checks an
  intent, and replies with the gate, the number, and the open unknowns.

Each build doc carries machine-readable front-matter (`build`, `status`, `question`,
`checkpoint`, `gate`, `needs`), which is the surface AI processes use to `list`, `compare`
(same-checkpoint only), and `rescore` builds.

## Global unknowns (shared by every scenario)

- the commander's true **base M/s and E/s** (the energy clock above is the whole
  argument — it must be exact).
- the **compound-weighting factor** for early metal.
- **reclaim yield rules**: does reclaiming an own building return ~100% of its metal, and
  any energy? (assumed metal-only and ~full below — conservative, verify).

## Next steps (build-analysis track)

1. **Registry index** — a generated `builds.json` (or a one-line `list` over the
   front-matter) so a process can enumerate builds, their `status`, `gate`, and open
   `needs` without parsing prose.
2. **Dispatch trigger** — implement the [DISPATCH.md](DISPATCH.md) loop as a
   `build-investigator` skill (and/or a routed agent watching an inbox) so `/build …` from
   the mobile app produces a build doc end-to-end.
3. **Auto-intent + compile gate** — for concrete builds, have the loop emit
   `intents/<slug>.md` and gate `status: intent-ready` on a clean `parse-intent` →
   `expand-goals`.
4. **Auto-score on projection** — once the eco_engine projection bridge lands (see
   [../../NEXT_TASK.md](../../NEXT_TASK.md)), score `intent-ready` builds to a checkpoint
   time, and **rescore** automatically when `units.json` or a `needs[]` value changes.
5. **Close the shared unknowns above** — they bound the accuracy of every build at once,
   so they outrank any single build's own `needs[]`.

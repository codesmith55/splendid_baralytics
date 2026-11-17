# Scouting → opponent economy estimation (future idea spec)

## The question

Scouting an opponent yields glimpses, not their ledger. The function to build is not
"what is their economy" (unknowable) but:

> **"Based on what I've seen, where are they in their economy compared to me, and how
> should that influence my meta choices (military pressure vs e-gen scaling)?"**

## Data model: the sighting ledger

Every enemy unit that enters vision/radar is recorded once with full context (the
fog-honest reader, docs/architecture.md, already emits this):

```json
{ "t": 312, "defName": "corwin", "x": 4120, "z": 1480, "conf": "los" }
{ "t": 318, "defName": null,    "x": 4300, "z": 1500, "conf": "radar" }
```

Sightings are never silently updated — a solar seen at 2:00 still exists in the
estimate at 6:00 unless its destruction was witnessed. Stale sightings decay in
confidence, not existence (matching how a human treats old scouting).

## Estimation: observed lower bound + priors

1. **Observed floor.** Sum the value/income of everything sighted (gex defs give
   eProd/mPerSec). This is a hard lower bound: they have AT LEAST this.
2. **Coverage estimate.** What fraction of their base did the scout actually see?
   (Scout path ∩ their build area, from start positions + typical base radius.)
   Seeing 12 winds across 40% of their base → central estimate scales to ~30, with
   wide uncertainty; floor stays 12.
3. **Template priors.** Replay analysis (gex_research) gives per-position expected
   economy curves — ATG position roles make this strong: a Tech-slot player at 4:00
   has a known income distribution (run-002 data: ~17k metal committed for an actual
   tech player). Prior = position role curve; sightings update it.
4. **Time projection.** Sightings age: a T2 lab seen STARTED at 4:00 implies T2 cons
   ~5:30 and a T2 mex shortly after, even if unseen since — project forward with the
   eco_engine, exactly like projecting own builds.

Output, per scouted opponent:

```json
{ "team": 9, "asOf": 360,
  "floor":   { "eIncome": 180, "mIncome": 14, "t2": false },
  "central": { "eIncome": 320, "mIncome": 22, "t2": "lab ~60% likely started" },
  "vsMe":    { "eco": "-15% to +25%", "verdict": "roughly even, T2 race live" },
  "staleness": 48 }
```

## Decision policy: what the estimate changes

The estimate feeds the planner as pressure on exactly two dials plus one standing rule:

1. **Military vs e-gen scaling dial.**
   - They are ECO-AHEAD → raiding pressure now is high-value (their army is thin;
     every eco building killed resets the gap) → bias factory output military,
     delay own scaling.
   - They are ECO-BEHIND → they likely went units → expect pressure, buy defense/
     units to survive it, then out-scale: bias e-gen + tech.
   - EVEN → tiebreakers: wind conditions (good wind favors scaling), map control,
     own build's checkpoint proximity (don't abandon a T2 mex 30s from done).
2. **Tech-race timer.** Any T2-signal sighting (T2 lab, T2 unit, adv mex) starts a
   countdown that re-justifies own fast-T2 or punishes theirs (T2 lab is a planned
   dive — they are weakest during it; the lost-seconds engine can price an attack
   window vs an eco window).
3. **Standing mex rule.** If you can take mexes, generally take mexes — T1 first,
   then T2. Mex income compounds for the rest of the game; almost no estimate state
   reverses this. The estimator only modulates HOW contested a mex spot is (their
   army central estimate near the spot), not WHETHER expansion is good.

## Framing note

All outputs are comparative ("where are they vs me") and probabilistic (floor /
central / staleness). The bot must never act on the central estimate as fact when
the floor would change the decision — e.g. attack timing can be justified by the
floor ("even their minimum eco means my window closes at 8:00"), while scaling
choices may use the central estimate.

## Build order (when this gets implemented)

1. Sighting ledger in the reader (cheap, do with the fog-honest reader anyway)
2. Observed floor + vsMe comparison (pure arithmetic over the ledger)
3. Position-role priors from gex_research replay corpus (needs more replays)
4. Coverage-scaled central estimate + forward projection
5. Decision dials wired into the planner

# Intent language — declared builds compiled to goal DAGs

An **intent** is a player-authored build declaration in natural build-order shorthand.
The planner compiles it into a goal DAG with resource projections, stall flags, and
mitigations. The live adapter then walks the DAG against reality.

## Reference intent (the spec driver)

> Execute a 3 mex 2 solar factory 2 solar into com rushing 2 workers, into all 3
> builders taking a 6th mex, giving away one of the workers to our air player (meta
> action, timer = give early enough that the con's walk ends as it can start building
> air's bottom-left mex). From there taking 7 mex, getting to about 25 wind based on
> current wind conditions, and go for a fast T2 factory. T1 factory is queued 3 con,
> laz, con, laz, infinite con. 1st laz eats available rocks in the general area of
> the 6 non-canyon players' starting bases.
> **First goal time: finish a T2 mex.**

## What the language needs (each from the reference intent)

| Construct | Example from reference | Compiled meaning |
|---|---|---|
| sequenced builds | `3 mex 2 solar factory 2 solar` | ordered goals with counts |
| assist directive | `com rushing 2 workers` | com assists factory until worker2 out |
| group action | `all 3 builders taking a 6th mex` | parallel goals, one per builder, shared target count (6 total) |
| **meta action + walk timer** | `give worker to air player` | `give_unit` scheduled so walk ends at readiness: giveTime = T(airMex.start) − walkTime(gift point → air bottom-left mex) |
| count-to-target | `taking 7 mex` | expand to (7 − current) mex goals, site-assigned |
| **conditional count** | `about 25 wind based on current wind conditions` | windTarget = f(observed wind μ over last N min, map minWind/maxWind): at ATG μ≈10–13 keep 25; low-wind reading → planner substitutes solar-equivalent e/s |
| tech goal | `fast T2 factory` | T2 lab goal; "fast" = prioritize on critical path, allow planned dive (duo-geo-rush precedent) |
| factory queue | `3 con, laz, con, laz, infinite con` | factory production program; `infinite X` = repeat until countermanded |
| **reclaim zone directive** | `1st laz eats rocks near the 6 non-canyon bases` | reclaim_zone goal: zone = union of disc(startPos, r) for positions {1,2,3,5,6,7} (canyon = 4, 8 excluded — see metrics/maps/all-that-glitters.json positionRoles); route greedy nearest-rock |
| **checkpoint goal** | `first goal time: finish a T2 mex` | named checkpoint; everything before it is graded in lost-seconds against the projection (gex_research convention) |

## Compiled form (sketch)

```json
{
  "intentId": "7mex-25wind-fast-t2",
  "checkpoints": [{ "id": "t2mex_online", "goal": "g_t2mex", "metric": "lost_seconds" }],
  "goals": [
    { "id": "g_mex123",   "build": "mex",    "count": 3, "who": "com" },
    { "id": "g_solar12",  "build": "solar",  "count": 2, "who": "com", "after": "g_mex123" },
    { "id": "g_factory",  "build": "botlab", "who": "com", "after": "g_solar12" },
    { "id": "g_solar34",  "build": "solar",  "count": 2, "who": "com", "after": "g_factory" },
    { "id": "g_workers",  "factory": "botlab", "produce": ["con", "con"], "assist": "com" },
    { "id": "g_mex456",   "build": "mex", "countToTotal": 6,
      "who": ["com", "worker1", "worker2"], "parallel": true, "after": "g_workers" },
    { "id": "g_give",     "meta": "give_unit", "unit": "worker2", "to": "ally:air",
      "timer": { "type": "walk_arrival", "target": "ally_air.bottomLeftMex" }, "after": "g_mex456" },
    { "id": "g_mex7",     "build": "mex", "countToTotal": 7 },
    { "id": "g_wind25",   "build": "wind", "countToTarget": 25,
      "conditional": { "on": "wind", "lowWindSubstitute": "solar_equivalent_eps" } },
    { "id": "g_facqueue", "factory": "botlab",
      "produce": ["con", "laz", "con", "laz", { "repeat": "con" }], "after": "g_workers" },
    { "id": "g_lazrocks", "meta": "reclaim_zone", "unit": "laz1",
      "zone": { "map": "all_that_glitters", "positions": [1,2,3,5,6,7], "radiusElmos": 900 },
      "filter": "features:rocks" },
    { "id": "g_t2lab",    "build": "t2lab", "priority": "critical", "after": "g_wind25" },
    { "id": "g_t2mex",    "build": "t2mex", "after": "g_t2lab" }
  ]
}
```

## Stall annotation pass (planner output, per goal)

After compilation the planner projects the whole DAG through eco_engine and attaches:

```json
{ "goalId": "g_t2lab",
  "projectedStart": 412, "projectedEnd": 471,
  "stalls": [{ "resource": "metal", "atSec": 388, "durSec": 22, "lostSec": 14 }],
  "mitigations": [
    { "type": "pre_walk", "what": "send con toward T2 lab site at 360s — walk overlaps the stall, costs nothing",
      "recoversSec": 9 },
    { "type": "reclaim_pass", "what": "laz rock route passes flagged window — rocks near pos-2 base land ~120 metal at 380-400s",
      "recoversSec": 5 }
  ]
}
```

Mitigation preference order: pre-walk build power → re-order slack goals → bank
threshold → reclaim pass → accept and re-time (mark the expected slip so the live
adapter doesn't treat it as divergence).

## Why lost-seconds is the native unit

Same convention as gex_research's eco_advisor: every deviation, stall, or mitigation
is valued as seconds gained/lost toward the next checkpoint (here: T2 mex online).
This makes intents comparable: two different 7-mex openings are judged by projected
checkpoint time, and live execution is judged by actual-vs-projected checkpoint time.

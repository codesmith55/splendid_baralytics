# Intent: legion-pos6-eco-bp  (Legion pos6 eco — return-to-commander BP branch)

Legion commander, starting position 6 (tech/eco slot). Identical opening to
legion-pos6-eco-wind: 3 mex + 2 solar → factory → mex 4+5 + 3 solar → estor →
con turret.

**Branch: return-to-commander.** After worker 1 builds mex 6+7, it walks back to
the commander's location and assists the medmex build, adding ~80 BP to the pool.
No wind is built by worker 1 — the energy economy stays lower than the wind branch,
but the combined BP shortens the medmex build duration.

Worker 2 is unassigned in this intent.

**Position target:** first medmex (legmext15) online. Compared against
legion-pos6-eco-wind to answer: does wind energy (reduces stall) beat BP boost
(reduces base build time)?

**Projection caveat:** project.mjs serializes single-actor builds. The true medmex
in this branch is built by BOTH com and worker1 simultaneously — combined BP
300 + 200 (turret) + 80 (worker1) = 580 vs wind branch's 500. The projection here
uses com-only (500 BP) so it OVERESTIMATES medmex duration; use sample data for
the real comparison.

```intent
# Commander opening: 3 mex, 2 solar, factory (identical to wind branch)
build com: 3 leg_mex              id=g_mex123
build com: 2 solar                id=g_solar12    after=g_mex123
build com: leg_factory            id=g_factory    after=g_solar12

# Factory produces 2 workers (legck) then idles
produce leg_factory: leg_con, leg_con   id=g_workers    after=g_factory

# Commander continues: mex 4+5, 3 more solar
build com: 2 leg_mex              id=g_mex45      after=g_factory
build com: 3 solar                id=g_solar345   after=g_mex45

# Energy buffer + BP boost
build com: leg_estor              id=g_estor      after=g_solar345
build com: leg_turret             id=g_turret     after=g_estor

# First medmex — DECLARED FIRST so topoSort simulates it on the correct (solar-only)
# eco state. worker1 assist (+80 BP, reducing build from 500→580 BP) is NOT modeled
# here — use sample data for the real BP-branch timing.
build com: leg_medmex             id=g_medmex1    after=g_turret

# Worker 1: builds mex 6+7, then walks back (no wind — BP branch)
build worker1: 2 leg_mex          id=g_mex67      after=g_workers

checkpoint first_medmex: goal=g_medmex1 metric=lost_seconds
```

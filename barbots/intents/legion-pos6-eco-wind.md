# Intent: legion-pos6-eco-wind  (Legion pos6 eco — wind trickle branch)

Legion commander, starting position 6 (tech/eco slot). Opens with 3 mex + 2 solar
into a Legion bot factory (leglab). Commander then takes mexes 4+5 and 3 more solar
(total: 5 mex, 5 solar). Factory makes exactly 2 workers (legcks) then idles until
the first medmex completes.

**Branch: wind-in-place.** After the factory workers are out, worker 1 walks to the
mex-6 and mex-7 sites, builds both, then begins a trickle wind queue in place (separate
from the commander's main build queue). Commander takes the energy buffer path:
estor → con turret → first medmex.

Worker 2 is unassigned in this intent (available to the player for whatever is needed).

**Position target:** first medmex (legmext15) online. Used to benchmark the
wind-trickle branch against the return-to-commander branch (legion-pos6-eco-bp).

**Units:** all `leg_*` keys map to Legion unit costs from `legion_unitdefs.json`.
`leg_medmex` proxied as ARM mex in the income model (build timing is accurate;
metal income rate after completion is ~2.28 m/s not 1.8 m/s — calibrate via samples).

```intent
# Commander opening: 3 mex, 2 solar, factory
build com: 3 leg_mex              id=g_mex123
build com: 2 solar                id=g_solar12    after=g_mex123
build com: leg_factory            id=g_factory    after=g_solar12

# Factory produces 2 workers (legck) then idles until medmex done
produce leg_factory: leg_con, leg_con   id=g_workers    after=g_factory

# Commander continues: mex 4+5, then 3 more solar (5 total)
build com: 2 leg_mex              id=g_mex45      after=g_factory
build com: 3 solar                id=g_solar345   after=g_mex45

# Energy buffer + BP boost before medmex
build com: leg_estor              id=g_estor      after=g_solar345
build com: leg_turret             id=g_turret     after=g_estor

# First medmex — DECLARED FIRST so topoSort simulates it on the correct (solar-only)
# eco state, before advancing time through worker1's concurrent actions.
# In the real game, wind income arrives concurrently and reduces stall — this model
# is pessimistic for the wind branch (overestimates medmex time).
build com: leg_medmex             id=g_medmex1    after=g_turret

# Worker 1: builds mex 6+7, then trickle wind queue in place
build worker1: 2 leg_mex          id=g_mex67      after=g_workers
build worker1: wind to-target 6   id=g_wind       after=g_mex67

checkpoint first_medmex: goal=g_medmex1 metric=lost_seconds
```

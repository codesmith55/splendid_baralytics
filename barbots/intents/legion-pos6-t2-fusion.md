# Intent: legion-pos6-t2-fusion  (Legion pos6 — full line to T2 fusion)

Extends the proven `legion-pos6-eco-bp` opening (the ENVIRONMENT: 5 mex + 5 solar +
factory) into the full T2-fusion line.

**Build order (the specific line, not a sweep):**
- Environment: 3 mex → 2 solar → factory → 2 mex → 3 solar (5 mex, 5 solar).
- Factory makes **3 workers (legck); 1 is given to air** after it builds a medmex.
  Worker 1 takes mexes 6+7 (→ 7 mex). Net effective workers = 2.
- Build power: **con turrets as needed** (each legnanotc = +200 BP).
- Battery: **solars + estorages** — built from would-be-overflow metal; banked energy +
  parked metal, later reclaimed into the fusion.
- T2 chain: **T2 factory (legalab) → T2 con (legack) → fusion (legfus)**.

**Reclaim caveat:** reclaiming your own solars/estor INTO the fusion (≈+2210m, which
nearly halves its 4000m) is the mechanic that breaks the fusion's metal gate. The intent
DSL only models map-feature `reclaim_zone`, not own-structure reclaim — so the projected
fusion stall below is the *no-reclaim* (pessimistic) case. That reclaim leg is the one
piece of logic still to add to the planner.

```intent
# ENVIRONMENT — proven Legion pos6 opening: 5 mex, 5 solar, factory
build com: 3 leg_mex              id=g_mex123
build com: 2 solar                id=g_solar12    after=g_mex123
build com: leg_factory            id=g_factory    after=g_solar12
build com: 2 leg_mex              id=g_mex45      after=g_factory
build com: 3 solar                id=g_solar345   after=g_mex45

# 3 workers; worker2 builds a medmex then is given to air. worker1 takes mex 6+7 (-> 7 mex)
produce leg_factory: leg_con, leg_con, leg_con   id=g_workers    after=g_factory
build worker1: 2 leg_mex          id=g_mex67      after=g_workers
build worker2: leg_medmex         id=g_medmex     after=g_workers
meta give_unit leg_con: to=ally:air               id=g_giveair    after=g_medmex

# Build power: con turrets as needed (+200 BP each)
build com: leg_turret             id=g_turret1    after=g_solar345
build com: leg_turret             id=g_turret2    after=g_turret1

# Battery: solars + estorages (metal+energy bank, reclaimed into the fusion)
build com: 4 solar                id=g_battery_s  after=g_turret2
build com: 2 leg_estor            id=g_battery_e  after=g_battery_s

# T2 chain: factory -> con -> fusion
build com: leg_t2factory          id=g_t2fac      after=g_battery_e
produce leg_t2factory: leg_t2con  id=g_t2con      after=g_t2fac
build com: leg_fusion             id=g_fusion     after=g_t2con

checkpoint fusion_online: goal=g_fusion metric=lost_seconds
```

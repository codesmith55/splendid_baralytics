# Intent: 7mex-25wind-fast-t2  (reference intent — drives the language spec)

Execute a 3 mex 2 solar factory 2 solar into com rushing 2 workers, into all 3
builders taking a 6th mex, giving away one of the workers to our air player
(meta action — timer: give early enough that the con's walk ends as it can start
building air's bottom-left mex). From there taking 7 mex, getting to about 25 wind
based on current wind conditions, and go for a fast T2 factory.

T1 factory queue: 3 con, laz, con, laz, infinite con.
1st laz eats available rocks in the general area of the 6 non-canyon players'
starting bases (ATG positions 1,2,3,5,6,7 — canyon roles 4 and 8 excluded).

**First goal time: finish a T2 mex.**

Compiled DAG: the prose above is for humans. The machine-readable build is the
fenced `intent` block below — `planner/parse-intent.mjs` compiles it into the goal
DAG (target shape: the hand-compiled sketch in docs/intent-language.md). Grammar:
docs/intent-grammar.md.

```intent
# 3 mex, 2 solar, factory, 2 solar — commander chain
build com: 3 mex                  id=g_mex123
build com: 2 solar                id=g_solar12  after=g_mex123
build com: botlab                 id=g_factory  after=g_solar12
build com: 2 solar                id=g_solar34  after=g_factory

# com rushes 2 workers out of the botlab (com assists)
produce botlab: con, con          id=g_workers  assist=com

# all 3 builders take mexes up to a shared total of 6
build [com,worker1,worker2]: mex to-total 6 parallel   id=g_mex456  after=g_workers

# meta: give worker2 to the air ally, timed so its walk ends as it can start
# building air's bottom-left mex
meta give_unit worker2: to=ally:air timer=walk_arrival:ally_air.bottomLeftMex  id=g_give  after=g_mex456

# expand to 7 mex, then ~25 wind (substitute solar-equivalent e/s if wind reads low)
build: mex to-total 7             id=g_mex7
build: wind to-target 25 conditional=wind:solar_equivalent_eps   id=g_wind25

# T1 factory production program; `*con` = repeat con until countermanded
produce botlab: con, laz, con, laz, *con   id=g_facqueue  after=g_workers

# 1st laz eats rocks near the 6 non-canyon ATG bases (canyon roles 4,8 excluded)
meta reclaim_zone laz1: zone=all_that_glitters:[1,2,3,5,6,7]@900 filter=features:rocks  id=g_lazrocks

# fast T2: lab on the critical path, then the first T2 mex (the checkpoint)
build: t2lab priority=critical    id=g_t2lab  after=g_wind25
build: t2mex                      id=g_t2mex  after=g_t2lab

checkpoint t2mex_online: goal=g_t2mex metric=lost_seconds
```

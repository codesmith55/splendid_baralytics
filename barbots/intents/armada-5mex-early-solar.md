# Intent: armada-5mex-early-solar (Armada 5-mex opener, solar after mex 3 and mex 5)

Armada commander opening, opening-only scope. Same 5-mex shape as the Legion
pos6 openers, but as Armada (`mex`/`solar`/`botlab` — ARM's `mex` is
energy-**negative**, -3 e/s upkeep, unlike Legion's energy-positive mex, so
energy support comes earlier): 3 mex, 1 solar, 2 more mex (5 total), 1 more
solar, then the bot lab. Matches the player's own 1v0 practice pattern
(3mex → sol → 2mex → sol → factory).

**Position target:** bot lab (`botlab`) online. Opening only — no factory
production, no T2/fusion line in this intent.

```intent
# 3 mex, 1 solar (inserted right after the 3rd mex)
build com: 3 mex                  id=g_mex123
build com: 1 solar                id=g_solar1     after=g_mex123

# 2 more mex (5 total), 1 more solar
build com: 2 mex                  id=g_mex45      after=g_solar1
build com: 1 solar                id=g_solar2     after=g_mex45

# Bot lab
build com: botlab                 id=g_botlab     after=g_solar2

checkpoint botlab_online: goal=g_botlab metric=lost_seconds
```

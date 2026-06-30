---
build: first-unit-rush
status: analysis
question: does skipping mexes/solar to rush the first unit out beat an eco-first opening
checkpoint: shared (vs eco-first baseline)
gate: energy (skip-solar only survives an energy-light follow-up)
needs: [laz-reclaim-rate, laz-energy-upkeep, rock-field-metal, raider-stats, compound-factor]
sources: [planner/data/units.json]
---

# Build: BP-skip / first-unit-out rush

> Skip most mexes and skip-or-delay solar to stand the factory up at a lower metal+energy
> count, betting that **the first unit out the door** pays back the eco deficit faster
> than a conventional eco-first opening reaches the same checkpoint.

Shared model and currency: [README.md](README.md).

## The reframe

By the [three clocks](README.md#the-shared-model-the-three-clocks), the commander is
already build-power-saturated against a small eco. So "rush to higher build power" is the
wrong lens for the opening — you can't feed the BP you already have. What this build
actually rushes is **the moment the factory produces its first unit**, bought by spending
less metal and energy on infrastructure first.

The constraint that binds it is **energy**, not metal: skipping solar leaves every
energy-hungry build (mexes are 500 e each, the factory 1200 e) running on the slow energy
clock. So **skip-solar only survives on an energy-light follow-up.** That single fact
sorts the three things the first unit could be.

## Case A — Lazarus eats rocks (coheres with skip-solar)

Reclaim produces *metal* and costs almost no energy to run, so a Lazarus eating rocks is
an energy-light way to bootstrap metal straight off the map. "Skip mexes + skip solar +
rush Laz" is internally consistent: the whole package dodges every energy-hungry step.

Income bump: `+R_laz` M/s for `F / R_laz` seconds, where `F` = reclaimable metal in the
zone and `R_laz` = Laz reclaim rate. Net value, in metal-equivalent:

```
ΔV_laz = F_captured·(1 + compound) + p_contest·F_denied
         − [ C_laz + factory_premium + deficit(skipped mex/solar) ]
```

- **front-loaded** metal is worth its later self plus the income it could seed (the
  `compound` term).
- rocks are a **shared, finite** pool, so `p_contest·F_denied` (metal the opponent now
  can't take) is real value, not a bonus.

**Wins when nearby `F` is large, close, and contested** — exactly the position-gated
`reclaim_zone` in the reference intent
([`intents/7mex-25wind-fast-t2.md`](../../intents/7mex-25wind-fast-t2.md): the laz eats
rocks near the 6 non-canyon bases). This is the strongest version of the concept.

## Case B — aggression unit (a bet on the opponent, not the map)

Value = enemy metal destroyed + **denied enemy income** (compounding) + tempo (forcing
defensive spend). Opportunity cost = your own skipped eco (compounding).

Because you flatten *their* eco curve while denting yours only once, even a small
permanent slope reduction on the enemy out-compounds your unit's cost — **when they are
eco-ahead / army-light.** That is precisely the military-vs-eco dial in
[scouting-economy-estimation.md](../scouting-economy-estimation.md), so this case is the
same math read from the other side of the fog.

## Case C — workers (the uncertain one — and the math says be uncertain)

Two reasons it rarely behaves like the others:

1. **Energy-heavy, so it fights skip-solar.** Cons are ~1100 e each, and they then build
   500-e mexes. Rushing cons with no solar energy-stalls. Workers belong *with* solar —
   they are the eco-*scaling* path, not the skip-eco *rush* path: same clothing, different
   strategy.
2. **Parallelism rarely beats the commander on a small mex count.** The com takes a mex
   serially in ≈ `walk/37.5 + 6 s`; a con takes one in ≈ `walk/36 + 22.5 s` (BP 80). To
   take `K` more mexes, the worker path only wins once
   `(K / n_con)·22.5 + factory+con overhead < K·6` — roughly **4+ cons** before parallel
   grabbing beats the com's high-BP serial grab. For "a 6th and 7th mex," the com is
   usually faster alone.

The real value of cons is doing a **second task** while the com builds — not winning a
mex-count race.

## Planner framing

This is a build **comparator**, not one build: generate candidates (eco-first baseline /
Laz-rush / raid-rush), project each through the eco_engine, and grade them in lost-seconds
to a shared checkpoint plus the value terms above. The math the comparator needs is the
projection bridge (next dev task) plus these value functions.

## Values still needed

- `R_laz` (reclaim rate) and the Laz's **energy upkeep** — from `units/armlaz.lua` (the
  `_PROVISIONAL` laz entry in `units.json`).
- reclaimable `F` and walk distance in a zone — from the **live reader's rock-feature
  emit** (not built).
- raider unit stats (cost, dps, speed) for Case B.
- the shared compound-weighting factor (see [README.md](README.md#currency-lost-seconds)).

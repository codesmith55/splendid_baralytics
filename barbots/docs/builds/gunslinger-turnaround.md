---
build: gunslinger-turnaround
status: analysis
question: as a front player, turnaround time to 1-2 gunslingers on the field
checkpoint: 1-2 gunslingers on field
gate: build-power
needs: [consul-stats, gunslinger-buildwork, front-nano-bp, reclaim-yield]
patch: { gunslinger: { metal: [650, 520], energy: [11000, 6500] } }
sources: [planner/data/units.json]
---

# Build: Gunslinger turnaround (factory-as-battery)

> As a **front player**, from the eco you already have plus some reclaimable T1 labs: how
> fast can you reach **1–2 Gunslingers on the field** (the stabilization point)?

Shared model and currency: [README.md](README.md).

## Patch context

This build is sized to a community patch — **often played, not universal** — that cuts
the Gunslinger's cost:

| Gunslinger | metal | energy |
|---|---|---|
| base | 650 | 11 000 |
| **patched** | **520** | **6500** |

The −4500 energy is the whole reason the build closes for a front player (see finding 2).
All math below uses the **patched** numbers.

## Constraint: front build power only

A front player cannot pull backline build power. The build power `B` for this maneuver is
the sum of **front** sources only: front commander(s), front con turrets (nanos), front
workers, and the Consul once it exists. Front income `M_f` / `E_f` is likewise the
front's own — no backline energy to lean on.

## The maneuver as an economic machine

The T2 lab is not infrastructure here, it's a **one-shot dispenser**: pay metal to stand
it up, extract exactly one mobile T2 builder (Consul), then **liquidate the lab to recover
its metal**, and let the Consul keep producing Gunslingers. Five phases, each a lump of
build-work paid out of `B` plus a metal/energy ledger entry:

| # | phase | build-work | metal | energy |
|---|---|---|---|---|
| 0 | reclaim `L` T1 labs | `L·6500` | **+`L·620`** | (return uncertain — ignore) |
| 1 | build T2 lab | `16000` | −720 | −1700 |
| 2 | pop 1 Consul | `W_consul` | −`m_c` | −`e_c` |
| 3 | reclaim ("sell") T2 lab | `16000` | **+720** | — |
| 4 | Consul builds `n` Gunslingers | `n·W_gun` | −`n·520` | −`n·6500` |

(T1 lab 620 m / 6500 w and T2 lab 720 m / 1700 e / 16000 w from
[`units.json`](../../planner/data/units.json); the T2 lab entry is `_PROVISIONAL`.)

## The three clocks, applied

```
T_bp(n)   = [ L·6500 + 16000 + W_consul + 16000 + n·W_gun ] / B      (pooled front BP)
M_out(n)  = 720 + m_c + n·520        M_in(n) = M_f·T + L·620 + 720
E_out(n)  = 1700 + e_c + n·6500      E_in(n) = E_f·T  (+ banks)
T_turn(n) = max( T_bp , E_out/E_f , metal-stall if M_out > M_in )
```

### Worked example (placeholders flagged)

Front player with `M_f = 25`, `E_f = 250`, `L = 2` labs, `B = 860` (com 300 + 2 nanos
≈400 + 2 cons 160), and **placeholder** `W_consul = 8000, m_c = 180, e_c = 2600,
W_gun = 9000`:

| target | BP-work / B | energy out vs supplied | **gate** |
|---|---|---|---|
| 1 Gunslinger | 62 000 / 860 = **72 s** | 10 800 vs 18 000 | BP-bound |
| 2 Gunslingers (patched 6500) | 71 000 / 860 = **83 s** | 17 300 vs 20 600 | **BP-bound** (3.3k headroom) |
| 2 Gunslingers (base 11 000) | 83 s of BP | 26 300 vs 20 600 | **energy-stalls ~23 s** |

## Findings

1. **It is build-power-bound, not metal-bound — the reclaim chain is what makes it
   cheap.** Reclaiming 2 T1 labs (+1240) and selling the T2 lab (+720) returns ~1960
   metal, which over-funds the whole spend (720 + 180 + 520 = 1420 to the first
   Gunslinger). Metal is never the wall once you reclaim, so **turnaround scales linearly
   with front BP** — every front nano/con pointed at it shaves `T_bp`. That is the lever.

2. **The patch flips the gate exactly at the stabilization point.** Base cost (11 000 e),
   a front-only eco cannot supply the 2nd Gunslinger's energy — it stalls ~23 s on energy
   it can't pull from the backline. Patched (6500 e), the 2-Gunslinger target fits under
   the BP clock with headroom. That −4500 energy is what turns "1 Gunslinger then stall"
   into "1–2 Gunslingers, stable" on front income alone — and why the build is played
   under the patch and not otherwise.

3. **The "metal storage" worry mostly dissolves.** Selling the T2 lab dumps 720 metal over
   its reclaim time (16000 / `B` ≈ 18.6 s → ~38.7 M/s). Gunslinger spend is ~520 over its
   build (`W_gun` / `B` ≈ 10.5 s → ~49.5 M/s). **Spend rate > reclaim rate, so no
   overflow** if you reclaim *while* the Consul builds — storage is only needed if you
   reclaim faster than you spend. Overflow condition:
   `720 / (16000 / B_reclaim) > M_f + Gunslinger_spend_rate`.

## Values still needed

- **Consul** — cost, `buildWork`, build power, and confirm it is a *mobile* T2 builder
  that can build the Gunslinger (the entire liquidation trick depends on it being
  mobile). From its unit def.
- **Gunslinger `buildWork`** — the patched 520 m / 6500 e are known; the build time
  (`W_gun`) is not, and it dominates phase 4.
- **front nano turret BP** and a realistic front count — the main term of the BP-bound
  turnaround.
- **reclaim yield** — confirm own-building reclaim returns ~100% metal and whether any
  energy comes back (assumed metal-only here).

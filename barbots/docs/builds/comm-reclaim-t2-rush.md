---
build: comm-reclaim-t2-rush
status: idea
question: does reclaiming the commander + T1 lab to stand up a permanent T2 factory + T2 con + metal storage beat a conventional transition, to field a Gunslinger or T2 long-range static defense ("Persecutor")
checkpoint: T2 factory + T2 con + metal storage standing, first Gunslinger or Persecutor queued
gate: unresolved — likely a RULES gate (commander death), not an economic one; see Findings #1
needs: [commander-cost, commander-reclaim-legality, arm-t2con-stats, arm-metalstorage-cost, persecutor-identity-and-cost, gunslinger-buildwork]
patch: { gunslinger: { metal: [650, 520], energy: [11000, 6500] } }   # inherited from gunslinger-turnaround.md
sources: [planner/data/units.json, docs/builds/gunslinger-turnaround.md]
---

# Build: Commander-reclaim T2 rush (standing factory, not liquidated)

> Reclaim the T1 lab **and the commander itself**, then stand up a **permanent** T2 lab +
> T2 con + metal storage (not sold, unlike gunslinger-turnaround), to sustain a Gunslinger
> or T2 long-range static defense ("Persecutor") rush rather than a one-shot pop.

Shared model and currency: [README.md](README.md). Sibling build:
[gunslinger-turnaround.md](gunslinger-turnaround.md) — same reclaim-funds-T2 trick, two
structural differences called out below.

## Before any economics: the commander-reclaim question

**Reclaiming (or otherwise destroying) your own commander is normally a loss condition in
BAR** — commander death eliminates that player from the game. This build cannot be scored
until it's confirmed whether the intended context is:
- a **team game**, where the player accepts elimination / hands off to a teammate as a
  deliberate sacrifice, or
- a **specific mode/ruleset** where commander loss doesn't end the game, or
- something else entirely (e.g. "reclaim" here means something other than reclaiming the
  literal commander unit — worth double-checking the intent).

This is listed first, ahead of every number below, because it is a **rules gate**, not an
economic one — if it isn't viable, none of the metal/energy math matters.

## The reframe / the maneuver

Same liquidation trick as gunslinger-turnaround (T1 lab reclaim funds a T2 lab, which pops
a mobile T2 con), with two changes:

1. **The commander is also reclaimed**, adding a much larger one-time metal lump on top of
   the T1 lab's 620m. Reclaiming requires an *existing* builder to do the reclaiming (the
   commander can't reclaim itself). The 300 BP it was providing is **not a permanent
   loss** — BP is metal-purchasable (con turret 230m→200 BP = 0.87 BP/m; con bot
   110m→80 BP = 0.73 BP/m), both far more metal-efficient than the commander's own
   ~0.11 BP/m (300 BP for ~2700m, using the Legion cross-reference). The reclaimed lump
   itself covers rebuying MORE BP than was lost — e.g. 1200m → 5 turrets (1150m) = 1000
   BP, over 3x the 300 lost — spent whenever BP/energy allow it. The real question isn't
   "BP recovers or not," it's **timing**: how long between the commander's death and
   enough BP being rebought to keep the T2 lab/con/storage phases moving at pace.
2. **The T2 lab is kept, not sold.** Gunslinger-turnaround liquidates the T2 lab for +720m
   after popping one Consul (a single-shot maneuver). This build instead funds the T2 lab
   *and* a metal storage as standing infrastructure — the right call only if the goal is
   sustained T2 production, not a one-time pop-and-sell.

## Phases / ledger

| # | phase | build-work | metal | energy |
|---|---|---|---|---|
| 0 | reclaim T1 lab (`botlab`) | 6500 | **+620** | (uncertain — ignored, same convention as gunslinger-turnaround) |
| 0b | reclaim commander | `w_com` (**unknown** — commander's own buildWork/BP) | **+`m_com`** (**unknown**) | ? |
| 0c | *(structural)* | — | 300 BP lost, but re-buyable from this phase's own metal: turret 230m→200BP (0.87 BP/m) beats the commander's own ~0.11 BP/m — **timing gap, not a permanent loss** | — |
| 1 | build T2 lab | 16000 | −720 | −1700 |
| 2 | pop 1 T2 con | `W_con` (**unknown**) | −`m_c` (**unknown**) | −`e_c` (**unknown**) |
| 3 | build metal storage | `W_ms` (**unknown**) | −`m_ms` (**unknown**) | −`e_ms` (**unknown**) |
| 4a | Gunslinger ×n | `n·W_gun` (**unknown**) | −`n·520` (patched) | −`n·6500` (patched) |
| 4b | *or* Persecutor ×n | fully unknown | fully unknown | fully unknown |

(T1 lab 620m/6500w and T2 lab 720m/1700e/16000w from
[`units.json`](../../planner/data/units.json) — T2 lab entry is `_PROVISIONAL`, and both
were sourced for the **Legion** T1/T2 lab in earlier work this session; ARM/COR equivalents
are assumed close per BAR's faction-symmetric economy tier, not independently confirmed.)

## The three clocks, applied

```
B(t)      = front-only builders alive at time t — drops to just the reclaiming con(s) the
            instant phase 0b completes, then climbs back as m_com gets spent on turrets/con
            bots (230m→200BP each) — a re-buy TIME gap, not a permanent BP ceiling
T_bp(n)   = [ w_com + 16000 + W_con + W_ms + n·W_gun ] / B(t)     (B changes mid-build — see above)
M_out(n)  = 720 + m_c + m_ms + n·520 + BP_rebuy_cost   M_in(n) = M_f·T + 620 + m_com
E_out(n)  = 1700 + e_c + e_ms + n·6500 + BP_rebuy_energy   E_in(n) = E_f·T  (+ banks)
T(n)      = max( T_bp , E_out/E_f , metal-stall if M_out > M_in )
```

No worked example yet — `m_com`, `W_con`, `m_c`, `e_c`, `W_ms`, `m_ms`, `e_ms`, and the
Persecutor's entire cost line are all unresolved (see Values still needed). Plugging in
placeholder numbers here would violate this doc-system's honesty rule; gunslinger-turnaround
at least has patched Gunslinger costs and a placeholder Consul to work with — this build
doesn't yet.

## Findings

1. **The gate is a rules question, not an economic one.** Until commander-reclaim is
   confirmed non-eliminating in the intended context, every clock below is moot — this
   is the opposite of gunslinger-turnaround, where the T1-lab reclaim is uncontroversially
   legal and the whole analysis is economic from the start.
2. **The commander lump isn't free — it costs 300 BP permanently.** Gunslinger-turnaround
   keeps the commander alive the whole time (front BP `B` explicitly includes "front
   commander(s)"). This build trades that ongoing 300 BP for a one-time metal spike, so
   `T_bp` for every phase *after* the reclaim runs on whatever con/turret BP is left —
   likely far slower than gunslinger-turnaround's 72-83s worked example, which had 860 BP
   throughout.
3. **Keeping vs. selling the T2 lab is the other real fork.** Selling it (gunslinger-
   turnaround) returns +720m once and ends with a mobile Consul as the only builder.
   Keeping it (this build) forgoes that +720m but keeps 100+ BP of standing factory
   capacity and lets the metal storage actually matter (gunslinger-turnaround finding #3
   shows overflow is a non-issue *only when the lab is being sold off during the pop* —
   with the lab kept, that headroom argument doesn't automatically carry over and needs
   its own check once `M_in`/`M_out` are known).
4. **Persecutor cannot be evaluated at all yet.** It doesn't match any `name`/`tooltip` in
   `legion_unitdefs.json`'s 252 defs (which does include Legion's own long-range T2 statics
   and the base ARM/COR/Legion economy buildings) — it isn't in this repo's data under that
   name. Needs a defName or a screenshot/tooltip before it can be costed at all.

## Values still needed

- **Commander-reclaim legality** in the intended game mode/context (see the section above)
  — this is the load-bearing unknown, not a "nice to have."
- **Commander cost + reclaim yield** (`m_com`) — ARM/COR `armcom`/`corcom` aren't in
  `units.json` or `legion_unitdefs.json`. (Legion's own commander is 2700m/26000e per that
  file, if useful as a rough cross-faction reference point — not a substitute for the real
  ARM/COR number.)
- **ARM/COR T2 con bot** ("Consul"-equivalent) cost/buildWork/BP — same open item
  gunslinger-turnaround still has for the Cortex Consul; ARM's own T2 con isn't in
  `units.json` either.
- **ARM/COR metal storage** cost/buildWork/energy — not in `units.json`. (Legion's
  `legamstor` is 760m/11000e/10000 storage/20500 buildWork if a same-tier reference helps.)
- **Persecutor** — identity (defName, faction) and full cost line. Not found under that
  name anywhere in this repo's captured unit data.
- **Gunslinger buildWork** — same unresolved item as gunslinger-turnaround.md.

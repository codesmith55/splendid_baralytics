# Long-T1 conversion vs fast-T2 mex — the SL4rk archetype

Conceptual comparison of two tech-role styles, grounded in game-1786039527
(All That Glitters 8v8, 25 min, spectated 2026-08-06). Archetype named for
SL4rk's line but general: **stay on T1 economy longer, oversize wind + T1
energy conversion, arrive at T2 slightly later but land on a pre-built energy
platform** — vs — **rush the T2 lab to unlock moho (the better scaler) as
early as possible on a thin T1 base**.

(Ignore the 4×advsolar in SL4rk's actual opening — judged junk; 1–2 sprinkled
in for stall security is the sane version. The archetype is wind + makers.)

## The archetype, empirically (SL4rk, back-mid tech role)

Opening (first 8 min): **43 armwin, 16 armmakr**, 7 mex (his lane spots — never
expands past them all game), armalab started **5:00** (enemy team's first T2:
4:24 — "a bit late"). From minute 4 he is #1 energy income of all 16 players
and virtually never gives it up. Converter count: 0 → 16 (min 6) → 42 (min 15)
→ 87 (min 25, T2 converters snowballing). End state: 15.2k E/s, 260 m/s from
just 7 extraction spots.

## Cumulative metal race vs the fast-mex scalers (13-spot expanders)

| | SL4rk (7 spots + conversion) | matejtanemarad0 (13 mex) | [MADO]DrSen (13 mex) |
|---|---|---|---|
| max deficit | — | **−7.2k** metal (~min 15) | **−4.9k** metal (~min 14) |
| permanent crossover | — | **min 17** | **min 19** |
| cumulative @25 | **126.9k** | 90.3k | 97.2k |
| e_inc @ crossover | 4.5–6.9k | 2.6k | 2.4k |

Shape of the race: SL4rk's mex-first open actually leads minutes 1–4; the
expanders out-produce him minutes ~5–16 (the deficit window); his conversion
snowball then crosses permanently and finishes +30–37k ahead. **The deficit
window (minutes ~5–16, worth ~5–7k metal) is the fast player's whole
advantage — it must be spent as pressure before the crossover or it never
existed.**

## Why the math works (real def costs from the stream)

- `armmakr`: **1 metal** + 1150 energy to build; converts 70 E/s → 1 m/s.
  Conversion capacity is bought almost entirely WITH ENERGY.
- `armwin`: 40 metal, ~13.5 E/s on this map → feeding one maker ≈ 5.2 winds.
- **Marginal +1 m/s via conversion ≈ 210 metal** (5.2 winds + 1 maker),
  unbounded — scales with energy forever, no map slots required.
- **Marginal +1 m/s via moho ≈ ~95 metal** (620 − 50 reclaim, ÷ ~+6 m/s over
  T1 mex) — ~2.2× more metal-efficient, **but** gated behind a 2600-metal
  armalab, buildable only on finite map spots, and adds energy upkeep.

So: mohos are the better scaler per metal; conversion is the only *unbounded*
scaler and its currency (energy) is what the long-T1 player has oversized
anyway. The styles differ in what they buy with the early game:

| | Long-T1 conversion | Fast-T2 mex |
|---|---|---|
| early metal | higher during T1 (makers from ~min 5) | lower until mohos online |
| T2 arrival | later (~30–60 s here) | earlier |
| stability | **implicit**: oversized energy = stall-immune, weathers wind lulls, absorbs moho/T2-conv upkeep instantly | thin energy; a stall or lab loss is a disaster |
| T2 transition | **instant** — energy platform pre-built, all spots upgrade at once, T2 converters chain immediately | staged — each moho must also fund its energy |
| scaling ceiling | unbounded (energy → metal) | capped by map spots, then must add conversion anyway |
| exposure | deficit window ~min 5–16: must not die while behind | must convert the lead into damage before crossover |

## Verdict / when each wins

- Fast-T2 wins **if the game is decided before the crossover** (~min 17–19
  here) or if the long-T1 player's lane can be punished during the deficit.
- Long-T1 conversion wins **any game that goes long** and degrades gracefully:
  "a bit late, but always strong" is literal — he arrives at T2 with 3–5× the
  energy of the fast-tech player, so his T2 *output* overtakes almost
  immediately even though his T2 *timing* trailed.
- The break-even is observable live: watch cumulative-metal curves
  (`series`/`flow_series`) — the fast player's clock is the crossover minute.

## Caveats

- matej's min-13 income spike (174 m/s) is a reclaim windfall, inflating his
  curve — the true crossover is if anything earlier than min 17.
- Cumulative metalIncome includes conversion output natively (BAR counts maker
  output as income), so the curves are directly comparable.
- The comparison players are fast *expanders*; a purer fast-T2-moho archetype
  (7 spots, rushed lab) would show the same shape with a smaller deficit
  window and a lower ceiling.

## ROI model: wind count vs T2-con timing (2026-08-06)

**The conversion block (exact)**: 6 × (40 m wind + 175 E) + 1 × (1 m + 1150 E
converter) = **241 metal + 2,200 energy → +1 m/s**. The 6:1 wind:converter
ratio budgets ~11.7 E/s per wind (headroom under average wind). The 2,200 E
build cost is self-amortizing (~31 s of the block's own 70 E/s draw) but is
why the line needs existing energy/estor to start rolling. Canon rates:
wind+T1conv **+1 m/s per ~241–250 metal**; T2-converter economy
**+1 m/s per 133**; own-spot mohos ~**+1 m/s per 95** (finite, 7 spots). The
T2 gate (lab 2600 + estor + con) earns nothing until the **T2 con finishes**
(factory start irrelevant; critical path = lab finish → con finish → mex
finish). Compounding doubling time at 1/250 = **2.9 min**; at 1/133 =
**1.5 min** — that gap is the whole argument.

BP-capped sim (8 s/wind wall; lab 90 s + con 45 s + moho 40 s), calibrated to
the empirical anchor "25–30 winds + estor → ~6:00–6:30 first T2mex":

| winds before gate | first T2mex | inc @8:00 | inc @12:00 |
|---|---|---|---|
| 20 | 6:38 | 178 | 1073 |
| **27** | **6:51** | 169 | 1019 |
| 35 | 7:55 | 126 | 760 |
| 45 | 9:15 | 34 | 511 |
| 54 | 10:27 | 36 | 350 |
| 65 | 11:55 | 37 | 216 |

**Mode note:** armmoho (T2 mex) IS available in this mode; what does NOT
exist is the **medium mex** (the T1.5 in-place upgrade the Legion eco model
carries as `leg_medmex`). So the model above stands as written — gate →
95-rate moho pool on own spots → 133-rate T2 cons — and any analysis of this
mode using `positions/state_api.py` should exclude the `leg_medmex` action
(and its `MOHO_NET_FROM_MED` reclaim path; T1→moho only).

**Sensitivity (gate value without the moho pool):** re-running with
`MOHO_POOL=0` changes nothing structurally — min-wind still re-passes
double-wind at 6:30, the sweep keeps its shape (~15–20 % lower absolute
incomes). The gate's opportunity cost (3,225 metal = +13.4 m/s at the
241-rate) is repaid by the 241→133 rate advantage alone after ~4,000 metal of
post-gate flow — about **2 minutes** at a 30 m/s surplus. The moho pool makes
the gate better still; it is not what makes it correct.

**Sequential double-wind (winds INSTEAD of gate progress) is strictly
dominated.** Its maximum lead is ~180 metal at 6:00; the min-wind line
re-passes it on both income and cumulative metal ~30 s after its first moho,
and is 2–3× ahead by minute 12. 20–27 winds are within seconds of each other
(the flat sweet spot — the minimum is set by the energy the T2 build itself
needs, lab + moho 8.1k E + con upkeep, which is why the floor exists at all);
every wind past ~35 costs about a minute of the 1/95–1/133 era.

**Reconciling with SL4rk making double-wind work:** he does not run the
sequential version. His lab lands ON TIME (5:00) and the wind/maker overshoot
is built in PARALLEL afterward — financed mostly in energy (makers cost
~1 metal) and spare BP, competing only weakly with gate metal. What he delays
is T2 *spending* (mohos ~min 12), not T2 *access* — a much softer penalty,
paid back because his oversized energy lets the 1/133 era saturate instantly
when it starts. The archetype's correct form is therefore:
**min-wind → gate on schedule → THEN overshoot wind+conversion in parallel**,
never winds-before-gate.

Rule of thumb at the margin: pre-gate, a 50-metal wind delays the 1/133 era
by ~50/S seconds (S = invested m/s) and the BP wall makes it worse — skip it;
post-gate, winds bought with spare BP and maker-energy are nearly free upside.

## Overshoot sweep on the eco simulator (2026-08-07)

Ran on `positions/state_api.py` (real banking/build-wall mechanics) with
injected mode actions: `conv_block` (241 m, +1 m/s), `nano` (120 m, +200 BP),
`t2_gate` (3,225 m, earns nothing, bw 47k), native `upgrade_t1_moho` ×7,
`adv_conv` (370 m, +2.78 m/s = 1/133). No medmex. Shared deviation state:
t=5:00, 7 mex, m_inc 27, **bp 350**, 27-wind platform. Line W spends W metal
on blocks+nanos first, then gate → 7 mohos → adv_conv forever.

| overshoot | +BP | gate done | ALL mohos | inc@20 | cum@20 | vs W=0 @20:00 |
|---|---|---|---|---|---|---|
| 0 (straight T2) | 0 | 9:10 | 13:52 | 82 | 47.1k | — |
| 500 | 200 | 8:37 | **11:37** | 90 | 54.9k | +7.8k |
| 1500 | 400 | 9:24 | 11:47 | 94 | 56.8k | +9.6k |
| 2000 | 600 | 9:27 | 11:44 | 95 | 57.7k | +10.6k |
| 3000 | 1000 | 9:50 | 12:07 | 95 | 58.3k | +11.2k |

**The expected "fast-T2 overtakes when its T2 mexes kick in" window never
opens** — at no point through 20:00 does any overshoot line fall behind on
cumulative metal, in any of three framings: vs the naive baseline, vs a fair
baseline buying nanos post-gate (all-mohos 11:45, still −4.5k vs
overshoot-1500), and vs a BP-rich deviation state (bp 800: margins shrink to
+1.6k…+5.9k, baseline finishes mohos first by only 10–36 s, still never
ahead). Two mechanisms close the window:

1. **Block income starts instantly** — a 241-m block bought at 5:00 has
   returned ~180 m before the straight-T2 line's mohos even come online; the
   moho-era income edge has a cushion to erode and only seconds-to-a-minute
   of completion lead to erode it with.
2. **At 350 BP the transition is BP-bound, not metal-bound** — "the point you
   could go T2" is when you can PAY for it, not when you can BUILD it.
   Straight-T2's 7 mohos take ~6.8 min at 350 BP; overshoot's nanos compress
   gate walls 250 s → 69–135 s and land ALL mohos 2+ minutes EARLIER despite
   starting later. Deliberately delaying T2 makes T2 finish sooner.

Sweet spot ~500–2,000 overshoot (nano-inclusive — the 250-m no-nano row barely
wins at +1.1k: **the BP is the active ingredient**, wind+conversion is the
financing). Diminishing beyond 2,000.

**Caveats:** eco-vacuum model — no enemy pressure (the true cost of a late
T2 is military exposure and map control, not cumulative metal); baseline
income held flat while banking (a mixed baseline trickling blocks would
narrow, not flip, the margins); energy assumed sufficient.

## Follow-ups

- state_api/navigator have no `t1_converter` action — adding one (≈210 M per
  +1 m/s marginal incl. wind, unbounded, energy-gated) would let
  `compare_t2_entry` simulate this archetype directly against `wind_med`
  and moho lines.
- player_db: tag candidates — `conversion_teching` (conv count high while mex
  count static) as the style signature.

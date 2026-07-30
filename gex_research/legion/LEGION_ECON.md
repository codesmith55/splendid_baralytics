# Legion economy — defs, asynchronous model, MedMex ROI/EROI

Source: headless re-sim of **2026-06-20_18-53-11-610** (Legion skirmish vs nothing,
confirmed `legcom` at frame 0), engine `recoil_2025.06.24`. Full defs saved to
[`legion_unitdefs.json`](legion_unitdefs.json) (252 defs). Model: [`legion_eco.mjs`](legion_eco.mjs).

> **Confirm-vs-memory (patch/mod drift):** numbers below are pulled from *current* game
> data, and a few differ from the remembered values — flagged with ⚠. Do the one-time
> in-game pull to confirm these are what your client runs.

## Asynchronous economy — measured, not assumed

Per-mex output measured from the replay (commander cluster on ATG): `5×1.47 + 2(com) = 9.35 m/s` ✓ and `30(com) + 3×7 = 51 E/s` ✓ — so the model is empirically exact.

| Unit | metal | energy | buildTime | output | running E | vs arm/cor |
|---|--:|--:|--:|--:|--:|---|
| `legmex` Metal Extractor | 50 | 500 | 1880 | **1.47 m/s** | **+7 E** | ⚠ extr 0.0008 = **80%** of standard (0.001), not 75%; and **+7 E** vs arm/cor mex's −3 E |
| `legmext15` "Overcharged" (**MedMex**) | 250 | 5000 | 5000 | **3.68 m/s** | **−30 E** | ⚠ extr 0.002 = **2.5× a legmex** (2.0× standard). The *bonus* over a legmex is +1.5× base → likely the source of your "1.5×". −30 E confirmed. |
| `legmoho` Adv Extractor (T2) | 640 | 8100 | 14100 | 7.35 m/s | −20 E | extr 0.004 |
| `legsolar` Solar | 155 | 0 | 2800 | — | +20 E | e-cost 0 (cheap E) |
| `legadvsol` Adv Solar | 465 | 4080 | 12500 | — | +100 E | |
| `legcom` Commander | 2700 | 26000 | 75000 | 2 m/s | +30 E | 300 BP |

**The asynchronicity:** a legmex is metal-light (80%) but **energy-positive (+7 E)** — it
pays for its own upkeep and then some, so Legion needs far less early solar than arm/cor.
The trade is lower metal income per spot. MedMex inverts it: big metal, big negative energy.

## Builders (your "funky E income / BP, cheaper, 275")

| Unit | metal | BP | running E |
|---|--:|--:|--:|
| `legck` Construction Bot (worker) | 100 | **75** | +5 E |
| `legcv` Construction Vehicle | 125 | 85 | +7 E |
| `legnanotc` Construction Turret | 230 | **200** | 0 |
| **worker + con turret** | 330 | **275 BP** | ⚠ your "275" = legck (75) **+** legnanotc (200) combined, not the turret alone |

At 275 BP: legmex builds in **6.8 s**, MedMex **18.2 s**, solar **10.2 s**.

## MedMex ROI / EROI

**ROI (metal payback), same spot vs a legmex:** +200 m & +4500 e buys **+2.21 m/s** →
`200 / 2.21 = ` **~91 s** to repay the extra metal (ignores energy).

**EROI (full, incl. powering it):** MedMex drains 30 E/s → needs **2× legsolar** (+40 E)
to cover. Package extra cost = 200 (medmex over legmex) + 310 (2 solars) = **510 m**,
~38.5 s of builder time → full payback `510 / 2.21 = ` **~231 s**.

**Opportunity cost (the decider):** the same 250 m as a MedMex buys **5 legmexes =
7.35 m/s, +35 E** vs the MedMex's 3.68 m/s, −30 E. So:

> **MedMex is a spot-constrained play.** On metal-per-metal it loses badly to more
> legmexes and it's energy-negative — only worth it once you've **saturated available
> mex spots** and want more metal from a fixed number of spots (capped expansion,
> contested ground, or spiking income on a key spot).

## Re-run with your own numbers
`node legion/legion_eco.mjs <spotLegmexMps> <builderBP>` — defaults `1.47 275`. Use a
different spot value for richer/poorer metal spots, or a different BP for com (300) etc.

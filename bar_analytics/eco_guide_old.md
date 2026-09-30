# EcoGuide -- BAR (Beyond All Reason)

There are 3 mechanisms in BAR: **Metal**, **Energy**, and **Build Power**. Generators of M, E, or BP all have a payback time.

* The point of this guide is to understand those payment times **not by an exact number, but by magnitude** -- big or small. The exact numbers in the tables below are a sanity check, not something you should be doing in your head mid-game.
* All "TROI" numbers below are converted to a single currency using the T1 energy converter rate: **70 E = 1 M**. This isn't a perfect conversion (you usually never want to actually run T1 converters as your main metal source), but it's the only common denominator the engine offers, so we use it to compare across resources.

---

## Metal Extractors

Variable M extract based on map; **1.85 M/s is a reasonable median** for most maps. (Hover the metal-spot indicator to see the actual yield.)

**T1 Metal Extractor:** 50 M + 500 E -> 57c M ≈ 1.85 M/s

* Payback: 50 M / 1.85 = **27s** of pure metal payback, +500 E (which is ~7 M of energy) = **31s + Build Time**.
* Rule of thumb: if you're rushing a unit or building, don't drop a T1 mex unless the rush takes at least ~31s anyway, or you care more about ongoing scaling than the immediate finish.

**Commander Mex (Commander BP = 300):** 1870 BP / 300 BP = 6.25s build, +31s payback = **~37s** until your economy has more total metal than if the Commander hadn't built it (assuming no build-stall).

The Commander's high BP means it's the cheapest way to **start** a mex; the build-time portion of the ROI is small enough to ignore. After that first one, hand mex production off to a T1 con or a Construction Turret.

---

## Energy Generators

Energy generators have **two ROIs**:

* **Energy_ROI (EROI)** -- Time the generator takes to pay back its own energy cost. (For zero-energy-cost gens like Solar, this collapses to Build Time.)
* **Total_ROI (TROI)** -- Time the generator takes to pay for **everything** it consumed, with metal converted to energy at 70:1. Formula: `(M_cost * 70 + E_cost) / output_E_per_s`.

The numbers below assume a **300 BP T1 constructor**. Faster builders shorten Build Time (and so EROI for Solar), but TROI is unaffected.

### Solar -- the boring reliable one

```
Armada Solar : 155 M +    0 E + 2800 BP =   20 E/s   ->  EROI = Build Time (9.3s);  TROI ≈ 542s
Cortex Solar : 150 M +    0 E + 2800 BP =   20 E/s   ->  EROI = Build Time (9.3s);  TROI ≈ 525s
```

* No energy up-front cost, so it never stalls your energy on the way up.
* Big build time and big metal cost. Medium TROI.
* Default if you can't be bothered to think, or if the map's avg wind is too low.

### Wind -- swingy, but the best on a windy map

```
Armada Wind  :  40 M +  175 E + 1600 BP =  0.6-2.5 E/s
Cortex Wind  :  43 M +  175 E + 1600 BP =  0.6-2.5 E/s
```

| Wind output       | EROI (Armada / Cortex) | TROI (Armada / Cortex) |
| ----------------- | ---------------------- | ---------------------- |
| Min wind (0.6)    | 292s   /  292s         | 4958s  /  5308s        |
| Mid wind (~1.55)  | 113s   /  113s         | 1919s  /  2055s        |
| Max wind (2.5)    |  70s   /   70s         | 1190s  /  1274s        |

* **Cheap**: ~25% the metal of a Solar and 60% the BP. You can spam them.
* **Variable**: the in-game wind value is **not linear from min to max** -- hover the wind-speed box on the side panel to see the exact value for the current map.
* **Default rule: if avg wind on the map is > ~1.1, build Wind, not Solar.** The TROI looks worse on paper but you build them faster, in larger numbers, and the per-tile up-front metal commitment is tiny.

### Advanced Solar -- density, not ROI

```
Armada AdvSolar : 350 M + 5000 E + 8000 BP =   75 E/s   ->  EROI ≈  67s;  TROI ≈ 393s
Cortex AdvSolar : 370 M + 4000 E + 8200 BP =   75 E/s   ->  EROI ≈  53s;  TROI ≈ 399s
```

* Build it for **E/s per tile** in a fortified base, not for early-game ROI.
* The 4-5k energy up-front cost is a real consideration -- you need to be running a healthy E surplus before you start one, or it'll stall you.
* Once it's up, TROI is actually **better than Solar's** because the output is so much higher relative to the metal cost.

### Magnitude summary

* **Solar** = boring and reliable. Build when energy is more important than metal and you don't trust the wind.
* **Wind** = best when avg wind > ~1.1. Cheap up-front, scales with map.
* **AdvSolar** = density play, not an opener.
* **(Geothermal not listed here -- on geo maps it's a separate calculation, generally the best E/s per metal in the game when a vent is available.)**

---

## Build Power

When we make Build Power instead of the thing the BP would have built, it slows down our production until the BP has paid for itself. We call this **BP_ROI**.

**Metal + Energy = Build Power.**

* **Construction Turret:** 200 M + 3200 E = 5300 BP at 200 BP/s -> **26.5s + Build Time** to break even.
* **T1 mobile cons:** 110-135 M + 1600-2100 E (Arm Bot through Cor Veh).

The cheaper bot/veh constructors recover their cost faster than a Con Turret in raw payback time, but the Con Turret has higher BP and infinite "patience" once placed -- pick based on whether you need mobility or sustained throughput.

---

## The decision tree (the real point of the guide)

You want to keep both metal and energy near-balanced and trending up. Use **spacebar + N** to insert these actions into your queue based on your current state:

1. **Metal in storage, no E to spend it** -> build a **Solar** (or Wind, if windy map).
2. **Both M and E producing healthily, but BP-bound** -> build a **mobile con or Con Turret**.
3. **Excess M and E, building queue empty** -> build a **mex** at the next open spot, or **AdvSolar** if you've already covered the map.
4. **Default if avg wind > ~1.1** -> Wind.
5. **Default otherwise** -> Solar.

Those are the main 3 levers (mex, energy gen, BP) and learning to insert them at the right moment in response to your current eco state is what drives the whole game.

---

## Where the numbers come from

All ROI numbers in the energy section are computed by `BAR/eco_calculator.py` from `BAR/bar_eco_table.csv`. Run it any time the patch changes resource costs:

```
python BAR/eco_calculator.py                         # default report
python BAR/eco_calculator.py --wind 1.55             # average wind override
python BAR/eco_calculator.py --md eco_extension.md   # also dump a markdown table
```
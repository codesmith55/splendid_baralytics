# Legion build-order simulator/comparator

[`legion_sim.mjs`](legion_sim.mjs) — projects a Legion build order forward from a start
state with **build power, walk times (distance/speed), and resource-gated stalls** baked
in, using the measured Legion eco model ([`LEGION_ECON.md`](LEGION_ECON.md)).

## Constants (calibrated from replay 2026-06-20_18-53-11-610)
- commander: **300 BP, 37.5 elmo/s**, base **2 m/s / +30 E**.
- legmex **1.47 m/s, +7 E** · MedMex **3.68 m/s, −30 E** · solar **+20 E**.
- build time(s) = `unitBuildTime / buildPower`; walk(s) = `distance / speed`.
- Validated: income curve reproduces the replay exactly (`3.5 / 4.9 / 6.4 m/s` for 1/2/3 mex),
  and the modelled 4th-mex walk (475 el) matches the replay's 0:34 finish.

> Build/walk times are **modelled** for now. Task #2 refines them with exact values from
> **live games** (via `bar_analytic_live`) and from skirmish-replay mex timings per map/spot.

## API
- `simulate(order, opts)` → `{ t, metal, energy, incM, incE, value, stalledSec, log }`.
  `order` is a list of steps: `{do:"mex"|"medmex"|"solar"|"build"|"wait"|"comboom", dist, name, secs}`.
  `opts`: `startMetal/startEnergy`, `startIncM/startIncE` (seed the income from already-built
  economy), `assists:[{at,bp}]` (worker/turret BP joining at time `at`), `comReclaimMetal`,
  `until`.
- `compare(builds, checkpoint)` → table of M/s, E/s, banked m/e, #built, value, stall_s.
- `project(seed, suggested, original, horizon)` → the narrative form:
  *"In this replay: you were at m:ss with R m / R e. System suggests <plan>. Compare end-state
  at <next> …"* — seed `{t, metal, energy, incM, incE, note}`.

## Demo output (4:00 checkpoint)
- `3 mex > factory > 2 solar` → 10.8 m/s, 132 E/s, banked 816 m / 9021 e.
- `3 mex > 4th mex > factory` → 10.8 m/s, banked 964 m (slightly ahead on metal).
- `3 mex > factory > MedMex` → **11.6 m/s** but energy banked only 3710 (the −30 E drain shows).

Seeded example (seed = replay state at 1:00, 4 mex / 7.9 m/s): expanding 3 more mex reaches
**12.3 m/s by 3:00** vs factory-then-sit's 7.9 m/s — the calculator quantifies the gap.

## Next
The 5 ChronoLog openings (task #4) are just `order` arrays fed to `compare()`/`project()`;
the `comboom` step models "explode commander for metal". T2 lines (task #5) extend the
`build` step with leglab→legalab→T2 con/infestor.

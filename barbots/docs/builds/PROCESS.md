# Process: investigating a new build

How to take a build *idea* and turn it into a finished, gradeable analysis. The steps are
the same whether a human or an AI process runs them — the AI dispatch path
([DISPATCH.md](DISPATCH.md)) just automates this loop. Output is a
`docs/builds/<slug>.md` from [`_TEMPLATE.md`](_TEMPLATE.md), and — where the build is
concrete enough — a compilable intent in `intents/`.

## The loop

1. **State the question and the checkpoint.** A build is only comparable if it has a
   finish line. Write the one-sentence `question` and the shared `checkpoint` (e.g. "T2
   mex online", "1–2 gunslingers on field"). Builds graded to different checkpoints can't
   be compared — pick the one the idea is really about.

2. **Describe it as an economic machine, not a click order.** What does it spend, produce,
   and liquidate? Reclaim lumps, factory-as-battery tricks, gifted units — write the
   *flows*, not the keystrokes. This is where a build usually reveals it isn't what it
   looks like.

3. **Pull the costs.** Every unit/building gets its `metal / energy / buildWork` from
   [`planner/data/units.json`](../../planner/data/units.json). Cite the key. If a unit
   isn't in the table (bot units, T2 lab, anything new), it's a **placeholder** — carry it
   as a symbol and add it to `Values still needed`. **Never invent a number.**

4. **Apply the three clocks.** For each phase, write `w/BP`, `m/M_income`, `e/E_income`
   and take the max ([the shared model](README.md#the-shared-model-the-three-clocks)).
   Build a phase ledger; track metal and energy balance across the whole build so reclaim
   lumps are timed against spends. Identify **the gate** — the clock that binds — because
   that names the lever.

5. **Work a concrete example.** Plug in a realistic eco (`M_f`, `E_f`, front BP, counts).
   Tabulate target(s) vs gate. This turns "it depends" into a number with stated inputs.

6. **Find the flip.** What threshold changes the verdict? A patch value (Gunslinger
   11000→6500 energy), a contested-resource amount (rock field `F`), a crossover count
   (≥4 cons before worker parallelism beats the com). The flip is the most reusable output.

7. **Write findings in lost-seconds terms.** Answer the `question`. Each finding names the
   gate, the lever, and the flip. Convert non-eco payoffs (denial, eco-damage) to seconds
   via the compound factor ([currency](README.md#currency-lost-seconds)).

8. **List what's still unknown.** The canonical values that would make it exact, each with
   where it lives. Set `status`: `idea` → `analysis` (clocks done, placeholders flagged) →
   `intent-ready` (compiles in the planner) → `scored` (projection bridge ran).

9. **(When concrete) emit an intent and compile-check it.** If the build maps to the
   shorthand ([intent-grammar.md](../intent-grammar.md)), write the `intent` block, then:
   ```
   node planner/parse-intent.mjs intents/<slug>.md     # compiles to a goal DAG?
   node planner/expand-goals.mjs intents/<slug>.md      # expands to a costed action list?
   ```
   A clean compile promotes the build to `intent-ready`. Once the projection bridge lands,
   the same intent yields the projected timeline and the build becomes `scored`.

## Done check

- [ ] front-matter filled (`build`, `status`, `question`, `checkpoint`, `gate`, `needs`)
- [ ] every number cited to `units.json` or flagged a placeholder
- [ ] the gate is named and a worked example produces a figure
- [ ] findings answer the `question` and name the flip
- [ ] `needs:` matches the "Values still needed" section
- [ ] linked from [README.md](README.md) and (if concrete) has an `intents/` file that compiles

# Design: AI build dispatch from mobile

Goal: a user on their phone sends a terse prompt, and an AI process turns it into a
finished build analysis (following [PROCESS.md](PROCESS.md)) — reading the cost tables,
applying the three clocks, compile-checking an intent where possible, and replying with
the findings. No game client, no laptop, one message in → one analysis out.

This works because a build has two faces the repo already supports: a **human analysis**
(`docs/builds/<slug>.md`) and a **machine intent** (`intents/<slug>.md`, compiled by
`parse-intent.mjs` → `expand-goals.mjs`). The AI's job is to produce the first and, when
the idea is concrete, the second — then let the existing planner CLIs check its work.

## The dispatch prompt

Optimised for thumb-typing. Only `idea` and `ask` are required; everything else the agent
infers or marks unknown. Free prose also works — an LLM agent normalises it — but this
shape makes the inputs explicit and the reply deterministic:

```
/build <slug>
idea:        <one sentence — the build and the bet>
eco:         M=<m/s> E=<e/s> [bp=<front build power>] [bank: m=.. e=..]
constraints: <e.g. front-only BP, no backline energy>
patch:       <unit field: old→new, ...>        (optional)
ask:         <the question, e.g. "time to 1-2 gunslingers">
```

Example (the Gunslinger turnaround, as it would arrive from a phone):

```
/build gunslinger-turnaround
idea: reclaim T1 labs, T2 lab, pop 1 consul, sell the lab, pump gunslingers
eco: M=25 E=250 bp=860
constraints: front-only BP (com, front nanos, front cons)
patch: gunslinger metal 650→520, energy 11000→6500
ask: turnaround to 1-2 gunslingers on field
```

## The agent loop

A `build-investigator` process (a skill or a dispatched agent — see Wiring) runs:

1. **Parse** the dispatch into the front-matter fields of [`_TEMPLATE.md`](_TEMPLATE.md).
   Unstated numbers become `needs[]`, not guesses.
2. **Gather context, read-only:** [`README.md`](README.md) (shared model + currency),
   [`PROCESS.md`](PROCESS.md), [`planner/data/units.json`](../../planner/data/units.json)
   for every cost, and existing `docs/builds/*.md` for consistent structure and to avoid a
   duplicate slug.
3. **Run PROCESS.md steps 1–8** to fill the template. Hard rule: numbers are cited to
   `units.json` or flagged placeholders — the agent **never fabricates a unit stat**.
   Patch values from the dispatch override the table (and are recorded in `patch:`).
4. **Try to emit an intent.** If the build maps to the shorthand
   ([intent-grammar.md](../intent-grammar.md)), write `intents/<slug>.md` and run
   `parse-intent` + `expand-goals`. A clean compile promotes `status` to `intent-ready`
   and the agent attaches the costed action list; a failure is reported, not hidden.
5. **Write** `docs/builds/<slug>.md`, add the README index line, and **reply to mobile**
   with: the gate, the worked number (or "symbolic — needs X"), the flip, and the top 1–3
   `needs[]`. Keep the reply to a glanceable few lines; the doc holds the detail.
6. **Don't commit unless asked.** Default: leave the new files in the working tree and say
   so. If the dispatch says `commit`, commit to a branch (never the default) with message
   `builds: <slug> (dispatch)`.

## Guardrails

- **Honesty over completeness.** A build with three placeholders and a named gate is a
  good result; a build with confident invented numbers is a failure. `status` cannot pass
  `analysis` while required `needs[]` are open.
- **One checkpoint.** The agent refuses to "compare" builds graded to different
  checkpoints — it states the mismatch instead.
- **Lost-seconds is the only verdict currency.** No "this build is strong" without a
  checkpoint time or a clearly-symbolic estimate.
- **Read-only outside the build's own files.** The agent writes `docs/builds/<slug>.md`,
  `intents/<slug>.md`, and the README index line. It does not touch planner code, the
  reader, or `units.json` (missing costs are reported as `needs[]`, not patched in).

## Interacting with existing builds

Front-matter ([`_TEMPLATE.md`](_TEMPLATE.md)) makes every build machine-addressable, so
dispatch verbs beyond "create" are cheap:

- `list` — enumerate builds with `status`, `gate`, open `needs`.
- `show <slug>` / `compare <a> <b>` — same-checkpoint only; reply with the lost-seconds
  delta (once scored) or the structural diff (until then).
- `rescore` — when `units.json` or a `needs[]` value lands, re-run the clocks (and, once
  it exists, the projection bridge) for affected builds and report what moved.

## Wiring (how a mobile message reaches the loop)

The repo defines the *contract* (dispatch grammar, template, guardrails); the trigger is
Claude Code capability, not repo code:

- **Skill** — a `build-investigator` skill so `/build …` in any session (mobile app
  included) runs the loop. Simplest path; user-initiated.
- **Scheduled / routed agent** — a routine that watches an inbox (a dispatch file, a
  label, a channel) and dispatches queued `/build` prompts as background agents, replying
  when done. Fits "send from phone, get the analysis later".

Either way the agent's instructions are *this file* + PROCESS.md, so the behaviour is the
same however it's triggered.

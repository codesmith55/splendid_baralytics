# Intent shorthand grammar (machine-readable build block)

An intent `.md` file has two parts: human prose (the build declaration in plain
English, for people) and a fenced ` ```intent ` block (the machine input).
`planner/parse-intent.mjs` reads only the fenced block and compiles it into a goal
DAG — see [intent-language.md](intent-language.md) for the DAG shape and the worked
example.

This shorthand is **structured**, not free-form English. Turning prose into shorthand
is a separate (future, likely LLM-assisted) step; the parser does not attempt it.

## Block

A `\`\`\`intent` … `\`\`\`` fenced block. One statement per line. Blank lines and lines
beginning with `#` are ignored (comments). Bracket lists (`[a,b,c]`) must contain no
spaces.

Every statement is `<verb> <head>: <body>`. The body is whitespace-separated tokens:
each token is either **positional** or a **kwarg** (`key=value`, key matching
`[a-z][a-z-]*`).

Common kwargs: `id=` (required on every goal), `after=` (a goal id this goal sequences
after).

## Statements

### `build <who>: <count?> <name> [to-total N | to-target N] [parallel] [kwargs]`
A build goal. `<who>` (between `build` and `:`) is empty, a single actor (`com`,
`worker1`), or a group `[com,worker1,worker2]`.

| token | compiles to |
|---|---|
| leading integer `3 mex` | `count: 3` |
| `to-total N` | `countToTotal: N` (raise to a shared running total) |
| `to-target N` | `countToTarget: N` (build toward a conditional target, e.g. wind) |
| `parallel` | `parallel: true` |
| `priority=critical` | `priority: "critical"` |
| `conditional=wind:solar_equivalent_eps` | `conditional: { on: "wind", lowWindSubstitute: "solar_equivalent_eps" }` |

### `produce <factory>: <item, item, *repeat> [assist=who] [kwargs]`
A factory production program. Items are comma-separated; `*x` means repeat `x` until
countermanded → `{ "repeat": "x" }`. `assist=com` → `assist: "com"`.

### `meta <kind> <unit>: [kwargs]`
A meta action on a unit. Supported kinds:
- `give_unit` — `to=ally:air` → `to`, `timer=walk_arrival:<target>` →
  `timer: { type, target }`.
- `reclaim_zone` — `zone=<map>:[positions]@<radius>` →
  `zone: { map, positions:[…], radiusElmos }`, `filter=features:rocks` → `filter`.

### `checkpoint <id>: goal=<goalId> metric=<metric>`
A named checkpoint. `metric=lost_seconds` is the native grading unit (see
intent-language.md). Adds to the DAG's `checkpoints` array rather than `goals`.

## Validation (compile-time, no live game)
- every goal has a unique `id=`
- every `after=` resolves to a known goal id
- every checkpoint `goal=` resolves to a known goal id

Errors are reported with the line number and the offending source line.

## CLI
```
node planner/parse-intent.mjs intents/<name>.md     # prints goal DAG JSON
```
`intentId` is the file stem. Run `node planner/test/parse-intent.test.mjs` for the
test suite (golden + per-construct + error cases).

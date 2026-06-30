# ai_processes — baranalytics / Gex

Runnable, discoverable process registry for the **BAR replay metrics** pipeline in
`gex_research/`. Same `pc` framework as `scavengers_guild/ai_processes`, with capabilities
for this project. Counterpart docs: `../DISPATCH.md`, `../gex_process.md`, `../headless_harness.md`.

---

## Quick start

Targets are **letters** (`a`, `b`, `c` … `z`, `aa`, `ab` …) — mobile-friendly, no numberpad.
Exact ids still work for stable scripting; legacy integers still work too.

```bash
pc                        # interactive menu
pc --spec --pretty        # full JSON spec (AI/agent-friendly)
pc info a                 # detail for capability a (bar_run_metric)
pc info a b               # sub-command b (run_001)
pc run  a b               # print the run command for that sub-command
pc run  bar_run_metric run_001   # same, by id
pc filter dispatch        # capabilities tagged 'dispatch'
pc tags                   # tag index   ·   pc .   navigation context
```

`pc` = `python capabilities.py`. Shortcuts: `pc.bat` (Windows cmd/PowerShell/Git Bash), `pc.sh` (bash;
`source pc.sh` for a persistent `pc` function). Both walk CWD upward for the nearest `capabilities.py`.

> Note: the capabilities are JS processes (`node process/run.mjs ...`); the `pc` registry that *indexes*
> them is Python. `pc run <letter> <letter>` prints the exact node command to execute — it does not run it.

---

## Capabilities

| key | ID | Name | Sub-cmds | What it does |
|-----|-----|------|----------|--------------|
| a | `bar_run_metric` | BAR Replay Metrics Runner | 3 (a/b/c) | Run metrics over a replay → JSON + HTML report |
| b | `bar_add_metric` | BAR Metric Registrar | — | Register a new metric from criteria JSON |
| c | `bar_add_situation` | BAR Situation Registrar | — | Register a new situation from criteria JSON |
| d | `bar_headless_extract` | BAR Headless Extractor | — | Replay a `.sdfz` headlessly → `actions.json` |
| e | `bar_demo_roster` | BAR Demo Roster Parser | — | Demo header → players (userId/faction/start) |
| f | `bar_catalog` | BAR Metric & Situation Catalog | 2 (a/b) | Inspect the master metric/situation lists |

Letter keys are positional (they shift if you reorder the list); the `ID` is the stable handle.
Run `pc --spec --pretty` for the live list with full schemas (inputs/outputs/usage).

---

## Most common dispatch

```bash
cd gex_research && node process/run.mjs 001        # = pc run bar_run_metric run_001
```
Or just say **"run the BAR economy metric"** — a dispatched agent resolves it via the project `CLAUDE.md`
and user memory.

---

## Adding a capability

Two ways:
1. **Built-in** — add a dict to `BUILT_IN_CAPABILITIES` in `capabilities.py` (schema: `id`, `name`,
   `description`, `module`, `usage`, `inputs`, `outputs`, `tags`, optional `commands[]`).
2. **Auto-discovered** — drop a `*.py` file in this folder that declares a module-scope `CAPABILITY = {...}`
   dict; it's picked up automatically (built-ins win on id collision).

This is distinct from adding a **metric/situation** to the pipeline itself — for that use
`bar_add_metric` / `bar_add_situation` (which edit `../metrics/catalog.json` and scaffold modules).

---

## Framework files

| File | Role | Edit when |
|------|------|-----------|
| `capabilities_core.py` | Base protocol (navigation, display, CLI) | Protocol changes only — copy from `scavengers_guild/ai_processes/` |
| `capabilities.py` | Project extension — BAR capabilities only | Adding / removing capabilities |

`capabilities.py` imports `run()` from `capabilities_core.py` and is the only file that needs
editing for capability changes.  The core is the "library"; this file is the "extension".

# barbots — Claude agent guide

_Scaffolded by ryan_adapter assess on 2026-07-01. Expand with project-specific context._

## What this project does

The third leg of the BAR analytics stack: a live bot that executes declared build intents in Beyond All Reason, using only the information a real player has.

## Stack

lua, node, npm

## Entry points

- `npm run test`  — node planner/test/parse-intent.test.mjs && node planner/test/expand-goals.test.m

## Session protocol

These instructions apply to every Claude Code session working in this project.
They are not suggestions — follow them as part of normal work output.

### Start of session

1. Read `next_todo.md` — understand current state and active tasks before doing anything.
2. Read `open_questions.md` — note unresolved gaps that may affect the work.
3. If this is a continuation of prior work, scan recent git log or file mtimes to
   reconstruct what changed since last session.

### During work

- When a task is started, mark it `[in progress]` in `next_todo.md`.
- When something is discovered that cannot be resolved in this session, add it to
  `open_questions.md` immediately (not at the end — while the context is live).
- When a significant decision is made (why X instead of Y), note it in the relevant
  file or in a brief inline comment — not in a standalone doc.
- Log work to ryan_adapter task_monitor if the resource is available:
  `python -m task_monitor log --project barbots --title "..." --resource local_llm`

### End of session

Before closing, always do these in order:

1. **Update `next_todo.md`** — mark completed tasks ✅, add newly discovered tasks,
   update status line at the top. Leave it accurate for the next session to read cold.
2. **Update `open_questions.md`** — close any questions answered this session,
   add any new ones surfaced. Questions that remain open across sessions are signals
   for higher-order solving (flag them with `[higher_model]` if they need it).
3. **Update entry points in this file** if new scripts, commands, or modules were added.
4. If a meaningful version milestone was reached, record it in `next_todo.md` status line.

### Output format rules

- No trailing summaries — the diff speaks for itself.
- No comments explaining what code does — only WHY if non-obvious (hidden constraint,
  workaround, subtle invariant).
- No creating new files unless required by the task. Prefer editing existing ones.
- No placeholder content — every file written should have real, usable content.
- Terse responses. One sentence per update. End-of-turn: what changed and what's next.

## Dispatch shorthands

`pc` — runs the nearest `capabilities.py` found by upward search.

```
pc               # interactive capability menu
pc --spec        # JSON spec (AI-friendly)
pc info a        # detail on capability a
pc run  a        # print run command for capability a
```

#!/usr/bin/env python3
"""barbots/capabilities.py — live BAR bot planner + reader + executor.

Third leg of the BAR analytics stack: takes a declared build intent
(a .md file), compiles it through parse-intent -> expand-goals ->
project into a costed, stall-annotated timeline, and (eventually)
executes it live via a fog-honest widget.

Expanded 2026-07-07 from the scaffold to cover every real verb the .mjs
modules and CLIs expose, plus the compound next_steps verb.
"""
from __future__ import annotations

import os, sys
from typing import Dict, List

_base = os.environ.get(
    "PC_BASE_DIR",
    "/sessions/clever-charming-euler/mnt/GitHub/scavengers_guild/ai_processes",
)
sys.path.insert(0, os.path.abspath(_base))
try:
    from capabilities_core import run
except ImportError:
    run = None


LOCAL_CAPABILITIES: List[Dict] = [
    # Planner layer 1 - intent -> goal DAG
    {
        "id": "parse_intent",
        "name": "Parse an intent file (Layer 1)",
        "summary": (
            "Reads intents/<name>.md, extracts the ```intent code block, "
            "compiles the shorthand DSL into a goal DAG (JSON). Pure "
            "text-to-JSON. 18 golden test cases."
        ),
        "usage": {
            "cli": "node planner/parse-intent.mjs intents/<name>.md",
            "example": "node planner/parse-intent.mjs intents/legion-pos6-t2-fusion.md",
            "api": "import { parseIntentFile } from './planner/parse-intent.mjs'",
        },
        "outputs": {"stdout": "{ intentId, goals: [...] }"},
        "tags": ["planner", "layer1", "intent", "compile", "dag"],
    },

    # Planner layer 2 - goal DAG -> costed action list
    {
        "id": "expand_goals",
        "name": "Expand goals to a costed action list (Layer 2)",
        "summary": (
            "Goal DAG to flat action list. Each action carries id, goalId, "
            "type, actor, target, metal_cost, energy_cost, build_time_s, "
            "optional walk legs, and `after` deps. Action types: build / "
            "queue_at / give_unit / reclaim_zone / checkpoint. Factory "
            "*repeat queues materialize FACTORY_QUEUE_HORIZON=8 concrete "
            "actions plus one tail flag. 29 golden test cases."
        ),
        "usage": {
            "cli": "node planner/expand-goals.mjs intents/<name>.md",
            "api": "import { expandGoalDag, expandIntentFile } from './planner/expand-goals.mjs'",
        },
        "outputs": {"stdout": "{ intentId, actions: [...] }"},
        "tags": ["planner", "layer2", "actions", "costs", "walk", "factory"],
    },

    # Planner layer 3 - projection
    {
        "id": "project_intent",
        "name": "Project an action list forward (Layer 3)",
        "summary": (
            "Feeds actions through gex_research's eco_engine. Every action "
            "gets projectedStart, projectedEnd, and stallSec. Emits "
            "goalTimelines + sampled econSeries. Default initial state is "
            "ARM opening (3 mex + commander); pass --wind for turbine e/s."
        ),
        "usage": {
            "cli": "node planner/project.mjs intents/<name>.md [--wind=N]",
            "api": "import { projectActionList } from './planner/project.mjs'",
        },
        "outputs": {"stdout": "{ intentId, actions, goalTimelines, econSeries }"},
        "tags": ["planner", "layer3", "project", "eco_engine", "stall", "timeline"],
    },

    # Position / state extraction
    {
        "id": "extract_position_file",
        "name": "Load a saved position file",
        "summary": (
            "Reads positions/named/<name>.json into eco_engine createState() "
            "parameters. Legion-aware synth_mexes calibration."
        ),
        "usage": {
            "cli": "node planner/extract-position.mjs --position <name> [--t <sec>] [--out <file>]",
        },
        "tags": ["planner", "state", "position", "extract", "eco_engine"],
    },
    {
        "id": "extract_position_demo",
        "name": "Extract createState() from a BAR demo (.sdfz)",
        "summary": (
            "Headless BAR demo parse at time T. Emits observed metal / "
            "energy / income / storage + a fitted createState() with "
            "Legion residual calibration. --player defaults to 'splendi'."
        ),
        "usage": {
            "cli": "node planner/extract-position.mjs --demo <path.sdfz> [--t <sec>] [--player <name>] [--out <file>]",
        },
        "outputs": {
            "fields": [
                "source", "t", "faction", "observed", "createState",
                "calibration", "completed", "inProgress",
            ],
        },
        "tags": ["planner", "state", "demo", "sdfz", "headless", "extract"],
    },

    # Compound: next_steps - the primary bot query
    {
        "id": "next_steps",
        "name": "Project next steps from a state reference",
        "summary": (
            "Given a state reference (--position | --demo+--t | --state) "
            "AND an intent (--intent-name | --intent), runs Layers 1-3 "
            "and returns the next N projected actions after time T. "
            "Answers 'from here, what should I do next and when?' - the "
            "primary bot query. Also returns nextCheckpoints (goal-level "
            "milestones in the same window)."
        ),
        "usage": {
            "cli": (
                "node planner/next-steps.mjs "
                "(--position <name> | --demo <path.sdfz> [--t <sec>] | --state <json>) "
                "(--intent <path.md> | --intent-name <name>) "
                "[--n 5] [--from-t 0] [--wind 10] [--summary]"
            ),
            "example_position": (
                "node planner/next-steps.mjs --position pos_50s_legpos6 "
                "--intent-name legion-pos6-t2-fusion --n 5 --from-t 60 --summary"
            ),
            "example_demo": (
                "node planner/next-steps.mjs --demo demo.sdfz --t 120 "
                "--intent-name legion-pos6-t2-fusion --n 3 --from-t 120"
            ),
            "example_default": (
                "node planner/next-steps.mjs --intent-name legion-pos6-t2-fusion --n 3 --summary"
            ),
            "api": "import { nextSteps } from './planner/next-steps.mjs'",
            "list_intents": "node planner/next-steps.mjs --list-intents",
        },
        "outputs": {
            "stdout_json": (
                "{ intent, state, projection, nextActions, "
                "nextCheckpoints, windowFrom, n }"
            ),
        },
        "tags": ["planner", "compound", "next-steps", "projection", "live", "adapter"],
    },
    # Demo roster + finder — describe starting positions on both teams
    {
        "id": "demo_roster",
        "name": "Read demo -> per-team roster with start positions",
        "summary": (
            "Reads a .sdfz header (fast, --skipPackets) and emits per "
            "allyTeam roster: player name, teamId, faction, skill, rank, "
            "start position, and the ally team's start box (for box-mode "
            "starts). Winning team is starred. Answers 'who was on which "
            "team, where did they start, and who won'."
        ),
        "usage": {
            "cli": "node planner/demo-roster.mjs <path.sdfz> [--summary]",
            "api": "import { readDemoRoster, describeRoster } from './planner/demo-roster.mjs'",
        },
        "outputs": {
            "stdout_json": (
                "{ source, meta:{map,engine,startTime,durationMinutes,"
                "playerCount,allyTeamCount,winningAllyTeamIds,startPosType}, "
                "allyTeams:[{allyTeamId,playerCount,startBox?,players:["
                "{name,teamId,faction,skill,rank,startPos,rgbColor}]}], "
                "spectatorCount }"
            ),
        },
        "tags": ["planner", "demo", "sdfz", "roster", "start-position", "teams", "headless"],
    },
    {
        "id": "find_demo",
        "name": "Find most-recent demo matching criteria",
        "summary": (
            "Scans a BAR demo directory (default: %LocalAppData%/BAR/data/"
            "demos on Windows, ~/.spring/demos otherwise) and returns the "
            "newest demos matching --players, --min-duration, --match "
            "regex. Reads each candidate's header via sdfz-demo-parser to "
            "confirm the actual counts. --limit caps how many candidates "
            "are opened."
        ),
        "usage": {
            "cli": "node planner/find-demo.mjs [--dir <path>] [--players N] [--min-duration <sec>] [--match <regex>] [--limit 20] [--n 1] [--json]",
            "example_16p_10min": "node planner/find-demo.mjs --players 16 --min-duration 600 --n 1",
            "api": "import { findDemos, defaultDemoDir } from './planner/find-demo.mjs'",
        },
        "outputs": {
            "stdout_json_with_flag_json": (
                "[{ path, name, mtimeMs, map, playerCount, allyTeamCount, "
                "durationSec, durationMinutes, winningAllyTeamIds }]"
            ),
        },
        "tags": ["planner", "demo", "find", "selector", "sdfz", "roster"],
    },
    {
        "id": "describe_last_game",
        "name": "Describe the last game matching criteria",
        "summary": (
            "Compound: find-demo -> demo-roster. Chains find-demo (newest "
            "demo matching filter) into demo-roster (per-team roster + "
            "start positions). Answers 'break down the last N-player game "
            "over M minutes'. Prints a summary table then JSON."
        ),
        "usage": {
            "cli": (
                "node -e 'import(\"./planner/find-demo.mjs\").then(async ({findDemos}) => "
                "{ const [d] = await findDemos({players:+process.argv[1]||16, minDurationSec:+process.argv[2]||600}); "
                "if (!d) return console.error(\"no match\"); "
                "const {readDemoRoster, describeRoster} = await import(\"./planner/demo-roster.mjs\"); "
                "const r = await readDemoRoster(d.path); console.error(describeRoster(r)); "
                "console.log(JSON.stringify(r, null, 2)); })' 16 600"
            ),
            "example": "See usage.cli — first CLI arg is player count, second is min-duration seconds.",
        },
        "tags": ["planner", "compound", "demo", "roster", "start-position"],
    },

    {
        "id": "list_intents",
        "name": "List available intent files",
        "summary": "Enumerate intents/*.md - the declared build orders barbots can execute.",
        "usage": {
            "cli": "node planner/next-steps.mjs --list-intents",
            "api": "import { listIntents } from './planner/next-steps.mjs'",
        },
        "tags": ["planner", "intents", "discovery"],
    },

    # Experiments (sweeps)
    {
        "id": "exp_legion_fusion_path",
        "name": "Sweep: Legion pos6 T2 fusion path",
        "summary": (
            "Sweeps 0-4 medmex x solar counts. Reads costs from "
            "gex_research/legion/legion_unitdefs.json. Result: 3 medmex "
            "+ 12 solars -> fusion online 7:40."
        ),
        "usage": {"cli": "node planner/experiments/legion-t2-fusion-path.mjs"},
        "tags": ["experiment", "sweep", "legion", "fusion", "t2"],
    },
    {
        "id": "exp_legion_5walk_2workers",
        "name": "Experiment: Legion 5-walk 2-workers opening",
        "summary": "Legion opening variant experiment.",
        "usage": {"cli": "node planner/experiments/legion-5walk-2workers.mjs"},
        "tags": ["experiment", "legion", "workers"],
    },
    {
        "id": "exp_first_unit_reclaim_vs_mex",
        "name": "Experiment: first-unit reclaim vs early mex",
        "summary": "Reclaim-first vs mex-first opening comparator.",
        "usage": {"cli": "node planner/experiments/first-unit-reclaim-vs-mex.mjs"},
        "tags": ["experiment", "reclaim", "opening"],
    },
    {
        "id": "live_reader",
        "name": "LiveReader - poll bar_analytic_server /api/state",
        "summary": (
            "Fog-honest live-state reader. Polls bar_analytic_server, "
            "emits typed events: econ, builderIdle, builderBusy, "
            "gameReset, gameEnd, error. Requires Node 18+."
        ),
        "usage": {
            "api": (
                "import { LiveReader } from './reader/live-reader.mjs'; "
                "const r = new LiveReader(); "
                "r.on('builderIdle', b => ...); r.start();"
            ),
        },
        "tags": ["reader", "live", "fog-honest", "events"],
    },
    {
        "id": "adapter_replan",
        "name": "Adapter: merge queue with live state + re-plan on divergence",
        "summary": "PLANNED, NOT BUILT (adapter/ is empty).",
        "usage": {"cli": "(not yet implemented)"},
        "tags": ["adapter", "planned"],
    },
    {
        "id": "executor_orders",
        "name": "Executor: issue in-game commands",
        "summary": "PLANNED. Primary path: Lua widget via Spring.GiveOrderToUnit.",
        "usage": {"cli": "(not yet implemented)"},
        "tags": ["executor", "planned", "lua", "widget"],
    },
    {
        "id": "npm_test",
        "name": "Run planner test suites",
        "summary": "parse-intent (18) + expand-goals (29) + project tests.",
        "usage": {"cli": "npm run test"},
        "tags": ["test", "npm", "golden"],
    },
]


def _spec():
    return {
        "project": "barbots",
        "description": (
            "Third leg of the BAR analytics stack. Reads declared build "
            "intents (.md), compiles them through parse-intent -> "
            "expand-goals -> project into a costed, stall-annotated "
            "timeline, then (planned) executes live via a fog-honest widget."
        ),
        "capabilities": LOCAL_CAPABILITIES,
    }


if __name__ == "__main__":
    if "--spec" in sys.argv:
        import json
        print(json.dumps(_spec(), indent=2))
    elif run is not None:
        run(LOCAL_CAPABILITIES, root_dir=__file__)
    else:
        import json
        print(json.dumps(_spec(), indent=2))
parse-intent -> "
            "expand-goals -> project into a costed, stall-annotated "
            "timeline, then (planned) executes live via a fog-honest widget."
        ),
        "capabilities": LOCAL_CAPABILITIES,
    }


if __name__ == "__main__":
    if "--spec" in sys.argv:
        import json
        print(json.dumps(_spec(), indent=2))
    elif run is not None:
        run(LOCAL_CAPABILITIES, root_dir=__file__)
    else:
        import json
        print(json.dumps(_spec(), indent=2))

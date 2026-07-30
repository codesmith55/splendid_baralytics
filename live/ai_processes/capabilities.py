#!/usr/bin/env python3
"""
live/ai_processes/capabilities.py
-----------------------------------------------------------------------------
Capability registry for bar_analytic_live — realtime BAR economy dashboard.

Sub-project of splendid_baralytics.  Provides a live streaming pipeline:
  widget (Lua) → JSONL file → server (Python) → browser dashboard (HTML)

Framework:   ../../../../ai_processes/capabilities_core.py  (canonical peer)
             capabilities_core.py  (local sync copy fallback)

SHORTCUT: `pc` from this folder (or any parent) picks this file up.

Quick dispatch:
  pc info a         Start server (default path + port 8787)
  pc run  a         Full server start command
  pc info b         Install the Lua widget to BAR
  pc info c         Open the dashboard in the browser
  pc info d         JSONL stream inspection commands
  pc info e         Classifier triage (others_to_be_classified.md)
  pc filter live    capabilities tagged 'live'
-----------------------------------------------------------------------------
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List

_base = os.environ.get(
    "PC_BASE_DIR",
    os.path.dirname(os.path.abspath(__file__)),
)
sys.path.insert(0, os.path.abspath(_base))
from capabilities_core import run  # noqa: E402

# BAR data path (edit if BAR is installed elsewhere)
_BAR_DATA = "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data"
_JSONL    = f"{_BAR_DATA}/bar_analytic_live.jsonl"
_WIDGET_DST = f"{_BAR_DATA}/LuaUI/Widgets/bar_analytic_live.lua"

LOCAL_CAPABILITIES: List[Dict] = [

    # -------------------------------------------------------------------------
    # a  Live Analytics Server  (primary entry point)
    # -------------------------------------------------------------------------
    {
        "id": "bar_live_server",
        "name": "Live Analytics Server",
        "description": (
            "Start bar_analytic_server.py: tails the widget JSONL, keeps per-team "
            "economy state, and serves http://localhost:8787 (dashboard + /api/state). "
            "Auto-exits ~4 min after a game ends; use --no-exit to run always-on. "
            "The widget must be installed and enabled (F11) in BAR. "
            "Spectate a game for full 16-player data; as a player only your ally team is visible."
        ),
        "module": "bar_analytic_server.py",
        "usage": "cd live && python bar_analytic_server.py",
        "inputs": {
            "--path FILE":       f"JSONL source (default: {_JSONL})",
            "--port N":          "HTTP port (default: 8787)",
            "--watch GLOB":      "Glob of JSONL files to auto-follow freshest (default: *.jsonl beside --path)",
            "--scan N":          "Seconds between source rescans (default: 60; drops to 5 after game ends)",
            "--end-grace N":     "Seconds to wait for a new game before self-terminating (default: 240)",
            "--idle-end N":      "No-new-frames seconds that mark a game as ended (default: 45)",
            "--no-exit":         "Never self-terminate — legacy always-on behavior",
        },
        "outputs": {
            "http://localhost:8787":          "Live dashboard (SVG pie grids, one per player)",
            "http://localhost:8787/api/state": "JSON snapshot of current per-team economy state",
        },
        "tags": ["bar", "live", "server", "dashboard", "dispatch"],
        "commands": [
            {
                "id": "start_default",
                "name": "Start (default path + port)",
                "description": "Run the server with defaults: reads the standard JSONL path, serves port 8787.",
                "usage": "cd live && python bar_analytic_server.py",
            },
            {
                "id": "start_custom_path",
                "name": "Start with custom JSONL path",
                "description": "Point at a different JSONL file (e.g. a recording from another session).",
                "usage": f"cd live && python bar_analytic_server.py --path <path/to/file.jsonl>",
            },
            {
                "id": "start_no_exit",
                "name": "Start always-on (never self-terminate)",
                "description": "Keep the server running across game sessions indefinitely.",
                "usage": "cd live && python bar_analytic_server.py --no-exit",
            },
            {
                "id": "start_custom_port",
                "name": "Start on a different port",
                "description": "Serve on a non-default port (useful if 8787 is busy).",
                "usage": "cd live && python bar_analytic_server.py --port 9000",
            },
        ],
    },

    # -------------------------------------------------------------------------
    # b  Install Lua Widget
    # -------------------------------------------------------------------------
    {
        "id": "bar_live_widget_install",
        "name": "Install Lua Widget",
        "description": (
            "Copy bar_analytic_live.lua to the BAR LuaUI/Widgets folder so the game "
            "can load it. After install: launch BAR → press F11 (Widget Manager) → "
            "find 'bar_analytic_live' → enable. Spectate a game for full 16-player data. "
            "The widget emits line-delimited JSON to the configured outPath (CONFIG.outPath "
            "in the Lua file) every 0.5 s. Edit CONFIG.outPath in the .lua file if BAR is "
            "installed in a non-default location before copying."
        ),
        "module": "bar_analytic_live.lua",
        "usage": f"copy live\\bar_analytic_live.lua \"{_WIDGET_DST}\"",
        "inputs": {
            "bar_analytic_live.lua": "Source widget file (live/ directory)",
            "CONFIG.outPath":        f"Destination JSONL path baked into the widget (default: {_JSONL})",
        },
        "outputs": {
            _WIDGET_DST: "Widget installed to BAR's LuaUI/Widgets folder",
        },
        "tags": ["bar", "live", "widget", "install", "lua"],
        "commands": [
            {
                "id": "install_windows",
                "name": "Install (Windows)",
                "description": "Copy the widget to the default BAR install location on Windows.",
                "usage": f"copy live\\bar_analytic_live.lua \"{_WIDGET_DST}\"",
            },
            {
                "id": "verify_install",
                "name": "Verify install",
                "description": "Check that the widget file exists in BAR's widget folder.",
                "usage": f"dir \"{_WIDGET_DST}\"",
            },
            {
                "id": "check_output",
                "name": "Check JSONL output",
                "description": "Confirm the widget is emitting events (file grows while in-game).",
                "usage": f"python -c \"import os,time; [print(os.path.getsize(r'{_JSONL}'), 'bytes') or time.sleep(1) for _ in range(5)]\"",
            },
        ],
    },

    # -------------------------------------------------------------------------
    # c  Open Dashboard
    # -------------------------------------------------------------------------
    {
        "id": "bar_live_dashboard",
        "name": "Open Live Dashboard",
        "description": (
            "Open the live SVG dashboard in the browser. Requires the server to be running "
            "(bar_live_server). The dashboard polls /api/state at 1 Hz and renders two 2×4 "
            "grids of pie charts (one grid per ally team): area ∝ total asset value, "
            "wedges = value buckets (Military / Defense / Build Power / Economy / "
            "Infrastructure / Commander / Support / Other), outer ring = storage fill, "
            "twin spark-bars = metal + energy income. Hover a pie for full topline. "
            "Enemy pies are hollow when not spectating."
        ),
        "usage": "start http://localhost:8787",
        "inputs": {
            "bar_live_server": "Server must be running on the target port",
        },
        "outputs": {
            "browser": "Live 2×4 pie grids with per-team economy state, updated every second",
        },
        "tags": ["bar", "live", "dashboard", "visualization", "dispatch"],
        "commands": [
            {
                "id": "open_default",
                "name": "Open dashboard (Windows)",
                "description": "Open the live dashboard in the default browser.",
                "usage": "start http://localhost:8787",
            },
            {
                "id": "open_api_state",
                "name": "Inspect /api/state (raw JSON)",
                "description": "View the raw JSON snapshot the dashboard polls.",
                "usage": "start http://localhost:8787/api/state",
            },
            {
                "id": "curl_state",
                "name": "Fetch /api/state via curl",
                "description": "Pipe the state snapshot through Python for pretty-printing.",
                "usage": "curl -s http://localhost:8787/api/state | python -m json.tool",
            },
        ],
    },

    # -------------------------------------------------------------------------
    # d  JSONL Stream Inspector
    # -------------------------------------------------------------------------
    {
        "id": "bar_live_jsonl",
        "name": "JSONL Stream Inspector",
        "description": (
            "Inspect the live JSONL file emitted by the widget. Useful for debugging "
            "event schemas, verifying the widget is running, counting events by action "
            "type, or extracting a specific team's economy series. "
            f"Default path: {_JSONL}"
        ),
        "usage": f"python -c \"import json,sys; [print(json.loads(l)['action']) for l in open(r'{_JSONL}') if l.strip()]\"",
        "inputs": {
            _JSONL: "Line-delimited JSON produced by bar_analytic_live.lua",
        },
        "outputs": {
            "stdout": "Filtered / formatted event data",
        },
        "tags": ["bar", "live", "jsonl", "debug", "inspect"],
        "commands": [
            {
                "id": "count_by_action",
                "name": "Count events by action type",
                "description": "Print a frequency table of action types in the JSONL.",
                "usage": (
                    f"python -c \""
                    f"import json,collections; "
                    f"c=collections.Counter(json.loads(l)['action'] for l in open(r'{_JSONL}') if l.strip()); "
                    f"[print(v,'\\t',k) for k,v in c.most_common()]\""
                ),
            },
            {
                "id": "tail_live",
                "name": "Tail JSONL (live, Windows)",
                "description": "Watch new events arrive in real-time (PowerShell equivalent of tail -f).",
                "usage": f"powershell -command \"Get-Content '{_JSONL}' -Wait -Tail 5\"",
            },
            {
                "id": "last_stats",
                "name": "Print latest extra_stat_update per team",
                "description": "Show the most recent economy snapshot for each team.",
                "usage": (
                    f"python -c \""
                    f"import json; "
                    f"last={{}}; "
                    f"[last.update({{json.loads(l)['teamID']: json.loads(l)}}) "
                    f"for l in open(r'{_JSONL}') if l.strip() and json.loads(l).get('action')=='extra_stat_update']; "
                    f"[print(t, json.dumps({{k:round(v,1) for k,v in s.items() if 'Value' in k or k=='totalValue'}}, indent=2)) "
                    f"for t,s in sorted(last.items())]\""
                ),
            },
            {
                "id": "session_info",
                "name": "Print session / map info",
                "description": "Show the most recent session event (map name, spectator mode).",
                "usage": (
                    f"python -c \""
                    f"import json; "
                    f"evs=[json.loads(l) for l in open(r'{_JSONL}') if l.strip()]; "
                    f"s=next((e for e in reversed(evs) if e.get('action')=='session'),None); "
                    f"print(json.dumps(s, indent=2))\""
                ),
            },
        ],
    },

    # -------------------------------------------------------------------------
    # f  Aberrant Event Logger
    # -------------------------------------------------------------------------
    {
        "id": "bar_live_aberrant",
        "name": "Aberrant Event Logger",
        "description": (
            "Detects and logs suspicious economy events in real-time during a live game: "
            "resource spikes consistent with /atm or /give (metal +400m, energy +4000e in "
            "one poll cycle), unexpected income jumps without new mexes, sudden builder or "
            "mex count changes, and worker self-destructs. "
            "For each event, reads the BAR infolog for chat ±30 s (CHATALL, CHATTEAM, "
            "CHATALLYTEAM, CHATSPEC, map tag labels) as potential player-supplied "
            "explanations.  Players attach a written explanation via POST /api/aberrant/explain. "
            "Requires bar_analytic_server running with positions/aberrant_log.py importable."
        ),
        "usage": "GET http://localhost:8787/api/aberrant",
        "inputs": {
            "?team=N":   "Filter to team ID N (default: -1 = all teams)",
            "?limit=N":  "Max events to return (default: 20)",
            "?window=N": "Chat context ± seconds around event (default: 30)",
        },
        "outputs": {
            "GET /api/aberrant":          "JSON: {count, events[{id,type,severity,detail,game_s,team_id,explanation,chat_context}], summary}",
            "POST /api/aberrant/explain": "Attach explanation string to a logged event by id",
        },
        "tags": ["bar", "live", "aberrant", "cheat", "detect", "explain", "dispatch"],
        "commands": [
            {
                "id": "list_all",
                "name": "List all aberrant events",
                "description": "Fetch all recent aberrant events (all teams) with chat context.",
                "usage": "curl -s http://localhost:8787/api/aberrant | python -m json.tool",
            },
            {
                "id": "list_team",
                "name": "List events for a team",
                "description": "Filter aberrant events to a specific team ID.",
                "usage": "curl -s \"http://localhost:8787/api/aberrant?team=0\" | python -m json.tool",
            },
            {
                "id": "explain",
                "name": "Attach explanation to an event",
                "description": "POST an explanation string to a specific event by its id field.",
                "usage": (
                    "curl -s -X POST http://localhost:8787/api/aberrant/explain "
                    "-H \"Content-Type: application/json\" "
                    "-d \"{\\\"id\\\": \\\"<event-id>\\\", \\\"explanation\\\": \\\"used /atm to fix eco balance\\\"}\" "
                    "| python -m json.tool"
                ),
            },
            {
                "id": "wider_window",
                "name": "Wider chat context window",
                "description": "Fetch events with 60-second chat context window instead of default 30.",
                "usage": "curl -s \"http://localhost:8787/api/aberrant?window=60\" | python -m json.tool",
            },
            {
                "id": "smoke_test",
                "name": "Smoke-test detector (no server needed)",
                "description": "Run the aberrant_log CLI self-test to verify detection thresholds.",
                "usage": "cd .. && python positions/aberrant_log.py",
            },
        ],
    },

    # -------------------------------------------------------------------------
    # g  Milestone Trigger Analysis
    # -------------------------------------------------------------------------
    {
        "id": "bar_milestones",
        "name": "Milestone Trigger Analysis",
        "description": (
            "Evaluate an ordered sequence of natural-language milestone triggers "
            "against any BAR replay, using the headless extraction pipeline. "
            "Triggers fire in order; the engine detects SEQUENCE SKIPS where the "
            "next trigger was already completed when the previous one fired (meaning "
            "the build was ahead of the plan, or the sequence is mis-defined). "
            "Supports snapshots of full economy state at any trigger event. "
            "\n\nGame reference: index=1 (last), index=2 (second-to-last), "
            "index=0 (live — limited), name='pattern' (filename match). "
            "\n\nTrigger phrases: '5 mex', '7 mex', 'each medmex', 'TPV 6000', "
            "'T2 factory', 'T2 mex', 'metal income 20', 'first T2 mex'. "
            "\n\nSnapshot: attach 'snapshot at <trigger>' or pass snapshots list to "
            "capture full economy state (TPV, income, metal, energy, unit counts) "
            "at the moment a trigger fires. "
            "\n\nUnit timings are unit_created (construction start). "
            "Build offsets: T1 mex ~23s, medmex ~62s, T2 mex ~75s, T2 factory ~80s. "
            "\n\nCLI: node gex_research/tools/milestone_check.mjs [options] <triggers...> "
            "\nAPI: POST http://localhost:8787/api/milestones"
        ),
        "usage": (
            "node gex_research/tools/milestone_check.mjs "
            "\"5 mex\" \"7 mex\" \"each medmex\" \"TPV 6000\" \"T2 factory\" \"T2 mex\""
        ),
        "inputs": {
            "game":      "{index: 1} | {name: 'pattern'} | {since: 'YYYY-MM-DD'} — which replay",
            "player":    "Player name substring to filter on (default: 'splendi')",
            "triggers":  "Ordered list of milestone phrases (natural language)",
            "snapshots": "Subset of trigger phrases to attach economy snapshots to on fire",
            "window":    "Analysis window in seconds (default 900 = 15 min)",
            "--game N":  "CLI shorthand: 1=last, 2=second-to-last, 0=live",
            "--demo":    "CLI: skip game lookup, use this .sdfz path directly",
            "--verbose": "CLI: print economy snapshot details inline",
        },
        "outputs": {
            "POST /api/milestones":  "JSON: {game, triggers, events, skips, unmatched, window_s}",
            "events[]":              "{triggerId, label, frame, game_s, value, instanceN, snapshot?}",
            "skips[]":               "{type, atGame_s, priorLabel, skipLabel, message}",
            "snapshot (per event)":  "{frame, game_s, metalCurrent, energyCurrent, metalIncome, tpv, unitCounts}",
        },
        "tags": [
            "bar", "milestone", "trigger", "sequence", "replay", "headless",
            "mex", "medmex", "moho", "T2", "TPV", "snapshot", "build-order",
        ],
        "commands": [
            {
                "id": "run_last_game",
                "name": "Run milestones on last solo game",
                "description": (
                    "Evaluate the canonical Legion opening sequence against the most recent "
                    "solo game for [APE]Splendi. reuseExisting=true skips headless if cached."
                ),
                "usage": (
                    "cd gex_research && node tools/milestone_check.mjs "
                    "\"5 mex\" \"7 mex\" \"each medmex\" \"TPV 6000\" \"T2 factory\" \"T2 mex\""
                ),
            },
            {
                "id": "run_with_snapshot",
                "name": "Run with snapshot at T2 mex",
                "description": "Same as above but captures full economy state when first T2 mex fires.",
                "usage": (
                    "cd gex_research && node tools/milestone_check.mjs "
                    "--snapshots \"T2 mex\" --verbose "
                    "\"5 mex\" \"7 mex\" \"each medmex\" \"TPV 6000\" \"T2 factory\" \"T2 mex\""
                ),
            },
            {
                "id": "run_nth_game",
                "name": "Run milestones on Nth-to-last game",
                "description": "Use --game N (e.g. --game 2 = second-to-last solo game).",
                "usage": (
                    "cd gex_research && node tools/milestone_check.mjs "
                    "--game 2 \"5 mex\" \"7 mex\" \"each medmex\" \"T2 factory\" \"T2 mex\""
                ),
            },
            {
                "id": "api_call",
                "name": "API: POST milestones",
                "description": (
                    "Call the live server API. game.index=1 = last game, =2 = second-to-last. "
                    "snapshots list attaches economy state to those trigger events."
                ),
                "usage": (
                    "curl -s -X POST http://localhost:8787/api/milestones "
                    "-H 'Content-Type: application/json' "
                    "-d '{\"game\":{\"index\":1},\"player\":\"splendi\","
                    "\"triggers\":[\"5 mex\",\"7 mex\",\"each medmex\","
                    "\"TPV 6000\",\"T2 factory\",\"T2 mex\"],"
                    "\"snapshots\":[\"T2 mex\"]}'"
                    " | python -m json.tool"
                ),
            },
            {
                "id": "api_last_or_live",
                "name": "API: live game (index 0) or last (index 1)",
                "description": "index=0 targets the current live game (limited support); index=1 targets last demo.",
                "usage": (
                    "curl -s -X POST http://localhost:8787/api/milestones "
                    "-H 'Content-Type: application/json' "
                    "-d '{\"game\":{\"index\":0},\"triggers\":[\"5 mex\",\"7 mex\"]}' "
                    "| python -m json.tool"
                ),
            },
        ],
    },

    # -------------------------------------------------------------------------
    # e  Classifier Triage
    # -------------------------------------------------------------------------
    {
        "id": "bar_live_classifier",
        "name": "Classifier Triage",
        "description": (
            "Manage the live widget's unit classifier (bar_analytic_live.lua classify()) "
            "and its canonical counterpart (../process/lib/classify.mjs). "
            "When a unit lands in the 'other' bucket, it means it has no weapon, no build "
            "power, no eco output, no intel range, and isn't a factory or commander. "
            "Triage list: live/others_to_be_classified.md. "
            "Precedence: commander → infrastructure(factory) → support(seed names) → "
            "economy → build_power → military/defense (weapon or intel) → other. "
            "After adding a rule: update BOTH classifiers (lua + mjs) and move the def "
            "to Resolved in others_to_be_classified.md. "
            "Widget classification changes only take effect on the NEXT game start."
        ),
        "module": "others_to_be_classified.md",
        "usage": f"grep '\"bucket\":\"other\"' \"{_JSONL}\" | python live/bar_analytic_server.py",
        "inputs": {
            "others_to_be_classified.md": "Living triage list of defs in the 'other' bucket",
            "bar_analytic_live.lua":      "Widget classifier (classify() function, SUPPORT_NAMES list)",
            "../process/lib/classify.mjs": "Canonical batch-pipeline classifier (keep in sync)",
        },
        "outputs": {
            "bar_analytic_live.lua (updated)":      "Unit routed to its correct bucket",
            "others_to_be_classified.md (updated)": "Def moved from Pending to Resolved",
        },
        "tags": ["bar", "live", "classifier", "triage", "other", "bucket"],
        "commands": [
            {
                "id": "list_other",
                "name": "List all 'other' defs from JSONL",
                "description": "Extract every unit_def event with bucket='other', sorted by value.",
                "usage": (
                    f"python -c \""
                    f"import json,sys,collections; "
                    f"seen={{}}; "
                    f"[seen.update({{json.loads(l)['defName']:(json.loads(l).get('name'),round(json.loads(l).get('value',0),1))}}) "
                    f"for l in open(r'{_JSONL}') if l.strip() and json.loads(l).get('action')=='unit_def' and json.loads(l).get('bucket')=='other']; "
                    f"[print(f'{{v:>8}} {{dn:<22}} {{hn}}') for dn,(hn,v) in sorted(seen.items(),key=lambda x:-x[1][1])]\""
                ),
            },
            {
                "id": "open_triage",
                "name": "Open triage document",
                "description": "Open others_to_be_classified.md in the default editor.",
                "usage": "start live\\others_to_be_classified.md",
            },
            {
                "id": "lookup_def",
                "name": "Look up a specific def in JSONL",
                "description": "Find all unit_def events for a specific defName (e.g. armdf, armfort).",
                "usage": (
                    f"python -c \""
                    f"import json; "
                    f"[print(json.dumps(json.loads(l), indent=2)) "
                    f"for l in open(r'{_JSONL}') if l.strip() "
                    f"and json.loads(l).get('action')=='unit_def' "
                    f"and json.loads(l).get('defName')=='<defName>']\""
                ),
            },
        ],
    },

    # -------------------------------------------------------------------------
    # h  Offline Replay Analyzer  (replay_jsonl.py — no BAR needed)
    # -------------------------------------------------------------------------
    {
        "id": "bar_live_replay",
        "name": "Offline Replay Analyzer",
        "description": (
            "Replay any bar_analytic_live JSONL through the server's Live pipeline (no BAR, "
            "no server) to validate / inspect a past game: per-minute snapshot recall, "
            "minute-to-minute compare, eco PROJECTION (project minute N forward, grade vs "
            "actual N+1), resource sharing (donation vs overflow, X > Y, with ezTax 'taxed'), "
            "and opening BUILD classification (mex/solar/wind cadence + phase2 + bp split; "
            "ARM/COR/Legion incl. medmex). USE THIS instead of hand-writing throwaway scripts. "
            f"Default --path: {_JSONL}"
        ),
        "module": "replay_jsonl.py",
        "usage": "cd live && python replay_jsonl.py [--path FILE] [ACTION] [--json]",
        "inputs": {
            "--path FILE":  f"JSONL to replay (default: {_JSONL})",
            "--minutes":    "list captured game-minutes",
            "--snapshot N": "dump full recalled state at minute N",
            "--compare N":  "per-team delta minute N -> N+1",
            "--project N":  "project eco from N, grade vs actual N+1 (needs positions/ analysis)",
            "--shares":     "energy/metal donation+overflow flows (X > Y, taxed)",
            "--build [N]":  "classify each team's opening build (optional teamID filter)",
            "--json":       "raw JSON instead of formatted tables",
        },
        "outputs": {
            "stdout":           "formatted analysis (or JSON with --json)",
            "/api/snapshots":   "(live server) recallable minutes index",
            "/api/snapshot?minute=N": "(live) full state at minute N",
            "/api/compare?minute=N":  "(live) minute N->N+1 delta",
            "/api/project?minute=N":  "(live) projection vs actual N+1",
            "/api/shares":      "(live) donation/overflow flows X > Y",
            "/api/build":       "(live) per-team opening build classification",
        },
        "tags": ["bar", "live", "replay", "offline", "snapshot", "project", "shares",
                 "build", "classify", "legion", "dispatch"],
        "commands": [
            {
                "id": "build_all",
                "name": "Classify every team's opening",
                "description": "Mex/solar/wind cadence, label, factory time, and build-power split per team.",
                "usage": "cd live && python replay_jsonl.py --build",
            },
            {
                "id": "shares",
                "name": "Resource donation / overflow flows",
                "description": "Per-pair X > Y energy/metal: donation (chat) vs overflow (auto), with ezTax taxed.",
                "usage": "cd live && python replay_jsonl.py --shares",
            },
            {
                "id": "project_minute",
                "name": "Project a minute & grade vs actual",
                "description": "From minute N: best build options, passive baseline, realized deltas, verdict.",
                "usage": "cd live && python replay_jsonl.py --project 7",
            },
            {
                "id": "compare_minute",
                "name": "Minute-to-minute compare",
                "description": "Per-team economy delta from minute N to N+1.",
                "usage": "cd live && python replay_jsonl.py --compare 5",
            },
            {
                "id": "recall_minute",
                "name": "Recall full state at a minute",
                "description": "Dump the full per-team snapshot recalled at minute N.",
                "usage": "cd live && python replay_jsonl.py --snapshot 8 --json",
            },
            {
                "id": "custom_jsonl",
                "name": "Analyze a saved JSONL",
                "description": "Run any action against a JSONL recording other than the live default.",
                "usage": "cd live && python replay_jsonl.py --path <file.jsonl> --build",
            },
        ],
    },
]

if __name__ == "__main__":
    run(LOCAL_CAPABILITIES, root_dir=__file__)

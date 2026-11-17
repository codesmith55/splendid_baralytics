#!/usr/bin/env python3
"""
gex_research/ai_processes/capabilities.py
-----------------------------------------------------------------------------
Project capability registry for gex_research — BAR replay analytics pipeline.

This file is the EXTENSION.  Add and remove LOCAL_CAPABILITIES here.
The framework (navigation, display, CLI plumbing) lives in capabilities_core.py
-- only edit that file when the protocol changes, not when adding capabilities.

Framework:   ../../../ai_processes/capabilities_core.py  (canonical peer)
             capabilities_core.py  (local sync copy fallback)
Sync note:   when the core protocol changes, copy capabilities_core.py from
             GitHub/ai_processes/ to this folder; this file stays untouched.

SHORTCUT: `pc` is an alias for `python capabilities.py`  (see pc.bat / pc.sh)

Quick dispatch:
  pc info a          BAR Replay Metrics Runner (run-001 or headless)
  pc info h          BAR New Run (workflow for a fresh demo)
  pc run  a b        command to run the economy composition run (run-001)
  pc run  h          command to set up and run against a new demo
  pc filter dispatch capabilities ready for unattended dispatch

Pipeline overview:
  pick demo (.sdfz)
    -> [spring-headless + gex.lua]  (only if not already extracted)
    -> actions.json  (line-delimited JSON, ~19K events / 13-min game)
    -> parse  ->  context (roster, start pos, ally map)
    ->  metric.compute()  ->  situation.apply()
    -> output/run-NNN/{report.html, metrics.json, situations.json, context.json}
-----------------------------------------------------------------------------
Auto-discovery: any .py file in this folder that declares CAPABILITY = {...}
at module scope is picked up automatically -- no registration needed here.
-----------------------------------------------------------------------------
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List

# ---------------------------------------------------------------------------
# Import base framework.
# PC_BASE_DIR is set by pc.bat / pc.sh to the canonical peer location
# (GitHub/ai_processes/) when available.  Falls back to the local sync copy
# in this directory for standalone use.
# ---------------------------------------------------------------------------
_base = os.environ.get(
    "PC_BASE_DIR",
    os.path.dirname(os.path.abspath(__file__)),   # local sync copy fallback
)
sys.path.insert(0, os.path.abspath(_base))
from capabilities_core import run  # noqa: E402

# -----------------------------------------------------------------------------
# Capability registry for gex_research
# -----------------------------------------------------------------------------

LOCAL_CAPABILITIES: List[Dict] = [
    # -------------------------------------------------------------------------
    # a  BAR Replay Metrics Runner  (primary entry point)
    # -------------------------------------------------------------------------
    {
        "id": "bar_run_metric",
        "name": "BAR Replay Metrics Runner",
        "description": (
            "Execute a full metrics run: obtain actions.json (reuse pre-extracted or replay "
            "headlessly), parse events, build context (roster + start positions + ally map), "
            "compute per-team economy composition over time, apply situations "
            "(per_user + mirror_by_start_position), and write "
            "output/<run>/{report.html, metrics.json, situations.json, context.json}. "
            "Accepts a run config by short id, keyword, filename, or omit for the default."
        ),
        "module": "process/run.mjs",
        "usage": "cd gex_research && node process/run.mjs [<run>]",
        "inputs": {
            "<run>":               "Short id '001', keyword 'economy', full path, or omit for default",
            "metrics/runs/*.json": "Run config: which metrics + situations over which replay/actions",
            "input.source":        "'actions' (reuse sample_output/actions.json) or 'headless' (replay demo)",
        },
        "outputs": {
            "output/<run>/report.html":     "Self-contained HTML report (inline SVG economy charts + mirror pairs)",
            "output/<run>/metrics.json":    "Per-team economy time series (one sample per 450 frames)",
            "output/<run>/situations.json": "per_user + mirror_by_start_position results",
            "output/<run>/context.json":    "Roster, start positions, ally map, replay metadata",
        },
        "tags": ["bar", "gex", "metrics", "replay", "economy", "dispatch"],
        "commands": [
            {
                "id": "default",
                "name": "Run Default",
                "description": "Run the lowest-numbered run config (run-001 economy composition, pre-extracted actions.json).",
                "usage": "cd gex_research && node process/run.mjs",
            },
            {
                "id": "run_001",
                "name": "Economy Composition (run-001)",
                "description": (
                    "Per-user economy composition % over time on the pre-extracted 8v8 sample game. "
                    "Uses sample_output/actions.json (no headless needed). "
                    "Mirror pairs: 8 pairs, gap < 100 elmos. "
                    "Outputs to output/run-001/."
                ),
                "usage": "cd gex_research && node process/run.mjs 001",
            },
            {
                "id": "run_002",
                "name": "Economy Composition — Headless (run-002)",
                "description": (
                    "Same metric/situations as run-001, but replays a new .sdfz headlessly "
                    "via spring-headless.exe + gex.lua (~137 s / 13-min game). "
                    "Machine must stay on + logged in. Outputs to output/run-002/."
                ),
                "usage": "cd gex_research && node process/run.mjs 002",
            },
            {
                "id": "custom_run",
                "name": "Run a Custom Config",
                "description": "Run any run config by full path (e.g. a config you created with bar_new_run).",
                "usage": "cd gex_research && node process/run.mjs metrics/runs/<your-run>.json",
            },
        ],
    },

    # -------------------------------------------------------------------------
    # b  BAR Metric Registrar
    # -------------------------------------------------------------------------
    {
        "id": "bar_add_metric",
        "name": "BAR Metric Registrar",
        "description": (
            "Register a NEW metric from a criteria JSON: validates the schema, appends a draft "
            "entry to metrics/catalog.json (the master list), and scaffolds "
            "process/lib/metrics/<id>.mjs with a compute() stub. "
            "After running: implement compute(), flip status draft→active, then add the id to "
            "a run config to use it. Use metrics/criteria-examples/metric.example.json as template."
        ),
        "module": "process/addMetric.mjs",
        "usage": "cd gex_research && node process/addMetric.mjs <criteria.json>",
        "inputs": {
            "<criteria.json>": "New-metric criteria (copy + edit metrics/criteria-examples/metric.example.json)",
        },
        "outputs": {
            "metrics/catalog.json":         "Draft entry appended (master metric list — do not hand-edit)",
            "process/lib/metrics/<id>.mjs": "Scaffolded compute() module stub — implement this",
        },
        "tags": ["bar", "gex", "metrics", "authoring", "extend"],
    },

    # -------------------------------------------------------------------------
    # c  BAR Situation Registrar
    # -------------------------------------------------------------------------
    {
        "id": "bar_add_situation",
        "name": "BAR Situation Registrar",
        "description": (
            "Register a NEW situation (a way to slice/pair/compare a metric's output): "
            "appends to metrics/situations.json and scaffolds "
            "process/lib/situations/<id>.mjs with an apply() stub. "
            "After running: implement apply(), flip status draft→active, add the id to a run config. "
            "Use metrics/criteria-examples/situation.example.json as template. "
            "Current active situations: per_user, mirror_by_start_position."
        ),
        "module": "process/addSituation.mjs",
        "usage": "cd gex_research && node process/addSituation.mjs <criteria.json>",
        "inputs": {
            "<criteria.json>": "New-situation criteria (copy + edit metrics/criteria-examples/situation.example.json)",
        },
        "outputs": {
            "metrics/situations.json":          "Draft entry appended (master situation list — do not hand-edit)",
            "process/lib/situations/<id>.mjs":  "Scaffolded apply() module stub — implement this",
        },
        "tags": ["bar", "gex", "situations", "authoring", "extend"],
    },

    # -------------------------------------------------------------------------
    # d  BAR Headless Extractor  (low-level; normally called via bar_run_metric)
    # -------------------------------------------------------------------------
    {
        "id": "bar_headless_extract",
        "name": "BAR Headless Extractor",
        "description": (
            "Low-level: replay a BAR .sdfz headlessly using the local BAR install + "
            "the vendored gex.lua widget, producing a line-delimited actions.json "
            "(per-team economy, damage, unit lifecycle, positions). "
            "Normally invoked automatically via bar_run_metric when input.source='headless'; "
            "run standalone to pre-extract actions.json for reuse across multiple runs. "
            "Requires BAR installed at the hardcoded engine path. ~137 s / 13-min game."
        ),
        "module": "process/lib/headless.mjs",
        "usage": (
            "cd gex_research && node -e \""
            "import('./process/lib/headless.mjs')"
            ".then(m=>m.runHeadless({demoFile:'<demo.sdfz>',vendorDir:'vendor'}))"
            ".then(p=>console.log('actions.json at:',p))"
            "\""
        ),
        "inputs": {
            "demoFile":  "Path to a BAR .sdfz demo file",
            "engine":    "Engine version string (default: recoil_2025.06.24 — must match demo)",
            "vendorDir": "Path to vendor/ directory containing gex.lua + BYAR.lua",
        },
        "outputs": {
            "actions.json": (
                "Line-delimited gex event log in an isolated temp write-dir "
                "(unit_def, unit_created, unit_killed, team_stats, extra_stat_update, ...)"
            ),
        },
        "tags": ["bar", "gex", "headless", "replay", "extract", "spring"],
    },

    # -------------------------------------------------------------------------
    # e  BAR Demo Roster Parser
    # -------------------------------------------------------------------------
    {
        "id": "bar_demo_roster",
        "name": "BAR Demo Roster Parser",
        "description": (
            "Extract the full player roster from a BAR .sdfz demo header via the "
            "vendored sdfz-demo-parser npm binding: userId, name, faction, allyTeam, "
            "start position, skill. Used to attach player identity to the per-team "
            "engine stats — without this, teams show by teamID only. "
            "Writes a .roster.json file (cached next to the demo) for reuse."
        ),
        "module": "tools/demoparser/parse.mjs",
        "usage": "cd gex_research && node tools/demoparser/parse.mjs <demo.sdfz> [out.roster.json]",
        "inputs": {
            "<demo.sdfz>": "Path to a BAR demo file",
            "[out.json]":  "Optional output path (default: print to stdout)",
        },
        "outputs": {
            "roster JSON": (
                "{ gameId, map, engine, winningAllyTeamIds, players: "
                "[{ teamId, userId, name, faction, allyTeamId, startPos, skill }] }"
            ),
        },
        "tags": ["bar", "gex", "roster", "demo", "parse"],
    },

    # -------------------------------------------------------------------------
    # f  BAR Economy Split Formatter
    # -------------------------------------------------------------------------
    {
        "id": "bar_split",
        "name": "BAR Economy Split Formatter",
        "description": (
            "Print any player's complete economy composition as a one-liner (topline) or "
            "full per-bucket breakdown (breakout) for any point in the game — a specific "
            "second, 'peak', or 'final'. Reads from the most-recent run output by default. "
            "Topline: 'Name @ Xs:  BP:7.0%  Eco:34.1%  Inf:8.8%  Mil:37.8%  Sto:10.1%  Oth:2.1%  [69k]'. "
            "Breakout: one aligned line per bucket with both % and absolute value."
        ),
        "module": "tools/split.mjs",
        "usage": "cd gex_research && node tools/split.mjs [run] [time] [--breakout] [--filter <name>]",
        "inputs": {
            "[run]":           "Run id: '002', 'run-002', or omit for the most-recent output/run-* directory",
            "[time]":          "Time spec: seconds (e.g. 600) | 'peak' | 'final'  (default: peak)",
            "--breakout":      "Multi-line per-bucket output with aligned % and absolute values",
            "--filter <name>": "Show only players whose name contains this substring (case-insensitive)",
        },
        "outputs": {
            "stdout": "Formatted economy splits, sorted by ally-team then teamID",
        },
        "tags": ["bar", "gex", "metrics", "split", "format", "query"],
        "commands": [
            {
                "id": "all_peak",
                "name": "All Players at Peak",
                "description": "One-liner for every player at their individual peak economy.",
                "usage": "cd gex_research && node tools/split.mjs",
            },
            {
                "id": "at_time",
                "name": "All Players at Time",
                "description": "One-liner for every player at a given game-second (nearest 15 s sample).",
                "usage": "cd gex_research && node tools/split.mjs 002 600",
            },
            {
                "id": "breakout_peak",
                "name": "Full Breakout at Peak",
                "description": "Per-bucket breakdown with absolute values for all players at their peak.",
                "usage": "cd gex_research && node tools/split.mjs 002 peak --breakout",
            },
            {
                "id": "player_at_time",
                "name": "Single Player at Time",
                "description": "One player's topline or breakout, filtered by name substring.",
                "usage": "cd gex_research && node tools/split.mjs 002 600 --breakout --filter <name>",
            },
        ],
    },

    # -------------------------------------------------------------------------
    # g  BAR Self-Reclaim Metric
    # -------------------------------------------------------------------------
    {
        "id": "bar_self_reclaim",
        "name": "BAR Self-Reclaim Metric",
        "description": (
            "Tracks the cumulative value of own units reclaimed over game time, per team, "
            "split by category: Eco (energy structures, mexes), Mil (living combat units eaten for "
            "metal), Inf (factories), BP (builders), Other. "
            "Detection: unit_killed where attackerTeam === teamID AND weaponDefID === -12 "
            "(Spring/Recoil's internal reclaim-action constant). "
            "Value = metalCost + energyCost/70, same formula as economy_composition. "
            "Key insight: economy_composition credits a solar as +~155 when built and -~155 when "
            "reclaimed — the self_reclaim metric surfaces that churn total separately so you can "
            "compare 'live economy' vs 'cycled-through economy'. "
            "Metric id: self_reclaim — included in run-002 config alongside economy_composition. "
            "Output in metrics.json under key 'self_reclaim': series, final, eventCount, events. "
            "HTML report shows a summary table sorted by total churn (players with zero are hidden)."
        ),
        "module": "process/lib/metrics/self_reclaim.mjs",
        "usage": "cd gex_research && node process/run.mjs 002  # self_reclaim runs as part of run-002",
        "inputs": {
            "unit_def events":    "Unit metalCost/energyCost for value calculation",
            "unit_killed events": "Filtered to weaponDefID=-12 AND attackerTeam===teamID",
        },
        "outputs": {
            "metrics.json['self_reclaim']":           "Per-team cumulative series + final totals + raw event list",
            "report.html (Self-reclaim section)":     "Summary table: Total | Eco | Mil | BP | Inf | Other | Evts per player",
        },
        "tags": ["bar", "gex", "metrics", "self_reclaim", "churn", "reclaim"],
        "commands": [
            {
                "id": "run_002",
                "name": "Run Self-Reclaim (run-002)",
                "description": "Execute run-002 which computes both economy_composition and self_reclaim.",
                "usage": "cd gex_research && node process/run.mjs 002",
            },
            {
                "id": "print_totals",
                "name": "Print Self-Reclaim Totals",
                "description": "Print per-player self-reclaim totals sorted by total churn (largest first).",
                "usage": (
                    "cd gex_research && node -e \""
                    "const m=require('./output/run-002/metrics.json');"
                    "const sr=m.self_reclaim;"
                    "const ctx=require('./output/run-002/context.json');"
                    "Object.entries(sr.final).sort((a,b)=>b[1].total-a[1].total)"
                    ".forEach(([t,s])=>console.log((ctx.roster[t]?.name??'t'+t).padEnd(24),s.total,'|',JSON.stringify(s.value)))\""
                ),
            },
            {
                "id": "print_events",
                "name": "Print Self-Reclaim Events for a Team",
                "description": "List every self-reclaim event for a given teamID (e.g. 8 = [APE]Splendi in run-002).",
                "usage": (
                    "cd gex_research && node -e \""
                    "const m=require('./output/run-002/metrics.json');"
                    "m.self_reclaim.events['8'].forEach(e=>console.log(e.second+'s',e.defName,e.bucket,'+'+e.value.toFixed(1)))\""
                ),
            },
        ],
    },

    # -------------------------------------------------------------------------
    # h  BAR Metric & Situation Catalog
    # -------------------------------------------------------------------------
    {
        "id": "bar_catalog",
        "name": "BAR Metric & Situation Catalog",
        "description": (
            "Inspect the master lists of every metric and situation ever created. "
            "Currently active — metrics: economy_composition; "
            "situations: per_user, mirror_by_start_position. "
            "Reference these ids in a run config's metrics[] / situations[] arrays. "
            "Do not hand-edit catalog.json or situations.json; use bar_add_metric / "
            "bar_add_situation to append entries."
        ),
        "module": "metrics/catalog.json",
        "usage": "cd gex_research && cat metrics/catalog.json metrics/situations.json",
        "inputs": {},
        "outputs": {
            "metrics/catalog.json":    "Master metric list (id, title, description, status, granularity)",
            "metrics/situations.json": "Master situation list (id, title, description, status)",
        },
        "tags": ["bar", "gex", "catalog", "registry", "docs"],
        "commands": [
            {
                "id": "metrics",
                "name": "List Metrics",
                "description": "Print every metric id + title + status from the master catalog.",
                "usage": "cd gex_research && node -e \"const c=require('./metrics/catalog.json'); c.metrics.forEach(m=>console.log(m.status, m.id, '-', m.title))\"",
            },
            {
                "id": "situations",
                "name": "List Situations",
                "description": "Print every situation id + title + status.",
                "usage": "cd gex_research && node -e \"const s=require('./metrics/situations.json'); s.situations.forEach(s=>console.log(s.status, s.id, '-', s.title))\"",
            },
            {
                "id": "list_runs",
                "name": "List Run Configs",
                "description": "Show all available run configs in metrics/runs/.",
                "usage": "ls gex_research/metrics/runs/",
            },
        ],
    },

    # -------------------------------------------------------------------------
    # g  BAR View Report  (daily workflow — open a completed run's HTML report)
    # -------------------------------------------------------------------------
    {
        "id": "bar_view_report",
        "name": "BAR View Report",
        "description": (
            "Open a completed run's self-contained HTML report in the browser. "
            "The report shows per-user economy composition charts (inline SVG), "
            "the mirror-start-position pairs with delta breakdowns, and the full "
            "roster with faction + skill. No server required — it's a single static file. "
            "All output files (metrics.json, situations.json, context.json) live in the "
            "same directory and can be inspected alongside."
        ),
        "usage": "start gex_research/output/run-001/report.html   # Windows\nopen  gex_research/output/run-001/report.html   # macOS/Linux",
        "inputs": {
            "output/<run>/": "Completed run directory (produced by bar_run_metric)",
        },
        "outputs": {
            "browser": "Economy composition charts, mirror pairs, roster view",
        },
        "tags": ["bar", "gex", "report", "visualization", "dispatch"],
        "commands": [
            {
                "id": "run_001",
                "name": "Open run-001 Report",
                "description": "Open the economy composition report for the pre-extracted 8v8 game.",
                "usage": "start gex_research/output/run-001/report.html",
            },
            {
                "id": "run_002",
                "name": "Open run-002 Report",
                "description": "Open the economy composition report for the headless-replayed game.",
                "usage": "start gex_research/output/run-002/report.html",
            },
            {
                "id": "open_dir",
                "name": "Open Output Directory",
                "description": "Open the output directory to browse all run outputs.",
                "usage": "start gex_research/output/",
            },
        ],
    },

    # -------------------------------------------------------------------------
    # h  BAR New Run  (workflow for running a fresh demo)
    # -------------------------------------------------------------------------
    {
        "id": "bar_new_run",
        "name": "BAR New Run (workflow)",
        "description": (
            "Full workflow for processing a brand-new BAR demo: copy a run config template, "
            "set the demo path and output directory, then run. "
            "The pipeline handles the rest: headless replay (~137 s/13-min game) → "
            "parse → economy metrics → mirror pairs → HTML report. "
            "Machine must stay on + logged in during headless replay. "
            "For pre-extracted actions.json (skip headless), set input.source='actions' instead."
        ),
        "usage": (
            "# 1. Copy a run config\n"
            "copy metrics\\runs\\run-001-economy-composition.json metrics\\runs\\run-NNN-<title>.json\n"
            "\n"
            "# 2. Edit the copy — set at minimum:\n"
            "#      runId, title\n"
            "#      input.source: 'headless'  (or 'actions' to reuse an existing actions.json)\n"
            "#      input.demoFile: 'C:/path/to/game.sdfz'  (if source=headless)\n"
            "#      output.dir: '../../output/run-NNN'\n"
            "\n"
            "# 3. Run it\n"
            "cd gex_research && node process/run.mjs metrics/runs/run-NNN-<title>.json"
        ),
        "inputs": {
            "demo.sdfz":         "Path to the BAR demo file to replay",
            "run-config (copy)": "Edited copy of metrics/runs/run-001-economy-composition.json",
        },
        "outputs": {
            "output/run-NNN/":        "report.html + metrics.json + situations.json + context.json",
            "actions.json (temp)":    "Line-delimited event log in isolated temp dir (auto-cleaned)",
        },
        "tags": ["bar", "gex", "workflow", "headless", "dispatch"],
        "commands": [
            {
                "id": "headless_demo",
                "name": "Headless — new demo",
                "description": (
                    "Process a new .sdfz: replay headlessly, extract actions, run economy metrics. "
                    "~137 s for a 13-min game. Machine must stay on."
                ),
                "usage": (
                    "copy metrics\\runs\\run-001-economy-composition.json metrics\\runs\\run-NNN-<title>.json\n"
                    "# edit: input.source='headless', input.demoFile='<path>', output.dir='../../output/run-NNN'\n"
                    "cd gex_research && node process/run.mjs metrics/runs/run-NNN-<title>.json"
                ),
            },
            {
                "id": "from_actions",
                "name": "From existing actions.json",
                "description": (
                    "Run metrics over a pre-extracted actions.json (no headless replay needed). "
                    "Use when you already have the event log and want to try different metrics/situations."
                ),
                "usage": (
                    "copy metrics\\runs\\run-001-economy-composition.json metrics\\runs\\run-NNN-<title>.json\n"
                    "# edit: input.source='actions', input.actionsFile='<path/to/actions.json>', output.dir='../../output/run-NNN'\n"
                    "cd gex_research && node process/run.mjs metrics/runs/run-NNN-<title>.json"
                ),
            },
        ],
    },
]

if __name__ == "__main__":
    run(LOCAL_CAPABILITIES, root_dir=__file__)

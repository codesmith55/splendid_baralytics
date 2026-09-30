#!/usr/bin/env python3
"""
bar_analytics/capabilities.py
-----------------------------------------------------------------------------
BAR build analytics capabilities -- local extension of capabilities_core.

Extends the base framework from ai_processes/ without copying it.
Run via: pc  (from this directory)  OR  python capabilities.py

To add a new capability: append a dict to LOCAL_CAPABILITIES below.
Any .py file in this folder that declares CAPABILITY = {...} at module scope
is also auto-discovered -- no manual registration needed.

Framework:   ../ai_processes/capabilities_core.py   (do not edit here)
Sync note:   when capabilities_core.py changes, update it in ai_processes/
             only -- this file is untouched on core syncs.
-----------------------------------------------------------------------------
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List

# ---------------------------------------------------------------------------
# Import base framework from ai_processes/
# PC_BASE_DIR is set by pc.bat / pc.sh to the ai_processes/ directory.
# Falls back to a relative path so the file also works when run directly.
# ---------------------------------------------------------------------------
_base = os.environ.get(
    "PC_BASE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ai_processes"),
)
sys.path.insert(0, os.path.abspath(_base))
from capabilities_core import run  # noqa: E402

# ---------------------------------------------------------------------------
# BAR build analytics capabilities
# ---------------------------------------------------------------------------

LOCAL_CAPABILITIES: List[Dict] = [
    {
        "id": "bar_build_explorer",
        "name": "BAR Build Explorer",
        "description": (
            "Interactive HTML dashboard for browsing BAR opening builds. "
            "Visualises each build's branch tree, metal/energy curves, and "
            "break-even timeline against a target composition. Reads from "
            "builds.json -- no server required, open in any browser."
        ),
        "usage": "start bar_analytics/build_explorer.html  # Windows\n"
                 "open  bar_analytics/build_explorer.html  # macOS/Linux",
        "inputs": {
            "builds.json": "Pre-generated simulation data (regenerate with build_export.py)",
        },
        "outputs": {
            "dashboard": "Interactive branch timeline + break-even chart in browser",
        },
        "tags": ["bar", "builds", "dashboard", "visualization"],
    },
    {
        "id": "bar_build_export",
        "name": "BAR Build Export",
        "description": (
            "Simulate every branch of every build and write the results to "
            "builds.json for the dashboard. Re-run this after editing builds "
            "with build_db.py to refresh the simulation data."
        ),
        "usage": "python bar_analytics/build_export.py",
        "inputs": {
            "builds.db": "SQLite build definitions (from build_db.py, via %TEMP%/bar_builds.db)",
        },
        "outputs": {
            "builds.json": "Simulated branch timelines, event lists, break-even data",
        },
        "tags": ["bar", "builds", "simulation", "export"],
    },
    {
        "id": "bar_build_db",
        "name": "BAR Build DB (editor)",
        "description": (
            "Python API for authoring and forking BAR opening builds. "
            "Works in a temp SQLite DB (%TEMP%/bar_builds.db) and snapshots "
            "to bar_analytics/builds.db via save(). Run build_export.py "
            "afterward to refresh the dashboard JSON."
        ),
        "usage": "python -c \"from bar_analytics.build_db import BuildDB; db = BuildDB()\"",
        "inputs": {
            "builds.db": "Workspace snapshot (auto-created in temp on first run)",
        },
        "outputs": {
            "builds.db":  "Updated workspace snapshot after save()",
            "builds.json": "After running build_export.py",
        },
        "tags": ["bar", "builds", "authoring", "sqlite"],
    },
    {
        "id": "bar_eco_calculator",
        "name": "BAR Economics Calculator",
        "description": (
            "Spreadsheet-style economics analysis for BAR unit compositions. "
            "Computes metal/energy cost curves, income projections, and "
            "build efficiency metrics from the CSV data files."
        ),
        "usage": "python bar_analytics/eco_calculator.py",
        "inputs": {
            "bar_eco_table.csv":     "Unit economics table",
            "Combined_Bar_Stats.csv": "Combined unit statistics",
        },
        "outputs": {
            "stdout": "Formatted economics report",
        },
        "tags": ["bar", "economics", "analysis"],
    },
]

if __name__ == "__main__":
    run(LOCAL_CAPABILITIES, root_dir=__file__)

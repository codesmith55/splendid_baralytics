#!/usr/bin/env bash
# pc.sh — shortcut for "python capabilities.py" (bar_analytic_live sub-project)
#
# Upward search from CWD; falls back to this script's directory.
# Source for a persistent `pc` function or run directly.
#
# Usage:
#   pc                    interactive menu
#   pc info a             Live Analytics Server detail
#   pc run  a             run command for capability a
#   pc --spec --pretty    full JSON spec

_PC_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_pc_find_caps() {
    local dir="$PWD"
    while true; do
        if [[ -f "$dir/capabilities.py" ]]; then
            echo "$dir/capabilities.py"; return 0
        fi
        local parent; parent="$(dirname "$dir")"
        [[ "$parent" == "$dir" ]] && break
        dir="$parent"
    done
    echo "$_PC_SCRIPT_DIR/capabilities.py"
}

_pc_base_dir() {
    local peer="$HOME/Documents/GitHub/ai_processes"
    if [[ -f "$peer/capabilities_core.py" ]]; then echo "$peer"
    else echo "$_PC_SCRIPT_DIR"; fi
}

pc() {
    local cap_file; cap_file="$(_pc_find_caps)"
    PC_CALLED_FROM="$PWD" PC_BASE_DIR="$(_pc_base_dir)" python "$cap_file" "$@"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then pc "$@"; fi

#!/usr/bin/env bash
# pc.sh — shortcut for "python capabilities.py"
#
# UPWARD SEARCH: searches CWD and each parent directory for a capabilities.py.
# Falls back to the capabilities.py next to this script if nothing is found.
#
# Two ways to use:
#
#   1. Run directly (from any directory):
#        bash /path/to/ai_processes/pc.sh info a
#
#   2. Source for a persistent `pc` function (recommended):
#        source /path/to/ai_processes/pc.sh
#        pc .                   # navigation context + menu
#        pc info c b            # sub-command b of capability c
#        pc run  g c            # run-command for sub c of cap g
#        pc --spec --pretty     # full JSON spec
#
# Usage:
#   pc                      interactive menu (auto-banner if resolved from parent)
#   pc .                    navigation context view, then menu
#   pc info <letter>        capability detail (letter, id, or integer)
#   pc info <letter> <letter>  sub-command detail
#   pc run  <letter> <letter>  sub-command run-command
#   pc filter <tag>         capabilities by tag
#   pc tags                 tag index
#   pc --spec --pretty      full JSON spec (AI/agent-friendly)

# Absolute path to the directory containing this script.
_PC_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Walk upward from CWD looking for a capabilities.py.
# Echos the resolved path; falls back to the script's own capabilities.py.
_pc_find_caps() {
    local dir="$PWD"
    while true; do
        if [[ -f "$dir/capabilities.py" ]]; then
            echo "$dir/capabilities.py"
            return 0
        fi
        local parent
        parent="$(dirname "$dir")"
        # Stop when dirname no longer changes (filesystem root reached)
        [[ "$parent" == "$dir" ]] && break
        dir="$parent"
    done
    # Fallback: the capabilities.py that lives next to pc.sh
    echo "$_PC_SCRIPT_DIR/capabilities.py"
}

# Resolve PC_BASE_DIR: prefer the canonical peer (GitHub/ai_processes/); fall
# back to the local sync copy next to this script when the peer is absent.
_pc_base_dir() {
    local peer="$HOME/Documents/GitHub/ai_processes"
    if [[ -f "$peer/capabilities_core.py" ]]; then
        echo "$peer"
    else
        echo "$_PC_SCRIPT_DIR"
    fi
}

# The `pc` command: resolve capabilities.py upward, stamp PC_CALLED_FROM and
# PC_BASE_DIR, then run.
pc() {
    local cap_file
    cap_file="$(_pc_find_caps)"
    PC_CALLED_FROM="$PWD" PC_BASE_DIR="$(_pc_base_dir)" python "$cap_file" "$@"
}

# When executed directly (not sourced), run immediately.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    pc "$@"
fi

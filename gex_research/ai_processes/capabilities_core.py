#!/usr/bin/env python3
"""
capabilities_core.py  --  base capabilities protocol
=============================================================================
BASE FRAMEWORK.  This file is an importable library.

CANONICAL SOURCE:  GitHub/ai_processes/capabilities_core.py
  This is the authoritative copy.  Sync copies live alongside local
  capabilities.py extensions in each project as a standalone fallback.
  Update this file when the protocol changes; bump CORE_VERSION; then
  copy it to any sync-copy locations.

DO NOT add project capabilities here.  Project-specific capabilities belong
in the thin `capabilities.py` in each project folder, which imports run()
from this module.

Separation contract
-------------------
  capabilities_core.py   Stable base protocol: letter navigation, display,
                         CLI plumbing, --spec output, auto-discovery.
                         Treat as an imported sub-module.  Bump CORE_VERSION
                         on any protocol change.  Rarely needs editing.

  capabilities.py        Project extension: only LOCAL_CAPABILITIES for
                         that folder.  Calls run(LOCAL_CAPABILITIES, root_dir=__file__).
                         Changes when capabilities are added or removed --
                         not when the framework evolves.

Extension model
---------------
  Each project folder keeps a thin capabilities.py that imports run()
  from this file via PC_BASE_DIR and passes its LOCAL_CAPABILITIES list
  together with root_dir=__file__:

      # any_project/any_folder/capabilities.py
      import sys, os
      _base = os.environ.get(
          "PC_BASE_DIR",
          os.path.dirname(os.path.abspath(__file__)),  # local sync copy fallback
      )
      sys.path.insert(0, os.path.abspath(_base))
      from capabilities_core import run

      LOCAL_CAPABILITIES = [...]

      if __name__ == "__main__":
          run(LOCAL_CAPABILITIES, root_dir=__file__)

  ``root_dir=__file__`` tells the core:
    * scan THIS folder for auto-discovered CAPABILITY modules
    * report THIS folder in the nav context banner

  pc.bat / pc.sh in each project set PC_BASE_DIR to this directory
  (GitHub/ai_processes/) when it exists on the machine, with a fallback
  to the local sync copy so each project works standalone.

Sync model
----------
  When the protocol changes:
    1. Update this file (canonical source).
    2. Bump CORE_VERSION.
    3. Copy this file to the sync-copy location in each project.
       (Project capabilities.py files do NOT need updating -- they only
       contain capability data, not framework code.)

  Sync copy locations:
    scavengers_guild/ai_processes/capabilities_core.py
    splendid_baralytics/gex_research/ai_processes/capabilities_core.py

Public API
----------
  run(built_ins, root_dir)  Register capabilities and launch the CLI.
                            Call this from capabilities.py __main__.
  CORE_VERSION              Protocol/framework version string.
  SCHEMA_VERSION            --spec JSON schema version string.

  Lower-level (importable for custom extensions):
    get_all_capabilities()
    resolve_chain(targets)
    _letter_to_index(tok), _index_to_letter(i), _target_index(target, items)
    print_menu(), print_info(targets), print_run_command(targets)
    print_spec(pretty), print_context(then_menu), print_tag_list()
    print_filtered(tag)

Chain navigation
----------------
  pc                       interactive menu
  pc info a                detail for capability a (1st)
  pc info a b              detail for sub-command b (2nd) of capability a
  pc run  a b              run-command for sub-command b of capability a
  pc filter <tag>          capabilities matching a tag
  pc tags                  tag index
  pc scaffold              create a local capabilities.py from a folder scan
  pc --spec [--pretty]     full JSON spec (AI/agent-friendly)

Target resolution (at every level):
  Letter (a,b..z, aa,ab..) positional, mobile-friendly, no numberpad
  Exact id string           stable lookup (survives reordering)
  Plain integer             legacy 1-based (still supported)
=============================================================================
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# -----------------------------------------------------------------------------
# Version constants
# -----------------------------------------------------------------------------

CORE_VERSION   = "1.3"   # bump when the protocol/framework changes
SCHEMA_VERSION = "1.3"   # bump when the --spec JSON schema changes


# -----------------------------------------------------------------------------
# Module-level registry (set by run() before CLI dispatch)
# -----------------------------------------------------------------------------

_BUILT_INS: List[Dict] = []
_LOCAL_DIR: Optional[Path] = None   # directory of the calling extension's file


def run(built_in_capabilities: List[Dict], root_dir: Optional[str] = None) -> None:
    """Register capabilities and dispatch the CLI.

    This is the only function a thin capabilities.py needs to call::

        from capabilities_core import run
        run(LOCAL_CAPABILITIES, root_dir=__file__)

    ``root_dir`` should be ``__file__`` (or the directory) of the calling
    extension file.  It tells the core:

    * where to scan for auto-discovered CAPABILITY modules
      (``_discover_local``)
    * what directory to report as the "capabilities location" in the nav
      context banner (``_nav_context``)

    When ``root_dir`` is omitted the core falls back to its own directory
    -- the behaviour before this extension protocol.
    """
    global _BUILT_INS, _LOCAL_DIR
    _BUILT_INS = built_in_capabilities
    if root_dir is not None:
        p = Path(root_dir).resolve()
        _LOCAL_DIR = p if p.is_dir() else p.parent
    main()


# -----------------------------------------------------------------------------
# Auto-discovery -- scan the same directory for modules that declare CAPABILITY
# -----------------------------------------------------------------------------

def _discover_local() -> List[Dict]:
    """Return CAPABILITY dicts from .py files in the active extension's directory.

    Scans ``_LOCAL_DIR`` when set by ``run(root_dir=...)``, otherwise falls back
    to the directory containing this file.  Framework files and the extension
    wrapper itself are excluded.
    """
    here = _LOCAL_DIR if _LOCAL_DIR is not None else Path(__file__).parent
    exclude = {"capabilities", "capabilities_core", "__init__"}
    discovered: List[Dict] = []
    for path in sorted(here.glob("*.py")):
        if path.stem in exclude:
            continue
        try:
            spec = importlib.util.spec_from_file_location(path.stem, path)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            cap = getattr(mod, "CAPABILITY", None)
            if cap and isinstance(cap, dict) and "id" in cap:
                discovered.append(cap)
        except Exception:
            pass
    return discovered


def get_all_capabilities() -> List[Dict]:
    """Return built-ins merged with any locally-discovered process modules."""
    built_in_ids = {c["id"] for c in _BUILT_INS}
    local = [c for c in _discover_local() if c["id"] not in built_in_ids]
    return _BUILT_INS + local


# -----------------------------------------------------------------------------
# Chain resolution  -- (capability-target [, sub-command-target])
# -----------------------------------------------------------------------------

def _letter_to_index(tok: str) -> Optional[int]:
    """Letter position -> 0-based index. 'a'->0 ... 'z'->25, 'aa'->26, 'ab'->27 ...
    Returns None if tok is not a pure a-z string."""
    if not tok or any(c < "a" or c > "z" for c in tok):
        return None
    idx = 0
    for c in tok:
        idx = idx * 26 + (ord(c) - ord("a") + 1)
    return idx - 1


def _index_to_letter(i: int) -> str:
    """0-based index -> letter position. 0->'a' ... 25->'z', 26->'aa' ... (inverse of above)."""
    s, i = "", i + 1
    while i > 0:
        i, r = divmod(i - 1, 26)
        s = chr(ord("a") + r) + s
    return s


def _target_index(target: str, items: List[Dict]) -> Optional[int]:
    """Resolve target -> 0-based index, or None. Order: exact id, letter position, legacy digit."""
    for i, it in enumerate(items):
        if it.get("id") == target:
            return i
    idx = _letter_to_index(target.lower())
    if idx is None and target.isdigit():
        idx = int(target) - 1
    if idx is not None and 0 <= idx < len(items):
        return idx
    return None


def _resolve_from(target: str, items: List[Dict], label: str) -> Dict:
    """Resolve target (letter position, exact id, or legacy integer) from items."""
    idx = _target_index(target, items)
    if idx is not None:
        return items[idx]
    span = f"a-{_index_to_letter(len(items) - 1)}" if items else "(none)"
    print(f"[error] Unknown {label}: '{target}'  (valid letters: {span}, or an exact id)", file=sys.stderr)
    print(f"  Run `pc` to see valid {label} letters and ids.", file=sys.stderr)
    sys.exit(1)


def resolve_chain(targets: List[str]) -> Tuple[Dict, Optional[Dict]]:
    """Resolve a chain of 1-2 targets to (capability, sub_command|None).

    targets[0]  capability by index or id
    targets[1]  sub-command by index or id within that capability (optional)
    """
    caps = get_all_capabilities()
    cap = _resolve_from(targets[0], caps, "capability")
    if len(targets) < 2:
        return cap, None
    commands = cap.get("commands") or []
    if not commands:
        print(
            f"[error] '{cap['name']}' has no sub-commands. "
            f"Use `pc info {targets[0]}` to see what it offers.",
            file=sys.stderr,
        )
        sys.exit(1)
    cmd = _resolve_from(targets[1], commands, "sub-command")
    return cap, cmd


# -----------------------------------------------------------------------------
# Navigation context  (. command / upward-search awareness)
# -----------------------------------------------------------------------------

def _nav_context() -> Dict:
    """Compute the relationship between the active capabilities directory and
    where `pc` was invoked from (via the PC_CALLED_FROM env var set by
    pc.bat/pc.sh).

    The "capabilities directory" is ``_LOCAL_DIR`` when an extension called
    ``run(root_dir=__file__)``; otherwise the directory of this file.

    Returns a dict with keys:
      capabilities_dir  absolute path of the active capabilities folder
      called_from       absolute path where `pc` was invoked
      same_dir          True if both are the same folder
      direction         human-readable relationship string
      levels_up         int if capabilities is N levels above called_from, else None
      other_caps        list of any other capabilities.py files found while scanning
                        upward from called_from (EXTEND: populate for richer context)
    """
    here = (_LOCAL_DIR if _LOCAL_DIR is not None else Path(__file__).resolve().parent)
    raw = os.environ.get("PC_CALLED_FROM", "")
    called_from = Path(raw).resolve() if raw else Path.cwd().resolve()

    same = (here == called_from)
    levels_up: Optional[int] = None
    direction: str

    if same:
        direction = "local (same folder)"
    else:
        try:
            rel = called_from.relative_to(here)
            direction = f"inside capabilities folder (at ./{rel})"
        except ValueError:
            try:
                rel = here.relative_to(called_from)
                levels_up = len(rel.parts)
                direction = (
                    f"resolved {levels_up} level{'s' if levels_up != 1 else ''} up"
                    f"  ({here})"
                )
            except ValueError:
                direction = f"different branch  ({here})"

    # EXTEND: scan upward from called_from for additional capabilities.py files
    # to surface sibling or ancestor capability sets.
    other_caps: List[str] = []

    return {
        "capabilities_dir": str(here),
        "called_from":      str(called_from),
        "same_dir":         same,
        "direction":        direction,
        "levels_up":        levels_up,
        "other_caps":       other_caps,
    }


def print_context(then_menu: bool = True) -> None:
    """[.] Navigation context view.

    Shows where capabilities.py was resolved from relative to where `pc` was
    called, then opens the interactive menu.  Designed as the default
    orientation command when working across folder boundaries.

    EXTEND: add `other_caps` scanning, CLAUDE.md detection, sibling
    capabilities.py discovery, and any other folder-level metadata that helps
    orient a dispatch agent or a human navigating an unfamiliar tree.
    """
    ctx = _nav_context()
    caps = get_all_capabilities()

    print("\n+----------------------------------------------------------+")
    print("|  Navigation Context  [pc .]                             |")
    print("+----------------------------------------------------------+")
    print(f"  capabilities : {ctx['capabilities_dir']}")
    print(f"  called from  : {ctx['called_from']}")
    print(f"  position     : {ctx['direction']}")
    print(f"  capabilities : {len(caps)} registered  "
          f"({sum(1 for c in caps if c.get('commands'))} with sub-commands)")
    print(f"  core version : {CORE_VERSION}  |  schema: {SCHEMA_VERSION}")

    if ctx["other_caps"]:
        print("\n  Other capabilities.py found nearby:")
        for p in ctx["other_caps"]:
            print(f"    {p}")

    # EXTEND: detect and list CLAUDE.md, README.md, pc.bat/pc.sh at each
    # ancestor level so a dispatch agent can jump to sibling contexts.

    print()
    if not ctx["same_dir"]:
        print("  Note: capabilities.py was resolved by upward search.")
        print("  To use a local one instead, run `pc` from its directory.")
        print()

    if then_menu:
        print_menu(_show_resolved_banner=False)


# -----------------------------------------------------------------------------
# Output helpers
# -----------------------------------------------------------------------------

def _all_tags() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for cap in get_all_capabilities():
        for tag in cap.get("tags", []):
            counts[tag] = counts.get(tag, 0) + 1
    return dict(sorted(counts.items()))


def print_spec(pretty: bool = False) -> None:
    """AI-friendly: dump the full capability registry as JSON."""
    caps = get_all_capabilities()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "core_version":   CORE_VERSION,
        "description": (
            "AI process capabilities. Targets are LETTER positions (a, b, c ... z, aa, ab ...) "
            "or an exact id; legacy integers still work. Two targets drill into sub-commands: "
            "pc info <cap> <cmd>. Letters are mobile-friendly (no numberpad)."
        ),
        "usage": {
            "interactive":      "pc",
            "spec":             "pc --spec [--pretty]",
            "detail":           "pc info <id-or-letter>",
            "sub_detail":       "pc info <id-or-letter> <sub-id-or-letter>",
            "run_command":      "pc run  <id-or-letter>",
            "sub_run_command":  "pc run  <id-or-letter> <sub-id-or-letter>",
            "filter_tag":       "pc filter <tag>",
            "list_tags":        "pc tags",
        },
        "total": len(caps),
        "tags": _all_tags(),
        "capabilities": caps,
    }
    print(json.dumps(payload, indent=2 if pretty else None))


W = 58  # display width constant


def _section(label: str) -> None:
    pad = W - len(label) - 5
    print(f"\n  -- {label} " + "-" * max(pad, 4))


def _print_command_detail(cap: Dict, cmd: Dict, letter: Optional[str] = None) -> None:
    """Detail block for a single sub-command."""
    idx_str = f"  ({letter})" if letter else ""
    bar = "=" * W
    print(f"\n{bar}")
    print(f"  {cap['name']} -> {cmd['name']}  [{cmd['id']}]{idx_str}")
    print(bar)
    print(f"\n  {cmd['description']}\n")
    if cmd.get("usage"):
        _section("Usage")
        for line in cmd["usage"].splitlines():
            print(f"    {line}")
    print()


def _print_capability_detail(cap: Dict) -> None:
    bar = "=" * W
    print(f"\n{bar}")
    print(f"  {cap['name']}  [{cap['id']}]")
    print(bar)
    print(f"\n  {cap['description']}\n")

    if cap.get("usage"):
        _section("Usage")
        for line in cap["usage"].splitlines():
            print(f"    {line}")

    if cap.get("inputs"):
        _section("Inputs")
        for k, v in cap["inputs"].items():
            print(f"    {k:<22} {v}")

    if cap.get("outputs"):
        _section("Outputs")
        for k, v in cap["outputs"].items():
            print(f"    {k:<22} {v}")

    commands = cap.get("commands") or []
    if commands:
        _section("Sub-commands  (drill: pc info <this> <a>  |  pc run <this> <a>)")
        for i, cmd in enumerate(commands):
            print(f"    {_index_to_letter(i)})  {cmd['name']}  [{cmd['id']}]")
            print(f"         {cmd['description']}")

    if cap.get("tags"):
        print(f"\n  Tags: {', '.join(cap['tags'])}")
    if cap.get("module"):
        print(f"  Module: {cap['module']}")
    print()


def print_info(targets: List[str]) -> None:
    """Show detail for a capability, or a sub-command if two targets given."""
    cap, cmd = resolve_chain(targets)
    if cmd is not None:
        pos = next(
            (i for i, c in enumerate(cap.get("commands", [])) if c is cmd), None
        )
        _print_command_detail(cap, cmd, letter=_index_to_letter(pos) if pos is not None else None)
    else:
        _print_capability_detail(cap)


def print_run_command(targets: List[str]) -> None:
    """Print the usage/run string for a capability or sub-command."""
    cap, cmd = resolve_chain(targets)
    item = cmd if cmd is not None else cap
    usage = item.get("usage", "No usage defined.")
    print(usage)


def print_tag_list() -> None:
    print("\n  Tags (and capability count):\n")
    for tag, count in _all_tags().items():
        print(f"    {tag:<28} {count} {'capabilities' if count != 1 else 'capability'}")
    print()


def print_filtered(tag: str) -> None:
    matching = [c for c in get_all_capabilities() if tag in c.get("tags", [])]
    if not matching:
        print(f"No capabilities tagged '{tag}'.", file=sys.stderr)
        print("Run `pc tags` to see valid tags.", file=sys.stderr)
        sys.exit(1)
    print(f"\n  Capabilities tagged '{tag}':\n")
    for i, cap in enumerate(matching, 1):
        ncmds = len(cap.get("commands") or [])
        sub = f"  ({ncmds} sub-commands)" if ncmds else ""
        print(f"  * {cap['name']}  [{cap['id']}]{sub}")
        desc = cap["description"]
        print(f"    {(desc[:72] + '...') if len(desc) > 72 else desc}\n")


# -----------------------------------------------------------------------------
# Interactive menu
# -----------------------------------------------------------------------------

def print_menu(_show_resolved_banner: bool = True) -> None:
    caps = get_all_capabilities()
    print("\n+----------------------------------------------------------+")
    print("|              AI Process Capabilities                     |")
    print("+----------------------------------------------------------+")
    print("|  <a>       detail  |  <a> <b>  sub-command detail        |")
    print("|  .  context |  t  tags  |  q  quit                       |")
    print("+----------------------------------------------------------+")

    # Auto-banner: show one-liner when capabilities.py was found by upward search
    if _show_resolved_banner:
        ctx = _nav_context()
        if not ctx["same_dir"]:
            print(f"  [resolved: {ctx['capabilities_dir']}  |  pc . for full context]")
    print()

    for i, cap in enumerate(caps):
        letter = _index_to_letter(i)
        tags_str = f"  [{', '.join(cap['tags'][:3])}]" if cap.get("tags") else ""
        ncmds = len(cap.get("commands") or [])
        sub_hint = f"  +{ncmds}" if ncmds else ""
        desc = cap["description"]
        short_desc = (desc[:65] + "...") if len(desc) > 65 else desc
        print(f"  {letter:>2}){sub_hint:<4} {cap['name']}")
        print(f"         {short_desc}")
        if tags_str:
            print(f"         {tags_str}")
        print()

    print("-" * 60)
    print("  Hint: +N means N sub-commands (e.g. 'a b' = 2nd sub-command of item a)")
    print("-" * 60)

    while True:
        raw = input("\n> ").strip().lower()
        if raw in ("q", "quit", "exit", ""):
            break
        if raw == "t":
            print_tag_list()
            continue
        if raw in ("0", ".", "ctx"):
            print_context(then_menu=False)
            continue
        parts = raw.split()
        if parts and _target_index(parts[0], caps) is not None:
            print_info([p for p in parts if p])
            another = input("  Another? (<a> / <a> <b> / . = context / q): ").strip().lower()
            if another in (".", "0", "ctx"):
                print_context(then_menu=False)
            elif another and another not in ("q", "quit"):
                aparts = another.split()
                if aparts:
                    print_info([p for p in aparts if p])
        else:
            print("  Enter a letter (or 'a b' for sub), '.' for context, 't' tags, 'q' quit.")


# -----------------------------------------------------------------------------
# Extension scaffolding  (auto-prompt + `pc scaffold`)
#
# Process description: How to examine a folder and create a local extension
# ─────────────────────────────────────────────────────────────────────────────
# 1. SCAN   Walk the target directory for runnable entry points:
#           *.py  (skip capabilities*, __init__, setup, conftest, test_*, pc)
#           *.mjs, *.js   → node <file>
#           *.sh  (skip pc.sh)  → bash <file>
#           package.json  → extract "scripts" block → npm run <name>
#
# 2. MAP    For each entry point, draft a stub capability dict:
#           { id, name, description (placeholder), usage, tags: [] }
#           ID: snake_case of the stem.  Name: title-cased stem.
#
# 3. WRITE  Generate capabilities.py from _SCAFFOLD_HEADER + stubs +
#           _SCAFFOLD_FOOTER.  The file uses the standard PC_BASE_DIR import
#           pattern and calls run(LOCAL_CAPABILITIES, root_dir=__file__).
#           capabilities_core.py is copied as a local sync copy alongside it.
#
# 4. FILL   User edits the stubs: replaces description placeholders, adds
#           inputs/outputs/commands sub-dicts, sets tags.
#
# 5. RUN    `pc` from the same directory finds the new capabilities.py and
#           shows the populated menu.
#
# This process runs automatically (Y/n prompt) when pc.bat/pc.sh is invoked
# from a directory that contains no capabilities.py.  Explicit: `pc scaffold`.
# -----------------------------------------------------------------------------

_SCAFFOLD_HEADER = (
    "#!/usr/bin/env python3\n"
    '"""\n'
    "{folder}/capabilities.py\n"
    "-----------------------------------------------------------------------------\n"
    "Local capabilities extension for {folder}.\n"
    "\n"
    "Auto-scaffolded {date}.\n"
    "Edit LOCAL_CAPABILITIES below: fill in descriptions, usage strings, and tags\n"
    "for each entry point.  Add \"commands\" (sub-commands), \"inputs\", and\n"
    "\"outputs\" to capabilities that have named modes.  See ai_processes/README.md.\n"
    "\n"
    "Framework:   GitHub/ai_processes/capabilities_core.py  (canonical peer)\n"
    "Fallback:    capabilities_core.py in this directory (sync copy, if present)\n"
    "\n"
    "Standalone use without pc.bat/pc.sh:\n"
    "    PC_BASE_DIR=/path/to/ai_processes python capabilities.py\n"
    "-----------------------------------------------------------------------------\n"
    '"""\n'
    "\n"
    "from __future__ import annotations\n"
    "import os, sys\n"
    "from typing import Dict, List\n"
    "\n"
    "_base = os.environ.get(\n"
    '    "PC_BASE_DIR",\n'
    "    os.path.dirname(os.path.abspath(__file__)),   # local sync copy fallback\n"
    ")\n"
    "sys.path.insert(0, os.path.abspath(_base))\n"
    "from capabilities_core import run  # noqa: E402\n"
    "\n"
    "LOCAL_CAPABILITIES: List[Dict] = [\n"
)

_SCAFFOLD_FOOTER = (
    "]\n"
    "\n"
    'if __name__ == "__main__":\n'
    "    run(LOCAL_CAPABILITIES, root_dir=__file__)\n"
)

# _STUB_ENTRY: legacy format string kept for external callers.
# scaffold_extension uses _format_stub() internally (supports real descriptions).
_STUB_ENTRY = (
    "    {{\n"
    '        "id":          "{id}",\n'
    '        "name":        "{name}",\n'
    '        "description": "# TODO: describe what {file} does.",\n'
    '        "usage":       "{usage}",\n'
    '        "tags":        [],\n'
    "    }},\n"
)

_STUB_PLACEHOLDER = (
    "    {\n"
    '        "id":          "my_tool",\n'
    '        "name":        "My Tool",\n'
    '        "description": "# TODO: describe what this does.",\n'
    '        "usage":       "python my_tool.py",\n'
    '        "tags":        [],\n'
    "    },\n"
)


def _has_local_caps(directory: Path) -> bool:
    """Return True if *directory* contains a capabilities.py."""
    return (directory / "capabilities.py").exists()


def _read_md_caps(directory: Path) -> List[Dict]:
    """Scan *.md files in *directory* for self-declared entry-point descriptions.

    Reads the markdown files looking for runner-prefixed commands
    (python / node / bash / npm run) in three contexts, in ascending priority:

      1. Inline backtick code anywhere in prose / bullets  (lowest priority)
      2. Fenced code blocks — the heading above the block is the description
      3. Table rows  — first cell = name, last plain-text cell = description  (highest)

    Returns partial capability dicts: id, name, description, usage.
    These seed scaffold stubs so the generated capabilities.py contains real
    descriptions instead of # TODO placeholders.
    """
    import re

    RUNNER = re.compile(r"(python3?|node|bash|npm\s+run)\s+(\S.*)", re.IGNORECASE)
    INLINE = re.compile(r"`((?:python3?|node|bash|npm\s+run)\s+\S[^`]*)`", re.IGNORECASE)

    def _cmd_id(usage: str) -> str:
        parts = usage.split()
        # Handle "npm run <script>" as a two-word runner explicitly
        if (len(parts) >= 3
                and parts[0].lower() == "npm"
                and parts[1].lower() == "run"):
            stem = Path(parts[2]).stem.lower().replace("-", "_")
            return stem if stem else parts[2].lower()
        # General case: skip the runner word, find first meaningful token
        skip = {"python", "python3", "node", "bash", "npm"}
        for tok in parts:
            if tok.lower() in skip or tok.startswith(("-", "<", "[")):
                continue
            stem = Path(tok).stem.lower().replace("-", "_")
            if stem and stem not in skip:
                return stem
        return ""

    def _cmd_name(usage: str, label: str = "") -> str:
        # Trim label at first parenthesis/comma to strip explanatory suffixes
        clean = re.split(r"[,(;]", label.strip("* _|"))[0].strip() if label else ""
        base = clean if (clean and len(clean) < 45) else _cmd_id(usage)
        return base.replace("_", " ").replace("-", " ").title()

    def _strip_md(text: str) -> str:
        """Strip markdown formatting but KEEP the text content inside markers."""
        text = re.sub(r"\*+([^*]+)\*+", r"\1", text)   # bold/italic → content
        text = re.sub(r"`([^`]+)`", r"\1", text)         # inline code → content
        text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)  # links → label
        return text.strip(" *_|#")

    hints: Dict[str, Dict] = {}  # id → dict, later priority wins

    for md_path in sorted(directory.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        section = ""
        in_code = False
        code_head = ""
        code_lines: List[str] = []

        for line in text.splitlines():
            # Heading
            hm = re.match(r"^#{1,4}\s+(.*)", line)
            if hm:
                section = _strip_md(hm.group(1))
                in_code = False
                code_lines = []
                code_head = section
                continue

            # Fenced code block
            if re.match(r"^```", line):
                if in_code:
                    # closing fence — extract first runner line per block
                    for cl in code_lines:
                        m = RUNNER.match(cl.strip())
                        if m:
                            cmd = cl.strip()
                            eid = _cmd_id(cmd)
                            if eid and eid not in hints:
                                hints[eid] = {
                                    "id":          eid,
                                    "name":        _cmd_name(cmd),
                                    "description": code_head or f"See {md_path.name}.",
                                    "usage":       cmd,
                                }
                    in_code = False
                    code_lines = []
                else:
                    in_code = True
                    code_head = section
                continue

            if in_code:
                code_lines.append(line)
                continue

            # Table row (highest priority — overwrites earlier entries for same id)
            if line.strip().startswith("|") and "|" in line:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                # skip separator rows like |---|---|
                if len(cells) < 2 or all(set(c) <= {"-", ":"} for c in cells if c):
                    continue
                for cell in cells:
                    for cmd in INLINE.findall(cell):
                        eid = _cmd_id(cmd)
                        if not eid:
                            continue
                        label = _strip_md(cells[0]) if cells else ""
                        # description: last non-command text cell
                        desc = ""
                        for c in reversed(cells):
                            cs = _strip_md(c)
                            if cs and len(cs) > 5 and not INLINE.search(c) and cs != label:
                                desc = cs
                                break
                        hints[eid] = {
                            "id":          eid,
                            "name":        _cmd_name(cmd, label),
                            "description": desc or f"See {md_path.name}.",
                            "usage":       cmd,
                        }
                continue

            # Inline code in prose / bullets (lowest priority — only if not yet seen)
            for cmd in INLINE.findall(line):
                eid = _cmd_id(cmd)
                if eid and eid not in hints:
                    desc_text = _strip_md(re.sub(r"`[^`]+`", "", line)).strip("- :")
                    hints[eid] = {
                        "id":          eid,
                        "name":        _cmd_name(cmd),
                        "description": desc_text[:120] if len(desc_text) > 5 else f"See {md_path.name}.",
                        "usage":       cmd,
                    }

    return list(hints.values())


def _format_stub(entry: Dict) -> str:
    """Render one capability entry as a Python source stub for a scaffolded file.

    Uses the entry's 'description' if present; falls back to a # TODO placeholder.
    Propagates 'tags' from the entry (e.g. keywords sourced from package.json).
    Escapes backslashes and double-quotes so the generated source is valid Python.
    """
    desc = (
        entry.get("description")
        or f"# TODO: describe what {entry.get('file') or entry.get('id', 'this')} does."
    )
    desc  = desc.replace("\\", "\\\\").replace('"', '\\"')
    name  = entry.get("name", "")
    usage = entry.get("usage", "")
    eid   = entry.get("id", "")
    tags  = entry.get("tags") or []
    tags_str = json.dumps(tags)   # double-quoted list: ["analytics", "metrics"]
    return (
        "    {\n"
        f'        "id":          "{eid}",\n'
        f'        "name":        "{name}",\n'
        f'        "description": "{desc}",\n'
        f'        "usage":       "{usage}",\n'
        f'        "tags":        {tags_str},\n'
        "    },\n"
    )


def _read_pkg_caps(directory: Path) -> List[Dict]:
    """Read package.json in *directory* for declared entry-point capabilities.

    This is a *structured declaration* scan (Phase 1), not a file-glob scan.
    Extracts four sources in priority order:

      description  Package-level description seeds capability descriptions:
                   - used verbatim for bin / main / module entry points
                   - used as fallback for scripts with no command value
                   - inserted into the scaffold_extension() docstring header
      bin          Explicitly declared CLI commands — highest fidelity.
                   "bin": {"my-tool": "./cli.js"} → usage: my-tool
      main/module  Primary entry point, described by the package description.
      scripts      Named tasks; script value becomes the description hint.
                   "dev": "next dev" → description: "Runs: next dev"
      keywords     Mapped directly to tags on every entry.

    Lifecycle hooks (pre*/post*, prepare, publish, pack) are excluded.
    npm shorthands: start / stop / test / restart use `npm <name>`, not `npm run`.
    IDs are plain snake_case (no npm_ prefix) so they merge with md-sourced hints.
    """
    pkg_path = directory / "package.json"
    if not pkg_path.exists():
        return []
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    LIFECYCLE = {
        "preinstall", "install", "postinstall",
        "prepublish", "publish", "postpublish",
        "prepare", "preprepare", "postprepare",
        "prepack",  "pack",  "postpack",
    }
    NPM_SHORTHAND = {"start", "stop", "test", "restart"}

    def _id(s: str) -> str:
        return s.lower().replace("-", "_").replace(":", "_").replace(" ", "_")

    def _name(s: str) -> str:
        return s.replace("-", " ").replace("_", " ").replace(":", " — ").title()

    pkg_desc = (data.get("description") or "").strip()
    pkg_name = (data.get("name") or "").strip()
    keywords = [str(k).lower() for k in (data.get("keywords") or [])]
    found: List[Dict] = []

    # main / module entry point: pkg description IS the capability description
    main_file = (data.get("main") or data.get("module") or "").strip()
    if main_file and pkg_desc:
        stem = Path(main_file).stem.lower().replace("-", "_")
        found.append({
            "id":          stem,
            "name":        _name(pkg_name) if pkg_name else _name(stem),
            "description": pkg_desc,
            "file":        main_file,
            "usage":       f"node {main_file}",
            "tags":        keywords[:5],
        })

    # bin entries: explicit CLI declarations
    bin_block = data.get("bin") or {}
    if isinstance(bin_block, str) and pkg_name:
        bin_block = {pkg_name: bin_block}
    for cmd_name, script_path in (bin_block.items() if isinstance(bin_block, dict) else []):
        found.append({
            "id":          "bin_" + _id(cmd_name),
            "name":        _name(cmd_name),
            "description": pkg_desc or f"CLI command: {cmd_name}  (entry: {script_path})",
            "file":        script_path,
            "usage":       cmd_name,
            "tags":        keywords[:5],
        })

    # scripts
    for script_name, script_cmd in (data.get("scripts") or {}).items():
        if script_name in LIFECYCLE or script_name.startswith(("pre", "post")):
            continue
        usage = (
            f"npm {script_name}" if script_name in NPM_SHORTHAND
            else f"npm run {script_name}"
        )
        # script value as description hint; pkg_desc as fallback when no command
        desc = f"Runs: {script_cmd}" if script_cmd else pkg_desc
        if len(desc) > 100:
            desc = desc[:97] + "..."
        found.append({
            "id":          _id(script_name),
            "name":        "npm " + _name(script_name),
            "description": desc,
            "file":        "package.json",
            "usage":       usage,
            "tags":        keywords[:5],
        })

    return found


def _scan_entry_points(directory: Path) -> List[Dict]:
    """Discover runnable entry points in *directory*.

    Phase 1 — Declarations: reads package.json (bin + scripts + keywords) and
               *.md files (tables, code blocks, inline code).  Both are treated
               as explicit declarations.  MD hints overwrite pkg hints for the
               same id (human text beats machine-generated descriptions).
    Phase 2 — File scan: globs *.py, *.mjs, *.js, *.sh.  Each found file
               inherits its description, name, usage, and tags from Phase 1
               when the ids match; otherwise description is left empty for
               _format_stub() to fill with a # TODO placeholder.
    Phase 3 — Declaration-only entries: scripts / bin entries / subdirectory
               commands that appeared in declarations but have no root-level
               file counterpart are appended (file = "").

    Each returned dict: id, name, description (str), file, usage, tags (list).
    """
    # Phase 1: merge pkg hints (lower priority) then md hints (higher priority)
    declared: Dict[str, Dict] = {}
    for h in _read_pkg_caps(directory):
        declared[h["id"]] = h
    for h in _read_md_caps(directory):
        declared[h["id"]] = h   # md overwrites pkg for same id

    _SKIP: set = {
        "capabilities", "capabilities_core", "setup", "conftest",
        "__init__", "test", "tests", "pc",
    }
    _SKIP_PREFIX = ("_", "test_")

    def _id(stem: str) -> str:
        return stem.lower().replace("-", "_").replace(" ", "_")

    def _name(stem: str) -> str:
        return stem.replace("_", " ").replace("-", " ").title()

    found: List[Dict] = []
    seen_ids: set = set()

    # Phase 2: File scan
    for glob_pat, runner in (
        ("*.py",  "python"),
        ("*.mjs", "node"),
        ("*.js",  "node"),
        ("*.sh",  "bash"),
    ):
        for path in sorted(directory.glob(glob_pat)):
            if path.stem in _SKIP:
                continue
            if any(path.stem.startswith(p) for p in _SKIP_PREFIX):
                continue
            eid = _id(path.stem)
            seen_ids.add(eid)
            hint = declared.get(eid, {})
            found.append({
                "id":          eid,
                "name":        hint.get("name") or _name(path.stem),
                "description": hint.get("description", ""),
                "file":        path.name,
                "usage":       hint.get("usage") or f"{runner} {path.name}",
                "tags":        hint.get("tags") or [],
            })

    # Phase 3: declaration-only entries (no root file found)
    for eid, hint in declared.items():
        if eid not in seen_ids:
            found.append({
                "id":          hint["id"],
                "name":        hint.get("name", ""),
                "description": hint.get("description", ""),
                "file":        hint.get("file", ""),
                "usage":       hint.get("usage", ""),
                "tags":        hint.get("tags") or [],
            })

    # Phase 4: if nothing got a description from declarations (e.g. package.json
    # has only a top-level description with no main/bin/scripts), propagate the
    # package description to all found entries as a project-level fallback.
    if found and not any(e.get("description") for e in found):
        pkg_json = directory / "package.json"
        if pkg_json.exists():
            try:
                pkg_data = json.loads(pkg_json.read_text(encoding="utf-8"))
                pkg_desc = (pkg_data.get("description") or "").strip()
                if pkg_desc:
                    for e in found:
                        e["description"] = pkg_desc
            except Exception:
                pass

    return found


def scaffold_extension(target_dir: Path) -> None:
    """Generate a capabilities.py extension in *target_dir*.

    Scans the directory for runnable entry points, writes stub capability
    dicts in the standard LOCAL_CAPABILITIES pattern, copies
    capabilities_core.py as a local sync copy, and prints next-step
    instructions.

    This function encodes the 5-step extension process documented at the
    top of this section.  Calling it from an unfamiliar folder is how an
    agent or user bootstraps the capabilities framework for that folder.
    """
    import datetime
    import shutil

    target_dir = Path(target_dir).resolve()
    out_path = target_dir / "capabilities.py"

    if out_path.exists():
        print(f"\n  capabilities.py already exists at {out_path}")
        print("  Edit it directly, or delete it and run `pc scaffold` again.")
        return

    stubs = _scan_entry_points(target_dir)
    date_str = datetime.date.today().isoformat()

    # Pull package.json description for the docstring header
    pkg_desc = ""
    pkg_json = target_dir / "package.json"
    if pkg_json.exists():
        try:
            pkg_data = json.loads(pkg_json.read_text(encoding="utf-8"))
            pkg_desc = (pkg_data.get("description") or "").strip()
        except Exception:
            pass

    entries = (
        "".join(_format_stub(s) for s in stubs)
        if stubs else _format_stub({
            "id": "my_tool", "name": "My Tool", "description": "",
            "file": "my_tool.py", "usage": "python my_tool.py",
        })
    )
    header = _SCAFFOLD_HEADER.format(folder=target_dir.name, date=date_str)
    if pkg_desc:
        # Insert description after the "Local capabilities extension for X." line
        header = header.replace(
            f"Local capabilities extension for {target_dir.name}.\n",
            f"Local capabilities extension for {target_dir.name}.\n{pkg_desc}\n",
            1,
        )
    content = header + entries + _SCAFFOLD_FOOTER
    out_path.write_text(content, encoding="utf-8")

    # Copy capabilities_core.py as a local sync copy (enables standalone use)
    core_src = Path(__file__).resolve()
    core_dst = target_dir / "capabilities_core.py"
    copied_core = False
    if not core_dst.exists() and core_src.resolve() != core_dst.resolve():
        try:
            shutil.copy2(str(core_src), str(core_dst))
            copied_core = True
        except Exception:
            pass

    print(f"\n  Scaffolded: {out_path.name}")
    if copied_core:
        print("  Sync copy:  capabilities_core.py")

    n_docs = sum(1 for s in stubs if s.get("description"))
    print(f"\n  Entry points found ({len(stubs)}, {n_docs} with descriptions from docs):\n")
    for s in stubs:
        tag = "  [from docs]" if s.get("description") else ""
        print(f"    {s['id']:<32} {s['usage']}{tag}")
    if not stubs:
        print("    (none found — one placeholder stub written)")

    print(
        f"\n  Next:\n"
        f"    1. Open capabilities.py and fill in descriptions + tags.\n"
        f"    2. Copy pc.bat / pc.sh from ai_processes/ for dispatch shortcuts.\n"
        f"    3. Run `pc` from {target_dir.name}/ to see your new capabilities menu.\n"
        f"    4. Run `pc --spec --pretty` to emit the AI-agent JSON spec.\n"
    )


def _prompt_scaffold(called_from: Path) -> bool:
    """Offer to scaffold a local capabilities.py when none exists in *called_from*.

    Returns True if the user accepted and scaffolding was performed.
    """
    print(f"\n  No capabilities.py in: {called_from.name}/")
    print("  (capabilities resolved from a parent directory)")
    print()
    try:
        ans = input("  Scaffold a local capabilities.py here? [Y/n] ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return False
    if ans in ("", "y", "yes"):
        scaffold_extension(called_from)
        return True
    return False


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI process capabilities -- menu, chain navigation, or JSON spec.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Chain navigation (pc = python capabilities.py) -- LETTER targets, no numberpad:\n"
            "  pc                         interactive menu\n"
            "  pc .                       navigation context + menu (orient first)\n"
            "  pc info a                  detail for capability a (1st)\n"
            "  pc info a b                detail for sub-command b of capability a\n"
            "  pc info <id> <sub-id>      by exact id at both levels\n"
            "  pc run  b c                run-command for sub-command c of capability b\n"
            "  pc filter <tag>            capabilities tagged <tag>\n"
            "  pc tags                    tag index\n"
            "  pc scaffold                create local capabilities.py from folder scan\n"
            "  pc --spec --pretty         full JSON spec (AI/agent-friendly)\n"
            "\n"
            "Targets: letters a,b,c..z,aa,ab (positional) or exact id; integers still work.\n"
            "Upward search: pc.bat/pc.sh walk CWD upward for capabilities.py.\n"
            "pc . always shows full context regardless of where pc was run from.\n"
        ),
    )
    parser.add_argument("--spec",   action="store_true", help="Output full JSON spec")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print --spec output")
    parser.add_argument("cmd_args", nargs="*", help="[action] [target] [sub-target]")

    args = parser.parse_args()
    cmd_args: List[str] = args.cmd_args
    action  = cmd_args[0] if cmd_args else None
    targets = cmd_args[1:]

    # Detect: invoked via pc.bat/pc.sh from a directory that has no capabilities.py
    _cf_env = os.environ.get("PC_CALLED_FROM", "")
    _called_from = Path(_cf_env).resolve() if _cf_env else Path.cwd().resolve()
    _no_local = (
        bool(_cf_env)
        and not _has_local_caps(_called_from)
        and (_LOCAL_DIR is None or _LOCAL_DIR.resolve() != _called_from)
    )

    VALID_ACTIONS = ("0", ".", "ctx", "info", "run", "tags", "filter", "scaffold")

    if args.spec:
        print_spec(pretty=args.pretty)
    elif action is None:
        if _no_local:
            if _prompt_scaffold(_called_from):
                return
        print_menu()
    elif action in ("0", ".", "ctx"):
        print_context(then_menu=True)
    elif action == "tags":
        print_tag_list()
    elif action == "filter":
        if not targets:
            parser.error("filter requires a tag name  (e.g. pc filter pcy)")
        print_filtered(targets[0])
    elif action == "info":
        if not targets:
            parser.error("info requires at least one target  (e.g. pc info a)")
        print_info(targets[:2])
    elif action == "run":
        if not targets:
            parser.error("run requires at least one target  (e.g. pc run a)")
        print_run_command(targets[:2])
    elif action == "scaffold":
        scaffold_extension(_called_from)
    else:
        print(
            f"[error] Unknown action: '{action}'. "
            f"Valid: {', '.join(VALID_ACTIONS)}",
            file=sys.stderr,
        )
        sys.exit(1)

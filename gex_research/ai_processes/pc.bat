@echo off
setlocal EnableDelayedExpansion

:: pc.bat — shortcut for "python capabilities.py"
::
:: UPWARD SEARCH: if the current directory (or any of its parents) contains a
:: capabilities.py, that file is used.  Falls back to the capabilities.py that
:: lives alongside this bat file if nothing is found above.
::
:: Usage (from any directory):
::   pc                      interactive menu (auto-banner if resolved from parent)
::   pc .                    navigation context view, then menu
::   pc info a               detail for capability a (1st)
::   pc info c b             detail for sub-command b of capability c
::   pc run  g c             run-command for sub-command c of capability g
::   pc filter llm           capabilities tagged 'llm'
::   pc tags                 tag index
::   pc --spec --pretty      full JSON spec (AI/agent-friendly)

:: --- Upward search from CWD ---
set "PC_CAP="
set "_SEARCH=%CD%"

:search
if exist "!_SEARCH!\capabilities.py" (
    set "PC_CAP=!_SEARCH!\capabilities.py"
    goto :found
)
:: Move up one level (%%~dpA gives drive+path of A with trailing backslash)
for %%A in ("!_SEARCH!") do set "_UP=%%~dpA"
:: Strip the trailing backslash that %%~dp always adds
if "!_UP:~-1!"=="\" set "_UP=!_UP:~0,-1!"
:: Stop when we can no longer move up (root reached)
if /i "!_UP!"=="!_SEARCH!" goto :fallback
set "_SEARCH=!_UP!"
goto :search

:fallback
:: Nothing found upward — use the capabilities.py next to this bat file
set "PC_CAP=%~dp0capabilities.py"

:found
:: Stamp where pc was invoked from so capabilities.py can show context
set PC_CALLED_FROM=%CD%
:: PC_BASE_DIR tells capabilities.py where to import capabilities_core from.
:: Prefer the canonical peer (GitHub/ai_processes/); fall back to the local
:: sync copy next to this script when the peer is not present.
set "_PEER=%USERPROFILE%\Documents\GitHub\ai_processes"
if exist "!_PEER!\capabilities_core.py" (
    set PC_BASE_DIR=!_PEER!
) else (
    set PC_BASE_DIR=%~dp0
)
python "!PC_CAP!" %*

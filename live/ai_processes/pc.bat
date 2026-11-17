@echo off
setlocal EnableDelayedExpansion

:: pc.bat — shortcut for "python capabilities.py" (bar_analytic_live sub-project)
::
:: Upward search: walks CWD → parents looking for capabilities.py.
:: Falls back to this directory's capabilities.py.

set "PC_CAP="
set "_SEARCH=%CD%"

:search
if exist "!_SEARCH!\capabilities.py" (
    set "PC_CAP=!_SEARCH!\capabilities.py"
    goto :found
)
for %%A in ("!_SEARCH!") do set "_UP=%%~dpA"
if "!_UP:~-1!"=="\" set "_UP=!_UP:~0,-1!"
if /i "!_UP!"=="!_SEARCH!" goto :fallback
set "_SEARCH=!_UP!"
goto :search

:fallback
set "PC_CAP=%~dp0capabilities.py"

:found
set PC_CALLED_FROM=%CD%
set "_PEER=%USERPROFILE%\Documents\GitHub\ai_processes"
if exist "!_PEER!\capabilities_core.py" (
    set PC_BASE_DIR=!_PEER!
) else (
    set PC_BASE_DIR=%~dp0
)
python "!PC_CAP!" %*

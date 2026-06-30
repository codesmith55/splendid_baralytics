-- bar_analytic_live.config.lua — external config for the bar_analytic_live widget.
--
-- INSTALL: copy to  ...\Beyond-All-Reason\data\bar_analytic_live.config.lua
--   (the BAR write dir root — same folder the .jsonl stream is written to).
--   It sits OUTSIDE LuaUI/Widgets on purpose, so the widget handler never tries
--   to load it as a widget.
--
-- Every key is optional. Anything omitted falls back to the widget's built-in
-- default. Delete this file entirely and the widget still runs on its defaults.

return {
    -- Output path for the JSONL stream. RELATIVE paths resolve under the BAR write
    -- dir (...\data\). Absolute paths (e.g. "C:/...") are REJECTED by the widget io
    -- sandbox — that was the original "cannot open outPath" crash-log error. Keep it
    -- relative, and point bar_analytic_server.py at the matching absolute path.
    outPath           = "bar_analytic_live.jsonl",

    statsEverySec     = 0.5,  -- per-team value/economy snapshot cadence (dashboard tick)
    teamStatsEverySec = 15,   -- cumulative team_stats history snapshot
    windEverySec      = 5,    -- wind sampling cadence (0 disables wind_update emits)
    shareEverySec     = 1,    -- energy share/overflow sampling (0 disables energy_share emits)
    t2EverySec        = 3,    -- teamwide T2-factory poll cadence (ends each team's phase 2)
}

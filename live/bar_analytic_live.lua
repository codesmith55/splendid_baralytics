-- bar_analytic_live.lua — LIVE BAR client widget for the bar_analytic_live dashboard.
-- Streams per-team economy state as line-delimited JSON for a local consumer to tail.
--
-- New entity (supersedes the gex_live prototype). Event schema = gex `actions.json`,
-- EXTENDED: extra_stat_update now carries a per-team VALUE BREAKDOWN classified with
-- the repo's canonical buckets (process/lib/classify.mjs): military, defense,
-- build_power, economy, infrastructure, commander, other; value = metalCost+energyCost/70.
--
-- INSTALL: copy to  ...\Beyond-All-Reason\data\LuaUI\Widgets\bar_analytic_live.lua
-- CONFIG (optional): copy bar_analytic_live.config.lua to  ...\Beyond-All-Reason\data\
--   to override outPath / cadences without editing this widget. Defaults work as-is.
-- Spectate a game for full-vision (all teams). As a player you only see your own team.

-- Built-in defaults. Every key can be overridden by an external config file
-- (see CONFIG_FILE below) so paths/cadences aren't hardcoded into the widget.
local CONFIG = {
    -- RELATIVE path → resolves under the BAR write dir (...\data\). Absolute paths
    -- are rejected by the widget io sandbox — that was the original "cannot open
    -- outPath" bug. Keep this relative; point the dashboard server at the same file.
    outPath           = "bar_analytic_live.jsonl",
    statsEverySec     = 0.5,  -- per-team value/economy snapshot cadence (dashboard tick)
    teamStatsEverySec = 15,   -- cumulative team_stats history snapshot
    windEverySec      = 5,
    shareEverySec     = 1,    -- energy share/overflow sampling (0 disables energy_share emits)
    t2EverySec        = 3,    -- teamwide T2-factory poll cadence (ends each team's phase 2)
}

-- Optional external config: a loose `return { ... }` Lua file in the BAR write dir
-- (...\data\bar_analytic_live.config.lua). Anything it sets overrides the defaults
-- above; a missing/invalid file is fine — we just keep the defaults. Kept OUT of
-- LuaUI/Widgets so the widget handler never tries to load it as a widget.
local CONFIG_FILE = "bar_analytic_live.config.lua"
if VFS and VFS.FileExists and VFS.FileExists(CONFIG_FILE, VFS.RAW) then
    local ok, ext = pcall(VFS.Include, CONFIG_FILE, nil, VFS.RAW)
    if ok and type(ext) == "table" then
        for k, v in pairs(ext) do CONFIG[k] = v end
        Spring.Echo("[bar_analytic_live] loaded external config: " .. CONFIG_FILE)
    else
        Spring.Echo("[bar_analytic_live] config present but invalid; using defaults.")
    end
end

----------------------------------------------------------------------
local UNIT_VALUE   = {}   -- defID -> metalCost + energyCost/70 (commander = 1200)
local UNIT_BUCKET  = {}   -- defID -> "military"|"defense"|"build_power"|"economy"|"infrastructure"|"commander"|"other"
local UNIT_IS_MEX  = {}
local UNIT_IS_T2FAC = {}  -- defID -> true for T2 (advanced) factories — the phase-2 boundary
local UNIT_CONV_MS = {}   -- defID -> converter metal/s capacity (cap*eff)
local UNIT_DEF_NAMES = {}
local commanders   = {}
local BUILDER_UNITS = {}   -- unitID -> defID, all live units with buildSpeed > 0
local frame = 0
local spawnsSent = false   -- one-shot: capture commander landing positions at ~0:03
local F = nil

local COMMANDER_VALUE = 1200

-- Energy sharing / overflow tracking (Spring.GetTeamResources sent/received deltas)
local prevShare       = {}   -- teamID -> { sent, recv } cumulative energy at the last sample
local recentDonations = {}   -- teamID -> { {frame, energy} } explicit chat donations, netted out of overflow
local t2Flagged       = {}   -- allyTeamID -> true once a T2 factory is seen on that team

----------------------------------------------------------------------
local function writeVal(v)
    local t = type(v)
    if t == "string" then F:write("\"", (v:gsub("\"", "\\\"")), "\"")
    elseif t == "boolean" then F:write(v and "true" or "false")
    elseif t == "number" then
        if v ~= v then F:write("\"NaN\"")
        elseif v == math.huge or v == -math.huge then F:write("\"Infinity\"")
        else F:write(tostring(v)) end
    elseif v == nil then F:write("null")
    else F:write(tostring(v)) end
end

local function emit(action, data, includeFrame)
    if not F then return end
    F:write("{\"action\":\"", action, "\"")
    if includeFrame ~= false then F:write(",\"frame\":", tostring(frame)) end
    if data and #data > 0 then
        F:write(",")
        for i = 1, #data do
            F:write("\"", data[i][1], "\":"); writeVal(data[i][2])
            if i < #data then F:write(",") end
        end
    end
    F:write("}\n"); F:flush()
end

----------------------------------------------------------------------
function widget:GetInfo()
    return {
        name    = "bar_analytic_live",
        desc    = "Streams per-team economy value-breakdown for the bar_analytic_live realtime dashboard",
        author  = "splendid_baralytics",
        date    = "2026",
        license = "MIT",
        layer   = 0,
        enabled = true,
    }
end

-- "support" bucket: global-effect multipliers that aren't themselves combat/eco/intel.
-- Seeded by name (no distinguishing UnitDef field found yet); see others_to_be_classified.md.
local SUPPORT_NAMES = { armtarg = true, cortarg = true, armfatf = true, corfatf = true }

-- classify a UnitDef into a value bucket (mirrors process/lib/classify.mjs)
local function classify(v)
    if v.customParams.iscommander ~= nil then return "commander" end
    if v.isFactory then return "infrastructure" end
    if SUPPORT_NAMES[v.name] then return "support" end
    local hasWeapon = (v.weapons and #v.weapons > 0) or ((v.maxWeaponRange or 0) > 0)
    local bp = v.buildSpeed or 0
    local isEco =
        (v.totalEnergyOut or 0) > 0 or (v.windGenerator or 0) > 0 or (v.tidalGenerator or 0) > 0 or
        (tonumber(v.customParams.energyconv_capacity or "0") or 0) > 0 or
        (v.customParams.metal_extractor ~= nil) or (v.metalMake or 0) > 0 or
        (((v.metalStorage or 0) >= 500 or (v.energyStorage or 0) >= 2000) and not hasWeapon and bp == 0)
    if isEco and not hasWeapon then return "economy" end
    if bp > 0 and not hasWeapon then return "build_power" end
    -- electronic warfare / intel: radar, sonar, jammers, seismic. Field names vary across
    -- BAR builds (legacy *Distance* vs modern *Radius*), so probe both. Mobile EW (radar/jam
    -- bots) -> military; static EW (radar/jam/sonar towers) -> defense.
    local isIntel =
        (v.radarDistance or 0) > 0 or (v.radarRadius or 0) > 0 or
        (v.sonarDistance or 0) > 0 or (v.sonarRadius or 0) > 0 or
        (v.radarDistanceJam or 0) > 0 or (v.jammerRadius or 0) > 0 or
        (v.sonarDistanceJam or 0) > 0 or (v.sonarJamRadius or 0) > 0 or
        (v.seismicDistance or 0) > 0 or (v.seismicRadius or 0) > 0
    if hasWeapon or isIntel then
        if (v.speed or 0) > 0 then return "military" else return "defense" end
    end
    if bp > 0 then return "build_power" end
    return "other"
end

local function emitSession()
    local spec, fullView = Spring.GetSpectatingState()
    emit("session", {
        { "isSpectator", spec == true }, { "fullView", fullView == true },
        { "myTeamID", Spring.GetMyTeamID() }, { "myAllyTeamID", Spring.GetMyAllyTeamID() },
        { "mapName", Game.mapName or "" }, { "gameSeconds", Spring.GetGameSeconds() },
    })
    for _, teamID in ipairs(Spring.GetTeamList()) do
        if teamID ~= Spring.GetGaiaTeamID() then
            local _, leader, isDead, isAi, side, allyTeam = Spring.GetTeamInfo(teamID)
            local name = "?"
            if isAi then local _,_,_,aiName = Spring.GetAIInfo(teamID); name = aiName or "AI"
            elseif leader and leader >= 0 then name = Spring.GetPlayerInfo(leader) or "?" end
            local sx, _, sz = Spring.GetTeamStartPosition(teamID)
            emit("session_team", {
                { "teamID", teamID }, { "allyTeamID", allyTeam }, { "side", side or "" },
                { "name", name }, { "isAI", isAi == true },
                { "startX", sx or -1 }, { "startZ", sz or -1 },
            })
        end
    end
end

----------------------------------------------------------------------
function widget:Initialize()
    Spring.Echo("[bar_analytic_live] writing -> " .. CONFIG.outPath)
    if type(io) ~= "table" or io.open == nil then
        Spring.Echo("[bar_analytic_live] ERROR: io.open unavailable; cannot stream."); return
    end
    F = io.open(CONFIG.outPath, "w")
    if not F then Spring.Echo("[bar_analytic_live] ERROR: cannot open outPath."); return end
    if widgetHandler and widgetHandler.RegisterGlobal then
        widgetHandler:RegisterGlobal("UnitDamagedReplay", function() end)
    end

    emit("init", { { "version", 2 }, { "live", true } })
    emitSession()

    for k, v in pairs(UnitDefs) do
        UNIT_DEF_NAMES[k] = v.name
        local val = v.metalCost + (v.energyCost or 0) / 70
        local bucket = classify(v)
        if bucket == "commander" then val = COMMANDER_VALUE end
        UNIT_VALUE[k]  = val
        UNIT_BUCKET[k] = bucket
        if v.customParams.metal_extractor ~= nil or (v.extractsMetal or 0) > 0 then UNIT_IS_MEX[k] = true end
        if v.isFactory then
            local tech = tonumber(v.customParams.techlevel or v.customParams.techLevel or 1) or 1
            if tech >= 2 or (v.metalCost or 0) >= 1000 then UNIT_IS_T2FAC[k] = true end
        end
        local cap = tonumber(v.customParams.energyconv_capacity or "0") or 0
        local eff = tonumber(v.customParams.energyconv_efficiency or "0") or 0
        if cap > 0 and eff > 0 then UNIT_CONV_MS[k] = cap * eff end

        emit("unit_def", {
            { "defID", k }, { "defName", v.name }, { "name", v.translatedHumanName },
            { "metalCost", v.metalCost }, { "energyCost", v.energyCost }, { "value", val },
            { "bucket", bucket }, { "buildPower", v.buildSpeed },
            { "isMetalExtractor", v.customParams.metal_extractor ~= nil },
            { "energyConversionCapacity", cap }, { "energyConversionEfficiency", eff },
            { "isCommander", v.customParams.iscommander ~= nil }, { "isFactory", v.isFactory },
        }, false)
    end
    Spring.Echo("[bar_analytic_live] defs written; streaming live.")
end

function widget:GameStart()
    spawnsSent = false
    prevShare       = {}   -- reset share baselines for the new game
    recentDonations = {}
    t2Flagged       = {}
    emit("start", { { "mapSizeX", Game.mapSizeX }, { "mapSizeZ", Game.mapSizeZ } })
    emitSession()
end

-- At ~0:03 the commanders have landed; record each team's commander position as its spawn.
local function emitSpawns()
    local gaia = Spring.GetGaiaTeamID()
    for _, teamID in ipairs(Spring.GetTeamList()) do
        if teamID ~= gaia then
            -- engine start position = the commander's landing spot, valid from frame 0 and stable
            -- even if the widget is enabled mid-game. Fall back to the live commander position only
            -- if the start position is unset.
            local cx, _, cz = Spring.GetTeamStartPosition(teamID)
            if not cx or cx <= 0 then
                for _, u in ipairs(Spring.GetTeamUnits(teamID) or {}) do
                    if UNIT_BUCKET[Spring.GetUnitDefID(u)] == "commander" then
                        local x, _, z = Spring.GetUnitPosition(u); cx, cz = x, z; break
                    end
                end
            end
            emit("team_spawn", { { "teamID", teamID }, { "startX", cx or -1 }, { "startZ", cz or -1 } })
        end
    end
end
function widget:GameID(gameID) emit("game_id", { { "gameID", gameID } }) end

----------------------------------------------------------------------
local function sendExtraStats()
    local gaia = Spring.GetGaiaTeamID()
    for _, teamID in ipairs(Spring.GetTeamList()) do
        if teamID ~= gaia then
            local mC, mS, _, mInc = Spring.GetTeamResources(teamID, "metal")
            local eC, eS, _, eInc = Spring.GetTeamResources(teamID, "energy")
            if mC ~= nil then  -- nil when fogged (player view)
                local b = { military=0, defense=0, build_power=0, economy=0, infrastructure=0, commander=0, support=0, other=0 }
                local total, construction, bp, bpUsed, nMex, nConv, nUnitsCompleted = 0, 0, 0, 0, 0, 0, 0
                for _, u in ipairs(Spring.GetTeamUnits(teamID) or {}) do
                    local uid = Spring.GetUnitDefID(u)
                    local bucket = UNIT_BUCKET[uid] or "other"
                    local val = UNIT_VALUE[uid] or 0
                    local _, _, _, _, prog = Spring.GetUnitHealth(u)
                    if prog and prog < 1 then
                        -- under construction: only the invested fraction exists, and it produces
                        -- nothing until finished — the "+build time" drag in the ROI sense.
                        construction = construction + val * prog
                    else
                        b[bucket] = b[bucket] + val
                        total = total + val
                        nUnitsCompleted = nUnitsCompleted + 1
                        if UNIT_IS_MEX[uid] then nMex = nMex + 1 end
                        if UNIT_CONV_MS[uid] then nConv = nConv + 1 end
                        if (UnitDefs[uid] and (UnitDefs[uid].buildSpeed or 0) > 0) then
                            bp = bp + UnitDefs[uid].buildSpeed
                            if Spring.GetUnitWorkerTask(u) ~= nil then bpUsed = bpUsed + UnitDefs[uid].buildSpeed end
                        end
                    end
                end
                local storageValue = mC + eC / 70
                -- totalPlayerValue: all metal-equivalent resources under this player's control.
                -- = unit/building metal worth  +  liquid metal bank  +  energy-as-metal (E/70)
                local totalPlayerValue = total + storageValue
                emit("extra_stat_update", {
                    { "teamID", teamID }, { "totalValue", total },
                    { "militaryValue", b.military }, { "defenseValue", b.defense },
                    { "buildPowerValue", b.build_power }, { "ecoValue", b.economy },
                    { "infraValue", b.infrastructure }, { "commanderValue", b.commander },
                    { "supportValue", b.support }, { "otherValue", b.other },
                    { "constructionValue", construction }, { "storageValue", storageValue },
                    { "totalPlayerValue", totalPlayerValue }, { "nUnitsCompleted", nUnitsCompleted },
                    { "metalCurrent", mC }, { "energyCurrent", eC },
                    { "metalStorage", mS }, { "energyStorage", eS },
                    { "metalIncome", mInc or 0 }, { "energyIncome", eInc or 0 },
                    { "buildPowerAvailable", bp }, { "buildPowerUsed", bpUsed },
                    { "nMex", nMex }, { "nConv", nConv },
                })
            end
        end
    end
end

local function sendTeamStatsSnapshot()
    local gaia = Spring.GetGaiaTeamID()
    for _, teamID in ipairs(Spring.GetTeamList()) do
        if teamID ~= gaia then
            local n = Spring.GetTeamStatsHistory(teamID)
            if n and n > 0 then
                local hist = Spring.GetTeamStatsHistory(teamID, 0, n)
                if hist and hist[n] then
                    local data = { { "teamID", teamID } }
                    for k, v in pairs(hist[n]) do data[#data+1] = { k, v } end
                    emit("team_stats", data)
                end
            end
        end
    end
end

local function sendBuilderStatus()
    local gaia = Spring.GetGaiaTeamID()
    for uid, did in pairs(BUILDER_UNITS) do
        local teamID = Spring.GetUnitTeam(uid)
        if teamID and teamID ~= gaia then
            local x, _, z = Spring.GetUnitPosition(uid)
            -- GetUnitWorkerTask: non-nil = unit is actively building something (placing build power)
            -- GetUnitCurrentCommand: nil = no command queued at all (truly idle, ready for dispatch)
            local task = Spring.GetUnitWorkerTask(uid)
            local cmd  = Spring.GetUnitCurrentCommand(uid)
            emit("builder_status", {
                {"unitID", uid}, {"teamID", teamID}, {"defID", did},
                {"x", x or -1}, {"z", z or -1},
                {"building", task ~= nil},
                {"idle", cmd == nil},
            })
        end
    end
end

----------------------------------------------------------------------
-- Resource sharing / overflow between teammates. Two DISTINCT signals:
--   DONATION — an explicit player share, announced in chat as exactly:
--                "<player>: I sent <N> <metal|energy> to <other>"
--              with optional "...and they received <M> of it" when ezTax is on
--              (the N-M difference is lost to the void). Parsed precisely below.
--   OVERFLOW — auto-spill of excess ENERGY at the storage cap (never in chat). Derived
--              from the per-sample delta of Spring.GetTeamResources `sent`/`received`,
--              MINUS explicit donations in the same window (so they aren't double-counted).
--              X->Y pairing inferred inside an allyteam (outflow split across receivers
--              proportional to each receiver's inflow).
local function nameToTeam()
    local m = {}
    for _, teamID in ipairs(Spring.GetTeamList()) do
        local _, leader = Spring.GetTeamInfo(teamID)
        if leader and leader >= 0 then
            local pn = Spring.GetPlayerInfo(leader)
            if pn then m[pn] = teamID end
        end
    end
    return m
end

function widget:AddConsoleLine(line, priority)
    if not line then return end
    -- "<player>: I sent <N> <metal|energy> to <other>[ and they received <M> of it]"
    local fromName, amt, res, rest = line:match("(%S[^:]-): I sent (%d+) (%a+) to (.+)")
    if not fromName or (res ~= "energy" and res ~= "metal") then return end
    amt = tonumber(amt)
    local toName, recv = rest:match("^(.-) and they received (%d+)")
    if toName then recv = tonumber(recv) else toName, recv = rest, amt end
    toName = toName:gsub("%s+$", "")
    local map = nameToTeam()
    local fromTeam, toTeam = map[fromName], map[toName]
    if not fromTeam or not toTeam then return end             -- couldn't resolve both players
    emit("resource_share", {
        { "fromTeam", fromTeam }, { "toTeam", toTeam }, { "resource", res },
        { "amount", recv }, { "sent", amt }, { "received", recv },
        { "taxed", math.max(0, amt - recv) }, { "kind", "donation" },
    })
    if res == "energy" then                                    -- net out of overflow detection
        local rd = recentDonations[fromTeam] or {}
        rd[#rd + 1] = { frame = frame, energy = amt }
        recentDonations[fromTeam] = rd
    end
end

local function sendEnergyShares()
    local gaia   = Spring.GetGaiaTeamID()
    local byAlly = {}   -- allyTeamID -> { senders = {...}, receivers = {...} }
    for _, teamID in ipairs(Spring.GetTeamList()) do
        if teamID ~= gaia then
            local _, _, _, _, _, _, eSent, eRecv = Spring.GetTeamResources(teamID, "energy")
            if eSent ~= nil then
                local prev  = prevShare[teamID] or { sent = eSent, recv = eRecv }
                local dSent = math.max(0, eSent - prev.sent)
                local dRecv = math.max(0, eRecv - prev.recv)
                prevShare[teamID] = { sent = eSent, recv = eRecv }
                -- subtract explicit chat donations (last ~1.5s) from this team's outflow
                local donated, rd = 0, recentDonations[teamID]
                if rd then
                    for i = #rd, 1, -1 do
                        if frame - rd[i].frame > 45 then table.remove(rd, i)
                        else donated = donated + rd[i].energy end
                    end
                end
                local overflowSent = math.max(0, dSent - donated)
                local _, _, _, _, _, allyTeam = Spring.GetTeamInfo(teamID)
                local a = byAlly[allyTeam]
                if not a then a = { senders = {}, receivers = {} }; byAlly[allyTeam] = a end
                if overflowSent > 0.5 then a.senders[#a.senders + 1] = { teamID = teamID, amount = overflowSent } end
                if dRecv > 0.5 then a.receivers[#a.receivers + 1]     = { teamID = teamID, amount = dRecv } end
            end
        end
    end
    for _, a in pairs(byAlly) do
        local totalRecv = 0
        for _, r in ipairs(a.receivers) do totalRecv = totalRecv + r.amount end
        if totalRecv > 0 then
            for _, s in ipairs(a.senders) do
                for _, r in ipairs(a.receivers) do
                    if r.teamID ~= s.teamID then
                        local amt = s.amount * (r.amount / totalRecv)
                        if amt > 0.5 then
                            emit("resource_share", {
                                { "fromTeam", s.teamID }, { "toTeam", r.teamID },
                                { "resource", "energy" }, { "amount", math.floor(amt + 0.5) },
                                { "kind", "overflow" },
                            })
                        end
                    end
                end
            end
        end
    end
end

-- Teamwide T2 poll: every t2EverySec, scan each allyteam's units for a T2 factory
-- (nanoframes are units too → fires at construction START). Emits t2_reached once per
-- allyteam — the authoritative end of phase 2 (independent of the capped build log).
local function checkTeamT2()
    local gaia = Spring.GetGaiaTeamID()
    for _, teamID in ipairs(Spring.GetTeamList()) do
        if teamID ~= gaia then
            local _, _, _, _, _, allyTeam = Spring.GetTeamInfo(teamID)
            if not t2Flagged[allyTeam] then
                for _, u in ipairs(Spring.GetTeamUnits(teamID) or {}) do
                    local did = Spring.GetUnitDefID(u)
                    if UNIT_IS_T2FAC[did] then
                        t2Flagged[allyTeam] = true
                        emit("t2_reached", {
                            { "allyTeamID", allyTeam }, { "teamID", teamID },
                            { "defID", did }, { "defName", UNIT_DEF_NAMES[did] },
                        })
                        break
                    end
                end
            end
        end
    end
end

function widget:GameFrame(n)
    frame = n
    if not spawnsSent and n >= 90 then spawnsSent = true; emitSpawns() end
    if CONFIG.windEverySec > 0 and n % math.floor(30 * CONFIG.windEverySec) == 0 then
        local wx, _, wz, ws = Spring.GetWind()
        emit("wind_update", { { "value", ws }, { "windX", wx }, { "windZ", wz } })
    end
    local statN = math.max(1, math.floor(30 * CONFIG.statsEverySec))
    if n % statN == 0 then sendExtraStats() end
    if n % 60 == 0 then sendBuilderStatus() end   -- builder idle/position state every 2s
    if CONFIG.shareEverySec > 0 and n % math.floor(30 * CONFIG.shareEverySec) == 0 then sendEnergyShares() end
    if CONFIG.t2EverySec > 0 and n % math.floor(30 * CONFIG.t2EverySec) == 0 then checkTeamT2() end
    if n % math.floor(30 * CONFIG.teamStatsEverySec) == 0 then sendTeamStatsSnapshot() end
end

----------------------------------------------------------------------
function widget:UnitCreated(unitID, unitDefID, teamID)
    if UNIT_BUCKET[unitDefID] == "commander" then commanders[unitID] = unitID end
    if (UnitDefs[unitDefID] and (UnitDefs[unitDefID].buildSpeed or 0) > 0) then
        BUILDER_UNITS[unitID] = unitDefID
    end
    local x, y, z = Spring.GetUnitPosition(unitID)
    emit("unit_created", {
        { "unitID", unitID }, { "teamID", teamID }, { "defID", unitDefID },
        { "defName", UNIT_DEF_NAMES[unitDefID] }, { "unit_x", x }, { "unit_y", y }, { "unit_z", z },
    })
end
function widget:UnitFromFactory(unitID, unitDefID, unitTeam, factID, factDefID)
    emit("factory_unit_created", {
        { "unitID", unitID }, { "defID", unitDefID }, { "teamID", unitTeam },
        { "factoryID", factID }, { "factoryDefID", factDefID },
    })
end
function widget:UnitDestroyed(unitID, unitDefID, teamID, attackerID, attackerDefID, attackerTeam, weaponDefID)
    commanders[unitID] = nil
    BUILDER_UNITS[unitID] = nil
    emit("unit_killed", {
        { "unitID", unitID }, { "teamID", teamID }, { "defID", unitDefID },
        { "defName", UNIT_DEF_NAMES[unitDefID] }, { "attackerTeam", attackerTeam }, { "weaponDefID", weaponDefID },
    })
end
function widget:UnitGiven(unitID, unitDefID, newTeamID, teamID)
    emit("unit_given", { { "unitID", unitID }, { "teamID", teamID }, { "newTeamID", newTeamID }, { "defID", unitDefID } })
end
function widget:UnitTaken(unitID, unitDefID, oldTeamID, teamID)
    emit("unit_taken", { { "unitID", unitID }, { "teamID", oldTeamID }, { "newTeamID", teamID }, { "defID", unitDefID } })
end
function widget:TeamDied(teamID) emit("team_died", { { "teamID", teamID } }) end

function widget:GameOver(winningAllyTeams)
    sendExtraStats()  -- flush final per-team values before the end marker
    local winners = {}
    if type(winningAllyTeams) == "table" then for _, a in ipairs(winningAllyTeams) do winners[#winners+1] = a end end
    emit("end", { { "ingame", Spring.GetGameSeconds() }, { "winners", table.concat(winners, ",") } })
    sendTeamStatsSnapshot()
    Spring.Echo("[bar_analytic_live] game over — stream finalized.")
end
function widget:Shutdown()
    if widgetHandler and widgetHandler.DeregisterGlobal then widgetHandler:DeregisterGlobal("UnitDamagedReplay") end
    if F then emit("shutdown", { { "done", "done" } }); F:close(); F = nil end
end

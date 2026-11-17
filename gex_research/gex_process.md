# gex_process.md — using Gex to extract per-player / per-team BAR stats

> Research notes for `splendid_baralytics`. Source repo read: `C:\Users\codes\Documents\GitHub\gex`
> (commit at read time: `e3628870`-era working tree). Read-only pass — nothing in gex was modified or run.
> All file paths below are relative to `gex/gex/` unless prefixed otherwise.

---

## Overview

**Gex** ("Beyond All Reason game extractor") is a C# / ASP.NET (dotnet 9) web server that:

1. **Ingests** public BAR games by polling the official BAR API (`https://api.bar-rts.com`), or by direct upload.
2. **Downloads** the demofile (`.sdfz` replay) for each game.
3. **Parses the demofile** to extract match metadata, players, teams, ally-teams, chat, commands.
4. **Replays the game locally and headlessly** in the real Recoil/Spring engine (`spring-headless`), with a custom Lua widget (`gex.lua`) loaded that dumps game events/stats to a flat file (`actions.json`).
5. **Parses that action log** back into C# objects and **persists every event/stat to a PostgreSQL DB**, then exposes it all via a JSON REST API and a Vue front-end.

So there are **two independent stat sources**:
- **(A) Demofile parse** — cheap, no engine needed. Gives roster, APM-ish input counts, and the engine's own per-team frame-by-frame stat history embedded in the replay.
- **(B) Headless widget replay** — expensive (runs the actual game), but gives rich per-unit / per-team economy, damage, value-composition, positions, and APM.

**Runtime modes / components** (from `gex/root.sln` and the READMEs):
- `gex` — the web server + processing pipeline + front end (the bulk; what we care about).
- `gex.Common` — shared models/services (engine download, pr-downloader, demofile bits).
- `gex.Familiar` — worker "drone" that can record & simulate games in real time, uploading results back to a coordinator over SignalR.
- `gex.Tests`, `gex.TestUpload`, `wiresharkDump` — tests + a SpringLobby packet dumper. Not relevant to stats.

**Prereqs to actually run gex** (`gex/gex/README.md`): PostgreSQL 13+, 7zip on PATH, npm, dotnet 9, an x86-64 CPU (headless replay refuses to run otherwise — `BarHeadlessInstance.RunGame` checks `RuntimeInformation.ProcessArchitecture`). Copy `secrets.template.json`→`secrets.json` and `env.template.json`→`env.json`, then `dotnet build && npm install && npm run build && dotnet run`, view at `https://localhost:6001/`.

**Vocabulary** (the engine's, which gex reuses — important, easy to mix up):
- **team** = a single army / one player's economy (NOT a side). PK-ish unit for most stats.
- **allyTeam** = a side of the fight (can contain multiple teams).
- **unit** = includes buildings.

---

## How to: pull replays

All BAR-API access is in `Services/BarApi/BarReplayApi.cs` (base URL `https://api.bar-rts.com`, hardcoded).

- **List recent replays:** `BarReplayApi.GetRecent(page=1, limit=50, cancel)` →
  `GET /replays?page={page}&limit={limit}&hasBots=false&endedNormally=true` → `List<BarRecentReplay>`.
- **Get one replay's metadata:** `BarReplayApi` also fetches per-game detail (used to populate `BarReplay` / `BarMatch`). See `Services/BarApi/BarReplayFileApi.cs` for the **demofile download** (the actual `.sdfz` bytes).
- **In the pipeline this is automated** by `Services/Hosted/QueueProcessor/GameReplayDownloadQueueProcessor.cs`, which pulls the replay file and drops it at `FileStorageOptions.ReplayLocation`.
- **Front-end / REST equivalents** (no code needed, just hit the running server):
  - `GET /api/match/recent` — recent processed matches (`BarMatchApiController.GetRecent`).
  - `GET /api/match/search` — search matches (`BarMatchApiController.Search`).
  - `GET /api/match/{gameID}` — full match incl. players/allyteams (`GetMatch`).
  - `POST /api/match-upload/upload` (and `/upload-familiar`, `/upload-third-party`, `/inspect`) — push a demofile in directly (`MatchUploadApiController`). Upload endpoints are JWT-gated (see README "jwts").

The periodic poller that keeps pulling new games lives under `Services/Hosted/PeriodicTasks/` + `Services/Hosted/BackgroundTasks/` (the recurring "get recent → enqueue download → enqueue parse" loop).

---

## How to: run a replay through headless

**Entry point:** `Services/BarApi/BarHeadlessInstance.cs` →
`Task<Result<GameOutput,string>> RunGame(string gameID, bool force, TimeSpan timeout, CancellationToken cancel)`.

**Driven by the queue:** `Services/Hosted/QueueProcessor/HeadlessRunQueueProcessor.cs` consumes `HeadlessRunQueueEntry { GameID, Force, ForceForward }`.

**Manual trigger (REST):** `POST /api/match-processing/run/{gameID}`
(`BarMatchProcessingApiController.ForceGameRun`, permission `GEX_MATCH_FORCE_REPLAY`) — enqueues a forced headless run. Note the warning in code: if the `headless_run_queue_processor` service is disabled, the game won't actually run.

**What `RunGame` does, step by step** (cite `BarHeadlessInstance.cs`):
1. Guard: must be amd64; match must exist in `BarMatchRepository`; game version must not be flagged bad; demofile must exist at `ReplayLocation/{match.FileName}` and be ≤ 64 MB.
2. If `GameOutputStorage.HasActionLog(gameID)` and not forced → short-circuits, returns empty `GameOutput` (already ran). If forced, deletes the old action log first.
3. Downloads engine (`BarEngineDownloader`), game version + map (`PrDownloaderService`) if missing.
4. **Installs the widget:** copies `./gex.lua` → `{enginePath}/LuaUI/Widgets/gex.lua`, and copies `./BYAR.lua` → `{dataDir}/LuaUI/Config/BYAR.lua` to force-enable the widget (`BYAR.lua` is just `order = { game_event_extractor = 1 }`).
5. Writes a start script `{enginePath}/_script-{gameID}.txt` containing `[game] { demofile=...; HostPort=<port>; }` (port = `50000 + offset`).
6. Launches `spring-headless(.exe)` with `--write-dir "{dataDir}" "{scriptsFile}"`, `dataDir = {enginePath}/data-{gameID}`. Stdout/stderr are captured.
7. Watches stdout with regexes: `[Gex] on frame (\d+)` for progress, `Failed to load: gex.lua` (kills run — widget didn't load), `[SpringApp::Kill][1] fromRun=1` (game ended), plus `Error:` / `Fatal:` patterns. Emits live `HeadlessRunStatus` updates (frame, fps, eta) over SignalR (`HeadlessReplayHub`) and a status queue. Default cap ~10 min unless forced.

**Where outputs land:**
- The widget writes **`actions.json`** into the engine **write-dir** (`{enginePath}/data-{gameID}/`), appending one JSON object per line (see widget `writeJson` → `io.open("actions.json","a")`).
- Gex then relocates/stores it under the game-log tree. `GameOutputStorage.GetGameLogLocation(gameID)` = `FileStorageOptions.GameLogLocation/{gameID[0..2]}/{gameID}/`, holding either **`actions.json`** or a zstd-compressed **`actions.zstd`** (`GameOutputStorage` reads/writes both; `Services/Storage/GameOutputStorage.cs`).
- Unit positions are split out to their own file via `Services/Storage/UnitPositionFileStorage.cs` (not kept in the DB row-per-event).

So: **the raw per-game stat dump is the line-delimited JSON `actions.json` / `actions.zstd`** in the game-log folder. Everything else is derived from parsing that.

---

## How to: extract per-player / per-team stats from a replay

There are three layers you can tap, cheapest first.

### Layer 1 — Demofile parse (no engine run)
`Services/Parser/BarDemofileParser.cs` (+ `Services/BarApi/ActionLogParser` is the *other* parser; don't confuse them). The demofile parser produces:
- **Per-player:** `Models/Demofile/DemofilePlayerStats.cs` — `PlayerID, CommandCount, UnitCommands, MousePixels, MouseClicks, KeyPresses`. (This is the raw material for APM / input-intensity stats, straight from the replay, no replay-run needed.)
- **Per-team, per-frame:** `Models/Demofile/DemofileTeamStats.cs` → `List<DemofileTeamFrameStats>`; each `DemofileTeamFrameStats` = `{ TeamID, Frame, MetalUsed, EnergyUsed, MetalProduced, EnergyProduced, MetalExcess, EnergyExcess, MetalReceived, EnergyReceived, MetalSend, EnergySend, DamageDealt, DamageReceived, UnitsProduced, UnitsDied, UnitsReceived, UnitsSent, UnitsCaptured, UnitsOutCaptured, UnitsKilled }`. This is the engine's own stat history baked into the replay.
- **Roster / match shape:** `Models/Db/BarMatchPlayer.cs` (`PlayerID, UserID, Name, TeamID, AllyTeamID, Faction, StartingPosition, Skill, SkillUncertainty, Color, Handicap, CountryCode`), `BarMatchAllyTeam`, `BarMatchSpectator`, `BarMatchAiPlayer`, `BarMatchChatMessage`, `BarMatchTeamDeath`, `BarMatchMapDraw`, `BarCommand`.
- Persisted by `GameReplayParseQueueProcessor.cs` via `BarMatchRepository`, `BarMatchPlayerRepository`, `BarMatchAllyTeamDb`, `BarReplayDb`, etc.

### Layer 2 — Headless widget replay → action log (`gex.lua`)
`gex.lua` (902 lines) is the widget `game_event_extractor`. It hooks engine call-ins and appends events to `actions.json`. The **stat-bearing** events, with granularity:

- **`team_stats`** (per **team**, emitted at `GameOver` for every frame of history) — from `Spring.GetTeamStatsHistory`. → `Models/Event/GameEventTeamStats.cs`: `metalProduced, metalUsed, metalExcess, metalSent, metalReceived, energyProduced, energyReceived, energySent, energyExcess, energyUsed, damageDealt, damageReceived, unitsProduced, unitsKilled, unitsSent, unitsReceived, unitsCaptured, unitsOutCaptured` (+ base `GameID, Frame`).
- **`extra_stat_update`** (per **team**, every 450 frames = 15 s, plus at GameOver) — gex's *custom* composition + APM stats. → `Models/Event/GameEventExtraStatUpdate.cs`: `totalValue, armyValue, defenseValue, utilValue, ecoValue, otherValue, buildPowerAvailable, buildPowerUsed, metalCurrent, energyCurrent, actions` (APM proxy; `actions` is per-team action count this window). Composition is computed in the widget's `SendExtraStats()` by bucketing each unit's metal cost into army/def/util/eco/other via `UNIT_TYPE_*` tables.
- **`unit_resources`** (per **unit**, emitted at GameOver / on death) — lifetime integrated economy per unit. → `Models/Event/GameEventUnitResources.cs`: `unitID, teamID, definitionID, metalMade, metalUsed, energyMade, energyUsed`. (Widget accumulates `Spring.GetUnitResources/30` each frame.)
- **`unit_damage`** (per **unit**) — `unitID, defID, teamID, dealt, taken, experience`. → `Models/Event/GameEventUnitDamage.cs`.
- **`unit_created` / `unit_killed` / `unit_given` / `unit_taken` / `factory_unit_created`** (per **unit**, tagged with `teamID`) → `GameEventUnitCreated/UnitKilled/UnitGiven/UnitTaken/FactoryUnitCreated.cs`. Roll up to per-team/per-player unit production & kill counts.
- **`commander_position_update`** (per commander unit, every 150 frames) and **`unit_position`** (per unit, every 900 frames) — spatial. Positions go to `UnitPositionFileStorage`, not DB rows.
- **`wind_update`** (global, every 150 frames), **`team_died`** (per team), **`unit_def`** (global unit-definition dump emitted at `Initialize`), `start` / `end` / `shutdown` (global markers; `end` carries `realtime`, `ingame` seconds).

**Parsing:** `Services/BarApi/ActionLogParser.cs` → `Parse(gameID)` reads `actions.json` line-by-line and fills `Models/Event/GameOutput.cs` (lists of every event type above). Per-event JSON keys map to C# props via `[JsonActionLogPropertyName(...)]` (see `Code/JsonActionLogPropertyName.cs` + the `JsonExtensions.UseActionLogNames` modifier).

**Persistence:** `Services/Hosted/QueueProcessor/ActionLogParseQueueProcessor.cs` inserts each list into its own repo/table: `ExtraStatsDb`, `TeamStatsDb`, `UnitCreatedDb`, `UnitDamageDb`, `UnitKilledDb`, `UnitGivenDb`, `UnitTakenDb`, `UnitResourcesDb`, `CommanderPositionDb`, `FactoryCreateDb`, `TeamDiedDb`, `TransportLoaded/UnloadedDb`, `WindUpdateDb`, `UnitDefDb` (+ `GameIdToUnitDefHash`), and `UnitPositionStorage` (disk). Each event row carries `game_id` + `frame`, so any of these can be re-bucketed per team → per player (player↔team via `BarMatchPlayer.TeamID`).

### Layer 3 — Derived / aggregated stats
- **`GameUnitsCreated`** (`Models/Event/GameUnitsCreated.cs`, table via `GameUnitsCreatedRepository`) — **per game × team × user × unit-definition** counts ("how many of unit X this player built"). Generated by `_UnitsCreatedDb.Generate(gameID)` at the end of `ActionLogParseQueueProcessor`. This is the closest existing **per-player** rollup.
- **User-level rollups** (`Models/UserStats/`): `BarUserUnitsMade`, `BarUserFactionStats`, `BarUserMapStats`, `BarUserSkill(/Changes)`, `BarUserInteractions`, `UserUnitsMadeLeaderboardEntry`. Updated by `UserFactionStatUpdateQueueProcessor`, `UserMapStatUpdateQueueProcessor`, etc.
- **Map-level rollups** (`Models/MapStats/`): start-spot heatmaps, opening-lab, units-made-by-day, plays-by-faction/gamemode.

### Reading the stats back out (REST)
- `GET /api/game-event/{gameID}` → **`GameOutput`** (the full parsed event set for a game) — `Controllers/Api/GameEventApiController.GetEvents`. **This is the single most useful endpoint for us**: one call returns every per-team/per-unit stat list for a replay.
- `GET /api/match/{gameID}` → match + players/allyteams.
- `GET /api/match/{gameID}/stdout` → raw engine stdout from the headless run (debugging).

---

## Stat catalog (everything gex already dumps to file)

`G` = global, `T` = per-team (≈ per-player, 1 team = 1 army), `U` = per-unit, `P` = per-player (input). Source: `API`=BAR API, `DF`=demofile parse, `WID`=headless widget (`gex.lua`/`GetTeamStatsHistory`), `DER`=derived.

| Stat | Gran | Source | Event / model | Notes |
|---|---|---|---|---|
| metalProduced / metalUsed / metalExcess / metalSent / metalReceived | T | WID | `GameEventTeamStats` | engine stat history, per frame |
| energyProduced / energyUsed / energyExcess / energySent / energyReceived | T | WID | `GameEventTeamStats` | |
| damageDealt / damageReceived | T | WID | `GameEventTeamStats` | |
| unitsProduced / unitsKilled / unitsSent / unitsReceived / unitsCaptured / unitsOutCaptured | T | WID | `GameEventTeamStats` | |
| (same metal/energy/damage/units set, per frame) | T | DF | `DemofileTeamFrameStats` | from the replay itself, no run needed |
| totalValue / armyValue / defenseValue / utilValue / ecoValue / otherValue | T | WID | `GameEventExtraStatUpdate` | metal-cost composition buckets, every 15 s |
| buildPowerAvailable / buildPowerUsed | T | WID | `GameEventExtraStatUpdate` | BP utilization |
| metalCurrent / energyCurrent | T | WID | `GameEventExtraStatUpdate` | stored resources snapshot |
| actions (APM) | T | WID | `GameEventExtraStatUpdate` | per-window action count |
| commandCount / unitCommands / mousePixels / mouseClicks / keyPresses | P | DF | `DemofilePlayerStats` | raw input intensity, per player |
| metalMade / metalUsed / energyMade / energyUsed (lifetime) | U | WID | `GameEventUnitResources` | tagged w/ teamID, defID |
| damage dealt / taken / experience | U | WID | `GameEventUnitDamage` | tagged w/ teamID, defID |
| unit created / killed / given / taken / from-factory | U→T | WID | `GameEventUnitCreated/Killed/Given/Taken/FactoryUnitCreated` | each tagged w/ teamID |
| unit positions / commander positions | U | WID | `GameEventUnitPosition` / `…CommanderPositionUpdate` | to disk (`UnitPositionFileStorage`) |
| wind value | G | WID | `GameEventWindUpdate` | every 5 s |
| team died | T | WID | `GameEventTeamDied` | |
| unit definitions (name, metal, health, build power, is-commander) | G | WID | `GameEventUnitDef` | dumped once at init |
| units-made count (game × team × user × unitdef) | P | DER | `GameUnitsCreated` | **only existing per-player unit rollup** |
| faction / map / skill / interaction rollups | P | DER | `Models/UserStats/*` | cross-game |
| roster: name, userID, team, allyTeam, faction, start pos, skill, color, handicap, country | P | DF | `BarMatchPlayer` | |
| match: engine, version, map, start, duration, gamemode, settings, OS spread | G | DF/API | `BarMatch` | |

---

## Gaps and extension surface — where to plug in NEW stat calculations

Our goal ("run a replay per player/per team, dump stats, then **calculate new stats**") maps cleanly onto gex's pipeline. Three viable insertion points, easiest → most invasive:

**1. Downstream / external (recommended first move — zero gex changes).**
Hit `GET /api/game-event/{gameID}` (returns `GameOutput`) + `GET /api/match/{gameID}` (roster), and compute new stats **in `splendid_baralytics`**. We already have a JS/TS analysis codebase here (`splendid_buildAnalyzer.ts`, `src/`, `bar-calc/`). New per-player/per-team derived metrics (e.g. eco efficiency = `metalUsed / metalProduced`, army-value-over-time slopes, BP idle %, damage-per-metal, APM-adjusted, opening build orders from `unit_created` frames) are just functions over the event lists. **No engine, no DB, no gex build.** This is the fastest path to "calculate new stats."

**2. In-widget (capture data gex doesn't emit yet).** If a new stat needs game-state gex isn't currently sampling (e.g. radar coverage, line-of-sight, eco stall events, per-unit idle time, reclaim income split), add a new `writeJson("my_event", {...})` call in `gex/gex/gex.lua` against the relevant Spring call-in, then a matching `GameEvent*` model + `[JsonActionLogPropertyName]` mappings + a list on `GameOutput` + parse/insert wiring in `ActionLogParser` & `ActionLogParseQueueProcessor`. This is the only way to get **new raw signal** out of the replay. Heaviest path (requires re-running every replay).

**3. Post-parse aggregation hook (new derived tables, inside gex).** The cleanest in-repo extension point for *derived* per-player stats is to follow the **`GameUnitsCreated` pattern**: it's a derived table generated at the tail of `ActionLogParseQueueProcessor._ProcessQueueEntry` via `_UnitsCreatedDb.Generate(gameID, cancel)` (see `Services/Repositories/GameUnitsCreatedRepository.cs` + `Models/Event/GameUnitsCreated.cs`). To add a new derived stat: (a) new `Models/...` class with `[ColumnMapping]`, (b) new repo with a `Generate(gameID)` that reads the already-inserted event tables and writes the rollup, (c) call it right after line ~202 in `ActionLogParseQueueProcessor.cs`, (d) expose via a new controller route mirroring `GameEventApiController`. User-level cross-game rollups follow the `UserFactionStatUpdateQueueProcessor` / `Models/UserStats/*` pattern instead.

**Quoted hook (the place to graft #3):** `Services/Hosted/QueueProcessor/ActionLogParseQueueProcessor.cs` — after all `InsertMany` calls and the `_ProcessingRepository.Upsert(processing)`, it calls `await _UnitsCreatedDb.Generate(entry.GameID, cancel);`. New `*.Generate(gameID)` calls belong here.

---

## Open questions (need code-dive or user confirmation before building)

1. **Player↔team join for stat rollups.** Most rich stats are keyed by `teamID`; `BarMatchPlayer` has `TeamID`. Need to confirm there's exactly one player per team in the gamemodes we care about (1v1 yes; team games — does each player own one `teamID`, with shared-eco handled via `unitsSent/Received`?). Verify against `BarMatchAllyTeam` structure.
2. **`team_stats` vs `DemofileTeamFrameStats` — same numbers?** Both claim engine stat history. If the demofile already carries per-frame team stats, **Layer 1 may make a full headless run unnecessary for economy stats** — only `extra_stat_update` (value composition, BP, APM) and per-unit data truly require the widget run. Worth empirically diffing one game.
3. **APM definition.** `extra_stat_update.actions` (widget, copied from BAR's `game_apm_broadcast.lua`) vs `DemofilePlayerStats.commandCount/unitCommands`. Which is "real" APM, and are they per-window or cumulative? The widget resets `teamAddedActionFrame` each frame — confirm the windowing.
4. **Is a public gex server already running** (git dot honu dot pw, per README) that we can query for `/api/game-event/{gameID}` without standing up our own Postgres + headless stack? If so, Layer-1 extension needs no gex deployment at all.
5. **Unit-position fidelity.** Positions sampled every 900 frames (30 s) and stored to disk, not DB. For movement/heatmap stats that may be too coarse — would need a widget change (#2) to sample denser.
6. **`actions.zstd` format.** Confirm it's just zstd-compressed line-delimited JSON (it reads that way in `GameOutputStorage`) so we can parse dumps directly off disk without the gex server.

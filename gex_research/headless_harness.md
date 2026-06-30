# headless_harness.md — running BAR replays headlessly WITHOUT the full Gex stack

> Goal: reproduce Gex's "replay → `actions.json`" step locally to feed our own analytics, while
> skipping the web server, PostgreSQL, queues, SignalR, lobby, and front end.
> Source of truth: `C:\Users\codes\Documents\GitHub\gex`. Read-only research — nothing run/modified.
> Companion: [`gex_process.md`](./gex_process.md) (the stat catalog this harness produces).

---

## TL;DR — what the harness actually is

Gex's headless run is **just a `spring-headless` process** launched against a demofile, with one Lua
widget installed that writes events to `actions.json`. Everything else in Gex (DB, API, queues) is
bookkeeping *around* that core. The irreducible recipe (all of it lifted directly from
`Services/BarApi/BarHeadlessInstance.cs` + `gex.Common/Services/Bar/*`):

```
spring-headless --write-dir "<WRITE_DIR>" "<SCRIPT_FILE>"
```
…with `gex.lua` in `<ENGINE>/LuaUI/Widgets/` and `BYAR.lua` in `<WRITE_DIR>/LuaUI/Config/`, where
`<SCRIPT_FILE>` contains `[game] { demofile=<...>; HostPort=<port>; }`. Output: **`<WRITE_DIR>/actions.json`**
(line-delimited JSON). Parse that ourselves — no C# required downstream.

**The entire heavy C# pipeline reduces to ~6 shell steps + 2 file copies.** We do NOT need to port any
C#; we only need the engine binary, BAR's `pr-downloader`, 7-zip, the two Lua files (copy from the gex
repo), and the demofile.

---

## Inputs needed per game (4 fields)

| Field | Example | Where to get it |
|---|---|---|
| `Engine` | `2025.01.6` | gex public API `GET /api/match/{gameID}` → `.engine`; or BAR API `GET https://api.bar-rts.com/replays/{gameID}` |
| `GameVersion` | `Beyond All Reason test-27562-33e445c` | same → `.gameVersion` |
| `Map` | `All That Glitters v2.2` | same → `.map` |
| `FileName` | `2025-...-....sdfz` | same → `.fileName` (the demo filename) |

`ApiMatch` (`Models/Api/ApiMatch.cs`) exposes all four. So: **hit the public gex API once for metadata,
then run everything else locally.** (We can also parse these from the demofile header ourselves later to
drop the gex-API dependency entirely — see "Cutting the last cord".)

---

## The 8 steps (each cites the gex source it's copied from)

### 0. One-time prereqs
- **x86-64 CPU** — `BarHeadlessInstance.RunGame` refuses on non-amd64 (`RuntimeInformation.ProcessArchitecture`). Recoil headless is amd64-only.
- **7-zip on PATH** (`7z`) — used to extract the engine archive (`BarEngineDownloader`).
- Pick four working dirs (Gex calls these `FileStorageOptions`, `gex.Common/Models/Options/FileStorageOptions.cs`):
  `ENGINES/`, `REPLAYS/`, `MAPS/`, `GAMELOGS/`.

### 1. Download + extract the engine
From `BarEngineDownloader.cs`. Engine install path convention (`EnginePathUtil.Get`): `ENGINES/{version}-win` on Windows, `-linux` on Linux.

URL templates (tried in order), base `https://github.com/beyond-all-reason/spring/releases/download`:
```
{version}/spring_bar_.rel2501.{version}_{windows|linux}-64-minimal-portable.7z
{version}/recoil_{version}_amd64-{windows|linux}.7z
```
Download to `ENGINES/{version}-win/engine.7z`, then `7z x -y engine.7z` **inside that dir**. The archive
ships `spring-headless(.exe)` and `pr-downloader(.exe)` at the engine root.

### 2. Download the game version (via pr-downloader)
From `PrDownloaderService.GetGameVersionInternal`. Run the engine's own `pr-downloader`:
```
pr-downloader --filesystem-writepath "<ENGINE>/games/<GameVersion>" --download-game "<GameVersion>"
```
**Required env vars** (without these it hits the wrong CDN):
```
PRD_RAPID_USE_STREAMER = false
PRD_HTTP_SEARCH_URL    = https://files-cdn.beyondallreason.dev/find
PRD_RAPID_REPO_MASTER  = https://repos-cdn.beyondallreason.dev/repos.gz
```
Done-marker convention: Gex writes a `done.txt` byte into `<ENGINE>/games/<GameVersion>/` to signal a
complete download (`HasGameVersion` checks for it). Replicate so re-runs skip re-downloading.

### 3. Download the map (via pr-downloader)
From `PrDownloaderService.GetMap`. Maps go to a shared cache, then get copied into the engine:
```
pr-downloader --filesystem-writepath "<MAPS>" --download-map "<Map>"
```
The file lands at `<MAPS>/maps/<map>.sd7` (name lowercased + filesystem-escaped via
`EscapeRecoilFilesytemCharacters`). Then **copy** it to `<ENGINE>/maps/maps/<map>.sd7` (note the
**double `maps/maps`** — that's what the engine expects; `HasMap` checks exactly there).

### 4. Download the demofile
From `BarReplayFileApi.DownloadReplay`. Base `https://storage.uk.cloud.ovh.net/v1/AUTH_10286efc0d334efd917d476d7183232e/BAR/demos`:
```
GET  https://storage.uk.cloud.ovh.net/.../BAR/demos/<FileName>
```
Save to `REPLAYS/<FileName>`. (Gex caps demofiles at 64 MB before processing.)

### 5. Install the widget + enable config
From `BarHeadlessInstance.cs` lines ~160-183. Copy the two Lua files straight out of the gex repo
(`gex/gex/gex.lua`, `gex/gex/BYAR.lua`):
```
copy gex.lua   ->  <ENGINE>/LuaUI/Widgets/gex.lua
copy BYAR.lua  ->  <WRITE_DIR>/LuaUI/Config/BYAR.lua     (force-enables widget order=1)
```
`<WRITE_DIR>` = a per-game scratch dir, Gex uses `<ENGINE>/data-{gameID}`. The widget reads from the
engine's `LuaUI/Widgets`; the enable-config is read from the **write-dir's** `LuaUI/Config`.

> **Pin these two files into our repo.** They are the only part of Gex we depend on *by content*.
> Vendor them under `gex_research/vendor/` and bump on upstream changes (see "Maintenance" below).

### 6. Write the start script
From `BarHeadlessInstance.cs` ~line 244. One file, e.g. `<ENGINE>/_script-{gameID}.txt`:
```
[game] {
demofile=<ABS PATH TO REPLAYS/FileName>;HostPort=<port>;
}
```
`port` = any free port; Gex uses `50000 + (n % 1000)` to avoid collisions across parallel runs.

### 7. Launch headless + watch stdout
From `BarHeadlessInstance.cs` ~line 248:
```
spring-headless(.exe)  --write-dir "<WRITE_DIR>"  "<SCRIPT_FILE>"
   cwd = <ENGINE>
```
Capture stdout/stderr. Useful line markers Gex keys off of (regexes in the same file):
- progress: `[Gex] on frame <N>` (emitted every 600 frames + key callins)
- **widget failed to load (abort):** `Failed to load: gex.lua`
- game ended (ignore later errors): `[SpringApp::Kill][1] fromRun=1`
- errors: lines matching `Error:` / `Fatal:`
Gex caps a run at ~10 min wall-clock by default and kills the process if exceeded.

### 8. Collect the output
From `BarHeadlessInstance.cs` ~line 465: `actions.json` is at **`<WRITE_DIR>/actions.json`**. That's the
deliverable. (Gex then zstd-compresses it to `actions.zstd` and deletes the data dir — we can skip that
and just read the raw json, or keep the dir for re-analysis.)

---

## What runs once vs. per-replay (caching)

| Asset | Cost | Reuse |
|---|---|---|
| Engine binary (`{version}-win`) | ~hundreds of MB, slow | once per **engine version** |
| Game version (`games/{GameVersion}`) | large, slow | once per **game version** (many replays share one) |
| Map (`.sd7`) | medium | once per **map** |
| Demofile | small | per replay |
| Widget run | **minutes of CPU** | per replay (the actual work) |

So a batch of N replays on the same patch+map pays the big downloads **once**, then just demofile +
headless run per game. This is exactly why extracting *only* the headless step is worthwhile: we keep
Gex's expensive-asset caching model without its server.

---

## Reference harness (pseudo / PowerShell skeleton)

This is a faithful translation of the C# flow — adapt into our toolchain (Python/Node/PS). Not run yet.

```powershell
param($GameID, $Root = "F:\bar-headless")
$ENG="$Root\engines"; $REP="$Root\replays"; $MAP="$Root\maps"; $LOG="$Root\gamelogs"
$env:PRD_RAPID_USE_STREAMER="false"
$env:PRD_HTTP_SEARCH_URL="https://files-cdn.beyondallreason.dev/find"
$env:PRD_RAPID_REPO_MASTER="https://repos-cdn.beyondallreason.dev/repos.gz"

# 0. metadata (one public API call; later: parse demofile header instead)
$m = irm "https://<gex-host>/api/match/$GameID" | % data
$engine=$m.engine; $ver=$m.gameVersion; $map=$m.map; $file=$m.fileName
$E="$ENG\$engine-win"

# 1. engine
if (!(Test-Path $E)) {
  ni $E -ItemType Directory -Force | Out-Null
  iwr "https://github.com/beyond-all-reason/spring/releases/download/$engine/spring_bar_.rel2501.${engine}_windows-64-minimal-portable.7z" -OutFile "$E\engine.7z"
  pushd $E; & 7z x -y engine.7z; popd
}
# 2. game version
if (!(Test-Path "$E\games\$ver\done.txt")) {
  & "$E\pr-downloader.exe" --filesystem-writepath "$E\games\$ver" --download-game "$ver"
  ni "$E\games\$ver\done.txt" -ItemType File -Force | Out-Null
}
# 3. map  (escape/lowercase name like EscapeRecoilFilesytemCharacters)
$safe = ($map + ".sd7").ToLower()  # plus filesystem escaping
if (!(Test-Path "$E\maps\maps\$safe")) {
  & "$E\pr-downloader.exe" --filesystem-writepath "$MAP" --download-map "$map"
  ni "$E\maps\maps" -ItemType Directory -Force | Out-Null
  copy "$MAP\maps\$safe" "$E\maps\maps\$safe"
}
# 4. demofile
if (!(Test-Path "$REP\$file")) {
  iwr "https://storage.uk.cloud.ovh.net/v1/AUTH_10286efc0d334efd917d476d7183232e/BAR/demos/$file" -OutFile "$REP\$file"
}
# 5. widget + config
$WD="$E\data-$GameID"
ni "$E\LuaUI\Widgets" -ItemType Directory -Force | Out-Null
ni "$WD\LuaUI\Config"  -ItemType Directory -Force | Out-Null
copy "<repo>\gex_research\vendor\gex.lua"  "$E\LuaUI\Widgets\gex.lua" -Force
copy "<repo>\gex_research\vendor\BYAR.lua" "$WD\LuaUI\Config\BYAR.lua" -Force
# 6. script
$script="$E\_script-$GameID.txt"
"[game] {`ndemofile=$REP\$file;HostPort=50123;`n}" | Set-Content $script
# 7. run
& "$E\spring-headless.exe" --write-dir "$WD" "$script"   # cwd should be $E
# 8. collect
copy "$WD\actions.json" "$LOG\$GameID.actions.json"
```

---

## Parsing `actions.json` ourselves (replaces the whole C# ingest)

`actions.json` is **newline-delimited JSON objects**, one per event, each with `"action"` + usually
`"frame"` (widget `writeJsonRaw`, `gex.lua` line ~49). We do NOT need Gex's parser/DB — a 30-line reader
in `splendid_baralytics` reproduces `GameOutput`:

```js
const events = fs.readFileSync(p, "utf8").split("\n").filter(Boolean).map(JSON.parse);
const byAction = Object.groupBy(events, e => e.action);
// byAction.team_stats, .extra_stat_update, .unit_resources, .unit_damage, .unit_created, ...
```
Field meanings + granularity are catalogued in `gex_process.md`. The C# models
(`Models/Event/GameEvent*.cs`) are just the schema reference for each line; `[JsonActionLogPropertyName]`
attributes there are the JSON key ↔ field map (note: widget JSON keys are camelCase like `metalProduced`,
`damageDealt`, etc.). **Player↔team join:** map each event's `teamID` to a player via the roster from
`/api/match/{gameID}` (`Players[].teamID`).

---

## What we DON'T need from Gex (explicitly dropped)

- PostgreSQL + all `Services/Repositories/*` + `notes/migrate_db.sql` — we store results our way.
- ASP.NET web server, controllers, SignalR hubs, auth/JWTs, Vue `src/` front end.
- Queues / hosted services (`Services/Hosted/*`) — replaced by our own batch loop.
- Lobby client, Familiar workers, wiresharkDump, Discord, metrics.
- `BarDemofileParser` (C#) — *optional*; only needed if we want to drop the gex-API metadata call
  (see below). Roster/economy-history can also come from the API or the action log.

## Cutting the last cord (no gex server at all)

The only runtime dependency on a gex instance is **step 0** (the 4 metadata fields). Two ways off it:
1. Use the **BAR public API directly**: `GET https://api.bar-rts.com/replays/{gameID}` returns engine,
   gameVersion, map, fileName (this is where Gex itself gets them — `BarReplayApi.cs`).
2. **Parse the demofile header** locally (port the relevant bit of `Services/Parser/BarDemofileParser.cs`,
   or use the JS `sdfz-demo-parser` already referenced in this repo's `package.json`). Then we need
   nothing but the BAR CDN for assets.

→ **Recommended:** drive metadata from `api.bar-rts.com` (option 1). Zero gex-server dependency, no
porting, and it's the same source Gex trusts.

## Maintenance / risks

- **Vendor `gex.lua` + `BYAR.lua`** into `gex_research/vendor/` and diff against upstream periodically;
  the widget is the contract that defines every stat we get. New `writeJson("…")` calls upstream = new
  stats for free (re-vendor + extend our parser).
- **Engine archive URL template** is version-coupled (`spring_bar_.rel2501.{ver}…` vs `recoil_{ver}…`);
  try both like `BarEngineDownloader` does. Older/newer patches may use a different template — watch for it.
- **`pr-downloader` env vars** are mandatory and CDN-specific; they will drift if BAR moves CDNs.
- **Map name escaping**: replicate `EscapeRecoilFilesytemCharacters` exactly (lowercase + special-char
  escaping) or `HasMap`-style path checks miss and you re-download forever.
- **Determinism**: a replay must be run on the **same engine + game version** it was recorded with, or
  desync produces garbage stats. That's why steps 1-2 pin exact versions per game.

## Open questions for the build

1. Does the `-minimal-portable` engine archive include unitsync/maps tooling needed by `pr-downloader`,
   or is a separate component required? (Gex assumes both binaries sit at engine root — verify on first
   real download.)
2. Exact `EscapeRecoilFilesytemCharacters` rules — read `gex.Common/Code/ExtensionMethods/StringExtensionMethods.cs`
   before reimplementing map-name normalization.
3. Headless `--write-dir` vs working-directory: confirm the widget's relative `io.open("actions.json")`
   resolves to `--write-dir` (Gex reads `<WRITE_DIR>/actions.json`, which implies yes) across OSes.
4. Can multiple `spring-headless` run in parallel on one box (distinct ports + write-dirs)? Gex's
   `_PortOffset` suggests yes — worth load-testing for batch throughput.
5. Linux vs Windows for the batch host — Linux engine archive exists (`recoil_{ver}_amd64-linux.7z`) and
   may be easier to containerize for large backfills.

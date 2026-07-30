# gex_research — todo / research backlog

---

## Asynchronous X-position players

### Background

BAR maps define a fixed grid of canonical start positions (the numbered spawn slots
players choose from in the lobby).  For an 8v8 that is 16 positions — 8 per side —
arranged with approximate (not perfect) bilateral symmetry through the map center.

The `mirror_by_start_position` situation pairs players by doing a 180° reflection of
each actual commander-spawn coordinate through the true map center `(mapSizeX/2,
mapSizeZ/2)` and finding the nearest opposing-ally player.  This works well for
standard games but has a gap: it assumes every player is on a canonical spawn.

Two related edge cases arise:

1. **Off-canonical spawn** — a player's actual commander position deviates
   significantly from any defined canonical start position for that map (they spawned
   outside their slot, or in a slot that belongs to the other half of the map).

2. **Vacant canonical position** — a canonical spawn slot has no player on it, while
   another player is present at an irregular position nearby.

When both conditions coincide — a vacant canonical position AND a nearby off-canonical
player — that player is an **asynchronous X-position player**: they are occupying a
position that is not the one the map "expected" them to fill.

### Why they are interesting

An asynchronous X-position player has chosen (intentionally or by accident) to start
in a geometrically different location than their mirror opponent on the other side.
This breaks the positional symmetry that the mirror-pair analysis assumes.

What we can ask:

- **Does the positional asymmetry pay off, and when?**  The economy composition
  time-series for the pair is still valid — both players share the same tick-rate and
  game clock.  By overlaying the async player's economy curve against their spatial
  mirror's economy curve, we can see whether the unconventional position front-loads
  an advantage, creates a deficit that is later recovered, or never converges.

- **What point in the game does synchrony (or divergence) appear?**  Frame-level
  granularity (every 450 frames / 15 s) means we can identify crossover points in
  total value or per-bucket percentages.

- **Is the effect repeatable across games?**  Flagging async players in every run
  allows cross-game aggregation once we have more replays.

### What needs to be built

#### 1 — Canonical start position catalog  (`metrics/maps/`)

Emit the map's defined start positions from gex.lua at game start:

```lua
function widget:GameStart()
    -- existing: mapSizeX, mapSizeZ
    -- add: per-slot start position (Spring gives us Game.teamStartPoses[i].x/y/z)
    local slots = {}
    for i = 0, Spring.GetGaiaTeamID() - 1 do
        local x, y, z = Spring.GetTeamStartPosition(i)
        if x then table.insert(slots, { i, x, z }) end
    end
    writeJson("start", {
        { "mapSizeX",    Game.mapSizeX },
        { "mapSizeZ",    Game.mapSizeZ },
        { "startSlots",  slots }        -- [{slotIndex, x, z}, ...]
    })
end
```

The `startSlots` array gives ground-truth canonical positions for that specific game
(the engine knows which slots were made available).  Save it into `meta.startSlots` in
`parseActions.mjs` and pass it through `context.mjs`.

#### 2 — Async-player detection  (`process/lib/context.mjs`)

After collecting actual commander spawns, compare each player's position to the nearest
canonical slot:

```
slotError(player) = distance(player.startPos, nearestCanonicalSlot)
```

A player is **asynchronous** if `slotError` exceeds a configurable threshold (suggested
starting value: `~300 elmos`, roughly half a spawn-zone radius).

Attach to each team entry in context:

```js
{
  teamID: 3,
  startPos: { x: 381, z: 9635 },
  canonicalSlot: { index: 3, x: 420, z: 9700 },
  slotError: 74,          // elmos
  asyncPosition: false,   // true if slotError > threshold
}
```

#### 3 — New situation: `async_position_analysis`

A new situation module `process/lib/situations/async_position_analysis.mjs` that:

1. Identifies all async-position players in the game.
2. For each async player, finds the vacant canonical slot they most plausibly
   "should" have filled (nearest vacant slot on their ally team's side).
3. Finds the opponent who filled the mirror of that vacant slot (the "expected"
   counterpart).
4. Produces a time-series comparison:
   - async player economy curve
   - expected counterpart economy curve
   - delta trajectory (does the async player lead or trail, and by how much, at each
     sample frame)
5. Marks the **crossover frame** if the delta changes sign (async player overtakes /
   falls behind their counterpart).

Output structure (per async pair):

```json
{
  "asyncPlayer":      { "teamID": N, "name": "...", "slotError": X },
  "counterpart":      { "teamID": M, "name": "...", "canonicalSlot": K },
  "vacantSlot":       { "index": K, "x": ..., "z": ... },
  "deltaTrajectory":  [{ "frame": F, "second": S, "totalDelta": D, "pct": {...} }],
  "crossoverFrame":   F | null,
  "verdict":          "async_advantage | counterpart_advantage | no_clear_winner"
}
```

#### 4 — HTML report section

Add an "Asynchronous positions" section to the report (after mirror pairs) showing:

- Map diagram (SVG) marking canonical slots, actual spawns, and async players
  with a distinct colour + dashed line from actual → expected slot
- Per-pair economy delta chart (async minus counterpart, line over time)
- Crossover annotation if present

---

## Mirror quality scoring

Related: because maps are only approximately symmetric, some mirror pairs will have
larger reflection errors than others.  Track `pair.distance` (already in
`mirror_by_start_position` output) as a **mirror quality** score and expose it in the
report so pairs with large offsets can be visually flagged as lower-confidence
comparisons.

Threshold ideas:
- `< 100 elmos` — good mirror (same spawn zone, different player)
- `100–400 elmos` — approximate mirror (different part of spawn area)
- `> 400 elmos` — suspect pair (review manually; may be an async player)

---

## Wreck recovery — battlefield resource attribution

### What it is

When a combat unit is destroyed normally (not reclaimed alive), it leaves a **wreck**
(a Spring "feature") worth ~55% of its original metal cost.  This wreck can be:

- **Reclaimed** by a friendly or enemy constructor → metal returned to whoever reclaims it
- **Resurrected** by a T1 resurrection unit (T1 bot lab or T1 sea lab unit only, both
  factions: `armrectr`/`correctr` and their sea equivalents) → unit returns to play at
  partial health, full metal value recovered
- **Left intact** → wreck decays or stays on the field until someone acts on it
- **Exploded** by further combat → wreck destroyed with no recovery

**Why it matters:** Who recovers the wrecks after a battle is a strong indicator of:
1. **Map control** — you need builders physically present on the battlefield
2. **Reclaim doctrine** — does the player always bring a constructor on pushes?
3. **Resurrection** — did the enemy have a resurrection unit near the front? Resurrecting a
   fresh wreck returns the FULL unit (typically 50–60% of max health, depending on wreck
   health remaining) — much better economy than reclaiming the ~55% metal value

### gex.lua status

**Implemented (2026-06-09):** `widget:FeatureCreated` and `widget:FeatureDestroyed` are
now in `vendor/gex.lua`.  These emit `wreck_created` and `wreck_removed` events.

New events in actions.json after the next headless run:

```
{"action":"wreck_created","frame":N, "featureID":X, "sourceName":"armamb", "allyTeam":0, "x":4293, "z":1993}
{"action":"wreck_removed","frame":N, "featureID":X, "sourceName":"armamb",
  "reclaimerID":Y, "reclaimerTeam":1, "reclaimerDist":87, "isResurrect":false, "x":4293, "z":1993}
```

`canResurrect` is also now emitted in `unit_def` events (e.g. `armrectr`/`correctr` will
have `"canResurrect": true`).

### Attribution accuracy

The `reclaimerTeam` at `wreck_removed` time is determined by the **nearest
reclaimer/resurrector within 500 elmos** at the moment the wreck disappears.  This is
approximate:
- Works well when a single builder is clearly responsible
- May mis-attribute in battles where multiple builders from both teams are present
- Improving to `AllowFeatureBuildStep` (synced callin, gives exact attribution) is
  possible if gex.lua is refactored to a synced Gadget — flagged for future work

### What needs to be built (Node.js side)

#### 1 — `process/lib/metrics/wreck_recovery.mjs`

New metric that processes `wreck_created` / `wreck_removed` events:

```
For each wreck_removed:
  - look up sourceName → unit def → metalCost
  - wreckedValue = metalCost * 0.55
  - attribution: reclaimerTeam from the event
  - classify: isResurrect? if so, value = metalCost (full unit) not wreckedValue
  - cross-reference with original kill: find the unit_killed event by position+sourceName to get
    which team originally lost this unit
```

Output per team per time:
- `reclaimed_from_enemy`: cumulative metal recovered from reclaiming enemy wrecks
- `reclaimed_friendly`: cumulative metal recovered from own-side wrecks
- `resurrected`: cumulative metal-equivalent value of resurrected units
- `lost_to_enemy_reclaim`: cumulative metal value of own wrecks that enemy recovered
- `unrecovered`: wrecks that were never removed (left on field)

#### 2 — Wreck–kill linkage

Match each `wreck_created` to the `unit_killed` event that produced it by:
- Position proximity: wreck spawns at (or near) the kill position
- Timing: wreck appears within a few frames of the kill
- sourceName → defName match

This gives each wreck a "killed by team X" attribution so we know which side lost
the unit, and the reclaim attribution tells us who recovered the value.

#### 3 — Battle efficiency table

For each significant engagement (cluster of kills in space/time), compute:
- Kills: N units destroyed (team A kills B units from team B)
- Own losses: M units lost
- Net wreck recovery: metal recovered from enemy wrecks minus metal lost to enemy reclaim
- Resurrection: any units resurrected by either side

A negative net wreck recovery despite winning kills = the enemy controlled the battlefield
well enough to recover value. A positive net = map control victory.

---

## Self-reclaim — precision military analysis

### Background

`self_reclaim.mjs` tracks cumulative own-unit reclaim value per team, with lifetime
energy accounting for eco structures.  The **military** bucket (reclaiming living combat
units) currently uses a simplified model because the actual HP% at reclaim start is not
available in the gex.lua event stream.

### The mechanic in full

Reclaiming a unit at H% HP:
- **Reclaim work** required = H% of the unit's original build-power-time (cheap if nearly dead)
- **Metal returned** = 100% of metalCost (full value, regardless of HP)
- **Alternative** (unit dies normally): wreck = ~55% of metalCost

Key scenarios:
1. **Deathsave** — unit at ~5–15% HP, killing blow mid-air.  Reclaim fires first, unit
   is destroyed by the reclaim action, you get 100% metal back.  Saved vs wreck: 45% of
   metalCost.  Combat-value fully realised (damage dealt + shots tanked); you only lose
   the remaining HP% in unspent potential.

2. **Tactical liquidation** — unit at 30–70% HP, intentionally reclaimed to convert
   military presence to raw metal (e.g. pulling a unit back from a failing push to fund
   eco).  Metal returned = full metalCost, but you surrender the unit's remaining
   fighting life.  Net metal = 0 (you built it for metalCost, you get metalCost back);
   combat-value partially realised.

3. **Strategic recomposition** — healthy unit reclaimed to rebuild it as a different
   unit type (e.g. reclaiming raiders to rebuild as tanks for a push).  Net metal = 0;
   interpretation depends on whether the rebuild was worth the timing cost.

### What the current metric shows

`reclaimAdvantage` = metalCost × 0.45 — the maximum possible saving vs wreck outcome.
This assumes the unit was at ~0% HP (deathsave).  If the unit was healthy, the actual
advantage is 0 (no savings vs wreck — you gave up a functional unit).

`lifetimeEnergyValue` for eco structures accurately captures the real value contribution
(wind turbines use max-capacity rate — actual output is wind-speed-dependent, so treat
wind LifeE figures as upper bounds).

### What needs to be built

#### gex.lua — emit HP at reclaim start

Spring provides `widget:UnitBeingBuilt` and `widget:UnitCloaked` but neither fires for
reclaim.  The correct hook is **`widget:UnitBeingReclaimed(unitID, unit, reclaimer)`**:

```lua
function widget:UnitBeingReclaimed(unitID, unit, reclaimer)
    local hp, maxHp = Spring.GetUnitHealth(unitID)
    local hpPct = (maxHp and maxHp > 0) and math.floor(hp / maxHp * 100 + 0.5) or nil
    writeJson("unit_reclaim_start", {
        { "unitID",    unitID },
        { "teamID",    Spring.GetUnitTeam(unitID) },
        { "reclaimerID", reclaimer },
        { "reclaimerTeam", Spring.GetUnitTeam(reclaimer) },
        { "hpPct",     hpPct }
    })
end
```

This fires when reclaim begins (not when the unit dies), giving the HP% before reclaim
work has reduced it.  Match to `unit_killed` (weaponDefID=-12) by unitID to classify
each reclaim as deathsave, liquidation, or recomposition.

#### Detection thresholds (suggested)

| hpPct range | Classification |
|---|---|
| 0–20% | Deathsave — full `reclaimAdvantage` credited |
| 21–60% | Liquidation — partial credit (metalCost × 0.45 × (1 - hpPct)) |
| 61–100% | Recomposition — 0 wreck-savings credit; note as strategic rotation |

#### Output enrichment

Add to each military reclaim event:
- `hpPct`: actual HP% at reclaim start (null until gex.lua updated)
- `classification`: "deathsave" | "liquidation" | "recomposition" | "unknown"
- `actualReclaimAdvantage`: vs `reclaimAdvantage` (theoretical max, always computed)

---

## Build-template-aware advising

`eco_advisor.mjs` grades against steady-state course-correction rules, so a deliberate
rush build (e.g. `metrics/builds/duo-geo-rush.json`) scores as "deviated" during its
planned resource dive — run-003's geo dive (E bank 1926 → 10) is correct play for that
build, not an error.

What's needed: let the advisor accept a build template (`params.buildTemplate`) and:
1. Match the replay's opening against the template sequence (defName + time window).
2. While the template is being followed, suspend the rule cascade and grade AGAINST
   THE TEMPLATE's checkpoints (factoryStart, geoOnline, ...) — report time deltas vs
   reference, not rule verdicts.
3. Detect "fell off the build" (missed checkpoint by > tolerance) and resume normal
   rule grading from that point.
4. Phase-specific gates: the template declares each checkpoint's gate (energy, BP,
   walk) — when a checkpoint is late, inspect the gate's actual state to say WHY
   (run-003: geoOnline ~33s late because energy bottomed at 10 — bank too small for
   the competing levlr/mex drains in the geo window).

---

## gex.lua — future emits to consider

| Field | Spring API | Notes |
|---|---|---|
| `startSlots` | `Spring.GetTeamStartPosition(i)` | canonical slot coords — needed for async detection |
| `unit_reclaim_start` | `widget:UnitBeingReclaimed(unitID, unit, reclaimer)` | HP% at reclaim start — needed for precise military self-reclaim classification |
| `mapChecksum` | `Game.mapChecksum` | for cross-game map identity |
| `winCondition` | `Game.gameMode` | annihilation vs. commander-kill |

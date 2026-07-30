# Opening Builds — 8v8 on All That Glitters (2026-06-10 14:43)

Analysis of the most recent complete 8v8 BAR replay, focused on the canyon matchup around
Ryan (**[APE]Splendi**). Build orders read directly from the gex headless extraction
(`unit_created` / `factory_unit_created` events, 30 fps); prose mapped to the intent-language
pattern in `barbots/docs/intent-language.md`.

## Replay metadata

| Field | Value |
|---|---|
| File | `2026-06-10_14-43-10-306_All That Glitters v2.2.3_2025.06.24.sdfz` |
| Path | `C:\Users\codes\AppData\Local\Programs\Beyond-All-Reason\data\demos\…` |
| Map | All That Glitters v2.2.3 (6144 × 10240) — 180°-rotation symmetric |
| Mode | 8v8 (16 players, 2 ally teams) |
| Date | 2026-06-10 |
| Duration | ~21.8 min (demo header). **gex extraction covers 0 – ~13.8 min** (frame 24900) |
| Winner | **allyTeam 1** (the enemy/top team) — **Splendi's team (allyTeam 0) lost** |
| Pipeline | `gex_research` → `node process/run.mjs metrics/runs/run-004-opening-builds.json` |
| Outputs | `gex_research/output/run-004/` (context.json, metrics.json, situations.json, report.html) |

## Player identifications

Roles assigned by commander-spawn position matched to canonical `positionRoles` in
`gex_research/metrics/maps/all-that-glitters.json` (every player snapped to a canonical slot
within < 30 elmos; the map is confirmed 180°-rotation symmetric by the pipeline's mirror
pairing, distance ≈ 1).

| Who | In-game name | Team | Ally | Pos / Role | Faction | Skill | Spawn (x,z) |
|---|---|---|---|---|---|---|---|
| **Ryan / codesmith55** | **[APE]Splendi** | 2 | 0 | **pos 1 — Anti-Canyon (F1)** → ATG | Cortex | 29.2 | (657, 8197) |
| his canyon opponent | **HomeLessPxrnStar** | 9 | 1 | **pos 4 — Canyon (F4)** | Cortex | 28.7 | (1153, 1996) |
| his canyon-lane opponent | **leebeck3** | 14 | 1 | **pos 8 — Back Canyon** | Cortex | 16.1 | (661, 747) |

**Why these three:** Splendi is the **Anti-Canyon** (pos 1) — an ATG position whose whole job is
fighting *into* the canyon. The map doc's laning rule is cross-mirror ("F1 lanes against enemy
F4"), so his direct lane / canyon opponent is the enemy **Canyon (pos 4) = HomeLessPxrnStar**.
**leebeck3** sits at enemy **Back Canyon (pos 8)** — directly behind HomeLessPxrnStar on the same
canyon flank — i.e. the adjacent canyon-lane enemy. (Note: Splendi's *pure geometric mirror* is
the enemy **Anti-Canyon** RabbanSqueezer, team 11 — a different player than his lane opponent,
because laning crosses F1↔F4 while the mirror keeps the same role.)

> **Identity caveat:** No literal "Ryan"/"codesmith55" appears in the replay. `[APE]Splendi` is
> inferred to be the user from the repo name *splendid_baralytics* and the high skill (29.2).

---

## 1. [APE]Splendi — pos 1 Anti-Canyon (Cortex) — vehicle eco / map-control

### Action timeline (commander `corcom` @ (657,8197); ⚙ = factory output)

| Time | Action | Notes |
|---|---|---|
| 0:04 / 0:11 / 0:18 | 3× **mex** | 3 mex |
| 0:25 / 0:36 | 2× **solar** | |
| 0:46 | **Vehicle Plant** (`corvp`, m570) | factory — opens **vehicle**, not bot |
| 1:06 / 1:17 | 2× solar (4 total) | |
| 1:06 ⚙ / 1:35 ⚙ / 1:50 ⚙ | 3× **con vehicle** (`corcv`) | early build-power |
| 1:23 | 1st **wind** | |
| 1:56–3:33 | **mex flood** — 4th→13th mex (1:56, 2:00, 2:15, 2:33, 2:49, 2:54, 3:15, 3:28, 3:33) | aggressive outward expansion |
| 2:12 ⚙ / 2:19 ⚙ | 2× Rascal scout (`corfav`) | scouting |
| 2:27 ⚙ / 2:35 ⚙ | 2× **Gator** (`corgator`, raider) | |
| 3:00 ⚙ / 3:16 ⚙ / 4:36 ⚙ | 3× **Leveler** (`corlevlr`, riot) | main line |
| 3:30 ⚙ | **Crasher** mobile AA (`cormist`) | answers air |
| 4:09 ⚙ / 4:09 ⚙ / 5:00 ⚙ | **Wolverine** (`corwolv`, mine-layer arty) | |
| 4:02 / 4:16 / 4:28 | **LLT** + **heavy-LLT** (`corllt`/`corhllt`) **at z≈5200** | forward static defense at **mid-map** (base is z≈8200) |
| 2:16–5:07 | ~9 more **wind** | ~10 wind total by 5:00 |
| 4:30 | 14th mex | |

**Resource state:** 0:00 M1000/E1000 · 2:00 eco 843 · 3:00 eco 1093 · **5:00 eco 1544, mInc ~24, army 1007** (highest eco of the three; army dipped 1227→1007 as forward units traded). **No T2** in the recorded window.

> **Prose (intent-language):** Opens **3 mex 2 solar into a vehicle plant (0:46)**, then 2 more
> solar and a first wind while the plant pumps **3 con vehicles**. From ~2:00 all builders fan out
> on a **heavy mex expansion — ~14 mex started by 4:30** — interleaved with ~10 wind (favorable,
> near-max-16 conditions). The factory program runs **scout → Gator/Leveler raiders → mobile AA →
> Wolverines**, and from ~4:00 cons walk forward to plant **LLT and heavy-LLT at mid-map (z≈5200)**,
> claiming ground toward the enemy canyon. By 5:00 he holds the **highest economy of the three
> (eco 1544, mInc ~24) with no tech started** — an economy-and-map-control vehicle opening that
> trades fast-T2 timing for board presence on the canyon flank. *First-goal checkpoint: win the
> mex count in the lane, not a T2 mex.*

---

## 2. HomeLessPxrnStar — pos 4 Canyon (Cortex) — bot-lab raider, double-lab

### Action timeline (commander `corcom` @ (1153,1996))

| Time | Action | Notes |
|---|---|---|
| 0:04 / 0:11 / 0:19 | 3× **mex** | |
| 0:26 / 0:37 | 2× **solar** | |
| 0:47 | **Bot Lab** (`corlab`, m470) | factory — opens **bot** |
| 1:05 / 1:28 / 1:46 | 3× solar (5 total) | |
| 1:07 ⚙ / 1:29 ⚙ | 2× **con bot** (`corck`) | |
| 1:07 | 1st wind | |
| 1:20–1:57 ⚙ | 4× **Grunt** (`corak`, fast raider) | early harass |
| 2:03 / 2:17 / 2:32 / 3:01 / 3:14 | mex 4→8 | modest expansion |
| 2:04–5:09 ⚙ | **Thug** (`corthud`, light plasma bot) ×~10 | main riot line |
| 2:52 | **Radar** (`corrad`) | |
| **3:21** | **2nd Bot Lab** (`corlab`) at (368,3984) | doubles bot production, forward-left |
| 3:41 ⚙ | con bot from 2nd lab | |
| 4:32 ⚙ | **Graverobber** (`cornecro`, rez/reclaim) | |
| 1:07–4:52 | ~7 **wind** | |

**Resource state:** 2:00 eco 793 · 3:00 eco 986 · **5:00 eco 1301, army 1428, mInc ~18.** **T2 bot lab @ 9.8 min.**

> **Prose (intent-language):** Opens **3 mex 2 solar into a bot lab (0:47)**, adds 3 more solar and
> a wind, and immediately leans on **2 con bots + 4 Grunts** to harass while **Thugs** become the
> standing riot line. Mex growth is deliberate (8 mex by 3:14). The signature move is a **second
> bot lab at 3:21**, pushed forward-left, that flips on its own con and floods more Thugs plus a
> Graverobber for reclaim. By 5:00 he is the **most balanced of the three (eco 1301, army 1428)**
> and tops out into a **standard T2 bot transition (~9.8 min)**. *First goal: out-produce the lane
> with doubled T1 bot output, then tech.*

---

## 3. leebeck3 — pos 8 Back Canyon (Cortex) — wind-flooded Brute aggression

### Action timeline (commander `corcom` @ (661,747))

| Time | Action | Notes |
|---|---|---|
| 0:04 / 0:11 / 0:18 | 3× **mex** | |
| 0:25 / 0:31 / 0:37 / 0:45 / 0:52 | **5× wind, back-to-back** | commits to the high-wind map before any other eco |
| 1:03 | **Vehicle Plant** (`corvp`, m570) | factory — **vehicle** |
| 1:23 ⚙ / 1:26 ⚙ | 2× Rascal scout (`corfav`) | |
| 1:30 ⚙ / 1:42 ⚙ | 2× **con vehicle** (`corcv`) | |
| 1:59–5:00 | ~16 more **wind** | **~22 wind by 5:00 — by far the most** |
| 2:00 / 2:36 / 3:20 | mex 4→6 | minimal expansion |
| 2:05 | **Nano turret** (`cornanotc`) | assists the plant |
| 2:05–5:10 ⚙ | **Brute** (`corraid`, medium assault tank) ×~8 | nonstop army |

**Resource state:** 2:00 eco 408 · 3:00 eco 766 · **5:00 eco 1203, army 1645 (highest), mInc stuck ~6–13 most of the opening, jumping to ~88 at 5:00.** **T2 vehicle plant @ 8.8 min (earliest of the three).**

> **Prose (intent-language):** Opens **3 mex then five straight wind (0:25–0:52)** — an all-in read
> of the **favorable, near-max-16 wind** — before laying a **vehicle plant (1:03)**. He skips real
> metal expansion (only 6 mex by 3:20, income parked at ~6–13) and instead converts that wind into
> a **nano-assisted plant pumping Brutes on repeat (~8 by 5:00)**, sustaining the **largest army of
> the three (1645)** on the **smallest economy**. He reaches **T2 vehicles fastest (~8.8 min)**.
> *First goal: convert wind into Brute tempo and pressure the lane; economy is an afterthought.*
> (Lowest-skill of the trio at 16.1 — the build is pure aggression over scaling.)

---

## Side-by-side

| | Splendi (AC / pos1) | HomeLessPxrnStar (Canyon / pos4) | leebeck3 (Back Canyon / pos8) |
|---|---|---|---|
| Opening | 3 mex 2 solar → **vehicle** | 3 mex 2 solar → **bot** | 3 mex → **5 wind** → vehicle |
| First factory | 0:46 vehicle plant | 0:47 bot lab | 1:03 vehicle plant |
| Energy plan | solar-first, ~10 wind | solar-heavy, ~7 wind | **wind flood (~22)** |
| Mex @ 5:00 | **~14 (most)** | ~8 | ~6 (fewest) |
| Eco bucket @ 5:00 | **1544 (highest)** | 1301 | 1203 (lowest) |
| Army @ 5:00 | 1007 (lowest) | 1428 | **1645 (highest)** |
| Army units | Gator/Leveler/Wolverine + fwd LLT | Grunt/Thug + 2nd lab | **Brute spam** |
| T2 timing (in window) | **none by 13.8 min** | bot @ **9.8 min** | vehicle @ **8.8 min** |
| Apparent goal | out-expand + map-control the front | doubled T1 bots → standard T2 | wind→Brute all-in, fastest T2 |

- **Who scaled faster (economy):** **Splendi** — most mex (~14) and highest eco bucket (1544),
  but he converted that lead into *map control* (forward LLT/HLLT at mid-map) rather than units,
  so his army was smallest at 5:00.
- **Who had the most army:** **leebeck3**, on the *weakest* economy — a pure wind→Brute tempo play.
- **T2 race:** leebeck3 (8.8) < HomeLessPxrnStar (9.8) < Splendi (no T2 visible in the recorded
  window). Splendi deferred tech for expansion + board presence.
- **Matchup read:** Splendi (Anti-Canyon) played to his role — out-mex the flank and wall the
  front with cheap defense — while his two canyon-flank opponents chose army-first builds
  (raiders / Brutes) and teched earlier. His ally team ultimately **lost** the game.

## Caveats

- **Extraction window:** the gex headless dump ends at ~13.8 min (frame 24900) though the game ran
  ~21.8 min. The **0–5 min opening is fully covered**; anything after 13.8 min (including a possible
  later Splendi T2) is **not visible**. "T2 timing" = first T2 factory/con event within that window.
- **Identity:** `[APE]Splendi` inferred as Ryan/codesmith55 (no literal name in the replay).
- **Roles** derived from commander-spawn positions vs the canonical map slots; "canyon opponent"
  (pos 4) and "canyon-lane opponent" (pos 8) follow the task's role definition and the map doc's
  cross-mirror laning rule. Splendi's strict geometric mirror is instead the enemy Anti-Canyon
  (RabbanSqueezer, team 11).
- **Faction** taken from the commander unit (`corcom` = Cortex for all three); the demo-header
  faction field is unreliable (it reported "Armada" for Splendi).
- Counts/timings are from raw unit-creation events; "eco"/"army"/"mInc" are gex `extra_stat_update`
  values (eco/army are the metric's value buckets, not raw metal). Wind peaked at **16 = map max**
  for most of 1:00–4:10 (mean 13.1), so wind investment was efficient this game.
- No analyzer code was modified; a pre-existing `run-004-opening-builds.json` already targeted this
  demo and was used as-is.
```

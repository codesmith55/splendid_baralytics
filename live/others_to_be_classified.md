# others_to_be_classified

A living triage list for unit defs that land in the **`other`** bucket of the economy
classifier. `other` is the *fall-through* — a def reaches it only when it is **not**
commander, **not** a factory, has **no weapon**, **no build power**, **no eco output**,
and **no intel/EW range**. The goal of this file is to drain `other` toward zero by
assigning each real, buildable def a proper bucket as it shows up in games.

Classifier sources (keep both in sync):
- live dashboard widget → [`bar_analytic_live.lua`](bar_analytic_live.lua) `classify()`
  (buckets: military / **defense** / build_power / economy / infrastructure / commander / other)
- canonical pipeline → [`../process/lib/classify.mjs`](../process/lib/classify.mjs)
  (no separate `defense` bucket — static defenses + EW collapse into `military`)

> Widget edits only take effect on the **next game start** (the running stream keeps the
> classification baked in at unit-def load).

## Precedence
`commander → infrastructure(factory) → support(seed names) → economy → build_power → military/defense (weapon or intel) → other`

## Primary buckets (live widget)
`military · defense · build_power · economy · infrastructure · commander · support · other`
plus two **non-productive** slices derived per tick (not from `classify()`):
- **construction** — Σ over unfinished units of `value × buildProgress`. Invested metal that
  produces nothing until complete (the "+build time" drag in energy_ROI / total_ROI). Completed
  units count in their functional bucket; partial units count *only* here.
- **storage** — `metalCurrent + energyCurrent/70`. Idle resource sitting in the bank.

> ⚠️ **Canonical divergence:** [`../process/lib/classify.mjs`](../process/lib/classify.mjs) does
> **not** yet have `support`, `construction`, or `storage` — only the EW→military fix is mirrored
> there. Propagating the new buckets to the batch pipeline touches its metric consumers
> (economy_composition, eco_advisor, …) and is a separate task.

---

## ✅ Resolved

### Pinpointers → new `support` bucket  — 2026-06-12
`armtarg` / `cortarg` / `armfatf` / `corfatf` (Pinpointer / Naval Pinpointer, ~905–913 value) are
global military multipliers, not combat/eco/intel units. Seeded **by name** in `classify()`
(`SUPPORT_NAMES`) because no distinguishing UnitDef field has been identified — if one turns up
(a `customParams` flag), switch to field detection. The `support` bucket is the home for future
global-effect multipliers.

### Electronic warfare / intel → military (mobile) · defense (static)  — 2026-06-12
Radar, sonar, jammers, and seismic sensors used to fall through to `other` because only the
legacy `radarDistance` field was checked, and this BAR build populates the modern `radarRadius`
field instead (Beholder/`armeyes`, a radar tower, was sitting in `other`). Detection now probes
**both** naming conventions for every sensor type:

`radarDistance|radarRadius · sonarDistance|sonarRadius · radarDistanceJam|jammerRadius · sonarDistanceJam|sonarJamRadius · seismicDistance|seismicRadius`

Mobile EW (radar/jammer bots) → **military**; static EW (radar/jam/sonar towers) → **defense**.
Examples now out of `other`: Beholder, Skyhook, Adv Sonar, Sonar, Veil, Shroud, Bermuda,
Phantasm, Umbra, Obscurer (static → defense); Sneaky Pete, Castro, Deceiver, Smuggler (mobile → military).

---

## ⏳ Pending decisions (still in `other`)

| Def(s) | Human name | ~value | Note / candidate bucket |
|---|---|---|---|
| `armdf` | Decoy Fusion Reactor | ~271 | Fake fusion to bait. Deception, not real eco. defense? economy(decoy)? keep other? |
| `armhvytrans` `corhvytrans` | Osprey / Hephaestus | ~247 | Air transport (logistics). military? |
| `corvalk` `armatlas` | Hercules / Stork | ~87–95 | Air transport. military? |
| `armfort` `corfort` | Fortification Wall | ~47 | Static obstacle. defense? |
| `armdrag` `cordrag` `armfdrag` `corfdrag` | Dragon's / Shark's Teeth | ~8–15 | Static obstacle. defense? |

### ⚠️ High-value cosmetics — distortion risk if ever present
These are skins/event props that the classifier values from their metal/energy cost, so if one
ever appears on the field it would silently inflate a player's pie. Decide whether to force them
to **zero value** or an `ignore` bucket.

| Def(s) | Human name | ~value |
|---|---|---|
| `comeffigylvl1`…`lvl5` | Commander Effigy | 1057 – **5286** |
| `cor_hat_*` (fightnight, hornet, hw, legfn, ptaq, viking) | Commander hats | ~1143 |

### Harmless (0 value, no pie impact) — leave in `other`
Debug/test: `dbg_sphere`, `dbg_sphere_fullmetal`, `pbr_cube`.
Critters: `critter_penguin/ant/crab/duck/goldfish/gull`. Props: `chip`, `dice`, `xmasball*`.

---

## How to refresh this list from a live/replay stream
Every def the widget loads is emitted as a `unit_def` event carrying its `bucket`. To list
everything currently classified `other`, with values, from the live JSONL:

```bash
F="C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data/bar_analytic_live.jsonl"
grep '"action":"unit_def"' "$F" | python -c "
import json,sys,collections
seen={}
for l in sys.stdin:
    d=json.loads(l)
    if d.get('bucket')=='other': seen[d['defName']]=(d.get('name'),round(d.get('value',0),1))
for dn,(hn,v) in sorted(seen.items(),key=lambda x:-x[1][1]): print(f'{v:>8} {dn:<22} {hn}')
"
```

When a new def shows up here that *should* be classified, add a detection rule to **both**
classifiers, move it to **Resolved** with a date, and note the field that anchors the rule.

## Decision log
- **2026-06-12** — EW/intel (radar, sonar, jammers, seismic) routed out of `other` into
  military (mobile) / defense (static); detection probes legacy + modern field names.
- **2026-06-12** — new `support` bucket (pinpointers, seeded by name). New non-productive pie
  slices: `construction` (Σ value×buildProgress of unfinished units) and `storage` (idle
  resource). Widget + live server + dashboard only; canonical pipeline not yet updated.

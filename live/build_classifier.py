#!/usr/bin/env python3
"""build_classifier.py — classify & describe a team's opening from its unit-creation log.

Two phases over the first minutes of a game (faction-agnostic: ARM/COR/Legion):

  Phase 1 — opening cadence: the run of mex / solar / wind (/ converter / storage)
            BEFORE the first factory. Rendered as e.g. "3mex>1solar>2wind>factory"
            with a label + description of the trade-off.

  Phase 2 — post-factory: solar/wind/factory/conturret/worker/unit counts plus
            stability deviations (estorage / converter / mstorage / advsolar).

At all times it splits build effort (metal-equiv value) into four buckets the user
cares about:
  expansion        — mexes + mobile workers (growth / more expanders)
  egen_necessary   — energy gen up to what current production needs
  egen_unnecessary — energy gen beyond that (over-investment)
  production       — factory + units + con turrets (making army)
  (storage)        — e/m storage, reported separately as a stability line

The necessary/unnecessary egen split is a transparent heuristic (see ENERGY MODEL);
tune the constants and re-run. JSON-in / JSON-out for the server + replay_jsonl.py.
"""
import re

# ── ENERGY MODEL (heuristic — tune & re-run) ────────────────────────────────────
GEN_EPS  = {"solar": 20.0, "advsolar": 75.0}   # e/s per gen; wind resolved with wind_e
FACTORY_EPS = 120.0   # e/s a T1 factory pulls building roughly continuously
WORKER_EPS  = 25.0    # e/s a mobile con pulls while assisting/expanding

OPENING_TYPES = {"mex", "medmex", "solar", "wind", "advsolar", "factory", "converter",
                 "estorage", "mstorage", "conturret"}
EGEN      = {"solar", "wind", "advsolar"}
EXPANSION = {"mex", "medmex", "mohomex", "worker"}   # medmex/moho = Legion income upgrades
PRODUCTION = {"factory", "military", "conturret"}
STORAGE    = {"estorage", "mstorage"}
DEVIATIONS = {"estorage", "converter", "mstorage", "advsolar"}

# Phase-2 (post-factory → team's first T2) resource split: 5 buckets the user asked for.
PHASE2_CAT = {
    "mex": "expanding", "medmex": "expanding", "mohomex": "expanding",
    "worker": "build_power", "conturret": "build_power", "factory": "build_power",
    "solar": "egen", "wind": "egen", "advsolar": "egen", "converter": "egen",
    "military": "military", "defense": "military",
    # estorage / mstorage / infra / commander / other -> "other"
}
T2_FACTORY_METAL = 1000   # T1 labs ~470-720; T2 (adv) labs ~2600 — clean discriminator
T2_MEX_METAL     = 600    # moho ~620-640; medmex 250; T1 mex 50


def is_t2(defname, udef):
    """A T2-tier marker — the milestone that ends phase 2. Conservative: adv factory or moho."""
    udef = udef or {}
    if udef.get("isFactory") and (udef.get("metalCost", 0) or 0) >= T2_FACTORY_METAL:
        return True
    if udef.get("isMetalExtractor") and (udef.get("metalCost", 0) or 0) >= T2_MEX_METAL:
        return True
    return "moho" in re.sub(r"^(arm|cor|leg)", "", (defname or "").lower())


def first_t2_frame(build_log, unit_defs):
    """Earliest frame this build_log shows a T2 marker, or None (ordered log)."""
    for b in build_log:
        if is_t2(b.get("defName"), unit_defs.get(b.get("defID"), {})):
            return b.get("frame")
    return None


def phase2_split(rows, factory_frame, t2_frame):
    """5-way VALUE split of builds in (factory_frame, t2_frame]. rows: [{frame,type,value}]."""
    end = t2_frame if t2_frame is not None else float("inf")
    cats = {"expanding": 0.0, "build_power": 0.0, "egen": 0.0, "military": 0.0, "other": 0.0}
    n = 0
    for r in rows:
        if r["frame"] <= factory_frame or r["frame"] > end:
            continue
        cats[PHASE2_CAT.get(r["type"], "other")] += r.get("value", 0) or 0
        n += 1
    total = sum(cats.values()) or 1.0
    return {
        "value": {k: round(v) for k, v in cats.items()},
        "pct":   {k: round(v / total * 100) for k, v in cats.items()},
        "nBuilds": n, "reachedT2": t2_frame is not None,
    }


def structure_type(defname, udef):
    """Map a defName + its unit_def metadata to a canonical opening-build type."""
    udef = udef or {}
    base = re.sub(r"^(arm|cor|leg)", "", (defname or "").lower())
    if udef.get("isCommander"):                       return "commander"
    if udef.get("isFactory"):                         return "factory"
    if "mext" in base or "medmex" in base:            return "medmex"    # Legion legmext15 income upgrade
    if "moho" in base:                                return "mohomex"   # T2 advanced extractor (arm/cor/leg)
    if udef.get("isMetalExtractor"):                  return "mex"
    if (udef.get("energyConversionCapacity") or 0) > 0: return "converter"
    if base.startswith("advsol"):                     return "advsolar"
    if base.startswith("solar") or base == "sol":     return "solar"
    if base.startswith("win"):                        return "wind"
    if "estor" in base:                               return "estorage"
    if "mstor" in base:                               return "mstorage"
    if "nanotc" in base or base.startswith("nano"):   return "conturret"
    bucket = udef.get("bucket", "other")
    if bucket == "build_power":                       return "worker"
    if bucket in ("military", "defense"):             return "military"
    if bucket == "infrastructure":                    return "infra"
    return bucket or "other"


def _cadence(seq):
    """Compress a list of types into run-length cadence: [mex,mex,solar] -> '2mex>1solar'."""
    runs = []
    for t in seq:
        if runs and runs[-1][1] == t:
            runs[-1][0] += 1
        else:
            runs.append([1, t])
    return ">".join(f"{c}{t}" for c, t in runs), runs


def classify_opening(types):
    """types: ordered structure-types for one team. Classify the pre-factory opening."""
    pre = []
    for t in types:
        if t in OPENING_TYPES:
            pre.append(t)
            if t == "factory":
                break
    cadence, _ = _cadence(pre)
    n_mex   = pre.count("mex")
    n_solar = pre.count("solar")
    n_wind  = pre.count("wind")
    n_adv   = pre.count("advsolar")
    n_med   = pre.count("medmex")
    has_fac = "factory" in pre

    if n_med >= 1:
        label, desc = ("legion-medmex",
            "Legion income opener — upgrading mex(es) to medmex (legmext15) for +metal around "
            "the factory; energy via legsolar/legwin. The medmex is Legion's signature early "
            "income lever, the metal-side analogue of the solar/wind energy choice.")
    elif n_solar >= 2 and n_wind == 0:
        label, desc = ("solar-fast",
            "2+ solar before factory — quick, reliable energy; favors pumping "
            "expanding workers sooner over the cheapest opener.")
    elif n_solar == 1 and n_wind >= 2:
        label, desc = ("standard-middle",
            "1 solar + wind — the standard balanced opener: enough energy to start "
            "units without over-spending metal on gen.")
    elif n_wind >= 3 and n_solar == 0:
        label, desc = ("wind-aggressive",
            "cheap wind, no solar — slower energy ramp (may walk/stall a little) but "
            "low metal cost; enables aggressive early units, and scales hard if wind is high.")
    elif n_solar >= 1 and n_wind >= 1:
        label, desc = ("mixed", "mixed solar+wind energy opener.")
    elif (n_solar + n_wind + n_adv) == 0:
        label, desc = ("energy-light",
            "little/no dedicated energy before the factory — likely to stall on energy.")
    else:
        label, desc = ("other", "non-standard opening.")

    return {
        "cadence": cadence or "(no structures pre-factory)",
        "label": label, "description": desc,
        "nMex": n_mex, "nSolar": n_solar, "nWind": n_wind, "nAdvSolar": n_adv, "nMedmex": n_med,
        "reachedFactory": has_fac,
    }


def buildpower_split(builds, wind_e=12.0):
    """Split cumulative build value into expansion / egen(nec/unnec) / production / storage.

    builds: [{type, value}]. Necessary egen = energy demand (factories+workers) capped
    against egen capacity; the remainder of egen value is 'unnecessary' (over-built).
    """
    val = {"expansion": 0.0, "egen": 0.0, "production": 0.0, "storage": 0.0, "other": 0.0}
    cap_eps, n_factory, n_worker = 0.0, 0, 0
    for b in builds:
        t, v = b["type"], b.get("value", 0) or 0
        if t in EXPANSION:
            val["expansion"] += v
            if t == "worker":
                n_worker += 1
        elif t in EGEN:
            val["egen"] += v
            cap_eps += GEN_EPS.get(t, wind_e if t == "wind" else 0.0)
        elif t == "converter":
            val["egen"] += v                      # converter is energy-side investment
        elif t in STORAGE:
            val["storage"] += v
        elif t in PRODUCTION:
            val["production"] += v
            if t == "factory":
                n_factory += 1
        else:
            val["other"] += v

    demand_eps = n_factory * FACTORY_EPS + n_worker * WORKER_EPS
    nec_frac = 1.0 if cap_eps <= 0 else min(1.0, demand_eps / cap_eps)
    egen_nec  = round(val["egen"] * nec_frac)
    egen_unec = round(val["egen"] * (1 - nec_frac))

    total = sum(val.values()) or 1.0
    return {
        "expansion":        round(val["expansion"]),
        "egen_necessary":   egen_nec,
        "egen_unnecessary": egen_unec,
        "production":       round(val["production"]),
        "storage":          round(val["storage"]),
        "other":            round(val["other"]),
        "pct": {
            "expansion":        round(val["expansion"] / total * 100),
            "egen_necessary":   round(egen_nec / total * 100),
            "egen_unnecessary": round(egen_unec / total * 100),
            "production":       round(val["production"] / total * 100),
            "storage":          round(val["storage"] / total * 100),
        },
        "energy": {"capacity_eps": round(cap_eps), "demand_eps": round(demand_eps),
                   "necessary_frac": round(nec_frac, 2)},
    }


def classify_build(build_log, unit_defs, wind_e=12.0, fps=30, t2_frame=None):
    """Top-level: classify a team's opening from its raw creation log.

    build_log: ordered [{frame, defID, defName}] for ONE team (structures + units).
    unit_defs: defID -> {bucket, value, isFactory, isMetalExtractor, isCommander,
                         energyConversionCapacity}
    t2_frame:  the team's (allyteam's) first-T2 frame — ends phase 2. None = use end of log.
    """
    rows = []
    for b in build_log:
        ud = unit_defs.get(b.get("defID"), {})
        rows.append({"frame": b.get("frame", 0), "defName": b.get("defName", ""),
                     "type": structure_type(b.get("defName"), ud),
                     "value": ud.get("value", 0) or 0})
    # ignore the initial commander spawn(s) for cadence
    structs = [r for r in rows if r["type"] != "commander"]
    types = [r["type"] for r in structs]

    opening = classify_opening(types)
    fac = next((r for r in structs if r["type"] == "factory"), None)
    opening["factorySec"] = round(fac["frame"] / fps, 1) if fac else None

    # phase 2 = after the first factory
    after = []
    seen_fac = False
    for r in structs:
        if seen_fac:
            after.append(r)
        if r["type"] == "factory":
            seen_fac = True
    p2_counts = {}
    for r in after:
        p2_counts[r["type"]] = p2_counts.get(r["type"], 0) + 1
    deviations = {k: v for k, v in p2_counts.items() if k in DEVIATIONS}

    fac_frame = fac["frame"] if fac else 0
    return {
        "opening": opening,
        "phase2": {
            "fromFactory": True if fac else False,
            "factorySec": opening.get("factorySec"),
            "t2Sec": round(t2_frame / fps, 1) if t2_frame else None,
            "reachedT2": t2_frame is not None,
            # the 5-way resource split the user asked for: post-factory → team's first T2
            "split": phase2_split(structs, fac_frame, t2_frame),
            "counts": p2_counts,
            "deviations": deviations or None,
            "nUnits": p2_counts.get("military", 0),
            "nWorkers": p2_counts.get("worker", 0),
            "nConTurret": p2_counts.get("conturret", 0),
        },
        "bpSplit": buildpower_split([{"type": r["type"], "value": r["value"]} for r in structs], wind_e),
        "nStructures": len(structs),
    }

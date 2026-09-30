#!/usr/bin/env python3
"""
bar-calc/econ_data.py — the one data layer behind every BAR economy model in this repo.

    config()            bar-calc/econ_model.json (model choices, which def stands for what)
    engine_defs()       merged engine unit defs from the dumps the config lists
    unitdef(defName)    one engine def (dict) or None
    object_types()      bar_unified / splendid_buildSimulator object table, resolved from the defs
    builder_profiles()  commander / con_bot / con_turret: build range (config) + speed/BP (defs)
    legion_actions()    positions/state_api ACTIONS data (costs, income deltas, reclaim, prereqs)
    legion_constants()  positions/state_api module constants (SPOT, T1_INC, BASE_E, …)
    legion_unit_costs() positions/compare.py UNIT table (metal, energy, build work)
    model_summary()     everything above as one JSON-able dict (served at /api/econ_model)

The same rules are mirrored line for line in splendid_buildSimulator.js (resolveObjectType /
resolveLegionAction); `python bar-calc/bar_unified.py --write-parity` freezes the resolved numbers
into bar-calc/parity.json and every model's `--selftest` checks against that file.

CLI:
    python bar-calc/econ_data.py --dump            resolved model as JSON
    python bar-calc/econ_data.py --check           drift report vs the remaining hand-written tables
    python bar-calc/econ_data.py --objects|--legion  tables
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from functools import lru_cache
from typing import Dict, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(HERE, "econ_model.json")
PARITY_PATH = os.path.join(HERE, "parity.json")


def _abs(p: str) -> str:
    return p if os.path.isabs(p) else os.path.join(REPO_ROOT, p)


# ════════════════════════════════════════════════════════════════════════════
# config + engine defs
# ════════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=None)
def config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _read_jsonl_unit_defs(path: str) -> Dict[str, dict]:
    """The headless dump: `unit_def` lines form the leading block; stop once past it."""
    out: Dict[str, dict] = {}
    seen = 0
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if '"unit_def"' not in line:
                if seen > 50:
                    break
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("action") != "unit_def":
                continue
            seen += 1
            out[e["defName"]] = e
    return out


def _read_defs_array(path: str) -> Dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    defs = d["defs"] if isinstance(d, dict) else d
    return {x["defName"]: x for x in defs}


_READERS = {"jsonl-unit_def": _read_jsonl_unit_defs, "defs-array": _read_defs_array}


def _resolve_source(src: dict) -> list:
    """Absolute file(s) for one `engineDefs` entry: a fixed `path`, or a `glob` with `pick: latest`
    (the newest by name — units_<dateTime>.json sorts by time — is the one that wins)."""
    if "glob" in src:
        matches = sorted(glob.glob(_abs(src["glob"])))
        if not matches:
            return []
        return [matches[-1]] if src.get("pick", "latest") == "latest" else matches
    return [_abs(src["path"])]


@lru_cache(maxsize=None)
def engine_defs() -> Dict[str, dict]:
    """All engine defs keyed by defName. Files are applied in config order; later files win."""
    merged: Dict[str, dict] = {}
    for src in config()["engineDefs"]:
        for p in _resolve_source(src):
            if os.path.exists(p):
                merged.update(_READERS[src["format"]](p))
    return merged


def engine_sources() -> list:
    """The `engineDefs` entries with their resolved file(s) — the provenance every reader should print."""
    out = []
    for s in config()["engineDefs"]:
        files = _resolve_source(s)
        rel = [os.path.relpath(p, REPO_ROOT).replace("\\", "/") for p in files]
        out.append({"path": rel[0] if len(rel) == 1 else (rel or None), "format": s["format"],
                    "present": bool(files) and all(os.path.exists(p) for p in files),
                    "glob": s.get("glob"), "note": s.get("note", "")})
    return out


def latest_units_file() -> Optional[str]:
    """The newest bar-calc/units_<dateTime>.json (harvested by bar_unified.harvest_unit_defs), or None."""
    for s in config()["engineDefs"]:
        if "glob" in s:
            files = _resolve_source(s)
            return files[-1] if files else None
    return None


def reload() -> None:
    """Drop every cache so a freshly harvested units_*.json is picked up in-process."""
    for fn in (config, engine_defs, builder_profiles, object_types, legion_actions, legion_constants):
        fn.cache_clear()


def unitdef(def_name: str) -> Optional[dict]:
    return engine_defs().get(def_name)


# ════════════════════════════════════════════════════════════════════════════
# derivation rules (mirrored in splendid_buildSimulator.js)
# ════════════════════════════════════════════════════════════════════════════

def energy_flows(d: dict) -> tuple:
    """(production, upkeep) in E/s. Engine: energyUpkeep < 0 means the unit produces."""
    prod = max(0.0, float(d.get("energyProduction") or 0)) + max(0.0, -float(d.get("energyUpkeep") or 0))
    upk = max(0.0, float(d.get("energyUpkeep") or 0))
    return prod, upk


def mex_income(d: dict) -> float:
    """m/s on the reference spot: extractsMetal / mexBaseExtract × metalSpot (armmex → 1.825)."""
    c = config()["constants"]
    over = c.get("mexMultiplierOverride") or {}
    if d.get("defName") in over:
        return float(over[d["defName"]]) * c["metalSpot"]
    ex = float(d.get("extractsMetal") or 0)
    if ex <= 0:
        return 0.0
    return round(ex / c["mexBaseExtract"], 4) * c["metalSpot"]


def _def_or_fallback(spec: dict) -> tuple:
    d = unitdef(spec["def"]) if "def" in spec else None
    if d is not None:
        return d, False
    return dict(spec.get("fallback") or {}), True


@lru_cache(maxsize=None)
def builder_profiles() -> Dict[str, dict]:
    out = {}
    for name, spec in config()["builderProfiles"].items():
        if name.startswith("_"):
            continue
        d, provisional = _def_or_fallback(spec)
        out[name] = {"def": spec.get("def"), "buildRange": float(spec["buildRange"]),
                     "speed": float(d.get("speed") or 0), "bp": float(d.get("buildPower") or 0),
                     "provisional": provisional}
    return out


@lru_cache(maxsize=None)
def object_types() -> Dict[str, dict]:
    """bar_unified.OBJECTS / JS OBJECT_TYPES, resolved from the engine defs."""
    cfg = config()
    profiles = builder_profiles()
    out: Dict[str, dict] = {}
    pending_reclaim = []
    for name, spec in cfg["objectTypes"].items():
        if name.startswith("_"):
            continue
        kind = spec.get("kind", "unit")
        if kind == "reclaim":
            pending_reclaim.append((name, spec))
            continue
        d, provisional = _def_or_fallback(spec)
        free = bool(spec.get("free"))
        prod, upk = energy_flows(d)
        wind_powered = bool(spec.get("windPowered")) or float(d.get("windGenerator") or 0) > 0
        factory = bool(spec.get("factory")) or bool(d.get("isFactory"))
        t = {
            "name": name, "defName": spec.get("def"), "kind": kind, "provisional": provisional,
            "metal": 0.0 if free else float(d.get("metalCost") or 0),
            "energy": 0.0 if free else float(d.get("energyCost") or 0),
            "bp": 0.0 if free else float(d.get("buildTime") or 0),
            "mInc": float(d.get("metalMake") or 0) + mex_income(d),
            "eInc": float(cfg["constants"]["defaultWind"]) if wind_powered else prod - upk,
            "storE": float(d.get("energyStorage") or 0),
            "storM": float(d.get("metalStorage") or 0),
            "windPowered": wind_powered,
            "converter": 1 if float(d.get("energyConversionCapacity") or 0) > 0 else 0,
            "factory": factory,
            "free": free,
        }
        if kind == "builder":
            prof = profiles.get(spec.get("profile") or "")
            t["builderBp"] = float(d.get("buildPower") or 0)
            t["speed"] = 0.0 if factory else float(d.get("speed") or 0)
            t["range"] = 0.0 if factory else (prof["buildRange"] if prof else 0.0)
            if spec.get("profile"):
                t["profile"] = spec["profile"]
        out[name] = t
    for name, spec in pending_reclaim:
        of = out[spec["of"]]
        out[name] = {"name": name, "defName": None, "kind": "reclaim", "of": spec["of"], "provisional": False,
                     "metal": 0.0, "energy": 0.0, "bp": of["bp"], "mInc": 0.0, "eInc": 0.0,
                     "storE": 0.0, "storM": 0.0, "windPowered": False, "converter": 0, "factory": False, "free": False}
    return out


def aliases() -> Dict[str, str]:
    """engine defName → object type name (primary defs + faction variants)."""
    out = {}
    for name, spec in config()["objectTypes"].items():
        if not name.startswith("_") and spec.get("def"):
            out[spec["def"]] = name
    for d, name in config()["aliases"].items():
        if not d.startswith("_"):
            out[d] = name
    return out


# ════════════════════════════════════════════════════════════════════════════
# Legion state model (positions/state_api.py)
# ════════════════════════════════════════════════════════════════════════════

def _need(def_name: str) -> dict:
    d = unitdef(def_name)
    if d is None:
        raise KeyError(f"engine def {def_name!r} not found in {[s['path'] for s in config()['engineDefs']]}")
    return d


@lru_cache(maxsize=None)
def legion_actions() -> Dict[str, dict]:
    """state_api.ACTIONS data: metal (net of reclaim), energy, bw, dm, de_inc (None = wind), de_upk,
    reclaim, dn_* deltas, prereq (min counts), label."""
    leg = config()["legion"]
    out: Dict[str, dict] = {}
    for aid, spec in leg["actions"].items():
        d = _need(spec["def"])
        rep = _need(spec["replaces"]) if spec.get("replaces") else None
        reclaim = sum(float(_need(r)["metalCost"]) for r in spec.get("reclaim", []))
        prod, upk = energy_flows(d)
        rprod, rupk = energy_flows(rep) if rep else (0.0, 0.0)
        wind_powered = float(d.get("windGenerator") or 0) > 0
        dm = mex_income(d) - (mex_income(rep) if rep else 0.0)
        de_inc = None if wind_powered else prod - rprod
        de_upk = upk - rupk
        metal = float(d["metalCost"]) - reclaim
        de = (0.0 if de_inc is None else de_inc) - de_upk
        a = {
            "def": spec["def"], "replaces": spec.get("replaces"),
            "label": spec["label"].format(dm=dm, de=de, metal=metal),
            "metal": metal, "energy": float(d["energyCost"]), "bw": float(d["buildTime"]),
            "dm": dm, "de_inc": de_inc, "de_upk": de_upk, "reclaim": reclaim,
            "prereq": dict(spec.get("prereq") or {}),
        }
        for k, v in spec.get("dn", {}).items():
            a["dn_" + k] = int(v)
        out[aid] = a
    return out


@lru_cache(maxsize=None)
def legion_constants() -> dict:
    """The module-level names positions/state_api.py exports, derived from the defs."""
    cfg = config()
    leg = cfg["legion"]
    com = _need(leg["commanderDef"])
    mex, med, moho = _need("legmex"), _need("legmext15"), _need("legmoho")
    sol, win = _need(leg["actions"]["solar"]["def"]), _need(leg["actions"]["wind"]["def"])
    t1_inc, med_inc, moho_inc = mex_income(mex), mex_income(med), mex_income(moho)
    t1_e = energy_flows(mex)[0] - energy_flows(mex)[1]
    med_e = energy_flows(med)[0] - energy_flows(med)[1]
    moho_e = energy_flows(moho)[0] - energy_flows(moho)[1]
    com_prod, com_upk = energy_flows(com)
    base_e_cap = float(cfg["baseState"]["teamStorage"]["energy"]) + float(com.get("energyStorage") or 0)
    return {
        "SPOT": cfg["constants"]["metalSpot"], "T2_MINGEN": float(cfg["constants"]["t2MinGen"]),
        "T1_INC": t1_inc, "MED_INC": med_inc, "MOHO_INC": moho_inc,
        "MED_DELTA": med_inc - t1_inc, "MOHO_FROM_T1": moho_inc - t1_inc, "MOHO_FROM_MED": moho_inc - med_inc,
        "T1_E_NET": t1_e, "MED_E_NET": med_e, "MOHO_E_NET": moho_e,
        "SOLAR_E": energy_flows(sol)[0] - energy_flows(sol)[1], "MED_SWING": t1_e - med_e,
        "T1_METAL": float(mex["metalCost"]), "T1_E_COST": float(mex["energyCost"]), "T1_BW": float(mex["buildTime"]),
        "MED_METAL": float(med["metalCost"]), "MED_E_COST": float(med["energyCost"]), "MED_BW": float(med["buildTime"]),
        "SOL_METAL": float(sol["metalCost"]), "SOL_E_COST": float(sol["energyCost"]), "SOL_BW": float(sol["buildTime"]),
        "WIND_METAL": float(win["metalCost"]), "WIND_E_COST": float(win["energyCost"]), "WIND_BW": float(win["buildTime"]),
        "MOHO_METAL": float(moho["metalCost"]), "MOHO_E_COST": float(moho["energyCost"]), "MOHO_BW": float(moho["buildTime"]),
        "BASE_M": float(com.get("metalMake") or 0), "BASE_E": com_prod - com_upk, "BASE_CAP": base_e_cap,
        "COM_BP": int(com.get("buildPower") or 0), "METAL_CAP": float(leg["metalCap"]),
        "RCL_SOLAR": float(sol["metalCost"]), "RCL_MED": float(med["metalCost"]), "RCL_T1": float(mex["metalCost"]),
        "MOHO_NET_FROM_T1": float(moho["metalCost"]) - float(mex["metalCost"]),
        "MOHO_NET_FROM_MED": float(moho["metalCost"]) - float(med["metalCost"]) - float(mex["metalCost"]),
        "MED_UPK": energy_flows(med)[1], "MEX_UPK": energy_flows(mex)[1],
        "TUR_BP": float(_need(leg["extraUnits"]["leg_turret"]).get("buildPower") or 0),
        "CON_BP": float(_need(leg["extraUnits"]["leg_con"]).get("buildPower") or 0),
    }


def legion_unit_costs() -> Dict[str, tuple]:
    """positions/compare.py UNIT: id → (metal, energy, build work); gross metal (no reclaim credit)."""
    out = {}
    for aid, a in legion_actions().items():
        if aid.startswith("upgrade_"):
            continue
        out[aid] = (a["metal"] + a["reclaim"], a["energy"], a["bw"])
    for uid, dn in config()["legion"]["extraUnits"].items():
        if uid.startswith("_"):
            continue
        d = _need(dn)
        out[uid] = (float(d["metalCost"]), float(d["energyCost"]), float(d["buildTime"]))
    return out


# ════════════════════════════════════════════════════════════════════════════
# summary / drift check
# ════════════════════════════════════════════════════════════════════════════

def model_summary() -> dict:
    cfg = config()
    return {
        "config": os.path.relpath(CONFIG_PATH, REPO_ROOT).replace("\\", "/"),
        "engineDefs": engine_sources(),
        "constants": {k: v for k, v in cfg["constants"].items() if not k.startswith("_")},
        "gridCalibration": {k: v for k, v in cfg["gridCalibration"].items() if not k.startswith("_")},
        "builderProfiles": builder_profiles(),
        "objectTypes": object_types(),
        "aliases": aliases(),
        "legion": {"constants": legion_constants(), "actions": legion_actions(),
                   "unitCosts": {k: list(v) for k, v in legion_unit_costs().items()}},
        "provisional": sorted(n for n, t in object_types().items() if t["provisional"]),
    }


def check(verbose: bool = True) -> list:
    """Drift report: the hand-written tables that still exist vs the resolved model."""
    issues = []
    ot = object_types()
    # barbots/planner/data/units.json (planner; not yet a reader of this file)
    uj = os.path.join(REPO_ROOT, "barbots", "planner", "data", "units.json")
    if os.path.exists(uj):
        with open(uj, encoding="utf-8") as f:
            units = json.load(f)["units"]
        m = {"mex": "Mex", "solar": "Solar", "wind": "Wind", "botlab": "BotFactory", "t2mex": "AMex", "con": "BotWorker"}
        for k, name in m.items():
            u = units.get(k)
            if not u:
                continue
            for uf, tf in (("metal", "metal"), ("energy", "energy"), ("buildWork", "bp")):
                if uf in u and abs(float(u[uf]) - ot[name][tf]) > 1e-9:
                    issues.append(f"barbots/planner/data/units.json {k}.{uf}={u[uf]}  model {name}.{tf}={ot[name][tf]:g}")
    # gex_research/process/lib/sim/eco_engine.mjs UNITS (planner projection engine)
    ee = os.path.join(REPO_ROOT, "gex_research", "process", "lib", "sim", "eco_engine.mjs")
    if os.path.exists(ee):
        src = open(ee, encoding="utf-8").read()
        m = {"wind": "Wind", "solar": "Solar", "advSolar": "AdvSolar", "mex": "Mex", "conTurret": "ConTurret",
             "worker": "BotWorker", "eStorage": "EStorage", "converter": "EConverter"}
        for k, name in m.items():
            mm = re.search(r"^\s*%s:\s*\{\s*m:\s*(-?[\d.]+),\s*e:\s*(-?[\d.]+),\s*bp:\s*(-?[\d.]+)" % re.escape(k), src, re.M)
            if not mm:
                continue
            for val, tf in zip(mm.groups(), ("metal", "energy", "bp")):
                if abs(float(val) - ot[name][tf]) > 1e-9:
                    issues.append(f"eco_engine.mjs UNITS.{k}.{tf}={val}  model {name}.{tf}={ot[name][tf]:g}")
    for n, t in ot.items():
        if t["provisional"]:
            issues.append(f"provisional: {n} ({t['defName']}) is not in any engine dump; using config fallback")
    if verbose:
        print("econ_model drift check")
        print(f"  engine defs: {len(engine_defs())} from {[s['path'] for s in engine_sources() if s['present']]}")
        if not issues:
            print("  no drift")
        for i in issues:
            print("  " + i)
    return issues


def _table_objects() -> str:
    rows = [f"{'name':12}{'def':10}{'kind':9}{'metal':>7}{'energy':>7}{'bw':>7}{'mInc':>7}{'eInc':>6}{'storE':>7}{'storM':>6}{'bBP':>5}{'spd':>6} flags"]
    for n, t in object_types().items():
        flags = " ".join(k for k in ("windPowered", "factory", "free", "provisional") if t.get(k)) + (" conv" if t["converter"] else "")
        rows.append(f"{n:12}{str(t['defName'] or '-'):10}{t['kind']:9}{t['metal']:7.0f}{t['energy']:7.0f}{t['bp']:7.0f}"
                    f"{t['mInc']:7.3f}{t['eInc']:6.0f}{t['storE']:7.1f}{t['storM']:6.0f}{t.get('builderBp', 0):5.0f}{t.get('speed', 0):6.1f} {flags}")
    return "\n".join(rows)


def _table_legion() -> str:
    rows = [f"{'action':18}{'def':10}{'metal':>7}{'energy':>7}{'bw':>6}{'dm':>7}{'de_inc':>7}{'de_upk':>7}{'reclaim':>8}  label"]
    for aid, a in legion_actions().items():
        de = "wind" if a["de_inc"] is None else f"{a['de_inc']:+.0f}"
        rows.append(f"{aid:18}{a['def']:10}{a['metal']:7.0f}{a['energy']:7.0f}{a['bw']:6.0f}{a['dm']:+7.3f}{de:>7}{a['de_upk']:+7.0f}{a['reclaim']:8.0f}  {a['label']}")
    c = legion_constants()
    rows.append("")
    rows.append("  ".join(f"{k}={v:g}" for k, v in c.items() if isinstance(v, (int, float))))
    return "\n".join(rows)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if "--dump" in args:
        print(json.dumps(model_summary(), indent=1))
    elif "--check" in args:
        sys.exit(1 if check() else 0)
    elif "--legion" in args:
        print(_table_legion())
    else:
        print(_table_objects())
        if "--objects" not in args:
            print()
            print(_table_legion())

#!/usr/bin/env python3
"""UNIT CATALOG — every unit and structure, by faction and by the lab that builds it.

The engine knows what each builder can make. Until now nothing downstream did, so every
reader hard-coded its gates: an air con needs an air lab, a Moho needs a T2 con, and those
facts lived in comments. The patched widget now emits `buildOptions` per def, `econ_db`
stores it as 5210 edges over 846 defs, and this module is the view onto it.

    FACTION     Armada, Cortex, Legion, derived from the defName prefix, because BAR
                leaves customParams.faction empty on every def.
    LAB         `products(builder)` is the engine's own list. `who_builds(product)` is
                the inverse, so "what do I need standing before I can make this" is a
                query and not a rule someone wrote down.
    LAYERS      breadth-first from the commander. The tiers are DERIVED: what the
                commander can make, then what those builders unlock, and so on. If the
                game rebalances, the layers change with it.
    OPTIONS     `options(have=[...])` takes what is standing and answers what can be
                built right now, and what one more builder would open up.

Aliases live in `unit_aliases.json`, hand-edited and never overwritten by a harvest, so
"aircon", "nano" and "moho" resolve to defs for every reader at once.

    python bar-calc/unit_catalog.py --tiers
    python bar-calc/unit_catalog.py --faction Armada --tree
    python bar-calc/unit_catalog.py --lab "air lab"
    python bar-calc/unit_catalog.py --who aircon
    python bar-calc/unit_catalog.py --have "armcom,armlab,armck" --options
    python bar-calc/unit_catalog.py --selftest
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import econ_data as ED                                            # noqa: E402
import econ_db as DB                                               # noqa: E402

VERSION = "1.0.0"
NL = chr(10)

# What a def IS, for charting. The DB holds engine facts; this is the interpretation,
# kept here so it can change without re-harvesting.
KIND_ORDER = ("commander", "extractor", "energy", "converter", "storage", "factory",
              "worker", "defence", "unit", "other")


def classify(row: dict) -> str:
    """Which bucket a def belongs in, from engine fields only."""
    raw = {}
    try:
        raw = json.loads(row.get("raw") or "{}")
    except (TypeError, ValueError):
        raw = {}
    # ROLE decides the bucket before economics do. A bot lab holds 100 metal and a con
    # bot trickles 7 E/s, so testing storage or energy first files every factory under
    # storage and every worker under energy, which is what the first cut did.
    if raw.get("isCommander"):
        return "commander"
    if row.get("is_extractor"):
        return "extractor"
    if row.get("is_factory"):
        return "factory"
    if row.get("is_builder"):
        return "worker"
    if (raw.get("energyConversionCapacity") or 0) > 0:
        return "converter"
    # a T1 solar reports energyProduction 0 and carries its 20 E/s as NEGATIVE upkeep,
    # so use econ_data's single derivation rather than re-deriving it here and getting
    # a different answer from the rest of the model
    # the resolved column already nets negative upkeep into production, so a T1 solar
    # reads 20 E/s here rather than the raw field's 0
    prod = float(row.get("energy_production") or 0.0) or ED.energy_flows(raw)[0]
    if prod > 0 or (row.get("wind_generator") or 0) > 0 \
            or (raw.get("tidalGenerator") or 0) > 0:
        return "energy"
    if (row.get("metal_storage") or 0) > 0 or (row.get("energy_storage") or 0) > 0:
        return "storage"
    weapons = raw.get("weaponCount") or 0
    speed = row.get("speed") or 0
    if weapons and not speed:
        return "defence"
    if speed:
        return "unit"
    return "other"


def _rows(path: str = DB.DB_PATH, include_unavailable: bool = False) -> Dict[str, dict]:
    """The def table. Defs the live game no longer offers are excluded by default.

    `unit_overrides.json` is what marks them: a dump is a snapshot of one build, and the
    newest harvest came from a local sdd build that still carries units the live game has
    removed. Showing those as build options is worse than not having them at all."""
    DB.ensure_defs(path)
    con = DB.connect(path)
    sql = "SELECT * FROM unit_defs"
    if not include_unavailable:
        sql += " WHERE COALESCE(available, 1) = 1"
    out = {r["def_name"]: dict(r) for r in con.execute(sql)}
    con.close()
    for d in out.values():
        d["kind"] = classify(d)
        d["alias_list"] = json.loads(d.get("aliases") or "[]")
        d["product_list"] = [x for x in str(d.get("build_options") or "").split(",") if x]
    return out


def products(builder: str, path: str = DB.DB_PATH,
             include_unavailable: bool = False) -> List[str]:
    """What this builder can make, straight from the engine."""
    b = DB.resolve_name(builder, path) or builder
    con = DB.connect(path)
    sql = """SELECT e.product FROM build_edges e
             JOIN unit_defs d ON d.def_name = e.product
             WHERE e.builder = ?"""
    if not include_unavailable:
        sql += " AND COALESCE(d.available, 1) = 1"
    sql += " ORDER BY e.product"
    rows = [r[0] for r in con.execute(sql, (b,))]
    con.close()
    return rows


def who_builds(product: str, path: str = DB.DB_PATH) -> List[str]:
    """Every builder that can make it — the answer to 'what gates this'."""
    p = DB.resolve_name(product, path) or product
    con = DB.connect(path)
    rows = [r[0] for r in con.execute(
        "SELECT builder FROM build_edges WHERE product = ? ORDER BY builder", (p,))]
    con.close()
    return rows


def catalog(faction: Optional[str] = None, path: str = DB.DB_PATH) -> Dict[str, dict]:
    """Every def grouped by faction and then by kind."""
    rows = _rows(path)
    out: Dict[str, dict] = {}
    for name, d in rows.items():
        f = d.get("faction") or "Other"
        if faction and f.lower() != faction.lower():
            continue
        out.setdefault(f, {}).setdefault(d["kind"], []).append(name)
    for f in out:
        for k in out[f]:
            out[f][k].sort()
    return out


def commander_of(faction: str, path: str = DB.DB_PATH) -> Optional[str]:
    """That faction's commander, which is the root of every build tree."""
    for name, d in sorted(_rows(path).items()):
        if (d.get("faction") or "").lower() == faction.lower() \
                and d["kind"] == "commander" and d["product_list"]:
            return name
    return None


def layers(faction: str, root: Optional[str] = None, max_depth: int = 8,
           path: str = DB.DB_PATH) -> List[dict]:
    """Breadth-first from the commander: the tiers, derived rather than asserted.

    Layer 0 is the commander. Layer n+1 is everything the BUILDERS discovered in layer n
    can make. A product that is itself a builder opens the next layer, which is exactly
    how a lab gates its own workers and a worker gates the next lab."""
    rows = _rows(path)
    start = root or commander_of(faction, path)
    if not start:
        return []
    seen = {start}
    frontier = [start]
    out = [{"depth": 0, "builders": [start], "products": [], "new_builders": [start]}]
    for depth in range(1, max_depth + 1):
        prods: set = set()
        for b in frontier:
            for p in rows.get(b, {}).get("product_list", []):
                if p in rows:
                    prods.add(p)
        fresh = sorted(prods - seen)
        if not fresh:
            break
        seen |= set(fresh)
        new_builders = [p for p in fresh if rows[p]["product_list"]]
        by_kind: Dict[str, List[str]] = {}
        for p in fresh:
            by_kind.setdefault(rows[p]["kind"], []).append(p)
        out.append({"depth": depth, "builders": sorted(frontier), "products": fresh,
                    "by_kind": by_kind, "new_builders": new_builders})
        frontier = new_builders
        if not frontier:
            break
    return out


def options(have: Sequence[str], faction: Optional[str] = None,
            path: str = DB.DB_PATH) -> dict:
    """What is buildable right now from what is standing, and what one more opens.

    `have` is whatever exists — a commander, a lab, a worker. Anything in it that can
    build contributes its own product list; everything else is just standing there."""
    rows = _rows(path)
    resolved, unknown = [], []
    for h in have:
        r = DB.resolve_name(h, path)
        (resolved if r else unknown).append(r or h)
    builders = [h for h in resolved if rows.get(h, {}).get("product_list")]
    now: Dict[str, List[str]] = {}
    for b in builders:
        for p in rows[b]["product_list"]:
            if p in rows:
                now.setdefault(p, []).append(b)
    by_kind: Dict[str, List[str]] = {}
    for p in now:
        by_kind.setdefault(rows[p]["kind"], []).append(p)
    for k in by_kind:
        by_kind[k].sort()
    # what a single further builder would unlock that is not already available
    unlocks: List[dict] = []
    for p in sorted(now):
        plist = rows[p]["product_list"]
        if not plist:
            continue
        gain = sorted(set(x for x in plist if x in rows and x not in now))
        if gain:
            unlocks.append({"build": p, "kind": rows[p]["kind"], "name": rows[p].get("human_name"),
                            "unlocks": gain, "count": len(gain)})
    unlocks.sort(key=lambda r: -r["count"])
    fac = faction or next((rows[h].get("faction") for h in resolved if h in rows), None)
    return {"have": resolved, "unknown": unknown, "builders": builders,
            "faction": fac, "buildable_now": sorted(now), "by_kind": by_kind,
            "by_product": now, "unlocks": unlocks,
            "counts": {k: len(v) for k, v in sorted(by_kind.items())}}


def tiers(faction: str = "Armada", path: str = DB.DB_PATH) -> dict:
    """The tier table, read off the engine's own graph instead of written by hand."""
    ls = layers(faction, path=path)
    rows = _rows(path)
    out = []
    for L in ls[1:]:
        gates = sorted({b for b in L["builders"]})
        out.append({"depth": L["depth"], "gated_by": gates,
                    "by_kind": {k: v for k, v in sorted((L.get("by_kind") or {}).items())},
                    "opens_builders": L["new_builders"],
                    "tech": sorted({("T%g" % (rows[p].get("tech_level") or 0))
                                    for p in L["products"]})})
    return {"faction": faction, "root": (ls[0]["builders"][0] if ls else None),
            "layers": out}


# ══════════════════════════════════════════════════════════════════════════
# printing
# ══════════════════════════════════════════════════════════════════════════

def print_catalog(faction: Optional[str] = None, limit: int = 12,
                  path: str = DB.DB_PATH) -> None:
    cat = catalog(faction, path)
    print("UNIT CATALOG" + ("  " + faction if faction else "  all factions"))
    for f in sorted(cat):
        total = sum(len(v) for v in cat[f].values())
        print()
        print("  " + f.upper() + "   " + str(total) + " defs")
        for k in KIND_ORDER:
            if k not in cat[f]:
                continue
            names = cat[f][k]
            print("    " + k.ljust(10) + str(len(names)).rjust(4) + "  "
                  + ", ".join(names[:limit]) + (" ..." if len(names) > limit else ""))


def print_lab(builder: str, path: str = DB.DB_PATH) -> None:
    b = DB.resolve_name(builder, path)
    if not b:
        print("no def, human name or alias matches " + builder)
        return
    rows = _rows(path)
    d = rows[b]
    ps = d["product_list"]
    print("LAB  " + b + "  " + str(d.get("human_name") or "")
          + "   " + str(d.get("faction")) + "  T" + ("%g" % (d.get("tech_level") or 0))
          + ("  factory" if d.get("is_factory") else "")
          + ("  builder" if d.get("is_builder") else ""))
    if d["alias_list"]:
        print("  aliases: " + ", ".join(d["alias_list"]))
    if not ps:
        print("  builds nothing")
        return
    by_kind: Dict[str, List[str]] = {}
    for p in ps:
        if p in rows:
            by_kind.setdefault(rows[p]["kind"], []).append(p)
    print("  builds " + str(len(ps)) + ":")
    for k in KIND_ORDER:
        if k not in by_kind:
            continue
        print("    " + k.ljust(10) + " " + ", ".join(sorted(by_kind[k])))


def print_tree(faction: str = "Armada", path: str = DB.DB_PATH) -> None:
    ls = layers(faction, path=path)
    if not ls:
        print("no commander found for " + faction)
        return
    rows = _rows(path)
    print("BUILD TREE  " + faction + "   root " + ls[0]["builders"][0]
          + "   (breadth-first from the commander, derived from the engine)")
    for L in ls[1:]:
        print()
        print("  DEPTH " + str(L["depth"]) + "  gated by: "
              + ", ".join(L["builders"][:6])
              + (" ..." if len(L["builders"]) > 6 else ""))
        for k in KIND_ORDER:
            names = (L.get("by_kind") or {}).get(k)
            if not names:
                continue
            print("    " + k.ljust(10) + str(len(names)).rjust(3) + "  "
                  + ", ".join(sorted(names)[:10])
                  + (" ..." if len(names) > 10 else ""))
        if L["new_builders"]:
            print("    -> opens " + str(len(L["new_builders"])) + " new builder(s): "
                  + ", ".join(L["new_builders"][:8])
                  + (" ..." if len(L["new_builders"]) > 8 else ""))


def print_options(have: Sequence[str], path: str = DB.DB_PATH) -> None:
    o = options(have, path=path)
    print("OPTIONS  standing: " + ", ".join(o["have"]) + "   faction "
          + str(o["faction"]))
    if o["unknown"]:
        print("  NOT RECOGNISED: " + ", ".join(o["unknown"])
              + "   (add an alias to bar-calc/unit_aliases.json)")
    if not o["builders"]:
        print("  nothing standing can build. You need a builder.")
        return
    print("  builders: " + ", ".join(o["builders"]))
    print("  buildable now: " + str(len(o["buildable_now"])))
    for k in KIND_ORDER:
        names = o["by_kind"].get(k)
        if not names:
            continue
        print("    " + k.ljust(10) + str(len(names)).rjust(3) + "  "
              + ", ".join(names[:12]) + (" ..." if len(names) > 12 else ""))
    if o["unlocks"]:
        print()
        print("  what one more builder would open (most first):")
        for u in o["unlocks"][:8]:
            print("    " + u["build"].ljust(12) + "(" + u["kind"] + ")  +"
                  + str(u["count"]) + " new: " + ", ".join(u["unlocks"][:8])
                  + (" ..." if len(u["unlocks"]) > 8 else ""))


def print_tiers(faction: str = "Armada", path: str = DB.DB_PATH) -> None:
    t = tiers(faction, path)
    print("TIERS  " + faction + "   root " + str(t["root"])
          + "   (derived from the engine's buildOptions, not written down)")
    for L in t["layers"]:
        print()
        print("  " + ("DEPTH %d" % L["depth"]).ljust(9) + "gated by "
              + ", ".join(L["gated_by"][:4])
              + (" ..." if len(L["gated_by"]) > 4 else "")
              + "   tech " + ",".join(L["tech"]))
        for k in KIND_ORDER:
            names = L["by_kind"].get(k)
            if not names:
                continue
            print("      " + k.ljust(10) + " " + ", ".join(sorted(names)[:9])
                  + (" ..." if len(names) > 9 else ""))


def selftest(path: Optional[str] = None, verbose: bool = True) -> bool:
    """The gates the user named must be what the engine says."""
    p = path or DB.DB_PATH
    DB.ensure_defs(p)
    ok = True
    problems: List[str] = []

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            problems.append(msg)

    rows = _rows(p)
    check(len(rows) > 500, "expected the full def table, got " + str(len(rows)))
    edges = DB.connect(p).execute("SELECT COUNT(*) FROM build_edges").fetchone()[0]
    check(edges > 1000, "build tree is empty or tiny: " + str(edges)
          + " edges - re-harvest with the buildOptions patch")

    # the user's own example: no air con until the air lab is standing
    air = DB.resolve_name("aircon", p)
    check(air == "armca", "alias 'aircon' should resolve to armca, got " + str(air))
    gates = who_builds("armca", p)
    check("armap" in gates, "armca should be gated by armap, gates are " + str(gates))
    o = options(["armcom"], path=p)
    check("armca" not in o["buildable_now"],
          "a commander alone must not be able to build an air con")
    check("armap" in o["buildable_now"], "a commander should be able to build armap")
    o2 = options(["armcom", "armap"], path=p)
    check("armca" in o2["buildable_now"],
          "with an air lab standing, an air con must be buildable")

    # the tier claims
    o3 = options(["armcom"], path=p)
    for want in ("armmex", "armsolar", "armwin", "armlab", "armestor", "armmakr"):
        check(want in o3["buildable_now"], "a commander should build " + want)
    check("armnanotc" not in o3["buildable_now"],
          "a con turret should NOT be commander-buildable")
    o4 = options(["armck"], path=p)
    check("armnanotc" in o4["buildable_now"], "a T1 worker should build a con turret")
    check("armadvsol" in o4["buildable_now"], "a T1 worker should build advanced solar")
    check("armalab" in o4["buildable_now"], "a T1 worker should build the T2 lab")
    o5 = options(["armalab"], path=p)
    check("armack" in o5["buildable_now"], "a T2 factory should build the T2 worker")
    o6 = options(["armack"], path=p)
    check("armmoho" in o6["buildable_now"], "a T2 worker should build the Moho")
    check("armmoho" not in o3["buildable_now"],
          "a commander must NOT be able to build the Moho")
    check(DB.resolve_name("moho", p) == "armmoho",
          "alias 'moho' must resolve to armmoho, not the T1 Twilight")

    # role must beat economics in the classification: a bot lab holds storage and a con
    # bot makes 7 E/s, and neither of those is what it IS
    kinds = {n: rows[n]["kind"] for n in rows}
    for name, want in (("armlab", "factory"), ("armap", "factory"),
                       ("armck", "worker"), ("armnanotc", "worker"),
                       ("armsolar", "energy"), ("armmex", "extractor"),
                       ("armestor", "storage"), ("armmakr", "converter"),
                       ("armfus", "energy"), ("armadvsol", "energy"),
                       ("armwin", "energy"), ("armmoho", "extractor"),
                       ("armalab", "factory"), ("armack", "worker")):
        check(kinds.get(name) == want, name + " should classify as " + want + ", got "
              + str(kinds.get(name)))

    # a def the live game has removed must not appear as an option, however present it
    # is in the dump. legmext15 is in units_20260928_155608.json because that harvest
    # came from a local sdd build.
    gone = DB.load_overrides().get("unavailable") or {}
    if "legmext15" in gone:
        check("legmext15" not in rows,
              "legmext15 is marked unavailable and must be hidden by default")
        all_rows = _rows(p, include_unavailable=True)
        check("legmext15" in all_rows,
              "--include-unavailable must still show it, for auditing")
        lo = options(["legck"], path=p)
        check("legmext15" not in lo["buildable_now"],
              "a Legion worker must not be offered the removed extractor")
        lt = tiers("Legion", path=p)
        listed = [x for L in lt["layers"]
                  for v in (L.get("by_kind") or {}).values() for x in v]
        check("legmext15" not in listed, "the Legion tiers must not list it either")
        # and the consequence: Legion's only scaling above legmex is the T2 moho
        legx = sorted(n for n, d in rows.items()
                      if d.get("faction") == "Legion" and d["kind"] == "extractor"
                      and (d.get("tech_level") or 0) < 2)
        check(legx == ["legmex"],
              "with the overcharged extractor gone, legmex should be Legion's only "
              "sub-T2 extractor, got " + str(legx))

    # solar reads 20 E/s through the classifier's own path too
    check((rows.get("armsolar") or {}).get("energy_production") == 20.0,
          "armsolar should carry 20 E/s in the table")

    ls = layers("Armada", path=p)
    check(len(ls) >= 4, "expected at least four layers, got " + str(len(ls)))
    for f in ("Armada", "Cortex", "Legion"):
        check(commander_of(f, p) is not None, f + " has no commander with build options")
        cat = catalog(f, p)
        check(f in cat and sum(len(v) for v in cat[f].values()) > 100,
              f + " has too few defs in the catalog")
    json.dumps({"c": catalog(None, p), "t": tiers("Legion", p), "o": options(["legcom"], path=p)})
    if verbose:
        if ok:
            print("selftest OK: " + str(len(rows)) + " defs, " + str(edges)
                  + " build edges, gates verified for all three factions "
                  + "(air con needs the air lab, con turret needs a worker, "
                  + "Moho needs a T2 worker)")
        else:
            print("selftest FAILED")
            for pr in problems:
                print("  " + pr)
    return ok


def _cli(argv: Sequence[str]) -> None:
    def opt(flag, default=None, cast=str):
        if flag in argv:
            i = list(argv).index(flag)
            if i + 1 < len(argv):
                return cast(argv[i + 1])
        return default

    if "--selftest" in argv:
        sys.exit(0 if selftest() else 1)
    fac = opt("--faction", "Armada")
    if "--tiers" in argv:
        print_tiers(fac)
    elif "--tree" in argv:
        print_tree(fac)
    elif "--lab" in argv:
        print_lab(opt("--lab", "armlab"))
    elif "--who" in argv:
        q = opt("--who", "armca")
        d = DB.resolve_name(q) or q
        gates = who_builds(d)
        print("WHO BUILDS  " + q + " -> " + d)
        if not gates:
            print("  nothing in the tree builds it (a starting unit, or a stale dump)")
        else:
            rows = _rows()
            for g in gates:
                r = rows.get(g, {})
                print("    " + g.ljust(12) + str(r.get("faction", "?")).ljust(8)
                      + "T" + ("%g" % (r.get("tech_level") or 0)).ljust(4)
                      + str(r.get("human_name") or ""))
    elif "--options" in argv:
        have = [x.strip() for x in str(opt("--have", "armcom")).split(",") if x.strip()]
        print_options(have)
    elif "--catalog" in argv:
        print_catalog(None if "--all" in argv else fac)
    else:
        print(__doc__)


if __name__ == "__main__":
    _cli(sys.argv[1:])

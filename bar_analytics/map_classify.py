"""
BAR Map Mex Classifier — starting / natural / expanding / contested
===================================================================

Takes a map-spot file from ``map_spots.py`` and classifies every metal spot by
its role in a team game, then renders a color-coded map so a human can confirm
the classification in bulk. Built for team games with two mirrored sides
(e.g. All That Glitters, 8v8), but the structure generalises to any map.

------------------------------------------------------------------------------
The four classes (the "dichotomy")
------------------------------------------------------------------------------
  starting   Spawn mexes each player takes immediately. Default 3 per player
             ("the natural 3-spawn"). Nearest spots to a start position.
  natural    Safe, uncontested expansion on a player's own half. Backliners
             get ~6 ("the natural 6"); frontliners get fewer, since their
             territory is shallower and closer to the enemy.
  expanding  Further spots on your own half, grabbed as the game develops —
             takeable but deeper/riskier than natural.
  contested  The front line of mexes both teams can reach roughly equally.
             These are fought over. (Map-specific exceptions — e.g. a spot in
             a canyon that is front-line by distance but safe in practice —
             are handled as manual overrides.)

------------------------------------------------------------------------------
How the geometric first pass works
------------------------------------------------------------------------------
  1. Split spawns into two teams by the map midline (long axis).
  2. Within each team, rank spawns by distance from the midline: the far half
     are BACKLINERS, the near half are FRONTLINERS.
  3. Voronoi-assign every mex to its nearest spawn -> owner + team.
  4. d_own  = distance to owning spawn; d_enemy = distance to nearest enemy
     spawn. A mex is CONTESTED when d_enemy / d_own < contested_ratio (the
     enemy can reach it nearly as fast).
  5. For each spawn, its non-contested mexes sorted by distance become:
        rank 1..starting_per_player      -> starting
        next backline/frontline natural  -> natural
        the rest                         -> expanding
  6. Manual OVERRIDES are applied last and always win. They persist in the
     saved JSON, so re-running keeps human corrections — edit `overrides`,
     re-run, regenerate the graphic.

This is a FIRST PASS meant for human confirmation. Distance can't see terrain,
chokes, or which "front-line" spot is actually safe — that's what the graphic
and the overrides list are for.

------------------------------------------------------------------------------
Usage
------------------------------------------------------------------------------
    # classify the seeded ATG2 map-spot file and render the graphic
    python bar_analytics/map_classify.py --in bar_analytics/map_data/ATG2.json

    from bar_analytics.map_classify import classify, render, load_overrides
    cls = classify(map_data, params, overrides)
"""

import argparse
import json
import math
import os
import sys
from typing import Dict, List, Optional

CLASS_COLORS = {
    "starting":  "#2ca02c",  # green
    "natural":   "#1f77b4",  # blue
    "expanding": "#ff7f0e",  # orange
    "contested": "#d62728",  # red
    "unclassified": "#7f7f7f",
}
CLASS_ORDER = ["starting", "natural", "expanding", "contested"]

DEFAULT_PARAMS = {
    "starting_per_player": 3,     # "natural 3-spawn"
    "backline_natural": 6,        # "natural 6" for backliners
    "frontline_natural": 3,       # frontliners' shallower natural
    "contested_ratio": 1.40,      # d_enemy/d_own below this => contested
    "long_axis": "z",             # confrontation axis (z is long on ATG2)
}


def _dist(ax: float, az: float, bx: float, bz: float) -> float:
    return math.hypot(ax - bx, az - bz)


# ──────────────────────────────────────────────────────────────────────────
# Team / role assignment
# ──────────────────────────────────────────────────────────────────────────
def _assign_teams(starts: List[dict], world_w: float, world_h: float,
                  long_axis: str) -> dict:
    """Split spawns into two sides by the map midline on the long axis, then
    label each spawn backliner/frontliner by distance from that midline."""
    axis = long_axis
    extent = world_h if axis == "z" else world_w
    mid = extent / 2.0

    north, south = [], []   # north = low coord side, south = high coord side
    for s in starts:
        (north if s[axis] < mid else south).append(s)

    teams = {}
    for name, group in (("north", north), ("south", south)):
        # farther from midline == deeper in own territory == backliner
        ranked = sorted(group, key=lambda s: abs(s[axis] - mid), reverse=True)
        half = len(ranked) // 2
        back = {s["team"] for s in ranked[:half]}
        front = {s["team"] for s in ranked[half:]}
        teams[name] = {
            "spawn_indices": [s["team"] for s in group],
            "backliners": sorted(back),
            "frontliners": sorted(front),
            "midline": mid,
        }
    return teams


def _team_of_spawn(spawn_idx: int, teams: dict) -> str:
    for name, t in teams.items():
        if spawn_idx in t["spawn_indices"]:
            return name
    return "?"


def _is_backliner(spawn_idx: int, teams: dict) -> bool:
    for t in teams.values():
        if spawn_idx in t["backliners"]:
            return True
    return False


# ──────────────────────────────────────────────────────────────────────────
# Classification
# ──────────────────────────────────────────────────────────────────────────
def classify(map_data: dict, params: Optional[dict] = None,
             overrides: Optional[List[dict]] = None) -> dict:
    p = {**DEFAULT_PARAMS, **(params or {})}
    overrides = overrides or []
    starts = map_data["start_positions"]
    spots = [dict(s) for s in map_data["mex_spots"]]
    teams = _assign_teams(starts, map_data["world_width"],
                          map_data["world_height"], p["long_axis"])

    # Nearest spawn (owner) + nearest enemy spawn distance for every mex.
    for s in spots:
        best_own = None
        dists = []
        for sp in starts:
            d = _dist(s["x"], s["z"], sp["x"], sp["z"])
            dists.append((d, sp["team"]))
        dists.sort()
        owner_d, owner = dists[0]
        owner_team = _team_of_spawn(owner, teams)
        enemy_d = next((d for d, ti in dists
                        if _team_of_spawn(ti, teams) != owner_team), owner_d)
        s["_owner"] = owner
        s["_team"] = owner_team
        s["d_own"] = round(owner_d, 1)
        s["d_enemy"] = round(enemy_d, 1)
        s["_contested"] = (owner_d > 0 and enemy_d / owner_d < p["contested_ratio"])

    # Per-spawn ranking of that spawn's own, non-contested mexes.
    by_owner: Dict[int, List[dict]] = {}
    for s in spots:
        if not s["_contested"]:
            by_owner.setdefault(s["_owner"], []).append(s)

    for owner, group in by_owner.items():
        group.sort(key=lambda s: s["d_own"])
        nat_n = (p["backline_natural"] if _is_backliner(owner, teams)
                 else p["frontline_natural"])
        for rank, s in enumerate(group):
            if rank < p["starting_per_player"]:
                s["cls"] = "starting"
            elif rank < p["starting_per_player"] + nat_n:
                s["cls"] = "natural"
            else:
                s["cls"] = "expanding"
            s["rank"] = rank

    for s in spots:
        if s["_contested"]:
            s["cls"] = "contested"
            s.setdefault("rank", -1)

    # Manual overrides win.
    ovr_by_id = {o["mex_id"]: o for o in overrides}
    for s in spots:
        o = ovr_by_id.get(s["id"])
        if o:
            s["cls"] = o["class"]
            s["override_reason"] = o.get("reason", "")

    # Build clean output records.
    out_spots = []
    for s in spots:
        out_spots.append({
            "id": s["id"], "x": s["x"], "z": s["z"],
            "metal_per_s_est": s.get("metal_per_s_est"),
            "class": s["cls"],
            "team": None if s["cls"] == "contested" else s["_team"],
            "owner_spawn": None if s["cls"] == "contested" else s["_owner"],
            "rank": s.get("rank", -1),
            "d_own": s["d_own"], "d_enemy": s["d_enemy"],
            **({"override_reason": s["override_reason"]}
               if "override_reason" in s else {}),
        })

    counts = {c: sum(1 for s in out_spots if s["class"] == c) for c in CLASS_ORDER}
    return {
        "map": map_data.get("map"),
        "shortname": map_data.get("shortname"),
        "version": map_data.get("version"),
        "source_map_spots": map_data.get("source_archive"),
        "schema_version": "0.1.0",
        "classification_scheme": {
            "starting": "Spawn mexes taken immediately (natural N-spawn per player)",
            "natural": "Safe uncontested expansion on own half (6 for backliners)",
            "expanding": "Further own-half spots taken as the game develops",
            "contested": "Front-line spots both teams contest (see overrides for exceptions)",
        },
        "params": p,
        "teams": teams,
        "counts": counts,
        "overrides": overrides,
        "start_positions": starts,
        "geo_spots": map_data.get("geo_spots", []),
        "mex_spots": out_spots,
    }


def load_overrides(path: str) -> List[dict]:
    """Pull the overrides list out of an existing classification JSON, if any."""
    if path and os.path.isfile(path):
        try:
            return json.load(open(path, encoding="utf-8")).get("overrides", [])
        except (json.JSONDecodeError, OSError):
            return []
    return []


# ──────────────────────────────────────────────────────────────────────────
# Rendering
# ──────────────────────────────────────────────────────────────────────────
def render(cls: dict, png_path: str) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    W = max(s["x"] for s in cls["mex_spots"] + cls["start_positions"])
    H = max(s["z"] for s in cls["mex_spots"] + cls["start_positions"])
    world_h = max(H, max((g["z"] for g in cls["geo_spots"]), default=H))
    fig_h = 13.0
    fig_w = fig_h * (W / world_h) + 2.4  # +room for legend
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    # Midline (front line) for reference.
    mid = cls["teams"]["north"]["midline"]
    ax.axhline(mid, color="#cccccc", lw=1.2, ls="--", zorder=1)
    ax.text(W * 0.5, mid, " front line ", ha="center", va="center",
            fontsize=8, color="#999999",
            bbox=dict(boxstyle="round", fc="white", ec="#cccccc", alpha=0.8), zorder=6)

    # Ownership lines: starting (solid faint) + natural (dotted fainter).
    spawn_xy = {s["team"]: (s["x"], s["z"]) for s in cls["start_positions"]}
    for s in cls["mex_spots"]:
        if s["owner_spawn"] is None:
            continue
        if s["class"] in ("starting", "natural"):
            sx, sz = spawn_xy.get(s["owner_spawn"], (None, None))
            if sx is None:
                continue
            ax.plot([s["x"], sx], [s["z"], sz],
                    color=CLASS_COLORS[s["class"]],
                    lw=0.5, alpha=0.25 if s["class"] == "starting" else 0.15,
                    ls="-" if s["class"] == "starting" else ":", zorder=2)

    # Mex dots, colored by class; size scaled by richness.
    for c in CLASS_ORDER:
        xs = [s["x"] for s in cls["mex_spots"] if s["class"] == c]
        zs = [s["z"] for s in cls["mex_spots"] if s["class"] == c]
        ss = [18 + 4 * (s.get("metal_per_s_est") or 0)
              for s in cls["mex_spots"] if s["class"] == c]
        ax.scatter(xs, zs, s=ss, c=CLASS_COLORS[c], edgecolors="black",
                   linewidths=0.4, alpha=0.9, zorder=4, label=None)

    # Spawns as numbered stars.
    for sp in cls["start_positions"]:
        ax.scatter(sp["x"], sp["z"], s=230, marker="*", c="#ffd400",
                   edgecolors="black", linewidths=0.8, zorder=5)
        ax.text(sp["x"], sp["z"], str(sp["team"]), ha="center", va="center",
                fontsize=7, fontweight="bold", zorder=6)

    # Geothermal vents.
    for g in cls["geo_spots"]:
        ax.scatter(g["x"], g["z"], s=180, marker="^", c="#e377c2",
                   edgecolors="black", linewidths=0.8, zorder=5)

    ax.set_xlim(-150, W + 150)
    ax.set_ylim(-150, world_h + 150)
    ax.invert_yaxis()  # z grows downward => north at top, in-game orientation
    ax.set_aspect("equal")
    ax.set_xlabel("x (elmos)"); ax.set_ylabel("z (elmos)")
    c = cls["counts"]
    name = cls["map"] or cls["shortname"] or "map"
    ver = str(cls["version"] or "")
    disp = name if (ver and ver in name) else f"{name} v{ver}".strip()
    ax.set_title(
        f"{disp} — mex classification "
        f"(start {c['starting']} · natural {c['natural']} · "
        f"expand {c['expanding']} · contested {c['contested']})",
        fontsize=11)

    legend = [Line2D([0], [0], marker="o", color="w", label=c.capitalize(),
                     markerfacecolor=CLASS_COLORS[c], markeredgecolor="black",
                     markersize=9) for c in CLASS_ORDER]
    legend += [
        Line2D([0], [0], marker="*", color="w", label="Spawn",
               markerfacecolor="#ffd400", markeredgecolor="black", markersize=14),
        Line2D([0], [0], marker="^", color="w", label="Geo vent",
               markerfacecolor="#e377c2", markeredgecolor="black", markersize=11),
    ]
    ax.legend(handles=legend, loc="center left", bbox_to_anchor=(1.01, 0.5),
              frameon=True, fontsize=9)

    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(png_path)), exist_ok=True)
    fig.savefig(png_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return png_path


def save_json(cls: dict, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cls, f, indent=2)
    return path


# ──────────────────────────────────────────────────────────────────────────
# Capability registration
# ──────────────────────────────────────────────────────────────────────────
CAPABILITY = {
    "id": "bar_map_classify",
    "name": "BAR Map Mex Classifier",
    "description": (
        "Classify a BAR map's metal spots into starting / natural / expanding / "
        "contested for team games, from a map_spots JSON. Splits spawns into "
        "two sides, labels backliners vs frontliners, Voronoi-assigns spots to "
        "owners, flags front-line spots as contested, and ranks each spawn's "
        "spots (natural 3-spawn, natural 6 for backliners). Manual overrides "
        "persist across re-runs for map-specific exceptions. Renders a "
        "color-coded PNG for bulk human confirmation."
    ),
    "usage": "python bar_analytics/map_classify.py --in bar_analytics/map_data/ATG2.json",
    "inputs": {
        "map_data/<map>.json": "Output of bar_map_spots (spots + starts + geos)",
        "overrides": "Optional manual reclassifications, persisted in the output",
    },
    "outputs": {
        "map_data/<map>_classification.json": "Per-spot class + team + owner + metadata",
        "map_data/<map>_classification.png": "Color-coded confirmation graphic",
    },
    "tags": ["bar", "map", "metal-spots", "classification", "graphic"],
}


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Classify BAR map mex spots and render a graphic.")
    ap.add_argument("--in", dest="infile",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "map_data", "ATG2.json"),
                    help="map_spots JSON (default map_data/ATG2.json).")
    ap.add_argument("--out", default=None, help="Output classification JSON path.")
    ap.add_argument("--png", default=None, help="Output PNG path.")
    ap.add_argument("--no-graphic", action="store_true")
    # Tunables (fall back to DEFAULT_PARAMS).
    ap.add_argument("--starting", type=int, default=None)
    ap.add_argument("--backline-natural", type=int, default=None)
    ap.add_argument("--frontline-natural", type=int, default=None)
    ap.add_argument("--contested-ratio", type=float, default=None)
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    map_data = json.load(open(args.infile, encoding="utf-8"))
    base = os.path.splitext(args.infile)[0]
    out = args.out or base + "_classification.json"
    png = args.png or base + "_classification.png"

    params = {k: v for k, v in {
        "starting_per_player": args.starting,
        "backline_natural": args.backline_natural,
        "frontline_natural": args.frontline_natural,
        "contested_ratio": args.contested_ratio,
    }.items() if v is not None}

    # Preserve any human overrides already saved.
    overrides = load_overrides(out)
    cls = classify(map_data, params, overrides)
    save_json(cls, out)

    c = cls["counts"]
    _name = cls["map"] or cls["shortname"] or "map"
    _ver = str(cls["version"] or "")
    _disp = _name if (_ver and _ver in _name) else f"{_name} v{_ver}".strip()
    print("═" * 64)
    print(f"  {_disp} — mex classification")
    print("═" * 64)
    for name in CLASS_ORDER:
        print(f"  {name:<10} {c[name]:>3}")
    print(f"  {'TOTAL':<10} {sum(c.values()):>3}  of {len(map_data['mex_spots'])} spots")
    print("─" * 64)
    for tname, t in cls["teams"].items():
        print(f"  {tname:<6} backliners {t['backliners']}  frontliners {t['frontliners']}")
    if overrides:
        print("─" * 64)
        print(f"  {len(overrides)} manual override(s) applied")
    print("─" * 64)
    print(f"  Saved JSON → {out}")

    if not args.no_graphic:
        render(cls, png)
        print(f"  Saved PNG  → {png}")


if __name__ == "__main__":
    main()

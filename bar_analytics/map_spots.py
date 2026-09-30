"""
BAR Map Spot Reader — metal spots + geos straight from the map file
===================================================================

Reads a Beyond All Reason map archive (``.sd7``) and extracts, with no game
running and no replay needed:

  * every metal spot   (world x/z position + relative richness)
  * every geothermal vent (world x/z)
  * team start positions, world size, wind range, extractor radius, maxMetal

This is the "read the map properties explicitly" path — it bypasses the
cheat-and-walk-the-replay method entirely. Metal-spot *positions* are exact
(derived from the SMF metal map the engine itself uses). The per-spot metal/s
is an ESTIMATE (``maxMetal * summed_metalmap_bytes / 255``); calibrate the
absolute number against a replay where a mex sits on each spot — the summed
byte value is the authoritative *relative* richness in the meantime.

------------------------------------------------------------------------------
Where the data comes from (BAR / Spring map internals)
------------------------------------------------------------------------------
An .sd7 is a 7-zip archive. Inside:
  * ``mapinfo.lua``  — scalars: name, version, maxMetal, extractorRadius,
                       min/max wind, team startPos list, and the SMF filename.
  * ``maps/<name>.smf`` — Spring Map Format. Its 80-byte header points to a
                       metal map (mapx/2 × mapy/2 bytes, one byte per 16×16-elmo
                       cell, 0-255 intensity) and a feature section listing
                       geovents with world coordinates.

Metal spots are found by connected-components labelling of the non-zero metal
cells (each blob is one spot on a spot-based map like All That Glitters), taking
the metal-weighted centroid as the spot position. A single T1 mex's extractor
radius (50 elmos ≈ 3.1 cells) covers a whole blob here, so one spot == one mex.

------------------------------------------------------------------------------
Usage
------------------------------------------------------------------------------
    # by fuzzy map name (searches the BAR maps dir)
    python bar_analytics/map_spots.py --map "all that glitters"

    # by explicit archive, custom output
    python bar_analytics/map_spots.py --sd7 ".../all_that_glitters_v2.2.3.sd7" \
        --out bar_analytics/map_data/atg2.json

    from bar_analytics.map_spots import read_map, save_json
    m = read_map(sd7_path)
    print(len(m["mex_spots"]), "spots")
    save_json(m, "bar_analytics/map_data/atg2.json")

The JSON is the artifact the walking analysis consumes: mex_spots[].{x,z} and
start positions give every walk distance you need.
"""

import argparse
import glob
import json
import os
import re
import struct
import sys
from typing import Dict, List, Optional

import numpy as np
from scipy import ndimage

# Metal-map cell = 2 heightmap squares. squareSize is 8 elmos, so 16 elmos/cell.
# (squareSize is read from the SMF header; this is the standard value.)
DEFAULT_MAPS_DIR = (
    r"C:\Users\codes\AppData\Local\Programs\Beyond-All-Reason\data\maps"
)
SMF_HEADER_FMT = "<iiiiiiiffiiiiiii"  # 16 fields after the 16-byte magic


# ──────────────────────────────────────────────────────────────────────────
# Archive access
# ──────────────────────────────────────────────────────────────────────────
def _extract_members(sd7_path: str, members: List[str], dest: str) -> Dict[str, str]:
    """Extract named members from the .sd7 into ``dest``; return name→abspath.

    Members not present are simply absent from the result. py7zr matches on the
    exact stored arcname, so we resolve the real path afterward via glob on the
    basename (archives sometimes nest under a top folder).
    """
    import py7zr
    os.makedirs(dest, exist_ok=True)
    with py7zr.SevenZipFile(sd7_path, "r") as z:
        z.extract(path=dest, targets=members)
    found: Dict[str, str] = {}
    for m in members:
        base = os.path.basename(m)
        hits = glob.glob(os.path.join(dest, "**", base), recursive=True)
        if hits:
            found[m] = hits[0]
    return found


def _mapfile_name(sd7_path: str, dest: str) -> str:
    """Return the SMF member path declared in mapinfo.lua (default maps/*.smf)."""
    got = _extract_members(sd7_path, ["mapinfo.lua"], dest)
    if "mapinfo.lua" not in got:
        # Fall back: list archive and grab the first .smf.
        import py7zr
        with py7zr.SevenZipFile(sd7_path, "r") as z:
            smfs = [n for n in z.getnames() if n.lower().endswith(".smf")]
        if not smfs:
            raise FileNotFoundError("no .smf inside " + sd7_path)
        return smfs[0]
    txt = open(got["mapinfo.lua"], encoding="utf-8", errors="replace").read()
    m = re.search(r'mapfile\s*=\s*["\']([^"\']+\.smf)["\']', txt, re.I)
    return m.group(1) if m else "maps/*.smf"


# ──────────────────────────────────────────────────────────────────────────
# mapinfo.lua scalar parsing (regex — no Lua interpreter needed)
# ──────────────────────────────────────────────────────────────────────────
def _parse_mapinfo(path: str) -> dict:
    txt = open(path, encoding="utf-8", errors="replace").read()

    def num(key: str, default: Optional[float] = None) -> Optional[float]:
        m = re.search(key + r"\s*=\s*(-?[0-9.]+)", txt)
        return float(m.group(1)) if m else default

    def s(key: str) -> Optional[str]:
        m = re.search(key + r'\s*=\s*["\']([^"\']+)["\']', txt)
        return m.group(1) if m else None

    starts: List[Dict[str, float]] = []
    tblk = re.search(r"teams\s*=\s*\{(.*?)\n\t\},", txt, re.S)
    if tblk:
        for tm in re.finditer(
            r"\[(\d+)\]\s*=\s*\{startPos\s*=\s*\{x\s*=\s*(-?[0-9.]+)\s*,\s*z\s*=\s*(-?[0-9.]+)",
            tblk.group(1),
        ):
            starts.append({"team": int(tm.group(1)),
                           "x": float(tm.group(2)), "z": float(tm.group(3))})

    return {
        "name": s("name") or "?",
        "shortname": s("shortname") or "?",
        "version": s("version") or "?",
        "author": s("author") or "?",
        "max_metal": num("maxMetal", 1.0),
        "extractor_radius": num("extractorRadius", 50.0),
        "min_wind": num("minWind", 0.0),
        "max_wind": num("maxWind", 0.0),
        "start_positions": starts,
    }


# ──────────────────────────────────────────────────────────────────────────
# SMF parsing
# ──────────────────────────────────────────────────────────────────────────
def _read_smf(smf_path: str) -> dict:
    with open(smf_path, "rb") as f:
        magic = f.read(16)
        if not magic.startswith(b"spring map file"):
            raise ValueError("not an SMF file: " + smf_path)
        h = struct.unpack(SMF_HEADER_FMT, f.read(64))
        (version, mapid, mapx, mapy, square, texel, tilesize,
         min_h, max_h, height_ptr, type_ptr, tiles_ptr, minimap_ptr,
         metal_ptr, feature_ptr, num_extra) = h

        mm_w, mm_h = mapx // 2, mapy // 2
        f.seek(metal_ptr)
        metal = (np.frombuffer(f.read(mm_w * mm_h), dtype=np.uint8)
                 .reshape(mm_h, mm_w).astype(np.float64))

        # Feature section: header (numTypes, numFeatures), then null-terminated
        # type names, then 24-byte records (typeIdx:i, x,y,z,rot,relSize:f×5).
        geos: List[Dict[str, float]] = []
        f.seek(feature_ptr)
        n_types, n_feats = struct.unpack("<ii", f.read(8))
        types: List[str] = []
        for _ in range(n_types):
            buf = bytearray()
            while True:
                c = f.read(1)
                if c in (b"\x00", b""):
                    break
                buf += c
            types.append(buf.decode("utf-8", "replace"))
        for _ in range(n_feats):
            ti, x, y, z, rot, rs = struct.unpack("<ifffff", f.read(24))
            tname = types[ti] if 0 <= ti < len(types) else "?"
            if "geo" in tname.lower():
                geos.append({"x": round(x, 1), "z": round(z, 1)})

    return {
        "mapx": mapx, "mapy": mapy, "square": square,
        "min_height": min_h, "max_height": max_h,
        "world_width": mapx * square, "world_height": mapy * square,
        "metal": metal, "cell_size": square * 2, "geos": geos,
    }


# ──────────────────────────────────────────────────────────────────────────
# Metal-spot detection (connected components + weighted centroid)
# ──────────────────────────────────────────────────────────────────────────
def _find_spots(metal: np.ndarray, cell: int, max_metal: float,
                min_est: float = 0.25) -> List[dict]:
    """One spot per connected non-zero metal blob.

    Position = metal-weighted centroid → world elmos. ``metal_sum`` is the raw
    summed byte intensity (authoritative *relative* richness). ``metal_per_s``
    is the maxMetal-scaled estimate, flagged for replay calibration.
    """
    lbl, n = ndimage.label(metal > 0)  # 4-connectivity
    if n == 0:
        return []
    idx = np.arange(1, n + 1)
    sums = ndimage.sum(metal, lbl, idx)
    sizes = ndimage.sum(np.ones_like(metal), lbl, idx)
    cys, cxs = zip(*ndimage.center_of_mass(metal, lbl, idx))  # weighted (row,col)

    spots: List[dict] = []
    for i in range(n):
        est = max_metal * sums[i] / 255.0
        if est < min_est:
            continue
        spots.append({
            "x": round((cxs[i] + 0.5) * cell, 1),
            "z": round((cys[i] + 0.5) * cell, 1),
            "metal_sum": int(round(sums[i])),
            "metal_per_s_est": round(est, 3),
            "size_cells": int(sizes[i]),
        })
    # Stable, human-friendly ordering: top-to-bottom, then left-to-right.
    spots.sort(key=lambda s: (s["z"], s["x"]))
    for j, s in enumerate(spots):
        s["id"] = j
    return spots


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────
def find_map_archive(query: str, maps_dir: str = DEFAULT_MAPS_DIR) -> str:
    """Fuzzy-match a map name to an .sd7 in ``maps_dir`` (newest version wins)."""
    if os.path.isfile(query):
        return query
    key = re.sub(r"[^a-z0-9]", "", query.lower())
    cands = []
    for p in glob.glob(os.path.join(maps_dir, "*.sd7")):
        norm = re.sub(r"[^a-z0-9]", "", os.path.basename(p).lower())
        if key in norm:
            cands.append(p)
    if not cands:
        raise FileNotFoundError(f"no .sd7 matching {query!r} in {maps_dir}")
    # Prefer the highest version string (lexical on the filename is good enough).
    cands.sort()
    if len(cands) > 1:
        # Version fidelity matters: map versions differ in spots/geos/wind. When
        # matching a specific replay, pass --sd7 for that exact version instead.
        print(f"note: {len(cands)} versions match {query!r}; using the newest "
              f"({os.path.basename(cands[-1])}). Others: "
              + ", ".join(os.path.basename(c) for c in cands[:-1])
              + "  — pass --sd7 for a specific version.", file=sys.stderr)
    return cands[-1]


def read_map(sd7_path: str, scratch: Optional[str] = None) -> dict:
    """Read a map .sd7 → dict with spots, geos, start positions, metadata."""
    scratch = scratch or os.path.join(
        os.environ.get("TEMP", "."), "bar_map_spots", os.path.basename(sd7_path))
    smf_member = _mapfile_name(sd7_path, scratch)
    got = _extract_members(sd7_path, ["mapinfo.lua", smf_member], scratch)
    info = _parse_mapinfo(got["mapinfo.lua"]) if "mapinfo.lua" in got else {}
    if smf_member not in got:
        raise FileNotFoundError(f"could not extract {smf_member} from {sd7_path}")
    smf = _read_smf(got[smf_member])

    spots = _find_spots(smf["metal"], smf["cell_size"],
                        info.get("max_metal", 1.0))
    total_est = round(sum(s["metal_per_s_est"] for s in spots), 1)

    return {
        "map": info.get("name", "?"),
        "shortname": info.get("shortname", "?"),
        "version": info.get("version", "?"),
        "author": info.get("author", "?"),
        "source_archive": os.path.basename(sd7_path),
        "world_width": smf["world_width"],
        "world_height": smf["world_height"],
        "max_metal": info.get("max_metal"),
        "extractor_radius": info.get("extractor_radius"),
        "wind": {"min": info.get("min_wind"), "max": info.get("max_wind")},
        "counts": {"mex_spots": len(spots), "geo_spots": len(smf["geos"]),
                   "start_positions": len(info.get("start_positions", []))},
        "total_metal_per_s_est": total_est,
        "calibration_note": (
            "mex positions are exact; metal_per_s_est = max_metal * "
            "metal_sum / 255 — calibrate absolute M/s against a replay with a "
            "mex on each spot. metal_sum is authoritative relative richness."
        ),
        "start_positions": info.get("start_positions", []),
        "geo_spots": smf["geos"],
        "mex_spots": spots,
    }


def save_json(map_data: dict, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(map_data, f, indent=2)
    return path


# ──────────────────────────────────────────────────────────────────────────
# Capability registration (auto-discovered by capabilities.py)
# ──────────────────────────────────────────────────────────────────────────
CAPABILITY = {
    "id": "bar_map_spots",
    "name": "BAR Map Spot Reader",
    "description": (
        "Read metal-spot and geothermal positions straight from a BAR map "
        "archive (.sd7) — no game running, no replay needed. Parses mapinfo.lua "
        "and the embedded SMF metal map, finds one spot per metal blob "
        "(weighted centroid → world coords), reads geovents from the SMF "
        "feature section, plus team start positions, world size, wind range, "
        "maxMetal and extractor radius. Writes a JSON map file for walking "
        "analysis. Spot positions are exact; per-spot metal/s is an estimate to "
        "calibrate against a replay."
    ),
    "usage": "python bar_analytics/map_spots.py --map \"all that glitters\"\n"
             "python bar_analytics/map_spots.py --sd7 <path.sd7> --out <file.json>",
    "inputs": {
        "map .sd7": "BAR map archive (7-zip). --map fuzzy-finds it in the maps dir",
    },
    "outputs": {
        "map_data/<shortname>.json": "mex_spots, geo_spots, start_positions, meta",
        "stdout": "Summary: counts, wind, richest spots",
    },
    "tags": ["bar", "map", "metal-spots", "geothermal", "parser"],
}


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Read BAR map metal/geo spots from an .sd7.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--map", help="Fuzzy map name to find in the BAR maps dir.")
    g.add_argument("--sd7", help="Explicit path to a map .sd7 archive.")
    ap.add_argument("--maps-dir", default=DEFAULT_MAPS_DIR)
    ap.add_argument("--out", default=None,
                    help="Output JSON path (default bar_analytics/map_data/<shortname>.json).")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    sd7 = args.sd7 if args.sd7 else find_map_archive(args.map, args.maps_dir)
    print(f"Reading: {os.path.basename(sd7)}")
    data = read_map(sd7)

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "map_data", f"{data['shortname']}.json")
    save_json(data, out)

    c = data["counts"]
    print("═" * 66)
    print(f"  {data['map']}  (v{data['version']} by {data['author']})")
    print("═" * 66)
    print(f"  World      : {data['world_width']} x {data['world_height']} elmos")
    print(f"  Wind       : {data['wind']['min']} – {data['wind']['max']}   "
          f"maxMetal {data['max_metal']}   extractorR {data['extractor_radius']}")
    print(f"  Mex spots  : {c['mex_spots']}   "
          f"(total est {data['total_metal_per_s_est']} M/s if all held)")
    print(f"  Geo vents  : {c['geo_spots']}  ->  "
          + ", ".join(f"({g['x']:.0f},{g['z']:.0f})" for g in data["geo_spots"]))
    print(f"  Starts     : {c['start_positions']} team positions")
    print("─" * 66)
    print("  Richest spots (x, z, est M/s):")
    for s in sorted(data["mex_spots"], key=lambda s: -s["metal_per_s_est"])[:6]:
        print(f"    ({s['x']:5.0f}, {s['z']:5.0f})   {s['metal_per_s_est']:.2f}")
    print("─" * 66)
    print(f"  ⚠ {data['calibration_note']}")
    print(f"\n  Saved → {out}")


if __name__ == "__main__":
    main()

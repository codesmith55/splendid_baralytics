#!/usr/bin/env python3
"""HORIZON VIZ - the capstone decision model, drawn.

Three pictures of ONE model, the one in bar_unified.py:

  THE DECISION TABLE (2-D)   rows add build power, columns add energy generation.
      Every cell is coloured by the regime that combination lands in and carries
      the advisor's pick for it. scaling_map + recommend + target_advisor, visual.

  THE FORWARD PROJECTION     build_horizon as a timeline: row i stops to build i
      build-power sources first, marks sit at true completion times, so the
      lateral cost of scaling and the point where it catches up are both readable.

  THE CUBE (3-D)             the same lattice with WIND as depth, one plane per
      wind speed, animated. REPLAY mode plays a real game's measured 15 s samples
      and the regime surface deforms as the position changes; SANDBOX mode puts
      the five quantities on sliders so you can push it and watch it react.

The page computes the model in JavaScript so nothing round-trips. Those functions
are a PORT of bar_unified's, so the payload carries Python-computed expectations
and the page checks itself against them on load - the badge is red if it drifted.

    python bar-calc/horizon_viz.py --game 1 --at 30
    python bar-calc/horizon_viz.py --game 20260925-165017 --target Wind --bpsrc ConTurret
    python bar-calc/bar_unified.py --viz [--game N] [--at SEC]        (same thing)
    python bar-calc/horizon_viz.py --selftest                        (payload + port checks)
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Dict, List, Optional, Sequence, Union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bar_unified as U                                            # noqa: E402

NL = chr(10)
HERE = os.path.dirname(os.path.abspath(__file__))
VIZ_DIR = os.path.join(HERE, "viz")

# the candidate set spans the whole metal:energy ratio spectrum on purpose -
# a pure metal sink (Solar), a pure energy sink (EConverter), and the range between
DEFAULT_CANDIDATES = ("Mex", "Solar", "Wind", "AdvSolar", "BotWorker",
                      "ConTurret", "EConverter", "EStorage")
# depth axis: one plane per wind condition. 11.9 is the MEASURED All That Glitters
# expectation, not the (0+16)/2 midpoint - see bar_unified section 3.
DEFAULT_DEPTH = (4.0, 8.0, 11.9, 16.0)
OVERFLOW_MARGIN = 1.25


def object_table(names: Sequence[str]) -> Dict[str, dict]:
    """The engine-resolved numbers the page needs, and nothing else."""
    out: Dict[str, dict] = {}
    for n in sorted(set(names)):
        t = U.OBJECTS[n]
        out[n] = {"m": t.metal_cost, "e": t.energy_cost, "bp": t.bp_cost,
                  "mInc": t.metal_income, "eInc": t.energy_income,
                  "bpInc": t.bp_income, "storM": t.stor_m, "storE": t.stor_e,
                  "wind": bool(t.wind_powered), "kind": t.kind,
                  "converter": int(t.converter or 0), "factory": bool(t.factory),
                  "provisional": bool(t.provisional), "def": t.def_name}
    return out


def frames_from_game(data: dict, until_sec: float = 600.0) -> List[dict]:
    """One frame per measured 15 s sample: the position, plus what was actually
    built in the window that follows it. The actual builds are the ground truth the
    advice gets read against."""
    comps = data.get("completions") or []
    starts = data.get("starts") or []
    out: List[dict] = []
    for r in (data.get("econ") or []):
        if r["t"] > until_sec:
            break
        st = U.state_from_game(data, r["t"])
        fin = [c["type"] for c in comps
               if r["t"] < c["t"] <= r["t"] + 15 and c.get("type")]
        beg = [c["type"] for c in starts
               if r["t"] <= c["t"] < r["t"] + 15 and c.get("type")]
        out.append({"t": st.t, "metal": st.metal, "energy": st.energy,
                    "mInc": st.m_inc, "eInc": st.e_inc, "bp": st.bp,
                    "bpUsed": r.get("bp_used") or 0.0,
                    "mCap": st.m_cap, "eCap": st.e_cap, "wind": st.wind,
                    "started": list(dict.fromkeys(beg)),
                    "finished": list(dict.fromkeys(fin)),
                    "counts": dict(st.counts)})
    return out


def _state_of(f: dict) -> U.EcoState:
    return U.EcoState(t=f["t"], metal=f["metal"], energy=f["energy"],
                      m_inc=f["mInc"], e_inc=f["eInc"], bp=f["bp"],
                      counts=dict(f.get("counts") or {}),
                      m_cap=f["mCap"], e_cap=f["eCap"], wind=f["wind"])


def port_checks(frames: Sequence[dict], cfg: dict,
                candidates: Sequence[str]) -> List[dict]:
    """Python's own answers for a sample of cells, so the page can verify its port.

    Same discipline as parity.json: the model exists once, and every other copy of
    it has to reproduce these or say so loudly."""
    ES, BS = U.OBJECTS[cfg["energySource"]], U.OBJECTS[cfg["bpSource"]]
    rows: List[dict] = []
    step = max(1, len(frames) // 5)
    for fi in range(0, len(frames), step):
        f = frames[fi]
        st = _state_of(f)
        # regime cells: corners and centre of the lattice, on every wind plane
        for wind in cfg["depth"]:
            e_out = wind if ES.wind_powered else ES.energy_income
            for i in (0, cfg["nBp"] // 2, cfg["nBp"]):
                for j in (0, cfg["nEnergy"] // 2, cfg["nEnergy"]):
                    bp = f["bp"] + i * BS.bp_income
                    m_inc = f["mInc"] + i * BS.metal_income
                    e_inc = f["eInc"] + j * e_out + i * BS.energy_income
                    r = U.regime_of(m_inc, e_inc, bp, cfg["on"], OVERFLOW_MARGIN)
                    rows.append({"kind": "regime", "frame": fi, "i": i, "j": j,
                                 "wind": wind, "regime": r["regime"],
                                 "needM": r["need_m"], "needE": r["need_e"]})
        # absorption profiles at the position itself
        for u in candidates:
            p = U.absorb_profile(st, u)
            rows.append({"kind": "absorb", "frame": fi, "unit": u,
                         "share": p["absorb_share"], "needM": p["needs_m"],
                         "needE": p["needs_e"], "binding": p["binding"]})
        # the advisor's own verdict
        a = U.target_advisor(st, candidates, verbose=False)
        rows.append({"kind": "advice", "frame": fi, "advice": a["advice"],
                     "overflow": bool(a["energy_overflowing"])})
        # and the forward projection, which is the loop most likely to drift
        mid = cfg["depth"][len(cfg["depth"]) // 2]
        for n in (0, cfg["nRows"]):
            pr = U._project_row(st, cfg["target"], cfg["bpSource"], n, mid,
                                cfg["horizon"])
            rows.append({"kind": "project", "frame": fi, "nBp": n, "wind": mid,
                         "targets": pr["targets"], "endBp": pr["end_bp"],
                         "effBp": pr["effective_bp"],
                         "firstT": (pr["events"][0]["t"] if pr["events"] else None)})
    return rows


# ══════════════════════════════════════════════════════════════════════════
# THE CADENCE AND THE PATH — computed in Python, one set per measured frame
#
# These two panels are NOT ported to JavaScript. The lattice and the spectrum are,
# because sliders need them instantly, but the cadence walk and the path search step
# a full state hundreds of times and porting them would be a second copy of the most
# intricate code in the model for no gain. So they ship precomputed per frame, and
# the page says so rather than pretending a sandbox slider moved them.
# ══════════════════════════════════════════════════════════════════════════

def budget_for(data: dict, standing: int, position: str = "front",
               count: Optional[int] = None) -> dict:
    """The mex budget for this game's own map and spawn."""
    g = data.get("game") or {}
    pl = data.get("player") or {}
    return U.mex_budget(map_query=g.get("map") or "All That Glitters",
                        team=int(pl.get("team_id") or 0),
                        count=count, position=position, standing=standing)


def _trim_budget(b: dict) -> dict:
    """Only what the page draws: the spot table is the interesting part."""
    return {k: b[k] for k in ("map", "position", "count", "standing", "room",
                              "spots", "m_per_s_current", "m_per_s_projected",
                              "m_per_s_remaining", "walk_routed_sec",
                              "walk_sum_from_spawn_sec", "rich_spots",
                              "flat_estimate", "spawn")}


def frame_extras(data: dict, frames: Sequence[dict], cfg: dict,
                 position: str = "front", count: Optional[int] = None,
                 workers: int = 3, rows: int = 3, items: int = 10,
                 objective: str = "hold_metal_bound") -> List[dict]:
    """Budget, phases, cadence rows and the path, for every measured frame."""
    out: List[dict] = []
    for f in frames:
        st = _state_of(f)
        standing = int((f.get("counts") or {}).get("Mex", 0))
        b = budget_for(data, standing, position, count)
        ph = U.phase_markers(st, b, target=cfg["target"], on=cfg["on"],
                             workers=workers)
        cad = U.cadence_table(st, target=cfg["target"],
                              scale_source=cfg["bpSource"], rows=rows,
                              items=items, budget=b, workers=workers,
                              verbose=False)
        ps = U.path_search(st, b, target=cfg["target"], bp_source=cfg["bpSource"],
                           on=cfg["on"], horizon=cfg["horizon"] * 2.5,
                           objective_name=objective, workers=workers,
                           verbose=False)
        best = ps["best"]
        out.append({
            "t": f["t"],
            "budget": _trim_budget(b),
            "phases": ph,
            "cadence": {"rows": [{
                "n_scale": r["n_scale"], "targets": r["targets"],
                "invest_sec": r["invest_sec"], "stall_sec": r["stall_sec"],
                "nominal_each": r["nominal_each"], "first_bound": r["first_bound"],
                "at": r["at"], "crossover": r.get("crossover"),
                "stopped": r["stopped"], "end_bp": r["end_bp"],
                "segments": [{k: sg[k] for k in
                              ("kind", "unit", "n", "t_start", "t_end", "dt",
                               "nominal", "stall", "bound", "walk_sec", "bp",
                               "m_inc", "e_inc", "phase")}
                             for sg in r["segments"]]}
                for r in cad["rows"]],
                "bands": cad["bands"],
                "span": max([sg["t_end"] for r in cad["rows"]
                             for sg in r["segments"]] or [1.0])},
            "path": {"objective": objective, "ratio": best["ratio"],
                     "threshold": best["threshold"],
                     "elapsed": best["elapsed"],
                     "metal_bound_sec": best["metal_bound_sec"],
                     "overflow_sec": best["overflow_sec"],
                     "waited_sec": best.get("waited_sec"),
                     "exit_reason": best.get("exit_reason"),
                     "off_chart": best.get("off_chart"),
                     "e_need_projected": best.get("e_need_projected"),
                     "score_detail": best.get("score_detail"),
                     "steps": [{k: x.get(k) for k in
                                ("kind", "unit", "t_start", "t_end", "dt", "bound",
                                 "feed_ratio", "mex", "room", "regime", "bp",
                                 "m_inc", "e_inc", "spilling", "why", "t",
                                 "off_chart")}
                               for x in best["steps"]],
                     "runs": [{"threshold": r["threshold"], "overs": r["overs"],
                               "crosses": r["crosses"], "ratio": r["ratio"],
                               "score": r["score"], "score_detail": r["score_detail"]}
                              for r in ps["runs"]]},
        })
    return out


def build_payload(game: Union[int, str] = 1, at: float = 30.0,
                  target: str = "Wind", bp_source: str = "ConTurret",
                  energy_source: str = "Solar", on: str = "Mex",
                  n_bp: int = 7, n_energy: int = 10, n_rows: int = 5,
                  depth: Sequence[float] = DEFAULT_DEPTH, horizon: float = 240.0,
                  until: float = 600.0,
                  candidates: Sequence[str] = DEFAULT_CANDIDATES,
                  position: str = "front", mex: Optional[int] = None,
                  workers: int = 3, items: int = 10,
                  objective: str = "hold_metal_bound") -> dict:
    """Everything the page needs, computed once from the engine-resolved model."""
    data = U.load_game_data(int(game) if str(game).isdigit() else game)
    frames = frames_from_game(data, until)
    if not frames:
        raise ValueError("no econ samples in that game's hard data")
    cfg = {"target": target, "bpSource": bp_source, "energySource": energy_source,
           "on": on, "nBp": n_bp, "nEnergy": n_energy, "nRows": n_rows,
           "depth": [float(w) for w in depth], "horizon": float(horizon),
           "candidates": list(candidates), "overflowMargin": OVERFLOW_MARGIN,
           "position": position, "mex": mex, "workers": workers, "items": items,
           "objective": objective,
           "objectives": sorted(U.PATH_OBJECTIVES)}
    names = list(candidates) + [target, bp_source, energy_source, on]
    g = data.get("game") or {}
    p = data.get("player") or {}
    start_i = max((i for i, f in enumerate(frames) if f["t"] <= at), default=0)
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "source": "bar-calc/horizon_viz.py over bar_unified.py",
        "game": {"id": g.get("id"), "map": g.get("map"), "matchup": g.get("matchup"),
                 "played": g.get("played_local"), "engine": g.get("engine")},
        "player": {"name": p.get("name"), "team": p.get("team_id"),
                   "faction": p.get("faction")},
        "cfg": cfg, "objects": object_table(names), "frames": frames,
        "startFrame": start_i,
        "constants": {"energyPerMetal": U.ENERGY_PER_METAL, "fps": U.GAME_FPS,
                      "defaultWind": U.DEFAULT_WIND},
        "units": sorted(U.OBJECTS.keys()),
        "extras": frame_extras(data, frames, cfg, position, mex, workers,
                               n_rows, items, objective),
        "checks": port_checks(frames, cfg, candidates),
    }


# ══════════════════════════════════════════════════════════════════════════
# RENDER — one self-contained file, no CDN, no network, opens offline
# ══════════════════════════════════════════════════════════════════════════

def render(payload: dict, title: Optional[str] = None) -> str:
    """The page, with the payload inlined."""
    from horizon_viz_page import PAGE
    g = payload.get("game") or {}
    t = title or ("Build Horizon " + (g.get("id") or ""))
    return (PAGE.replace("__TITLE__", t)
                .replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":"),
                                                   default=str)))


def write(payload: dict, out: Optional[str] = None,
          title: Optional[str] = None) -> str:
    """Write the page under bar-calc/viz/ and return the path."""
    os.makedirs(VIZ_DIR, exist_ok=True)
    gid = (payload.get("game") or {}).get("id") or "state"
    path = out or os.path.join(VIZ_DIR, "horizon_" + str(gid) + ".html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(payload, title))
    return path


def viz(game: Union[int, str] = 1, at: float = 30.0, out: Optional[str] = None,
        open_browser: bool = False, verbose: bool = True, **kw) -> str:
    """Build the payload and write the page. This is what the CLI calls."""
    p = build_payload(game=game, at=at, **kw)
    path = write(p, out)
    if verbose:
        g, cfg = p["game"], p["cfg"]
        print("HORIZON VIZ  " + str(g.get("id")) + "  " + str(g.get("map")))
        print("  target " + cfg["target"] + "   build power from " + cfg["bpSource"]
              + "   energy from " + cfg["energySource"]
              + "   work measured on " + cfg["on"])
        print("  lattice " + str(cfg["nBp"] + 1) + " x " + str(cfg["nEnergy"] + 1)
              + " cells over " + str(len(cfg["depth"])) + " wind planes "
              + str(cfg["depth"]))
        print("  " + str(len(p["frames"])) + " measured frames, "
              + str(len(p["checks"])) + " port checks pinned")
        print("  -> " + path)
    if open_browser:
        import webbrowser
        webbrowser.open("file:///" + path.replace(os.sep, "/"))
    return path


def check_syntax(html: str, verbose: bool = True) -> bool:
    """Parse the WHOLE page script with node, not just the pure block.

    The port check only exercises the model. A typo in a drawing function would
    still break the page silently, and nothing else in this repo would notice."""
    import subprocess
    import tempfile
    i = html.index("<script>") + len("<script>")
    j = html.index("</script>", i)
    body = html[i:j]
    fd, path = tempfile.mkstemp(suffix=".js", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        proc = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        ok = proc.returncode == 0
        if not ok and verbose:
            print("  FAIL page script does not parse:")
            for line in (proc.stderr or "").strip().splitlines()[:8]:
                print("    " + line)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return ok


def check_ids(html: str, verbose: bool = True) -> bool:
    """Every id the script reaches for must exist in the markup.

    A renamed element is the other way this page breaks silently: the model stays
    correct and a panel just never draws."""
    import re as _re
    want = set(_re.findall(r'getElementById\("([^"]+)"\)', html))
    have = set(_re.findall(r'\bid="([^"]+)"', html))
    missing = sorted(want - have)
    if missing and verbose:
        print("  FAIL script reaches for ids that do not exist: " + ", ".join(missing))
    return not missing


def selftest(game: Union[int, str] = 1) -> bool:
    """Payload sanity plus the invariants the page depends on."""
    p = build_payload(game=game)
    ok = True

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        if not cond:
            ok = False
            print("  FAIL " + msg)

    check(len(p["frames"]) >= 2, "need at least two measured frames")
    check(len(p["checks"]) > 0, "no port checks were pinned")
    check(all(k in p["objects"] for k in p["cfg"]["candidates"]),
          "a candidate is missing from the object table")
    for n, o in p["objects"].items():
        check(o["bp"] > 0, n + " has no build work, the page would divide by zero")
    # the ratio spectrum has to actually span, or the picture says nothing
    ratios = [o["e"] / o["m"] for o in p["objects"].values() if o["m"] > 0]
    check(max(ratios) / max(min(ratios), 1e-9) > 10,
          "candidate ratios do not span; pick a wider candidate set")
    check(any(o["e"] == 0 for o in p["objects"].values()),
          "no zero-energy target, so the energy-famine branch is untestable")
    # every pinned regime must be one the page knows how to colour
    regs = {c["regime"] for c in p["checks"] if c["kind"] == "regime"}
    check(regs <= {"metal", "bp", "energy", "overflow"}, "unknown regime " + str(regs))
    html = render(p)
    check("__PAYLOAD__" not in html and "__TITLE__" not in html,
          "a template placeholder survived rendering")
    check(len(html) > 20000, "page suspiciously small")
    check(len(p["extras"]) == len(p["frames"]),
          "one extras block per frame is required")
    e0 = p["extras"][0]
    check(e0["budget"]["count"] > 0, "the budget has no spots")
    check(e0["budget"]["room"] <= e0["budget"]["count"], "room exceeds the budget")
    check(any(r["segments"] for r in e0["cadence"]["rows"]),
          "the cadence produced no segments")
    for r in e0["cadence"]["rows"]:
        for sg in r["segments"]:
            check(sg["dt"] > 0, "a cadence segment has no duration")
            check(sg["t_end"] > sg["t_start"], "a cadence segment does not advance")
    check(e0["path"]["ratio"] is not None, "the path produced no ratio")
    check(e0["phases"]["mex"]["phase"] in ("to_take", "tasked", "taken"),
          "unknown claiming phase")
    check(e0["phases"]["energy"]["phase"] in
          ("underpowered", "spend_current", "spend_projected", "scaling"),
          "unknown spending phase")
    check(check_syntax(html), "the page script has a syntax error")
    check(check_ids(html), "the page script references a missing element id")
    print(("selftest OK: " + str(len(p["frames"])) + " frames, "
           + str(len(p["checks"])) + " pinned checks, page "
           + str(len(html) // 1024) + " kb") if ok else "selftest FAILED")
    return ok


# ══════════════════════════════════════════════════════════════════════════
# VERIFY THE PORT HEADLESSLY — the page's badge is for humans, this is for CI
#
# The page carries a second copy of the decision model, in JavaScript, so that
# dragging a slider re-derives everything with no round trip. A second copy can
# drift. The pure part of that copy sits between two sentinel comments and touches
# no DOM, so it can be cut out and run under Node against the same pinned
# expectations the browser checks. Python computes, JavaScript reproduces, and a
# mismatch is a hard failure rather than a colour in a corner.
# ══════════════════════════════════════════════════════════════════════════

PORT_BEGIN = "/* ==== MODEL PORT BEGIN"
PORT_END = "/* ==== MODEL PORT END ==== */"


def extract_port(html: str) -> str:
    """The pure model block out of a rendered page."""
    i = html.index(PORT_BEGIN)
    j = html.index(PORT_END)
    return html[i:j]


def verify_port(game: Union[int, str] = 1, verbose: bool = True, **kw) -> dict:
    """Run the page's JavaScript model under Node against Python's own answers."""
    import subprocess
    import tempfile
    p = build_payload(game=game, **kw)
    block = extract_port(render(p))
    js = block + NL + "const r = checkPort();" + NL + \
        "console.log(JSON.stringify({n: r.n, bad: r.bad}));" + NL
    fd, path = tempfile.mkstemp(suffix=".mjs", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(js)
        proc = subprocess.run(["node", path], capture_output=True, text=True)
        if proc.returncode != 0:
            out = {"ok": False, "error": (proc.stderr or "node failed").strip()[:2000]}
        else:
            r = json.loads(proc.stdout.strip().splitlines()[-1])
            out = {"ok": not r["bad"], "checked": r["n"], "bad": r["bad"]}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if verbose:
        if out.get("error"):
            print("PORT VERIFY: could not run node - " + out["error"].splitlines()[0])
        elif out["ok"]:
            print("port verify OK: " + str(out["checked"])
                  + " values reproduced by the page's JavaScript")
        else:
            print("PORT DRIFT: " + str(len(out["bad"])) + " of "
                  + str(out["checked"]) + " differ")
            for line in out["bad"][:12]:
                print("   " + line)
    return out


def _cli(argv: Sequence[str]) -> None:
    def opt(flag: str, default, cast=float):
        if flag in argv:
            i = list(argv).index(flag)
            if i + 1 < len(argv):
                return cast(argv[i + 1])
        return default

    if "--verify-port" in argv:
        sys.exit(0 if verify_port(opt("--game", 1, str)).get("ok") else 1)
    if "--selftest" in argv:
        ok = selftest(opt("--game", 1, str))
        ok = bool(verify_port(opt("--game", 1, str)).get("ok")) and ok
        sys.exit(0 if ok else 1)
    depth = [float(x) for x in str(opt("--depth", "", str)).split(",") if x] or list(DEFAULT_DEPTH)
    cands = [x for x in str(opt("--candidates", "", str)).split(",") if x] or list(DEFAULT_CANDIDATES)
    viz(game=opt("--game", 1, str), at=opt("--at", 30.0),
        out=opt("--out", None, str), open_browser="--open" in argv,
        target=opt("--target", "Wind", str), bp_source=opt("--bpsrc", "ConTurret", str),
        energy_source=opt("--energy", "Solar", str), on=opt("--on", "Mex", str),
        n_bp=int(opt("--bprows", 7)), n_energy=int(opt("--ecols", 10)),
        n_rows=int(opt("--rows", 3)), depth=depth,
        horizon=opt("--until", 240.0), until=opt("--frames-until", 600.0),
        candidates=cands, position=opt("--position", "front", str),
        mex=(int(opt("--mex", 0)) or None), workers=int(opt("--workers", 3)),
        items=int(opt("--items", 10)),
        objective=opt("--objective", "hold_metal_bound", str))


if __name__ == "__main__":
    _cli(sys.argv[1:])

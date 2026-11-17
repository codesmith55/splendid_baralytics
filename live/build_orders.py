#!/usr/bin/env python3
"""build_orders.py — build-order chronicle library + website.

Extracts a player's opening from a recorded game (unit_finished events —
recorded completion times; falls back to unit_created + estimated build time
on old streams), stores it as a named JSON in live/builds/, and renders the
whole library as a self-contained site (live/viz/builds.html): completion
timeline per build, per-minute resource snapshots (current + gathered),
auto-computed benchmarks, and a benchmark comparison across starred builds.

Tracked classes: mex, wind, solar, worker, factory, converter, advsolar
(+ nano, moho, advconverter as extras).

CLI:
    python build_orders.py extract <game> --player SL4rk [--name "..."] [--star]
    python build_orders.py extract <game> --team 14
    python build_orders.py list
    python build_orders.py rename <id> "New name"
    python build_orders.py star <id> [--off]
    python build_orders.py render
"""
from __future__ import annotations
import argparse, glob, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import eco_viz  # noqa: E402  (page chrome, palette, formatters)

BUILDS_DIR = os.path.join(HERE, "builds")
GAMES_DIR = os.path.join(HERE, "games")
SITE_PATH = os.path.join(eco_viz.VIZ_DIR, "builds.html")

CLASSES = ["mex", "wind", "solar", "worker", "factory", "converter", "advsolar"]
EXTRAS = ["nano", "moho", "advconverter"]
CLASS_SLOT = {"mex": "s1", "wind": "s2", "solar": "s3", "worker": "s4",
              "factory": "s5", "converter": "s6", "advsolar": "s7",
              "nano": "s4", "moho": "s1", "advconverter": "s6"}
# nth-completion benchmark targets per class
BENCH_N = {"mex": (3, 5, 7), "wind": (5, 10, 20, 30), "solar": (2, 5),
           "worker": (1, 3, 5), "factory": (1, 2), "converter": (1, 5, 10, 16),
           "advsolar": (1, 2), "nano": (1, 3), "moho": (1, 7), "advconverter": (1, 5)}
SNAP_MARKS = (180, 300, 480, 600)      # counts/resources checkpoints (s)
EXTRACT_HORIZON = 900                  # chronicle the first 15 min
EST_BP = 300                           # assumed BP for estimated finishes (old streams)


def classify_def(d):
    n = (d.get("defName") or "").lower()
    if d.get("energyConversionCapacity"):
        return "advconverter" if (d.get("metalCost", 0) or 0) > 50 else "converter"
    if d.get("isFactory"):
        return "factory"
    if "nanotc" in n:
        return "nano"
    if "advsol" in n:
        return "advsolar"
    if "solar" in n:
        return "solar"
    if "win" in n and "wint2" not in n:
        return "wind"
    if "moho" in n:
        return "moho"
    if d.get("isMetalExtractor") or n.endswith("mex"):
        return "mex"
    if d.get("isCommander"):
        return None
    return None                        # untracked (army etc.)


# ── extraction ─────────────────────────────────────────────────────────────
def extract_game(path):
    """One stream pass → teams, defs, per-team finish events + minute resources."""
    defs, teams = {}, {}
    finishes = {}          # tid -> [(t, defID)]
    created = {}           # tid -> [(t, defID)]  (fallback)
    res = {}               # tid -> {"snaps": {minute: {...}}, "m_gath": x, ...}
    session = {}
    saw_finished = False
    last_frame = 0

    def team_res(tid):
        return res.setdefault(tid, {"snaps": {}, "m_gath": 0.0, "e_gath": 0.0,
                                    "last_f": None})

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            a = ev.get("action")
            if a == "init":
                defs, teams, finishes, created, res, session = {}, {}, {}, {}, {}, {}
                saw_finished, last_frame = False, 0
            elif a == "session":
                session["map"] = ev.get("mapName", "")
            elif a == "session_team":
                teams[ev.get("teamID")] = {"name": ev.get("name", ""),
                                           "ally": ev.get("allyTeamID", 0),
                                           "side": ev.get("side", ""),
                                           "startX": ev.get("startX", -1),
                                           "startZ": ev.get("startZ", -1)}
            elif a == "unit_def":
                defs[ev.get("defID")] = ev
            elif a == "unit_finished":
                saw_finished = True
                fr = ev.get("frame", 0)
                if fr <= EXTRACT_HORIZON * 30:
                    finishes.setdefault(ev.get("teamID"), []).append((fr / 30.0, ev.get("defID")))
            elif a == "unit_created":
                fr = ev.get("frame", 0)
                if fr <= EXTRACT_HORIZON * 30:
                    created.setdefault(ev.get("teamID"), []).append((fr / 30.0, ev.get("defID")))
            elif a == "extra_stat_update":
                tid, fr = ev.get("teamID"), ev.get("frame", 0)
                r = team_res(tid)
                if r["last_f"] is not None and fr > r["last_f"]:
                    dt = (fr - r["last_f"]) / 30.0
                    r["m_gath"] += (ev.get("metalIncome", 0) or 0) * dt
                    r["e_gath"] += (ev.get("energyIncome", 0) or 0) * dt
                r["last_f"] = fr
                minute = fr // 1800
                if minute * 1800 <= fr < minute * 1800 + 60 and minute not in r["snaps"] \
                        and minute <= EXTRACT_HORIZON // 60:
                    r["snaps"][minute] = {
                        "t": minute * 60,
                        "metal": round(ev.get("metalCurrent", 0) or 0),
                        "energy": round(ev.get("energyCurrent", 0) or 0),
                        "m_inc": round(ev.get("metalIncome", 0) or 0, 1),
                        "e_inc": round(ev.get("energyIncome", 0) or 0),
                        "m_gathered": round(r["m_gath"]),
                        "e_gathered": round(r["e_gath"]),
                    }
                last_frame = max(last_frame, fr)
    return {"defs": defs, "teams": teams, "finishes": finishes, "created": created,
            "res": res, "session": session, "recorded": saw_finished,
            "duration": last_frame / 30.0}


def _estimate_finishes(created, defs):
    """Old streams: creation time + value/EST_BP as a rough build-wall estimate."""
    out = []
    for t, did in created:
        d = defs.get(did, {})
        out.append((t + (d.get("value", 0) or 0) / EST_BP, did))
    return sorted(out)


def build_record(path, team_id, name=None, star=False):
    g = extract_game(path)
    meta = g["teams"].get(team_id)
    if not meta:
        raise KeyError(f"team {team_id} not in game; have "
                       f"{ {k: v['name'] for k, v in g['teams'].items()} }")
    raw = g["finishes"].get(team_id) if g["recorded"] else None
    if not raw:
        raw = _estimate_finishes(g["created"].get(team_id, []), g["defs"])
    events = []
    for t, did in sorted(raw):
        cls = classify_def(g["defs"].get(did, {}))
        if cls:
            events.append({"t": round(t, 1), "class": cls,
                           "def": g["defs"].get(did, {}).get("defName", "")})
    counts_at = {}
    for mark in SNAP_MARKS:
        c = {}
        for e in events:
            if e["t"] <= mark:
                c[e["class"]] = c.get(e["class"], 0) + 1
        counts_at[str(mark)] = c
    bench = {}
    per_cls = {}
    for e in events:
        per_cls.setdefault(e["class"], []).append(e["t"])
    for cls, targets in BENCH_N.items():
        ts = per_cls.get(cls, [])
        for n in targets:
            if len(ts) >= n:
                bench[f"{cls}{n}"] = ts[n - 1]
    game_id = os.path.splitext(os.path.basename(path))[0]
    sizes = sorted((sum(1 for t in g["teams"].values() if t["ally"] == a)
                    for a in {t["ally"] for t in g["teams"].values()}), reverse=True)
    snaps = g["res"].get(team_id, {}).get("snaps", {})
    rec = {
        "id": f"{game_id}_t{team_id}",
        "game": game_id, "team": team_id,
        "player": meta["name"], "side": meta.get("side", ""),
        "map": g["session"].get("map", ""), "mode": "v".join(map(str, sizes)),
        "recorded": bool(g["recorded"]),
        "name": name or suggest_name(events, meta["name"]),
        "name_suggested": name is None,
        "starred": bool(star),
        "extracted_at": time.time(),
        "duration": round(g["duration"], 1),
        "events": events[:800],
        "snapshots": [snaps[m] for m in sorted(snaps)],
        "counts_at": counts_at,
        "benchmarks": bench,
    }
    return rec


def suggest_name(events, player):
    """Name from the 5:00 shape: dominant flavor + eco counts at the mark."""
    at5 = {}
    for e in events:
        if e["t"] <= 300:
            at5[e["class"]] = at5.get(e["class"], 0) + 1
    conv = sum(1 for e in events if e["class"] == "converter")
    wind_all = sum(1 for e in events if e["class"] == "wind")
    flavor = ("wind-conversion" if conv >= 5 and wind_all >= 15 else
              "wind-heavy" if wind_all >= 15 else
              "solar" if at5.get("solar", 0) > at5.get("wind", 0) else "standard")
    shape = "/".join(f"{at5[c]}{c}" for c in ("mex", "wind", "solar") if at5.get(c))
    return f"{flavor} {shape or 'opening'}@5:00 ({player})"


# ── library ────────────────────────────────────────────────────────────────
def save_build(rec):
    os.makedirs(BUILDS_DIR, exist_ok=True)
    p = os.path.join(BUILDS_DIR, f"{rec['id']}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
    return p


def load_builds():
    out = []
    for p in sorted(glob.glob(os.path.join(BUILDS_DIR, "*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
    out.sort(key=lambda b: (-b.get("starred", False), -b.get("extracted_at", 0)))
    return out


def update_build(build_id, **fields):
    p = os.path.join(BUILDS_DIR, f"{build_id}.json")
    with open(p, encoding="utf-8") as f:
        rec = json.load(f)
    rec.update(fields)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
    return rec


# ── site rendering ─────────────────────────────────────────────────────────
_EXTRA_CSS = """
<style>
.viz-root { --s6: #008300; --s7: #4a3aa7; }
@media (prefers-color-scheme: dark) { .viz-root { --s6: #008300; --s7: #9085e9; } }
.dot.s6{fill:var(--s6)} .dot.s7{fill:var(--s7)}
.key.s6{background:var(--s6)} .key.s7{background:var(--s7)}
.bo-card { background: var(--surface); border: 1px solid var(--ring); border-radius: 10px;
           padding: 14px 16px; margin: 0 0 18px; }
.bo-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; }
.bo-name { font-size: 16px; font-weight: 600; border: none; background: transparent;
           color: var(--ink); min-width: 320px; border-bottom: 1px dashed var(--ring); }
.bo-meta { color: var(--ink2); font-size: 12px; }
.bo-star { cursor: pointer; font-size: 16px; background: none; border: none;
           color: var(--muted); }
.bo-star.on { color: #eda100; }
.lane-label { fill: var(--ink2); font-size: 10px; }
.bo-note { color: var(--muted); font-size: 11px; margin-top: 6px; }
.cmp td.best { font-weight: 700; color: var(--good); }
.estim { color: var(--muted); font-style: italic; }
</style>"""

_SITE_JS = """
<script>
(function () {
  const ov = JSON.parse(localStorage.getItem('build_overlays') || '{}');
  document.querySelectorAll('.bo-name').forEach(inp => {
    const id = inp.dataset.id;
    if (ov[id] && ov[id].name) inp.value = ov[id].name;
    inp.addEventListener('change', () => {
      ov[id] = ov[id] || {}; ov[id].name = inp.value;
      localStorage.setItem('build_overlays', JSON.stringify(ov));
      const n = inp.closest('.bo-card').querySelector('.bo-note');
      n.textContent = 'saved locally — make permanent: python build_orders.py rename '
        + id + ' "' + inp.value + '"';
    });
  });
  document.querySelectorAll('.bo-star').forEach(btn => {
    const id = btn.dataset.id;
    if (ov[id] && ov[id].star !== undefined) btn.classList.toggle('on', ov[id].star);
    btn.addEventListener('click', () => {
      const on = !btn.classList.contains('on');
      btn.classList.toggle('on', on);
      ov[id] = ov[id] || {}; ov[id].star = on;
      localStorage.setItem('build_overlays', JSON.stringify(ov));
      const n = btn.closest('.bo-card').querySelector('.bo-note');
      n.textContent = 'saved locally — make permanent: python build_orders.py star '
        + id + (on ? '' : ' --off');
    });
  });
})();
</script>"""


def _timeline_svg(rec, horizon=None):
    evs = rec["events"]
    if not evs:
        return ""
    horizon = horizon or min(EXTRACT_HORIZON, (int(max(e["t"] for e in evs) // 60) + 1) * 60)
    lanes = [c for c in CLASSES + EXTRAS
             if any(e["class"] == c for e in evs)]
    W, LH, ML, MT = 900, 26, 86, 8
    H = MT * 2 + LH * len(lanes) + 20
    parts = []
    for i in range(0, horizon // 60 + 1):
        x = ML + (W - ML - 12) * (i * 60) / horizon
        parts.append(f'<line x1="{x:.0f}" y1="{MT}" x2="{x:.0f}" y2="{H - 18}" class="grid"/>')
        parts.append(f'<text x="{x:.0f}" y="{H - 6}" class="tick" text-anchor="middle">{i}:00</text>')
    for li, cls in enumerate(lanes):
        y = MT + LH * li + LH / 2
        parts.append(f'<text x="{ML - 8}" y="{y + 3:.0f}" class="lane-label" text-anchor="end">{cls}</text>')
        n = 0
        for e in evs:
            if e["class"] != cls or e["t"] > horizon:
                continue
            n += 1
            x = ML + (W - ML - 12) * e["t"] / horizon
            tip = f"{cls} #{n} — {e['def']} @ {eco_viz._fmt_t(e['t'])}"
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.0f}" r="4.5" '
                         f'class="dot {CLASS_SLOT[cls]} seg" tabindex="0" '
                         f'data-tip="{eco_viz._esc(tip)}"/>')
    legend = '<div class="legend">' + "".join(
        f'<span><i class="key sw {CLASS_SLOT[c]}"></i>{c}</span>' for c in lanes) + "</div>"
    return (legend + f'<div class="plot"><svg viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="build timeline">' + "".join(parts) + "</svg></div>")


def _snapshot_table(rec):
    snaps = rec.get("snapshots", [])
    if not snaps:
        return ""
    head = ("<tr><th>t</th><th>metal</th><th>energy</th><th>m/s</th><th>E/s</th>"
            "<th>metal gathered</th><th>energy gathered</th>"
            + "".join(f"<th>{c}</th>" for c in CLASSES) + "</tr>")
    rows = []
    for s in snaps:
        mark = str(s["t"])
        counts = rec["counts_at"].get(mark) or {}
        if not counts:
            counts = {e["class"]: sum(1 for x in rec["events"]
                                      if x["class"] == e["class"] and x["t"] <= s["t"])
                      for e in rec["events"]}
        rows.append(f"<tr><td>{eco_viz._fmt_t(s['t'])}</td>"
                    f"<td>{s['metal']:,}</td><td>{s['energy']:,}</td>"
                    f"<td>{s['m_inc']}</td><td>{s['e_inc']}</td>"
                    f"<td>{s['m_gathered']:,}</td><td>{s['e_gathered']:,}</td>"
                    + "".join(f"<td>{counts.get(c, 0)}</td>" for c in CLASSES) + "</tr>")
    return ('<details class="tbl" open><summary>Snapshots — resources + completed counts'
            '</summary><div class="scroll"><table><thead>' + head + "</thead><tbody>"
            + "".join(rows) + "</tbody></table></div></details>")


def _bench_label(key):
    for cls in sorted(BENCH_N, key=len, reverse=True):
        if key.startswith(cls):
            return f"{key[len(cls):]}th {cls}" if key[len(cls):] != "1" else f"first {cls}"
    return key


def render_site():
    builds = load_builds()
    body = []
    for rec in builds:
        star = "on" if rec.get("starred") else ""
        est = "" if rec.get("recorded") else ' <span class="estim">(estimated finishes)</span>'
        sug = " (suggested — edit to rename)" if rec.get("name_suggested") else ""
        bench = rec.get("benchmarks", {})
        bench_html = " · ".join(
            f"{_bench_label(k)} <b>{eco_viz._fmt_t(v)}</b>"
            for k, v in sorted(bench.items(), key=lambda kv: kv[1])[:8])
        body.append(
            f'<div class="bo-card" id="{rec["id"]}"><div class="bo-head">'
            f'<button class="bo-star {star}" data-id="{rec["id"]}" title="benchmark star">★</button>'
            f'<input class="bo-name" data-id="{rec["id"]}" value="{eco_viz._esc(rec["name"])}"/>'
            f'<span class="bo-meta">{eco_viz._esc(rec["player"])} · {rec["mode"]} · '
            f'{eco_viz._esc(rec["map"])} · {rec["game"]}{est}{sug}</span></div>'
            + _timeline_svg(rec)
            + f'<div class="bo-meta" style="margin-top:6px">{bench_html}</div>'
            + _snapshot_table(rec)
            + '<div class="bo-note"></div></div>')

    starred = [b for b in builds if b.get("starred")] or builds[:4]
    if len(starred) >= 2:
        keys = sorted({k for b in starred for k in b.get("benchmarks", {})},
                      key=lambda k: min(b["benchmarks"].get(k, 9e9) for b in starred))
        head = "<tr><th>benchmark</th>" + "".join(
            f"<th>{eco_viz._esc(b['name'][:28])}</th>" for b in starred) + "</tr>"
        rows = []
        for k in keys:
            vals = [b["benchmarks"].get(k) for b in starred]
            known = [v for v in vals if v is not None]
            best = min(known) if known else None
            cells = "".join(
                f'<td class="{"best" if v is not None and v == best else ""}">'
                f'{eco_viz._fmt_t(v) if v is not None else "—"}</td>' for v in vals)
            rows.append(f"<tr><td>{_bench_label(k)}</td>{cells}</tr>")
        body.append('<div class="bo-card cmp"><div class="bo-head"><b>Benchmark comparison'
                    '</b><span class="bo-meta">starred builds · fastest in green</span></div>'
                    '<div class="scroll"><table><thead>' + head + "</thead><tbody>"
                    + "".join(rows) + "</tbody></table></div></div>")

    page = eco_viz._page(
        "Build orders",
        f"{len(builds)} builds · completion chronicle (mex, wind, solar, worker, "
        "factory, converter, advsolar) · rename inline, ★ to benchmark",
        "".join(body) or "<p>No builds yet — python build_orders.py extract &lt;game&gt; --player NAME</p>")
    page = page.replace("</head>", _EXTRA_CSS + "</head>").replace("</body>", _SITE_JS + "</body>")
    os.makedirs(eco_viz.VIZ_DIR, exist_ok=True)
    with open(SITE_PATH, "w", encoding="utf-8") as f:
        f.write(page)
    return SITE_PATH


# ── CLI ────────────────────────────────────────────────────────────────────
def _resolve_game(ref):
    if os.path.isfile(str(ref)):
        return str(ref)
    hits = sorted(glob.glob(os.path.join(GAMES_DIR, "*.jsonl")),
                  key=os.path.getmtime, reverse=True)
    for h in hits:
        if os.path.splitext(os.path.basename(h))[0] == str(ref):
            return h
    try:
        return hits[int(ref) - 1]
    except (ValueError, IndexError):
        pass
    m = [h for h in hits if str(ref).lower() in os.path.basename(h).lower()]
    if m:
        return m[0]
    raise FileNotFoundError(f"game not found: {ref}")


def main():
    ap = argparse.ArgumentParser(description="build-order chronicle library + site")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("game")
    e.add_argument("--team", type=int, default=None)
    e.add_argument("--player", default=None)
    e.add_argument("--name", default=None)
    e.add_argument("--star", action="store_true")
    sub.add_parser("list")
    r = sub.add_parser("rename"); r.add_argument("id"); r.add_argument("name")
    s = sub.add_parser("star"); s.add_argument("id"); s.add_argument("--off", action="store_true")
    sub.add_parser("render")
    a = ap.parse_args()

    if a.cmd == "extract":
        path = _resolve_game(a.game)
        tid = a.team
        if tid is None and a.player:
            g = extract_game(path)
            tid = next((k for k, v in g["teams"].items()
                        if a.player.lower() in v["name"].lower()), None)
            if tid is None:
                raise SystemExit(f"player {a.player!r} not found; teams: "
                                 f"{ {k: v['name'] for k, v in g['teams'].items()} }")
        if tid is None:
            raise SystemExit("need --team N or --player NAME")
        rec = build_record(path, tid, name=a.name, star=a.star)
        p = save_build(rec)
        print(f"saved {rec['id']}: {rec['name']!r}  "
              f"({len(rec['events'])} completions, "
              f"{'recorded' if rec['recorded'] else 'ESTIMATED'})  -> {p}")
        print(f"site: {render_site()}")
    elif a.cmd == "list":
        for b in load_builds():
            star = "★" if b.get("starred") else " "
            print(f"{star} {b['id']:28} {b['name'][:44]:44} {b['player']}")
    elif a.cmd == "rename":
        rec = update_build(a.id, name=a.name, name_suggested=False)
        print(f"renamed -> {rec['name']!r}")
        render_site()
    elif a.cmd == "star":
        rec = update_build(a.id, starred=not a.off)
        print(f"{'starred' if rec['starred'] else 'unstarred'} {rec['id']}")
        render_site()
    elif a.cmd == "render":
        print(render_site())


if __name__ == "__main__":
    main()

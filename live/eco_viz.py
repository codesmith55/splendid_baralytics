#!/usr/bin/env python3
"""eco_viz.py — economy visualization for the replayer (and anything with a game object).

Two products, both self-contained HTML (inline SVG, no external libs, light+dark):

    player view   every economy metric for one player over the game
    head-to-head  two players side by side — each side is a game team OR a
                  theoretical state (positions/snapshots.json id or a state
                  JSON file) projected forward with a navigator strategy

Series come from the same read API everything else uses (`game.minutes()` /
`game.recall(m)`), so the module works on the live game, a replayed JSONL, or
an archived game. Theoretical series reuse state_api's engine step-for-step.

Front-ends: replay_jsonl.py --viz / --h2h, and the `series` registry analysis.
"""
from __future__ import annotations
import html as _html
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
_POS = os.path.normpath(os.path.join(HERE, "..", "positions"))
if _POS not in sys.path:
    sys.path.insert(0, _POS)

from state_api import (                                   # noqa: E402
    state_from_dict, state_to_dict, apply_action, _prereq_met,
    ACTIONS, T2_MINGEN,
)
from navigator import STRATEGIES                          # noqa: E402

VIZ_DIR = os.path.join(HERE, "viz")

# value buckets folded to stay inside the categorical comfort zone (5 series)
BUCKET_ORDER = ["economy", "military", "defense", "build_power", "other"]
_BUCKET_FOLD = {"economy": "economy", "military": "military", "defense": "defense",
                "build_power": "build_power"}   # everything else → "other"


# ── series extraction ──────────────────────────────────────────────────────
def game_series(game, team_id):
    """Per-minute metric series for one team of a (live or replayed) game."""
    t, M = [], {k: [] for k in ("m_inc", "e_inc", "metal", "m_cap", "energy", "e_cap",
                                "value", "bp_avail", "bp_used", "bp_util",
                                "n_mex", "n_units", "construction", "storage_value",
                                "eco_added")}
    buckets = {k: [] for k in BUCKET_ORDER}
    label = str(team_id)
    prev_eco_made = None
    for m in game.minutes():
        snap = game.recall(m)
        if not snap:
            continue
        team = next((x for x in snap.get("teams", []) if x.get("teamID") == team_id), None)
        if not team:
            continue
        label = team.get("name") or label
        em = (team.get("flow") or {}).get("eco_made")
        M["eco_added"].append(None if em is None or prev_eco_made is None
                              else round(em - prev_eco_made, 1))
        prev_eco_made = em
        t.append(snap.get("gameSeconds", m * 60))
        M["m_inc"].append(team.get("metalIncome", 0))
        M["e_inc"].append(team.get("energyIncome", 0))
        M["metal"].append(team.get("metalCurrent", 0))
        M["m_cap"].append(team.get("metalStorage", 0))
        M["energy"].append(team.get("energyCurrent", 0))
        M["e_cap"].append(team.get("energyStorage", 0))
        M["value"].append(team.get("total", 0))
        ba, bu = team.get("bpAvail", 0), team.get("bpUsed", 0)
        M["bp_avail"].append(ba)
        M["bp_used"].append(bu)
        M["bp_util"].append(round(100.0 * bu / ba, 1) if ba else 0)
        M["n_mex"].append(team.get("nMex", 0))
        M["n_units"].append(team.get("nUnitsCompleted", 0))
        M["construction"].append(team.get("constructionValue", 0))
        M["storage_value"].append(team.get("storageValue", 0))
        raw = team.get("buckets", {}) or {}
        fold = {k: 0.0 for k in BUCKET_ORDER}
        for k, v in raw.items():
            fold[_BUCKET_FOLD.get(k, "other")] += v or 0
        for k in BUCKET_ORDER:
            buckets[k].append(round(fold[k], 1))
    return {"label": label, "source": "game", "team": team_id,
            "t": t, "metrics": M, "buckets": buckets if t else None}


def theory_series(params, strategy="wind_med", wind_e=None, t_limit=840.0):
    """Project a state_api state forward with a navigator strategy, sampling the
    full state after every engine step — the theoretical side of a head-to-head."""
    if strategy not in STRATEGIES:
        raise KeyError(f"unknown strategy {strategy!r}; available: {list(STRATEGIES)}")
    fn, desc = STRATEGIES[strategy]
    s = state_from_dict(params)
    eff_w = wind_e if wind_e is not None else s.wind_e
    t, M = [], {k: [] for k in ("m_inc", "e_inc", "metal", "n_mex")}
    events = []

    def record(st):
        d = state_to_dict(st)
        t.append(d["t"])
        M["m_inc"].append(round(d["m_inc"], 3))
        M["e_inc"].append(round(d["e_net"], 1))
        M["metal"].append(round(d["metal"], 1))
        M["n_mex"].append(d.get("n_mex", 0) + d.get("n_med", 0) + d.get("n_moho", 0))

    record(s)
    while s.t < t_limit and s.e_net < T2_MINGEN:
        aid = fn(s, eff_w)
        if aid is None or not _prereq_met(s, aid):
            s.tick(5.0)
        else:
            s, _ = apply_action(s, aid, eff_w)
            events.append(s.events[-1])
        record(s)

    return {"label": f"{params.get('id', 'theory')} · {strategy}",
            "source": "theory", "strategy": strategy, "desc": desc,
            "t": t, "metrics": M, "buckets": None, "events": events}


def flow_series(game, team_id):
    """Per-minute behavioral deltas for one team — what the trait detectors eat.
    One row per minute m (starting at the second recorded minute):
      {minute, army_added, eco_added, army_lost_d, eco_lost_d, enemy_killed_d,
       self_removed_d, bank, bank_delta, bp_util, total_value}"""
    rows, prev_f, prev_bank = [], None, None
    for m in game.minutes():
        snap = game.recall(m)
        if not snap:
            continue
        team = next((x for x in snap.get("teams", []) if x.get("teamID") == team_id), None)
        if not team:
            continue
        f = team.get("flow") or {}
        bank = player_layers(team)["bank"]
        ba, bu = team.get("bpAvail", 0) or 0, team.get("bpUsed", 0) or 0
        if prev_f is not None:
            rows.append({
                "minute": m,
                "army_added": round((f.get("army_made", 0) or 0) - (prev_f.get("army_made", 0) or 0), 1),
                "eco_added": round((f.get("eco_made", 0) or 0) - (prev_f.get("eco_made", 0) or 0), 1),
                "army_lost_d": round((f.get("army_lost", 0) or 0) - (prev_f.get("army_lost", 0) or 0), 1),
                "eco_lost_d": round((f.get("eco_lost", 0) or 0) - (prev_f.get("eco_lost", 0) or 0), 1),
                "enemy_killed_d": round((f.get("enemy_killed", 0) or 0) - (prev_f.get("enemy_killed", 0) or 0), 1),
                "self_removed_d": round((f.get("eco_self_removed", 0) or 0) - (prev_f.get("eco_self_removed", 0) or 0), 1),
                "bank": round(bank, 1),
                "bank_delta": round(bank - prev_bank, 1),
                "bp_util": round(100.0 * bu / ba, 1) if ba else 0.0,
                "total_value": team.get("total", 0) or 0,
            })
        prev_f, prev_bank = f, bank
    return rows


def lane_positions(snap):
    """Geometry-based pseudo-position per team: lane index along the spread
    axis + depth relative to the own-team front. Returns {teamID: {lane_i,
    lane_n, position_class}} with position_class like 'front-corner',
    'back-mid' — or {} when the game isn't a clean 2-team layout."""
    teams = [t for t in snap.get("teams", []) if t.get("startX", -1) >= 0]
    by_ally = {}
    for t in teams:
        by_ally.setdefault(t.get("allyTeamID", 0), []).append(t)
    if len(by_ally) != 2:
        return {}
    (a_id, A), (b_id, B) = sorted(by_ally.items())

    def cen(rs, k):
        return sum(t[k] for t in rs) / len(rs)
    sep_x = abs(cen(A, "startX") - cen(B, "startX"))
    sep_z = abs(cen(A, "startZ") - cen(B, "startZ"))
    lane_key = "startZ" if sep_x >= sep_z else "startX"
    front_key = "startX" if lane_key == "startZ" else "startZ"
    out = {}
    for own, enemy in ((A, B), (B, A)):
        toward_enemy = 1 if cen(enemy, front_key) > cen(own, front_key) else -1
        ordered = sorted(own, key=lambda t: (t[lane_key], t["teamID"]))
        depths = sorted(t[front_key] * toward_enemy for t in own)
        median = depths[len(depths) // 2]
        span = max(depths[-1] - depths[0], 1)
        n = len(ordered)
        for i, t in enumerate(ordered):
            lat = "corner" if (i == 0 or i == n - 1) and n > 2 else "mid"
            d = t[front_key] * toward_enemy - median
            depth = "front" if d >= 0 else "back"
            if abs(d) < 0.08 * span:      # essentially on the line with the pack
                depth = "front"
            out[t["teamID"]] = {"lane_i": i, "lane_n": n,
                                "position_class": f"{depth}-{lat}"}
    return out


def load_theory_ref(ref):
    """Resolve `snap:<id>[:strategy]` or `state:<file>[:strategy]` to a series."""
    kind, _, rest = ref.partition(":")
    body, _, strat = rest.partition(":")
    strat = strat or "wind_med"
    if kind == "snap":
        with open(os.path.join(_POS, "snapshots.json"), encoding="utf-8") as f:
            snaps = {s["id"]: s for s in json.load(f)["snapshots"]}
        if body not in snaps:
            raise KeyError(f"unknown snapshot {body!r}; available: {list(snaps)}")
        return theory_series(snaps[body], strat)
    if kind == "state":
        with open(body, encoding="utf-8") as f:
            return theory_series(json.load(f), strat)
    raise ValueError(f"theory ref must be snap:<id>[:strategy] or state:<file>[:strategy], got {ref!r}")


# ── SVG helpers ────────────────────────────────────────────────────────────
W, H = 720, 220
ML, MR, MT, MB = 52, 14, 12, 26
PW, PH = W - ML - MR, H - MT - MB


def _esc(s):
    return _html.escape(str(s), quote=True)


def _fmt_t(sec):
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"


def _fmt_v(v):
    if v is None:
        return "—"
    a = abs(v)
    if a >= 10000:
        return f"{v / 1000:.1f}k"
    if a >= 100:
        return f"{v:,.0f}"
    if a >= 10:
        return f"{v:.1f}"
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def _ticks(lo, hi, n=4):
    if hi <= lo:
        hi = lo + 1
    import math
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    start = math.floor(lo / step) * step
    out = []
    v = start
    while v <= hi + 1e-9:
        if v >= lo - 1e-9:
            out.append(round(v, 6))
        v += step
    return out


def _xy(t, vals, t0, t1, lo, hi):
    pts = []
    for x, y in zip(t, vals):
        if y is None:
            continue
        px = ML + PW * (x - t0) / max(t1 - t0, 1e-9)
        py = MT + PH * (1 - (y - lo) / max(hi - lo, 1e-9))
        pts.append((round(px, 1), round(py, 1)))
    return pts


def _axes_svg(t0, t1, lo, hi, unit=""):
    out = []
    for v in _ticks(lo, hi):
        py = MT + PH * (1 - (v - lo) / max(hi - lo, 1e-9))
        out.append(f'<line x1="{ML}" y1="{py:.1f}" x2="{W - MR}" y2="{py:.1f}" class="grid"/>')
        out.append(f'<text x="{ML - 6}" y="{py + 3:.1f}" class="tick" text-anchor="end">{_fmt_v(v)}</text>')
    n = max(2, min(7, int((t1 - t0) / 60)))
    for i in range(n + 1):
        tv = t0 + (t1 - t0) * i / n
        px = ML + PW * i / n
        out.append(f'<text x="{px:.1f}" y="{H - 8}" class="tick" text-anchor="middle">{_fmt_t(tv)}</text>')
    out.append(f'<line x1="{ML}" y1="{MT + PH}" x2="{W - MR}" y2="{MT + PH}" class="axis"/>')
    if unit:
        out.append(f'<text x="{ML}" y="{MT - 2}" class="tick">{_esc(unit)}</text>')
    return "".join(out)


def line_chart(cid, title, t, series, unit="", subtitle=""):
    """series: [{name, values, cls, context?}] — cls picks the CSS series color.
    A context series renders as a muted reference line and stays out of the legend."""
    vis = [s for s in series if any(v is not None for v in s["values"])]
    if not t or not vis:
        return ""
    t0, t1 = t[0], t[-1]
    allv = [v for s in vis for v in s["values"] if v is not None]
    lo, hi = min(0, min(allv)), max(allv) * 1.06 or 1
    parts = [_axes_svg(t0, t1, lo, hi, unit)]
    for s in vis:
        pts = _xy(t, s["values"], t0, t1, lo, hi)
        if not pts:
            continue
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        cls = "ctx" if s.get("context") else s["cls"]
        if s.get("area") and not s.get("context"):
            parts.append(f'<path d="{d} L{pts[-1][0]},{MT + PH} L{pts[0][0]},{MT + PH} Z" '
                         f'class="area {cls}"/>')
        parts.append(f'<path d="{d}" class="line {cls}" fill="none"/>')
        x, y = pts[-1]
        parts.append(f'<circle cx="{x}" cy="{y}" r="4" class="dot {cls}"/>')
    parts.append(f'<line class="xh" x1="0" y1="{MT}" x2="0" y2="{MT + PH}" visibility="hidden"/>')

    data = {"t": t, "xs": [round(ML + PW * (x - t0) / max(t1 - t0, 1e-9), 1) for x in t],
            "series": [{"name": s["name"], "values": s["values"],
                        "cls": ("ctx" if s.get("context") else s["cls"])} for s in vis],
            "unit": unit}
    keys = [s for s in vis if not s.get("context")]
    legend = ""
    if len(keys) > 1:
        legend = '<div class="legend">' + "".join(
            f'<span><i class="key {s["cls"]}"></i>{_esc(s["name"])}</span>' for s in keys) + "</div>"
    return (f'<figure class="chart viz-line" id="{cid}">'
            f'<figcaption><b>{_esc(title)}</b>'
            f'{f"<span>{_esc(subtitle)}</span>" if subtitle else ""}</figcaption>{legend}'
            f'<div class="plot"><svg viewBox="0 0 {W} {H}" role="img" aria-label="{_esc(title)}">'
            + "".join(parts) +
            f'</svg></div><script type="application/json">{json.dumps(data)}</script></figure>')


def stacked_chart(cid, title, t, buckets, unit="metal value"):
    """Per-minute stacked columns of the value buckets (fixed slot order)."""
    if not t or not buckets:
        return ""
    t0, t1 = t[0], t[-1]
    totals = [sum(buckets[k][i] for k in BUCKET_ORDER) for i in range(len(t))]
    hi = max(totals) * 1.06 or 1
    bw = min(24, max(6, int(PW / max(len(t), 1) * 0.55)))
    parts = [_axes_svg(t0, t1, 0, hi, unit)]
    for i, x in enumerate(t):
        px = ML + PW * (x - t0) / max(t1 - t0, 1e-9) - bw / 2
        y0 = MT + PH
        segs = [(k, buckets[k][i]) for k in BUCKET_ORDER if buckets[k][i] > 0]
        for j, (k, v) in enumerate(segs):
            h = PH * v / hi
            top = y0 - h
            gap = 2 if j < len(segs) - 1 else 0
            tip = f"{_fmt_t(x)} · {k.replace('_', ' ')}: {_fmt_v(v)}"
            if j == len(segs) - 1 and h > 5:      # rounded data-end on the topmost segment
                r = min(4, bw / 2, h)
                d = (f"M{px:.1f},{y0:.1f} L{px:.1f},{top + r:.1f} Q{px:.1f},{top:.1f} {px + r:.1f},{top:.1f} "
                     f"L{px + bw - r:.1f},{top:.1f} Q{px + bw:.1f},{top:.1f} {px + bw:.1f},{top + r:.1f} "
                     f"L{px + bw:.1f},{y0:.1f} Z")
                parts.append(f'<path d="{d}" class="seg b-{k}" tabindex="0" data-tip="{_esc(tip)}"/>')
            else:
                parts.append(f'<rect x="{px:.1f}" y="{top:.1f}" width="{bw}" height="{max(h - gap, 0.5):.1f}" '
                             f'class="seg b-{k}" tabindex="0" data-tip="{_esc(tip)}"/>')
            y0 = top
    legend = '<div class="legend">' + "".join(
        f'<span><i class="key sw b-{k}"></i>{k.replace("_", " ")}</span>' for k in BUCKET_ORDER) + "</div>"
    return (f'<figure class="chart viz-bars" id="{cid}">'
            f'<figcaption><b>{_esc(title)}</b></figcaption>{legend}'
            f'<div class="plot"><svg viewBox="0 0 {W} {H}" role="img" aria-label="{_esc(title)}">'
            + "".join(parts) + '</svg></div></figure>')


def diverging_chart(cid, title, t, diff, pos_label, neg_label, unit=""):
    """Signed lead per sample: positive fills toward pos_label (blue pole),
    negative toward neg_label (red pole), gray zero midline."""
    if not t or not any(d for d in diff):
        return ""
    t0, t1 = t[0], t[-1]
    m = max(abs(d) for d in diff) * 1.1 or 1
    lo, hi = -m, m
    zero_y = MT + PH * (1 - (0 - lo) / (hi - lo))
    bw = min(24, max(6, int(PW / max(len(t), 1) * 0.55)))
    parts = [_axes_svg(t0, t1, lo, hi, unit)]
    parts.append(f'<line x1="{ML}" y1="{zero_y:.1f}" x2="{W - MR}" y2="{zero_y:.1f}" class="axis"/>')
    for x, d in zip(t, diff):
        px = ML + PW * (x - t0) / max(t1 - t0, 1e-9) - bw / 2
        h = abs(d) / (hi - lo) * PH
        y = zero_y - h if d > 0 else zero_y
        cls = "pos" if d > 0 else "neg"
        who = pos_label if d > 0 else neg_label
        tip = f"{_fmt_t(x)} · {who} ahead by {_fmt_v(abs(d))}"
        parts.append(f'<rect x="{px:.1f}" y="{y:.1f}" width="{bw}" height="{max(h, 0.5):.1f}" rx="2" '
                     f'class="seg {cls}" tabindex="0" data-tip="{_esc(tip)}"/>')
    legend = (f'<div class="legend"><span><i class="key sw pos"></i>{_esc(pos_label)} ahead</span>'
              f'<span><i class="key sw neg"></i>{_esc(neg_label)} ahead</span></div>')
    return (f'<figure class="chart viz-bars" id="{cid}">'
            f'<figcaption><b>{_esc(title)}</b></figcaption>{legend}'
            f'<div class="plot"><svg viewBox="0 0 {W} {H}" role="img" aria-label="{_esc(title)}">'
            + "".join(parts) + '</svg></div></figure>')


def _tile(label, value, delta=None, unit=""):
    d = ""
    if delta is not None and delta != 0:
        cls = "up" if delta > 0 else "down"
        d = f'<span class="delta {cls}">{"+" if delta > 0 else ""}{_fmt_v(delta)} vs prev min</span>'
    u = f'<span class="unit">{_esc(unit)}</span>' if unit else ""
    return (f'<div class="tile"><div class="tlabel">{_esc(label)}</div>'
            f'<div class="tvalue">{_fmt_v(value)}{u}</div>{d}</div>')


def kpi_row(series):
    t, M = series["t"], series["metrics"]
    if not t:
        return ""
    i, p = -1, -2 if len(t) > 1 else -1

    def dv(key):
        col = M.get(key)
        if not col or col[i] is None or col[p] is None:
            return None
        return round(col[i] - col[p], 2)

    tiles = [_tile("Metal income", M["m_inc"][i], dv("m_inc"), "m/s"),
             _tile("Energy income", M["e_inc"][i], dv("e_inc"), "E/s"),
             _tile("Metal bank", M["metal"][i], dv("metal"), "m")]
    if M.get("value") and any(v is not None for v in M["value"]):
        tiles.append(_tile("Total value", M["value"][i], dv("value"), "m"))
    if M.get("bp_util") and any(v is not None for v in M["bp_util"]):
        tiles.append(_tile("BP utilization", M["bp_util"][i], dv("bp_util"), "%"))
    tiles.append(_tile("Mex", M["n_mex"][i], dv("n_mex")))
    if M.get("eco_added") and any(v is not None for v in M["eco_added"]):
        tiles.append(_tile("Eco added (last min)", M["eco_added"][i], dv("eco_added"), "m"))
    return '<div class="tiles">' + "".join(tiles) + "</div>"


def data_table(series_list):
    """The non-gated view: every sample of every metric, per player."""
    out = []
    for s in series_list:
        keys = [k for k, col in s["metrics"].items() if any(v is not None for v in col)]
        head = "".join(f"<th>{_esc(k)}</th>" for k in keys)
        rows = []
        for i, tv in enumerate(s["t"]):
            cells = "".join(f"<td>{_fmt_v(s['metrics'][k][i])}</td>" for k in keys)
            rows.append(f"<tr><td>{_fmt_t(tv)}</td>{cells}</tr>")
        out.append(f'<details class="tbl"><summary>Data table — {_esc(s["label"])}</summary>'
                   f'<div class="scroll"><table><thead><tr><th>t</th>{head}</tr></thead>'
                   f'<tbody>{"".join(rows)}</tbody></table></div></details>')
    return "".join(out)


# ── page assembly ──────────────────────────────────────────────────────────
_CSS = """
:root { color-scheme: light dark; }
body { margin: 0; background: var(--page); color: var(--ink);
       font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
.viz-root {
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4;
  --pos:#2a78d6; --neg:#e34948; --good:#006300; --bad:#d03b3b;
  max-width: 1560px; margin: 0 auto; padding: 20px 24px 48px; }
@media (prefers-color-scheme: dark) {
  .viz-root { --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7;
    --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181;
    --pos:#3987e5; --neg:#e66767; --good:#0ca30c; --bad:#e66767; } }
h1 { font-size: 20px; margin: 0 0 2px; }
.sub { color: var(--ink2); margin: 0 0 18px; }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 16px; }
.tiles { display: flex; flex-wrap: wrap; gap: 12px; margin: 0 0 18px; }
.tile { background: var(--surface); border: 1px solid var(--ring); border-radius: 10px;
        padding: 10px 16px 12px; min-width: 128px; }
.tlabel { color: var(--ink2); font-size: 12px; }
.tvalue { font-size: 26px; font-weight: 600; }
.tvalue .unit { font-size: 12px; font-weight: 400; color: var(--muted); margin-left: 4px; }
.delta { display: block; font-size: 11px; color: var(--ink2); }
.delta.up { color: var(--good); } .delta.down { color: var(--bad); }
.chart { background: var(--surface); border: 1px solid var(--ring); border-radius: 10px;
         margin: 0; padding: 12px 14px; }
figcaption b { font-size: 13px; }
figcaption span { color: var(--ink2); font-size: 12px; margin-left: 8px; }
.plot { position: relative; }
svg { width: 100%; height: auto; display: block; }
.grid { stroke: var(--grid); stroke-width: 1; }
.axis { stroke: var(--axis); stroke-width: 1; }
.tick { fill: var(--muted); font-size: 10px; }
.line { stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.line.s1{stroke:var(--s1)} .line.s2{stroke:var(--s2)} .line.s3{stroke:var(--s3)}
.line.s4{stroke:var(--s4)} .line.s5{stroke:var(--s5)} .line.ctx{stroke:var(--axis)}
.area { fill-opacity: .1; stroke: none; }
.area.s1{fill:var(--s1)} .area.s2{fill:var(--s2)} .area.s3{fill:var(--s3)}
.dot { stroke: var(--surface); stroke-width: 2; }
.dot.s1{fill:var(--s1)} .dot.s2{fill:var(--s2)} .dot.s3{fill:var(--s3)}
.dot.s4{fill:var(--s4)} .dot.s5{fill:var(--s5)} .dot.ctx{fill:var(--axis)}
.seg { stroke: var(--surface); stroke-width: 1; outline: none; }
.seg:hover, .seg:focus { filter: brightness(1.12); }
.seg.b-economy{fill:var(--s1)} .seg.b-military{fill:var(--s2)} .seg.b-defense{fill:var(--s3)}
.seg.b-build_power{fill:var(--s4)} .seg.b-other{fill:var(--s5)}
.seg.pos{fill:var(--pos)} .seg.neg{fill:var(--neg)}
.xh { stroke: var(--axis); stroke-width: 1; }
.legend { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12px; color: var(--ink2);
          margin: 4px 0 2px; }
.legend .key { display: inline-block; width: 14px; height: 3px; border-radius: 2px;
               vertical-align: middle; margin-right: 5px; }
.legend .key.sw { height: 10px; width: 10px; border-radius: 3px; }
.key.s1{background:var(--s1)} .key.s2{background:var(--s2)} .key.s3{background:var(--s3)}
.key.s4{background:var(--s4)} .key.s5{background:var(--s5)}
.key.b-economy{background:var(--s1)} .key.b-military{background:var(--s2)}
.key.b-defense{background:var(--s3)} .key.b-build_power{background:var(--s4)}
.key.b-other{background:var(--s5)}
.key.pos{background:var(--pos)} .key.neg{background:var(--neg)}
.tip { position: fixed; pointer-events: none; background: var(--surface); color: var(--ink);
       border: 1px solid var(--ring); border-radius: 8px; padding: 8px 10px; font-size: 12px;
       box-shadow: 0 4px 14px rgba(0,0,0,.15); visibility: hidden; z-index: 10; max-width: 260px; }
.tip .tv { font-weight: 600; }
.tip .row { display: flex; align-items: center; gap: 6px; }
.tip .k { display: inline-block; width: 12px; height: 3px; border-radius: 2px; }
.tstrip { margin: 0 0 14px; font-size: 13px; color: var(--ink2); }
.tstrip a { color: var(--ink2); text-decoration: none; padding: 3px 8px; border-radius: 6px; }
.tstrip a:hover { background: var(--surface); }
.tstrip a.cur { background: var(--surface); color: var(--ink); font-weight: 600;
                border: 1px solid var(--ring); }
.legend.big { font-size: 13px; margin: 0 0 14px; align-items: center; }
.legend.big .hint { color: var(--muted); margin-left: auto; }
.lic { width: 14px; height: 14px; vertical-align: -2px; margin-right: 5px; }
.bgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 16px; }
.panel { margin: 0 0 clamp(8px, 1.5vw, 20px); }
.phead { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
         margin: 0 0 6px; font-size: clamp(11px, 1.2vw, 14px); }
.phead span { color: var(--ink2); font-size: clamp(10px, 1vw, 12px); }
.pgrid { display: grid; gap: clamp(4px, 0.8vw, 14px); }
.bcard { background: var(--surface); border: 1px solid var(--ring); border-radius: 10px;
         padding: clamp(4px, 0.8vw, 14px); text-align: center; min-width: 0; }
.bcard svg { max-width: 230px; margin: 0 auto; }
.bname { font-weight: 600; font-size: clamp(10px, 1.1vw, 14px); text-align: left;
         white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bsub { color: var(--muted); font-weight: 400; font-size: clamp(9px, 0.9vw, 11px); margin-left: 6px; }
.btotal { font-size: clamp(14px, 1.8vw, 24px); font-weight: 600; }
.btotal .unit { font-size: 11px; font-weight: 400; color: var(--muted); margin-left: 5px; }
.bvals { font-size: clamp(8px, 0.85vw, 11px); color: var(--ink2); }
.bub { stroke: var(--surface); stroke-width: 2; outline: none; }
.bub:hover, .bub:focus { filter: brightness(1.1); }
.bub.s1{fill:var(--s1)} .bub.s2{fill:var(--s2)} .bub.s3{fill:var(--s3)}
.bub.s4{fill:var(--s4)} .bub.s5{fill:var(--s5)}
.badge .bbg { fill: var(--surface); }
.bic { fill: none; stroke-width: 1.4; stroke-linejoin: round; stroke-linecap: round; }
.bic.s1{stroke:var(--s1)} .bic.s2{stroke:var(--s2)} .bic.s3{stroke:var(--s3)}
.bic.s4{stroke:var(--s4)} .bic.s5{stroke:var(--s5)}
.pair { display: flex; gap: clamp(2px, 0.5vw, 8px); justify-content: center; align-items: flex-end; }
.half { flex: 1 1 0; min-width: 0; }
.half svg { max-width: 170px; }
.bcap { font-size: clamp(8px, 0.9vw, 11px); color: var(--ink2); margin-top: 2px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chips { display: flex; flex-direction: column; gap: 3px; margin-top: 6px; text-align: left; }
.chip { font-size: clamp(8px, 0.85vw, 11px); color: var(--ink2); line-height: 1.3; }
.chip b { display: inline-block; width: 12px; }
.chip.good b { color: var(--good); }
.chip.warning b { color: #b97900; }
.chip.serious b { color: var(--bad); }
@media (max-width: 1000px) {
  .viz-root { padding: 8px 10px 24px; }
  h1 { font-size: 15px; } .sub { margin-bottom: 8px; }
  .legend.big { gap: 8px; margin-bottom: 8px; } .legend.big .hint { display: none; }
  .tstrip { margin-bottom: 8px; }
  .bsub, .bvals { display: none; }        /* tooltips + table still carry the numbers */
  .chips { gap: 2px; margin-top: 3px; }
}
.tbl { margin-top: 16px; background: var(--surface); border: 1px solid var(--ring);
       border-radius: 10px; padding: 10px 14px; }
.tbl summary { cursor: pointer; color: var(--ink2); font-size: 13px; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; font-size: 12px; margin-top: 8px;
        font-variant-numeric: tabular-nums; }
th, td { padding: 3px 10px; text-align: right; border-bottom: 1px solid var(--grid); }
th { color: var(--ink2); font-weight: 600; }
"""

_JS = """
(function () {
  const tip = document.createElement('div');
  tip.className = 'tip'; document.body.appendChild(tip);
  function showTip(x, y, html) {
    tip.innerHTML = html; tip.style.visibility = 'visible';
    const r = tip.getBoundingClientRect();
    tip.style.left = Math.min(x + 14, innerWidth - r.width - 8) + 'px';
    tip.style.top = Math.min(y + 14, innerHeight - r.height - 8) + 'px';
  }
  function hideTip() { tip.style.visibility = 'hidden'; }
  const esc = s => { const d = document.createElement('span'); d.textContent = s; return d.innerHTML; };
  const fmtT = s => Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0');
  const fmtV = v => v == null ? '—' : Math.abs(v) >= 10000 ? (v / 1000).toFixed(1) + 'k'
    : Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : Math.abs(v) >= 10 ? v.toFixed(1) : (+v).toFixed(2);

  document.querySelectorAll('.viz-line').forEach(fig => {
    const d = JSON.parse(fig.querySelector('script').textContent);
    const svg = fig.querySelector('svg'), xh = fig.querySelector('.xh');
    svg.addEventListener('pointermove', ev => {
      const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
      const p = pt.matrixTransform(svg.getScreenCTM().inverse());
      let best = 0, bd = 1e9;
      d.xs.forEach((x, i) => { const dd = Math.abs(x - p.x); if (dd < bd) { bd = dd; best = i; } });
      xh.setAttribute('x1', d.xs[best]); xh.setAttribute('x2', d.xs[best]);
      xh.setAttribute('visibility', 'visible');
      const rows = d.series.map(s =>
        '<div class="row"><i class="k ' + s.cls + '" style="background:var(--' +
        (s.cls === 'ctx' ? 'axis' : s.cls) + ')"></i><span class="tv">' +
        fmtV(s.values[best]) + '</span> <span>' + esc(s.name) + '</span></div>').join('');
      showTip(ev.clientX, ev.clientY, '<div>' + fmtT(d.t[best]) +
        (d.unit ? ' · ' + esc(d.unit) : '') + '</div>' + rows);
    });
    svg.addEventListener('pointerleave', () => { xh.setAttribute('visibility', 'hidden'); hideTip(); });
  });

  document.querySelectorAll('.seg[data-tip], .bub[data-tip]').forEach(el => {
    el.addEventListener('pointermove', ev => showTip(ev.clientX, ev.clientY, esc(el.dataset.tip)));
    el.addEventListener('pointerleave', hideTip);
    el.addEventListener('focus', () => { const r = el.getBoundingClientRect();
      showTip(r.left + r.width / 2, r.top, esc(el.dataset.tip)); });
    el.addEventListener('blur', hideTip);
  });
})();
"""


def _page(title, subtitle, body):
    return (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_esc(title)}</title><style>{_CSS}</style></head>'
            f'<body><div class="viz-root"><h1>{_esc(title)}</h1>'
            f'<p class="sub">{_esc(subtitle)}</p>{body}</div>'
            f'<script>{_JS}</script></body></html>')


def render_player(series, meta=""):
    t, M = series["t"], series["metrics"]
    body = [kpi_row(series), '<div class="cols">']
    body.append(line_chart("mi", "Metal income", t,
                           [{"name": "metal income", "values": M["m_inc"], "cls": "s1", "area": True}],
                           "m/s"))
    body.append(line_chart("ei", "Energy income", t,
                           [{"name": "energy income", "values": M["e_inc"], "cls": "s3", "area": True}],
                           "E/s"))
    if M.get("m_cap") and any(M["m_cap"]):
        body.append(line_chart("mb", "Metal bank", t,
                               [{"name": "bank", "values": M["metal"], "cls": "s1", "area": True},
                                {"name": "storage cap", "values": M["m_cap"], "cls": "ctx", "context": True}],
                               "metal", "vs storage cap"))
        body.append(line_chart("eb", "Energy bank", t,
                               [{"name": "bank", "values": M["energy"], "cls": "s3", "area": True},
                                {"name": "storage cap", "values": M["e_cap"], "cls": "ctx", "context": True}],
                               "energy", "vs storage cap"))
    else:
        body.append(line_chart("mb", "Metal bank", t,
                               [{"name": "bank", "values": M["metal"], "cls": "s1", "area": True}], "metal"))
    if M.get("value") and any(v for v in M.get("value", [])):
        body.append(line_chart("tv", "Total unit value", t,
                               [{"name": "completed", "values": M["value"], "cls": "s1"},
                                {"name": "under construction", "values": M["construction"], "cls": "s2"}],
                               "metal value"))
    if M.get("bp_util") and any(v is not None for v in M.get("bp_util", [])):
        body.append(line_chart("bp", "Build power utilization", t,
                               [{"name": "utilization", "values": M["bp_util"], "cls": "s2", "area": True}],
                               "%"))
    body.append(line_chart("mex", "Extractors", t,
                           [{"name": "mex", "values": M["n_mex"], "cls": "s1"}], "count"))
    if M.get("eco_added") and any(v is not None for v in M["eco_added"]):
        body.append(line_chart("ea", "Eco added per minute", t,
                               [{"name": "eco value added", "values": M["eco_added"],
                                 "cls": "s1", "area": True}], "metal value/min"))
    if series.get("buckets"):
        body.append(stacked_chart("comp", "Value composition", t, series["buckets"]))
    body.append("</div>")
    body.append(data_table([series]))
    return _page(f"Economy — {series['label']}", meta, "".join(body))


def render_h2h(a, b, meta=""):
    """Two series (game or theory) side by side. A = slot 1 (blue), B = slot 2 (orange)."""
    def pair(cid, title, key, unit="", area=False):
        sa, sb = a["metrics"].get(key), b["metrics"].get(key)
        if not (sa and any(v is not None for v in sa)) or \
           not (sb and any(v is not None for v in sb)):
            return ""
        # merge onto a shared t axis by sampling each side at its own points
        ts = sorted(set(a["t"]) | set(b["t"]))
        va = _resample(a["t"], sa, ts)
        vb = _resample(b["t"], sb, ts)
        return line_chart(cid, title, ts,
                          [{"name": a["label"], "values": va, "cls": "s1", "area": area},
                           {"name": b["label"], "values": vb, "cls": "s2", "area": area}], unit)

    tiles = []
    for label, key, unit in (("Metal income", "m_inc", "m/s"), ("Energy income", "e_inc", "E/s"),
                             ("Metal bank", "metal", "m"), ("Total value", "value", "m"),
                             ("Mex", "n_mex", "")):
        va = a["metrics"].get(key), b["metrics"].get(key)
        if all(col and any(v is not None for v in col) for col in va):
            fa, fb = va[0][-1], va[1][-1]
            tiles.append(_tile(f"{label} — {a['label'][:14]}", fa, None, unit) +
                         _tile(f"{label} — {b['label'][:14]}", fb, None, unit))
    body = ['<div class="tiles">' + "".join(tiles) + "</div>", '<div class="cols">']
    body.append(pair("mi", "Metal income", "m_inc", "m/s"))
    body.append(pair("ei", "Energy income", "e_inc", "E/s"))
    body.append(pair("mb", "Metal bank", "metal", "metal"))
    body.append(pair("tv", "Total unit value", "value", "metal value"))
    body.append(pair("bp", "Build power utilization", "bp_util", "%"))
    body.append(pair("mex", "Extractors", "n_mex", "count"))

    lead_key = "value" if (a["metrics"].get("value") and b["metrics"].get("value")
                           and any(a["metrics"]["value"]) and any(b["metrics"]["value"])) else "m_inc"
    ts = sorted(set(a["t"]) | set(b["t"]))
    va = _resample(a["t"], a["metrics"][lead_key], ts)
    vb = _resample(b["t"], b["metrics"][lead_key], ts)
    diff = [round((x or 0) - (y or 0), 2) for x, y in zip(va, vb)]
    title = "Value lead" if lead_key == "value" else "Metal-income lead"
    body.append(diverging_chart("lead", title, ts, diff, a["label"], b["label"],
                                "metal value" if lead_key == "value" else "m/s"))
    body.append("</div>")
    body.append(data_table([a, b]))
    return _page(f"Head-to-head — {a['label']} vs {b['label']}", meta, "".join(body))


def _resample(t_src, v_src, t_out):
    """Step-hold resample onto a merged time axis (None before the first sample)."""
    out, j = [], -1
    for tv in t_out:
        while j + 1 < len(t_src) and t_src[j + 1] <= tv:
            j += 1
        out.append(v_src[j] if j >= 0 else None)
    return out


# ── composite "player size" bubble ─────────────────────────────────────────
# Layer composition is data, adjust in one place. A player's total size =
# infrastructure + army + resource bank; each layer expands the bubble and
# the AREA of each band is proportional to its value (radius = sqrt).
INFRA_BUCKETS = ("economy", "defense", "build_power", "infrastructure")
ARMY_BUCKETS = ("military", "commander", "support", "other")
E_TO_M = 70.0            # energy→metal-equivalent, same rate the widget uses

# layer id → (label, css slot, icon path in a 12x12 viewbox)
_ICON_HOUSE = "M1.5 11V5.5L6 2l4.5 3.5V11H7.5V7.5h-3V11z"
_ICON_SHIELD = "M6 1l4.5 1.8v3.4c0 2.6-1.9 4.1-4.5 5-2.6-.9-4.5-2.4-4.5-5V2.8z"
_ICON_COINS = ("M2 3.2c0-.9 1.8-1.6 4-1.6s4 .7 4 1.6-1.8 1.6-4 1.6-4-.7-4-1.6zm0 2.6c0 .9 "
               "1.8 1.6 4 1.6s4-.7 4-1.6M2 3.2v5.6c0 .9 1.8 1.6 4 1.6s4-.7 4-1.6V3.2")
_ICON_CROSS = "M2.5 2.5l7 7M9.5 2.5l-7 7"

LAYERS = {
    "infra": ("Infrastructure", "s1", _ICON_HOUSE),
    "army": ("Army", "s2", _ICON_SHIELD),
    "bank": ("Banks", "s3", _ICON_COINS),
}
LAYER_ORDER = ("infra", "army", "bank")

# activity (flow) bubble: gross churn over a window. Identity colors keep the
# validated slot order; the made/lost meaning rides the icon + label + tooltip.
ACT_LAYERS = {
    "infra_built": ("Eco built", "s1", _ICON_HOUSE),
    "army_built": ("Army built", "s2", _ICON_SHIELD),
    "bank_swing": ("Bank swing", "s3", _ICON_COINS),
    "eco_lost": ("Eco destroyed", "s4", _ICON_CROSS),
    "army_lost": ("Army lost", "s5", _ICON_CROSS),
}
ACT_ORDER = ("infra_built", "army_built", "bank_swing", "eco_lost", "army_lost")


def player_layers(team):
    """One team dict (from a snapshot) → the three size layers, metal-equivalent."""
    b = team.get("buckets", {}) or {}
    infra = sum(b.get(k, 0) or 0 for k in INFRA_BUCKETS)
    army = sum(b.get(k, 0) or 0 for k in ARMY_BUCKETS)
    bank = team.get("storageValue")
    if bank is None:
        bank = (team.get("metalCurrent", 0) or 0) + (team.get("energyCurrent", 0) or 0) / E_TO_M
    layers = {"infra": round(infra, 1), "army": round(army, 1), "bank": round(bank, 1)}
    layers["total"] = round(sum(layers[k] for k in LAYER_ORDER), 1)
    return layers


def bubble_svg(layers, global_max, size=230, defs=LAYERS, order=LAYER_ORDER,
               tips=None, aria="player size bubble"):
    """Concentric area-true bubble. global_max sets the shared scale: the largest
    bubble on the page fills the canvas, everyone else is proportionally smaller.
    `tips` overrides the default per-layer tooltip text (e.g. signed bank swing)."""
    import math
    cx = cy = size / 2
    rmax = size / 2 - 6
    gm = max(global_max, 1e-9)
    total = max(sum(abs(layers.get(k, 0) or 0) for k in order), 1e-9)
    cum, parts, badges = 0.0, [], []
    radii = {}
    for key in order:
        cum += abs(layers.get(key, 0) or 0)
        radii[key] = rmax * math.sqrt(cum / gm)
    for key in reversed(order):              # outer first, inner circles cover
        label, cls, _icon = defs[key]
        v = layers.get(key, 0) or 0
        tip = (tips or {}).get(key) or \
            f"{label}: {_fmt_v(v)} ({round(100 * abs(v) / total)}% of size)"
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{radii[key]:.1f}" '
                     f'class="bub {cls}" tabindex="0" data-tip="{_esc(tip)}"/>')
    prev = 0.0
    for key in order:                        # icon badge centered in its band, 12 o'clock
        label, cls, icon = defs[key]
        band = radii[key] - prev
        if band >= 15:
            by = cy - (prev + band / 2)
            badges.append(
                f'<g class="badge" transform="translate({cx - 8:.1f},{by - 8:.1f})">'
                f'<circle cx="8" cy="8" r="8" class="bbg"/>'
                f'<path d="{icon}" transform="translate(2,2)" class="bic {cls}"/>'
                f'<title>{_esc(label)}</title></g>')
        prev = radii[key]
    return (f'<svg viewBox="0 0 {size} {size}" role="img" '
            f'aria-label="{_esc(aria)}">' + "".join(parts + badges) + "</svg>")


_FLOW_KEYS = ("eco_made", "army_made", "eco_lost", "army_lost",
              "eco_self_removed", "enemy_killed", "units_made", "units_lost")


def flow_delta(cur_team, prev_team=None):
    """Windowed flow: cumulative counters at now minus at the window start,
    plus the signed bank swing. prev_team=None → whole game so far."""
    fc = cur_team.get("flow", {}) or {}
    fp = (prev_team.get("flow", {}) or {}) if prev_team else {}
    d = {k: round((fc.get(k, 0) or 0) - (fp.get(k, 0) or 0), 1) for k in _FLOW_KEYS}
    bank_now = player_layers(cur_team)["bank"]
    bank_then = player_layers(prev_team)["bank"] if prev_team else bank_now
    d["bank_delta"] = round(bank_now - bank_then, 1)
    d["net_army"] = round(d["army_made"] - d["army_lost"], 1)
    return d


def activity_layers(delta):
    """Flow delta → the activity-bubble layers (gross churn; area = |value moved|)."""
    L = {"infra_built": delta["eco_made"], "army_built": delta["army_made"],
         "bank_swing": abs(delta["bank_delta"]), "eco_lost": delta["eco_lost"],
         "army_lost": delta["army_lost"]}
    L["total"] = round(sum(L[k] for k in ACT_ORDER), 1)
    return L


def compute_insights(snap, prev_snap=None):
    """State-conditional judgments from metric combinations, per team.

    Direction matters: spending the bank down is good; idle build power is bad
    ONLY when resources are banked (with an empty bank it is the optimal
    waiting state); army losses are judged against enemy value killed; net
    army growth is compared across players so a smaller economy that
    out-grows bigger ones gets credit.
    Returns {teamID: {"delta": flow_delta, "chips": [{level, kind, text}]}}.
    """
    prev_by_id = {t["teamID"]: t for t in (prev_snap or {}).get("teams", [])}
    teams = [t for t in snap.get("teams", []) if not t.get("dead")]
    out = {}
    net_army, totals = {}, {}
    for t in teams:
        d = flow_delta(t, prev_by_id.get(t["teamID"]))
        out[t["teamID"]] = {"delta": d, "chips": []}
        net_army[t["teamID"]] = d["net_army"]
        totals[t["teamID"]] = player_layers(t)["total"]

    for t in teams:
        tid = t["teamID"]
        d, chips = out[tid]["delta"], out[tid]["chips"]
        bank = player_layers(t)["bank"]
        cap = (t.get("metalStorage", 0) or 0) + (t.get("energyStorage", 0) or 0) / E_TO_M
        bank_low = bank < max(150, 0.15 * cap)
        ba, bu = t.get("bpAvail", 0) or 0, t.get("bpUsed", 0) or 0
        bp_util = 100.0 * bu / ba if ba else 0

        # 1. trade efficiency — the tick-spam / metal-sink detector
        if d["army_lost"] >= 250:
            ratio = d["enemy_killed"] / d["army_lost"]
            if ratio < 0.6:
                chips.append({"level": "serious", "kind": "metal_sink",
                              "text": f"metal sink: lost {_fmt_v(d['army_lost'])} army, "
                                      f"killed only {_fmt_v(d['enemy_killed'])} ({ratio:.1f}x)"})
            elif ratio >= 1.3:
                chips.append({"level": "good", "kind": "winning_trades",
                              "text": f"winning trades: {ratio:.1f}x "
                                      f"({_fmt_v(d['enemy_killed'])} killed vs "
                                      f"{_fmt_v(d['army_lost'])} lost)"})

        # 2. bank direction, judged by its cause
        if d["bank_delta"] <= -200:
            chips.append({"level": "good", "kind": "deploying",
                          "text": f"spending down: bank {_fmt_v(d['bank_delta'])} into the game"})
        elif d["bank_delta"] >= 200:
            if d["eco_self_removed"] >= 100:
                chips.append({"level": "good", "kind": "reclaim_bank",
                              "text": f"bank +{_fmt_v(d['bank_delta'])} fed by reclaim "
                                      f"(recycled {_fmt_v(d['eco_self_removed'])} own eco)"})
            elif bp_util >= 85:
                chips.append({"level": "warning", "kind": "bp_capped",
                              "text": f"banking +{_fmt_v(d['bank_delta'])} with BP saturated "
                                      f"({bp_util:.0f}%) — add build power"})
            else:
                chips.append({"level": "serious", "kind": "unqueued",
                              "text": f"banking +{_fmt_v(d['bank_delta'])} with idle BP "
                                      f"({bp_util:.0f}% used) — not queued"})
        # 3. build-power state (only when the bank didn't already tell the story)
        elif bp_util < 70:
            if bank_low:
                chips.append({"level": "good", "kind": "optimal_wait",
                              "text": f"fully invested: BP at {bp_util:.0f}% only because "
                                      "resources are drained — optimal waiting state"})
            else:
                chips.append({"level": "serious", "kind": "idle_bp",
                              "text": f"idle BP ({bp_util:.0f}% used) with "
                                      f"{_fmt_v(bank)} banked"})

        # 4. army growth vs economy size, cross-player
        if len(teams) >= 2 and d["net_army"] > 0:
            growth_rank = sorted(net_army, key=lambda k: -net_army[k]).index(tid)
            size_rank = sorted(totals, key=lambda k: -totals[k]).index(tid)
            if growth_rank == 0 and size_rank >= len(teams) // 2:
                chips.append({"level": "good", "kind": "outgrowing",
                              "text": f"fastest army growth (+{_fmt_v(d['net_army'])}) "
                                      f"from a bottom-half economy — losing less than the big ecos"})
    return out


_CHIP_GLYPH = {"good": "✓", "warning": "!", "serious": "✕"}


def _mirror_matchup(rows):
    """Two-team lane alignment: order each ally team along the lane axis (the
    start-position axis with the smaller team separation), then pair players in
    the double xy-mirror matchup — middle position i faces enemy position
    N+1-i (opposite tech vs tech, air vs air), while the two corner positions
    face their single-mirror opposite across the front line, whom they fight
    directly. Returns [(allyID, ordered_rows), ...] with the second team's
    order rearranged so the SAME grid cell in both panels is a head-to-head
    pair — or None when the layout doesn't apply (not 2 teams, uneven counts,
    or missing spawn positions)."""
    by_ally = {}
    for r in rows:
        by_ally.setdefault(r[0].get("allyTeamID", 0), []).append(r)
    if len(by_ally) != 2:
        return None
    a_id, b_id = sorted(by_ally)
    A, B = by_ally[a_id], by_ally[b_id]
    if len(A) != len(B):
        return None
    if any(r[0].get("startX", -1) < 0 or r[0].get("startZ", -1) < 0 for r in A + B):
        return None

    def cen(rs, k):
        return sum(r[0][k] for r in rs) / len(rs)
    sep_x = abs(cen(A, "startX") - cen(B, "startX"))
    sep_z = abs(cen(A, "startZ") - cen(B, "startZ"))
    lane_key = "startZ" if sep_x >= sep_z else "startX"   # spread axis ⊥ front line
    A = sorted(A, key=lambda r: (r[0][lane_key], r[0]["teamID"]))
    B = sorted(B, key=lambda r: (r[0][lane_key], r[0]["teamID"]))
    n = len(A)

    def opp(i):
        return i if n == 1 or i in (0, n - 1) else n - 1 - i
    return [(a_id, A), (b_id, [B[opp(i)] for i in range(n)])]


def eco_added_last_minute(snap, prev1_snap):
    """Per-team eco value added in the last game-minute (None without a prior minute)."""
    prev = {t["teamID"]: t for t in (prev1_snap or {}).get("teams", [])}
    out = {}
    for t in snap.get("teams", []):
        cur = (t.get("flow") or {}).get("eco_made")
        was = (prev.get(t["teamID"], {}).get("flow") or {}).get("eco_made")
        out[t["teamID"]] = None if cur is None or was is None else round(cur - was, 1)
    return out


def render_bubbles(snap, meta="", refresh=None, minute_links=None, current=None,
                   prev_snap=None, window_label="", prev1_snap=None):
    """The composite view: each living player is a PAIR of circles — left = size
    (stock: infra+army+bank, scale = biggest player), right = activity over the
    window (gross value moved: built / lost / bank swing, its own shared scale).
    Insight chips judge the direction of the flows. `current` = recalled minute
    or None (live)."""
    teams = [t for t in snap.get("teams", []) if not t.get("dead")]
    prev_by_id = {t["teamID"]: t for t in (prev_snap or {}).get("teams", [])}
    insights = compute_insights(snap, prev_snap)
    eco1 = eco_added_last_minute(snap, prev1_snap)

    rows = []
    for t in teams:
        L = player_layers(t)
        d = insights[t["teamID"]]["delta"]
        d["eco_added_1min"] = eco1.get(t["teamID"])
        A = activity_layers(d)
        rows.append((t, L, A, d, insights[t["teamID"]]["chips"]))
    rows.sort(key=lambda r: -r[1]["total"])
    gm = max((L["total"] for _, L, _, _, _ in rows), default=1)
    ga = max((A["total"] for _, _, A, _, _ in rows), default=1) or 1

    gs = snap.get("gameSeconds", 0)
    when = f"minute {current}" if current is not None else f"live · {_fmt_t(gs)}"
    wlabel = window_label or "whole game"
    legend = '<div class="legend big">' + "".join(
        f'<span><svg viewBox="0 0 12 12" class="lic"><path d="{icon}" class="bic {cls}"/></svg>'
        f'{label}</span>'
        for label, cls, icon in
        ([LAYERS[k] for k in LAYER_ORDER] +
         [ACT_LAYERS[k] for k in ("bank_swing", "eco_lost", "army_lost")])) + \
        '<span class="hint">area = metal-equivalent value · left: size (scale = leader) · ' \
        f'right: activity, {_esc(wlabel)}</span></div>'

    strip = ""
    if minute_links is not None:
        links = ['<a href="/viz" class="{}">live</a>'.format("cur" if current is None else "")]
        links += [f'<a href="/viz?minute={m}" class="{"cur" if current == m else ""}">{m}</a>'
                  for m in minute_links]
        strip = '<div class="tstrip">Point in time: ' + " ".join(links) + "</div>"

    def card(t, L, A, d, chips, vs=None):
        pct = round(100 * L["total"] / gm)
        sub = f"vs {vs}" if vs else f"{pct}% of leader"
        swing = d["bank_delta"]
        act_tips = {"bank_swing": f"Bank swing: {'+' if swing >= 0 else ''}{_fmt_v(swing)} "
                                  f"({'banking up' if swing >= 0 else 'spending down'})"}
        chip_html = "".join(
            f'<span class="chip {c["level"]}"><b>{_CHIP_GLYPH[c["level"]]}</b>{_esc(c["text"])}</span>'
            for c in chips)
        vals = (f"built {_fmt_v(d['eco_made'] + d['army_made'])} · "
                f"lost {_fmt_v(d['eco_lost'] + d['army_lost'])} · "
                f"killed {_fmt_v(d['enemy_killed'])} · "
                f"bank {'+' if swing >= 0 else ''}{_fmt_v(swing)}")
        if d.get("eco_added_1min") is not None:
            vals += f" · eco +{_fmt_v(d['eco_added_1min'])}/min"
        return (
            f'<div class="bcard"><div class="bname">{_esc(t.get("name", t["teamID"]))} '
            f'<span class="bsub">{_esc(sub)}</span></div>'
            f'<div class="pair">'
            f'<div class="half">{bubble_svg(L, gm, size=170)}'
            f'<div class="bcap">size · {_fmt_v(L["total"])}</div></div>'
            f'<div class="half">{bubble_svg(A, ga, size=170, defs=ACT_LAYERS, order=ACT_ORDER, tips=act_tips, aria="activity bubble")}'
            f'<div class="bcap">activity · {_fmt_v(A["total"])}</div></div>'
            f'</div>'
            f'<div class="bvals">{_esc(vals)}</div>'
            f'<div class="chips">{chip_html}</div></div>')

    # one panel per ally team, 4 fixed columns → 8 players = 2×4, scaling down
    # fluidly. With exactly two even teams and known spawns, panels align in the
    # double xy-mirror matchup: the same grid cell in both panels is a
    # head-to-head pair (middles cross-mirrored, corners face directly).
    matchup = _mirror_matchup(rows)
    if matchup:
        vs_names = {}
        (a_id, A_rows), (b_id, B_rows) = matchup
        for ra, rb in zip(A_rows, B_rows):
            vs_names[ra[0]["teamID"]] = rb[0].get("name", "")
            vs_names[rb[0]["teamID"]] = ra[0].get("name", "")
        panel_src = matchup
    else:
        by_ally = {}
        for r in rows:
            by_ally.setdefault(r[0].get("allyTeamID", 0), []).append(r)
        vs_names = {}
        panel_src = [(ally, by_ally[ally]) for ally in sorted(by_ally)]

    panels = []
    for ally, members in panel_src:
        team_total = sum(L["total"] for _, L, _, _, _ in members)
        team_kill = sum(d["enemy_killed"] for _, _, _, d, _ in members)
        team_lost = sum(d["eco_lost"] + d["army_lost"] for _, _, _, d, _ in members)
        cols = len(members) if len(members) <= 4 else 4
        note = " · cells align head-to-head" if matchup else ""
        panels.append(
            f'<section class="panel"><div class="phead"><b>Team {ally}</b>'
            f'<span>{len(members)} players · total {_fmt_v(team_total)} · '
            f'killed {_fmt_v(team_kill)} · lost {_fmt_v(team_lost)}{note}</span></div>'
            f'<div class="pgrid" style="grid-template-columns:repeat({cols},minmax(0,1fr))">'
            + "".join(card(*r, vs=vs_names.get(r[0]["teamID"])) for r in members)
            + "</div></section>")

    body = strip + legend + "".join(panels)
    body += _bubble_table(rows)
    auto = f'<script>setTimeout(()=>location.reload(),{int(refresh) * 1000})</script>' if refresh else ""
    return _page(f"Player size — {when}", meta, body).replace("</body>", auto + "</body>")


def _bubble_table(rows):
    heads = "".join(f"<th>{LAYERS[k][0]}</th>" for k in LAYER_ORDER) + "<th>total</th>" + \
        "".join(f"<th>{h}</th>" for h in
                ("eco built", "army built", "eco destroyed", "army lost",
                 "enemy killed", "self-reclaimed", "bank Δ", "net army", "eco +/min"))
    tr = "".join(
        f'<tr><td style="text-align:left">{_esc(t.get("name", t["teamID"]))}</td>'
        + "".join(f"<td>{_fmt_v(L[k])}</td>" for k in LAYER_ORDER)
        + f"<td>{_fmt_v(L['total'])}</td>"
        + "".join(f"<td>{_fmt_v(d.get(k))}</td>" for k in
                  ("eco_made", "army_made", "eco_lost", "army_lost",
                   "enemy_killed", "eco_self_removed", "bank_delta", "net_army",
                   "eco_added_1min"))
        + "</tr>"
        for t, L, A, d, chips in rows)
    return (f'<details class="tbl"><summary>Data table — size layers + window flows</summary>'
            f'<div class="scroll"><table><thead><tr><th>player</th>{heads}</tr>'
            f'</thead><tbody>{tr}</tbody></table></div></details>')


def write_report(html_text, name):
    os.makedirs(VIZ_DIR, exist_ok=True)
    path = os.path.join(VIZ_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_text)
    return path

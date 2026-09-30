#!/usr/bin/env python3
"""display_hex.py — hex/triangle infographic for the realtime dashboard.

DisplayHex: a hex grid-point system. Clickable points = center (0) + six
vertex directions (1-6, clockwise from top). Expanding rings of faint hex
outlines are the magnitude tiers (linear for now; ring scaling is pluggable
per attribute: linear | log | custom callable).

Each ATTRIBUTE renders at its directional vertex (center=0 reserved/special),
at a radius proportional to its magnitude. Three attributes on alternating
vertices — metal (5, bottom-left), bp (1, top), energy (3, bottom-right) —
form the weighted triangle: a perfect economy is equilateral at the mid ring;
an overweighted side sags the triangle toward its vertex (distress), and the
RESPONSE FLAG on the 180-degree opposing vertex lights up.

Orientation is a view concern, not data: to_svg(rot=positions) re-renders
with a directionalOffset; the page's ⟲/⟳ controls animate the rotation
client-side while every label counter-rotates to stay upright.

First imbalance rule (the reclaim test): if (metal bank + metal income)
exceeds (current spending + capacity to grow spending) because energy can't
power more BP, light the flag opposite metal: solar/con-turret scaling,
"infinite until solved" — con turret while there is energy, solar when not.

CLI:
    python display_hex.py --demo                 # synthetic states incl. the reclaim case
    python display_hex.py --game <ref> [--team N] [--minute M] [--rot P]
"""
from __future__ import annotations
import argparse, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import eco_viz  # noqa: E402  (page chrome, palette, formatters)

E_TO_M = eco_viz.E_TO_M          # 70 energy ≈ 1 metal
BP_TO_MPS = 0.03                 # rough m/s a structure-building BP point can spend


def opposite(d):
    """The 180-degree opposing vertex: 5↔2, 1↔4, 3↔6."""
    return (d + 2) % 6 + 1


def _angle(d, offset=0.0):
    """Direction 1 = top, clockwise. offset in positions (60° each)."""
    return math.radians(-90 + (d - 1 + offset) * 60)


# ── magnitude scales (ring mapping) — pluggable ────────────────────────────
SCALES = {
    "linear": lambda v, full: v / full,
    "log": lambda v, full: math.log1p(max(v, 0)) / math.log1p(full),
}


def resolve_scale(scale):
    if callable(scale):
        return scale
    return SCALES[scale]


class DisplayHex:
    """Data + geometry for one hex. Attributes/flags are data; orientation is
    passed at render time. Extend by adding attrs, flags, or custom scales."""

    def __init__(self, rings=4, size=520, full_scale=2.0, title=""):
        self.rings = rings          # faint outline tiers
        self.size = size
        self.full_scale = full_scale  # magnitude that reaches the outer ring
        self.title = title
        self.attrs = {}             # id -> dict
        self.flags = []             # [{direction, label, lit, reason, slot}]
        self.center = None          # optional special center rendering {label, value}
        self.note = ""

    def set_attr(self, aid, label, direction, value, magnitude,
                 scale="linear", slot="s1", detail=""):
        """direction 1-6 (0=center is reserved). magnitude is the relative
        strength (1.0 = balanced = mid ring); scale maps it onto the rings."""
        self.attrs[aid] = {"id": aid, "label": label, "direction": direction,
                           "value": value, "magnitude": magnitude,
                           "scale": scale, "slot": slot, "detail": detail}

    def add_flag(self, direction, label, lit, reason="", slot="s2"):
        self.flags.append({"direction": direction, "label": label,
                           "lit": bool(lit), "reason": reason, "slot": slot})

    # ── geometry ───────────────────────────────────────────────────────────
    def _xy(self, direction, frac, offset=0.0):
        c = self.size / 2
        R = self.size / 2 - 70
        a = _angle(direction, offset)
        return (c + R * frac * math.cos(a), c + R * frac * math.sin(a))

    def _mag_frac(self, att):
        f = resolve_scale(att["scale"])(att["magnitude"], self.full_scale)
        return max(0.04, min(f, 1.0))

    def to_svg(self, rot=0):
        """rot = directionalOffset in positions (60° steps). Server-side
        orientation; the page JS animates further offsets client-side."""
        c = self.size / 2
        deg = rot * 60
        parts = []

        # rotating geometry group (labels inside counter-rotate via CSS class)
        parts.append(f'<g class="hexrot" style="transform: rotate({deg}deg)">')
        for k in range(1, self.rings + 1):
            pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in
                           (self._xy(d, k / self.rings) for d in range(1, 7)))
            parts.append(f'<polygon points="{pts}" class="hexring"/>')
        for d in range(1, 7):
            x, y = self._xy(d, 1.0)
            parts.append(f'<line x1="{c}" y1="{c}" x2="{x:.1f}" y2="{y:.1f}" class="hexspoke"/>')

        # the weighted triangle (attribute polygon), sagging toward excess
        pts = [(a, self._xy(a["direction"], self._mag_frac(a)))
               for a in sorted(self.attrs.values(), key=lambda a: a["direction"])]
        if len(pts) >= 3:
            mags = [a["magnitude"] for a, _ in pts]
            distress = max(mags) / max(min(mags), 1e-9) > 1.3
            poly = " ".join(f"{x:.1f},{y:.1f}" for _, (x, y) in pts)
            parts.append(f'<polygon points="{poly}" class="wtri {"distress" if distress else ""}"/>')

        # attribute spikes + markers + upright labels
        for a in self.attrs.values():
            f = self._mag_frac(a)
            x, y = self._xy(a["direction"], f)
            vx, vy = self._xy(a["direction"], 1.0)
            tip = f'{a["label"]}: {a["value"]} (x{a["magnitude"]:.2f} of balance, {a["scale"]})'
            parts.append(f'<line x1="{c}" y1="{c}" x2="{x:.1f}" y2="{y:.1f}" '
                         f'class="aspike {a["slot"]}"/>')
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" '
                         f'class="apt {a["slot"]} seg" tabindex="0" data-tip="{eco_viz._esc(tip)}"/>')
            lx, ly = self._xy(a["direction"], min(f + 0.16, 1.14))
            parts.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" class="alabel upright" text-anchor="middle" '
                f'style="transform-origin:{lx:.1f}px {ly:.1f}px">'
                f'<tspan x="{lx:.1f}" dy="-2">{eco_viz._esc(a["label"])}</tspan>'
                f'<tspan x="{lx:.1f}" dy="13" class="aval">{eco_viz._esc(str(a["value"]))}</tspan></text>')

        # response flags at their (opposing) vertices
        for fl in self.flags:
            x, y = self._xy(fl["direction"], 1.22)
            lit = "lit" if fl["lit"] else ""
            tip = fl["reason"] or fl["label"]
            parts.append(
                f'<g class="hexflag {lit}" tabindex="0" data-tip="{eco_viz._esc(tip)}" '
                f'style="transform-origin:{x:.1f}px {y:.1f}px">'
                f'<rect x="{x - 56:.1f}" y="{y - 12:.1f}" width="112" height="24" rx="12" class="fbg"/>'
                f'<text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="middle" class="ftxt upright" '
                f'style="transform-origin:{x:.1f}px {y:.1f}px">{eco_viz._esc(fl["label"])}</text></g>')

        # grid points: center + six vertices (clickable)
        parts.append(f'<circle cx="{c}" cy="{c}" r="11" class="hexpt" data-dir="0" tabindex="0"/>')
        if self.center:
            parts.append(f'<text x="{c}" y="{c - 16:.1f}" class="alabel upright" text-anchor="middle" '
                         f'style="transform-origin:{c}px {c - 16:.1f}px">'
                         f'{eco_viz._esc(self.center.get("label", ""))}</text>')
        for d in range(1, 7):
            x, y = self._xy(d, 1.0)
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="10" class="hexpt" '
                         f'data-dir="{d}" tabindex="0"/>')
        parts.append("</g>")
        return (f'<svg viewBox="0 0 {self.size} {self.size}" class="hexsvg" role="img" '
                f'aria-label="{eco_viz._esc(self.title or "display hex")}">' + "".join(parts) + "</svg>")


# ── economy adapter: the imbalance-from-perfect-economy view ───────────────
# Response catalog: what lights up opposite an overweighted attribute.
RESPONSES = {
    "metal": {"label": "solar / con turret", "slot": "s3",
              "reason": "metal overweight: bank+income exceed spending and the "
                        "capacity to grow spending — scale BP with its energy: "
                        "con turret while energy holds, solar when it doesn't "
                        "(repeat until solved)"},
    "energy": {"label": "wind / stall guard", "slot": "s2",
               "reason": "energy overweight-inverse or starved: add generation "
                         "before anything else"},
    "bp": {"label": "queue eco / expand", "slot": "s1",
           "reason": "build power overweight: BP idle relative to resources — "
                     "give it targets (eco, expansion)"},
}
ATTR_DIRS = {"bp": 1, "energy": 3, "metal": 5}
ATTR_SLOTS = {"metal": "s1", "bp": "s4", "energy": "s3"}


def team_scores(team):
    """Comparable per-second 'weight' of each side of the triangle."""
    metal = (team.get("metalIncome", 0) or 0) + (team.get("metalCurrent", 0) or 0) / 60.0
    energy = ((team.get("energyIncome", 0) or 0) +
              (team.get("energyCurrent", 0) or 0) / 60.0) / E_TO_M
    bp = (team.get("bpAvail", 0) or 0) * BP_TO_MPS
    return {"metal": metal, "energy": energy, "bp": bp}


def check_reclaim_overload(team):
    """The first test rule: (current metal + metal income) exceeding
    (spending + capacity to increase spending), with energy the limiter on
    growing BP. Returns (triggered, reason)."""
    m_supply = (team.get("metalIncome", 0) or 0) + (team.get("metalCurrent", 0) or 0) / 60.0
    spending = (team.get("bpUsed", 0) or 0) * BP_TO_MPS
    bp_headroom = max((team.get("bpAvail", 0) or 0) - (team.get("bpUsed", 0) or 0), 0) * BP_TO_MPS
    e_net = team.get("energyIncome", 0) or 0
    e_bank = team.get("energyCurrent", 0) or 0
    energy_limited = e_net < 1.2 * (team.get("bpUsed", 0) or 0) * 0.5 and e_bank < 0.5 * (
        team.get("energyStorage", 0) or 1)
    # floor: the opening bank (1000 start metal vs tiny early spend) is not a flood
    over = m_supply > 20 and m_supply > (spending + bp_headroom) * 1.15
    if over and energy_limited:
        return True, (f"metal supply {m_supply:.0f}/s > spend {spending:.0f}/s "
                      f"+ headroom {bp_headroom:.0f}/s, and energy can't power more BP")
    return over, (f"metal supply {m_supply:.0f}/s > spend+headroom "
                  f"{spending + bp_headroom:.0f}/s" if over else "")


def solar_conturret_step(team, e_per_bp=0.6):
    """The response's simple logic: con turret while I have energy, solar when
    I don't. (The 'infinite until we solve the problem' loop body.)
    'Have energy' = bank healthy OR income comfortably above what the working
    BP already burns (~e_per_bp energy per used BP point)."""
    e_inc = team.get("energyIncome", 0) or 0
    e_bank = team.get("energyCurrent", 0) or 0
    burn = (team.get("bpUsed", 0) or 0) * e_per_bp
    have_energy = e_bank > 0.25 * (team.get("energyStorage", 0) or 1) or e_inc > burn
    return "con_turret" if have_energy else "solar"


def eco_hex(team, title=None):
    """Team snapshot dict -> DisplayHex of the metal/bp/energy triangle with
    imbalance flags on opposing vertices."""
    scores = team_scores(team)
    mean = sum(scores.values()) / 3 or 1.0
    hx = DisplayHex(rings=4, full_scale=2.0,
                    title=title or f'{team.get("name", "?")} — economy balance')
    fmt = {"metal": f'{scores["metal"]:.0f} m/s', "bp": f'{team.get("bpAvail", 0):.0f} BP',
           "energy": f'{team.get("energyIncome", 0):.0f} E/s'}
    for aid, d in ATTR_DIRS.items():
        hx.set_attr(aid, aid, d, fmt[aid], scores[aid] / mean,
                    scale="linear", slot=ATTR_SLOTS[aid])
    hx.center = {"label": ""}

    mags = {k: v / mean for k, v in scores.items()}
    heavy = max(mags, key=mags.get)
    imbalance = mags[heavy] / max(min(mags.values()), 1e-9)
    reclaim, why = check_reclaim_overload(team)
    for aid, d in ATTR_DIRS.items():
        r = RESPONSES[aid]
        lit = (aid == heavy and imbalance > 1.3)
        reason = r["reason"]
        if aid == "metal" and reclaim:
            lit = True
            step = solar_conturret_step(team)
            reason = f'{why} → next: {step.replace("_", " ")}. ' + r["reason"]
        hx.add_flag(opposite(d), r["label"], lit, reason, r["slot"])
    hx.note = (f"imbalance x{imbalance:.2f} (heavy: {heavy})"
               + (" · reclaim-overload rule TRIGGERED" if reclaim else ""))
    return hx


# ── page assembly ──────────────────────────────────────────────────────────
_HEX_CSS = """
<style>
.hexsvg { max-width: 560px; margin: 0 auto; display: block; }
.hexrot { transition: transform .55s ease; transform-origin: 50% 50%; transform-box: view-box; }
.upright { transition: transform .55s ease; transform-box: fill-box; }
.hexring { fill: none; stroke: var(--grid); stroke-width: 1; }
.hexspoke { stroke: var(--grid); stroke-width: 1; opacity: .6; }
.aspike { stroke-width: 3; opacity: .55; }
.aspike.s1{stroke:var(--s1)} .aspike.s3{stroke:var(--s3)} .aspike.s4{stroke:var(--s4)}
.apt { stroke: var(--surface); stroke-width: 2; outline: none; }
.apt:hover, .apt:focus { filter: brightness(1.12); }
.apt.s1{fill:var(--s1)} .apt.s3{fill:var(--s3)} .apt.s4{fill:var(--s4)}
.alabel { font-size: 13px; font-weight: 600; fill: var(--ink); }
.alabel .aval { font-weight: 400; fill: var(--ink2); font-size: 12px; }
.wtri { fill: var(--s1); fill-opacity: .08; stroke: var(--axis); stroke-width: 1.5;
        transition: all .55s ease; }
.wtri.distress { fill: var(--neg); fill-opacity: .13; stroke: var(--neg); }
.hexpt { fill: transparent; stroke: var(--axis); stroke-width: 1; cursor: pointer; outline: none; }
.hexpt:hover, .hexpt:focus { stroke: var(--ink); stroke-width: 2; }
.hexpt.sel { stroke: var(--s1); stroke-width: 3; }
.hexflag .fbg { fill: var(--surface); stroke: var(--ring); stroke-width: 1; opacity: .55; }
.hexflag .ftxt { font-size: 11px; fill: var(--muted); }
.hexflag.lit .fbg { stroke: var(--s2); stroke-width: 2; opacity: 1; fill: var(--surface); }
.hexflag.lit .ftxt { fill: var(--ink); font-weight: 700; }
.hexctl { display: flex; gap: 8px; justify-content: center; align-items: center; margin: 8px 0; }
.hexctl button { background: var(--surface); color: var(--ink); border: 1px solid var(--ring);
                 border-radius: 8px; padding: 4px 14px; font-size: 15px; cursor: pointer; }
.hexinfo { text-align: center; color: var(--ink2); font-size: 12px; min-height: 18px; }
.hexnote { text-align: center; color: var(--muted); font-size: 12px; margin-top: 4px; }
</style>"""

_HEX_JS = """
<script>
(function () {
  let off = +(localStorage.getItem('hex_rot') || 0);   // directionalOffset, positions
  const base = %(base_rot)d;
  function apply() {
    const deg = (base + off) * 60;
    document.querySelectorAll('.hexrot').forEach(g =>
      g.style.transform = 'rotate(' + deg + 'deg)');
    document.querySelectorAll('.upright').forEach(el =>
      el.style.transform = 'rotate(' + (-deg) + 'deg)');
    localStorage.setItem('hex_rot', off);
  }
  window.HEX = {                                        // extension surface
    rotate(p) { off += p; apply(); },
    setOffset(p) { off = p; apply(); },
    onPoint: null,
  };
  document.getElementById('rl').onclick = () => HEX.rotate(-1);
  document.getElementById('rr').onclick = () => HEX.rotate(1);
  const info = document.querySelector('.hexinfo');
  document.querySelectorAll('.hexpt').forEach(pt => {
    const h = () => {
      document.querySelectorAll('.hexpt').forEach(p => p.classList.remove('sel'));
      pt.classList.add('sel');
      const d = +pt.dataset.dir;
      info.textContent = d === 0 ? 'center (0) — reserved / special'
        : 'direction ' + d + (pt.dataset.attr ? ' — ' + pt.dataset.attr : ' — open grid point');
      if (HEX.onPoint) HEX.onPoint(d);
    };
    pt.addEventListener('click', h);
    pt.addEventListener('keydown', e => { if (e.key === 'Enter') h(); });
  });
  apply();
})();
</script>"""


def render_page(hexes, subtitle="", rot=0, links=""):
    body = [links,
            '<div class="hexctl"><button id="rl" title="rotate left">⟲</button>'
            '<span class="hexinfo" style="min-width:220px">orient</span>'
            '<button id="rr" title="rotate right">⟳</button></div>',
            '<div class="cols" style="grid-template-columns:repeat(auto-fit,minmax(360px,1fr))">']
    for hx in hexes:
        body.append('<div class="chart hexcard">')
        body.append(f'<figcaption style="text-align:center"><b>{eco_viz._esc(hx.title)}</b></figcaption>')
        body.append(hx.to_svg(rot=0))
        if hx.note:
            body.append(f'<div class="hexnote">{eco_viz._esc(hx.note)}</div>')
        body.append("</div>")
    body.append("</div>")
    page = eco_viz._page("Economy hex", subtitle, "".join(body))
    page = page.replace("</head>", _HEX_CSS + "</head>")
    page = page.replace("</body>", (_HEX_JS % {"base_rot": rot}) + "</body>")
    return page


# ── CLI ────────────────────────────────────────────────────────────────────
DEMO_TEAMS = {
    "balanced": {"name": "balanced", "metalIncome": 20, "metalCurrent": 300,
                 "energyIncome": 1500, "energyCurrent": 2000, "energyStorage": 6000,
                 "bpAvail": 800, "bpUsed": 720},
    "reclaim-flood": {"name": "reclaim-flood", "metalIncome": 35, "metalCurrent": 4800,
                      "energyIncome": 180, "energyCurrent": 300, "energyStorage": 6000,
                      "bpAvail": 500, "bpUsed": 480},
    "energy-starved": {"name": "energy-starved", "metalIncome": 18, "metalCurrent": 100,
                       "energyIncome": 60, "energyCurrent": 80, "energyStorage": 2000,
                       "bpAvail": 900, "bpUsed": 300},
}


def main():
    ap = argparse.ArgumentParser(description="hex infographic (economy balance)")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--game", default=None)
    ap.add_argument("--team", type=int, default=None)
    ap.add_argument("--minute", type=int, default=None)
    ap.add_argument("--rot", type=int, default=0)
    a = ap.parse_args()

    if a.demo:
        hexes = [eco_hex(t) for t in DEMO_TEAMS.values()]
        t = DEMO_TEAMS["reclaim-flood"]
        trig, why = check_reclaim_overload(t)
        assert trig, "reclaim-overload rule failed to trigger on the demo state"
        assert solar_conturret_step(t) == "solar", "no energy -> should pick solar"
        t2 = dict(t, energyIncome=400, energyCurrent=3000)
        assert solar_conturret_step(t2) == "con_turret", "energy ok -> con turret"
        print(f"reclaim rule: TRIGGERED ({why}); step now: {solar_conturret_step(t)}")
        path = os.path.join(eco_viz.VIZ_DIR, "hex_demo.html")
    else:
        from bar_analytic_server import load_game
        game = load_game(a.game or 1)
        snap = game.recall(a.minute) if a.minute is not None else game.snapshot()
        teams = [x for x in snap.get("teams", []) if not x.get("dead")]
        if a.team is not None:
            teams = [x for x in teams if x.get("teamID") == a.team]
        hexes = [eco_hex(teams[0])] if teams else []
        path = os.path.join(eco_viz.VIZ_DIR, f"hex_team{teams[0]['teamID']}.html")
    os.makedirs(eco_viz.VIZ_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_page(hexes, subtitle="metal · bp · energy — imbalance from the "
                            "perfect economy; response flags on opposing vertices",
                            rot=a.rot))
    print(f"page: {path}")


if __name__ == "__main__":
    main()

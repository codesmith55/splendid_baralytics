#!/usr/bin/env python3
"""
positions/compare.py — IRG (In-Real-Game) build path comparison

Workflow:
  1. cherry_pick(criteria)  —  select the best matching real game snapshot
  2. eco_from_snapshot()    —  load it as a live Eco state
  3. simulate() × 2        —  run two competing priority concepts from that state
  4. compare_two()         —  show divergence at a target time OR time-to-target

Usage:
    python positions/compare.py
    python positions/compare.py --strat-a=solar_med --strat-b=wind_med
    python positions/compare.py --snapshot=leg-pos6-eco-t260-6mex
    python positions/compare.py --target=t2_energy
    python positions/compare.py --target=m_inc:20
    python positions/compare.py --criteria '{"n_mex":{"min":5},"tags":["light-solar"]}'
    python positions/compare.py --list-snapshots
    python positions/compare.py --list-strategies
"""

import argparse, json, math, os, sys
from dataclasses import dataclass, field
from typing import Optional, Callable

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))

# ── Legion constants ───────────────────────────────────────────────────────────

BASE_M    = 2.0
BASE_E    = 25.0
BASE_CAP  = 200.0
MEX_UPK   = 3.0
COM_BP    = 300
TUR_BP    = 200
CON_BP    = 80
SPOT      = 1.825
T1_INC    = 0.75 * SPOT
MED_DELTA = (2.00 - 0.75) * SPOT   # +2.281 m/s net
MED_SWING = 37                      # E/s per medmex drain
LEGMEX_E  = 7.0
T2_MINGEN = 300.0

UNIT = {
    'solar':      (155,     0, 2600),
    'wind':       ( 40,   175, 1600),
    'leg_mex':    ( 50,   500, 1880),
    'leg_medmex': (250,  5000, 5000),
    'leg_turret': (230,  3200, 5300),
    'leg_con':    (100,  1600, 3250),
}


# ── Eco state ──────────────────────────────────────────────────────────────────

@dataclass
class Eco:
    t:        float = 0.0
    metal:    float = 0.0
    energy:   float = 0.0
    m_inc:    float = BASE_M
    e_inc:    float = BASE_E
    e_upk:    float = 0.0
    bp:       int   = COM_BP
    e_cap:    float = BASE_CAP
    n_mex:    int   = 0
    n_med:    int   = 0
    n_solar:  int   = 0
    n_wind:   int   = 0
    m_gen:    float = 0.0   # metal generated since sim start
    m_spt:    float = 0.0
    events:   list  = field(default_factory=list)
    snaps:    list  = field(default_factory=list)
    # milestone tracking
    t2_energy_t:  Optional[float] = None
    first_med_t:  Optional[float] = None

    @property
    def e_net(self): return self.e_inc - self.e_upk

    def tick(self, dt: float):
        self.m_gen  += self.m_inc * dt
        self.metal   = min(self.metal + self.m_inc * dt, 2000)
        self.energy  = max(0.0, min(self.energy + self.e_net * dt, self.e_cap))
        self.t      += dt

    def affordable(self, unit: str) -> bool:
        return self.metal >= UNIT[unit][0]

    def snap(self):
        return dict(
            t=round(self.t), m_inc=round(self.m_inc, 2), e_net=round(self.e_net, 1),
            bp=self.bp, n_mex=self.n_mex, n_med=self.n_med,
            n_sol=self.n_solar, n_wnd=self.n_wind,
            m_gen=round(self.m_gen), metal=round(self.metal),
        )


# ── Snapshot loading and cherry-pick ──────────────────────────────────────────

def load_snapshots(path: Optional[str] = None) -> list:
    p = path or os.path.join(HERE, 'snapshots.json')
    with open(p) as f:
        return json.load(f)['snapshots']


def score_snapshot(snap: dict, criteria: dict) -> float:
    """
    Score a snapshot against criteria dict. Returns -1 if any hard constraint fails.

    Criteria keys:
      faction, position  — string exact match (hard disqualify on mismatch)
      tags               — list of required tags (hard disqualify if any missing)
      n_mex, n_med, t, m_inc, e_net  — numeric: {"min":X, "max":Y} or {"exact":X}
    """
    score = 0.0
    for key, crit in criteria.items():
        if key == 'tags':
            required = crit if isinstance(crit, list) else [crit]
            snap_tags = snap.get('tags', [])
            if not all(t in snap_tags for t in required):
                return -1.0
            score += 10.0
        elif key in ('faction', 'position'):
            if snap.get(key) != crit:
                return -1.0
            score += 10.0
        elif isinstance(crit, dict):
            val = snap.get(key)
            if val is None:
                score -= 2.0
                continue
            if 'exact' in crit:
                if val != crit['exact']:
                    return -1.0
                score += 8.0
            else:
                lo = crit.get('min', float('-inf'))
                hi = crit.get('max', float('inf'))
                if val < lo or val > hi:
                    return -1.0
                # Bonus for being near center of range
                if lo != float('-inf') and hi != float('inf'):
                    center = (lo + hi) / 2.0
                    span   = max(hi - lo, 1.0)
                    score += 5.0 * (1 - abs(val - center) / span)
                else:
                    score += 3.0
        else:
            # Exact match shorthand
            if snap.get(key) != crit:
                return -1.0
            score += 5.0
    return score


def cherry_pick(criteria: dict, snapshots: list, verbose: bool = True) -> dict:
    """
    Score every snapshot against criteria, return the best matching one.
    Prints reasoning if verbose=True.
    """
    scored = [(score_snapshot(s, criteria), s) for s in snapshots]
    scored = [(sc, s) for sc, s in scored if sc >= 0]
    if not scored:
        raise ValueError(f"No snapshot matches criteria: {criteria}")

    scored.sort(key=lambda x: -x[0])
    best_score, best = scored[0]

    if verbose:
        print(f"  cherry_pick: selected '{best['id']}' (score={best_score:.1f})")
        print(f"    {best['desc']}")
        if len(scored) > 1:
            runners = ', '.join(f"'{s['id']}'({sc:.0f})" for sc, s in scored[1:3])
            print(f"    runners-up: {runners}")
    return best


def eco_from_snapshot(snap: dict) -> Eco:
    """Build an Eco state from a snapshot dict."""
    s          = Eco()
    s.t        = snap['t']
    s.n_mex    = snap.get('n_mex', 5)
    s.n_med    = snap.get('n_med', 0)
    s.n_solar  = snap.get('n_solar', 0)
    s.n_wind   = snap.get('n_wind', 0)
    s.bp       = snap.get('bp', COM_BP)
    s.e_cap    = snap.get('e_cap', BASE_CAP)
    s.metal    = snap.get('metal_bank', 0)
    s.energy   = snap.get('energy_bank', 0)
    # Reconstruct income from snapshot values rather than re-deriving
    # m_inc and e_net are stored directly in the snapshot
    s.m_inc    = snap.get('m_inc', BASE_M)
    # Reconstruct e_inc and e_upk from e_net + known upkeep
    n_med  = s.n_med
    n_mex  = s.n_mex
    # Upkeep = all mex slots × 3 + medmex drain × 30
    s.e_upk = n_mex * MEX_UPK + n_med * 30
    # e_inc = e_net + e_upk (gross income)
    s.e_inc = snap.get('e_net', 110) + s.e_upk
    return s


# ── Build engine ───────────────────────────────────────────────────────────────

def _build_time(s: Eco, unit: str) -> tuple:
    _, e_cost, bw = UNIT[unit]
    full_t    = bw / s.bp
    available = s.energy + s.e_net * full_t
    if available >= e_cost or e_cost == 0:
        return full_t, 0.0
    if s.e_net <= 0:
        return full_t + 999, 999.0
    stall = max(0.0, (e_cost - available) / s.e_net)
    return full_t + stall, stall


def do_build(s: Eco, unit: str, wind_e: float, verbose: bool) -> None:
    m_cost, e_cost, _ = UNIT[unit]
    bt, stall = _build_time(s, unit)

    if not s.affordable(unit):
        wait = max(0.0, (m_cost - s.metal) / s.m_inc)
        s.tick(wait)

    s.metal -= m_cost
    s.m_spt += m_cost
    s.tick(bt)
    s.energy = max(0.0, s.energy - e_cost)

    label = ""
    if unit == 'solar':
        s.n_solar += 1;  s.e_inc += 20
        label = f"+20 E/s → e_net {s.e_net:.0f}"
    elif unit == 'wind':
        s.n_wind  += 1;  s.e_inc += wind_e
        label = f"+{wind_e:.0f} E/s → e_net {s.e_net:.0f}"
    elif unit == 'leg_mex':
        s.n_mex += 1;  s.m_inc += T1_INC;  s.e_inc += LEGMEX_E;  s.e_upk += MEX_UPK
        label = f"+{T1_INC:.2f} m/s → m_inc {s.m_inc:.2f}  e_net {s.e_net:.0f}"
    elif unit == 'leg_medmex':
        s.n_med += 1;  s.m_inc += MED_DELTA;  s.e_inc -= LEGMEX_E;  s.e_upk += 30
        label = f"+{MED_DELTA:.2f} m/s → m_inc {s.m_inc:.2f}  e_net {s.e_net:.0f}"
        if s.first_med_t is None:
            s.first_med_t = s.t
    elif unit == 'leg_turret':
        s.bp += TUR_BP
        label = f"+{TUR_BP} BP → bp {s.bp}"
    elif unit == 'leg_con':
        s.bp += CON_BP
        label = f"+{CON_BP} BP → bp {s.bp}"

    stall_s = f"  ⏸{stall:.0f}s" if stall > 1 else ""
    tag = {'solar':'SOLAR','wind':'WIND','leg_mex':'T1-MEX','leg_medmex':'MED-MEX',
           'leg_turret':'TURRET','leg_con':'CON'}.get(unit, unit.upper())

    if verbose:
        mins, secs = int(s.t // 60), int(s.t % 60)
        print(f"  {mins}:{secs:02d}  [{tag:7s}]  {label:46s}"
              f"(cost {m_cost}m/{e_cost}e  {bt:.1f}s){stall_s}"
              f"  bank {s.metal:.0f}m/{s.energy:.0f}E")

    s.events.append({'t': round(s.t, 1), 'unit': unit, 'bt': round(bt, 1),
                     'stall': round(stall, 1), 'label': label})


# ── Strategy library ───────────────────────────────────────────────────────────
#
# Each strategy is a function(s: Eco, wind_e: float) -> Optional[str]
# returning the next unit to build, or None when done / no-op.
#
# Named strategies are registered in STRATEGIES dict at bottom of this section.

def _solar_med(s: Eco, wind_e: float) -> Optional[str]:
    """
    SOLAR_MED — Solar gates medmex (income-first philosophy).
    Build solar to sustain each medmex slot. No wind.
    Keeps building solar toward T2_MINGEN after medmexes max out.
    Post-T2 solar reclaim is housekeeping, not modeled here.
    """
    can_med = (s.e_net - MED_SWING) >= 20
    if s.n_mex < 7:        return 'leg_mex'
    if not can_med:         return 'solar'
    if s.n_med < min(s.n_mex - 1, 6): return 'leg_medmex'
    if s.e_net < T2_MINGEN: return 'solar'
    return None


def _wind_med(s: Eco, wind_e: float) -> Optional[str]:
    """
    WIND_MED — Wind gates medmex (permanent-energy philosophy).
    Build wind to sustain each medmex slot. Keeps starting solar as-is.
    Wind is permanent: no transition cost. Slower stall recovery per unit spent.
    """
    can_med = (s.e_net - MED_SWING) >= 20
    if s.n_mex < 7:        return 'leg_mex'
    if not can_med:         return 'wind'
    if s.n_med < min(s.n_mex - 1, 6): return 'leg_medmex'
    if s.e_net < T2_MINGEN: return 'wind'
    return None


def _solar_t2(s: Eco, wind_e: float) -> Optional[str]:
    """
    SOLAR_T2 — Straight T2 energy sprint via solar. No medmex.
    Prioritizes reaching T2_MINGEN E/s as fast as possible via cheap BP-per-E.
    Highest T2 energy rate of any solar build but entirely backfill-dependent later.
    """
    if s.n_mex < 7:         return 'leg_mex'
    if s.e_net < T2_MINGEN: return 'solar'
    return None


def _wind_t2(s: Eco, wind_e: float) -> Optional[str]:
    """
    WIND_T2 — T2 energy sprint via wind only. No medmex.
    Cleanest long-term energy: no backfill, no reclaim obligation.
    Fastest to T2 energy on ATG-level wind.
    """
    if s.n_mex < 7:         return 'leg_mex'
    if s.e_net < T2_MINGEN: return 'wind'
    return None


def _med_first(s: Eco, wind_e: float) -> Optional[str]:
    """
    MED_FIRST — Medmex as soon as technically gated, add energy only when forced.
    Accepts large energy stalls. Pure income maximization within the window.
    No preference for solar vs wind — uses solar as the faster 20 E/s gate.
    """
    can_med = s.e_net > MED_SWING + 5   # minimal safety margin
    if s.n_mex < 7:        return 'leg_mex'
    if not can_med:         return 'solar'  # smallest gate: 1 solar = 20 E/s
    if s.n_med < min(s.n_mex - 1, 6): return 'leg_medmex'
    if s.e_net < T2_MINGEN: return 'solar'
    return None


def _wind_bp(s: Eco, wind_e: float) -> Optional[str]:
    """
    WIND_BP — Wind for energy, early turret/con for BP, then medmex.
    Invests some income into BP pool before medmex phase.
    Models the idea: better BP = less time gated on energy stalls.
    """
    can_med = (s.e_net - MED_SWING) >= 20
    if s.n_mex < 7:          return 'leg_mex'
    # Build a turret before first medmex if BP is still at base
    if s.bp < (COM_BP + TUR_BP + TUR_BP) and s.n_med == 0:
        if not can_med:      return 'wind'
        return 'leg_turret'  # second turret for BP before going medmex
    if not can_med:           return 'wind'
    if s.n_med < min(s.n_mex - 1, 6): return 'leg_medmex'
    if s.e_net < T2_MINGEN:  return 'wind'
    return None


STRATEGIES: dict[str, tuple[Callable, str]] = {
    'solar_med':  (_solar_med,  'Solar gates medmex — income-first, reclaim is post-T2'),
    'wind_med':   (_wind_med,   'Wind gates medmex — permanent energy, no transition needed'),
    'solar_t2':   (_solar_t2,   'Solar T2 sprint — no medmex, fastest cheap E to 300 E/s'),
    'wind_t2':    (_wind_t2,    'Wind T2 sprint — cleanest path, no reclaim obligation'),
    'med_first':  (_med_first,  'Medmex as soon as gated — income max, accept stalls'),
    'wind_bp':    (_wind_bp,    'Wind + BP investment before medmex — longer build, less stall'),
}


# ── Target definitions ─────────────────────────────────────────────────────────

def parse_target(target_str: str) -> tuple:
    """
    Parse a target string into (label, check_fn).
    Formats:
      t2_energy         — first time e_net >= 300
      first_medmex      — first time n_med >= 1
      n_medmex:3        — first time n_med >= 3
      m_inc:20          — first time m_inc >= 20.0
      at:480            — fixed time (compare state at T=480s)
    """
    if target_str == 't2_energy':
        return ('T2 energy (300 E/s)', lambda s: s.e_net >= T2_MINGEN)
    if target_str == 'first_medmex':
        return ('first medmex', lambda s: s.n_med >= 1)
    if ':' in target_str:
        kind, val = target_str.split(':', 1)
        v = float(val)
        if kind == 'n_medmex':
            return (f'{int(v)} medmexes', lambda s, n=int(v): s.n_med >= n)
        if kind == 'm_inc':
            return (f'm_inc >= {v:.1f}', lambda s, x=v: s.m_inc >= x)
        if kind == 'at':
            return (f'T={int(v)}s snapshot', None)   # fixed-time mode
    # fallback: numeric seconds
    try:
        t = float(target_str)
        return (f'T={int(t)}s snapshot', None)
    except ValueError:
        raise ValueError(f"Unknown target format: '{target_str}'. "
                         f"Use t2_energy, first_medmex, n_medmex:N, m_inc:X, at:N")


# ── Simulation ─────────────────────────────────────────────────────────────────

def simulate(strat_fn: Callable, snapshot: dict, wind_e: float,
             t_end: float, verbose: bool, label: str,
             target_check: Optional[Callable] = None) -> tuple:
    """
    Simulate strategy from snapshot until t_end (or target hit).
    Returns (Eco_state, target_hit_t, target_snap).
    target_snap is an Eco.snap() dict captured exactly at target hit (or None).
    """
    s           = eco_from_snapshot(snapshot)
    snap_at     = s.t + 60
    target_t    = None
    target_snap = None

    if verbose:
        w = 65
        print(f"\n{'═'*w}")
        print(f"  {label}")
        print(f"{'─'*w}")
        mins, secs = int(s.t // 60), int(s.t % 60)
        print(f"  {mins}:{secs:02d}  m_inc={s.m_inc:.2f}  e_net={s.e_net:.0f}  bp={s.bp}")
        print(f"  [{s.n_mex} mex | {s.n_solar} sol | {s.n_wind} wnd | {s.n_med} med | {s.metal:.0f}m bank]")
        print(f"{'─'*w}")

    while s.t < t_end:
        # Check target
        if target_check and target_t is None and target_check(s):
            target_t    = s.t
            target_snap = s.snap()
            s.events.append({'t': round(s.t, 1), 'unit': 'TARGET',
                             'bt': 0, 'stall': 0, 'label': 'target reached'})
            if verbose:
                mins, secs = int(s.t // 60), int(s.t % 60)
                print(f"  {mins}:{secs:02d}  *** TARGET REACHED ***  "
                      f"m_inc={s.m_inc:.2f}  e_net={s.e_net:.0f}  [{s.n_med}med]")

        if s.t >= snap_at:
            snap = s.snap()
            s.snaps.append(snap)
            if verbose:
                gap = max(0, T2_MINGEN - snap['e_net'])
                print(f"\n  ─── {int(snap['t']//60)}:{int(snap['t']%60):02d} "
                      f"m_inc={snap['m_inc']:.2f}  e_net={snap['e_net']:.0f}"
                      f"  m_gen={snap['m_gen']}m  T2gap={gap:.0f}"
                      f"  [{snap['n_mex']}T1|{snap['n_med']}med|{snap['n_sol']}sol|{snap['n_wnd']}wnd] ───\n")
            snap_at += 60

        unit = strat_fn(s, wind_e)
        if unit is None:
            s.tick(min(5.0, t_end - s.t))
            continue

        # Don't start a build that would complete well past t_end
        m_wait  = max(0.0, (UNIT[unit][0] - s.metal) / max(s.m_inc, 0.001))
        bt_est, _ = _build_time(s, unit)
        if s.t + m_wait + bt_est > t_end + 10:   # 10s grace for short overruns
            s.tick(t_end - s.t)
            break

        if not s.affordable(unit):
            wait = max(0.0, (UNIT[unit][0] - s.metal) / s.m_inc)
            s.tick(min(wait + 0.1, t_end - s.t))
            continue

        do_build(s, unit, wind_e, verbose)

    s.snaps.append(s.snap())
    return s, target_t, target_snap


# ── Comparison output ──────────────────────────────────────────────────────────

def compare_two(snap_meta: dict, a_result: tuple, b_result: tuple,
                a_name: str, b_name: str,
                mode: str, target_label: str, wind_e: float):
    """
    Print comparison between two strategies run from the same starting snapshot.
    mode: 'at_time' | 'time_to_target'
    """
    sa, ta, tsnap_a = a_result   # Eco state, target_hit_t, target-hit snap
    sb, tb, tsnap_b = b_result

    w = 80
    print(f"\n{'═'*w}")
    print(f"  COMPARISON — from '{snap_meta['id']}'")
    print(f"  {snap_meta['desc']}")
    print(f"{'─'*w}")
    print(f"  Starting state:  T={snap_meta['t']}s  m_inc={snap_meta['m_inc']:.2f}  "
          f"e_net={snap_meta['e_net']:.0f}  bp={snap_meta['bp']}")
    print(f"  [{snap_meta['n_mex']} mex | {snap_meta['n_solar']} solar | "
          f"{snap_meta.get('n_wind',0)} wind | {snap_meta['n_med']} med]")
    print(f"{'═'*w}")

    if mode == 'time_to_target':
        print(f"\n  Target: {target_label}")
        print()
        for name, s, t_hit, tsnap in [(a_name, sa, ta, tsnap_a), (b_name, sb, tb, tsnap_b)]:
            if t_hit is not None:
                mins, secs = int(t_hit // 60), int(t_hit % 60)
                game_t = f"{mins}:{secs:02d}"
                delta  = t_hit - snap_meta['t']
                f = tsnap  # state at exact moment target was hit
                print(f"  {name:<24}  reached at {game_t}  ({delta:.0f}s after start)")
                print(f"  {'':24}  m_inc={f['m_inc']:.2f}  e_net={f['e_net']:.0f}"
                      f"  [{f['n_med']}med|{f['n_sol']}sol|{f['n_wnd']}wnd]")
            else:
                f = s.snaps[-1] if s.snaps else s.snap()
                print(f"  {name:<24}  NOT REACHED  (final e_net={f['e_net']:.0f}, "
                      f"m_inc={f['m_inc']:.2f}, [{f['n_med']}med])")
            print()

        if ta is not None and tb is not None:
            delta = tb - ta
            winner = a_name if ta < tb else b_name
            loser  = b_name if ta < tb else a_name
            print(f"  ► {winner} reaches target {abs(delta):.0f}s earlier than {loser}")
        elif ta is not None:
            print(f"  ► {a_name} reached target; {b_name} did not")
        elif tb is not None:
            print(f"  ► {b_name} reached target; {a_name} did not")
        else:
            print(f"  ► Neither reached target within simulation window")

    else:  # at_time
        fa = sa.snaps[-1] if sa.snaps else sa.snap()
        fb = sb.snaps[-1] if sb.snaps else sb.snap()
        # Use the average of the two final times (builds can complete slightly past t_end)
        end_t_a = int(sa.t)
        end_t_b = int(sb.t)
        end_label = f"T≈{end_t_a}s" if end_t_a == end_t_b else f"T={end_t_a}s/{end_t_b}s"

        print(f"\n  State at end of window ({end_label}):\n")
        print(f"  {'':24}  {'m_inc':>6}  {'e_net':>6}  {'med':>4}  "
              f"{'sol':>4}  {'wnd':>4}  {'m_gen':>7}  {'T2_gap':>7}")
        print(f"  {'─'*24}  {'─'*6}  {'─'*6}  {'─'*4}  "
              f"{'─'*4}  {'─'*4}  {'─'*7}  {'─'*7}")

        for name, f, s in [(a_name, fa, sa), (b_name, fb, sb)]:
            gap = max(0, T2_MINGEN - f['e_net'])
            print(f"  {name:<24}  {f['m_inc']:>6.2f}  {f['e_net']:>6.0f}  {f['n_med']:>4}  "
                  f"{f['n_sol']:>4}  {f['n_wnd']:>4}  {f['m_gen']:>7.0f}  {gap:>7.0f}")

        # Delta row
        dm   = fa['m_inc'] - fb['m_inc']
        dgen = fa['m_gen'] - fb['m_gen']
        dmed = fa['n_med'] - fb['n_med']
        print(f"\n  delta ({a_name} minus {b_name}):")
        print(f"    m_inc: {dm:+.2f} m/s   m_gen: {dgen:+.0f}m   medmex: {dmed:+d}")

        # BP obligation
        n_sol_a = fa['n_sol']
        n_sol_b = fb['n_sol']
        bp_extra = (n_sol_a - n_sol_b) * 2 * 2600 / sa.bp
        opp_per_builder = bp_extra * max(fa['m_inc'], 0.1)
        print(f"\n  Double-BP solar obligation (marginal: {a_name} has {n_sol_a-n_sol_b:+d} extra solar):")
        print(f"    Extra reclaim BP: {bp_extra:.0f}s  "
              f"Opportunity cost 1 builder={opp_per_builder:.0f}m  "
              f"2 builders={opp_per_builder/2:.0f}m  "
              f"3 builders={opp_per_builder/3:.0f}m")
        if abs(n_sol_a - n_sol_b) > 0:
            net2 = dgen - opp_per_builder / 2
            print(f"  Net A advantage with 1 worker reclaiming: {net2:+.0f}m")
        print()

    # Wind condition note
    n_wnd_per_med = math.ceil(MED_SWING / max(wind_e, 0.1))
    c_sol = 250 + 2 * 155
    c_wnd = 250 + n_wnd_per_med * 40
    print(f"  Medmex full cost:  solar={c_sol}m (ROI {round(c_sol/MED_DELTA)}s)   "
          f"wind={c_wnd}m (ROI {round(c_wnd/MED_DELTA)}s)   wind saves {c_sol-c_wnd}m/slot")
    print(f"  wind={wind_e} E/s  →  {n_wnd_per_med} winds per medmex slot")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description=__doc__)
    ap.add_argument('--strat-a',         default='solar_med',
                    help='Strategy A name (default: solar_med)')
    ap.add_argument('--strat-b',         default='wind_med',
                    help='Strategy B name (default: wind_med)')
    ap.add_argument('--target',          default='at:480',
                    help='Comparison target. Examples: t2_energy  first_medmex  m_inc:20  at:480')
    ap.add_argument('--snapshot',        default=None,
                    help='Use this snapshot ID directly (skips cherry-pick)')
    ap.add_argument('--criteria',        default=None,
                    help='JSON criteria for cherry_pick, e.g. \'{"n_mex":{"min":5}}\'')
    ap.add_argument('--wind',            type=float, default=10.0,
                    help='E/s per wind turbine (default 10)')
    ap.add_argument('--no-verbose',      action='store_true')
    ap.add_argument('--list-snapshots',  action='store_true')
    ap.add_argument('--list-strategies', action='store_true')
    args = ap.parse_args()

    if args.list_strategies:
        print("\nAvailable strategies:")
        for name, (_, desc) in STRATEGIES.items():
            print(f"  {name:<14}  {desc}")
        print()
        return

    snapshots = load_snapshots()

    if args.list_snapshots:
        print("\nKnown snapshots:")
        for s in snapshots:
            tags = ', '.join(s.get('tags', []))
            print(f"  {s['id']}")
            print(f"    T={s['t']}s  m_inc={s['m_inc']}  e_net={s['e_net']}  [{tags}]")
            print(f"    {s['desc']}")
            print()
        return

    # Select snapshot
    verbose = not args.no_verbose
    if args.snapshot:
        snap = next((s for s in snapshots if s['id'] == args.snapshot), None)
        if snap is None:
            print(f"Snapshot '{args.snapshot}' not found. Use --list-snapshots.")
            sys.exit(1)
        if verbose:
            print(f"\n  Using snapshot: '{snap['id']}'")
    else:
        criteria = json.loads(args.criteria) if args.criteria else {
            'faction': 'legion',
            'n_med': {'exact': 0},
            'n_mex': {'min': 5},
        }
        if verbose:
            print(f"\n  cherry_pick criteria: {criteria}")
        snap = cherry_pick(criteria, snapshots, verbose=verbose)

    # Resolve strategies
    if args.strat_a not in STRATEGIES:
        print(f"Unknown strategy '{args.strat_a}'. Use --list-strategies.")
        sys.exit(1)
    if args.strat_b not in STRATEGIES:
        print(f"Unknown strategy '{args.strat_b}'. Use --list-strategies.")
        sys.exit(1)

    fn_a, desc_a = STRATEGIES[args.strat_a]
    fn_b, desc_b = STRATEGIES[args.strat_b]

    # Parse target
    target_label, target_check = parse_target(args.target)
    mode = 'at_time' if target_check is None else 'time_to_target'

    # For at_time mode, parse the time (absolute game seconds)
    if mode == 'at_time':
        try:
            t_end = float(args.target.split(':')[-1])
        except (ValueError, IndexError):
            t_end = snap['t'] + 235   # default: ~4 min window from snapshot
    else:
        # Simulate up to 10 min past snapshot; target check stops early if hit
        t_end = snap['t'] + 600

    wind_e = args.wind

    print(f"""
+======================================================+
|  IRG build path comparison                           |
|  Strategies: {args.strat_a:<12} vs {args.strat_b:<12}         |
|  Target:     {target_label:<38}|
|  wind={wind_e:.1f} E/s                                       |
+======================================================+""")

    if verbose:
        print(f"\n  {args.strat_a}: {desc_a}")
        print(f"  {args.strat_b}: {desc_b}")

    label_a = f"A  {args.strat_a.upper()}"
    label_b = f"B  {args.strat_b.upper()}"

    result_a = simulate(fn_a, snap, wind_e, t_end, verbose, f"{label_a}: {desc_a}", target_check)
    result_b = simulate(fn_b, snap, wind_e, t_end, verbose, f"{label_b}: {desc_b}", target_check)

    compare_two(snap, result_a, result_b, label_a, label_b,
                mode, target_label, wind_e)


if __name__ == '__main__':
    main()

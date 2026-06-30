#!/usr/bin/env python3
"""
positions/navigator.py — Economy state space navigator

Explores potential game states from a known starting point.
Any external agent can call these functions to traverse possible economies.

Usage:
    from positions.navigator import step_options, compare_t2_entry, project_strategies

    # From a live IRG state: what are the best next builds?
    options = step_options(state_dict, wind_e=10)
    for opt in options[:3]:
        print(opt['roi']['label'], '→ ROI', opt['roi']['roi_s'], 's')

    # Compare two strategies to T2 transition:
    result = compare_t2_entry(state_dict, 'solar_med', 'wind_med', wind_e=10)
    print(result['summary'])

HTTP-ready: all public functions are dict-in / dict-out.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from state_api import (
    GameState, state_from_dict, state_to_dict,
    apply_action, roi, available_actions, t2_wealth,
    project_to_t2, ACTIONS, T2_MINGEN,
    MOHO_FROM_MED, MOHO_FROM_T1, MOHO_NET_FROM_MED, MOHO_NET_FROM_T1,
)
from meta_log import check as check_notable, summarize as summarize_notable, rate_t2_entry
from typing import Optional, Callable

# ── Built-in strategy functions ────────────────────────────────────────────────
# These mirror compare.py strategies but work on GameState directly.
# Return action_id (str) or None.

def _strat_solar_med(s: GameState, wind_e: float) -> Optional[str]:
    can_med = (s.e_net - 37) >= 20
    if s.n_mex < 7:           return 'leg_mex'
    if not can_med:           return 'solar'
    if s.n_med < min(s.n_mex - 1, 6): return 'leg_medmex'
    if s.e_net < T2_MINGEN:  return 'solar'
    return None

def _strat_wind_med(s: GameState, wind_e: float) -> Optional[str]:
    can_med = (s.e_net - 37) >= 20
    if s.n_mex < 7:           return 'leg_mex'
    if not can_med:           return 'wind'
    if s.n_med < min(s.n_mex - 1, 6): return 'leg_medmex'
    if s.e_net < T2_MINGEN:  return 'wind'
    return None

def _strat_solar_t2(s: GameState, wind_e: float) -> Optional[str]:
    if s.n_mex < 7:           return 'leg_mex'
    if s.e_net < T2_MINGEN:  return 'solar'
    return None

def _strat_wind_t2(s: GameState, wind_e: float) -> Optional[str]:
    if s.n_mex < 7:           return 'leg_mex'
    if s.e_net < T2_MINGEN:  return 'wind'
    return None

def _strat_med_first(s: GameState, wind_e: float) -> Optional[str]:
    can_med = s.e_net > 42
    if s.n_mex < 7:           return 'leg_mex'
    if not can_med:           return 'solar'
    if s.n_med < min(s.n_mex - 1, 6): return 'leg_medmex'
    if s.e_net < T2_MINGEN:  return 'solar'
    return None

def _strat_moho_med(s: GameState, wind_e: float) -> Optional[str]:
    """At T2: prioritize upgrading medmex slots to moho (best ROI)."""
    if s.n_med >= 1 and s.metal >= MOHO_NET_FROM_MED:
        return 'upgrade_med_moho'
    if s.n_mex >= 1 and s.metal >= MOHO_NET_FROM_T1:
        return 'upgrade_t1_moho'
    return None

STRATEGIES: dict[str, tuple[Callable, str]] = {
    'solar_med':  (_strat_solar_med,  'Solar gates medmex → income-first, reclaim post-T2'),
    'wind_med':   (_strat_wind_med,   'Wind gates medmex → permanent energy'),
    'solar_t2':   (_strat_solar_t2,   'Solar sprint to T2 energy (no medmex)'),
    'wind_t2':    (_strat_wind_t2,    'Wind sprint to T2 energy (no medmex)'),
    'med_first':  (_strat_med_first,  'Medmex as soon as gated, accept energy stall'),
    'moho_med':   (_strat_moho_med,   'Post-T2: upgrade medmex → moho (best ROI first)'),
}


# ── Step-level explorer ────────────────────────────────────────────────────────

def step_options(params: dict, wind_e: Optional[float] = None) -> list[dict]:
    """
    From current state, evaluate every available action.
    Returns list of options sorted by roi_s (best ROI first).

    Each option:
      {action_id, label, roi, resulting_state, notables, wealth_if_t2_ready}
    """
    s      = state_from_dict(params)
    eff_w  = wind_e if wind_e is not None else s.wind_e
    acts   = available_actions(s)
    opts   = []

    for aid in acts:
        r   = roi(s, aid, eff_w)
        ns, bt = apply_action(s, aid, eff_w)
        ns_d   = state_to_dict(ns)
        notables = check_notable(ns_d, state_to_dict(s))

        entry = {
            'action_id':       aid,
            'label':           r['label'],
            'roi':             r,
            'build_wall_s':    round(bt, 1),
            'resulting_state': ns_d,
            'notables':        notables,
        }
        if ns.t2_ready:
            entry['t2_wealth'] = t2_wealth(ns)
        opts.append(entry)

    opts.sort(key=lambda o: o['roi']['roi_s'])
    return opts


# ── T2 transition comparison ───────────────────────────────────────────────────

def compare_t2_entry(
        params:   dict,
        strat_a:  str = 'solar_med',
        strat_b:  str = 'wind_med',
        wind_e:   Optional[float] = None,
        t_limit:  float = 600.0,
) -> dict:
    """
    Project two strategies forward from the same state to T2 transition.
    Returns a side-by-side comparison dict with wealth at T2 for each strategy.
    """
    s    = state_from_dict(params)
    eff_w = wind_e if wind_e is not None else s.wind_e

    if strat_a not in STRATEGIES or strat_b not in STRATEGIES:
        return {'error': f'Unknown strategy. Available: {list(STRATEGIES)}'}

    fn_a, desc_a = STRATEGIES[strat_a]
    fn_b, desc_b = STRATEGIES[strat_b]

    end_a, events_a = project_to_t2(s, fn_a, eff_w, t_limit)
    end_b, events_b = project_to_t2(s, fn_b, eff_w, t_limit)

    w_a = t2_wealth(end_a)
    w_b = t2_wealth(end_b)
    r_a = rate_t2_entry(w_a)
    r_b = rate_t2_entry(w_b)

    def delta(key):
        return round(w_a.get(key, 0) - w_b.get(key, 0), 1)

    # Advantage calculation: who has better liquid at T2?
    t_a = w_a.get('t', end_a.t)
    t_b = w_b.get('t', end_b.t)
    liq_a = w_a.get('liquid', 0)
    liq_b = w_b.get('liquid', 0)

    # If A hits T2 earlier, normalize B's liquid to that time
    t2_hit_a = next((e['snap']['t'] for e in events_a if e.get('type') == 't2_threshold'), None)
    t2_hit_b = next((e['snap']['t'] for e in events_b if e.get('type') == 't2_threshold'), None)

    summary_lines = [
        f"T2 transition: {strat_a}={_fmt_t(t2_hit_a)}  {strat_b}={_fmt_t(t2_hit_b)}",
        f"  Time delta: {abs((t2_hit_a or 0)-(t2_hit_b or 0)):.0f}s earlier for "
        f"{'A' if (t2_hit_a or 9999) < (t2_hit_b or 9999) else 'B'}",
        f"  Liquid at T2 — {strat_a}: {liq_a:.0f}m  {strat_b}: {liq_b:.0f}m  (delta: {delta('liquid'):+.0f}m)",
        f"  Med slots — A: {w_a.get('n_med',0)}  B: {w_b.get('n_med',0)}",
        f"  Moho fundable now — A: {w_a.get('med_moho_fundable_now',0)} med-slots  "
        f"B: {w_b.get('med_moho_fundable_now',0)} med-slots",
        f"  Rating: {strat_a}={r_a['label']}  {strat_b}={r_b['label']}",
    ]

    return {
        'start_state':  state_to_dict(s),
        'strat_a':      {'id': strat_a, 'desc': desc_a, 't2_at': t2_hit_a,
                         'end_state': state_to_dict(end_a), 'wealth': w_a, 'rating': r_a},
        'strat_b':      {'id': strat_b, 'desc': desc_b, 't2_at': t2_hit_b,
                         'end_state': state_to_dict(end_b), 'wealth': w_b, 'rating': r_b},
        'delta':        {k: delta(k) for k in ('t', 'liquid', 'total_available',
                                                'n_med', 'med_moho_fundable_now')},
        'summary':      '\n'.join(summary_lines),
        'events_a':     events_a,
        'events_b':     events_b,
    }


def _fmt_t(t: Optional[float]) -> str:
    if t is None: return '?'
    return f"{int(t)//60}:{int(t)%60:02d}"


# ── Multi-strategy forward sweep ───────────────────────────────────────────────

def project_strategies(
        params:     dict,
        strategy_ids: Optional[list[str]] = None,
        wind_e:     Optional[float] = None,
        t_limit:    float = 600.0,
) -> dict:
    """
    Project all (or selected) strategies to T2 from the same starting state.
    Returns ranked results by T2 liquid wealth.
    """
    s        = state_from_dict(params)
    eff_w    = wind_e if wind_e is not None else s.wind_e
    strat_ids = strategy_ids or list(STRATEGIES.keys())

    results = []
    for sid in strat_ids:
        if sid not in STRATEGIES:
            continue
        fn, desc = STRATEGIES[sid]
        end, events = project_to_t2(s, fn, eff_w, t_limit)
        w = t2_wealth(end)
        r = rate_t2_entry(w)
        t2_hit = next((e['snap']['t'] for e in events if e.get('type') == 't2_threshold'), None)
        results.append({
            'strategy':   sid,
            'desc':       desc,
            't2_at':      t2_hit,
            'wealth':     w,
            'rating':     r,
            'end_state':  state_to_dict(end),
            'events':     events,
        })

    # Sort: t2_ready first, then by liquid wealth descending
    results.sort(key=lambda r: (
        -(r['wealth'].get('liquid', 0)),
        r.get('t2_at') or 9999,
    ))

    return {
        'start':     state_to_dict(s),
        'wind_e':    eff_w,
        'results':   results,
        'winner':    results[0]['strategy'] if results else None,
    }


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse, json

    ap = argparse.ArgumentParser(description='Economy state navigator CLI')
    ap.add_argument('--snapshot',  default=None, help='Snapshot ID from snapshots.json')
    ap.add_argument('--strat-a',   default='solar_med')
    ap.add_argument('--strat-b',   default='wind_med')
    ap.add_argument('--wind',      type=float, default=10.0)
    ap.add_argument('--t-limit',   type=float, default=600.0)
    ap.add_argument('--all-strats', action='store_true')
    ap.add_argument('--step',       action='store_true', help='Show step options from start state')
    args = ap.parse_args()

    # Load snapshot
    HERE = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(HERE, 'snapshots.json')) as f:
        snaps = {s['id']: s for s in json.load(f)['snapshots']}

    snap_id = args.snapshot or 'leg-pos6-eco-t245-standard'
    if snap_id not in snaps:
        print(f'Unknown snapshot: {snap_id}. Available: {list(snaps)}')
        sys.exit(1)

    snap = snaps[snap_id]
    print(f'\nStarting from: {snap["id"]}')
    print(f'  {snap["desc"]}')
    print(f'  T={snap["t"]}s  m_inc={snap["m_inc"]}  e_net={snap["e_net"]}  [{snap["n_mex"]}mex|{snap["n_solar"]}sol]')

    if args.step:
        print('\nStep options (next single build, ranked by ROI):')
        opts = step_options(snap, wind_e=args.wind)
        for opt in opts:
            r = opt['roi']
            notables_str = '  ← ' + ', '.join(n['label'] for n in opt['notables']) if opt['notables'] else ''
            print(f"  {opt['action_id']:<20}  ROI {r['roi_s']:>6.1f}s  "
                  f"net {r['net_metal']:>4}m  Δm {r['income_gain']:>+.3f}  "
                  f"ΔE {r['e_delta']:>+.0f}{notables_str}")

    elif args.all_strats:
        print(f'\nAll strategies projected to T2 (wind={args.wind}):')
        result = project_strategies(snap, wind_e=args.wind, t_limit=args.t_limit)
        print(f'{"strategy":<14}  {"T2 at":>7}  {"liquid":>8}  {"n_med":>5}  '
              f'{"fundable":>8}  {"rating"}')
        print('─' * 65)
        for r in result['results']:
            w  = r['wealth']
            t  = r.get('t2_at')
            ts = _fmt_t(t)
            print(f"  {r['strategy']:<12}  {ts:>7}  {w.get('liquid',0):>8.0f}m  "
                  f"{w.get('n_med',0):>5}  {w.get('med_moho_fundable_now',0):>8}  "
                  f"{r['rating']['label']}")

    else:
        result = compare_t2_entry(snap, args.strat_a, args.strat_b,
                                  wind_e=args.wind, t_limit=args.t_limit)
        print(f'\n{result["summary"]}')

        for key in ('strat_a', 'strat_b'):
            r  = result[key]
            w  = r['wealth']
            print(f"\n  {r['id']}: {r['desc']}")
            print(f"    T2 at {_fmt_t(r['t2_at'])}  "
                  f"liquid={w.get('liquid',0):.0f}m  "
                  f"total={w.get('total_available',0):.0f}m  "
                  f"[{w.get('n_med',0)}med|{w.get('n_mex',0)}T1]  "
                  f"→ {w.get('med_moho_fundable_now',0)} moho now  "
                  f"rating: {r['rating']['label']}")

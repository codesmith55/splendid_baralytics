#!/usr/bin/env python3
"""
positions/meta_log.py — Notable economy event catalog

Declarative threshold catalog for BAR Legion economy milestones.
Detects impressive single attributes AND combinations.

Usage:
    from positions.meta_log import check, summarize, THRESHOLDS

    notables = check(state_dict)
    print(summarize(notables))

Each Notable is a dict:
  {id, label, category, priority, detail, combo}
"""

from __future__ import annotations
from typing import Optional
import math

# ── Threshold catalog ──────────────────────────────────────────────────────────
# Each entry:
#   id        : unique string key
#   check     : callable(s: dict) -> bool   (s is a state_to_dict result)
#   label     : short human-readable label
#   category  : 'energy' | 'income' | 'tech' | 'transition' | 'reclaim' | 'combo'
#   priority  : 'note' | 'good' | 'great' | 'exceptional'
#   detail    : f-string callable (s) -> str for context  (optional)
#   combo     : list of threshold IDs this combines (for combo entries)

def _t(m): return m * 60   # minutes → seconds


THRESHOLDS = [

    # ── Energy milestones ─────────────────────────────────────────────────────

    {
        'id': 'wind_25',
        'check': lambda s: s.get('n_wind', 0) >= 25,
        'label': '25+ wind: fast tech threshold',
        'category': 'energy',
        'priority': 'great',
        'detail': lambda s: f"{s['n_wind']} wind turbines",
    },
    {
        'id': 'wind_10_early',
        'check': lambda s: s.get('n_wind', 0) >= 10 and s.get('t', 999) < _t(6),
        'label': '10+ wind by 6 min: strong wind opener',
        'category': 'energy',
        'priority': 'good',
        'detail': lambda s: f"{s['n_wind']} wind at {s['t']//60:.0f}:{s['t']%60:02.0f}",
    },
    {
        'id': 't2_threshold_fast',
        'check': lambda s: s.get('t2_ready', False) and s.get('t', 999) < _t(7),
        'label': 'T2 energy threshold before 7 min: fast tech',
        'category': 'tech',
        'priority': 'great',
        'detail': lambda s: f"e_net={s['e_net']:.0f} at {s['t']//60:.0f}:{s['t']%60:02.0f}",
    },
    {
        'id': 't2_threshold_eco',
        'check': lambda s: s.get('t2_ready', False) and _t(7) <= s.get('t', 0) < _t(9),
        'label': 'T2 energy threshold 7–9 min: eco pace tech',
        'category': 'tech',
        'priority': 'good',
        'detail': lambda s: f"e_net={s['e_net']:.0f} at {s['t']//60:.0f}:{s['t']%60:02.0f}",
    },
    {
        'id': 't2_threshold_late',
        'check': lambda s: s.get('t2_ready', False) and s.get('t', 0) >= _t(9),
        'label': 'T2 energy threshold 9+ min: late/heavy eco',
        'category': 'tech',
        'priority': 'note',
        'detail': lambda s: f"e_net={s['e_net']:.0f} at {s['t']//60:.0f}:{s['t']%60:02.0f}",
    },

    # ── Income milestones ─────────────────────────────────────────────────────

    {
        'id': 'm_inc_20_early',
        'check': lambda s: s.get('m_inc', 0) >= 20 and s.get('t', 999) < _t(8),
        'label': '20+ m/s income before 8 min: exceptional eco',
        'category': 'income',
        'priority': 'exceptional',
        'detail': lambda s: f"{s['m_inc']:.2f} m/s at {s['t']//60:.0f}:{s['t']%60:02.0f}",
    },
    {
        'id': 'm_inc_15_7min',
        'check': lambda s: s.get('m_inc', 0) >= 15 and s.get('t', 999) < _t(7),
        'label': '15+ m/s income before 7 min: very strong eco',
        'category': 'income',
        'priority': 'great',
        'detail': lambda s: f"{s['m_inc']:.2f} m/s at {s['t']//60:.0f}:{s['t']%60:02.0f}",
    },
    {
        'id': 'med_5_early',
        'check': lambda s: s.get('n_med', 0) >= 5 and s.get('t', 999) < _t(9),
        'label': '5 medmex before 9 min: strong medmex pace',
        'category': 'income',
        'priority': 'good',
        'detail': lambda s: f"{s['n_med']} med at {s['t']//60:.0f}:{s['t']%60:02.0f}",
    },
    {
        'id': 'med_5_fast',
        'check': lambda s: s.get('n_med', 0) >= 5 and s.get('t', 999) < _t(7.5),
        'label': '5 medmex before 7:30: race eco pace',
        'category': 'income',
        'priority': 'great',
        'detail': lambda s: f"{s['n_med']} med at {s['t']//60:.0f}:{s['t']%60:02.0f}",
    },

    # ── T2 transition wealth ──────────────────────────────────────────────────

    {
        'id': 't2_rich_entry',
        'check': lambda s: (s.get('t2_ready', False) and
                            (s.get('liquid', s.get('metal', 0)) > 2000)),
        'label': '2000m+ liquid at T2: rich T2 entry',
        'category': 'transition',
        'priority': 'great',
        'detail': lambda s: f"{s.get('liquid', s.get('metal',0)):.0f}m liquid",
    },
    {
        'id': 't2_rich_total',
        'check': lambda s: (s.get('t2_ready', False) and
                            (s.get('total_reclaim', 0) + s.get('metal', 0)) > 3000),
        'label': '3000m+ total reclaimable at T2: elite T2 entry',
        'category': 'transition',
        'priority': 'exceptional',
        'detail': lambda s: f"total={s.get('total_reclaim',0)+s.get('metal',0):.0f}m",
    },
    {
        'id': 'high_solar_reclaim',
        'check': lambda s: s.get('reclaim_solar', 0) > 1000,
        'label': '1000m+ reclaimable solar: large BP loan outstanding',
        'category': 'reclaim',
        'priority': 'note',
        'detail': lambda s: f"{s.get('n_solar',0)} solars = {s.get('reclaim_solar',0):.0f}m",
    },
    {
        'id': 'med_slot_value',
        'check': lambda s: s.get('n_med', 0) >= 4,
        'label': '4+ medmex slots: major T2 upgrade value',
        'category': 'reclaim',
        'priority': 'good',
        'detail': lambda s: (
            f"{s['n_med']} med slots = {s['n_med']*300}m reclaim "
            f"-> {s['n_med']}x 340m moho upgrades (71.9s ROI each)"
        ),
    },

    # ── Combo thresholds ──────────────────────────────────────────────────────

    {
        'id': 'fast_tech_wind_income',
        'combo': ['wind_25', 'm_inc_15_7min'],
        'check': lambda s: (s.get('n_wind', 0) >= 25 and
                            s.get('m_inc', 0) >= 15 and
                            s.get('t', 999) < _t(7)),
        'label': 'Fast tech + strong income: wind-eco hybrid race',
        'category': 'combo',
        'priority': 'exceptional',
        'detail': lambda s: (
            f"{s['n_wind']} wind + {s['m_inc']:.1f} m/s "
            f"at {s['t']//60:.0f}:{s['t']%60:02.0f}"
        ),
    },
    {
        'id': 'rich_med_t2',
        'combo': ['t2_threshold_fast', 'med_5_fast'],
        'check': lambda s: (s.get('t2_ready', False) and
                            s.get('n_med', 0) >= 4 and
                            s.get('t', 999) < _t(8)),
        'label': 'Fast T2 + 4+ medmex: optimal upgrade path setup',
        'category': 'combo',
        'priority': 'exceptional',
        'detail': lambda s: (
            f"T2 ready + {s['n_med']} med slots at {s['t']//60:.0f}:{s['t']%60:02.0f} "
            f"-> {s['n_med']}x 71.9s ROI moho upgrades"
        ),
    },
    {
        'id': 'solar_reclaim_ready',
        'combo': ['high_solar_reclaim', 't2_threshold_fast'],
        'check': lambda s: (s.get('t2_ready', False) and
                            s.get('reclaim_solar', 0) > 500 and
                            s.get('n_med', 0) >= 3),
        'label': 'T2 + large solar pool: reclaim funds moho upgrades',
        'category': 'combo',
        'priority': 'great',
        'detail': lambda s: (
            f"{s.get('reclaim_solar',0):.0f}m solar + {s['n_med']} med slots "
            f"= {s.get('reclaim_solar',0) + s['n_med']*300:.0f}m reclaimable"
        ),
    },
]

# Build an index for O(1) lookup
_THRESHOLD_INDEX = {t['id']: t for t in THRESHOLDS}


# ── Check function ─────────────────────────────────────────────────────────────

def check(state: dict, prev: Optional[dict] = None) -> list[dict]:
    """
    Run all thresholds against state (plain dict from state_to_dict).
    prev: previous state dict for transition-only events (optional).
    Returns list of fired Notable dicts, priority-sorted (exceptional first).
    """
    PRIORITY_ORDER = {'exceptional': 0, 'great': 1, 'good': 2, 'note': 3}
    fired = []

    for t in THRESHOLDS:
        try:
            if t['check'](state):
                # Transition-only: skip if was already true in prev state
                if prev and t['check'](prev):
                    continue
                detail = t.get('detail')
                fired.append({
                    'id':       t['id'],
                    'label':    t['label'],
                    'category': t['category'],
                    'priority': t['priority'],
                    'combo':    t.get('combo', []),
                    'detail':   detail(state) if detail else '',
                })
        except (KeyError, TypeError, ZeroDivisionError):
            pass

    fired.sort(key=lambda n: PRIORITY_ORDER.get(n['priority'], 9))
    return fired


def check_transition(state: dict, prev: dict) -> list[dict]:
    """
    Only return notables that fired in state but not in prev.
    Use for per-build event streams (avoid re-firing stable flags).
    """
    return check(state, prev)


def summarize(notables: list[dict], prefix: str = '') -> str:
    """
    Format a list of notables as a concise human-readable string.
    One line per notable.
    """
    if not notables:
        return f'{prefix}(no notable milestones)'

    ICONS = {'exceptional': '**', 'great': '* ', 'good': '+ ', 'note': '. '}
    lines = []
    for n in notables:
        icon   = ICONS.get(n['priority'], '  ')
        detail = f'  [{n["detail"]}]' if n.get('detail') else ''
        lines.append(f'{prefix}{icon} [{n["category"]:10s}]  {n["label"]}{detail}')
    return '\n'.join(lines)


# ── Contextual ratings ─────────────────────────────────────────────────────────

def rate_t2_entry(wealth: dict) -> dict:
    """
    Rate a t2_wealth dict against known benchmarks.
    Returns {rating, label, detail}.
    """
    t     = wealth.get('t', 0)
    liq   = wealth.get('liquid', 0)
    total = wealth.get('total_available', 0)
    n_med = wealth.get('n_med', 0)
    e_net = wealth.get('e_net', 0)

    if t < 420 and n_med >= 4 and liq > 1500:
        return {'rating': 'exceptional', 'label': 'elite T2 entry',
                'detail': f'T={t//60:.0f}:{t%60:02.0f}, {n_med} med slots, {liq:.0f}m liquid'}
    elif t < 480 and n_med >= 3 and liq > 1000:
        return {'rating': 'great', 'label': 'strong T2 entry',
                'detail': f'T={t//60:.0f}:{t%60:02.0f}, {n_med} med slots, {liq:.0f}m liquid'}
    elif t < 540 and n_med >= 2:
        return {'rating': 'good', 'label': 'solid T2 entry',
                'detail': f'T={t//60:.0f}:{t%60:02.0f}, {n_med} med slots'}
    elif t >= 540:
        return {'rating': 'late', 'label': 'late T2 entry',
                'detail': f'T={t//60:.0f}:{t%60:02.0f}, heavy eco focus'}
    else:
        return {'rating': 'standard', 'label': 'standard T2 entry',
                'detail': f'T={t//60:.0f}:{t%60:02.0f}'}


# ── CLI quick-check ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys, json
    # Accept a state dict on stdin or as an argument
    if len(sys.argv) > 1:
        s = json.loads(sys.argv[1])
    else:
        s = json.load(sys.stdin)
    notables = check(s)
    print(summarize(notables))
    if not notables:
        print('  State:', {k: s[k] for k in ('t','m_inc','e_net','n_med','n_solar','n_wind') if k in s})

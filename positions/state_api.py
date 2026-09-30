#!/usr/bin/env python3
"""
positions/state_api.py — BAR Legion economy state engine

Pure-function state transitions. JSON-in / JSON-out (HTTP-compatible).
All public api_* functions accept / return plain dicts.

Canonical source for economy constants used by compare.py, navigator.py,
meta_log.py, and live/bar_analytic_server.py - itself resolved from
bar-calc/econ_model.json + the engine unit-def dumps (bar-calc/econ_data.py),
the same files splendid_buildSimulator.js and bar_unified.py read.
`python positions/state_api.py --selftest` checks against bar-calc/parity.json.

State lifecycle:
  state_from_dict(d) → GameState
  apply_action(s, action_id, wind_e) → (new_state, build_seconds)
  roi(s, action_id, wind_e) → dict
  t2_wealth(s) → dict
  notable_check(s, prev=None) → list[Notable]
  state_to_dict(s) → dict
"""

from __future__ import annotations
import math, copy
from dataclasses import dataclass, field
from typing import Optional, Callable

# ── Model constants ────────────────────────────────────────────────────────────
# Every number below is resolved from bar-calc/econ_model.json + the engine
# unit-def dumps it lists (see bar-calc/econ_data.py). The names are kept so
# navigator.py, compare.py, eco_viz.py and bar_analytic_server.py import as before.
# `python positions/state_api.py --selftest` checks them against bar-calc/parity.json.
import os as _os, sys as _sys
_BAR_CALC = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'bar-calc')
if _BAR_CALC not in _sys.path:
    _sys.path.insert(0, _BAR_CALC)
import econ_data as _ED   # noqa: E402

_K = _ED.legion_constants()

SPOT        = _K['SPOT']          # m/s of a x1.0 extractor on the reference spot
T2_MINGEN   = _K['T2_MINGEN']     # E/s net required for T2 factory viability

T1_INC      = _K['T1_INC']        # legmex     (x0.75 calibrated)
MED_INC     = _K['MED_INC']       # legmext15  (x2.0, total slot)
MOHO_INC    = _K['MOHO_INC']      # legmoho    (x4.0)

MED_DELTA       = _K['MED_DELTA']       # T1 -> med delta
MOHO_FROM_T1    = _K['MOHO_FROM_T1']    # T1 -> moho delta
MOHO_FROM_MED   = _K['MOHO_FROM_MED']   # med -> moho delta

T1_E_NET    = _K['T1_E_NET']    # legmex net energy (engine energyUpkeep -7 = produces 7)
MED_E_NET   = _K['MED_E_NET']   # medmex net energy (-30 drain)
MOHO_E_NET  = _K['MOHO_E_NET']  # legmoho net energy (-20 drain)
SOLAR_E     = _K['SOLAR_E']     # E/s per solar panel

MED_SWING   = _K['MED_SWING']   # E/s swing T1->med
MED_UPK     = _K['MED_UPK']     # medmex upkeep (E/s)
MOHO_UPK    = -MOHO_E_NET       # moho upkeep (E/s)
MEX_UPK     = _K['MEX_UPK']     # legmex upkeep (engine: it produces, so 0)
TUR_BP      = _K['TUR_BP']      # legnanotc build power
CON_BP      = _K['CON_BP']      # legck build power

# Unit costs (engine defs: legmex, legmext15, legsolar, legwin, legmoho)
T1_METAL,   T1_E_COST,   T1_BW    = _K['T1_METAL'],   _K['T1_E_COST'],   _K['T1_BW']
MED_METAL,  MED_E_COST,  MED_BW   = _K['MED_METAL'],  _K['MED_E_COST'],  _K['MED_BW']
SOL_METAL,  SOL_E_COST,  SOL_BW   = _K['SOL_METAL'],  _K['SOL_E_COST'],  _K['SOL_BW']
WIND_METAL, WIND_E_COST, WIND_BW  = _K['WIND_METAL'], _K['WIND_E_COST'], _K['WIND_BW']
MOHO_METAL, MOHO_E_COST, MOHO_BW  = _K['MOHO_METAL'], _K['MOHO_E_COST'], _K['MOHO_BW']

# Commander (legcom): passive incomes, energy cap (team base + commander storage), build power
BASE_M, BASE_E, BASE_CAP, COM_BP  = _K['BASE_M'], _K['BASE_E'], _K['BASE_CAP'], _K['COM_BP']
METAL_CAP = _K['METAL_CAP']        # model bank cap for metal (econ_model.json legion.metalCap)

# Reclaim values - 100 % (solar is a BP loan; medmex/mex reclaimed before moho build)
RCL_SOLAR = _K['RCL_SOLAR']
RCL_MED   = _K['RCL_MED']
RCL_T1    = _K['RCL_T1']

# Moho net costs after reclaim of what's underneath
MOHO_NET_FROM_T1  = _K['MOHO_NET_FROM_T1']
MOHO_NET_FROM_MED = _K['MOHO_NET_FROM_MED']

# ── Action definitions ─────────────────────────────────────────────────────────
# Keys used by apply_action, roi, available_actions.
# 'metal'       : net metal cost (after reclaim_before credit)
# 'energy'      : energy cost paid during build
# 'bw'          : build work (wall_s = bw / bp)
# 'dm'          : m_inc delta on completion
# 'de_inc'      : e_inc delta on completion (None = the current wind_e)
# 'de_upk'      : e_upk delta on completion (positive = more drain)
# 'reclaim'     : metal returned to bank BEFORE the build starts
# 'prereq'      : callable(state) -> bool - hard gate, returns False if action unavailable
# 'dn_*'        : unit count deltas on completion
# The table is data: econ_model.json `legion.actions` resolved against the engine defs
# (costs, income deltas from `replaces`, reclaim credits). See econ_data.legion_actions().

def _prereq_fn(req: dict):
    return lambda s: all(getattr(s, k, 0) >= v for k, v in req.items())


ACTIONS: dict[str, dict] = {}
for _aid, _a in _ED.legion_actions().items():
    _entry = {k: v for k, v in _a.items() if k not in ('prereq', 'replaces')}
    if _a.get('prereq'):
        _entry['prereq'] = _prereq_fn(_a['prereq'])
    ACTIONS[_aid] = _entry


# ── GameState ──────────────────────────────────────────────────────────────────

@dataclass
class GameState:
    t:         float = 0.0
    metal:     float = 0.0
    energy:    float = 0.0
    e_cap:     float = BASE_CAP
    m_inc:     float = BASE_M
    e_inc:     float = BASE_E
    e_upk:     float = 0.0
    bp:        int   = COM_BP
    n_mex:     int   = 0
    n_med:     int   = 0
    n_solar:   int   = 0
    n_wind:    int   = 0
    n_moho:    int   = 0
    n_workers: int   = 0
    wind_e:    float = 10.0   # current map wind condition (E/s per turbine)
    m_gen:     float = 0.0    # cumulative metal generated since tracking start
    events:    list  = field(default_factory=list)

    @property
    def e_net(self) -> float:
        return self.e_inc - self.e_upk

    @property
    def reclaim_solar_m(self) -> float:
        return self.n_solar * RCL_SOLAR           # 155m × n_solar

    @property
    def reclaim_med_m(self) -> float:
        return self.n_med * (RCL_MED + RCL_T1)   # 300m × n_med

    @property
    def reclaim_t1_m(self) -> float:
        return self.n_mex * RCL_T1               # 50m × n_mex

    @property
    def total_reclaim_m(self) -> float:
        return self.reclaim_solar_m + self.reclaim_med_m + self.reclaim_t1_m

    @property
    def t2_ready(self) -> bool:
        return self.e_net >= T2_MINGEN

    def tick(self, dt: float) -> None:
        self.m_gen  += self.m_inc * dt
        self.metal   = min(self.metal + self.m_inc * dt, METAL_CAP)
        self.energy  = max(0.0, min(self.energy + self.e_net * dt, self.e_cap))
        self.t      += dt

    def copy(self) -> GameState:
        s = copy.copy(self)
        s.events = list(self.events)
        return s


# ── State conversion ───────────────────────────────────────────────────────────

def state_from_dict(d: dict) -> GameState:
    """
    Build a GameState from a plain dict.
    Accepts both API format and live server snapshot team entries.
    """
    s = GameState()
    s.t          = float(d.get('t',          d.get('gameSeconds', 0)))
    s.metal      = float(d.get('metal',      d.get('metalCurrent', d.get('metal_bank', 0))))
    s.energy     = float(d.get('energy',     d.get('energyCurrent', d.get('energy_bank', 0))))
    s.e_cap      = float(d.get('e_cap',      d.get('energyStorage', BASE_CAP)))
    s.m_inc      = float(d.get('m_inc',      d.get('metalIncome', BASE_M)))
    s.n_mex      = int(d.get('n_mex',        d.get('nMex', 0)))
    s.n_med      = int(d.get('n_med',        0))
    s.n_solar    = int(d.get('n_solar',      0))
    s.n_wind     = int(d.get('n_wind',       0))
    s.n_moho     = int(d.get('n_moho',       0))
    s.n_workers  = int(d.get('n_workers',    d.get('nConv', 0)))
    s.wind_e     = float(d.get('wind_e',     d.get('wind', 10.0)) or 10.0)
    s.bp         = int(d.get('bp',           d.get('bpAvail', COM_BP)))
    s.m_gen      = float(d.get('m_gen',      0))

    # Reconstruct e_inc / e_upk from e_net if only e_net is provided
    if 'e_net' in d and 'e_inc' not in d:
        # Estimate upkeep from mex counts; gross income = e_net + upkeep
        # T1 mex: e_inc += T1_E_NET (no upkeep); medmex: e_upk += MED_UPK; moho: e_upk += MOHO_UPK
        estimated_upk = s.n_med * MED_UPK + s.n_moho * MOHO_UPK
        s.e_upk = estimated_upk
        s.e_inc = float(d['e_net']) + estimated_upk
    else:
        s.e_inc  = float(d.get('e_inc', BASE_E))
        s.e_upk  = float(d.get('e_upk', 0))

    return s


def state_to_dict(s: GameState) -> dict:
    """Serialize a GameState to a JSON-compatible dict."""
    return {
        't':            round(s.t, 1),
        'metal':        round(s.metal, 1),
        'energy':       round(s.energy, 1),
        'e_cap':        round(s.e_cap),
        'm_inc':        round(s.m_inc, 3),
        'e_net':        round(s.e_net, 1),
        'e_inc':        round(s.e_inc, 1),
        'e_upk':        round(s.e_upk, 1),
        'bp':           s.bp,
        'n_mex':        s.n_mex,
        'n_med':        s.n_med,
        'n_solar':      s.n_solar,
        'n_wind':       s.n_wind,
        'n_moho':       s.n_moho,
        'n_workers':    s.n_workers,
        'wind_e':       s.wind_e,
        'm_gen':        round(s.m_gen, 1),
        't2_ready':     s.t2_ready,
        'reclaim_solar':round(s.reclaim_solar_m),
        'reclaim_med':  round(s.reclaim_med_m),
        'reclaim_t1':   round(s.reclaim_t1_m),
        'total_reclaim':round(s.total_reclaim_m),
        'liquid':       round(s.metal + s.reclaim_solar_m),
    }


# ── Core transition engine ─────────────────────────────────────────────────────

def _build_time(s: GameState, action_id: str, wind_e: float) -> tuple[float, float]:
    """
    Estimate (total_wall_s, stall_s) for an action from state s.
    stall_s = energy accumulation wait before build can proceed.
    Does not mutate s.
    """
    a        = ACTIONS[action_id]
    net_cost = a['metal']
    e_cost   = a['energy']
    bw       = a['bw']
    bp       = max(s.bp, 1)

    # Metal wait (if bank is short)
    m_wait   = max(0.0, (net_cost - s.metal) / max(s.m_inc, 0.001))

    # Energy stall: can we accumulate e_cost by the time build finishes?
    full_t   = bw / bp
    avail_e  = s.energy + s.e_net * (m_wait + full_t)
    if avail_e >= e_cost or e_cost == 0:
        stall = 0.0
    elif s.e_net <= 0:
        stall = 999.0
    else:
        stall = max(0.0, (e_cost - avail_e) / s.e_net)

    return m_wait + full_t + stall, stall


def apply_action(s: GameState, action_id: str,
                 wind_e: Optional[float] = None) -> tuple[GameState, float]:
    """
    Apply action_id to state s. Returns (new_state, wall_seconds).
    Does NOT mutate s — returns a fresh copy.
    wind_e overrides s.wind_e for wind turbines.
    """
    a     = ACTIONS[action_id]
    eff_wind = wind_e if wind_e is not None else s.wind_e
    ns    = s.copy()

    # Metal wait
    if ns.metal < a['metal']:
        wait = max(0.0, (a['metal'] - ns.metal) / max(ns.m_inc, 0.001))
        ns.tick(wait)

    # Reclaim credit (returned before build starts)
    ns.metal = min(ns.metal + a.get('reclaim', 0), METAL_CAP)

    # Spend net metal
    ns.metal -= a['metal']
    ns.metal  = max(0.0, ns.metal)

    # Stall + build time
    wall_t, stall = _build_time(s, action_id, eff_wind)
    ns.tick(a['bw'] / max(ns.bp, 1) + stall)
    ns.energy = max(0.0, ns.energy - a['energy'])

    # Apply completion effects
    ns.m_inc  += a.get('dm', 0)
    ns.e_upk  += a.get('de_upk', 0)
    de_inc     = eff_wind if a.get('de_inc') is None else a.get('de_inc', 0)
    ns.e_inc  += de_inc

    for field, delta in a.items():
        if field.startswith('dn_') and isinstance(delta, int):
            attr = field[3:]     # 'solar', 'wind', 'mex', 'med', 'moho', 'workers'
            attr = f'n_{attr}'
            setattr(ns, attr, getattr(ns, attr, 0) + delta)

    ns.events.append({
        't': round(ns.t, 1), 'action': action_id,
        'stall': round(stall, 1), 'label': a['label'],
        'm_inc': round(ns.m_inc, 3), 'e_net': round(ns.e_net, 1),
    })
    return ns, wall_t


# ── ROI calculation ────────────────────────────────────────────────────────────

def roi(s: GameState, action_id: str,
        wind_e: Optional[float] = None) -> dict:
    """
    Return ROI analysis for a given action from state s.

    energy_norm_cost: extra metal to build/reclaim solar to cover the E/s swing.
      Negative = energy improves → credit (equivalent to reclaiming solar).
    effective_cost: net_metal + energy_norm_cost.
    roi_s: effective_cost / income_gain — seconds to recoup investment.
    """
    a        = ACTIONS[action_id]
    eff_wind = wind_e if wind_e is not None else s.wind_e

    dm       = a.get('dm', 0)
    de_inc   = eff_wind if a.get('de_inc') is None else a.get('de_inc', 0)
    de_upk   = a.get('de_upk', 0)
    e_delta  = de_inc - de_upk   # net E/s change (positive = better)

    net_metal = a['metal']

    # Solar normalization: convert E/s swing to metal cost
    # Positive e_delta = energy improves → credit (can reclaim solar)
    # Negative e_delta = energy worsens → need to build solar to cover
    solar_norm_cost = -(e_delta / SOLAR_E) * SOL_METAL   # negative e_delta → positive cost
    effective_cost  = net_metal + solar_norm_cost

    wall_s, stall_s = _build_time(s, action_id, eff_wind)

    roi_s = (effective_cost / dm) if dm > 0 else float('inf')

    return {
        'action':          action_id,
        'label':           a['label'],
        'net_metal':       round(net_metal),
        'income_gain':     round(dm, 3),
        'e_delta':         round(e_delta, 1),
        'solar_norm_cost': round(solar_norm_cost),
        'effective_cost':  round(effective_cost),
        'roi_s':           round(roi_s, 1),
        'build_wall_s':    round(wall_s, 1),
        'stall_s':         round(stall_s, 1),
        'prereq_met':      _prereq_met(s, action_id),
        'affordable':      s.metal >= net_metal,
    }


def _prereq_met(s: GameState, action_id: str) -> bool:
    fn = ACTIONS[action_id].get('prereq')
    return fn(s) if fn else True


def available_actions(s: GameState) -> list[str]:
    """Actions whose prerequisites are currently satisfied."""
    return [aid for aid in ACTIONS if _prereq_met(s, aid)]


# ── T2 transition wealth ───────────────────────────────────────────────────────

def t2_wealth(s: GameState) -> dict:
    """
    Compute T2 entry wealth: all metal available for moho upgrades,
    including reclaimable structures. Call at (or after) T2 threshold.
    """
    liquid  = s.metal + s.reclaim_solar_m
    total   = liquid + s.reclaim_med_m + s.reclaim_t1_m

    # How many mohos immediately fundable from liquid + solar reclaim?
    med_fundable = min(s.n_med,
                       int(liquid // MOHO_NET_FROM_MED) if MOHO_NET_FROM_MED > 0 else s.n_med)
    t1_fundable  = min(s.n_mex,
                       int(liquid // MOHO_NET_FROM_T1)  if MOHO_NET_FROM_T1  > 0 else s.n_mex)

    return {
        't':               round(s.t),
        't2_ready':        s.t2_ready,
        'e_net':           round(s.e_net, 1),
        'm_inc':           round(s.m_inc, 3),

        # Current metal
        'metal_bank':      round(s.metal),

        # Reclaimable pools
        'reclaim_solar':   round(s.reclaim_solar_m),      # 155m × n_solar
        'reclaim_med':     round(s.reclaim_med_m),        # 300m × n_med
        'reclaim_t1':      round(s.reclaim_t1_m),         # 50m × n_mex

        # Aggregates
        'liquid':          round(liquid),                  # bank + solar
        'total_available': round(total),                   # bank + solar + all slots

        # Upgrade economics (energy-normalized ROI via roi())
        'n_med':           s.n_med,
        'n_mex':           s.n_mex,
        'n_moho':          s.n_moho,
        'moho_net_from_med': MOHO_NET_FROM_MED,
        'moho_net_from_t1':  MOHO_NET_FROM_T1,
        'roi_med_moho_s':  roi(s, 'upgrade_med_moho')['roi_s'],  # ~71.9s (energy norm)
        'roi_t1_moho_s':   roi(s, 'upgrade_t1_moho' )['roi_s'],  # ~134.7s (energy norm)

        # Immediately fundable (from liquid alone)
        'med_moho_fundable_now': med_fundable,
        't1_moho_fundable_now':  t1_fundable,

        # Energy note: net E/s change of each upgrade (engine deltas)
        'e_gain_per_med_moho': (ACTIONS['upgrade_med_moho']['de_inc'] or 0) - ACTIONS['upgrade_med_moho']['de_upk'],
        'e_cost_per_t1_moho':  -((ACTIONS['upgrade_t1_moho']['de_inc'] or 0) - ACTIONS['upgrade_t1_moho']['de_upk']),
    }


# ── Forward projection ─────────────────────────────────────────────────────────

def project_to_t2(s: GameState,
                  strategy_fn: Callable,
                  wind_e: Optional[float] = None,
                  t_limit: float = 840.0) -> tuple[GameState, list]:
    """
    Simulate strategy_fn forward until T2_MINGEN is reached or t_limit.
    Returns (state_at_t2_or_end, event_log).
    """
    eff_wind = wind_e if wind_e is not None else s.wind_e
    ns       = s.copy()
    events   = []
    t2_snap  = None

    while ns.t < s.t + t_limit:
        if ns.t2_ready and t2_snap is None:
            t2_snap = state_to_dict(ns)
            t2_snap['wealth'] = t2_wealth(ns)
            events.append({'type': 't2_threshold', 'snap': t2_snap})
            break

        action_id = strategy_fn(ns, eff_wind)
        if action_id is None:
            ns.tick(5.0)
            continue

        if not _prereq_met(ns, action_id):
            ns.tick(5.0)
            continue

        a = ACTIONS[action_id]
        m_wait  = max(0.0, (a['metal'] - ns.metal) / max(ns.m_inc, 0.001))
        bt_est, _ = _build_time(ns, action_id, eff_wind)
        if ns.t + m_wait + bt_est > s.t + t_limit + 10:
            ns.tick(s.t + t_limit - ns.t)
            break

        ns, _ = apply_action(ns, action_id, eff_wind)
        events.append(ns.events[-1])

    if t2_snap is None and ns.t2_ready:
        t2_snap = state_to_dict(ns)
        t2_snap['wealth'] = t2_wealth(ns)
        events.append({'type': 't2_threshold', 'snap': t2_snap})

    return ns, events


# ── API wrappers (dict in/out) ─────────────────────────────────────────────────

def api_state(params: dict) -> dict:
    """Convert a param dict to a full state dict (all derived fields included)."""
    return state_to_dict(state_from_dict(params))


def api_roi(params: dict) -> dict:
    """
    params: state fields + 'action' (action_id) + optional 'wind_e'
    Returns ROI analysis for that action from that state.
    """
    action_id = params.get('action')
    if not action_id or action_id not in ACTIONS:
        return {'error': f'Unknown action: {action_id!r}. Available: {list(ACTIONS)}'}
    s       = state_from_dict(params)
    wind_e  = params.get('wind_e')
    return roi(s, action_id, wind_e)


def api_all_roi(params: dict) -> dict:
    """
    params: state fields + optional 'wind_e'
    Returns ROI for all available actions, sorted by roi_s (best first).
    """
    s       = state_from_dict(params)
    wind_e  = params.get('wind_e')
    results = [roi(s, aid, wind_e) for aid in available_actions(s)]
    results.sort(key=lambda r: r['roi_s'])
    return {'state': state_to_dict(s), 'options': results}


def api_t2_wealth(params: dict) -> dict:
    """
    params: state fields.
    Returns T2 entry wealth report.
    """
    return t2_wealth(state_from_dict(params))


def api_available_actions(params: dict) -> dict:
    """Returns list of available action IDs and their ROI from this state."""
    s      = state_from_dict(params)
    wind_e = params.get('wind_e')
    return {
        'available': available_actions(s),
        'roi': {aid: roi(s, aid, wind_e) for aid in available_actions(s)},
    }


# ── Parity selftest ────────────────────────────────────────────────────────────

def selftest(tol: float = 1e-6) -> bool:
    """Compare the resolved constants + ACTIONS with bar-calc/parity.json (written by
    `python bar-calc/bar_unified.py --write-parity`)."""
    import json
    if not _os.path.exists(_ED.PARITY_PATH):
        print('no parity file; run: python bar-calc/bar_unified.py --write-parity')
        return False
    with open(_ED.PARITY_PATH, encoding='utf-8') as f:
        want = json.load(f)['legion']
    bad = []
    g = globals()
    for k, v in want['constants'].items():
        have = g.get(k)
        if have is None or not isinstance(v, (int, float)) or abs(float(have) - v) > tol * max(1.0, abs(v)):
            bad.append((f'constants.{k}', v, have))
    for aid, a in want['actions'].items():
        mine = ACTIONS.get(aid)
        if mine is None:
            bad.append((f'actions.{aid}', 'present', 'missing'))
            continue
        for k, v in a.items():
            if k in ('prereq', 'replaces'):
                continue
            have = mine.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                ok = have is not None and abs(float(have) - v) <= tol * max(1.0, abs(v))
            else:
                ok = have == v
            if not ok:
                bad.append((f'actions.{aid}.{k}', v, have))
    for aid in ACTIONS:
        if aid not in want['actions']:
            bad.append((f'actions.{aid}', 'missing', 'present'))
    print(f"state_api: {len(ACTIONS)} actions, BASE_E={BASE_E:g} BASE_CAP={BASE_CAP:g} T1_INC={T1_INC:.4f} "
          f"SOL_BW={SOL_BW:g} WIND_METAL={WIND_METAL:g}")
    for k, v, h in bad[:30]:
        print(f'  x {k}: parity {v!r}  state_api {h!r}')
    print('selftest OK' if not bad else f'selftest FAILED ({len(bad)} differences)')
    return not bad


if __name__ == '__main__':
    if hasattr(_sys.stdout, 'reconfigure'):
        _sys.stdout.reconfigure(encoding='utf-8')
    if '--selftest' in _sys.argv:
        _sys.exit(0 if selftest() else 1)
    import json as _json
    print(_json.dumps({aid: {k: v for k, v in a.items() if k != 'prereq'} for aid, a in ACTIONS.items()}, indent=1))

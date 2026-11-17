#!/usr/bin/env python3
"""
positions/aberrant_log.py  —  Aberrant economy event detector + chat context

Detects resource cheats, sudden income spikes, and builder losses from the
live economy state stream (extra_stat_update events).  For each event, reads
the BAR infolog for chat ± WINDOW_S seconds as potential player explanations.

Detection sources (field deltas between consecutive extra_stat_update polls):
  metal_spike    — metalCurrent jumps > METAL_SPIKE_M above expected income
  energy_spike   — energyCurrent jumps > ENERGY_SPIKE_E above expected regen
  income_spike   — metalIncome jumps > INCOME_JUMP_MS without new mexes
  workers_gained — nConv increases > CONV_SPAWN_N (possible /give workers)
  mexes_gained   — nMex increases > MEX_SPAWN_N (possible /give mex)
  builder_loss   — nConv decreases (self-destruct or unexpected death)

Chat context: reads BAR infolog at INFOLOG_PATH, returns lines from channels
  CHATALL, CHATTEAM, CHATALLYTEAM, CHATSPEC, and map tag labels within
  ± window_s seconds of the event's game time.

HTTP-ready: all public functions are dict-in / dict-out.
"""

from __future__ import annotations
import os, re, threading, time, uuid
from typing import Optional

# ── Detection thresholds ───────────────────────────────────────────────────────

METAL_SPIKE_M   = 400.0   # net metal jump > this after income credit → likely /atm or /give metal
ENERGY_SPIKE_E  = 4000.0  # energy jump > this in one poll cycle
INCOME_JUMP_MS  = 50.0    # m_inc jump > this without proportional new mexes
CONV_SPAWN_N    = 3       # nConv increases by > this in one tick → possible /give workers
MEX_SPAWN_N     = 5       # nMex increases by > this → possible /give mex

DEFAULT_WINDOW_S = 30.0   # ± seconds of chat to collect around each event

# ── BAR file paths ─────────────────────────────────────────────────────────────

_BAR_DATA    = "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data"
INFOLOG_PATH = os.path.join(_BAR_DATA, "infolog.txt")

# Chat line: [  123.456] CHATALL: PlayerName: message text
# Handles both CHATALL and CHATALLYTEAM, map tag labels, etc.
_CHAT_RE = re.compile(
    r'^\[\s*(\d+(?:\.\d+)?)\]\s*'
    r'(CHATALL|CHATTEAM|CHATALLYTEAM|CHATSPEC|CHATSPC|TAG|MAPLABEL|CHATLOBBY)'
    r'\s*:?\s*(.+)$',
    re.IGNORECASE,
)

# Game-start line in infolog — used to offset timestamps to game-relative seconds
# BAR logs GameID: at game start; timestamps AFTER this line are game-seconds
_GAME_START_RE = re.compile(
    r'^\[\s*(\d+(?:\.\d+)?)\]\s*(?:GameID:|SPRING\s+GAME\s+STARTED|Game\s+started)',
    re.IGNORECASE,
)

# ── Event type catalog ─────────────────────────────────────────────────────────

ABERRANT_TYPES: dict[str, dict] = {
    # ── Resource cheats (high severity) ───────────────────────────────────────
    'metal_spike': {
        'label':       'Metal spike',
        'description': 'Metal increased far above expected income (possible /atm or /give metal)',
        'severity':    'high',
        'icon':        '[M+]',
    },
    'energy_spike': {
        'label':       'Energy spike',
        'description': 'Energy increased far above normal regen (possible /atm or /give energy)',
        'severity':    'high',
        'icon':        '[E+]',
    },
    'income_spike': {
        'label':       'Income spike',
        'description': 'Metal income jumped without proportional new mexes (possible /give mex or script)',
        'severity':    'medium',
        'icon':        '[I+]',
    },
    'workers_gained': {
        'label':       'Workers gained',
        'description': 'Builder count increased sharply in one tick (possible /give workers)',
        'severity':    'medium',
        'icon':        '[W+]',
    },
    'mexes_gained': {
        'label':       'Mexes gained',
        'description': 'Mex count increased sharply in one tick (possible /give mex)',
        'severity':    'medium',
        'icon':        '[X+]',
    },
    # ── Builder-level events (low/log severity) ───────────────────────────────
    'builder_loss': {
        'label':       'Builder lost',
        'description': 'Builder count decreased (self-destruct, reclaim, or unexpected death)',
        'severity':    'low',
        'icon':        '[W-]',
    },
    # ── Engine-level unit events (log severity — valid gameplay, not suspicious) ──
    'self_reclaim': {
        'label':       'Self-reclaim',
        'description': 'Player reclaimed one of their own live units (weaponDefID=-12)',
        'severity':    'log',
        'icon':        '[R]',
    },
    'self_destruct': {
        'label':       'Self-destruct',
        'description': 'Player self-destructed a unit (weaponDefID=-1, D-key)',
        'severity':    'log',
        'icon':        '[D]',
    },
    'tpv_drop_reclaim': {
        'label':       'TPV drop + metal gain (heuristic)',
        'description': 'totalValue dropped but storageValue rose — likely self-reclaim (confirmed by self_reclaim event if present)',
        'severity':    'log',
        'icon':        '[R?]',
    },
}


# ── Core detector ──────────────────────────────────────────────────────────────

def check_aberrant(prev: dict, curr: dict) -> list[dict]:
    """
    Compare two consecutive extra_stat_update events (raw widget fields or
    _team_state dicts).  Returns a list of aberrant event dicts; empty if none.

    Accepted field names (either raw widget or _team_state format):
      metal       : metalCurrent  / metal
      energy      : energyCurrent / energy
      m_inc       : metalIncome   / m_inc
      e_inc       : energyIncome  / e_inc
      n_mex       : nMex          / n_mex
      n_workers   : nConv         / n_workers
      frame       : frame         (raw only; game_s = frame/30)
      t           : t             (_team_state only, game seconds)
    """

    def _f(ev, *keys) -> Optional[float]:
        for k in keys:
            v = ev.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return None

    p_metal  = _f(prev, 'metalCurrent',  'metal')
    c_metal  = _f(curr, 'metalCurrent',  'metal')
    p_energy = _f(prev, 'energyCurrent', 'energy')
    c_energy = _f(curr, 'energyCurrent', 'energy')
    p_m_inc  = _f(prev, 'metalIncome',   'm_inc')
    c_m_inc  = _f(curr, 'metalIncome',   'm_inc')
    p_n_mex  = _f(prev, 'nMex',          'n_mex')
    c_n_mex  = _f(curr, 'nMex',          'n_mex')
    p_n_conv = _f(prev, 'nConv',         'n_workers')
    c_n_conv = _f(curr, 'nConv',         'n_workers')

    # Game time: prefer frame/30, fall back to 't' field
    frame  = _f(curr, 'frame') or 0
    game_s = frame / 30.0 if frame else (_f(curr, 't') or 0.0)
    team_id = curr.get('teamID', curr.get('team_id', curr.get('team', 0)))

    events: list[dict] = []

    def _ev(atype: str, detail: str, delta=None) -> None:
        meta = ABERRANT_TYPES[atype]
        events.append({
            'id':          uuid.uuid4().hex[:8],
            'type':        atype,
            'label':       meta['label'],
            'icon':        meta['icon'],
            'severity':    meta['severity'],
            'description': meta['description'],
            'detail':      detail,
            'delta':       delta,
            'game_s':      round(game_s, 1),
            'frame':       int(frame),
            'team_id':     team_id,
            'explanation': '',       # blank — player fills in via /api/aberrant/explain
            'wall_time':   time.time(),
            # chat_context populated lazily by AberrantStore.all_with_context()
        })

    # ── Metal spike: net increase above expected income ──────────────────────
    if p_metal is not None and c_metal is not None:
        delta_m  = c_metal - p_metal
        expected = (p_m_inc or 0) * 2.5   # ≈2–3s between polls at max
        net_spike = delta_m - expected
        if net_spike > METAL_SPIKE_M:
            _ev('metal_spike',
                f'metal {p_metal:.0f} -> {c_metal:.0f}  (+{delta_m:.0f}m, net spike ~{net_spike:.0f}m)',
                delta=round(net_spike, 1))

    # ── Energy spike ─────────────────────────────────────────────────────────
    if p_energy is not None and c_energy is not None:
        delta_e = c_energy - p_energy
        if delta_e > ENERGY_SPIKE_E:
            _ev('energy_spike',
                f'energy {p_energy:.0f} -> {c_energy:.0f}  (+{delta_e:.0f}e)',
                delta=round(delta_e, 1))

    # ── Income spike: income jump unexplained by new mexes ───────────────────
    if (p_m_inc is not None and c_m_inc is not None
            and p_n_mex is not None and c_n_mex is not None):
        d_inc = c_m_inc - p_m_inc
        d_mex = c_n_mex - p_n_mex
        unexplained = d_inc - d_mex * 2.5   # ~2.5 m/s per new mex at worst
        if unexplained > INCOME_JUMP_MS:
            _ev('income_spike',
                f'm_inc {p_m_inc:.1f} -> {c_m_inc:.1f} m/s  (+{d_inc:.1f}), new mex: {d_mex:+.0f}',
                delta=round(unexplained, 1))

    # ── Builder count changes ─────────────────────────────────────────────────
    if p_n_conv is not None and c_n_conv is not None:
        d_conv = c_n_conv - p_n_conv
        if d_conv > CONV_SPAWN_N:
            _ev('workers_gained',
                f'builders {p_n_conv:.0f} -> {c_n_conv:.0f}  (+{d_conv:.0f})',
                delta=int(d_conv))
        elif d_conv < 0:
            _ev('builder_loss',
                f'builders {p_n_conv:.0f} -> {c_n_conv:.0f}  ({d_conv:+.0f})',
                delta=int(d_conv))

    # ── Mex count spike ──────────────────────────────────────────────────────
    if p_n_mex is not None and c_n_mex is not None:
        d_mex = c_n_mex - p_n_mex
        if d_mex > MEX_SPAWN_N:
            _ev('mexes_gained',
                f'mexes {p_n_mex:.0f} -> {c_n_mex:.0f}  (+{d_mex:.0f})',
                delta=int(d_mex))

    # ── TPV drop + storage gain (self-reclaim heuristic) ─────────────────────
    # totalValue = sum of all unit/building metal-equivalent values
    # storageValue = metalCurrent + energyCurrent/70
    # If totalValue drops but storageValue rises, a unit was converted back to metal
    p_tv = _f(prev, 'totalValue')
    c_tv = _f(curr, 'totalValue')
    p_sv = _f(prev, 'storageValue')
    c_sv = _f(curr, 'storageValue')
    if p_tv is not None and c_tv is not None and p_sv is not None and c_sv is not None:
        d_tv = c_tv - p_tv    # negative = units/buildings lost
        d_sv = c_sv - p_sv    # positive = metal bank grew
        # Reclaim signature: meaningful unit loss AND simultaneous metal gain
        # (combat loss also drops totalValue but storageValue wouldn't rise from it)
        if d_tv < -50.0 and d_sv > 15.0:
            _ev('tpv_drop_reclaim',
                f'totalValue {p_tv:.0f} -> {c_tv:.0f} ({d_tv:+.0f}m), '
                f'storage {p_sv:.0f} -> {c_sv:.0f} ({d_sv:+.0f}m)',
                delta=round(d_sv, 1))

    return events


# ── Engine-level unit event detector ─────────────────────────────────────────

# Spring/BAR weaponDefID constants (engine-internal, not user-defined weapons)
WEAPON_RECLAIM    = -12   # builder reclaimed a live unit
WEAPON_SELFDEST   = -1    # unit self-destructed (D-key) or died to generic damage


def check_unit_event(ev: dict, unit_info: Optional[dict] = None) -> list[dict]:
    """
    Check a single unit_killed event for notable reclaim/self-destruct actions.

    ev        : unit_killed event dict from the JSONL stream
                Required fields: unitID, teamID, attackerTeam, weaponDefID, frame, defName
    unit_info : pre-fetched unit def info {defName, metalCost, value, bucket}
                (from the unit_defs cache in Live); pass {} or None if unavailable

    Returns a list of event dicts (empty if nothing notable).
    """
    if unit_info is None:
        unit_info = {}

    wid      = ev.get('weaponDefID')
    team_id  = ev.get('teamID')
    atk_team = ev.get('attackerTeam')
    frame    = ev.get('frame', 0) or 0
    game_s   = frame / 30.0
    def_name = unit_info.get('defName') or ev.get('defName', '?')
    metal    = unit_info.get('metalCost', unit_info.get('value', 0)) or 0
    bucket   = unit_info.get('bucket', '?')

    if wid is None or team_id is None:
        return []

    events: list[dict] = []

    def _ev(atype: str, detail: str) -> None:
        meta = ABERRANT_TYPES[atype]
        events.append({
            'id':          uuid.uuid4().hex[:8],
            'type':        atype,
            'label':       meta['label'],
            'icon':        meta['icon'],
            'severity':    meta['severity'],
            'description': meta['description'],
            'detail':      detail,
            'delta':       -metal,   # metal recovered (approximate)
            'game_s':      round(game_s, 1),
            'frame':       int(frame),
            'team_id':     team_id,
            'unit_id':     ev.get('unitID'),
            'def_name':    def_name,
            'metal_value': metal,
            'bucket':      bucket,
            'explanation': '',
            'wall_time':   time.time(),
        })

    if wid == WEAPON_RECLAIM and atk_team == team_id:
        _ev('self_reclaim',
            f'reclaimed own {def_name}  ({bucket}, ~{metal:.0f}m metal returned)')

    elif wid == WEAPON_SELFDEST and atk_team == team_id:
        _ev('self_destruct',
            f'self-destructed own {def_name}  ({bucket}, ~{metal:.0f}m lost)')

    return events


# ── Total player value utility ────────────────────────────────────────────────

def total_player_value(stat_ev: dict) -> float:
    """
    Total metal-equivalent value a player controls.
      = totalValue (all unit/building metalCost+energyCost/70)
      + storageValue (metalCurrent + energyCurrent/70)

    Both fields are produced by extra_stat_update; totalPlayerValue is now
    also emitted directly by the widget but this function works on older data too.
    """
    tv = stat_ev.get('totalPlayerValue')
    if tv is not None:
        return float(tv)
    return (float(stat_ev.get('totalValue', 0) or 0) +
            float(stat_ev.get('storageValue', 0) or 0))


# ── BAR infolog chat parser ───────────────────────────────────────────────────

def _parse_infolog(path: str) -> tuple[Optional[float], list[tuple[float, str, str]]]:
    """
    Read the BAR infolog and return:
      (game_start_t, [(timestamp_s, channel, text), ...])

    game_start_t: infolog timestamp of the GameID line (marks game clock zero),
                  or None if not found (times are used as-is).
    timestamp_s:  raw infolog timestamp — subtract game_start_t to get game-seconds.
    channel:      normalised to CHATALL / CHATTEAM / CHATALLYTEAM / CHATSPEC / TAG
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            lines = fh.readlines()
    except OSError:
        return None, []

    game_start_t: Optional[float] = None
    chat: list[tuple[float, str, str]] = []

    for line in lines:
        line = line.rstrip()

        if game_start_t is None:
            m = _GAME_START_RE.match(line)
            if m:
                game_start_t = float(m.group(1))
                continue

        m = _CHAT_RE.match(line)
        if m:
            t_raw = float(m.group(1))
            channel = m.group(2).upper()
            # Normalise aliases
            if channel in ('CHATSPC', 'CHATLOBBY'):
                channel = 'CHATSPEC'
            text = m.group(3).strip()
            chat.append((t_raw, channel, text))

    return game_start_t, chat


def load_chat_context(
        game_s: float,
        window_s: float = DEFAULT_WINDOW_S,
        infolog_path: str = INFOLOG_PATH,
) -> list[dict]:
    """
    Return chat lines within ±window_s of game_s from the BAR infolog.

    Each entry:
      game_s    — game-relative seconds (raw_t - game_start_t, or raw_t if start unknown)
      channel   — CHATALL / CHATTEAM / CHATALLYTEAM / CHATSPEC / TAG
      text      — full message text
      offset_s  — seconds relative to the event (negative = before, positive = after)
    """
    game_start_t, chat = _parse_infolog(infolog_path)

    results: list[dict] = []
    for raw_t, channel, text in chat:
        t = raw_t - game_start_t if game_start_t is not None else raw_t
        offset = t - game_s
        if -window_s <= offset <= window_s:
            results.append({
                'game_s':   round(t, 1),
                'channel':  channel,
                'text':     text,
                'offset_s': round(offset, 1),
            })

    return sorted(results, key=lambda x: x['game_s'])


# ── In-memory aberrant event store ────────────────────────────────────────────

class AberrantStore:
    """
    Thread-safe store for aberrant events detected in the live game stream.
    Chat context is populated lazily on first call to all_with_context().
    """

    MAX_EVENTS = 500

    def __init__(self, infolog_path: str = INFOLOG_PATH, window_s: float = DEFAULT_WINDOW_S):
        self._lock     = threading.Lock()
        self._events:  list[dict] = []
        self._infolog  = infolog_path
        self._window_s = window_s

    def add(self, ev: dict) -> None:
        """Append a detected event (no chat context yet — fetched lazily)."""
        with self._lock:
            self._events.append(dict(ev))
            if len(self._events) > self.MAX_EVENTS:
                self._events = self._events[-self.MAX_EVENTS:]

    def add_explanation(self, event_id: str, explanation: str) -> bool:
        """Attach an explanation string to an event by id. Returns True if found."""
        with self._lock:
            for ev in self._events:
                if ev.get('id') == event_id:
                    ev['explanation'] = explanation
                    return True
        return False

    def all_with_context(
            self,
            team_id: Optional[int] = None,
            limit: int = 50,
            window_s: Optional[float] = None,
    ) -> list[dict]:
        """
        Return recent events with chat_context populated.
        chat_context is cached on the stored event after first fetch.
        """
        ws = window_s if window_s is not None else self._window_s
        with self._lock:
            evs = list(self._events)   # refs to originals

        if team_id is not None:
            evs = [e for e in evs if e.get('team_id') == team_id]
        evs = evs[-limit:]

        result = []
        for ev in evs:
            # Populate chat_context on original (idempotent) — outside lock for IO
            if 'chat_context' not in ev:
                ev['chat_context'] = load_chat_context(ev['game_s'], ws, self._infolog)
            result.append(dict(ev))   # return a copy
        return result

    def clear(self) -> None:
        """Clear all events (call on game reset)."""
        with self._lock:
            self._events.clear()

    def summary(self) -> dict:
        """Return event counts by type and severity."""
        from collections import Counter
        with self._lock:
            evs = list(self._events)
        by_type = dict(Counter(e['type'] for e in evs))
        by_sev  = dict(Counter(e['severity'] for e in evs))
        return {'by_type': by_type, 'by_severity': by_sev, 'total': len(evs)}


# ── CLI quick-test ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import json

    # Simulate an /atm event: metal jumps 1000m in one poll
    prev = {'metalCurrent': 200, 'energyCurrent': 500, 'metalIncome': 8.0,
            'energyIncome': 50, 'nMex': 4, 'nConv': 3, 'frame': 9000, 'teamID': 0}
    curr = {'metalCurrent': 1200, 'energyCurrent': 10500, 'metalIncome': 8.0,
            'energyIncome': 50, 'nMex': 4, 'nConv': 3, 'frame': 9060, 'teamID': 0}

    events = check_aberrant(prev, curr)
    print(f'Detected {len(events)} aberrant event(s):')
    for ev in events:
        print(f'  [{ev["icon"]}] {ev["label"]}  @{ev["game_s"]:.0f}s  severity={ev["severity"]}')
        print(f'      {ev["detail"]}')
        chat = load_chat_context(ev['game_s'])
        if chat:
            print(f'      Chat context ({len(chat)} lines):')
            for c in chat:
                print(f'        [{c["offset_s"]:+.0f}s {c["channel"]}] {c["text"]}')
        else:
            print(f'      (no infolog chat context — {INFOLOG_PATH})')

    # Worker self-destruct
    prev2 = dict(prev, nConv=3, frame=10800)
    curr2 = dict(curr, metalCurrent=400, energyCurrent=600, nConv=2, frame=10860)
    for ev in check_aberrant(prev2, curr2):
        print(f'  [{ev["icon"]}] {ev["label"]}  severity={ev["severity"]}  {ev["detail"]}')

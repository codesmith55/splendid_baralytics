"""
BAR Worker Count Optimization — Full Resource Thread

The full tension:
  - Each worker costs 110M + 1600E + 23s factory time
  - That worker then generates 80 BP/s toward wind
  - But that 1600E could have built 9 winds (1600/175)
  - The 110M is reclaimable later (metal battery)
  - The factory is 500M locked up — eating it frees metal for wind
  - Energy overflow when metal-stalling → econverters (70E→1M/s)

Sweep: for each worker count, factory is eaten immediately after last unit.
Lazarus eats solars during wind phase, then eats lab when factory stops.
Econverters built when energy overflows and metal is full.
"""

WORKER   = {'m': 110, 'e': 1600, 'bt': 3450, 'bp': 80,  'passive_e': 7}
LAZ      = {'m': 130, 'e': 1400, 'bt': 2800, 'bp': 200}
WIND     = {'m': 40,  'e': 175,  'bt': 1600, 'e_out': 11.9}
SOLAR    = {'m': 155, 'e': 0,    'bt': 2600, 'e_out': 20}
ESTOR    = {'m': 170, 'e': 1700, 'bt': 4100, 'e_cap': 6000}
ECONVERT = {'m': 1,   'e': 1150, 'bt': 2600, 'e_drain': 70, 'm_out': 1}
FACTORY  = {'m': 500, 'e': 950,  'bt': 5000, 'bp': 150}

T2LAB    = {'m': 2600, 'e': 15000, 'bt': 25000, 'bp': 600}
T2CON    = {'m': 430,  'e': 6900,  'bt': 12500, 'bp': 210}
T2MEX    = {'m': 620,  'e': 7700,  'bt': 14900}

COM_BP = 300; COM_E = 30; COM_M = 2
MEX_UPKEEP = 3; MEX_VALUE = 2.0; BUILD_DELAY = 1

N_EXPAND_MEX = 2; N_LAZ = 2; N_SOLARS_INIT = 5

# MEX_WALK_TIME used to be a flat guess (45s). Derive it from the calibrated
# distance model when available. NOTE: this models EXPANSION mexes, which are
# farther out than the 3 starting spots (those sit inside the commander's build
# range, ~0 walk). MEX_EXPAND_DISTANCE_SQUARES is the one value to measure off
# your map for the spots you actually expand to; 5 squares is a placeholder
# estimate. Falls back to 45s if bar_distance isn't importable.
MEX_EXPAND_DISTANCE_SQUARES = 5.0  # TODO: measure real expansion distance off map
try:
    import bar_distance
    MEX_WALK_TIME = bar_distance.mex_walk_time(
        "commander", n_mex=N_EXPAND_MEX,
        distance_squares=MEX_EXPAND_DISTANCE_SQUARES)
except ImportError:
    MEX_WALK_TIME = 45
MAP_RECLAIM_M = 522
LAB_GAME_T = 99; COM_AVAIL_T = 135
TARGET_WIND = 25
TOTAL_MEX = 7


def e_rate(bp, unit):
    return (bp / unit['bt']) * unit['e'] if unit['e'] else 0

def m_rate(bp, unit):
    return (bp / unit['bt']) * unit['m'] if unit['m'] else 0


def simulate(n_max_workers, verbose=False, external_metal=None):
    """
    external_metal: list of (game_time_seconds, metal_amount) injections.
    """
    if external_metal is None:
        external_metal = []
    metal_injections = {int(t): m for t, m in external_metal}

    metal = 300.0; energy = 500.0
    m_cap = 1000.0; e_cap = 1000.0 + N_SOLARS_INIT * 50

    n_winds = 0; n_solars = N_SOLARS_INIT; n_estor = 0; n_econvert = 0
    n_workers = 0; n_laz = 0; n_mex_taken = 0
    factory_alive = True; lab_reclaimed = False
    solars_reclaimed = 0; workers_reclaimed = 0

    builders = {'Com': {'bp': COM_BP, 'avail': COM_AVAIL_T, 'rem': 0, 'proj': None}}

    # Factory
    fact_producing = None; fact_prog = 0
    fact_done = False  # True once all units produced → signal to eat

    # Production queue: mex workers first, then interleave laz + workers
    prod_queue = []
    w, l = 0, 0
    for _ in range(min(N_EXPAND_MEX, n_max_workers)):
        prod_queue.append('w'); w += 1
    for _ in range(N_LAZ):
        prod_queue.append('l'); l += 1
    while w < n_max_workers:
        prod_queue.append('w'); w += 1
    prod_idx = 0

    # Lazarus
    laz_rock_rem = 0; laz_rock_rate = 0
    laz_eat_prog = 0

    # Phases
    phase = 'build'  # 'build' (wind+workers), 't2lab', 't2con', 't2mex'
    t2lab_prog = 0; t2con_prog = 0; t2mex_prog = 0
    t2_start = None; t2lab_done = None; t2con_done = None
    wind25_t = None

    # Track energy spent on workers vs wind
    e_spent_workers = 0; e_spent_wind = 0; m_spent_workers = 0

    for tick in range(LAB_GAME_T, 700):
        # ── Income ──
        m_inc = TOTAL_MEX * MEX_VALUE + COM_M
        e_inc = (n_winds * WIND['e_out'] + n_solars * SOLAR['e_out'] + COM_E
                 + n_workers * WORKER['passive_e'])
        e_up = TOTAL_MEX * MEX_UPKEEP

        # Converters: activate when energy > 80% cap
        conv_e = 0
        if n_econvert > 0 and energy > e_cap * 0.8:
            conv_e = n_econvert * ECONVERT['e_drain']
            m_inc += n_econvert * ECONVERT['m_out']

        metal += m_inc; energy += (e_inc - e_up - conv_e)
        metal = max(0, min(metal, m_cap))
        energy = max(0, min(energy, e_cap))

        # External metal injection (allies, bonus reclaim)
        if tick in metal_injections:
            bonus = metal_injections[tick]
            metal = min(metal + bonus, m_cap)
            if verbose: print(f"  [{tick}s] $$ External metal: +{bonus:.0f}M (now {metal:.0f}M)")

        # Laz#1 map reclaim
        if laz_rock_rem > 0:
            gain = min(laz_rock_rate, laz_rock_rem)
            laz_rock_rem -= gain
            metal = min(metal + gain, m_cap)
            if laz_rock_rem <= 0 and verbose:
                print(f"  [{tick}s] ★ Laz#1 map reclaim done (+{MAP_RECLAIM_M}M)")

        # Laz#2+ eats structures: solars first, then lab (when factory done)
        if n_laz >= 2 and phase == 'build':
            eat_bp = (n_laz - 1) * LAZ['bp']
            if n_solars > 0:
                laz_eat_prog += eat_bp / SOLAR['bt']
                if laz_eat_prog >= 1.0:
                    laz_eat_prog -= 1.0
                    n_solars -= 1; solars_reclaimed += 1
                    metal = min(metal + SOLAR['m'], m_cap); e_cap -= 50
                    if verbose: print(f"  [{tick}s] ★ Laz ate solar ({n_solars} left, +{SOLAR['m']}M)")
            elif fact_done and factory_alive:
                laz_eat_prog += eat_bp / FACTORY['bt']
                if laz_eat_prog >= 1.0:
                    factory_alive = False; lab_reclaimed = True
                    metal = min(metal + FACTORY['m'], m_cap)
                    laz_eat_prog = 0
                    if verbose: print(f"  [{tick}s] ★ Laz ate lab (+{FACTORY['m']}M)")

        # ── Factory production ──
        if factory_alive and not fact_done:
            if fact_producing is None and prod_idx < len(prod_queue):
                utype = prod_queue[prod_idx]
                fact_producing = utype
                fact_prog = 0
                if utype == 'w' and n_workers == 0 and tick < COM_AVAIL_T:
                    fact_producing = 'w_assist'

            if fact_producing:
                if fact_producing == 'w_assist':
                    bp = FACTORY['bp'] + COM_BP; unit = WORKER
                elif fact_producing == 'w':
                    bp = FACTORY['bp']; unit = WORKER
                else:
                    bp = FACTORY['bp']; unit = LAZ

                ed = e_rate(bp, unit); md = m_rate(bp, unit)
                s = 1.0
                if ed > 0 and energy < ed: s = min(s, max(0, energy/ed))
                if md > 0 and metal < md: s = min(s, max(0, metal/md))
                energy -= ed*s; metal -= md*s
                if 'w' in fact_producing:
                    e_spent_workers += ed*s; m_spent_workers += md*s
                fact_prog += (bp / unit['bt']) * s

                if fact_prog >= 1.0:
                    prod_idx += 1
                    if 'w' in fact_producing:
                        n_workers += 1; lbl = f'W{n_workers}'
                        if n_mex_taken < N_EXPAND_MEX:
                            n_mex_taken += 1
                            avail = tick + MEX_WALK_TIME
                            if verbose: print(f"  [{tick}s] ★ {lbl} → mex (avail {avail}s)")
                        else:
                            avail = tick + BUILD_DELAY
                            if verbose: print(f"  [{tick}s] ★ {lbl} → wind")
                        builders[lbl] = {'bp': WORKER['bp'], 'avail': avail, 'rem': 0, 'proj': None}
                        e_cap += 50
                    else:
                        n_laz += 1
                        if n_laz == 1:
                            laz_rock_rem = MAP_RECLAIM_M
                            laz_rock_rate = MAP_RECLAIM_M / 240.0
                            if verbose: print(f"  [{tick}s] ★ Laz#1 → rocks ({MAP_RECLAIM_M}M)")
                        else:
                            laz_eat_prog = 0
                            if verbose: print(f"  [{tick}s] ★ Laz#{n_laz} → eat structures")
                    fact_producing = None; fact_prog = 0

                    # Check if factory is done producing
                    if prod_idx >= len(prod_queue):
                        fact_done = True
                        if verbose: print(f"  [{tick}s]   Factory done ({n_workers}w {n_laz}l). Laz will eat it.")

        # ══════════════════════════════════
        # BUILD PHASE: wind + estor + econvert
        # ══════════════════════════════════
        if phase == 'build':
            metal_full = metal > m_cap * 0.85
            energy_high = energy > e_cap * 0.7

            for lbl, b in builders.items():
                if tick < b['avail']: continue
                if fact_producing == 'w_assist' and lbl == 'Com': continue

                if b['rem'] <= 0:
                    # Decision: what to build next
                    if n_estor < 2 and n_winds >= 12 and metal >= ESTOR['m'] and energy >= ESTOR['e']:
                        b['rem'] = ESTOR['bt'] / b['bp'] + BUILD_DELAY
                        b['proj'] = 'estor'
                    elif metal_full and energy_high and n_econvert < 3 and n_solars == 0:
                        # Overflow: build econverter
                        b['rem'] = ECONVERT['bt'] / b['bp'] + BUILD_DELAY
                        b['proj'] = 'econvert'
                    else:
                        b['rem'] = WIND['bt'] / b['bp'] + BUILD_DELAY
                        b['proj'] = 'wind'

                proj = b['proj']
                if proj == 'wind': unit = WIND
                elif proj == 'estor': unit = ESTOR
                elif proj == 'econvert': unit = ECONVERT
                else: unit = WIND

                ed = e_rate(b['bp'], unit); md = m_rate(b['bp'], unit)
                s = 1.0
                if ed > 0 and energy < ed: s = min(s, max(0, energy/ed))
                if md > 0 and metal < md: s = min(s, max(0, metal/md))
                energy -= ed*s; metal -= md*s
                if proj == 'wind': e_spent_wind += ed*s
                b['rem'] -= s

                if b['rem'] <= 0:
                    if proj == 'wind':
                        n_winds += 1
                        if n_winds == TARGET_WIND and wind25_t is None:
                            wind25_t = tick
                    elif proj == 'estor':
                        n_estor += 1; e_cap += ESTOR['e_cap']
                    elif proj == 'econvert':
                        n_econvert += 1

            # Transition to T2 when 25 wind reached
            if n_winds >= TARGET_WIND:
                phase = 't2lab'; t2_start = tick
                bp = sum(b['bp'] for b in builders.values() if tick >= b['avail'])
                if verbose:
                    print(f"  [{tick}s] → T2 Lab. {n_winds}W {n_estor}E {n_econvert}C."
                          f" BP={bp}. M={metal:.0f} E={energy:.0f}")

        # ══════════════════════════════════
        # T2 LAB: all BP, eat workers when metal low
        # ══════════════════════════════════
        elif phase == 't2lab':
            active = {l: b for l, b in builders.items() if tick >= b['avail']}
            bp = sum(b['bp'] for b in active.values())
            ed = e_rate(bp, T2LAB); md = m_rate(bp, T2LAB)
            s = 1.0
            if ed > 0 and energy < ed: s = min(s, max(0, energy/ed))
            if md > 0 and metal < md: s = min(s, max(0, metal/md))
            energy -= ed*s; metal -= md*s
            t2lab_prog += (bp / T2LAB['bt']) * s

            # Laz continues eating structures during T2 lab
            if n_laz >= 2:
                eat_bp = n_laz * LAZ['bp']  # all lazarus now (rocks may be done)
                if n_solars > 0:
                    laz_eat_prog += eat_bp / SOLAR['bt']
                    if laz_eat_prog >= 1.0:
                        laz_eat_prog -= 1.0
                        n_solars -= 1; solars_reclaimed += 1
                        metal = min(metal + SOLAR['m'], m_cap); e_cap -= 50
                elif factory_alive:
                    laz_eat_prog += eat_bp / FACTORY['bt']
                    if laz_eat_prog >= 1.0:
                        factory_alive = False; lab_reclaimed = True
                        metal = min(metal + FACTORY['m'], m_cap); laz_eat_prog = 0

            # Eat workers when metal low (keep 1 for T2 mex)
            eatable = [l for l in active if l.startswith('W')]
            if metal < 80 and len(eatable) > 1:
                victim = eatable[-1]
                del builders[victim]
                n_workers -= 1; workers_reclaimed += 1
                metal = min(metal + WORKER['m'], m_cap); e_cap -= 50
                if verbose: print(f"  [{tick}s] ★ Ate {victim} (+{WORKER['m']}M)")

            if t2lab_prog >= 1.0:
                phase = 't2con'; t2lab_done = tick
                rem_w = sum(1 for l in builders if l.startswith('W'))
                if verbose:
                    print(f"  [{tick}s] ★ T2 Lab done. Ate {workers_reclaimed}w."
                          f" {rem_w}w remain. All assist T2 Con.")

        # ══════════════════════════════════
        # T2 CON: lab 600 + builders assist
        # ══════════════════════════════════
        elif phase == 't2con':
            assist = sum(b['bp'] for b in builders.values() if tick >= b['avail'])
            total_bp = T2LAB['bp'] + assist
            ed = e_rate(total_bp, T2CON); md = m_rate(total_bp, T2CON)
            s = 1.0
            if ed > 0 and energy < ed: s = min(s, max(0, energy/ed))
            if md > 0 and metal < md: s = min(s, max(0, metal/md))
            energy -= ed*s; metal -= md*s
            t2con_prog += (total_bp / T2CON['bt']) * s

            # Keep eating workers if metal low
            eatable = [l for l in builders if l.startswith('W')]
            if metal < 80 and len(eatable) > 0:
                victim = eatable[-1]
                del builders[victim]
                n_workers -= 1; workers_reclaimed += 1
                metal = min(metal + WORKER['m'], m_cap); e_cap -= 50
                if verbose: print(f"  [{tick}s] ★ Ate {victim} (+{WORKER['m']}M)")

            if t2con_prog >= 1.0:
                phase = 't2mex'; t2con_done = tick
                mbp = sum(b['bp'] for b in builders.values() if tick >= b['avail'])
                if verbose:
                    print(f"  [{tick}s] ★ T2 Con done ({total_bp:.0f}BP). Given away."
                          f" {mbp}BP → T2 Mex")

        # ══════════════════════════════════
        # T2 MEX: builders only
        # ══════════════════════════════════
        elif phase == 't2mex':
            bp = sum(b['bp'] for b in builders.values() if tick >= b['avail'])
            ed = e_rate(bp, T2MEX); md = m_rate(bp, T2MEX)
            s = 1.0
            if ed > 0 and energy < ed: s = min(s, max(0, energy/ed))
            if md > 0 and metal < md: s = min(s, max(0, metal/md))
            energy -= ed*s; metal -= md*s
            t2mex_prog += (bp / T2MEX['bt']) * s

            if t2mex_prog >= 1.0:
                return tick, {
                    'n_workers_total': n_workers + workers_reclaimed,
                    'n_laz': n_laz, 'n_winds': n_winds,
                    'n_solars': n_solars, 'n_estor': n_estor,
                    'n_econvert': n_econvert,
                    'solars_eaten': solars_reclaimed,
                    'lab_eaten': lab_reclaimed,
                    'workers_eaten': workers_reclaimed,
                    'workers_surviving': n_workers,
                    't2_start': t2_start, 't2lab_done': t2lab_done,
                    't2con_done': t2con_done, 't2mex_done': tick,
                    'wind25_t': wind25_t,
                    'e_on_workers': e_spent_workers,
                    'e_on_wind': e_spent_wind,
                    'm_on_workers': m_spent_workers,
                    'fact_done_at': None,  # tracked below
                }

    return 700, {'failed': True, 'n_winds': n_winds, 'n_workers_total': n_workers + workers_reclaimed}


def run_sweep(label, external_metal=None, verbose_best=True):
    """Run worker sweep for a given external metal scenario."""
    ext_desc = "none"
    if external_metal:
        ext_desc = " + ".join(f"{m:.0f}M@{t}s" for t, m in external_metal)

    print(f"\n{'═' * 78}")
    print(f"  {label}")
    print(f"  External metal: {ext_desc}")
    print(f"{'═' * 78}")

    print(f"\n  {'Wkr':>3} {'Wnd':>3} {'ESt':>3} {'ECv':>3}"
          f" {'Eaten':>8} {'25W@':>5} {'T2@':>5}"
          f" {'Lab':>5} {'Con':>4} {'Mex':>4}"
          f" {'TOTAL':>7} {'Δ':>6}")
    print("  " + "─" * 70)

    results = []
    for nw in range(2, 11):
        t, b = simulate(nw, external_metal=external_metal)
        results.append((nw, t, b))
        if b.get('failed'):
            print(f"  {nw:>3} {'FAILED':>60} ({b.get('n_winds',0)}W)")
            continue

        d = ""
        if len(results) >= 2 and not results[-2][2].get('failed'):
            d = f"{t - results[-2][1]:>+5.0f}s"

        tl = b['t2lab_done'] - b['t2_start'] if b.get('t2lab_done') and b.get('t2_start') else 0
        tc = b['t2con_done'] - b['t2lab_done'] if b.get('t2con_done') and b.get('t2lab_done') else 0
        tm = b['t2mex_done'] - b['t2con_done'] if b.get('t2mex_done') and b.get('t2con_done') else 0
        ate = f"{b.get('solars_eaten',0)}s{b.get('workers_eaten',0)}w{'L' if b.get('lab_eaten') else ''}"

        print(f"  {nw:>3} {b['n_winds']:>3} {b['n_estor']:>3} {b.get('n_econvert',0):>3}"
              f" {ate:>8} {b.get('wind25_t',0):>4.0f}s"
              f" {b.get('t2_start',0):>4.0f}s"
              f" {tl:>4.0f}s {tc:>3.0f}s {tm:>3.0f}s"
              f" {t:>6.0f}s {d}")

    valid = [(nw, t, b) for nw, t, b in results if not b.get('failed')]
    if not valid:
        print("\n  All failed!"); return None

    best_nw, best_t, best_b = min(valid, key=lambda x: x[1])
    b = best_b

    print(f"\n  ★ OPTIMUM: {best_nw} workers → T2 mex at {best_t:.0f}s ({best_t/60:.1f} min)")
    print(f"    Eaten: {b.get('workers_eaten',0)}w + {b.get('solars_eaten',0)} sol"
          f" + {'lab' if b.get('lab_eaten') else '—'}."
          f" Surviving: {b.get('workers_surviving',0)}w → {b.get('workers_surviving',0)*80+300}BP on T2 mex")

    if verbose_best:
        print(f"\n  ── Trace ({best_nw} workers) ──")
        simulate(best_nw, verbose=True, external_metal=external_metal)

    return best_nw, best_t, best_b


def main():
    print("═" * 78)
    print("  FULL-THREAD WORKER OPTIMIZATION — External Metal Scenarios")
    print("═" * 78)
    print("""
  How does bonus metal (ally gifts, extra reclaim) change the answer?
  With more metal arriving during T2 lab, fewer workers need to be eaten,
  leaving more BP on T2 mex (faster finish).
""")

    # Baseline
    r0 = run_sweep("BASELINE — No External Metal")

    # +500M at 5:00
    r1 = run_sweep("+500M at 5:00 (300s)", external_metal=[(300, 500)])

    # +500M at 5:00 and +500M at 6:00
    r2 = run_sweep("+500M at 5:00 + 500M at 6:00", external_metal=[(300, 500), (360, 500)])

    # Comparison
    print(f"\n{'═' * 78}")
    print(f"  COMPARISON")
    print(f"{'═' * 78}")
    print(f"  {'Scenario':<35} {'Workers':>7} {'Total':>7} {'T2Mex BP':>9} {'Δ vs base':>10}")
    print("  " + "─" * 70)

    scenarios = [
        ("Baseline", r0),
        ("+500M @ 5:00", r1),
        ("+500M @ 5:00 + 6:00", r2),
    ]
    base_t = r0[1] if r0 else 0
    for label, r in scenarios:
        if r is None:
            print(f"  {label:<35} {'FAILED':>30}")
        else:
            nw, t, b = r
            surv = b.get('workers_surviving', 0)
            mex_bp = surv * 80 + 300
            delta = f"{t - base_t:>+5.0f}s" if base_t else ""
            print(f"  {label:<35} {nw:>7} {t:>6.0f}s {mex_bp:>8} BP {delta}")

    if r0 and r2:
        diff = r0[1] - r2[1]
        print(f"\n  1000M external metal saves {diff:.0f}s ({diff/60:.1f} min)")
        print(f"  That's {diff/r0[1]*100:.1f}% faster.")


if __name__ == '__main__':
    main()

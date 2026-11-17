// reclaim-breakeven.mjs — energy break-even for reclaiming one eco building to fund another
//
// Question it answers: "I reclaim a solar (155 M, 20 E/s) to unlock metal for otherwise-idle
// build power, and spend that metal on winds (40 M + 175 E each). The winds out-produce the
// solar eventually — but I paid 175 E each AND gave up 20 E/s in the meantime. How many
// seconds after the reclaim finishes until I'm net energy-positive vs. having done nothing?"
//
// CLI:
//   node planner/reclaim-breakeven.mjs                       # solar -> wind, bp=1060, wind=10
//   node planner/reclaim-breakeven.mjs --bp=1060 --wind=15
//   node planner/reclaim-breakeven.mjs --from=solar --to=wind --sweep
//   node planner/reclaim-breakeven.mjs --json
//
// Flags:
//   --from=KEY        unit reclaimed (units.json key)              default solar
//   --to=KEY          unit built with the metal                    default wind
//   --bp=N            build power available to build the `to` units  default 1060
//   --reclaim-bp=N    build power doing the reclaim                default = --bp
//   --wind=N          avg E/s of the `to` unit (overrides units.json energyIncome)
//   --yield=F         fraction of metal returned by reclaim         default 1.0
//   --sweep           table of break-even vs wind speed / vs BP
//   --json            machine-readable output
//
// MODEL (t = 0 at the moment the reclaim COMPLETES)
//   Until the reclaim finishes the old building is still alive and still producing, so the
//   energy accounts of "reclaim it" and "leave it" are identical — the clock only starts when
//   the building dies. Reclaim wall-time is reported separately as an opportunity-cost note.
//
//   delta  d  = BW_to / BP                    seconds per replacement unit at full BP
//   count  n  = yield * M_from / M_to         units the freed metal buys
//   build  Tb = n * d                         total build time (all BP on the job)
//   drain     = E_to / d = BP * E_to / BW_to  E/s burned while building (BP-proportional!)
//   deficit D = E_from*Tb + n*E_to - (income earned by units that finished early)
//   surplus R = n*W - E_from                  steady-state E/s gain once all are up
//   BREAK-EVEN  tau = Tb + D / R              (undefined if R <= 0 — never pays off)
//
//   Two build schedules bound reality:
//     parallel — all BP smeared over all n units, nothing online until Tb (worst case)
//     serial   — full BP on one unit at a time, unit k online at k*d, income ramps (best case)
//   Real play with several builders sits between them.
//
//   HARD FLOOR: as BP -> inf, Tb -> 0 and tau -> n*E_to / (n*W - E_from). Build time barely
//   matters; the sunk E_to per unit dominates. More build power cannot rescue a bad swap.
//
// The numeric simulation is the authority; the closed form is printed beside it and must agree.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const UNITS = JSON.parse(fs.readFileSync(path.join(here, 'data', 'units.json'), 'utf8')).units;

const DT = 0.005;      // sim step (s)
const HORIZON = 1800;  // give up after 30 min of game time

// ── core ─────────────────────────────────────────────────────────────────────

/**
 * Simulate cumulative energy delta vs. the do-nothing baseline (keep the old building).
 * Returns the break-even second, the worst debt reached, and the debt curve's shape.
 *
 * schedule: 'serial' (one unit at a time, full BP) | 'parallel' (all at once, all finish at Tb)
 * fractional: credit the leftover metal as a partial unit producing frac*W from Tb onward.
 */
function simulate({ Efrom, Eto, Mto, BWto, W, metal, bp, schedule, fractional }) {
    const nRaw = metal / Mto;
    const n = fractional ? nRaw : Math.floor(nRaw);
    if (n <= 0) return { n, impossible: 'not enough metal for even one unit' };

    const d = BWto / bp;          // seconds per unit at full BP
    const Tb = n * d;             // total build time
    const drain = Eto / d;        // E/s while a unit is under construction at full BP
    const R = n * W - Efrom;      // steady-state surplus

    // online(t) -> how many units' worth of income is live at time t
    const online = (t) => {
        if (schedule === 'parallel') return t >= Tb ? n : 0;
        if (t >= Tb) return n;
        return Math.min(Math.floor(t / d), n);   // serial: unit k lands at k*d
    };
    // spendRate(t) -> E/s of construction draw
    const spend = (t) => (t < Tb ? drain : 0);

    let cum = 0, worst = 0, worstAt = 0, breakEven = null;
    for (let t = 0; t < HORIZON; t += DT) {
        const rate = online(t) * W - spend(t) - Efrom;   // vs. baseline (old building's Efrom)
        cum += rate * DT;
        if (cum < worst) { worst = cum; worstAt = t; }
        if (breakEven === null && cum >= 0 && t > 0) { breakEven = t + DT; break; }
    }

    // closed form, same schedule
    const earlyIncome = schedule === 'serial' ? W * d * (n * (n - 1)) / 2 : 0;
    const D = Efrom * Tb + n * Eto - earlyIncome;
    const closed = R > 0 ? Tb + D / R : null;

    return {
        n, unitsWhole: Math.floor(nRaw), leftoverMetal: metal - Math.floor(nRaw) * Mto,
        buildTime: Tb, secondsPerUnit: d, drainRate: drain,
        buildCost: n * Eto, carryCost: Efrom * Tb, deficit: D,
        surplusRate: R, breakEven, closedForm: closed,
        peakDebt: -worst, peakDebtAt: worstAt,
        floorBp: R > 0 ? (n * Eto) / R : null,   // tau as BP -> infinity
        newIncome: n * W, oldIncome: Efrom,
    };
}

function analyze(opts) {
    const from = UNITS[opts.from], to = UNITS[opts.to];
    if (!from) throw new Error(`unknown --from unit '${opts.from}' (see planner/data/units.json)`);
    if (!to) throw new Error(`unknown --to unit '${opts.to}'`);

    const metal = from.metal * opts.yield;
    const W = opts.wind ?? to.energyIncome ?? 0;
    const base = { Efrom: from.energyIncome ?? 0, Eto: to.energy, Mto: to.metal, BWto: to.buildWork, W, metal, bp: opts.bp };

    const cases = {};
    for (const schedule of ['serial', 'parallel'])
        for (const [tag, fractional] of [['fractional', true], ['whole', false]])
            cases[`${schedule}/${tag}`] = simulate({ ...base, schedule, fractional });

    return {
        from: opts.from, to: opts.to,
        metalFreed: metal, windAssumed: W, bp: opts.bp,
        reclaimSeconds: from.buildWork / opts.reclaimBp,
        neverPaysBelowWind: (from.energyIncome ?? 0) / (metal / to.metal),  // W below this => R<=0
        cases,
    };
}

// ── output ───────────────────────────────────────────────────────────────────

const f = (x, d = 1) => (x === null || x === undefined || !isFinite(x) ? '  never' : x.toFixed(d));

function report(a, opts) {
    const L = [];
    L.push(`\nRECLAIM ${a.from.toUpperCase()} -> BUILD ${a.to.toUpperCase()}    bp=${a.bp}   ${a.to} output=${a.windAssumed} E/s`);
    L.push('='.repeat(78));
    const u = UNITS[a.from], v = UNITS[a.to];
    L.push(`  give up : ${u.metal} M building making ${u.energyIncome} E/s  (reclaim takes ${f(a.reclaimSeconds, 1)} s at ${opts.reclaimBp} BP)`);
    L.push(`  buy     : ${a.metalFreed} M / ${v.metal} M = ${(a.metalFreed / v.metal).toFixed(3)} x ${a.to}  @ ${v.energy} E + ${v.buildWork} BW each`);
    L.push('');

    const rows = [
        ['serial/fractional', 'serial, leftover metal credited'],
        ['serial/whole', 'serial, whole units only'],
        ['parallel/fractional', 'parallel, leftover credited'],
        ['parallel/whole', 'parallel, whole units only'],
    ];
    L.push('  schedule                          n     build   E spent   peak debt   +E/s    BREAK-EVEN');
    L.push('  ' + '-'.repeat(88));
    for (const [key, label] of rows) {
        const c = a.cases[key];
        if (c.impossible) { L.push(`  ${label.padEnd(32)}  ${c.impossible}`); continue; }
        L.push('  ' + label.padEnd(32) +
            `${c.n.toFixed(2).padStart(5)}` +
            `${f(c.buildTime, 1).padStart(9)}s` +
            `${f(c.buildCost, 0).padStart(9)}` +
            `${f(c.peakDebt, 0).padStart(12)}` +
            `${(c.surplusRate > 0 ? '+' + f(c.surplusRate, 2) : f(c.surplusRate, 2)).padStart(9)}` +
            `${f(c.breakEven, 1).padStart(11)}s`);
    }

    const ref = a.cases['serial/fractional'];
    L.push('');
    L.push(`  closed form check (serial/fractional): ${f(ref.closedForm, 1)}s  vs sim ${f(ref.breakEven, 1)}s`);
    L.push(`  construction draw while building     : ${f(ref.drainRate, 1)} E/s  (= bp * ${v.energy} / ${v.buildWork})`);
    L.push(`  break-even floor at infinite BP      : ${f(ref.floorBp, 1)}s  <- build time is NOT the lever`);
    L.push(`  income swap                          : ${f(ref.oldIncome, 0)} E/s guaranteed -> ${f(ref.newIncome, 1)} E/s variable`);
    if (a.neverPaysBelowWind > 0)
        L.push(`  never pays off if ${a.to} output <= ${f(a.neverPaysBelowWind, 2)} E/s`);
    return L.join('\n');
}

function sweep(opts) {
    const L = ['', 'BREAK-EVEN (s) vs ' + opts.to + ' output — serial schedule', '='.repeat(78)];
    L.push('  E/s   frac-units   whole-units      |  bp sensitivity (fractional)');
    L.push('  ' + '-'.repeat(74));
    const bps = [300, 600, 1060, 2000, Infinity];
    L.push('  '.padEnd(38) + '|  ' + bps.map(b => (b === Infinity ? '   inf' : String(b).padStart(6))).join(' '));
    for (const W of [5, 7.5, 10, 12.5, 15, 17.5, 20, 25]) {
        const a = analyze({ ...opts, wind: W });
        const cells = bps.map(b => {
            if (b === Infinity) return f(a.cases['serial/fractional'].floorBp, 0).padStart(6);
            const s = analyze({ ...opts, wind: W, bp: b, reclaimBp: b });
            return f(s.cases['serial/fractional'].breakEven, 0).padStart(6);
        });
        L.push('  ' + String(W).padStart(4) +
            f(a.cases['serial/fractional'].breakEven, 1).padStart(13) +
            f(a.cases['serial/whole'].breakEven, 1).padStart(14) +
            '      |  ' + cells.join(' '));
    }
    return L.join('\n');
}

// ── cli ──────────────────────────────────────────────────────────────────────

function parseArgs(argv) {
    const o = { from: 'solar', to: 'wind', bp: 1060, yield: 1.0, sweep: false, json: false };
    for (const arg of argv) {
        const m = /^--([\w-]+)(?:=(.*))?$/.exec(arg);
        if (!m) continue;
        const [, k, v] = m;
        if (k === 'sweep' || k === 'json') o[k] = true;
        else if (k === 'reclaim-bp') o.reclaimBp = Number(v);
        else if (['bp', 'wind', 'yield'].includes(k)) o[k] = Number(v);
        else if (['from', 'to'].includes(k)) o[k] = v;
    }
    o.reclaimBp = o.reclaimBp ?? o.bp;
    return o;
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
    const opts = parseArgs(process.argv.slice(2));
    const a = analyze(opts);
    if (opts.json) console.log(JSON.stringify(a, null, 2));
    else {
        console.log(report(a, opts));
        if (opts.sweep) console.log(sweep(opts));
        console.log('');
    }
}

export { analyze, simulate };

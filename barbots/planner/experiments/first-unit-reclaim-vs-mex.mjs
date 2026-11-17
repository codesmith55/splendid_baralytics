// first-unit-reclaim-vs-mex.mjs — an eco theory test (standalone, runnable).
//
// THEORY UNDER TEST
// -----------------
// "The first worker out of the lab: should it RECLAIM ROCKS or BUILD MEXES?"
//
//   - Reclaim rocks  → metal NOW. Rocks are a *static, finite* resource: reclaiming
//     depletes them, but you get a fast lump of metal early. In an RTS, metal earlier
//     is worth more than the same metal later (you can reinvest it sooner — tempo).
//   - Build mexes    → metal LATER, forever. A mex costs metal + build time up front
//     (it starts you *negative*), then pays a small trickle that compounds without end.
//     It is the better *source* of metal — eventually.
//
// So this is a classic burst-vs-income, now-vs-later question. This file models both
// openings from the moment the first worker pops, plots their cumulative-metal curves,
// finds the CROSSOVER (when the income source overtakes the depleting one), and applies
// a time-value lens to test the "earlier = value in RTS" half of the claim.
//
// It also models the synthesis the dichotomy hides: RECLAIM-THEN-MEX — reclaim funds
// the mex, so you get the early lump *and* the long-run income. (This is exactly the
// reference intent's "1st laz eats rocks" while workers go take mexes.)
//
// Run:  node planner/experiments/first-unit-reclaim-vs-mex.mjs
//
// SCOPE: a deliberately simple closed-form model, not the full eco_engine sim. It
// isolates the *first worker's first job*; it does not reinvest income into a real
// build order (that is what eco_engine/projectOption is for — see planner/README). The
// point is to make the now-vs-later trade legible, not to predict an exact game.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const UNITS = JSON.parse(readFileSync(join(here, '..', 'data', 'units.json'), 'utf8'));

// ── Parameters ──────────────────────────────────────────────────────────────
// SOURCED values come from planner/data/units.json (transcribed from bar-calc).
// PROVISIONAL values are map/feature dependent and flagged — they move the numbers
// but not the shape of the result. Tune them and re-run to probe the conclusion.
const MEX = UNITS.units.mex;                 // SOURCED: metal 50, buildWork 1800, income 1.8/s
const CON = UNITS.builders.con;              // SOURCED: buildPower 80, speed 36, range 130
const GRID = UNITS._meta.elmosPerGridSquare; // SOURCED: 48.3 elmos/square

const BP = CON.buildPower;                    // worker build power (= reclaim power too)
const MEX_BUILD_S = MEX.buildWork / BP;       // 1800/80 = 22.5 s to build a mex
const MEX_INCOME = MEX.metalIncome;           // 1.8 m/s  (map-dependent in reality)
const MEX_COST = MEX.metal;                   // 50 metal sunk to build it

// PROVISIONAL — the rock field and reclaim physics.
const ROCKS_METAL = 300;        // total reclaimable metal in the nearby rock field. _PROVISIONAL: map feature value (ATG rocks near a base ≈ 200–500).
const RECLAIM_EFF = 1.0;        // reclaim returns feature metal at (buildPower × eff). _PROVISIONAL: Spring reclaim ≈ buildpower-rate; eff=1 is the simplifying assumption.
const RECLAIM_RATE = BP * RECLAIM_EFF;        // 80 m/s while rock remains
const RECLAIM_DUR_S = ROCKS_METAL / RECLAIM_RATE; // 300/80 = 3.75 s to strip the field

// PROVISIONAL — walk distances (stubbed, like the expander). Both are near base, so
// walk is small vs build/reclaim time; kept explicit so you can see it barely matters.
const ROCK_DIST_SQUARES = 3.0;
const MEX_DIST_SQUARES = 3.0;
const MEX_DIST2_SQUARES = 4.0;  // hybrid: a bit farther to the mex after the rocks

const HORIZON_S = 300;          // how long we score (first ~5 minutes)

// RTS time-value: metal in hand at time t is worth more than the same metal later,
// because you could already have reinvested it. We proxy that with an exponential
// discount. HALF_LIFE_S = time over which a unit of metal loses half its strategic
// value if it just sits unspent. _PROVISIONAL knob — it encodes "tempo matters".
const VALUE_HALF_LIFE_S = 60;

// ── Helpers ─────────────────────────────────────────────────────────────────
function walkTime(squares) {
  const gap = squares * GRID;
  return Math.max(0, gap - CON.buildRange) / CON.speed; // builder stops within build range
}
const clampAtLeast = (x, lo) => (x < lo ? lo : x);

// ── Strategy A: pure reclaim ─────────────────────────────────────────────────
// Walk to rocks, strip them, then idle (this worker's job is done). Finite total.
const tWalkR = walkTime(ROCK_DIST_SQUARES);
function reclaimNet(t) {
  const since = t - tWalkR;
  if (since <= 0) return 0;
  if (since >= RECLAIM_DUR_S) return ROCKS_METAL;
  return RECLAIM_RATE * since;
}

// ── Strategy B: pure mex ─────────────────────────────────────────────────────
// Walk to a metal spot, spend MEX_COST building it (goes negative), then +income/s.
const tWalkM = walkTime(MEX_DIST_SQUARES);
const tMexOnline = tWalkM + MEX_BUILD_S;
function mexNet(t) {
  if (t <= tWalkM) return 0;
  if (t < tMexOnline) {
    // spend the cost linearly across the build → dips to -MEX_COST as it completes
    const frac = (t - tWalkM) / MEX_BUILD_S;
    return -MEX_COST * frac;
  }
  return -MEX_COST + MEX_INCOME * (t - tMexOnline);
}

// ── Strategy C: reclaim, then mex (the synthesis) ────────────────────────────
// Strip the rocks (early lump), walk on, build a mex funded by that metal, then income.
const tReclaimDone = tWalkR + RECLAIM_DUR_S;
const tHybMexStart = tReclaimDone + walkTime(MEX_DIST2_SQUARES);
const tHybMexOnline = tHybMexStart + MEX_BUILD_S;
function hybridNet(t) {
  const reclaimed = reclaimNet(t); // same front-loaded lump
  if (t <= tHybMexStart) return reclaimed;
  if (t < tHybMexOnline) {
    const frac = (t - tHybMexStart) / MEX_BUILD_S;
    return reclaimed - MEX_COST * frac;
  }
  return reclaimed - MEX_COST + MEX_INCOME * (t - tHybMexOnline);
}

// ── Crossover: when does the income source overtake the depleting one? ────────
function crossover(f, g, lo = 0, hi = HORIZON_S, step = 0.01) {
  let prev = f(lo) - g(lo);
  for (let t = lo + step; t <= hi; t += step) {
    const d = f(t) - g(t);
    if (prev <= 0 && d > 0) return Math.round(t * 10) / 10; // f pulls ahead of g for good
    prev = d;
  }
  return null; // never within horizon
}

// ── Time-value lens: discount each strategy's metal by how early it arrives ───
// Integrate the discounted *rate* of metal acquisition. Earlier metal is multiplied by
// a larger weight, so a strategy that front-loads scores higher under tempo pressure.
const decay = Math.log(2) / VALUE_HALF_LIFE_S;
function timeValue(netFn, hi = HORIZON_S, dt = 0.05) {
  let v = 0;
  let prev = netFn(0);
  for (let t = dt; t <= hi; t += dt) {
    const cur = netFn(t);
    const dGain = cur - prev;               // metal acquired in this slice (can be negative)
    v += dGain * Math.exp(-decay * t);      // weighted by how early it landed
    prev = cur;
  }
  return v;
}

// ── ASCII chart ──────────────────────────────────────────────────────────────
function chart(series, hi = HORIZON_S, rows = 16, cols = 60) {
  const ts = Array.from({ length: cols }, (_, i) => (i / (cols - 1)) * hi);
  const vals = series.map((s) => ts.map(s.fn));
  const flat = vals.flat();
  const max = Math.max(...flat, 0);
  const min = Math.min(...flat, 0);
  const span = clampAtLeast(max - min, 1);
  const grid = Array.from({ length: rows }, () => Array(cols).fill(' '));
  const zeroRow = rows - 1 - Math.round(((0 - min) / span) * (rows - 1));
  for (let c = 0; c < cols; c++) if (grid[zeroRow]) grid[zeroRow][c] = '·'; // zero line
  series.forEach((s, si) => {
    for (let c = 0; c < cols; c++) {
      const r = rows - 1 - Math.round(((vals[si][c] - min) / span) * (rows - 1));
      if (grid[r]) grid[r][c] = s.mark;
    }
  });
  const lines = grid.map((row, r) => {
    const yVal = min + ((rows - 1 - r) / (rows - 1)) * span;
    return `${String(Math.round(yVal)).padStart(6)} |${row.join('')}`;
  });
  lines.push(`${' '.repeat(6)} +${'-'.repeat(cols)}`);
  lines.push(`${' '.repeat(8)}0${' '.repeat(cols - 6)}${hi}s`);
  return lines.join('\n');
}

// ── Report ────────────────────────────────────────────────────────────────────
function fmt(x) { return (x >= 0 ? ' ' : '') + x.toFixed(1).padStart(6); }

function main() {
  console.log('First unit out of the lab — RECLAIM ROCKS vs BUILD MEX');
  console.log('='.repeat(64));
  console.log('Parameters (S=sourced from units.json, P=provisional):');
  console.log(`  worker build/reclaim power : ${BP} (S)`);
  console.log(`  mex: cost ${MEX_COST}m, build ${MEX_BUILD_S}s, income ${MEX_INCOME}/s (S)`);
  console.log(`  rock field total           : ${ROCKS_METAL}m, stripped in ${RECLAIM_DUR_S}s @ ${RECLAIM_RATE}/s (P)`);
  console.log(`  walks (≈near base)         : rock ${tWalkR.toFixed(1)}s, mex ${tWalkM.toFixed(1)}s (P)`);
  console.log(`  value half-life (tempo)    : ${VALUE_HALF_LIFE_S}s (P)`);
  console.log('');

  console.log('Cumulative NET metal (generated − spent):');
  console.log('   t(s) | reclaim |   mex   | reclaim→mex |  leader');
  console.log('  ------+---------+---------+-------------+---------');
  for (let t = 0; t <= HORIZON_S; t += 30) {
    const r = reclaimNet(t), m = mexNet(t), h = hybridNet(t);
    const leader = r >= m ? 'reclaim' : 'mex';
    console.log(`  ${String(t).padStart(5)} |${fmt(r)} |${fmt(m)} |${fmt(h).padStart(11)}  |  ${leader}`);
  }
  console.log('');

  console.log('Curves (R=reclaim  M=mex  H=reclaim→mex,  · = zero):');
  console.log(chart([
    { fn: reclaimNet, mark: 'R' },
    { fn: mexNet, mark: 'M' },
    { fn: hybridNet, mark: 'H' },
  ]));
  console.log('');

  const xMexBeatsReclaim = crossover(mexNet, reclaimNet);
  console.log('Findings:');
  console.log(`  • Reclaim is ahead from the start — full ${ROCKS_METAL}m banked by t=${tReclaimDone.toFixed(1)}s,`);
  console.log(`    while the pure-mex worker is still NEGATIVE until its mex pays back the ${MEX_COST}m`);
  console.log(`    (mex breaks even at t=${(tMexOnline + MEX_COST / MEX_INCOME).toFixed(1)}s).`);
  if (xMexBeatsReclaim) {
    console.log(`  • Pure mex finally overtakes pure reclaim at t=${xMexBeatsReclaim}s — the CROSSOVER.`);
    console.log(`    Before it: reclaim wins (earlier metal = tempo). After it: mex wins (income compounds).`);
  } else {
    console.log(`  • Within ${HORIZON_S}s, pure mex never catches the reclaim lump`);
    console.log(`    (crossover is beyond the horizon — solve: tMexOnline + (ROCKS+cost)/income).`);
  }
  const tvR = timeValue(reclaimNet), tvM = timeValue(mexNet), tvH = timeValue(hybridNet);
  console.log(`  • Time-valued score (earlier metal weighted, ${VALUE_HALF_LIFE_S}s half-life):`);
  console.log(`        reclaim ${tvR.toFixed(0)}   mex ${tvM.toFixed(0)}   reclaim→mex ${tvH.toFixed(0)}`);
  console.log(`    → ${tvH > tvR && tvH > tvM ? 'reclaim→mex dominates' : (tvR > tvM ? 'reclaim dominates' : 'mex dominates')} under tempo pressure.`);
  console.log('');
  console.log('VERDICT:');
  console.log('  The theory holds — but the dichotomy is false. Reclaim delivers the early');
  console.log('  metal RTS tempo rewards; the mex is the better source only past the crossover.');
  console.log('  Because they are not mutually exclusive, RECLAIM-THEN-MEX captures both: the');
  console.log('  rock lump funds the mex, so you lead early AND own the compounding income.');
  console.log('  That is precisely the reference intent: 1st laz eats rocks, workers take mexes.');

  // ── sanity asserts (the model must exhibit the claimed shape) ──────────────
  const fail = [];
  if (!(reclaimNet(tReclaimDone + 5) > mexNet(tReclaimDone + 5))) fail.push('reclaim should lead early');
  if (!(mexNet(0) === 0 && mexNet(tMexOnline - 0.01) < 0)) fail.push('mex should start non-positive (sunk cost)');
  if (!(hybridNet(HORIZON_S) >= reclaimNet(HORIZON_S) && hybridNet(HORIZON_S) >= mexNet(HORIZON_S))) fail.push('hybrid should dominate at horizon');
  if (fail.length) { console.error('\nMODEL SANITY FAILED: ' + fail.join('; ')); process.exit(1); }
}

main();

// eco_table.mjs — per-interval economy/asset snapshot per team from a gex actions.json.
//   node eco_table.mjs <actions.json> <intervalSec> <teamID,...> [maxSec]
// Uses this run's rich extra_stat_update (totalValue/army/def/eco/util, metalIncome,
// energyIncome, buildPower*, stored M/E, received) + live-unit tracking for mex &
// converter counts (converter M/s capacity = Σ cap*eff of live converters).
import { parseActions } from "../process/lib/parseActions.mjs";

const [, , actionsFile, intervalArg, teamsArg, maxSecArg] = process.argv;
const interval = Number(intervalArg || 60);
const fps = 30;
const teams = (teamsArg || "").split(",").filter(s => s !== "").map(Number);

const { byAction, defMap, meta } = parseActions(actionsFile);
// Default analysis window = first 15 min (most action is early; rest expands from there).
// Pass an explicit number of seconds to override, or "full" for the whole game.
const gameSec = Math.floor(meta.endFrame / fps);
const DEFAULT_WINDOW_SEC = 900; // 15 min
const maxSec = !maxSecArg ? Math.min(DEFAULT_WINDOW_SEC, gameSec)
  : (maxSecArg === "full" ? gameSec : Number(maxSecArg));

const isMex  = (d) => !!d && (d.isMetalExtractor === true || (d.extractsMetal || 0) > 0);
const convMs = (d) => (d && (d.energyConversionCapacity || 0) > 0) ? (d.energyConversionCapacity * d.energyConversionEfficiency) : 0;

// ---- lifecycle stream for live-unit counts ----
const lc = [];
for (const e of byAction.get("unit_created") ?? [])         lc.push({ f: e.frame, t: "c", id: e.unitID, team: e.teamID, def: e.defID });
for (const e of byAction.get("factory_unit_created") ?? []) lc.push({ f: e.frame, t: "c", id: e.unitID, team: e.teamID, def: e.defID });
for (const e of byAction.get("unit_killed") ?? [])          lc.push({ f: e.frame, t: "k", id: e.unitID });
for (const e of byAction.get("unit_given") ?? [])           lc.push({ f: e.frame, t: "m", id: e.unitID, team: e.newTeamID ?? e.teamID });
for (const e of byAction.get("unit_taken") ?? [])           lc.push({ f: e.frame, t: "m", id: e.unitID, team: e.teamID });
lc.sort((a, b) => a.f - b.f || (a.t === "k" ? 0 : a.t === "m" ? 1 : 2) - (b.t === "k" ? 0 : b.t === "m" ? 1 : 2));

const xs = (byAction.get("extra_stat_update") ?? []).slice().sort((a, b) => a.frame - b.frame);
const xsByTeam = new Map();
for (const e of xs) { if (!xsByTeam.has(e.teamID)) xsByTeam.set(e.teamID, []); xsByTeam.get(e.teamID).push(e); }
const latestLE = (arr, frame) => { let r = null; for (const e of arr) { if (e.frame > frame) break; r = e; } return r; };

const rnd = (x, d = 0) => { if (x == null) return null; const p = 10 ** d; return Math.round((x + Number.EPSILON) * p) / p; };
const tstr = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// walk lifecycle once, snapshot live counts per team at each mark frame
const marks = [];
for (let s = 0; s <= maxSec; s += interval) marks.push(s);
if (marks[marks.length - 1] !== maxSec) marks.push(maxSec);

const alive = new Map();                 // id -> {team, def}
const liveSnap = new Map();              // team -> [{sec, nMex, nConv, convCap, nUnits}]
for (const tm of teams) liveSnap.set(tm, []);
let p = 0;
for (const sec of marks) {
  const F = sec * fps;
  while (p < lc.length && lc[p].f <= F) {
    const ev = lc[p++];
    if (ev.t === "c") alive.set(ev.id, { team: ev.team, def: ev.def });
    else if (ev.t === "k") alive.delete(ev.id);
    else if (ev.t === "m") { const r = alive.get(ev.id); if (r) r.team = ev.team; }
  }
  const agg = new Map();
  for (const [, r] of alive) {
    if (!teams.includes(r.team)) continue;
    const a = agg.get(r.team) || { nMex: 0, nConv: 0, convCap: 0, nUnits: 0 };
    const d = defMap.get(r.def);
    a.nUnits++;
    if (isMex(d)) a.nMex++;
    const cm = convMs(d); if (cm > 0) { a.nConv++; a.convCap += cm; }
    agg.set(r.team, a);
  }
  for (const tm of teams) liveSnap.get(tm).push({ sec, ...(agg.get(tm) || { nMex: 0, nConv: 0, convCap: 0, nUnits: 0 }) });
}

for (const team of teams) {
  console.log(`\n################ team ${team} (interval ${interval}s) ################`);
  const xsa = xsByTeam.get(team) || [];
  const live = liveSnap.get(team);
  const cols = ["t", "totalVal", "army", "def", "eco", "util", "other", "bpAvail", "bpUsed", "mInc", "eInc", "convCap", "mexInc~", "mStored", "eStored", "mRecv", "nMex", "nConv", "nUnits"];
  console.log(cols.join("\t"));
  live.forEach((ls, i) => {
    const F = ls.sec * fps;
    const x = latestLE(xsa, F) || {};
    const conv = rnd(ls.convCap, 1);
    const mInc = x.metalIncome ?? null;
    const mexInc = (mInc == null) ? null : rnd(mInc - ls.convCap, 1); // mex+reclaim ≈ total − converter(max)
    const row = {
      t: tstr(ls.sec),
      totalVal: rnd(x.totalValue), army: rnd(x.armyValue), def: rnd(x.defValue), eco: rnd(x.ecoValue),
      util: rnd(x.utilValue), other: rnd(x.otherValue),
      bpAvail: rnd(x.buildPowerAvailable), bpUsed: rnd(x.buildPowerUsed),
      mInc: rnd(mInc, 1), eInc: rnd(x.energyIncome, 1), convCap: conv, "mexInc~": mexInc,
      mStored: rnd(x.metalCurrent), eStored: rnd(x.energyCurrent), mRecv: rnd(x.metalReceived, 1),
      nMex: ls.nMex, nConv: ls.nConv, nUnits: ls.nUnits,
    };
    console.log(cols.map(c => row[c] == null ? "-" : row[c]).join("\t"));
  });
}

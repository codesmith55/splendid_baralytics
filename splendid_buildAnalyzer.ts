// splendid_buildAnalyzer.ts — comparative economy + collapse ("death") detector for BAR demos.
//
//   node splendid_buildAnalyzer.js [demo|latest] [--me <name>] [--dir <demosDir>] [--every <sec>]
//
// The demo's teamStats are *cumulative* counters sampled every 15 s. We differentiate them
// into per-second income and derive a single "total economy" = metal/s + energy/s/70 (the
// repo's value formula). From that we produce:
//   1. Comparative total economy — allyTeam vs allyTeam over time (who is out-producing).
//   2. Per-player splits — each player's share of their team's economy, and metal:energy mix.
//   3. Collapse detection — a dramatic, sustained drop in a player's economy is flagged as a
//      loss/death ("reductions in economy are dramatic indicators"). A near-total, unrecovered
//      collapse is marked 💀 "died handedly".
//
// NOTE: splendid_buildAnalyzer.js is the runnable artifact (root has no node_modules; it
// resolves sdfz-demo-parser from the gex_research/tools/demoparser install). Keep the two in
// sync. This .ts is the typed source of record.
import { createRequire } from "node:module";
import * as fs from "node:fs";
import * as path from "node:path";

const require = createRequire(import.meta.url);

// ---- parser resolution (root has no node_modules; reuse the gex demoparser install) ----
type DemoParserCtor = new (opts?: { verbose?: boolean }) => {
  parseDemo(file: string): Promise<DemoModel>;
};
function loadDemoParser(): DemoParserCtor {
  const attempts = [
    "sdfz-demo-parser",
    "./gex_research/tools/demoparser/node_modules/sdfz-demo-parser",
    "./sdfz-demo-parser",
  ];
  for (const id of attempts) {
    try {
      const dp = require(id).DemoParser;
      if (typeof dp === "function") return dp as DemoParserCtor;
    } catch { /* try next */ }
  }
  throw new Error(
    "sdfz-demo-parser not found. Run `npm install` here, or keep " +
    "gex_research/tools/demoparser/node_modules installed."
  );
}

// ----------------------------------------------------------------------------- types
// One teamStats sample — cumulative counters at a given frame (sampled every 15 s).
interface TeamStatSample {
  frame: number;
  metalProduced: number; energyProduced: number;
  metalUsed: number; energyUsed: number;
  metalExcess: number; energyExcess: number;
  damageReceived: number; unitsDied: number;
  [k: string]: number;
}
interface PlayerInfo { playerId: number; teamId: number; allyTeamId: number; name: string; faction?: string; }
interface AiInfo { teamId: number; allyTeamId: number; name?: string; faction?: string; }
interface DemoMeta { map?: string; mapName?: string; winningAllyTeamIds?: number[]; durationMs?: number; }
interface DemoModel {
  info?: { players?: PlayerInfo[]; ais?: AiInfo[]; meta?: DemoMeta };
  // teamStats is an OBJECT keyed by teamId ("0","1",...), each an array of samples.
  statistics?: { teamStats?: Record<string, TeamStatSample[]> };
}
interface TeamMeta { name: string; ally: number; faction: string; isAI: boolean; }
interface EcoPoint {
  frame: number; sec: number;
  econ: number; metalInc: number; energyInc: number;
  buildUse: number; waste: number;
  dmgRecvRate: number; unitsDiedRate: number;
  cumUnitsDied: number; cumDmgRecv: number;
  // absolute per-interval deltas (for minute-over-minute battle/swing aggregation)
  dDealt: number; dTaken: number; dKilled: number; dLost: number; dBuilt: number; dProduced: number;
}
interface Bucket { sec: number; dealt: number; taken: number; killed: number; lost: number; built: number; produced: number; }
interface Collapse {
  peak: EcoPoint; trough: EcoPoint; dropFrac: number;
  recovered: boolean; recoveredAt: EcoPoint | null; decisive: boolean;
  unitsLost: number; dmgTaken: number;
}

// ----------------------------------------------------------------------------- consts
const FPS = 30;
const VALUE_E_DIV = 70;
const MIN_PEAK = 40;
const COLLAPSE_FRAC = 0.4;
const DECISIVE_FRAC = 0.15;
const RECOVER_FRAC = 0.5;

const DEMO_DIRS = [
  process.env.BAR_DEMOS,
  "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data/demos",
  process.env.HOME ? path.join(process.env.HOME, ".local/state/Beyond All Reason/demos") : null,
].filter((d): d is string => !!d);

// ------------------------------------------------------------------------------- args
interface Args { demo: string; me: string | null; dir: string | null; every: number; actions: string | null; }
function parseArgs(argv: string[]): Args {
  const a: Args = { demo: "latest", me: null, dir: null, every: 60, actions: null };
  const rest: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t === "--me") a.me = argv[++i];
    else if (t === "--dir") a.dir = argv[++i];
    else if (t === "--every") a.every = Number(argv[++i]) || 60;
    else if (t === "--actions") a.actions = argv[++i];   // headless lifecycle actions.json (unit value)
    else rest.push(t);
  }
  if (rest[0]) a.demo = rest[0];
  return a;
}

function demosDir(override: string | null): string | null {
  const dirs = override ? [override, ...DEMO_DIRS] : DEMO_DIRS;
  for (const d of dirs) { try { if (fs.statSync(d).isDirectory()) return d; } catch { /* skip */ } }
  return null;
}

function resolveDemo(arg: string, dirOverride: string | null): string {
  if (arg && arg !== "latest" && fs.existsSync(arg)) return arg;
  const dir = demosDir(dirOverride);
  if (!dir) throw new Error("no demos directory found; pass a demo path or --dir <dir>");
  if (arg && arg !== "latest") {
    const direct = path.join(dir, arg);
    if (fs.existsSync(direct)) return direct;
  }
  const demos = fs.readdirSync(dir).filter(f => f.endsWith(".sdfz"))
    .map(f => ({ f, m: fs.statSync(path.join(dir, f)).mtimeMs }))
    .sort((x, y) => y.m - x.m);
  if (!demos.length) throw new Error(`no .sdfz demos in ${dir}`);
  return path.join(dir, demos[0].f);
}

// ------------------------------------------------------------------------- team meta
function buildTeamMeta(info: DemoModel["info"]): Map<number, TeamMeta> {
  const meta = new Map<number, TeamMeta>();
  for (const p of info?.players ?? [])
    meta.set(p.teamId, { name: p.name, ally: p.allyTeamId, faction: p.faction || "?", isAI: false });
  for (const ai of info?.ais ?? [])
    meta.set(ai.teamId, { name: ai.name || `AI ${ai.teamId}`, ally: ai.allyTeamId, faction: ai.faction || "AI", isAI: true });
  return meta;
}

// ------------------------------------------------- differentiate cumulative -> rates
function computeSeries(teamStats: Record<string, TeamStatSample[]>): Map<number, EcoPoint[]> {
  const out = new Map<number, EcoPoint[]>();
  for (const key of Object.keys(teamStats)) {
    const teamId = Number(key);
    const samples = teamStats[key];
    if (!samples || samples.length < 2) { out.set(teamId, []); continue; }
    const series: EcoPoint[] = [];
    for (let i = 1; i < samples.length; i++) {
      const a = samples[i - 1], b = samples[i];
      const dt = Math.max((b.frame - a.frame) / FPS, 1e-6);
      const metalInc = (b.metalProduced - a.metalProduced) / dt;
      const energyInc = (b.energyProduced - a.energyProduced) / dt;
      const econ = metalInc + energyInc / VALUE_E_DIV;
      const buildUse = (b.metalUsed - a.metalUsed) / dt + ((b.energyUsed - a.energyUsed) / dt) / VALUE_E_DIV;
      const waste = (b.metalExcess - a.metalExcess) / dt + ((b.energyExcess - a.energyExcess) / dt) / VALUE_E_DIV;
      series.push({
        frame: b.frame, sec: b.frame / FPS,
        econ, metalInc, energyInc, buildUse, waste,
        dmgRecvRate: (b.damageReceived - a.damageReceived) / dt,
        unitsDiedRate: (b.unitsDied - a.unitsDied) / dt,
        cumUnitsDied: b.unitsDied, cumDmgRecv: b.damageReceived,
        dDealt: b.damageDealt - a.damageDealt,
        dTaken: b.damageReceived - a.damageReceived,
        dKilled: b.unitsKilled - a.unitsKilled,
        dLost: b.unitsDied - a.unitsDied,
        dBuilt: b.unitsProduced - a.unitsProduced,
        dProduced: (b.metalProduced - a.metalProduced) + (b.energyProduced - a.energyProduced) / VALUE_E_DIV,
      });
    }
    out.set(teamId, series);
  }
  return out;
}

// When a game ends (or is mass-resigned) the FINAL stat interval shows a broad, simultaneous
// economy crater across most teams — an artifact, not a death. Detect it (median last/prev econ
// ratio < 0.5 among teams with a real economy) and drop the trailing sample everywhere.
function trimEndFlush(seriesMap: Map<number, EcoPoint[]>, maxTrim = 2): number {
  let trimmed = 0;
  for (let pass = 0; pass < maxTrim; pass++) {
    const arrs = [...seriesMap.values()].filter(s => s.length >= 2);
    if (arrs.length < 3) break;
    const len = Math.max(...arrs.map(s => s.length));
    const ratios: number[] = [];
    for (const s of arrs) {
      if (s.length !== len) continue;
      const last = s[s.length - 1].econ, prev = s[s.length - 2].econ;
      if (prev > MIN_PEAK) ratios.push(last / prev);
    }
    if (ratios.length < 3) break;
    ratios.sort((a, b) => a - b);
    const median = ratios[Math.floor(ratios.length / 2)];
    if (median >= 0.5) break;
    for (const [k, s] of seriesMap) if (s.length === len) seriesMap.set(k, s.slice(0, -1));
    trimmed++;
  }
  return trimmed;
}

// ------------------------------------------------------------- collapse / death model
function detectCollapse(series: EcoPoint[]): Collapse | null {
  const pts = series.filter(s => s.sec >= 30);   // skip the early-game ramp
  if (pts.length < 3) return null;

  let peak = pts[0], peakIdx = 0;
  pts.forEach((s, i) => { if (s.econ > peak.econ) { peak = s; peakIdx = i; } });
  if (peak.econ < MIN_PEAK) return null;

  let trough = pts[peakIdx], troughIdx = peakIdx;
  for (let i = peakIdx; i < pts.length; i++) {
    if (pts[i].econ < trough.econ) { trough = pts[i]; troughIdx = i; }
  }
  const dropFrac = 1 - trough.econ / peak.econ;
  if (trough.econ > COLLAPSE_FRAC * peak.econ) return null;

  // require the collapse to be SUSTAINED (≥2 low samples ≈ ≥30 s), so a lone dip isn't a "death".
  const lowSamples = pts.slice(peakIdx).filter(s => s.econ < COLLAPSE_FRAC * peak.econ).length;
  if (lowSamples < 2) return null;

  let recovered = false, recoveredAt: EcoPoint | null = null;
  for (let i = troughIdx + 1; i < pts.length; i++) {
    if (pts[i].econ >= RECOVER_FRAC * peak.econ) { recovered = true; recoveredAt = pts[i]; break; }
  }
  const decisive = trough.econ <= DECISIVE_FRAC * peak.econ && !recovered;
  const unitsLost = Math.max(0, trough.cumUnitsDied - peak.cumUnitsDied);
  const dmgTaken = Math.max(0, trough.cumDmgRecv - peak.cumDmgRecv);
  return { peak, trough, dropFrac, recovered, recoveredAt, decisive, unitsLost, dmgTaken };
}

// ---------------------------------------------------- unit value flow (headless lifecycle)
// The .sdfz demo records only player COMMANDS — it has no unit-creation/death events. To get
// the RESOURCE VALUE of units built (+) and lost (−) per minute we need a headless lifecycle
// dump (gex_research actions.json: unit_def + unit_created/unit_killed). value = metal + e/70,
// commander = flat 1200 (matches process/lib/classify.mjs).
interface ValueFlow { built: number[]; lost: number[]; }
function loadValueFlow(actionsPath: string, bucketSec: number, nBuckets: number): Map<number, ValueFlow> {
  const lines = fs.readFileSync(actionsPath, "utf8").split(/\r?\n/);
  const bf = bucketSec * FPS;
  const val = new Map<number, number>();
  const events: Array<{ action: string; frame: number; teamID: number; defID: number }> = [];
  for (const ln of lines) {
    if (!ln) continue;
    let e: { action: string; defID: number; defName?: string; isCommander?: boolean; metalCost?: number; energyCost?: number; frame: number; teamID: number };
    try { e = JSON.parse(ln); } catch { continue; }
    if (e.action === "unit_def") {
      const com = e.isCommander === true || /com$/.test(e.defName || "");
      val.set(e.defID, com ? 1200 : (e.metalCost || 0) + (e.energyCost || 0) / VALUE_E_DIV);
    } else events.push(e);
  }
  const flow = new Map<number, ValueFlow>();
  const ensure = (t: number): ValueFlow => {
    if (!flow.has(t)) flow.set(t, { built: new Array(nBuckets).fill(0), lost: new Array(nBuckets).fill(0) });
    return flow.get(t)!;
  };
  for (const e of events) {
    if (typeof e.frame !== "number" || typeof e.teamID !== "number") continue;
    const bi = Math.min(nBuckets - 1, Math.floor(e.frame / bf));
    if (bi < 0) continue;
    if (e.action === "unit_created" || e.action === "factory_unit_created") ensure(e.teamID).built[bi] += val.get(e.defID) || 0;
    else if (e.action === "unit_killed") ensure(e.teamID).lost[bi] += val.get(e.defID) || 0;
  }
  return flow;
}

// ------------------------------------------------------- battles & swings (per minute)
// Aggregate the per-interval deltas into minute buckets, per ally team and per player.
function aggregateBuckets(
  series: Map<number, EcoPoint[]>, teamMeta: Map<number, TeamMeta>,
  allies: Map<number, number[]>, bucketSec: number, analysisEnd: number,
): { perAlly: Map<number, Bucket[]>; perTeam: Map<number, Bucket[]>; nBuckets: number } {
  const bf = bucketSec * FPS;
  const nBuckets = Math.max(1, Math.ceil((analysisEnd + 1) / bf));
  const blank = (): Bucket[] => Array.from({ length: nBuckets }, (_, i) => ({
    sec: (i + 1) * bucketSec, dealt: 0, taken: 0, killed: 0, lost: 0, built: 0, produced: 0,
  }));
  const perTeam = new Map<number, Bucket[]>(), perAlly = new Map<number, Bucket[]>();
  for (const a of allies.keys()) perAlly.set(a, blank());
  for (const [tid, m] of teamMeta) {
    const tb = blank();
    perTeam.set(tid, tb);
    const ab = perAlly.get(m.ally)!;
    for (const p of series.get(tid) ?? []) {
      const bi = Math.min(nBuckets - 1, Math.floor((p.frame - 1) / bf));
      for (const dst of [tb, ab]) {
        dst[bi].dealt += p.dDealt; dst[bi].taken += p.dTaken; dst[bi].killed += p.dKilled;
        dst[bi].lost += p.dLost; dst[bi].built += p.dBuilt; dst[bi].produced += p.dProduced;
      }
    }
  }
  return { perAlly, perTeam, nBuckets };
}

// ------------------------------------------------------------------------- formatting
const mmss = (sec: number): string => {
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
};
const k = (n: number): string => {
  const v = Math.round(n);
  return Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + "k" : String(v);
};
const pad = (s: unknown, n: number): string => { const x = String(s); return x.length >= n ? x : x + " ".repeat(n - x.length); };
const padL = (s: unknown, n: number): string => { const x = String(s); return x.length >= n ? x : " ".repeat(n - x.length) + x; };

function econAtFrame(series: EcoPoint[] | undefined, F: number): number {
  if (!series || !series.length) return 0;
  let v = 0;
  for (const s of series) { if (s.frame > F) break; v = s.econ; }
  return v;
}

function findMe(name: string, teamMeta: Map<number, TeamMeta>): string {
  const lc = name.toLowerCase();
  for (const m of teamMeta.values()) if (m.name.toLowerCase() === lc) return m.name;
  for (const m of teamMeta.values()) if (m.name.toLowerCase().includes(lc)) return m.name;
  return name;
}

// ------------------------------------------------------------------------------- main
async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const DemoParser = loadDemoParser();
  const demoPath = resolveDemo(args.demo, args.dir);

  const demo = await new DemoParser({ verbose: false }).parseDemo(demoPath);
  const info = demo.info ?? {};
  const meta = info.meta ?? {};
  const teamStats = demo.statistics?.teamStats ?? {};
  const teamKeys = Object.keys(teamStats);
  const firstSamples = teamKeys.length ? teamStats[teamKeys[0]] : null;
  if (!firstSamples || firstSamples.length < 2) {
    console.error(`No teamStats in ${path.basename(demoPath)} — game too short or aborted (try a longer demo).`);
    process.exit(2);
  }

  const teamMeta = buildTeamMeta(info);
  const series = computeSeries(teamStats);
  trimEndFlush(series);
  const winners = meta.winningAllyTeamIds ?? [];
  let analysisEnd = 0;
  for (const s of series.values()) if (s.length) analysisEnd = Math.max(analysisEnd, s[s.length - 1].frame);

  const allies = new Map<number, number[]>();
  for (const [tid, m] of teamMeta) { if (!allies.has(m.ally)) allies.set(m.ally, []); allies.get(m.ally)!.push(tid); }
  const allyIds = [...allies.keys()].sort((a, b) => a - b);

  const lastFrame = firstSamples[firstSamples.length - 1].frame;
  const meName = args.me ? findMe(args.me, teamMeta) : null;

  console.log("");
  console.log(`BAR Build Analyzer — ${meta.map || meta.mapName || "?"}`);
  console.log(`${path.basename(demoPath)}`);
  console.log(`duration ${mmss(lastFrame / FPS)} · ${teamMeta.size} teams · winner allyTeam ${winners.length ? winners.join(",") : "?"}`);
  if (meName) console.log(`highlighting: ${meName} (you)`);
  console.log("");

  // 1. comparative team economy
  console.log("== Comparative team economy  (value/s = metal/s + energy/s ÷ 70) ==");
  const stepFrames = args.every * FPS;
  const headerCols = allyIds.map(a => padL(`AT${a}${winners.includes(a) ? "*" : ""}`, 9)).join(" ");
  console.log(`  ${pad("time", 6)} ${headerCols}   lead`);
  const sampleFrames: number[] = [];
  for (let f = stepFrames; f <= analysisEnd + 1; f += stepFrames) sampleFrames.push(f);
  if (sampleFrames[sampleFrames.length - 1] < analysisEnd) sampleFrames.push(analysisEnd);
  for (const F of sampleFrames) {
    const totals = allyIds.map(a => allies.get(a)!.reduce((sum, tid) => sum + econAtFrame(series.get(tid), F), 0));
    const max = Math.max(...totals), min = Math.min(...totals);
    const leader = allyIds[totals.indexOf(max)];
    const leadPct = max > 0 ? Math.round((1 - min / max) * 100) : 0;
    const cols = totals.map(t => padL(k(t), 9)).join(" ");
    console.log(`  ${pad(mmss(F / FPS), 6)} ${cols}   AT${leader} +${leadPct}%`);
  }
  console.log("");

  // 2. collapse / death detection
  console.log("== Economy collapses  (death indicators) ==");
  const events: { tid: number; m: TeamMeta; c: Collapse }[] = [];
  for (const [tid, m] of teamMeta) {
    const c = detectCollapse(series.get(tid) ?? []);
    if (c) events.push({ tid, m, c });
  }
  events.sort((a, b) => b.c.dropFrac - a.c.dropFrac);
  if (!events.length) {
    console.log("  (no significant economy collapse detected — all economies held)");
  } else {
    for (const { m, c } of events) {
      const glyph = c.decisive ? "💀" : c.recovered ? "↩ " : "⚠ ";
      const tag = c.decisive ? "DIED HANDEDLY" : c.recovered ? `recovered by ${mmss(c.recoveredAt!.sec)}` : "did not recover";
      const mine = meName && m.name === meName ? "  <- you" : "";
      const corro = (c.unitsLost || c.dmgTaken) ? `  [${c.unitsLost} units lost, ${k(c.dmgTaken)} dmg taken]` : "";
      console.log(
        `  ${glyph} ${pad(m.name, 22)} AT${m.ally}  econ ${k(c.peak.econ)}→${k(c.trough.econ)}/s ` +
        `(−${Math.round(c.dropFrac * 100)}%)  ${mmss(c.peak.sec)}→${mmss(c.trough.sec)}  ${tag}${corro}${mine}`
      );
    }
  }
  console.log("");

  // 3. battles & swings (minute over minute)
  const { perAlly, perTeam } = aggregateBuckets(series, teamMeta, allies, args.every, analysisEnd);
  const nB = perAlly.get(allyIds[0])!.length;
  const mapDmg: number[] = [];
  for (let i = 0; i < nB; i++) mapDmg.push(allyIds.reduce((s, a) => s + perAlly.get(a)![i].dealt, 0));
  const activeDmg = mapDmg.filter(d => d > 0);
  const meanDmg = activeDmg.length ? activeDmg.reduce((s, d) => s + d, 0) / activeDmg.length : 0;
  const peakDmg = activeDmg.length ? Math.max(...activeDmg) : 0;
  const battleThresh = Math.max(meanDmg * 1.3, peakDmg * 0.35);

  console.log("== Battles — minute over minute  (kills = enemy units destroyed, losses = own units lost) ==");
  console.log(`  ${pad("time", 6)} ${allyIds.map(a => padL(`AT${a} k/lost`, 12)).join("  ")}   map dmg   `);
  for (let i = 0; i < nB; i++) {
    if (mapDmg[i] <= 0) continue;
    const cols = allyIds.map(a => { const b = perAlly.get(a)![i]; return padL(`${b.killed}/${b.lost}`, 12); }).join("  ");
    let flag = "";
    if (mapDmg[i] >= battleThresh) {
      const nets = allyIds.map(a => { const b = perAlly.get(a)![i]; return { a, net: b.killed - b.lost }; });
      nets.sort((x, y) => y.net - x.net);
      const margin = nets[0].net - nets[1].net;
      const totalKilled = allyIds.reduce((s, a) => s + perAlly.get(a)![i].killed, 0) || 1;
      flag = margin < totalKilled * 0.2 ? "🔥 big battle — even trade" : `🔥 big battle — edge AT${nets[0].a}`;
    }
    const label = mmss(Math.min((i + 1) * args.every, analysisEnd / FPS));
    console.log(`  ${pad(label, 6)} ${cols}   ${padL(k(mapDmg[i]), 7)}   ${flag}`);
  }
  console.log("");

  const lossEvents: { m: TeamMeta; sec: number; lost: number; dmg: number }[] = [];
  const buildEvents: { m: TeamMeta; sec: number; built: number }[] = [];
  const capSec = (i: number): number => Math.min((i + 1) * args.every, analysisEnd / FPS);
  for (const [tid, m] of teamMeta) {
    const buckets = perTeam.get(tid)!;
    let maxLoss = { lost: 0, i: -1 }, maxBuild = { built: 0, i: -1 };
    buckets.forEach((b, i) => { if (b.lost > maxLoss.lost) maxLoss = { lost: b.lost, i }; if (b.built > maxBuild.built) maxBuild = { built: b.built, i }; });
    if (maxLoss.i >= 0 && maxLoss.lost >= 8) lossEvents.push({ m, sec: capSec(maxLoss.i), lost: maxLoss.lost, dmg: buckets[maxLoss.i].taken });
    if (maxBuild.i >= 0 && maxBuild.built >= 8) buildEvents.push({ m, sec: capSec(maxBuild.i), built: maxBuild.built });
  }
  lossEvents.sort((a, b) => b.lost - a.lost);
  buildEvents.sort((a, b) => b.built - a.built);
  console.log("== Biggest unit swings (single minute, per player) ==");
  console.log("  − losses:");
  for (const e of lossEvents.slice(0, 6))
    console.log(`     ${pad(mmss(e.sec), 6)} ${pad(e.m.name, 22)} AT${e.m.ally}  −${e.lost} units  (${k(e.dmg)} dmg taken)${meName && e.m.name === meName ? "  <- you" : ""}`);
  console.log("  + production:");
  for (const e of buildEvents.slice(0, 6))
    console.log(`     ${pad(mmss(e.sec), 6)} ${pad(e.m.name, 22)} AT${e.m.ally}  +${e.built} units built${meName && e.m.name === meName ? "  <- you" : ""}`);
  console.log("");

  // 3b. unit value flow (only when a headless lifecycle actions.json is supplied)
  if (args.actions) {
    if (!fs.existsSync(args.actions)) {
      console.log(`(--actions file not found: ${args.actions} — skipping unit value flow)\n`);
    } else {
      const flow = loadValueFlow(args.actions, args.every, nB);
      const allyFlow = new Map<number, ValueFlow>();
      for (const a of allyIds) allyFlow.set(a, { built: new Array(nB).fill(0), lost: new Array(nB).fill(0) });
      for (const [tid, m] of teamMeta) {
        const fl = flow.get(tid); if (!fl) continue;
        const af = allyFlow.get(m.ally)!;
        for (let i = 0; i < nB; i++) { af.built[i] += fl.built[i]; af.lost[i] += fl.lost[i]; }
      }
      console.log("== Unit value flow — minute over minute  (value built + / lost −, metal + energy/70) ==");
      console.log(`  source: ${path.basename(args.actions)} (headless lifecycle)`);
      console.log(`  ${pad("time", 6)} ${allyIds.map(a => padL(`AT${a} +built/-lost`, 18)).join("  ")}`);
      for (let i = 0; i < nB; i++) {
        const any = allyIds.some(a => allyFlow.get(a)!.built[i] > 0 || allyFlow.get(a)!.lost[i] > 0);
        if (!any) continue;
        const cols = allyIds.map(a => { const f = allyFlow.get(a)!; return padL(`+${k(f.built[i])}/-${k(f.lost[i])}`, 18); }).join("  ");
        console.log(`  ${pad(mmss(Math.min((i + 1) * args.every, analysisEnd / FPS)), 6)} ${cols}`);
      }
      const valLoss: { m: TeamMeta; sec: number; v: number }[] = [];
      for (const [tid, m] of teamMeta) {
        const fl = flow.get(tid); if (!fl) continue;
        let mx = { v: 0, i: -1 };
        fl.lost.forEach((v, i) => { if (v > mx.v) mx = { v, i }; });
        if (mx.i >= 0 && mx.v >= 500) valLoss.push({ m, sec: Math.min((mx.i + 1) * args.every, analysisEnd / FPS), v: mx.v });
      }
      valLoss.sort((a, b) => b.v - a.v);
      console.log("  biggest material losses (value, single minute):");
      for (const e of valLoss.slice(0, 6))
        console.log(`     ${pad(mmss(e.sec), 6)} ${pad(e.m.name, 22)} AT${e.m.ally}  −${k(e.v)} value${meName && e.m.name === meName ? "  <- you" : ""}`);
      console.log("");
    }
  }

  // 4. per-player splits / standings
  console.log("== Per-player economy splits  (peak economy, metal:energy mix, team share) ==");
  for (const a of allyIds) {
    console.log(`  allyTeam ${a}${winners.includes(a) ? "  (winner)" : ""}`);
    const rows = allies.get(a)!.map(tid => {
      const s = series.get(tid) ?? [];
      const peak = s.reduce((p, x) => (x.econ > p ? x.econ : p), 0);
      const fin = s.length ? s[s.length - 1] : { econ: 0, metalInc: 0, energyInc: 0 } as EcoPoint;
      const eVal = fin.energyInc / VALUE_E_DIV;
      const split = (fin.metalInc + eVal) > 0 ? Math.round(fin.metalInc / (fin.metalInc + eVal) * 100) : 0;
      return { tid, m: teamMeta.get(tid)!, peak, fin: fin.econ, split };
    });
    const teamFinal = rows.reduce((sum, r) => sum + r.fin, 0) || 1;
    rows.sort((x, y) => y.peak - x.peak);
    for (const r of rows) {
      const mine = meName && r.m.name === meName ? " <- you" : "";
      console.log(
        `    ${pad(r.m.name, 22)} peak ${padL(k(r.peak), 6)}/s  final ${padL(k(r.fin), 6)}/s  ` +
        `M:E ${padL(r.split + ":" + (100 - r.split), 7)}  ${padL(Math.round(r.fin / teamFinal * 100) + "%", 4)} of team${mine}`
      );
    }
  }
  console.log("");
}

main().catch((e: Error) => { console.error("✘ " + (e.stack || e.message)); process.exit(1); });

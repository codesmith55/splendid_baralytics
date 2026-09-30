// harvest_defs.mjs — pull every unit / structure / object def straight from the game engine by replaying a
// demo headlessly, and save them as bar-calc/units_<dateTime>.json (the "defs-array" format econ_data.py and
// splendid_buildSimulator.js read; econ_model.json's `engineDefs` glob entry picks the newest file).
//
//   node bar-calc/harvest_defs.mjs [--demo 8v8|latest|<path|filename>] [--dir <demosDir>] [--engine recoil_2026.07.04]
//                                  [--out <file>] [--timeout <ms>] [--full] [--list [N]]
//
//   --demo 8v8      newest demo with 16 human players in two ally teams of 8 (default); NvN works too
//   --demo latest   newest demo of any size
//   --engine        engine folder under <BAR>/engine; default = the engine the demo was recorded with
//   --full          let the replay run to its end (default: stop as soon as the unit_def block is complete —
//                   the defs are emitted at frame 0 by gex.lua, so a full replay is not needed for stats)
//   --list N        print the N newest demos with their matchup and exit
//
// Driven by bar_unified.harvest_unit_defs() (`python bar-calc/bar_unified.py --harvest-defs`), which then
// regenerates parity.json. Last stdout line is a JSON summary {out, count, demo, engine, game, map}.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn, execFileSync } from "node:child_process";
import { createRequire } from "node:module";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const BAR = process.env.BAR_DATA || "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data";
const VENDOR = path.join(ROOT, "gex_research", "vendor");
const DEMO_DIRS = [process.env.BAR_DEMOS, path.join(BAR, "demos")].filter(Boolean);
const require = createRequire(import.meta.url);

function loadDemoParser() {
  for (const id of ["sdfz-demo-parser", path.join(ROOT, "gex_research", "tools", "demoparser", "node_modules", "sdfz-demo-parser")]) {
    try { return require(id).DemoParser; } catch (_) { /* next */ }
  }
  throw new Error("sdfz-demo-parser not found (npm install at the repo root or in gex_research/tools/demoparser)");
}

const log = (...a) => console.error("[harvest]", ...a);

// ───────────────────────────────────────────── demo selection
function demosDir(override) {
  for (const d of [override, ...DEMO_DIRS]) if (d && fs.existsSync(d)) return d;
  throw new Error("no demos directory found; pass --dir <dir>");
}
function listDemos(dir) {
  // filenames start with the game's start time (YYYY-MM-DD_HH-MM-SS-mmm), so a name sort is a time sort
  return fs.readdirSync(dir).filter(f => f.toLowerCase().endsWith(".sdfz")).sort().reverse();
}
async function demoHeader(file) {
  const DemoParser = loadDemoParser();
  const demo = await new DemoParser({ skipPackets: true }).parseDemo(file);
  const info = demo.info || {}, meta = info.meta || {};
  const players = (info.players || []).filter(Boolean);
  const byAlly = {};
  for (const p of players) byAlly[p.allyTeamId] = (byAlly[p.allyTeamId] || 0) + 1;
  const matchup = Object.values(byAlly).sort((a, b) => b - a).join("v") || "0";
  return { file, players: players.length, ais: (info.ais || []).length, matchup, meta,
    durationMin: meta.durationMs ? meta.durationMs / 60000 : null };
}
async function findDemo(spec, dirOverride) {
  if (spec && spec !== "latest" && spec !== "8v8" && fs.existsSync(spec)) return path.resolve(spec);
  const dir = demosDir(dirOverride);
  if (spec && spec !== "latest" && !/^\d+v\d+$/.test(spec)) {
    const hit = listDemos(dir).find(f => f === spec || f.includes(spec));
    if (!hit) throw new Error(`no demo matching "${spec}" in ${dir}`);
    return path.join(dir, hit);
  }
  const want = spec && /^\d+v\d+$/.test(spec) ? spec : (spec === "latest" ? null : "8v8");
  for (const f of listDemos(dir)) {
    const p = path.join(dir, f);
    if (!want) return p;
    let h; try { h = await demoHeader(p); } catch (e) { log(`skip ${f}: ${e.message}`); continue; }
    if (h.matchup === want && h.ais === 0) return p;
  }
  throw new Error(`no ${want} demo found in ${dir}`);
}

// ───────────────────────────────────────────── engine
function engineFor(meta, override) {
  const engDir = path.join(BAR, "engine");
  const available = fs.existsSync(engDir) ? fs.readdirSync(engDir) : [];
  const candidates = override ? [override] : [`recoil_${meta.engine}`, String(meta.engine || "")];
  for (const c of candidates) if (c && fs.existsSync(path.join(engDir, c, "spring-headless.exe"))) return c;
  throw new Error(`no spring-headless for ${candidates.join(" / ")}; installed: ${available.join(", ")}`);
}

// ───────────────────────────────────────────── headless replay, stopped once the def block is complete
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function killTree(pid) { try { execFileSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" }); } catch (_) {} }

/** Read the leading `unit_def` block of an actions.json. Returns { defs, complete } — complete once a
 *  non-def line follows the block (the widget writes all defs at frame 0, then gameplay events). */
function readDefBlock(actionsPath) {
  const defs = new Map(); let complete = false;
  if (!fs.existsSync(actionsPath)) return { defs, complete };
  const text = fs.readFileSync(actionsPath, "utf8");
  for (const ln of text.split(/\r?\n/)) {
    if (!ln) continue;
    if (!ln.includes('"unit_def"')) { if (defs.size > 50) { complete = true; break; } continue; }
    let e; try { e = JSON.parse(ln); } catch { continue; }
    if (e.action !== "unit_def") continue;
    const { action, frame, ...def } = e;
    defs.set(def.defName, def);
  }
  return { defs, complete };
}

async function replayForDefs(demoFile, engine, { timeoutMs = 300000, pollMs = 1000, full = false } = {}) {
  const eng = path.join(BAR, "engine", engine);
  const exe = path.join(eng, "spring-headless.exe");
  const wd = path.join(os.tmpdir(), "gex_harness", "defs_" + path.basename(demoFile).replace(/[^\w.-]/g, "_"));
  try { fs.rmSync(wd, { recursive: true, force: true }); } catch (_) {}
  fs.mkdirSync(path.join(wd, "LuaUI", "Widgets"), { recursive: true });
  fs.mkdirSync(path.join(wd, "LuaUI", "Config"), { recursive: true });
  fs.copyFileSync(path.join(VENDOR, "gex.lua"), path.join(wd, "LuaUI", "Widgets", "gex.lua"));
  fs.copyFileSync(path.join(VENDOR, "BYAR.lua"), path.join(wd, "LuaUI", "Config", "BYAR.lua"));
  const hostPort = 50100 + (process.pid % 4900);
  const script = path.join(wd, "_script.txt");
  fs.writeFileSync(script, `[game] {\ndemofile=${demoFile};HostPort=${hostPort};\n}`, "ascii");
  log(`replaying ${path.basename(demoFile)} on ${engine} (${full ? "full replay" : "until the unit_def block is complete"}) ...`);
  const outFd = fs.openSync(path.join(wd, "stdout.txt"), "w"), errFd = fs.openSync(path.join(wd, "stderr.txt"), "w");
  const child = spawn(exe, ["--write-dir", wd, script], { cwd: eng, env: { ...process.env, SPRING_DATADIR: `${wd};${BAR}` }, stdio: ["ignore", outFd, errFd] });
  const actions = path.join(wd, "actions.json");
  const t0 = Date.now();
  let exited = false, reason = null;
  child.on("exit", () => { exited = true; });
  let lastCount = 0, stableSince = null;
  while (!exited) {
    await sleep(pollMs);
    const { defs, complete } = readDefBlock(actions);
    if (defs.size !== lastCount) { lastCount = defs.size; stableSince = Date.now(); log(`  ${defs.size} defs so far (${((Date.now() - t0) / 1000).toFixed(0)} s)`); }
    if (!full && complete) { reason = `unit_def block complete (${defs.size} defs)`; break; }
    if (!full && defs.size > 50 && stableSince && Date.now() - stableSince > 15000) { reason = `def count stable at ${defs.size} for 15 s`; break; }
    if (Date.now() - t0 > timeoutMs) { reason = `hard timeout ${timeoutMs} ms`; break; }
  }
  if (!exited) { log(`stopping replay — ${reason}`); killTree(child.pid); await sleep(500); }
  fs.closeSync(outFd); fs.closeSync(errFd);
  const { defs } = readDefBlock(actions);
  if (!defs.size) throw new Error(`no unit_def lines produced${reason ? ` (${reason})` : ""}; see ${path.join(wd, "stdout.txt")}`);
  return { defs: [...defs.values()], actions, seconds: (Date.now() - t0) / 1000 };
}

// ───────────────────────────────────────────── prior data (for factions the new game did not load)
/** Every def the current data layer knows, in econ_model.json `engineDefs` order (later wins), keyed by
 *  defName → { def, from }. The file being written is excluded so a re-harvest of the same demo is clean. */
function loadPriorDefs(excludeOut) {
  const econ = JSON.parse(fs.readFileSync(path.join(HERE, "econ_model.json"), "utf8"));
  const prior = new Map();
  const add = (d, from) => { const { action, frame, carriedFrom, ...def } = d; prior.set(def.defName, { def, from }); };
  for (const src of econ.engineDefs) {
    let files;
    if (src.glob) {
      const parts = src.glob.split("/"); const pat = parts.pop(); const dir = path.join(ROOT, ...parts);
      const re = new RegExp("^" + pat.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$");
      files = fs.existsSync(dir) ? fs.readdirSync(dir).filter(f => re.test(f)).sort().map(f => path.join(dir, f)) : [];
      files = files.filter(f => path.resolve(f) !== path.resolve(excludeOut));
      if ((src.pick || "latest") === "latest") files = files.slice(-1);
    } else files = [path.join(ROOT, ...src.path.split("/"))];
    for (const f of files) {
      if (!fs.existsSync(f)) continue;
      const from = path.relative(ROOT, f).replace(/\\/g, "/");
      if (src.format === "defs-array") { const d = JSON.parse(fs.readFileSync(f, "utf8")); for (const e of (Array.isArray(d) ? d : d.defs)) add(e, from); }
      else for (const [, d] of readDefBlock(f).defs) add(d, from);
    }
  }
  return prior;
}

// ───────────────────────────────────────────── main
function parseArgs(argv) {
  const a = { demo: "8v8", dir: null, engine: null, out: null, timeout: 300000, full: false, list: null };
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t === "--demo") a.demo = argv[++i];
    else if (t === "--dir") a.dir = argv[++i];
    else if (t === "--engine") a.engine = argv[++i];
    else if (t === "--out") a.out = argv[++i];
    else if (t === "--timeout") a.timeout = Number(argv[++i]);
    else if (t === "--full") a.full = true;
    else if (t === "--list") a.list = Number(argv[i + 1]) || (argv[++i], 20);
    else if (!t.startsWith("--")) a.demo = t;
  }
  return a;
}
function stampFromDemo(demoFile) {
  const m = path.basename(demoFile).match(/^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})/);
  if (m) return { stamp: `${m[1]}${m[2]}${m[3]}_${m[4]}${m[5]}${m[6]}`, started: `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}` };
  const d = new Date(fs.statSync(demoFile).mtimeMs);
  const p = n => String(n).padStart(2, "0");
  return { stamp: `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`, started: d.toISOString() };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.list) {
    const dir = demosDir(args.dir);
    for (const f of listDemos(dir).slice(0, args.list)) {
      try { const h = await demoHeader(path.join(dir, f)); console.log(`${f} | ${h.players}p ${h.matchup}${h.ais ? ` +${h.ais}ai` : ""} ${h.durationMin ? h.durationMin.toFixed(1) + "min" : "?"} engine=${h.meta.engine} ${h.meta.map}`); }
      catch (e) { console.log(`${f} | ERROR ${e.message}`); }
    }
    return;
  }
  const demoFile = await findDemo(args.demo, args.dir);
  const h = await demoHeader(demoFile);
  log(`demo: ${path.basename(demoFile)} — ${h.players} players ${h.matchup}, ${h.durationMin ? h.durationMin.toFixed(1) : "?"} min, ${h.meta.map}, game ${h.meta.game}, engine ${h.meta.engine}`);
  const engine = engineFor(h.meta, args.engine);
  const { defs, actions, seconds } = await replayForDefs(demoFile, engine, { timeoutMs: args.timeout, full: args.full });
  defs.sort((a, b) => (a.defID || 0) - (b.defID || 0));
  const { stamp, started } = stampFromDemo(demoFile);
  const out = args.out ? path.resolve(args.out) : path.join(HERE, `units_${stamp}.json`);
  // which factions the engine had loaded (Legion is a lobby option: leg* defs only exist when it was enabled)
  const factions = {};
  for (const d of defs) { const f = (d.defName.match(/^(arm|cor|leg)/) || [, "other"])[1]; factions[f] = (factions[f] || 0) + 1; }
  const have = new Set(defs.map(d => d.defName));
  const missing = ["arm", "cor", "leg"].filter(f => !have.has(`${f}com`));   // a faction is loaded iff its commander def exists
  // A faction the lobby did not enable (usually Legion) is pulled through from the previous data so this
  // file stays complete: the game's own defs win, the carried defs are tagged with where they came from.
  const carried = {};
  if (missing.length) {
    const prior = loadPriorDefs(out);
    for (const f of missing) {
      let n = 0;
      for (const [name, d] of prior) {
        if (!name.startsWith(f) || have.has(name)) continue;
        defs.push({ ...d.def, carriedFrom: d.from });
        have.add(name); n++;
        carried[f] = carried[f] || { count: 0, from: new Set() };
        carried[f].count++; carried[f].from.add(d.from);
      }
      log(`note: no ${f} defs in this game (faction not enabled in the lobby) — carried ${n} ${f}* defs through from ${carried[f] ? [...carried[f].from].join(", ") : "nothing (no prior data)"}`);
    }
    for (const f of Object.keys(carried)) carried[f].from = [...carried[f].from];
    defs.sort((a, b) => (a.defID || 0) - (b.defID || 0));
  }
  const doc = {
    source: "bar-calc/harvest_defs.mjs — headless re-run of the demo below; every unit/structure/object def the engine reports at frame 0",
    demo: path.basename(demoFile), demoStarted: started, matchup: h.matchup, players: h.players, map: h.meta.map,
    engine, game: h.meta.game, captured: new Date().toISOString(), replaySeconds: Math.round(seconds), actionsJson: actions,
    factions, factionsMissing: missing, carried,
    note: "energyUpkeep<0 means the unit PRODUCES energy; extractsMetal is the per-metalspot multiplier (÷0.001); buildTime is build work in BP-seconds. Defs with `carriedFrom` belong to a faction this game did not load and were pulled through from that earlier file. Read by bar-calc/econ_data.py and splendid_buildSimulator.js through econ_model.json `engineDefs` (newest units_*.json wins).",
    count: defs.length, defs,
  };
  fs.writeFileSync(out, JSON.stringify(doc, null, 1) + "\n", "utf8");
  log(`wrote ${defs.length} defs -> ${out} (${(fs.statSync(out).size / 1024).toFixed(0)} KB, ${seconds.toFixed(0)} s)`);
  console.log(JSON.stringify({ out, count: defs.length, demo: path.basename(demoFile), engine, game: h.meta.game, map: h.meta.map, matchup: h.matchup, factions, factionsMissing: missing, carried }));
}

main().catch(e => { console.error("✘ " + (e.stack || e.message)); process.exit(1); });

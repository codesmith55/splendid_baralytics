// replay_demo.mjs — replay a BAR demo headlessly and return the actions.json it produced.
//
//   node bar-calc/replay_demo.mjs [--demo 1v0|latest|8v8|<path|filename>] [--dir <demosDir>]
//                                 [--engine recoil_2026.07.04] [--timeout ms] [--idle ms] [--reuse]
//   node bar-calc/replay_demo.mjs --list [N] [--only 1v0]
//
//   --demo 1v0      newest SKIRMISH (one human, no AI) — the clean test case: no opponent noise
//   --demo NvN      newest game with that matchup (8v8, 1v1, ...)
//   --demo latest   newest demo of any shape
//
// Unlike harvest_defs.mjs (which stops as soon as the frame-0 unit_def block is complete), this
// runs the whole replay, so the output carries gameplay events: unit lifecycle, team_stats, and
// the patched widget's `reclaim_sample`. Feeds `python bar-calc/bar_unified.py --reclaim-runs`.
//
// A skirmish has no opponent, so spring-headless free-runs forever once the recorded commands end;
// the shared headless runner's idle watchdog stops it. Last stdout line is a JSON summary.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { runHeadless } from "../gex_research/process/lib/headless.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const BAR = process.env.BAR_DATA || "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data";
const DEMOS = process.env.BAR_DEMOS || path.join(BAR, "demos");
const require = createRequire(import.meta.url);
const log = (...a) => console.error("[replay]", ...a);

function DemoParser() {
  for (const id of ["sdfz-demo-parser", path.join(ROOT, "gex_research", "tools", "demoparser", "node_modules", "sdfz-demo-parser")]) {
    try { return require(id).DemoParser; } catch (_) { /* next */ }
  }
  throw new Error("sdfz-demo-parser not found");
}
const listDemos = () => fs.readdirSync(DEMOS).filter(f => f.toLowerCase().endsWith(".sdfz")).sort().reverse();

async function header(file) {
  const P = DemoParser();
  const d = await new P({ skipPackets: true }).parseDemo(file);
  const i = d.info || {}, m = i.meta || {};
  const players = (i.players || []).filter(Boolean);
  const ais = (i.ais || []).length;
  const byAlly = {};
  for (const p of players) byAlly[p.allyTeamId] = (byAlly[p.allyTeamId] || 0) + 1;
  const sizes = Object.values(byAlly).sort((a, b) => b - a);
  // a skirmish is one human against nothing: a single populated ally team and no AI
  const matchup = players.length === 1 && ais === 0 ? "1v0" : (sizes.join("v") || "0");
  return { file, players: players.length, ais, matchup, meta: m,
           durationMin: m.durationMs ? m.durationMs / 60000 : null };
}

async function pick(spec) {
  if (spec && spec !== "latest" && !/^\d+v\d+$/.test(spec)) {
    if (fs.existsSync(spec)) return path.resolve(spec);
    const hit = listDemos().find(f => f === spec || f.includes(spec));
    if (!hit) throw new Error(`no demo matching "${spec}" in ${DEMOS}`);
    return path.join(DEMOS, hit);
  }
  const want = spec === "latest" ? null : (spec || "1v0");
  for (const f of listDemos()) {
    const p = path.join(DEMOS, f);
    if (!want) return p;
    let h; try { h = await header(p); } catch { continue; }
    if (h.matchup === want) return p;
  }
  throw new Error(`no ${want} demo in ${DEMOS}`);
}

function engineFor(meta, override) {
  const dir = path.join(BAR, "engine");
  for (const c of override ? [override] : [`recoil_${meta.engine}`, String(meta.engine || "")]) {
    if (c && fs.existsSync(path.join(dir, c, "spring-headless.exe"))) return c;
  }
  throw new Error(`no spring-headless for engine ${meta.engine}`);
}

const arg = (k, d) => { const i = process.argv.indexOf(k); return i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith("--") ? process.argv[i + 1] : d; };
const has = k => process.argv.includes(k);

async function main() {
  if (has("--list")) {
    const n = Number(arg("--list", 20)) || 20;
    const only = arg("--only", null);
    let shown = 0;
    for (const f of listDemos()) {
      if (shown >= n) break;
      let h; try { h = await header(path.join(DEMOS, f)); } catch { continue; }
      if (only && h.matchup !== only) continue;
      const kb = (fs.statSync(path.join(DEMOS, f)).size / 1024).toFixed(0);
      console.log(`${h.matchup.padEnd(5)} ${String(kb).padStart(5)}KB ${(h.durationMin ? h.durationMin.toFixed(1) + "min" : "   ?   ").padStart(7)}  ${String(h.meta.map).slice(0, 26).padEnd(26)} ${f}`);
      shown++;
    }
    return;
  }
  const demo = await pick(arg("--demo", "1v0"));
  const h = await header(demo);
  const engine = engineFor(h.meta, arg("--engine", null));
  log(`${path.basename(demo)} — ${h.matchup}, ${h.players} player(s), ${h.meta.map}, engine ${h.meta.engine}`);
  const t0 = Date.now();
  const actions = runHeadless({
    demoFile: demo, engine, vendorDir: path.join(ROOT, "gex_research", "vendor"),
    timeoutMs: Number(arg("--timeout", 420000)), idleMs: Number(arg("--idle", 25000)),
    reuseExisting: has("--reuse"),
  });
  const size = fs.statSync(actions).size;
  const hasSamples = fs.readFileSync(actions, "utf8").includes('"reclaim_sample"');
  if (!hasSamples) log("WARNING: no reclaim_sample events — is the SPLENDID patch still in gex_research/vendor/gex.lua?");
  log(`done in ${((Date.now() - t0) / 1000).toFixed(0)}s -> ${actions} (${(size / 1024).toFixed(0)} KB)`);
  console.log(JSON.stringify({ actions, demo: path.basename(demo), matchup: h.matchup,
                               map: h.meta.map, engine, reclaimSamples: hasSamples }));
}

main().catch(e => { console.error("x " + (e.stack || e.message)); process.exit(1); });

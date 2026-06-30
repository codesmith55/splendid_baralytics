#!/usr/bin/env node
// run.mjs — execute ONE calculation run from a run-config JSON.
//   node process/run.mjs metrics/runs/run-001-economy-composition.json
// Reads which metrics + situations to compute over which replay, runs them, writes JSON + HTML.
import fs from "node:fs";
import path from "node:path";
import { parseActions } from "./lib/parseActions.mjs";
import { buildContext } from "./lib/context.mjs";
import { loadRoster } from "./lib/roster.mjs";
import { runHeadless } from "./lib/headless.mjs";
import { loadMetricModule, loadSituationModule, paths } from "./lib/registry.mjs";
import { renderHtml } from "./lib/chart.mjs";

const { HERE, ROOT } = paths();
const VENDOR = path.join(ROOT, "vendor");
const DEMOPARSER = path.join(ROOT, "tools", "demoparser");

function resolveRun(arg) {
  const runsDir = path.join(ROOT, "metrics", "runs");
  if (!arg) { // default: the lowest-numbered run config
    const f = fs.readdirSync(runsDir).filter(x => x.endsWith(".json")).sort()[0];
    return path.join(runsDir, f);
  }
  const direct = path.resolve(arg);
  if (fs.existsSync(direct)) return direct;
  const files = fs.readdirSync(runsDir).filter(x => x.endsWith(".json"));
  const hit = files.find(f => f === arg || f === `${arg}.json`)
    || files.find(f => f.startsWith(`run-${arg}`)) // e.g. "001" -> run-001-*.json
    || files.find(f => f.includes(arg));           // e.g. "economy"
  if (!hit) throw new Error(`no run config matches '${arg}' in metrics/runs/ (have: ${files.join(", ")})`);
  return path.join(runsDir, hit);
}

async function main() {
  const cfgPath = resolveRun(process.argv[2]);
  const cfg = JSON.parse(fs.readFileSync(cfgPath, "utf8"));
  const base = path.dirname(cfgPath);
  const rel = p => (p ? path.resolve(base, p) : null);
  console.log(`▶ run '${cfg.runId}'  (${cfgPath})`);

  // 1. obtain actions.json (reuse existing, or run headless first)
  let actionsFile;
  if (cfg.input.source === "headless") {
    actionsFile = runHeadless({ demoFile: cfg.input.demoFile, engine: cfg.input.engine, vendorDir: VENDOR, reuseExisting: cfg.input.reuseExisting ?? false });
  } else {
    actionsFile = rel(cfg.input.actionsFile);
    if (!fs.existsSync(actionsFile)) throw new Error(`actionsFile not found: ${actionsFile}`);
  }

  // 2. parse + roster + context
  const parsed = parseActions(actionsFile);
  console.log(`  parsed ${parsed.meta.eventCount} events · ${parsed.meta.teams.length} teams · ${parsed.meta.unitDefCount} unit defs`);
  const roster = cfg.roster?.source === "none"
    ? new Map()
    : loadRoster({ demoFile: cfg.input.demoFile, demoparserDir: DEMOPARSER });
  if (roster.size) console.log(`  roster: ${roster.size} players named (demo header)`);
  else console.log(`  roster: none — using commander-spawn start positions + inferred allies`);

  const primaryParams = mergeParams(cfg, cfg.metrics[0]);
  const ctx = buildContext(parsed, { params: primaryParams, sampling: cfg.sampling, roster });

  // 3. metrics
  const results = {};
  for (const m of cfg.metrics) {
    const { entry, mod } = await loadMetricModule(m.id);
    const params = mergeParams(cfg, m, entry);
    const res = mod.compute(ctx, params);
    res.commanderValue = params.commanderValue ?? 1200;
    results[m.id] = res;
    console.log(`  ✓ metric '${m.id}' → ${res.teams.length} teams × ${res.series[res.teams[0]]?.length || 0} samples`);
  }
  const primary = results[cfg.metrics[0].id];

  // 4. situations (applied to the primary metric)
  const situationOut = {};
  for (const s of cfg.situations || []) {
    const { mod } = await loadSituationModule(s.id);
    situationOut[s.id] = mod.apply(primary, ctx, s.params || {});
    const r = situationOut[s.id];
    console.log(`  ✓ situation '${s.id}'${r.pairCount != null ? ` → ${r.pairCount} mirror pairs` : ""}`);
  }

  // 5. outputs
  const outDir = rel(cfg.output?.dir || "./output");
  fs.mkdirSync(outDir, { recursive: true });
  const formats = cfg.output?.formats || ["json"];
  write(path.join(outDir, "metrics.json"), results);
  write(path.join(outDir, "situations.json"), situationOut);
  write(path.join(outDir, "context.json"), {
    meta: parsed.meta,
    startPos: Object.fromEntries(ctx.startPos),
    allyOf: Object.fromEntries(ctx.allyOf),
    roster: Object.fromEntries(ctx.roster),
    center: ctx.center,
  });
  if (formats.includes("html")) {
    const perUser = situationOut.per_user
      ? { ...situationOut.per_user, commanderValue: primary.commanderValue }
      : { users: primary.teams.map(tm => ({ teamID: tm, user: `User of team ${tm}`, allyTeam: ctx.allyOf.get(tm), final: primary.final[tm], peak: primary.peak?.[tm] ?? primary.final[tm], series: primary.series[tm] })), commanderValue: primary.commanderValue };
    const html = renderHtml({ run: cfg, meta: parsed.meta, perUser, mirror: situationOut.mirror_by_start_position || null, selfReclaim: results.self_reclaim || null });
    fs.writeFileSync(path.join(outDir, "report.html"), html);
    console.log(`  ✓ wrote report.html`);
  }
  console.log(`✔ done → ${outDir}`);
}

function mergeParams(cfg, metricCfg, catalogEntry) {
  return {
    ...(catalogEntry?.params || {}),
    ...(metricCfg?.params || {}),
    sampling: { ...(catalogEntry?.params?.sampling || {}), ...(cfg.sampling || {}), ...(metricCfg?.params?.sampling || {}) },
  };
}
function write(p, obj) { fs.writeFileSync(p, JSON.stringify(obj, null, 2)); }

main().catch(e => { console.error("✘ " + (e.stack || e.message)); process.exit(1); });

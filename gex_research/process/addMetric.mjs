#!/usr/bin/env node
// addMetric.mjs — register a NEW metric from a criteria JSON, append to metrics/catalog.json,
// and scaffold an implementation module.  Usage:
//   node process/addMetric.mjs path/to/metric-criteria.json
//
// Criteria JSON shape (minimum):
// {
//   "id": "snake_case_id",                 // required, unique
//   "title": "human title",                // required
//   "granularity": "team-per-time",        // team-per-time | team-final | player | global
//   "value": { "formula": "metal_plus_energy_div_70", "overrides": { "commander": 1200 } },
//   "categories": { "<bucket>": { "desc": "...", "detect": {...}, "seedNames": [...] } },  // optional
//   "inputs": ["unit_def","unit_created", ...],
//   "params": { ...defaults... },
//   "module": "optional_existing_module.mjs"   // omit to scaffold a new one
// }
import fs from "node:fs";
import path from "node:path";
import { paths, loadCatalog } from "./lib/registry.mjs";

const { HERE, ROOT } = paths();
const criteria = JSON.parse(fs.readFileSync(path.resolve(process.argv[2]), "utf8"));

for (const k of ["id", "title"]) if (!criteria[k]) die(`criteria missing required field '${k}'`);
if (!/^[a-z][a-z0-9_]*$/.test(criteria.id)) die(`id must be snake_case: '${criteria.id}'`);

const catalogPath = path.join(ROOT, "metrics", "catalog.json");
const catalog = loadCatalog();
if (catalog.metrics.some(m => m.id === criteria.id)) die(`metric '${criteria.id}' already exists in catalog`);

const moduleName = criteria.module || `${criteria.id}.mjs`;
const modulePath = path.join(HERE, "metrics", moduleName);
if (!fs.existsSync(modulePath)) { fs.writeFileSync(modulePath, scaffold(criteria)); console.log(`scaffolded lib/metrics/${moduleName}`); }
else console.log(`reusing existing module lib/metrics/${moduleName}`);

const entry = {
  id: criteria.id, title: criteria.title, created: today(), status: "draft",
  granularity: criteria.granularity || "team-per-time", module: moduleName,
  value: criteria.value || { formula: "metal_plus_energy_div_70" },
  ...(criteria.categories ? { categories: criteria.categories } : {}),
  inputs: criteria.inputs || ["unit_def", "unit_created", "unit_killed"],
  params: criteria.params || {},
};
catalog.metrics.push(entry);
catalog.version = (catalog.version || 0) + 1;
catalog.updated = today();
fs.writeFileSync(catalogPath, JSON.stringify(catalog, null, 2));
console.log(`✔ added metric '${criteria.id}' to catalog.json (status=draft)`);
console.log(`  next: implement compute() in lib/metrics/${moduleName}, set status=active, then reference id '${criteria.id}' in a run config.`);

function scaffold(c) {
  return `// ${c.id}.mjs — ${c.title}
// Auto-scaffolded by addMetric.mjs. Implement compute() then set status=active in catalog.json.
import { buildDefIndex, unitValue, classifyDef } from "../classify.mjs";

export const meta = {
  id: ${JSON.stringify(c.id)},
  title: ${JSON.stringify(c.title)},
  granularity: ${JSON.stringify(c.granularity || "team-per-time")},
  inputs: ${JSON.stringify(c.inputs || ["unit_def", "unit_created", "unit_killed"])},
};

// ctx: { all, byAction, defMap, defIndex, meta, startPos, roster, allyOf, center, sampling }
// return: { metricId, teams, series: { team: [...] }, final: { team: snap } }
export function compute(ctx, params = {}) {
  const defIndex = buildDefIndex(ctx.defMap, params);
  const teams = ctx.meta.teams.slice();
  // TODO: implement '${c.id}'. See lib/metrics/economy_composition.mjs for the reference pattern
  // (frame-sorted lifecycle walk -> per-team running sums -> snapshot at sample frames).
  const series = {}, final = {};
  for (const t of teams) { series[t] = []; final[t] = null; }
  return { metricId: ${JSON.stringify(c.id)}, teams, series, final, params };
}
`;
}

function today() { return new Date().toISOString().slice(0, 10); }
function die(m) { console.error("✘ " + m); process.exit(1); }

#!/usr/bin/env node
// addSituation.mjs — register a NEW situation (a way to slice/pair/compare a metric's output).
//   node process/addSituation.mjs path/to/situation-criteria.json
//
// Criteria JSON shape (minimum):
// {
//   "id": "snake_case_id",        // required, unique
//   "title": "human title",       // required
//   "needs": ["start_positions"], // optional context requirements
//   "params": { ... },            // optional default params
//   "module": "optional.mjs"      // omit to scaffold
// }
import fs from "node:fs";
import path from "node:path";
import { paths, loadSituations } from "./lib/registry.mjs";

const { HERE, ROOT } = paths();
const c = JSON.parse(fs.readFileSync(path.resolve(process.argv[2]), "utf8"));
for (const k of ["id", "title"]) if (!c[k]) die(`criteria missing required field '${k}'`);
if (!/^[a-z][a-z0-9_]*$/.test(c.id)) die(`id must be snake_case: '${c.id}'`);

const sitPath = path.join(ROOT, "metrics", "situations.json");
const sits = loadSituations();
if (sits.situations.some(s => s.id === c.id)) die(`situation '${c.id}' already exists`);

const moduleName = c.module || `${c.id}.mjs`;
const modulePath = path.join(HERE, "situations", moduleName);
if (!fs.existsSync(modulePath)) { fs.writeFileSync(modulePath, scaffold(c)); console.log(`scaffolded lib/situations/${moduleName}`); }
else console.log(`reusing existing module lib/situations/${moduleName}`);

sits.situations.push({ id: c.id, title: c.title, created: today(), status: "draft", module: moduleName, needs: c.needs || [], params: c.params || {} });
sits.version = (sits.version || 0) + 1;
sits.updated = today();
fs.writeFileSync(sitPath, JSON.stringify(sits, null, 2));
console.log(`✔ added situation '${c.id}' to situations.json (status=draft)`);
console.log(`  next: implement apply() in lib/situations/${moduleName}, set status=active, then reference id '${c.id}' in a run config.`);

function scaffold(c) {
  return `// ${c.id}.mjs — ${c.title}
// Auto-scaffolded by addSituation.mjs. Implement apply() then set status=active in situations.json.
import { label } from "./per_user.mjs";

export const meta = { id: ${JSON.stringify(c.id)}, title: ${JSON.stringify(c.title)}, needs: ${JSON.stringify(c.needs || [])} };

// metricResult: { teams, series, final }    ctx: { startPos, roster, allyOf, center, ... }
export function apply(metricResult, ctx, params = {}) {
  // TODO: implement '${c.id}'. See lib/situations/mirror_by_start_position.mjs for the reference pattern.
  return { situationId: ${JSON.stringify(c.id)}, users: metricResult.teams.map(tm => ({ teamID: tm, user: label(ctx, tm) })) };
}
`;
}

function today() { return new Date().toISOString().slice(0, 10); }
function die(m) { console.error("✘ " + m); process.exit(1); }

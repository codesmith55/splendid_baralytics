// classify_units.mjs — apply the versioned unit taxonomy to a stream's military defs and print
// the tech×class breakdown + coverage. Validates metrics/unit_taxonomy.json against real data.
//
//   node tools/classify_units.mjs <stream.jsonl> [metrics/unit_taxonomy.json]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadTaxonomy, classifyUnit, isSeeded } from "../process/lib/unitType.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const jsonl = process.argv[2];
const taxPath = process.argv[3] || path.join(ROOT, "metrics/unit_taxonomy.json");
if (!jsonl) { console.error("usage: node tools/classify_units.mjs <stream.jsonl> [taxonomy.json]"); process.exit(1); }

const tax = loadTaxonomy(taxPath);
const defs = new Map();
for (const line of fs.readFileSync(jsonl, "utf8").split("\n")) {
  if (!line.includes('"unit_def"')) continue;
  let d; try { d = JSON.parse(line); } catch { continue; }
  if (d.action !== "unit_def" || d.bucket !== "military") continue;
  if (!defs.has(d.defName)) defs.set(d.defName, d);
}

const grid = {};           // "class" -> { "T1": [names], ... }
let seeded = 0;
for (const d of defs.values()) {
  const c = classifyUnit(d, tax);
  if (isSeeded(d, tax)) seeded++;
  (grid[c.cls] = grid[c.cls] || {});
  const k = "T" + c.tech;
  (grid[c.cls][k] = grid[c.cls][k] || []).push(d.name || d.defName);
}

console.log(`taxonomy v${tax.version}  —  ${defs.size} military defs  —  ${seeded} seeded, ${defs.size - seeded} by heuristic\n`);
const order = Object.keys(tax.classes).filter(c => grid[c]);
for (const cls of order) {
  const sym = tax.classes[cls].symbol;
  const tiers = grid[cls];
  const counts = ["T1", "T2", "T3"].map(t => `${t}:${(tiers[t] || []).length}`).join("  ");
  console.log(`${sym} ${cls.padEnd(8)} ${counts}`);
  for (const t of ["T1", "T2", "T3"]) {
    if (tiers[t]) console.log(`    ${t}  ${tiers[t].slice(0, 6).join(", ")}${tiers[t].length > 6 ? ` … +${tiers[t].length - 6}` : ""}`);
  }
}

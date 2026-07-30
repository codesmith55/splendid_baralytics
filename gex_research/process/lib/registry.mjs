// registry.mjs — resolve metric/situation ids to their modules via the catalog JSONs.
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const ROOT = path.resolve(HERE, "..", ".."); // gex_research/

export function loadCatalog() {
  return readJson(path.join(ROOT, "metrics", "catalog.json"));
}
export function loadSituations() {
  return readJson(path.join(ROOT, "metrics", "situations.json"));
}

export async function loadMetricModule(id) {
  const cat = loadCatalog();
  const entry = cat.metrics.find(m => m.id === id);
  if (!entry) throw new Error(`metric '${id}' not found in catalog.json`);
  const mod = await import(pathToFileURL(path.join(HERE, "metrics", entry.module)).href);
  return { entry, mod };
}

export async function loadSituationModule(id) {
  const sits = loadSituations();
  const entry = sits.situations.find(s => s.id === id);
  if (!entry) throw new Error(`situation '${id}' not found in situations.json`);
  const mod = await import(pathToFileURL(path.join(HERE, "situations", entry.module)).href);
  return { entry, mod };
}

export function readJson(p) { return JSON.parse(fs.readFileSync(p, "utf8")); }
export function paths() { return { HERE, ROOT }; }

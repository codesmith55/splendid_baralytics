// unitType.mjs — classify a military unit def into a (tech tier, class/role) using a versioned
// taxonomy (metrics/unit_taxonomy.json). Tech -> color, class -> symbol. Pure + dependency-free.
//
// Seed-first, then field heuristics, then cost bands — so it works on rich defs (gex dump, in-engine
// UnitDefs) AND degrades gracefully on the slim live unit_def (name + cost only).
import fs from "node:fs";

export function loadTaxonomy(path) { return JSON.parse(fs.readFileSync(path, "utf8")); }
export function taxonomyVersion(tax) { return tax.version; }

const num = x => (typeof x === "number" && isFinite(x) ? x : 0);

/** Tech tier 1|2|3. */
export function techOf(def, tax) {
  const seed = tax.seeds[def.defName];
  if (seed && seed.tech) return seed.tech;
  const tl = num(def.techLevel) || num(def.customParams?.techlevel);
  if (tl >= 1 && tl <= 3) return tl;
  const m = num(def.metalCost);
  if (m >= tax.tech.t3CostFloor) return 3;
  if (m >= tax.tech.t2CostFloor) return 2;
  return 1;
}

/** Class/role key (spam|raider|main|brawler|arty|skirm|aa|scout|other). */
export function classOf(def, tax) {
  const seed = tax.seeds[def.defName];
  if (seed && seed.class) return seed.class;
  const h = tax.heuristics, m = num(def.metalCost);
  // air-only weapon -> AA
  if (def.weaponTargetsAir === true && def.weaponTargetsGround === false) return "aa";
  // (near) unarmed + fast -> scout
  const range = num(def.attackRange) || num(def.maxRange) || num(def.maxWeaponRange);
  const spd = num(def.speed);
  if (range <= 0 && spd > 0) return "scout";
  if (m <= h.spamCostCeil) return "spam";
  if (def.highTrajectory === true || def.highTrajectory === 1) return "arty";
  if (range >= h.artyRange && spd > 0 && spd <= h.artySpeed) return "arty";
  if (range >= h.skirmRange && spd >= h.skirmSpeed) return "skirm";
  if (range > 0 && range <= h.brawlerRange && m >= h.brawlerCost) return "brawler";
  return "main";
}

/** Full classification with display attributes. */
export function classifyUnit(def, tax) {
  const cls = classOf(def, tax), tech = techOf(def, tax);
  const c = tax.classes[cls] || tax.classes.other;
  return { cls, tech, symbol: c.symbol, label: c.label, color: tax.tech.colors[String(tech)] };
}

/** Whether a def was matched by an explicit seed (vs heuristics) — for taxonomy coverage reporting. */
export function isSeeded(def, tax) { return !!tax.seeds[def.defName]; }

// classify.mjs — map a unit definition into an economy category + compute its value.
// Categories: build_power, economy, infrastructure, military, other. (storage is resource-based, handled in the metric.)
// Detection is field-driven (robust across patches) with the catalog's seedNames as anchors.

export const BUCKETS = ["build_power", "economy", "infrastructure", "military", "storage", "other"];

/** value of one unit def: metalCost + energyCost/70 (default) or metal only. */
export function unitValue(def, params = {}) {
  const formula = params?.value?.formula ?? "metal_plus_energy_div_70";
  const m = num(def.metalCost), e = num(def.energyCost);
  if (formula === "metal") return m;
  return m + e / 70;
}

/**
 * Classify a unit def into a bucket. Returns { bucket, isCommander }.
 * Precedence: commander > infrastructure(factory) > economy > build_power > military > other.
 * Commander is reported separately so the metric can double-count it (build_power + military).
 */
export function classifyDef(def, params = {}) {
  if (!def) return { bucket: "other", isCommander: false };
  if (def.isCommander === true || /com$/.test(def.defName || "")) {
    return { bucket: "commander", isCommander: true };
  }
  if (def.isFactory === true) return { bucket: "infrastructure", isCommander: false };

  const hasWeapon = num(def.weaponCount) > 0 || num(def.attackRange) > 0;
  const isEco =
    num(def.energyProduction) > 0 ||
    num(def.energyUpkeep) < 0 ||        // BAR: some energy producers (armsolar/corsolar) report via negative upkeep
    num(def.windGenerator) > 0 ||
    num(def.tidalGenerator) > 0 ||
    num(def.energyConversionCapacity) > 0 ||
    def.isMetalExtractor === true ||
    num(def.metalMake) > 0 ||
    // dedicated storage building: meaningful storage, no weapon, no build power
    ((num(def.metalStorage) >= 500 || num(def.energyStorage) >= 2000) && !hasWeapon && num(def.buildPower) === 0);
  if (isEco && !hasWeapon) return { bucket: "economy", isCommander: false };

  // workers + construction turrets (mobile or static builders that are not factories)
  if (num(def.buildPower) > 0 && !hasWeapon) return { bucket: "build_power", isCommander: false };

  // combat units, static defenses, and electronic warfare / intel (radar, sonar, jammers,
  // seismic). Field names vary across BAR builds (legacy *Distance* vs modern *Radius*) — probe
  // both so radar/jam bots and towers don't fall through to "other".
  const isIntel =
    num(def.radarDistance) > 0 || num(def.radarRadius) > 0 ||
    num(def.sonarDistance) > 0 || num(def.sonarRadius) > 0 ||
    num(def.radarDistanceJam) > 0 || num(def.jammerRadius) > 0 ||
    num(def.sonarDistanceJam) > 0 || num(def.sonarJamRadius) > 0 ||
    num(def.seismicDistance) > 0 || num(def.seismicRadius) > 0;
  if (hasWeapon || isIntel) return { bucket: "military", isCommander: false };

  // armed builders (e.g. some commanders/T2 cons with a weapon) -> build_power if they build, else other
  if (num(def.buildPower) > 0) return { bucket: "build_power", isCommander: false };

  return { bucket: "other", isCommander: false };
}

/** Precompute defID -> { bucket, value, isCommander } for every known def. */
export function buildDefIndex(defMap, params = {}) {
  const idx = new Map();
  const commanderValue = num(params.commanderValue ?? 1200);
  for (const [defID, def] of defMap) {
    const c = classifyDef(def, params);
    const value = c.isCommander ? commanderValue : unitValue(def, params);
    idx.set(defID, { bucket: c.bucket, isCommander: c.isCommander, value, defName: def.defName });
  }
  return idx;
}

function num(x) { return typeof x === "number" && isFinite(x) ? x : 0; }

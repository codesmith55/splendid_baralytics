// legion_eco.mjs — Legion asynchronous-economy model + MedMex ROI/EROI.
//   node legion_eco.mjs [spotLegmexMps] [builderBP]
// Loads legion_unitdefs.json (saved from a headless re-sim). Defaults are MEASURED
// from replay 2026-06-20_18-53-11-610 (ATG commander cluster): legmex = 1.47 m/s, +7 E.
// builderBP default 275 = legck worker (75) + legnanotc con turret (200).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const DB = JSON.parse(fs.readFileSync(path.join(here, "legion_unitdefs.json"), "utf8"));
const def = (n) => DB.defs.find((d) => d.defName === n);

const SPOT_LEGMEX_MPS = Number(process.argv[2] || 1.825);  // user spot value (legmex ≈ 1.825 m/s)
const MEDMEX_MULT = Number(process.env.MEDMEX_MULT || 2.0); // user: T1.5 = 2x legmex (= 3.65 on a 1.825 spot)
const BUILDER_BP = Number(process.argv[3] || 275);          // legck(75) + legnanotc(200)

const legmex = def("legmex"), medmex = def("legmext15"), moho = def("legmoho");
const solar = def("legsolar"), advsol = def("legadvsol"), com = def("legcom");
const legck = def("legck"), nano = def("legnanotc"), conv = def("legeconv");

// output scales with extractsMetal on the same spot; T1.5 uses the user's 2x (not the def's 2.5x)
const mps = (d) => d === medmex
  ? SPOT_LEGMEX_MPS * MEDMEX_MULT
  : SPOT_LEGMEX_MPS * (d.extractsMetal / legmex.extractsMetal);
// energy a unit nets per second: energyUpkeep<0 => produces; mex eUp is the running E
const netE = (d) => -(d.energyUpkeep || 0);
// build time (s) at a given build power, and the drain rates while building
const buildT = (d, bp = BUILDER_BP) => d.buildTime / bp;
const r2 = (x) => Math.round(x * 100) / 100;
const r1 = (x) => Math.round(x * 10) / 10;

console.log(`# Legion economy model   (spot legmex = ${SPOT_LEGMEX_MPS} m/s, builder BP = ${BUILDER_BP})`);
console.log(`# source: ${DB.source}\n`);

console.log("## Mex & energy units (cost, output, build time @ builder BP)");
const rows = [legmex, medmex, moho, solar, advsol].map((d) => ({
  unit: d.defName, name: d.name, m: d.metalCost, e: d.energyCost, bt: d.buildTime,
  "m/s": d.extractsMetal ? r2(mps(d)) : 0,
  "E/s": r1(netE(d) || (d.energyProduction || 0)),
  "build_s": r1(buildT(d)),
}));
console.table(rows);

// ---- MedMex marginal vs a legmex on the SAME spot ----
const dM = medmex.metalCost - legmex.metalCost;          // +200
const dE = medmex.energyCost - legmex.energyCost;        // +4500
const dMps = mps(medmex) - mps(legmex);                  // +metal/s
const dEs = netE(medmex) - netE(legmex);                 // energy swing (negative = worse)
console.log("\n## MedMex (legmext15) vs legmex on the SAME spot");
console.log(`  extra metal cost ........ +${dM} m`);
console.log(`  extra energy cost ....... +${dE} e`);
console.log(`  extra metal output ...... +${r2(dMps)} m/s  (medmex ${r2(mps(medmex))} vs legmex ${r2(mps(legmex))})`);
console.log(`  energy swing ............ ${r1(dEs)} E/s  (legmex +${netE(legmex)} -> medmex ${netE(medmex)})`);
console.log(`  >> MedMex ROI (metal payback) = ${dM} / ${r2(dMps)} = ${r1(dM / dMps)} s`);

// ---- MedMex EROI: support the energy drain with solars (mex then solars) ----
const drain = -netE(medmex);                              // E/s it consumes (30)
const solarsNeeded = Math.ceil(drain / netE(solar));     // legsolar = +20 E
const supportM = solarsNeeded * solar.metalCost;
const pkgM = dM + supportM;                               // extra metal incl. solar support
const buildSecPkg = buildT(medmex) + solarsNeeded * buildT(solar);
console.log("\n## MedMex EROI  (medmex + solars to cover its drain, from a 275-BP builder)");
console.log(`  drain to cover .......... ${drain} E/s  -> ${solarsNeeded}x legsolar (+${netE(solar)} E each)`);
console.log(`  package extra cost ...... ${dM} (medmex over legmex) + ${supportM} (solars) = ${pkgM} m`);
console.log(`  builder time (pkg) ...... ${r1(buildSecPkg)} s @ ${BUILDER_BP} BP`);
console.log(`  >> MedMex EROI (full payback incl. support) = ${pkgM} / ${r2(dMps)} = ${r1(pkgM / dMps)} s`);

// ---- Opportunity cost: same metal as N legmexes on OPEN spots ----
const nLeg = Math.floor(medmex.metalCost / legmex.metalCost);
console.log("\n## Opportunity cost — MedMex vs spending its metal on more legmexes (open spots)");
console.log(`  1 MedMex = ${medmex.metalCost} m -> ${r2(mps(medmex))} m/s, ${netE(medmex)} E/s`);
console.log(`  ${nLeg}x legmex = ${nLeg * legmex.metalCost} m -> ${r2(nLeg * mps(legmex))} m/s, +${nLeg * netE(legmex)} E/s`);
console.log(`  => MedMex only wins when mex SPOTS are the constraint, not metal.`);

// ===================== per-building ROI / EROI =====================
// Definitions:
//  metal/s        = direct metal income (mexes); 0 for energy/worker
//  netE           = net energy/s (>0 produces, <0 consumes)
//  E->M value     = netE / 70  (converter exchange 70 E : 1 M) -> energy as metal-equiv
//  Metal ROI      = metalCost / (metal/s)                 [pure metal payback, mexes]
//  True ROI       = metalCost / (metal/s + netE/70)       [payback counting energy too]
//  EROI (energy)  = energyCost / netE                     [time to repay build-energy; producers only]
const E2M = 1 / 70;
const WIND_AVG = Number(process.env.WIND_AVG || 11.2);   // measured ATG mean (range 0-16)
function roiRow(d, mMps, label, netEoverride) {
  const netE = netEoverride != null ? netEoverride : (-(d.energyUpkeep || 0) || (d.energyProduction || 0));
  const valRate = mMps + netE * E2M;
  const metalROI = mMps > 0 ? r1(d.metalCost / mMps) : null;
  const trueROI = valRate > 0 ? r1(d.metalCost / valRate) : null;
  const eroi = netE > 0 ? r1(d.energyCost / netE) : null;   // only if it nets energy
  return {
    unit: label, m: d.metalCost, e: d.energyCost,
    "m/s": r2(mMps), "netE": netE,
    "MetalROI_s": metalROI ?? "-",
    "TrueROI_s": trueROI ?? "-",
    "EROI_s": eroi ?? (netE < 0 ? "sink" : "-"),
  };
}
console.log("\n## Per-building ROI / EROI");
const tbl = [
  roiRow(legmex, mps(legmex), "T1 legmex"),
  roiRow(medmex, mps(medmex), "T1.5 legmext15 (MedMex)"),
  roiRow(moho, mps(moho), "T2 legmoho"),
  roiRow(def("legwin"), 0, `legwin (avg wind ${WIND_AVG})`, WIND_AVG),
  roiRow(solar, 0, "legsolar"),
  roiRow(advsol, 0, "legadvsol (legasolar)"),
];
console.table(tbl);
console.log(`  (legwin output is VARIABLE: max ${def("legwin").windGenerator}, ATG avg ${WIND_AVG}, range ~0-16; set WIND_AVG=<n> to recompute)`);

// worker (legbotworker = legck): build-power unit, ROI is throughput-based
{
  const w = legck;
  const netE = -(w.energyUpkeep || 0) || (w.energyProduction || 0);
  const mexBuildS = r1(legmex.buildTime / w.buildPower);                 // time to build one legmex solo
  const throughput = r2(w.buildPower * (legmex.metalCost / legmex.buildTime)); // m/s it can sink into mexes
  // payback: extra mexes it builds repay its metal. continuous mexing, 1 mex per mexBuildS adding spotMps.
  // metal repaid when cumulative extra income * t >= worker metal cost (ignoring mex metal, +walk).
  const paybackS = r1(w.metalCost / (mps(legmex))) ; // ~ once its first mex runs this long it has repaid the worker's metal
  console.log("\n## Worker — legbotworker (legck)  [build-power unit, not direct income]");
  console.log(`  cost ${w.metalCost} m / ${w.energyCost} e, BP ${w.buildPower}, netE +${netE}`);
  console.log(`  builds a legmex solo in ${mexBuildS}s; metal throughput into mexes = ${throughput} m/s`);
  console.log(`  EROI (energy) = ${w.energyCost}/${netE} = ${r1(w.energyCost/netE)}s to repay its build-energy via +${netE}E`);
  console.log(`  BP-ROI (metal): the +${r2(mps(legmex))} m/s mex it builds repays the ${w.metalCost}m worker in ~${paybackS}s of that mex running`);
  console.log(`  -> a worker "pays for itself" once it has added ~${Math.ceil(w.metalCost/legmex.metalCost)} legmexes' worth of income it enabled.`);
}

// ===================== TotalROI: structure + the energy infra to sustain it =====================
// For an energy-DRAINING structure, true cost = its metal + the metal of the energy source that
// covers its -E/s drain. Two variants: backed by legsolar vs legadvsol.
//   legsolar:  155 m / +20 E  -> 7.75 m per E/s   (0 build-energy)
//   legadvsol: 465 m / +100 E -> 4.65 m per E/s
const SOLAR_M_PER_E = solar.metalCost / (-(solar.energyUpkeep)); // 7.75
const ADVSOL_M_PER_E = advsol.metalCost / advsol.energyProduction; // 4.65
function totalROI(d, mMps) {
  const drain = Math.max(0, -( -(d.energyUpkeep || 0) )); // E/s consumed (positive)
  const solarBack = drain * SOLAR_M_PER_E, advBack = drain * ADVSOL_M_PER_E;
  return {
    unit: d.defName, m: d.metalCost, "m/s": r2(mMps), "drain E/s": drain,
    "+solarBacking_m": Math.round(solarBack), "+advsolBacking_m": Math.round(advBack),
    "TotalROI_solar_s": r1((d.metalCost + solarBack) / mMps),
    "TotalROI_advsol_s": r1((d.metalCost + advBack) / mMps),
  };
}
console.log("\n## TotalROI of energy-draining mexes (incl. metal for the energy source)");
console.log(`   (solar = ${r2(SOLAR_M_PER_E)} m per E/s, advsol = ${r2(ADVSOL_M_PER_E)} m per E/s)`);
console.table([ totalROI(medmex, mps(medmex)), totalROI(moho, mps(moho)) ]);
{ // legmex is energy-POSITIVE: it has no backing cost and earns an energy credit instead
  const credS = Math.round(legmex.metalCost - (-(legmex.energyUpkeep)) * SOLAR_M_PER_E);
  const credA = Math.round(legmex.metalCost - (-(legmex.energyUpkeep)) * ADVSOL_M_PER_E);
  console.log(`  legmex: ${r2(mps(legmex))} m/s, +${-(legmex.energyUpkeep)} E (CREDIT) -> effective metal after energy credit: ${credS} (vs solar) / ${credA} (vs advsol); ROI ${r1(legmex.metalCost/mps(legmex))}s`);
}

console.log("\n## Builder facts");
console.log(`  legck worker: ${legck.metalCost} m, ${legck.buildPower} BP, +${netE(legck)||legck.energyProduction} E`);
console.log(`  legnanotc con turret: ${nano.metalCost} m, ${nano.buildPower} BP  ->  worker+turret = ${legck.buildPower + nano.buildPower} BP`);
console.log(`  legmex build @ ${BUILDER_BP}BP = ${r1(buildT(legmex))}s | medmex = ${r1(buildT(medmex))}s | solar = ${r1(buildT(solar))}s`);

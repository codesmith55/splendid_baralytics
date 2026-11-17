// one-off: run headless on the 15:13 demo, print actions.json path + basic cadence.
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { runHeadless } from "../process/lib/headless.mjs";
import { parseActions } from "../process/lib/parseActions.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const vendorDir = path.join(here, "..", "vendor");
const demoFile = "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data/demos/2026-06-10_15-13-08-319_All That Glitters v2.2.3_2025.06.24.sdfz";

const actions = runHeadless({ demoFile, engine: "recoil_2025.06.24", vendorDir, reuseExisting: true, timeoutMs: 600000 });
console.log("ACTIONS:", actions);

const { byAction, defMap, meta } = parseActions(actions);
console.log("meta:", JSON.stringify(meta));
for (const a of ["team_stats", "extra_stat_update", "unit_resources", "unit_created", "wind_update"]) {
  const arr = byAction.get(a) || [];
  const frames = arr.map(e => e.frame).filter(x => typeof x === "number");
  console.log(`${a}: count=${arr.length} frameRange=${frames.length?Math.min(...frames):"-"}..${frames.length?Math.max(...frames):"-"}`);
}

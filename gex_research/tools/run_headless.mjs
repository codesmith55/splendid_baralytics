// run_headless.mjs — run headless on a demo, print actions.json path + cadence.
//   node run_headless.mjs <demo.sdfz> [engine]
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runHeadless } from "../process/lib/headless.mjs";
import { parseActions } from "../process/lib/parseActions.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const vendorDir = path.join(here, "..", "vendor");
const [, , demoFile, engine = "recoil_2025.06.24"] = process.argv;

const actions = runHeadless({ demoFile, engine, vendorDir, reuseExisting: true, timeoutMs: 600000 });
console.log("ACTIONS:", actions);
const { byAction, meta } = parseActions(actions);
console.log("meta:", JSON.stringify(meta));
for (const a of ["team_stats", "extra_stat_update", "unit_created", "factory_unit_created", "unit_killed"]) {
  const arr = byAction.get(a) || [];
  console.log(`${a}: count=${arr.length}`);
}

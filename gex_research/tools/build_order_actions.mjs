// build_order_actions.mjs — accurate opening build order from gex actions.json.
//   node build_order_actions.mjs <actions.json> <maxSec> <teamID,...>
// Combines unit_created (con-built structures/units) + factory_unit_created (factory units),
// excludes the t=0 starting commander. Collapses runs of same def into "def xN @ t0–t1".
import { parseActions } from "../process/lib/parseActions.mjs";

const [, , actionsFile, maxSecArg, teamsArg] = process.argv;
const maxSec = Number(maxSecArg || 300);
const fps = 30;
const teams = (teamsArg || "").split(",").filter(s => s !== "").map(Number);

const { byAction, defMap } = parseActions(actionsFile);
const name = (id) => defMap.get(id)?.defName ?? `def${id}`;
const human = (id) => defMap.get(id)?.name ?? "";
const tstr = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

const COM = new Set([49, 302]); // armcom, corcom

for (const team of teams) {
  const evs = [];
  for (const e of byAction.get("unit_created") ?? [])
    if (e.teamID === team && e.frame / fps <= maxSec && !(e.frame === 0 && COM.has(e.defID)))
      evs.push({ f: e.frame, def: e.defID, src: "con" });
  for (const e of byAction.get("factory_unit_created") ?? [])
    if (e.teamID === team && e.frame / fps <= maxSec)
      evs.push({ f: e.frame, def: e.defID, src: "fac" });
  evs.sort((a, b) => a.f - b.f);

  console.log(`\n===== team ${team} — ${evs.length} units built in 0-${maxSec}s =====`);
  let i = 0;
  while (i < evs.length) {
    let j = i;
    while (j + 1 < evs.length && evs[j + 1].def === evs[i].def && (evs[j + 1].f - evs[j].f) / fps <= 20) j++;
    const n = j - i + 1;
    const t0 = evs[i].f / fps, t1 = evs[j].f / fps;
    const range = n > 1 ? `${tstr(t0)}-${tstr(t1)}` : tstr(t0);
    const d = name(evs[i].def);
    console.log(`  ${range.padEnd(12)} ${d}${n > 1 ? ` x${n}` : ""}   ${human(evs[i].def)}${evs[i].src === "fac" ? " [factory]" : ""}`);
    i = j + 1;
  }
}

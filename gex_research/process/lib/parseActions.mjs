// parseActions.mjs — read a gex actions.json (line-delimited JSON) into grouped events.
// Pure, dependency-free. Works for actions.json or actions.zstd-decompressed text.
import fs from "node:fs";

/** Parse a line-delimited gex action log into { all, byAction, defMap, meta }. */
export function parseActions(actionsFile) {
  const text = fs.readFileSync(actionsFile, "utf8");
  const all = [];
  const byAction = new Map();
  let bad = 0;
  for (const line of text.split("\n")) {
    const s = line.trim();
    if (!s) continue;
    let ev;
    try { ev = JSON.parse(s); } catch { bad++; continue; }
    all.push(ev);
    if (!byAction.has(ev.action)) byAction.set(ev.action, []);
    byAction.get(ev.action).push(ev);
  }

  // defID -> unit definition (rich fields: metalCost, energyCost, buildPower, isFactory, isCommander, canResurrect, ...)
  const defMap = new Map();
  for (const d of byAction.get("unit_def") ?? []) defMap.set(d.defID, d);

  const startEv = (byAction.get("start") ?? [])[0];
  const endEv = (byAction.get("end") ?? [])[0];
  const meta = {
    startFrame: startEv?.frame ?? 0,
    endFrame: endEv?.frame ?? maxFrame(all),
    durationSeconds: endEv?.ingame ?? null,
    realtimeSeconds: endEv?.realtime ?? null,
    mapSizeX: startEv?.mapSizeX ?? null,   // map width  in elmos (from gex.lua Game.mapSizeX)
    mapSizeZ: startEv?.mapSizeZ ?? null,   // map height in elmos (from gex.lua Game.mapSizeZ)
    teams: [...new Set(all.filter(e => e.teamID != null).map(e => e.teamID))].sort((a, b) => a - b),
    unitDefCount: defMap.size,
    eventCount: all.length,
    parseErrors: bad,
  };
  return { all, byAction, defMap, meta };
}

function maxFrame(all) {
  let m = 0;
  for (const e of all) if (typeof e.frame === "number" && e.frame > m) m = e.frame;
  return m;
}

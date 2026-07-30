// roster.mjs — produce team -> {name, faction, skill, allyTeam, startPos} from a demo header.
// Strategy: if a roster JSON (from tools/demoparser) exists next to the demo, load it. Else return
// an empty map (the context falls back to commander-spawn start positions + inferred allies).
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

export function loadRoster({ demoFile, rosterFile, demoparserDir } = {}) {
  // 1. explicit roster file
  if (rosterFile && fs.existsSync(rosterFile)) return fromJson(rosterFile);

  // 2. cached roster beside the demo
  if (demoFile) {
    const cached = demoFile.replace(/\.sdfz$/i, "") + ".roster.json";
    if (fs.existsSync(cached)) return fromJson(cached);

    // 3. run the demo parser on demand (tools/demoparser/parse.mjs <demo> <out>)
    if (demoparserDir && fs.existsSync(path.join(demoparserDir, "parse.mjs")) && fs.existsSync(path.join(demoparserDir, "node_modules"))) {
      const r = spawnSync(process.execPath, [path.join(demoparserDir, "parse.mjs"), demoFile, cached], { encoding: "utf8" });
      if (r.status === 0 && fs.existsSync(cached)) return fromJson(cached);
      else console.warn(`[roster] demo parse failed (${r.status}); falling back to action-log start positions`);
    }
  }
  return new Map();
}

function fromJson(file) {
  const j = JSON.parse(fs.readFileSync(file, "utf8"));
  const map = new Map();
  for (const p of j.players || []) {
    if (p.teamId == null) continue;
    map.set(p.teamId, {
      userId: p.userId ?? null,
      name: p.name ?? null,
      faction: p.faction ?? null,
      skill: p.skill ?? null,
      allyTeam: p.allyTeamId ?? null,
      startPos: p.startPos ?? null,
    });
  }
  return map;
}

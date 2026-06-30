// parse.mjs — extract a normalized roster from a BAR .sdfz demo header.
//   node parse.mjs <demo.sdfz> <out.roster.json>
// Output: { source, map, engine, gameVersion, players: [{ teamId, name, faction, allyTeamId, skill, startPos }] }
import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(import.meta.url);
const { DemoParser } = require("sdfz-demo-parser");

const [, , demoFile, outFile] = process.argv;
if (!demoFile) { console.error("usage: node parse.mjs <demo.sdfz> [out.json]"); process.exit(2); }

const parser = new DemoParser();
const demo = await parser.parseDemo(demoFile);
const info = demo.info || {};
const meta = info.meta || {};

const pick = (o, ...keys) => { for (const k of keys) if (o && o[k] != null) return o[k]; return null; };

const players = [];
for (const p of info.players || []) {
  const sp = pick(p, "startPos", "startpos");
  players.push({
    teamId: pick(p, "teamId", "team"),
    playerId: pick(p, "playerId"),
    userId: pick(p, "userId"),
    name: pick(p, "name", "username"),
    faction: pick(p, "faction", "side"),
    allyTeamId: pick(p, "allyTeamId", "allyTeam"),
    skill: numOrNull(pick(p, "skill", "skillValue", "rank")),
    startPos: sp ? { x: sp.x, z: sp.z } : null,
  });
}

const out = {
  source: "sdfz-demo-parser",
  gameId: pick(meta, "gameId"),
  map: pick(meta, "map", "mapName"),
  engine: pick(meta, "engine"),
  gameVersion: pick(meta, "game", "gameVersion"),
  winningAllyTeamIds: pick(meta, "winningAllyTeamIds") || [],
  durationMs: pick(meta, "durationMs"),
  playerCount: players.length,
  players,
};

if (outFile) { fs.writeFileSync(outFile, JSON.stringify(out, null, 2)); console.error(`wrote ${players.length} players -> ${outFile}`); }
else console.log(JSON.stringify(out, null, 2));

function numOrNull(x) {
  if (x == null) return null;
  const m = String(x).match(/-?\d+(\.\d+)?/);
  return m ? Number(m[0]) : null;
}

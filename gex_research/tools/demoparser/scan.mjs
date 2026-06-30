// scan.mjs — scan recent .sdfz demos, print player/allyteam counts to find 8v8s.
//   node scan.mjs <demoDir> [limit]
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
const require = createRequire(import.meta.url);
const { DemoParser } = require("sdfz-demo-parser");

const [, , demoDir, limitArg] = process.argv;
const limit = limitArg ? Number(limitArg) : 15;

const files = fs.readdirSync(demoDir)
  .filter(f => f.toLowerCase().endsWith(".sdfz"))
  .map(f => ({ f, m: fs.statSync(path.join(demoDir, f)).mtimeMs, size: fs.statSync(path.join(demoDir, f)).size }))
  .sort((a, b) => b.m - a.m)
  .slice(0, limit);

for (const { f, size } of files) {
  try {
    const parser = new DemoParser({ skipPackets: true });
    const demo = await parser.parseDemo(path.join(demoDir, f));
    const info = demo.info || {};
    const players = (info.players || []).filter(p => p);
    const ais = info.ais || [];
    const allyTeams = info.allyTeams || [];
    const meta = info.meta || {};
    const durMin = meta.durationMs ? (meta.durationMs / 60000).toFixed(1) : "?";
    // allyteam -> count of players
    const byAlly = {};
    for (const p of players) byAlly[p.allyTeamId] = (byAlly[p.allyTeamId] || 0) + 1;
    const allyStr = Object.entries(byAlly).map(([a, c]) => `AT${a}:${c}`).join(" ");
    console.log(`${f} | size=${(size/1024).toFixed(0)}KB players=${players.length} ais=${ais.length} allyTeams=${allyTeams.length} dur=${durMin}min map=${meta.map} | ${allyStr}`);
  } catch (e) {
    console.log(`${f} | ERROR ${e.message}`);
  }
}

import { createRequire } from "node:module";
import fs from "node:fs"; import path from "node:path";
const require = createRequire(import.meta.url);
const { DemoParser } = require("sdfz-demo-parser");
const dir = "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data/demos";
const files = fs.readdirSync(dir).filter(f => f.toLowerCase().endsWith(".sdfz"))
  .map(f => ({ f, m: fs.statSync(path.join(dir, f)).mtimeMs, sz: fs.statSync(path.join(dir, f)).size }))
  .sort((a, b) => b.m - a.m).slice(0, 50);
for (const { f, sz } of files) {
  try {
    const d = await new DemoParser({ skipPackets: true }).parseDemo(path.join(dir, f));
    const ps = (d.info.players || []).filter(Boolean);
    const ais = d.info.ais || [];
    if (ps.length <= 2) {  // skirmish-ish
      const facs = ps.map(p => `${p.name}:${p.faction || "?"}`).join(", ");
      const map = (d.info.meta && d.info.meta.map) || "?";
      console.log(`${f} | sz=${(sz/1024).toFixed(0)}KB players=${ps.length} ais=${ais.length} | ${facs} | ${map}`);
    }
  } catch (e) { /* skip */ }
}

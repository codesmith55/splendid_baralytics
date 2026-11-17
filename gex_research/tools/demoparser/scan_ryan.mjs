import { createRequire } from "node:module";
import fs from "node:fs"; import path from "node:path";
const require = createRequire(import.meta.url);
const { DemoParser } = require("sdfz-demo-parser");
const dir = "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data/demos";
const files = fs.readdirSync(dir).filter(f => f.toLowerCase().endsWith(".sdfz"))
  .map(f => ({ f, m: fs.statSync(path.join(dir, f)).mtimeMs })).sort((a, b) => b.m - a.m).slice(0, 40);
for (const { f } of files) {
  try {
    const d = await new DemoParser({ skipPackets: true }).parseDemo(path.join(dir, f));
    const ps = (d.info.players || []).filter(Boolean);
    const splendi = ps.find(p => /splendi/i.test(p.name || ""));
    if (ps.length === 16 || splendi) console.log(`${f} | players=${ps.length} | splendi=${splendi ? splendi.name + " (tid" + splendi.teamId + " AT" + splendi.allyTeamId + ")" : "-"}`);
  } catch (e) { console.log(f, "ERR", e.message); }
}

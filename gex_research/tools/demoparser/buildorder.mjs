// buildorder.mjs — extract opening build order (issued BUILD commands) per player from a .sdfz.
//   node buildorder.mjs <demo.sdfz> <maxSeconds> <playerNum,playerNum,...>
// Reads COMMAND + AICOMMAND + AICOMMANDS packets, keeps cmdName=="BUILD",
// timestamps via packet.actualGameTime (seconds). Prints a per-player timeline.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { DemoParser } = require("sdfz-demo-parser");

const [, , demoFile, maxSecArg, playersArg] = process.argv;
const maxSec = Number(maxSecArg || 300);
const wanted = new Set((playersArg || "").split(",").filter(s => s !== "").map(Number));

const events = []; // {t, player, unit, src}
const parser = new DemoParser({ verbose: false });

function pushBuild(t, player, cmd, src) {
  if (!cmd || cmd.cmdName !== "BUILD") return;
  if (wanted.size && !wanted.has(player)) return;
  events.push({ t, player, unit: cmd.unitDefId, src });
}

parser.onPacket.add((p) => {
  const t = p.actualGameTime != null ? p.actualGameTime : p.fullGameTime;
  const d = p.data || {};
  if (p.name === "COMMAND") pushBuild(t, d.playerNum, d.command, "C");
  else if (p.name === "AICOMMAND") pushBuild(t, d.playerNum, d.command, "A");
  else if (p.name === "AICOMMANDS") {
    for (const c of d.commands || []) pushBuild(t, d.playerNum, c, "AS");
  }
});

await parser.parseDemo(demoFile);

// time bounds
const times = events.map(e => e.t).filter(x => typeof x === "number");
console.log(`# total BUILD events (all wanted players, all time): ${events.length}`);
console.log(`# actualGameTime range across BUILD events: ${Math.min(...times).toFixed(1)}s .. ${Math.max(...times).toFixed(1)}s`);

for (const pn of [...wanted].sort((a,b)=>a-b)) {
  const evs = events.filter(e => e.player === pn && typeof e.t === "number" && e.t <= maxSec)
                    .sort((a,b)=>a.t-b.t);
  console.log(`\n===== playerNum ${pn} — ${evs.length} BUILD orders in 0-${maxSec}s =====`);
  // collapse consecutive identical units issued within a short window into "unit xN @ t0–t1"
  let i = 0;
  while (i < evs.length) {
    let j = i;
    while (j + 1 < evs.length && evs[j+1].unit === evs[i].unit) j++;
    const n = j - i + 1;
    const t0 = evs[i].t, t1 = evs[j].t;
    const tstr = (s) => `${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,"0")}`;
    const range = n > 1 ? `${tstr(t0)}–${tstr(t1)}` : tstr(t0);
    console.log(`  ${range.padEnd(13)} ${evs[i].unit}${n>1?` x${n}`:""}`);
    i = j + 1;
  }
}

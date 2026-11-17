// shares.mjs — dump resource-sharing traffic (SHARE/SETSHARE) with timing.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { DemoParser } = require("sdfz-demo-parser");
const [, , demoFile] = process.argv;
const parser = new DemoParser({ verbose: false });
const tstr = (s) => `${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,"0")}`;
parser.onPacket.add((p) => {
  const t = p.actualGameTime ?? p.fullGameTime;
  const d = p.data || {};
  if (p.name === "SHARE") {
    console.log(`${tstr(t).padEnd(6)} SHARE   from player ${d.playerNum} -> team ${d.shareTeam} | metal=${d.shareMetal} energy=${d.shareEnergy} units=${d.shareUnits}`);
  } else if (p.name === "SETSHARE") {
    console.log(`${tstr(t).padEnd(6)} SETSHARE player ${d.playerNum} team ${d.teamId} | metalFrac=${d.metalShareFraction} energyFrac=${d.energyShareFraction}`);
  }
});
await parser.parseDemo(demoFile);

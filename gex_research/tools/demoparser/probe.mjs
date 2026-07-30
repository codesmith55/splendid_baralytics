// probe.mjs — scan packet stream: max frame, packet histogram, build-command count per player.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { DemoParser } = require("sdfz-demo-parser");
const [, , demoFile] = process.argv;

const parser = new DemoParser({ verbose: false });
let maxFrame = 0;
const hist = {};
const buildByPlayer = {};      // playerNum -> count of BUILD commands
const buildDefSeen = new Set();
parser.onPacket.add((p) => {
  hist[p.name] = (hist[p.name] || 0) + 1;
  const d = p.data || {};
  if (p.name === "KEYFRAME" || p.name === "NEWFRAME") {
    if (typeof d.frameNum === "number" && d.frameNum > maxFrame) maxFrame = d.frameNum;
  }
  if (p.name === "COMMAND" && d.command && d.command.cmdName === "BUILD") {
    const pn = d.playerNum;
    buildByPlayer[pn] = (buildByPlayer[pn] || 0) + 1;
    buildDefSeen.add(d.command.unitDefId);
  }
});
await parser.parseDemo(demoFile);
console.log("maxFrame:", maxFrame, "=> ~", (maxFrame/30/60).toFixed(2), "min (assuming 30fps)");
console.log("packet histogram:", JSON.stringify(hist));
console.log("BUILD commands per playerNum:", JSON.stringify(buildByPlayer));
console.log("distinct unitDefIds in BUILD cmds (sample):", [...buildDefSeen].slice(0,40).join(","));

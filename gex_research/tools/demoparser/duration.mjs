// duration.mjs — report demo game length via header + packet scan.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { DemoParser } = require("sdfz-demo-parser");
const [, , demoFile] = process.argv;
const parser = new DemoParser();
const demo = await parser.parseDemo(demoFile);
const h = demo.header || {};
console.log("header.gameTime(s):", h.gameTime, "wallclock(s):", h.wallclockTime);
const ts = demo.statistics?.teamStats?.[0];
if (ts) console.log("teamStats[0] frames:", ts.length, "lastFrame:", ts[ts.length-1]?.frame, "=> ~", ((ts[ts.length-1]?.frame||0)/30/60).toFixed(1), "min");
console.log("durationMs:", demo.info?.meta?.durationMs, "winners:", demo.info?.meta?.winningAllyTeamIds);

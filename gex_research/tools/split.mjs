#!/usr/bin/env node
// tools/split.mjs — print economy-composition splits from a run's per_user output.
//
// USAGE
//   node tools/split.mjs [run] [time] [--breakout] [--filter <name>]
//
// ARGUMENTS
//   run              run-id or short suffix: "002" | "run-002" | omit for most-recent output
//   time             time spec: seconds (number) | "peak" | "final"    (default: peak)
//   --breakout       multi-line per-bucket output with absolute values
//   --filter <name>  show only players whose name contains this substring (case-insensitive)
//
// EXAMPLES
//   node tools/split.mjs
//     → all players at peak economy, topline
//
//   node tools/split.mjs 002 600
//     → all players @ 600 s, topline
//
//   node tools/split.mjs 002 peak --breakout
//     → full per-bucket breakout for every player at their peak
//
//   node tools/split.mjs 002 600 --filter hakimhc
//     → one player @ 600 s, topline
//
//   node tools/split.mjs 002 final --breakout --filter Splendi
//     → one player's breakout at the final frame
import fs   from "node:fs";
import path from "node:path";
import { splitAt } from "../process/lib/snapFormat.mjs";

const ROOT = path.resolve(
  path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")),
  ".."
);

// ── parse CLI ─────────────────────────────────────────────────────────────────
const argv       = process.argv.slice(2);
const isBreakout = argv.includes("--breakout");
const filterIdx  = argv.indexOf("--filter");
const nameFilter = filterIdx >= 0 ? argv[filterIdx + 1] ?? null : null;

// positional args: skip flags and the --filter value
const positional = argv.filter((a, i) => !a.startsWith("--") && (filterIdx < 0 || i !== filterIdx + 1));
let [runArg = null, timeArg = "peak"] = positional;

// ── resolve run directory ─────────────────────────────────────────────────────
const outRoot = path.join(ROOT, "output");
if (!fs.existsSync(outRoot)) {
  console.error(`output/ directory not found: ${outRoot}`);
  process.exit(1);
}

if (!runArg) {
  const dirs = fs.readdirSync(outRoot)
    .filter(d => d.startsWith("run-") && fs.statSync(path.join(outRoot, d)).isDirectory())
    .sort();
  if (!dirs.length) { console.error("no run output found in output/"); process.exit(1); }
  runArg = dirs[dirs.length - 1].replace(/^run-/, "");
}
const runId  = runArg.startsWith("run-") ? runArg : `run-${runArg}`;
const outDir = path.join(outRoot, runId);
if (!fs.existsSync(outDir)) { console.error(`run output not found: ${outDir}`); process.exit(1); }

// ── load situations.json ──────────────────────────────────────────────────────
const sitFile = path.join(outDir, "situations.json");
if (!fs.existsSync(sitFile)) { console.error(`situations.json not found: ${sitFile}`); process.exit(1); }

const situations = JSON.parse(fs.readFileSync(sitFile, "utf8"));
const users      = situations.per_user?.users;
if (!users?.length) { console.error("no per_user data found in situations.json"); process.exit(1); }

// ── resolve timeSpec ──────────────────────────────────────────────────────────
const timeSpec = (timeArg === "peak" || timeArg === "final") ? timeArg : +timeArg;
if (typeof timeSpec === "number" && isNaN(timeSpec)) {
  console.error(`invalid time '${timeArg}': must be a number (seconds), 'peak', or 'final'`);
  process.exit(1);
}

// ── filter ────────────────────────────────────────────────────────────────────
let targets = users;
if (nameFilter) {
  const q = nameFilter.toLowerCase();
  targets = users.filter(u => (u.user ?? "").toLowerCase().includes(q));
  if (!targets.length) { console.error(`no player matching "${nameFilter}"`); process.exit(1); }
}

// sort: ally-team 0 first, then by teamID
targets = [...targets].sort((a, b) => (a.allyTeam ?? 0) - (b.allyTeam ?? 0) || a.teamID - b.teamID);

// ── output ────────────────────────────────────────────────────────────────────
const mode = isBreakout ? "breakout" : "topline";
console.log(`${runId}  @  ${timeArg}  (${mode})\n`);

for (const u of targets) {
  console.log(splitAt(u, timeSpec, mode));
  if (isBreakout && targets.length > 1) console.log();  // blank line between breakout blocks
}

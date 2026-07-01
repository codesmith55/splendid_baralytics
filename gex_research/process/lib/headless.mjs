// headless.mjs — run a BAR replay headlessly via the local install and return the actions.json path.
// Mirrors gex's BarHeadlessInstance: isolated write-dir, vendored widget, SPRING_DATADIR for read.
//
// Idle watchdog: on a 1v0/skirmish replay there is no opponent to trigger a clean
// game-over, so spring-headless free-runs frames forever once the demo's recorded
// commands run out (observed: real actions stopped at frame 13526, engine kept
// ticking wind_update/extra_stat_update noise to frame 338100+ before being killed
// manually). We track wall-clock time since the last REAL gameplay event
// (unit_created/unit_finished/factory_unit_created/unit_killed/unit_resources) —
// periodic poll events (wind_update, extra_stat_update) don't count, since those
// fire forever regardless of whether anything is actually happening. If no real
// event lands within idleMs, the replay has exhausted its content and is killed.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, execFileSync } from "node:child_process";

const BAR = "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data";

// Event types that indicate the replay is still doing something new (vs periodic
// polling noise that fires forever even after the demo's real content ends — this
// includes wind_update, extra_stat_update, unit_position, AND commander_position_update,
// which all fire on a fixed tick cadence regardless of whether anything is happening).
const ACTIVITY_RE = /"action":"(unit_created|unit_finished|factory_unit_created|unit_killed|unit_resources|unit_damage)"/g;

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function killTree(pid) {
  try { execFileSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" }); } catch (_) {}
}

export function runHeadless({ demoFile, engine = "recoil_2025.06.24", vendorDir, timeoutMs = 600000, idleMs = 20000, pollMs = 2000, reuseExisting = false } = {}) {
  if (!fs.existsSync(demoFile)) throw new Error(`demo not found: ${demoFile}`);
  const eng = path.join(BAR, "engine", engine);
  const exe = path.join(eng, "spring-headless.exe");
  if (!fs.existsSync(exe)) throw new Error(`spring-headless not found for engine ${engine}: ${exe}`);

  const wdBase = path.join(os.tmpdir(), "gex_harness", "wd_" + path.basename(demoFile).replace(/[^\w.-]/g, "_"));
  let wd = wdBase;

  // fast path: re-use existing extraction if caller opts in and actions.json is present
  if (reuseExisting) {
    const cached = path.join(wd, "actions.json");
    if (fs.existsSync(cached)) {
      console.log(`[headless] reusing cached actions.json (${fs.statSync(cached).size} bytes) — skipping replay`);
      return cached;
    }
  }

  // Try to remove the existing wd; if another process has it locked (Windows fd leak),
  // fall back to a fresh numbered directory rather than failing.
  let rmOk = false;
  try { fs.rmSync(wd, { recursive: true, force: true }); rmOk = true; } catch (_) {}
  if (!rmOk) {
    let n = 2;
    while (fs.existsSync(`${wdBase}_r${n}`)) n++;
    wd = `${wdBase}_r${n}`;
    console.log(`[headless] wd locked — using fresh path: ${wd}`);
  }
  fs.mkdirSync(path.join(wd, "LuaUI", "Widgets"), { recursive: true });
  fs.mkdirSync(path.join(wd, "LuaUI", "Config"), { recursive: true });
  fs.copyFileSync(path.join(vendorDir, "gex.lua"), path.join(wd, "LuaUI", "Widgets", "gex.lua"));
  fs.copyFileSync(path.join(vendorDir, "BYAR.lua"), path.join(wd, "LuaUI", "Config", "BYAR.lua"));

  // Derive port from process PID so concurrent Node processes don't collide on 50124
  const hostPort = 50100 + (process.pid % 4900);
  const script = path.join(wd, "_script.txt");
  fs.writeFileSync(script, `[game] {\ndemofile=${demoFile};HostPort=${hostPort};\n}`, "ascii");

  console.log(`[headless] replaying ${path.basename(demoFile)} on ${engine} ...`);
  const outFd = fs.openSync(path.join(wd, "stdout.txt"), "w");
  const errFd = fs.openSync(path.join(wd, "stderr.txt"), "w");
  const child = spawn(exe, ["--write-dir", wd, script], {
    cwd: eng,
    env: { ...process.env, SPRING_DATADIR: `${wd};${BAR}` },
    stdio: ["ignore", outFd, errFd],
  });

  const actions = path.join(wd, "actions.json");
  const tStart = Date.now();
  // Engine/map load can legitimately take well over idleMs before actions.json even
  // exists (~137s/13-min-game observed elsewhere) — don't idle-kill during that phase.
  // Only start the strict "no new gameplay event" clock once the FIRST real event has
  // been seen. Before that, only bail if NOTHING at all is being written (hung engine).
  const STARTUP_GRACE_MS = Math.max(idleMs, 90000);
  let tLastActivity = tStart;
  let tLastAnyBytes  = tStart;
  let sawAnyActivity = false;
  let readOffset = 0;
  let exited = false;
  let killedReason = null;
  child.on("exit", () => { exited = true; });

  while (!exited) {
    sleepSync(pollMs);
    const now = Date.now();

    // Scan any bytes appended since the last poll for real (non-noise) events.
    if (fs.existsSync(actions)) {
      const size = fs.statSync(actions).size;
      if (size > readOffset) {
        const fd = fs.openSync(actions, "r");
        const buf = Buffer.alloc(size - readOffset);
        fs.readSync(fd, buf, 0, buf.length, readOffset);
        fs.closeSync(fd);
        readOffset = size;
        tLastAnyBytes = now;
        if (ACTIVITY_RE.test(buf.toString("utf8"))) { tLastActivity = now; sawAnyActivity = true; }
        ACTIVITY_RE.lastIndex = 0;
      }
    }

    if (sawAnyActivity) {
      if (now - tLastActivity > idleMs) { killedReason = `idle ${idleMs}ms (no new gameplay events since real action)`; break; }
    } else if (now - tLastAnyBytes > STARTUP_GRACE_MS) {
      killedReason = `no output within ${STARTUP_GRACE_MS}ms startup grace — engine likely hung`; break;
    }
    if (now - tStart > timeoutMs) { killedReason = `hard timeout ${timeoutMs}ms`; break; }
  }

  if (!exited) {
    console.log(`[headless] killing runaway replay — ${killedReason}`);
    killTree(child.pid);
    sleepSync(500);
  }
  // Explicitly close fds so Windows doesn't lock the tmp dir after the child exits
  fs.closeSync(outFd);
  fs.closeSync(errFd);

  if (!fs.existsSync(actions)) {
    // Clean up failed fallback directories so they don't accumulate
    if (wd !== wdBase) {
      try { fs.rmSync(wd, { recursive: true, force: true }); } catch (_) {}
    }
    throw new Error(`headless run produced no actions.json${killedReason ? ` (${killedReason})` : ""}. See ${path.join(wd, "stdout.txt")}`);
  }
  console.log(`[headless] done -> ${actions} (${fs.statSync(actions).size} bytes)${killedReason ? `  [closed early: ${killedReason}]` : ""}`);
  return actions;
}

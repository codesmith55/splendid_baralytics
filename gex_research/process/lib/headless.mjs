// headless.mjs — run a BAR replay headlessly via the local install and return the actions.json path.
// Mirrors gex's BarHeadlessInstance: isolated write-dir, vendored widget, SPRING_DATADIR for read.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

const BAR = "C:/Users/codes/AppData/Local/Programs/Beyond-All-Reason/data";

export function runHeadless({ demoFile, engine = "recoil_2025.06.24", vendorDir, timeoutMs = 600000, reuseExisting = false } = {}) {
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
  const r = spawnSync(exe, ["--write-dir", wd, script], {
    cwd: eng,
    env: { ...process.env, SPRING_DATADIR: `${wd};${BAR}` },
    timeout: timeoutMs,
    stdio: ["ignore", outFd, errFd],
  });
  // Explicitly close fds so Windows doesn't lock the tmp dir after spawnSync returns
  fs.closeSync(outFd);
  fs.closeSync(errFd);
  const actions = path.join(wd, "actions.json");
  if (!fs.existsSync(actions)) {
    // Clean up failed fallback directories so they don't accumulate
    if (wd !== wdBase) {
      try { fs.rmSync(wd, { recursive: true, force: true }); } catch (_) {}
    }
    throw new Error(`headless run produced no actions.json (exit ${r.status}). See ${path.join(wd, "stdout.txt")}`);
  }
  console.log(`[headless] done -> ${actions} (${fs.statSync(actions).size} bytes)`);
  return actions;
}

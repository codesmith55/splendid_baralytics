// snapFormat.mjs — format an economy-composition snapshot as a one-liner or full breakout.
//
// Two output modes (pass as `mode` or call a formatter directly):
//
//   topline  — single line with all buckets:
//              "name @ Xs:  BP:7.0%  Eco:34.1%  Inf:8.8%  Mil:37.8%  Sto:10.1%  Oth:2.1%  [69k]"
//
//   breakout — one line per bucket with % and absolute value, columns aligned:
//              "name @ Xs  (total: 69,448)"
//              "  build_power      7.0%    4,886"
//              "  economy         34.1%   23,686"
//              ...
//
// Works on any snapshot { frame, second, total, value:{...}, pct:{...} } produced by
// economy_composition — a single entry from series[], or the peak / final objects.

export const BUCKETS = ["build_power", "economy", "infrastructure", "military", "storage", "other"];
export const ABBREV  = {
  build_power: "BP", economy: "Eco", infrastructure: "Inf",
  military: "Mil", storage: "Sto", other: "Oth",
};

// ── core query ────────────────────────────────────────────────────────────────

/**
 * Find the snapshot in a time-series array nearest to the requested time.
 *
 * @param {Array}  series   — [{frame, second, total, value, pct}, …] from economy_composition
 * @param {number|{second?:number, frame?:number}} timeSpec
 *   number  → treated as seconds
 *   {second: N} | {frame: N}  → explicit
 * @returns {object|null} closest snapshot, or null if series is empty
 */
export function snapAt(series, timeSpec) {
  if (!series?.length) return null;
  const sec = _asSec(timeSpec);
  let best = series[0], bestD = Math.abs(series[0].second - sec);
  for (const s of series) {
    const d = Math.abs(s.second - sec);
    if (d < bestD) { bestD = d; best = s; }
  }
  return best;
}

// ── formatters ────────────────────────────────────────────────────────────────

/**
 * One-liner with all buckets.
 * "name @ Xs:  BP:7.0%  Eco:34.1%  Inf:8.8%  Mil:37.8%  Sto:10.1%  Oth:2.1%  [69k]"
 *
 * @param {object}   snap
 * @param {string}   [label]          player name / any prefix string
 * @param {object}   [opts]
 * @param {string[]} [opts.buckets]   ordered bucket list (default: BUCKETS)
 * @param {boolean}  [opts.noTotal]   omit the [total] suffix
 */
export function topline(snap, label = "", { buckets = BUCKETS, noTotal = false } = {}) {
  if (!snap) return label ? `${label}  (no data)` : "(no data)";
  const pct  = snap.pct  ?? {};
  const parts = buckets.map(b => `${ABBREV[b] ?? b}:${p1(pct[b])}%`).join("  ");
  const tot   = (!noTotal && snap.total != null) ? `  [${fmtK(snap.total)}]` : "";
  const tag   = label ? `${label} @ ${snap.second}s:` : `@ ${snap.second}s:`;
  return `${tag}  ${parts}${tot}`;
}

/**
 * Percentage-only line — no label, no total, no timestamp.
 * "BP:7.0%  Eco:34.1%  Inf:8.8%  Mil:37.8%  Sto:10.1%  Oth:2.1%"
 *
 * Useful as a compact inline annotation (e.g. HTML chart subtitles, mirror delta rows).
 */
export function pctLine(snap, { buckets = BUCKETS } = {}) {
  if (!snap) return "";
  const pct = snap.pct ?? {};
  return buckets.map(b => `${ABBREV[b] ?? b}:${p1(pct[b])}%`).join("  ");
}

/**
 * Multi-line breakout — one row per bucket, % and absolute value aligned.
 *
 * "name @ Xs  (total: 69,448)"
 * "  build_power      7.0%    4,886"
 * "  economy         34.1%   23,686"
 * "  infrastructure   8.8%    6,142"
 * "  military        37.8%   26,234"
 * "  storage         10.1%    7,010"
 * "  other            2.1%    1,490"
 *
 * @param {object}   snap
 * @param {string}   [label]
 * @param {object}   [opts]
 * @param {string[]} [opts.buckets]
 */
export function breakout(snap, label = "", { buckets = BUCKETS } = {}) {
  if (!snap) return label ? `${label}  (no data)` : "(no data)";
  const pct = snap.pct ?? {}, val = snap.value ?? {};
  const tag = label ? `${label} @ ${snap.second}s` : `@ ${snap.second}s`;
  const lines = [`${tag}  (total: ${fmtN(snap.total)})`];
  for (const b of buckets) {
    lines.push(`  ${b.padEnd(16)} ${p1(pct[b]).padStart(5)}%  ${fmtN(val[b]).padStart(8)}`);
  }
  return lines.join("\n");
}

// ── high-level convenience ────────────────────────────────────────────────────

/**
 * Format one user from per_user situation output in the requested mode.
 *
 * @param {object} user      — a row from per_user.users: {user, series, peak, final, teamID}
 * @param {number|"peak"|"final"|{second?:number,frame?:number}} [timeSpec="peak"]
 * @param {"topline"|"breakout"} [mode="topline"]
 * @param {object} [opts]    — forwarded to topline() / breakout()
 * @param {string} [opts.label]   override the player name
 * @returns {string}
 */
export function splitAt(user, timeSpec = "peak", mode = "topline", opts = {}) {
  const label = opts.label ?? shortName(user.user ?? `team ${user.teamID}`);
  const snap  = _pickSnap(user, timeSpec);
  return mode === "breakout" ? breakout(snap, label, opts) : topline(snap, label, opts);
}

// ── internals ─────────────────────────────────────────────────────────────────

function _asSec(ts) {
  if (typeof ts === "number") return ts;
  if (ts?.frame  != null) return ts.frame / 30;
  if (ts?.second != null) return ts.second;
  return 0;
}

function _pickSnap(user, ts) {
  if (ts === "peak")  return user.peak  ?? null;
  if (ts === "final") return user.final ?? null;
  return snapAt(user.series, ts);
}

/** Strip " (user NNNNN) · Faction" suffix from per_user label strings. */
function shortName(s) { return String(s).replace(/\s*\(user \d+\).*$/, "").trim(); }

function p1(x)   { return (+(x ?? 0)).toFixed(1); }
function fmtK(n) { return (n ?? 0) >= 1000 ? `${Math.round(n / 1000)}k` : String(Math.round(n ?? 0)); }
function fmtN(n) { return Math.round(n ?? 0).toLocaleString("en-US"); }

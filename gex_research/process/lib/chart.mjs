// chart.mjs — render a self-contained HTML report (inline SVG, no external deps) from run results.
import { pctLine } from "./snapFormat.mjs";
const COLORS = {
  build_power: "#4e9a06", economy: "#f0c000", infrastructure: "#3465a4",
  military: "#cc0000", storage: "#75507b", other: "#888a85",
};
const ORDER = ["build_power", "economy", "infrastructure", "military", "storage", "other"];

export function renderHtml({ run, meta, perUser, mirror, selfReclaim }) {
  const users = (perUser?.users || []).slice().sort((a, b) => (a.allyTeam - b.allyTeam) || (a.teamID - b.teamID));
  const legend = ORDER.map(b => `<span class="lg"><i style="background:${COLORS[b]}"></i>${b}</span>`).join(" ");

  const snapOf = t => t.peak || t.final;
  const nameOf = t => t.user || t.player || `team ${t.teamID}`;
  const subOf = t => `ally ${t.allyTeam} · controls team ${t.teamID}`;
  const userRows = users.map(t => row(nameOf(t), snapOf(t), subOf(t))).join("");

  const pairBlocks = (mirror?.pairs || []).map((p, i) => `
    <div class="pair">
      <h3>Mirror ${i + 1} &middot; start gap ${p.distance}</h3>
      <div class="cmp">
        <div>${row(nameOf(p.a), snapOf(p.a), subOf(p.a))}</div>
        <div class="vs">vs</div>
        <div>${row(nameOf(p.b), snapOf(p.b), subOf(p.b))}</div>
      </div>
      <div class="delta">${deltaLine(p.delta)}</div>
    </div>`).join("");

  const srHtml = selfReclaim ? srTable(selfReclaim, perUser) : "";

  return `<!doctype html><meta charset="utf-8"><title>${esc(run.title || run.runId)}</title>
<style>
 body{font:14px/1.45 system-ui,Segoe UI,sans-serif;margin:24px;color:#1a1a1a;background:#fafafa}
 h1{font-size:20px}h2{margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}
 .lg{margin-right:10px;white-space:nowrap}.lg i{display:inline-block;width:11px;height:11px;margin-right:4px;border-radius:2px;vertical-align:-1px}
 .r{display:grid;grid-template-columns:230px 1fr;gap:10px;align-items:start;margin:5px 0}
 .r .nm{font-weight:600}.r .sub{color:#888;font-weight:400;font-size:12px}
 .bar{display:flex;height:22px;border-radius:3px;overflow:hidden;background:#eee}
 .seg{height:100%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:10px;overflow:hidden}
 .split{font-size:11px;color:#555;font-family:ui-monospace,monospace;margin-top:2px;letter-spacing:.01em}
 .pair{background:#fff;border:1px solid #e3e3e3;border-radius:6px;padding:10px 14px;margin:10px 0}
 .cmp{display:grid;grid-template-columns:1fr 32px 1fr;align-items:start;gap:8px}
 .vs{text-align:center;color:#aaa;font-weight:700;padding-top:4px}
 .delta{color:#555;font-size:12px;margin-top:6px}.delta b{color:#000}
 .meta{color:#666;font-size:12px}
 .sr-table{border-collapse:collapse;width:100%;font-size:13px}
 .sr-table th{text-align:right;padding:3px 8px;border-bottom:2px solid #ddd;color:#555;font-weight:600}
 .sr-table th:first-child{text-align:left}
 .sr-table td{text-align:right;padding:3px 8px;border-bottom:1px solid #eee}
 .sr-table td:first-child{text-align:left;font-weight:600}
 .sr-table tr:last-child td{border-bottom:none}
 .sr-table .zero{color:#bbb}
 .sr-eco{color:${COLORS.economy};font-weight:700}
 .sr-mil{color:${COLORS.military};font-weight:700}
 .sr-inf{color:${COLORS.infrastructure};font-weight:700}
 .sr-bp{color:${COLORS.build_power};font-weight:700}
</style>
<h1>${esc(run.title || run.runId)}</h1>
<div class="meta">replay frames 0–${meta.endFrame} (~${meta.durationSeconds ? (meta.durationSeconds/60).toFixed(1)+" min" : "?"}) ·
 ${users.length} users · value = metal + energy/70 · commander = ${perUser?.commanderValue ?? 1200} (build_power+military)</div>
<p class="meta">Each user controls one engine "team"; rows are presented per user.</p>
<p>${legend}</p>
<h2>Per-user economy composition (at peak economy)</h2>
<p class="meta">Each bar = a user's % composition at their peak unit value (avoids the all-dead final frame). Full per-time series in metrics.json.</p>
${userRows}
${mirror ? `<h2>Mirror matchups by start position (${mirror.pairCount} pairs)</h2>${pairBlocks}` : ""}
${srHtml}
<h2>Raw data</h2>
<p class="meta">Full time series embedded below as <code>window.RESULT</code> (open dev console) and written to the sibling <code>*.json</code> files.</p>
<script>window.RESULT=${JSON.stringify({ run: run.runId, perUser, mirror, selfReclaim }).replace(/</g, "\\u003c")};</script>`;
}

function row(name, snap, sub) {
  if (!snap) return `<div class="r"><div class="nm">${esc(name)}<div class="sub">${esc(sub)} · no data</div></div><div class="bar"></div></div>`;
  const segs = ORDER.map(b => {
    const v = snap.pct[b] || 0;
    if (v < 0.5) return "";
    return `<span class="seg" style="width:${v}%;background:${COLORS[b]}" title="${b} ${v}%">${v >= 6 ? v + "%" : ""}</span>`;
  }).join("");
  const split = pctLine(snap, { buckets: ORDER });
  return `<div class="r"><div class="nm">${esc(name)}<div class="sub">${esc(sub)} · total ${Math.round(snap.total)} @ ${snap.second}s</div></div><div><div class="bar">${segs}</div><div class="split">${esc(split)}</div></div></div>`;
}

function srTable(sr, perUser) {
  // build name lookup from perUser
  const nameMap = new Map();
  for (const u of (perUser?.users || [])) nameMap.set(String(u.teamID), u.user || `team ${u.teamID}`);

  const rows = Object.entries(sr.final)
    .map(([tid, snap]) => ({
      tid, name: nameMap.get(tid) || `team ${tid}`, snap,
      count:        sr.eventCount[tid] ?? 0,
      lifeE:        sr.lifetimeEnergyTotal?.[tid] ?? 0,
      reclaimAdv:   sr.reclaimAdvantageTotal?.[tid] ?? 0,
    }))
    .filter(r => r.snap.total > 0)
    .sort((a, b) => b.snap.total - a.snap.total);

  if (!rows.length) return "";

  const fmt  = v => v > 0 ? Math.round(v) : `<span class="zero">—</span>`;
  const fmtA = v => v > 0 ? `+${Math.round(v)}` : `<span class="zero">—</span>`;

  const trs = rows.map(({ name, snap, count, lifeE, reclaimAdv }) => {
    const v = snap.value;
    return `<tr>
      <td>${esc(name)}</td>
      <td><b>${Math.round(snap.total)}</b></td>
      <td class="sr-eco">${fmt(v.economy)}</td>
      <td class="sr-mil">${fmt(v.military)}</td>
      <td class="sr-bp">${fmt(v.build_power)}</td>
      <td class="sr-inf">${fmt(v.infrastructure)}</td>
      <td>${fmt(v.other)}</td>
      <td class="sr-eco" title="metal-equiv energy produced by reclaimed eco structures during their lifetime">${fmtA(lifeE)}</td>
      <td class="sr-mil" title="max metal saved vs wreck (assumes all military reclaims were deathsaves)">${fmtA(reclaimAdv)}</td>
      <td>${count}</td>
    </tr>`;
  }).join("");

  return `<h2>Self-reclaim — cumulative value of own units reclaimed (metal equiv)</h2>
<p class="meta">
  Reclaiming your own unit disappears from economy_composition, but the churn is tracked here.
  <b>LifeE</b>: metal-equiv energy the eco structures generated during their lifetime — this is real value earned even though you reclaimed them. Wind turbines use max-capacity rate (actual output is wind-speed-dependent; treat as upper bound).
  <b>MilAdv</b>: max metal saved vs wreck outcome for military reclaims, assuming each was a deathsave (unit at ~0% HP reclaimed before dying). Wreck baseline = 55% of metalCost. If the unit was healthy, advantage is 0 (liquidation). HP-at-reclaim not yet emitted by gex.lua — see todo.md.
</p>
<table class="sr-table">
<thead><tr><th>Player</th><th>Total</th><th>Eco</th><th>Mil</th><th>BP</th><th>Inf</th><th>Other</th><th>LifeE</th><th>MilAdv</th><th>Evts</th></tr></thead>
<tbody>${trs}</tbody>
</table>`;
}

function deltaLine(d) {
  if (!d) return "";
  return "&Delta; (this − mirror): " + ORDER.filter(b => d[b] != null).map(b => `${b} <b>${d[b] > 0 ? "+" : ""}${d[b]}</b>`).join(" · ");
}
function esc(s) { return String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

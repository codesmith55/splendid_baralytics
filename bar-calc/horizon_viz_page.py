"""The page for horizon_viz: one self-contained HTML file, no CDN, no network.

PAGE carries two placeholders, __PAYLOAD__ and __TITLE__. The JavaScript in here is
a PORT of bar_unified's decision model (drain_rates, sustainable_bp, bank_runway,
energy_ceiling, regime_of, recommend, absorb_profile, target_advisor, _project_row,
effective_bproi). It exists so that dragging a slider re-derives the whole picture
with no round trip. Because it is a second copy of the model, the payload ships
Python's answers for a sample of cells and checkPort() verifies them on load.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --bg:#0e1116; --panel:#161b22; --panel2:#1b222c; --line:#2b3340;
  --ink:#e6edf3; --dim:#8b96a5; --faint:#5a6472;
  --metal:#2ea043; --bp:#3b82f6; --energy:#d29922; --overflow:#a371f7;
  --accent:#58a6ff; --warn:#f85149; --ok:#2ea043;
}
:root:not([data-theme="dark"]){
  @media (prefers-color-scheme: light){
    --bg:#f6f8fa; --panel:#fff; --panel2:#f0f3f6; --line:#d6dde6;
    --ink:#1f2328; --dim:#5a6472; --faint:#8b96a5;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;
  padding:14px 16px;border-bottom:1px solid var(--line);background:var(--panel)}
h1{font-size:17px;margin:0;letter-spacing:.02em}
h2{font-size:13px;margin:0 0 10px;color:var(--dim);text-transform:uppercase;
  letter-spacing:.09em;font-weight:600}
.meta{color:var(--dim);font-size:12px}
.badge{margin-left:auto;padding:3px 9px;border-radius:11px;font-size:11px;
  border:1px solid var(--line);color:var(--dim)}
.badge.ok{color:var(--ok);border-color:var(--ok)}
.badge.bad{color:var(--warn);border-color:var(--warn);font-weight:700}
main{padding:16px;display:flex;flex-direction:column;gap:14px;max-width:1500px;margin:0 auto}
section{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px}
.row{display:flex;flex-wrap:wrap;gap:14px}
.row>section{flex:1 1 420px;min-width:0}
.ctl{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end}
.ctl label{display:flex;flex-direction:column;gap:3px;font-size:11px;color:var(--dim)}
select,input[type=range]{background:var(--panel2);color:var(--ink);
  border:1px solid var(--line);border-radius:5px;padding:4px 6px;font:inherit;font-size:12px}
input[type=range]{width:150px;padding:0}
button{background:var(--panel2);color:var(--ink);border:1px solid var(--line);
  border-radius:5px;padding:5px 11px;font:inherit;font-size:12px;cursor:pointer}
button:hover{border-color:var(--accent)}
button.on{background:var(--accent);color:#04101f;border-color:var(--accent);font-weight:700}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:5px;overflow:hidden}
.seg button{border:0;border-radius:0}
.tiles{display:flex;flex-wrap:wrap;gap:8px}
.tile{background:var(--panel2);border:1px solid var(--line);border-radius:6px;
  padding:7px 11px;min-width:92px}
.tile .k{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.07em}
.tile .v{font-size:18px;font-weight:700;line-height:1.2}
.tile .s{font-size:10px;color:var(--faint)}
.verdict{margin-top:11px;padding:11px 13px;border-radius:6px;background:var(--panel2);
  border-left:4px solid var(--accent)}
.verdict b{font-size:16px}
.verdict .why{color:var(--dim);font-size:12px;margin-top:3px}
.chip{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;
  font-weight:700;color:#04101f}
.c-metal{background:var(--metal)} .c-bp{background:var(--bp)}
.c-energy{background:var(--energy)} .c-overflow{background:var(--overflow)}
table.grid{border-collapse:separate;border-spacing:2px;font-size:11px}
table.grid td,table.grid th{text-align:center;padding:0}
table.grid th{color:var(--dim);font-weight:500;font-size:10px;padding:2px 4px}
td.cell{width:26px;height:22px;border-radius:3px;color:#04101f;font-weight:700;
  cursor:crosshair;position:relative}
td.cell.here{outline:2px solid var(--ink);outline-offset:1px}
.legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:11px;font-size:11px;color:var(--dim)}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;
  margin-right:5px;vertical-align:-1px}
#tip{position:fixed;pointer-events:none;z-index:50;background:var(--panel2);
  border:1px solid var(--line);border-radius:6px;padding:8px 10px;font-size:11px;
  max-width:330px;box-shadow:0 6px 22px rgba(0,0,0,.45);display:none;white-space:pre-line}
svg{display:block;max-width:100%;overflow:visible}
canvas{display:block;width:100%;height:auto;cursor:grab;touch-action:none}
canvas.drag{cursor:grabbing}
table.data{border-collapse:collapse;font-size:11px;width:100%;margin-top:11px}
table.data th{text-align:right;color:var(--dim);font-weight:500;padding:3px 7px;
  border-bottom:1px solid var(--line)}
table.data th:first-child,table.data td:first-child{text-align:left}
table.data td{text-align:right;padding:3px 7px;border-bottom:1px solid var(--line)}
table.data tr.hi td{background:var(--panel2)}
.ribbon{display:flex;gap:1px;margin-top:9px;align-items:stretch}
.rib{flex:1 1 0;min-width:6px;cursor:pointer;border-radius:2px;
  display:flex;flex-direction:column;justify-content:flex-end;height:42px;
  font-size:9px;text-align:center;color:#04101f;font-weight:700;overflow:hidden}
.rib.sel{outline:2px solid var(--ink);outline-offset:1px}
.note{color:var(--dim);font-size:12px;line-height:1.65}
.note b{color:var(--ink)}
.note code{background:var(--panel2);padding:1px 4px;border-radius:3px}
.spark{font-size:10px;color:var(--faint)}
</style>
</head>
<body>
<header>
  <h1>Build Horizon</h1>
  <div class="meta" id="hmeta"></div>
  <div class="badge" id="parity">checking port</div>
</header>
<main>

<section>
  <h2>Position</h2>
  <div class="ctl">
    <div class="seg" id="mode">
      <button data-mode="replay" class="on">Replay</button>
      <button data-mode="sandbox">Sandbox</button>
    </div>
    <div id="replayCtl" class="ctl">
      <button id="play">Play</button>
      <label>frame<input type="range" id="frame" min="0" step="1"></label>
      <label>speed<select id="speed">
        <option value="900">slow</option><option value="450" selected>1x</option>
        <option value="200">fast</option></select></label>
    </div>
    <div id="sandCtl" class="ctl" style="display:none">
      <label>metal income<input type="range" id="sMinc" min="0" max="40" step="0.1"></label>
      <label>energy income<input type="range" id="sEinc" min="0" max="2000" step="5"></label>
      <label>build power<input type="range" id="sBp" min="100" max="6000" step="10"></label>
      <label>metal bank<input type="range" id="sMbank" min="0" max="4000" step="10"></label>
      <label>energy bank<input type="range" id="sEbank" min="0" max="20000" step="50"></label>
      <label>wind<input type="range" id="sWind" min="0" max="22" step="0.1"></label>
    </div>
    <label>target<select id="target"></select></label>
    <label>build power from<select id="bpsrc"></select></label>
    <label>energy from<select id="esrc"></select></label>
    <label>work measured on<select id="on"></select></label>
  </div>
  <div class="tiles" id="tiles" style="margin-top:12px"></div>
  <div class="verdict" id="verdict"></div>
  <div class="ribbon" id="ribbon"></div>
  <div class="spark" id="ribbonKey"></div>
</section>

<div class="row">
  <section>
    <h2>The decision table &mdash; build power down, energy across</h2>
    <div class="ctl" style="margin-bottom:10px">
      <div class="seg" id="lens">
        <button data-lens="regime" class="on">Regime</button>
        <button data-lens="pick">What to build</button>
        <button data-lens="absorb">Target absorbs</button>
      </div>
    </div>
    <div id="table2d"></div>
    <div class="legend" id="legend"></div>
  </section>
  <section>
    <h2>What can eat your build power</h2>
    <div id="spectrum"></div>
  </section>
</div>

<section>
  <h2>The cadence &mdash; how long the next one takes, from here</h2>
  <div id="cadence"></div>
  <div id="cadenceTable"></div>
</section>

<section>
  <h2>The path &mdash; over for energy, down for build power</h2>
  <div id="ratio"></div>
  <div id="pathRuns"></div>
  <div id="pathWalk"></div>
</section>

<section>
  <h2>The mex budget &mdash; the room left to grow</h2>
  <div id="budget"></div>
</section>

<section>
  <h2>The cube &mdash; wind is depth</h2>
  <div class="ctl" style="margin-bottom:10px">
    <button id="spin" class="on">Auto-spin</button>
    <button id="reset">Reset view</button>
    <label>plane<select id="planeSel"></select></label>
    <span class="spark">drag to rotate</span>
  </div>
  <canvas id="cube" width="1000" height="520"></canvas>
</section>

<section>
  <h2>What this is saying</h2>
  <div class="note" id="notes"></div>
</section>
</main>
<div id="tip"></div>

<script>
/* ==== MODEL PORT BEGIN (extracted and run headlessly by --verify-port) ====
   Everything between these two markers is PURE: no DOM, no timers, no canvas.
   That is what lets the same code be checked from the command line. ==== */
const P = __PAYLOAD__;
const OBJ = P.objects, INF = Infinity;
const CFG = Object.assign({}, P.cfg);
const REG = {
  metal:    {ch:"M", css:"metal",    name:"metal bound - ON TARGET",
             fix:"nothing is wasted; the only gain left is a higher ceiling: another extractor"},
  bp:       {ch:"B", css:"bp",       name:"build power bound",
             fix:"metal and energy both idle; buy hands to spend them"},
  energy:   {ch:"E", css:"energy",   name:"energy bound",
             fix:"builders idle for want of energy; add the energy source"},
  overflow: {ch:"O", css:"overflow", name:"energy overflow",
             fix:"energy spilling is metal already spent returning nothing"}
};
const COL = {metal:"#2ea043", bp:"#3b82f6", energy:"#d29922", overflow:"#a371f7"};

/* ============ formatting ============ */
function fmt(v, d){
  if(v === INF) return "inf";
  if(v == null || isNaN(v)) return "-";
  if(d == null) d = Math.abs(v) < 10 ? 2 : 0;
  return v.toFixed(d);
}
function eShort(v){
  if(v === INF) return "inf";
  if(Math.abs(v) >= 10000) return (v/1000).toFixed(0) + "k";
  return v.toFixed(0);
}
function mmss(s){
  const m = Math.floor(s/60), r = Math.round(s - m*60);
  return m + ":" + (r < 10 ? "0" : "") + r;
}

/* ============ the model, ported from bar_unified.py ============ */
function drain(name, bp){
  const t = OBJ[name];
  if(!t || t.bp <= 0) return {sec:0, m:0, e:0};
  return {sec: bp ? t.bp/bp : INF, m: t.m*bp/t.bp, e: t.e*bp/t.bp};
}
function sustainable(name, mInc, eInc){
  const t = OBJ[name];
  const byM = t.m > 0 ? mInc*t.bp/t.m : INF;
  const byE = t.e > 0 ? eInc*t.bp/t.e : INF;
  return {byM, byE, bp: Math.min(byM, byE), binding: byM < byE ? "metal" : "energy"};
}
function runway(name, bp, mBank, eBank, mInc, eInc){
  const r = drain(name, bp), mg = r.m - mInc, eg = r.e - eInc;
  const tm = mg > 0 ? mBank/mg : INF, te = eg > 0 ? eBank/eg : INF;
  const t = Math.min(tm, te);
  return {sec:t, count: r.sec ? t/r.sec : 0,
          binding: tm < te ? "metal" : (te < tm ? "energy" : "neither")};
}
function ceilingE(bp, on){ return drain(on, bp).e; }
function regimeOf(mInc, eInc, bp, on, margin){
  const d = drain(on, bp), needM = d.m, needE = d.e;
  const sm = mInc < needM, se = eInc < needE;
  let r;
  if(sm && se) r = ((needM ? mInc/needM : 1) < (needE ? eInc/needE : 1)) ? "metal" : "energy";
  else if(sm) r = "metal";
  else if(se) r = "energy";
  else if(needE > 0 && eInc > needE*margin) r = "overflow";
  else r = "bp";
  return {regime:r, needM, needE, mRatio: needM ? mInc/needM : INF,
          eRatio: needE ? eInc/needE : INF};
}
function recommend(st, on, esrc, bpsrc){
  const r = regimeOf(st.mInc, st.eInc, st.bp, on, CFG.overflowMargin), reg = r.regime;
  let pick, why;
  if(reg === "bp"){ pick = bpsrc; why = "metal and energy are both idle; buy hands to spend them"; }
  else if(reg === "energy"){ pick = esrc; why = "builders idle for want of energy"; }
  else if(reg === "metal"){ pick = "Mex";
    why = "on target - metal-bound is where you want to be. Nothing is being wasted, so the only gain left is a higher ceiling: another extractor"; }
  else if(r.mRatio < 1.5){ pick = "Mex";
    why = "energy spilling and metal is the tighter of the two; an extractor eats 500 E and pays metal"; }
  else if(st.metal > 0.6*st.mCap){ pick = bpsrc;
    why = "energy spilling and metal banking; buy hands to spend both"; }
  else { pick = "EConverter";
    why = "metal is being spent and energy still spills; convert the remainder"; }
  return Object.assign({regime:reg, build:pick, why}, r);
}
function absorbProfile(st, unit, bp){
  const b = (bp == null) ? st.bp : bp, t = OBJ[unit], d = drain(unit, b);
  const feed = sustainable(unit, st.mInc, st.eInc);
  const absorbable = Math.min(b, feed.bp);
  const rw = runway(unit, b, st.metal, st.energy, st.mInc, st.eInc);
  return {unit, m:t.m, e:t.e, ratio: t.e === 0 ? INF : t.m/t.e,
          needM:d.m, needE:d.e, sec:d.sec, absorbable,
          share: b ? absorbable/b : 0, binding: feed.binding,
          runway: rw.sec, count: rw.count};
}
function advisor(st, cands, bp){
  const list = (cands || CFG.candidates).filter(u => OBJ[u]);
  const b = (bp == null) ? st.bp : bp;
  const profs = list.map(u => absorbProfile(st, u, b));
  profs.sort((x, y) => (y.share - x.share) || (x.sec - y.sec));
  const top = profs[0] || null;
  const surplus = st.eInc <= 0 ? INF : st.mInc/st.eInc;
  const overflow = st.eInc > ceilingE(b, "Mex");
  const metalDry = st.metal < 50 && st.mInc < drain("Mex", b).m*0.5;
  const famine = st.eInc < 20 || st.energy < 100;
  let advice = null, why = "";
  if(famine){ advice = "Solar";
    why = "energy famine: Solar is the only generator that costs no energy to erect, so it is buildable when Wind is not"; }
  else if(metalDry && overflow){ advice = "EConverter";
    why = "metal is gone and energy is spilling: a converter costs 1 metal and 1150 energy, so it converts the spill with nothing else to pay"; }
  else if(top && top.share >= 0.999){ advice = overflow ? "ConTurret" : "BotWorker";
    why = top.unit + " already absorbs all " + fmt(b, 0) + " build power, so build power is now the limit" +
          (overflow ? " - and energy is spilling, so buy the hungrier turret" : ""); }
  else if(top){ advice = top.unit;
    why = "absorbs " + fmt(top.share*100, 0) + "% of build power, the most of any candidate; bound by " + top.binding; }
  return {bp:b, profiles:profs, advice, why, surplus, overflow, metalDry, famine};
}
function projectRow(st, target, bpsrc, nBp, wind, horizon, dt){
  dt = dt || 0.25;
  let metal = st.metal, energy = st.energy;
  let mInc = st.mInc, eInc = st.eInc, bp = st.bp;
  let mCap = st.mCap, eCap = st.eCap;
  const queue = []; for(let k = 0; k < nBp; k++) queue.push(bpsrc);
  const events = [];
  let t = 0, cur = null, prog = 0, stalled = 0, nTarget = 0, guard = 0;
  while(t < horizon && guard++ < 200000){
    if(cur === null){ cur = queue.length ? queue.shift() : target; prog = 0; }
    const o = OBJ[cur];
    const needM = o.m*bp/o.bp*dt, needE = o.e*bp/o.bp*dt;
    const availM = metal + mInc*dt, availE = energy + eInc*dt;
    let scale = 1;
    if(needM > 0) scale = Math.min(scale, availM/needM);
    if(needE > 0) scale = Math.min(scale, availE/needE);
    scale = Math.max(0, Math.min(1, scale));
    if(scale < 0.999) stalled += dt;
    prog += scale*bp*dt/o.bp;
    metal = Math.min(metal + mInc*dt - needM*scale, mCap);
    energy = Math.min(energy + eInc*dt - needE*scale, eCap);
    t += dt;
    if(prog >= 1 - 1e-9){
      eInc += o.wind ? wind : o.eInc;
      mInc += o.mInc; bp += o.bpInc;
      if(o.storM) mCap += o.storM;
      if(o.storE) eCap += o.storE;
      const isT = (cur === target);
      if(isT) nTarget++;
      events.push({t: Math.round(t*100)/100, unit: cur, target: isT,
                   n: isT ? nTarget : null, bp, mInc, eInc});
      cur = null;
    }
  }
  const T = OBJ[target];
  const eff = Math.min(bp,
    T.m ? mInc*T.bp/T.m : INF,
    T.e ? eInc*T.bp/T.e : INF);
  return {nBp, events, targets:nTarget, endBp:bp, effBp:eff,
          stalled: Math.round(stalled*10)/10, mInc, eInc, metal, energy};
}
function effectiveBproi(unit, oldBp, effBp, nomBp){
  const t = OBJ[unit];
  const nominal = t.bpInc ? t.bp/t.bpInc : INF;
  const gN = oldBp ? nomBp/oldBp : 1, gE = oldBp ? effBp/oldBp : 1;
  const factor = gE > 0 ? gN/gE : INF;
  return {nominal, effective: nominal*factor, gN, gE,
          fed: gN ? gE/gN : 1};
}

/* ============ port parity: this page must reproduce Python ============ */
function near(a, b, tol){
  tol = tol || 1e-6;
  if(a === b) return true;
  if(a == null || b == null) return a === b;
  if(!isFinite(a) || !isFinite(b)) return a === b;
  return Math.abs(a - b) <= tol*Math.max(1, Math.abs(a), Math.abs(b));
}
function stateOf(f){
  return {t:f.t, metal:f.metal, energy:f.energy, mInc:f.mInc, eInc:f.eInc,
          bp:f.bp, mCap:f.mCap, eCap:f.eCap, wind:f.wind, counts:f.counts};
}
function checkPort(){
  const bad = [];
  let n = 0;
  const ES = OBJ[P.cfg.energySource], BS = OBJ[P.cfg.bpSource];
  for(const c of P.checks){
    const f = P.frames[c.frame], st = stateOf(f);
    let ok = true, got = null;
    if(c.kind === "regime"){
      const eOut = ES.wind ? c.wind : ES.eInc;
      const r = regimeOf(f.mInc + c.i*BS.mInc,
                         f.eInc + c.j*eOut + c.i*BS.eInc,
                         f.bp + c.i*BS.bpInc, P.cfg.on, P.cfg.overflowMargin);
      got = r.regime;
      ok = r.regime === c.regime && near(r.needM, c.needM) && near(r.needE, c.needE);
    } else if(c.kind === "absorb"){
      const a = absorbProfile(st, c.unit);
      got = a.share;
      ok = near(a.share, c.share) && near(a.needM, c.needM) &&
           near(a.needE, c.needE) && a.binding === c.binding;
    } else if(c.kind === "advice"){
      const a = advisor(st);
      got = a.advice;
      ok = a.advice === c.advice && a.overflow === c.overflow;
    } else if(c.kind === "project"){
      const pr = projectRow(st, P.cfg.target, P.cfg.bpSource, c.nBp, c.wind, P.cfg.horizon);
      got = pr.targets;
      ok = pr.targets === c.targets && near(pr.endBp, c.endBp) &&
           near(pr.effBp, c.effBp) && near(pr.events.length ? pr.events[0].t : null, c.firstT, 0.02);
    }
    n++;
    if(!ok) bad.push(c.kind + " f" + c.frame + " -> " + got + " want " +
                     (c.regime || c.advice || c.share || c.targets));
  }
  return {n, bad};
}
/* ==== MODEL PORT END ==== */

function paintParity(){
  const r = checkPort(), el = document.getElementById("parity");
  if(r.bad.length){
    el.className = "badge bad";
    el.textContent = "PORT DRIFT " + r.bad.length + "/" + r.n;
    el.title = r.bad.slice(0, 12).join(String.fromCharCode(10));
  } else {
    el.className = "badge ok";
    el.textContent = "port matches Python " + r.n + "/" + r.n;
    el.title = "every sampled cell, absorption profile, verdict and projection reproduces bar_unified.py";
  }
  return r;
}

/* ============ state ============ */
let mode = "replay", fi = P.startFrame, playing = false, timer = null;
let sand = null, lens = "regime";
let rotY = -0.62, rotX = 0.42, spin = true, planeIdx = 0, dragging = false;

function currentState(){
  if(mode === "sandbox") return sand;
  return stateOf(P.frames[fi]);
}
function eOutOf(wind){
  const ES = OBJ[CFG.energySource];
  return ES.wind ? wind : ES.eInc;
}
function cellState(st, i, j, wind){
  const BS = OBJ[CFG.bpSource], eOut = eOutOf(wind);
  return {t:st.t, metal:st.metal, energy:st.energy, mCap:st.mCap, eCap:st.eCap,
          wind, bp: st.bp + i*BS.bpInc,
          mInc: st.mInc + i*BS.mInc,
          eInc: st.eInc + j*eOut + i*BS.eInc};
}

/* ============ header, tiles, verdict ============ */
function drawHead(){
  const g = P.game, p = P.player;
  document.getElementById("hmeta").textContent =
    [g.id, g.map, g.matchup, p.name ? p.name + " (team " + p.team + ", " + p.faction + ")" : null,
     "generated " + P.generated].filter(Boolean).join("  |  ");
}
function drawTiles(){
  const st = currentState();
  const on = CFG.on, cap = ceilingE(st.bp, on);
  const r = regimeOf(st.mInc, st.eInc, st.bp, on, CFG.overflowMargin);
  const f = mode === "replay" ? P.frames[fi] : null;
  const tiles = [
    ["time", mode === "replay" ? mmss(st.t) : "sandbox", mode === "replay" ? st.t.toFixed(0) + " s" : "no game"],
    ["metal income", fmt(st.mInc, 2), "need " + fmt(r.needM, 2) + " for " + on],
    ["energy income", eShort(st.eInc), "need " + eShort(r.needE) + ", ceiling " + eShort(cap)],
    ["build power", fmt(st.bp, 0), f ? "used " + fmt(f.bpUsed, 0) : "nominal"],
    ["metal bank", fmt(st.metal, 0), "cap " + fmt(st.mCap, 0)],
    ["energy bank", eShort(st.energy), "cap " + eShort(st.eCap)],
    ["wind", fmt(st.wind, 1), "E/s per turbine"]
  ];
  document.getElementById("tiles").innerHTML = tiles.map(t =>
    '<div class="tile"><div class="k">' + t[0] + '</div><div class="v">' + t[1] +
    '</div><div class="s">' + t[2] + '</div></div>').join("");

  const rec = recommend(st, on, CFG.energySource, CFG.bpSource);
  const a = advisor(st);
  const top = a.profiles[0];
  const actual = f && f.started.length ? f.started.join(", ") : (f ? "nothing started" : null);
  let html = '<span class="chip c-' + REG[rec.regime].css + '">' + REG[rec.regime].name + "</span>" +
    '<div style="margin-top:8px"><b>' + a.advice + "</b> &nbsp;<span class=spark>by absorption</span>" +
    " &nbsp;&middot;&nbsp; <b>" + rec.build + "</b> &nbsp;<span class=spark>by regime</span></div>" +
    '<div class="why">' + a.why + "</div>" +
    '<div class="why">regime says ' + rec.build + ": " + rec.why + "</div>" +
    '<div class="why">surplus ratio 1 metal : ' +
      (st.mInc > 0 ? fmt(st.eInc/st.mInc, 0) : "inf") + " energy per second" +
      " &nbsp;&middot;&nbsp; " + CFG.target + " burns 1 : " +
      (OBJ[CFG.target].m ? fmt(OBJ[CFG.target].e/OBJ[CFG.target].m, 0) : "inf") +
      " &nbsp;&middot;&nbsp; best absorber " + top.unit + " eats " + fmt(top.share*100, 0) + "%" +
      (a.overflow ? " &nbsp;&middot;&nbsp; ENERGY SPILLING" : "") + "</div>" +
    (actual ? '<div class="why">actually started next: <b>' + actual + "</b></div>" : "");
  document.getElementById("verdict").innerHTML = html;
}
function drawRibbon(){
  const box = document.getElementById("ribbon");
  if(mode !== "replay"){ box.innerHTML = ""; document.getElementById("ribbonKey").textContent = ""; return; }
  box.innerHTML = P.frames.map((f, k) => {
    const st = stateOf(f);
    const r = regimeOf(st.mInc, st.eInc, st.bp, CFG.on, CFG.overflowMargin);
    const a = advisor(st);
    const h = Math.round(6 + 36*Math.min(1, (a.profiles[0] || {share:0}).share));
    return '<div class="rib' + (k === fi ? " sel" : "") + '" data-k="' + k +
      '" title="' + mmss(f.t) + "  " + REG[r.regime].name + "  advice " + a.advice +
      (f.started.length ? "  started " + f.started.join(",") : "") +
      '" style="background:' + COL[r.regime] + ';justify-content:flex-end">' +
      '<div style="height:' + h + 'px;background:rgba(0,0,0,.18)"></div>' +
      "<span>" + (a.advice || "?").slice(0, 2) + "</span></div>";
  }).join("");
  box.querySelectorAll(".rib").forEach(el => el.onclick = () => {
    fi = +el.dataset.k; stop(); render();
  });
  document.getElementById("ribbonKey").textContent =
    "one block per measured 15 s sample: colour = regime, dark bar = how much of build power the best target could absorb, letters = the advice. Click to jump.";
}

/* ============ 2-D decision table ============ */
function drawTable(){
  const st = currentState(), on = CFG.on;
  const BS = OBJ[CFG.bpSource], eOut = eOutOf(st.wind);
  let h = '<table class="grid"><tr><th></th>';
  for(let j = 0; j <= CFG.nEnergy; j++) h += "<th>" + j + "</th>";
  h += '<th style="text-align:left;padding-left:8px">+ ' + CFG.energySource + "</th></tr>";
  for(let i = 0; i <= CFG.nBp; i++){
    h += "<tr><th>+" + i + "</th>";
    for(let j = 0; j <= CFG.nEnergy; j++){
      const cs = cellState(st, i, j, st.wind);
      const r = regimeOf(cs.mInc, cs.eInc, cs.bp, on, CFG.overflowMargin);
      let bg, txt;
      if(lens === "regime"){ bg = COL[r.regime]; txt = REG[r.regime].ch; }
      else if(lens === "pick"){
        const rec = recommend(cs, on, CFG.energySource, CFG.bpSource);
        bg = COL[r.regime]; txt = rec.build.slice(0, 2);
      } else {
        const a = absorbProfile(cs, CFG.target);
        const v = Math.min(1, a.share);
        bg = "rgba(88,166,255," + (0.10 + 0.9*v).toFixed(3) + ")";
        txt = Math.round(v*100);
      }
      h += '<td class="cell' + (i === 0 && j === 0 ? " here" : "") + '" style="background:' + bg +
        '" data-i="' + i + '" data-j="' + j + '">' + txt + "</td>";
    }
    h += '<th style="text-align:left;padding-left:8px">BP ' + fmt(st.bp + i*BS.bpInc, 0) + "</th></tr>";
  }
  h += "</table>";
  h += '<div class="spark" style="margin-top:6px">rows add ' + CFG.bpSource + " (+" +
    fmt(BS.bpInc, 0) + " BP, " + (BS.eInc >= 0 ? "+" : "") + fmt(BS.eInc, 0) +
    " E/s each) &nbsp;|&nbsp; columns add " + CFG.energySource + " (" + fmt(eOut, 1) +
    " E/s each) &nbsp;|&nbsp; ringed cell is where you are</div>";
  const box = document.getElementById("table2d");
  box.innerHTML = h;
  box.querySelectorAll("td.cell").forEach(td => {
    td.onmousemove = ev => {
      const i = +td.dataset.i, j = +td.dataset.j;
      const cs = cellState(st, i, j, st.wind);
      const r = regimeOf(cs.mInc, cs.eInc, cs.bp, on, CFG.overflowMargin);
      const rec = recommend(cs, on, CFG.energySource, CFG.bpSource);
      const a = advisor(cs);
      const ab = absorbProfile(cs, CFG.target);
      showTip(ev,
        "+" + i + " " + CFG.bpSource + "   +" + j + " " + CFG.energySource +
        String.fromCharCode(10) + fmt(cs.mInc, 2) + " M/s   " + eShort(cs.eInc) + " E/s   BP " + fmt(cs.bp, 0) +
        String.fromCharCode(10) + REG[r.regime].name.toUpperCase() +
        String.fromCharCode(10) + "needs " + fmt(r.needM, 2) + " M/s and " + eShort(r.needE) + " E/s for " + on +
        String.fromCharCode(10) + "metal at " + fmt(r.mRatio, 2) + "x need, energy at " + fmt(r.eRatio, 2) + "x" +
        String.fromCharCode(10) + CFG.target + " would absorb " + fmt(ab.share*100, 0) + "% of build power (bound by " + ab.binding + ")" +
        String.fromCharCode(10) + "regime says " + rec.build + ", absorption says " + a.advice);
    };
    td.onmouseleave = hideTip;
  });
  document.getElementById("legend").innerHTML = Object.keys(REG).map(k =>
    "<span><i style='background:" + COL[k] + "'></i>" + REG[k].ch + " " + REG[k].name +
    " &mdash; " + REG[k].fix + "</span>").join("");
}

/* ============ absorption spectrum ============ */
function drawSpectrum(){
  const st = currentState(), a = advisor(st);
  const W = 470, rowH = 26, H = a.profiles.length*rowH + 96;
  const barX = 132, barW = 210;
  let s = '<svg viewBox="0 0 ' + W + " " + H + '" width="' + W + '">';
  s += '<text x="0" y="12" fill="#8b96a5" font-size="10">share of ' + fmt(st.bp, 0) +
       ' BP this target can consume</text>';
  a.profiles.forEach((p, k) => {
    const y = 26 + k*rowH;
    const w = Math.max(1, barW*Math.min(1, p.share));
    const col = k === 0 ? "#58a6ff" : "#3b4a5e";
    s += '<text x="0" y="' + (y + 11) + '" fill="' + (k === 0 ? "#e6edf3" : "#8b96a5") +
         '" font-size="11">' + p.unit + "</text>";
    s += '<rect x="' + barX + '" y="' + y + '" width="' + barW + '" height="15" rx="3" fill="#1b222c"/>';
    s += '<rect x="' + barX + '" y="' + y + '" width="' + w + '" height="15" rx="3" fill="' + col + '"/>';
    s += '<text x="' + (barX + barW + 7) + '" y="' + (y + 11) + '" fill="#8b96a5" font-size="10">' +
         fmt(p.share*100, 0) + "%  " + p.binding + "</text>";
    s += '<text x="' + (barX - 6) + '" y="' + (y + 11) + '" fill="#5a6472" font-size="9" text-anchor="end">' +
         (p.e === 0 ? "pure metal" : "1:" + fmt(p.e/Math.max(p.m, 1e-9), 0)) + "</text>";
  });
  // the ratio spectrum: log axis of energy per metal, with the surplus marked
  const y0 = 26 + a.profiles.length*rowH + 26;
  const lo = 1, hi = 2000;
  const lx = v => 24 + (Math.log10(Math.max(lo, Math.min(hi, v))) - Math.log10(lo)) /
                       (Math.log10(hi) - Math.log10(lo)) * (W - 70);
  s += '<text x="0" y="' + (y0 - 10) + '" fill="#8b96a5" font-size="10">' +
       'the ratio spectrum: energy burned per metal burned (log)</text>';
  s += '<line x1="24" y1="' + y0 + '" x2="' + (W - 46) + '" y2="' + y0 + '" stroke="#2b3340"/>';
  [1, 10, 100, 1000].forEach(v => {
    s += '<line x1="' + lx(v) + '" y1="' + (y0 - 4) + '" x2="' + lx(v) + '" y2="' + (y0 + 4) + '" stroke="#2b3340"/>';
    s += '<text x="' + lx(v) + '" y="' + (y0 + 16) + '" fill="#5a6472" font-size="9" text-anchor="middle">' + v + "</text>";
  });
  a.profiles.forEach(p => {
    const v = p.m > 0 ? p.e/p.m : hi;
    const x = p.e === 0 ? 24 : lx(v);
    const hit = p.unit === a.advice;
    s += '<circle cx="' + x + '" cy="' + y0 + '" r="' + (hit ? 5 : 3) + '" fill="' +
         (hit ? "#58a6ff" : "#5a6472") + '"/>';
    s += '<text x="' + x + '" y="' + (y0 - 9) + '" fill="' + (hit ? "#e6edf3" : "#5a6472") +
         '" font-size="8" text-anchor="middle" transform="rotate(-32 ' + x + " " + (y0 - 9) + ')">' +
         p.unit + "</text>";
  });
  const sr = st.mInc > 0 ? st.eInc/st.mInc : hi;
  const sx = lx(sr);
  s += '<line x1="' + sx + '" y1="' + (y0 - 22) + '" x2="' + sx + '" y2="' + (y0 + 22) +
       '" stroke="#2ea043" stroke-width="2"/>';
  s += '<text x="' + sx + '" y="' + (y0 + 34) + '" fill="#2ea043" font-size="10" text-anchor="middle">' +
       "your surplus 1:" + fmt(sr, 0) + "</text>";
  s += "</svg>";
  s += '<div class="spark" style="margin-top:8px">A target whose ratio sits near the green line burns your surplus at the ratio you have it in. Solar at the far left is a pure metal sink and the only generator that costs no energy to erect; EConverter at the far right is a pure energy sink at 1 metal.</div>';
  document.getElementById("spectrum").innerHTML = s;
}

/* ============ the cadence, the path, the budget ============
   These three are computed in Python and shipped per measured frame. The lattice and
   the spectrum above are ported to JavaScript because sliders need them instantly;
   the cadence walk and the path search step a full state hundreds of times, so a
   second copy would be the most intricate code in the model duplicated for nothing.
   In sandbox mode these panels therefore show the nearest REPLAY frame and say so. */

function extrasNow(){
  return (P.extras && P.extras[fi]) ? P.extras[fi] : null;
}
const BOUNDCOL = {none:"#3b82f6", metal:"#2ea043", energy:"#d29922",
                  "build power":"#a371f7"};

function drawCadence(){
  const ex = extrasNow();
  const box = document.getElementById("cadence");
  const tbl = document.getElementById("cadenceTable");
  if(!ex){ box.innerHTML = '<div class=spark>no cadence for this frame</div>'; tbl.innerHTML = ""; return; }
  const cd = ex.cadence, span = Math.max(1, cd.span);
  const W = 980, left = 118, right = 54, rowH = 34;
  const H = cd.rows.length*rowH + 74;
  const sx = t => left + t/span*(W - left - right);
  let s = '<svg viewBox="0 0 ' + W + " " + H + '" width="' + W + '">';
  // phase bands, shaded from each boundary to the next
  const bands = (cd.bands || []).filter(b => b.phase && b.phase !== "?");
  bands.forEach((b, k) => {
    const x0 = sx(b.t), x1 = k + 1 < bands.length ? sx(bands[k + 1].t) : sx(span);
    s += '<rect x="' + x0 + '" y="26" width="' + Math.max(0, x1 - x0) + '" height="' +
         (cd.rows.length*rowH + 8) + '" fill="' + (k % 2 ? "#ffffff" : "#58a6ff") +
         '" opacity="0.045"/>';
    s += '<line x1="' + x0 + '" y1="20" x2="' + x0 + '" y2="' +
         (cd.rows.length*rowH + 34) + '" stroke="#3b4a5e" stroke-dasharray="2 3"/>';
    s += '<text x="' + (x0 + 4) + '" y="16" fill="#8b96a5" font-size="9">' +
         b.phase + " @" + fmt(b.t, 0) + "s</text>";
  });
  // time axis
  let step = 15;
  for(const c of [5, 10, 15, 30, 60, 120, 300]){ if(span/c <= 9){ step = c; break; } }
  for(let t = 0; t <= span; t += step){
    s += '<text x="' + sx(t) + '" y="' + (cd.rows.length*rowH + 48) +
         '" fill="#5a6472" font-size="9" text-anchor="middle">' + t + "</text>";
  }
  s += '<text x="' + (W - right + 6) + '" y="' + (cd.rows.length*rowH + 48) +
       '" fill="#5a6472" font-size="9">s</text>';
  // rows
  cd.rows.forEach((r, i) => {
    const y = 30 + i*rowH;
    s += '<text x="0" y="' + (y + 16) + '" fill="#8b96a5" font-size="10">+' +
         r.n_scale + " " + CFG.bpSource + "</text>";
    r.segments.forEach(sg => {
      const x0 = sx(sg.t_start), x1 = sx(sg.t_end), w = Math.max(1.5, x1 - x0);
      const invest = sg.kind === "invest";
      const col = invest ? "#8957e5" : BOUNDCOL[sg.bound] || "#3b82f6";
      s += '<rect x="' + x0 + '" y="' + y + '" width="' + w + '" height="22" rx="2" fill="' +
           col + '" opacity="' + (invest ? 0.9 : 0.78) + '"/>';
      const lab = invest ? ("B " + fmt(sg.dt, 0) + "s")
                         : ("+" + (sg.dt >= 9.5 ? fmt(sg.dt, 0) : fmt(sg.dt, 1)));
      if(w >= lab.length*6.1 + 5)
        s += '<text x="' + (x0 + w/2) + '" y="' + (y + 15) +
             '" fill="#04101f" font-size="9.5" font-weight="700" text-anchor="middle">' +
             lab + "</text>";
      s += '<title>' + (invest ? CFG.bpSource + " investment" : CFG.target + " #" + sg.n) +
           "  +" + fmt(sg.dt, 2) + "s (nominal " + fmt(sg.nominal, 2) + "s" +
           (sg.walk_sec ? ", walk " + fmt(sg.walk_sec, 1) + "s" : "") + ")" +
           "  bound by " + sg.bound + "  BP " + fmt(sg.bp, 0) +
           "  " + fmt(sg.m_inc, 2) + " M/s  " + eShort(sg.e_inc) + " E/s" +
           "  phase " + sg.phase + "</title>";
    });
    if(r.crossover)
      s += '<line x1="' + sx(r.crossover.t) + '" y1="' + (y - 4) + '" x2="' +
           sx(r.crossover.t) + '" y2="' + (y + 26) + '" stroke="#2ea043" stroke-width="2.5"/>';
    s += '<text x="' + (W - right + 6) + '" y="' + (y + 16) +
         '" fill="#8b96a5" font-size="10">' + r.targets + "x</text>";
  });
  s += "</svg>";
  box.innerHTML = s;

  let h = '<div class="legend"><span><i style="background:#3b82f6"></i>on pace</span>' +
    '<span><i style="background:#2ea043"></i>metal-bound, stretched</span>' +
    '<span><i style="background:#d29922"></i>energy-bound, stretched</span>' +
    '<span><i style="background:#8957e5"></i>the ' + CFG.bpSource + ' investment</span>' +
    '<span>green tick = catches row +0</span></div>';
  h += '<table class="data"><tr><th>row</th><th>' + CFG.target + "s</th>" +
    "<th>nominal each</th><th>invest</th><th>1st</th><th>5th</th><th>10th</th>" +
    "<th>20th</th><th>stall</th><th>first bound</th><th>catches +0</th></tr>";
  cd.rows.forEach((r, i) => {
    const g = k => (r.at[k] == null ? "-" : fmt(r.at[k], 0) + "s");
    const fb = r.first_bound ? ("#" + r.first_bound.n + " " + r.first_bound.bound +
                                " @" + fmt(r.first_bound.t, 0) + "s") : "never";
    const co = !r.n_scale ? "baseline"
             : (r.crossover ? fmt(r.crossover.t, 0) + "s at #" + r.crossover.n : "no");
    h += "<tr" + (i === 0 ? ' class="hi"' : "") + "><td>+" + r.n_scale + " " +
      CFG.bpSource + "</td><td>" + r.targets + "</td><td>" + fmt(r.nominal_each, 1) +
      "s</td><td>" + fmt(r.invest_sec, 0) + "s</td><td>" + g(1) + "</td><td>" + g(5) +
      "</td><td>" + g(10) + "</td><td>" + g(20) + "</td><td>" + fmt(r.stall_sec, 0) +
      "s</td><td>" + fb + "</td><td>" + co + "</td></tr>";
  });
  h += "</table>";
  const stops = cd.rows.filter(r => r.stopped);
  if(stops.length)
    h += '<div class="spark" style="margin-top:6px">' + stops.map(r =>
      "row +" + r.n_scale + " stopped early: " + r.stopped).join(" &middot; ") + "</div>";
  h += '<div class="spark" style="margin-top:6px">Every cell is ONE ' + CFG.target +
    " and its WIDTH is the seconds that one took, computed from the state at that " +
    "moment. Hover a cell for its nominal time, its walk, what bound it and the " +
    "position it landed in. Rows share the axis, so the gap on the right of a lower " +
    "row is what stopping to scale cost." +
    (mode === "sandbox" ? " <b>Sandbox: these panels show replay frame " + fi +
      ", they are not driven by the sliders.</b>" : "") + "</div>";
  tbl.innerHTML = h;
}

function drawPath(){
  const ex = extrasNow();
  const rbox = document.getElementById("ratio");
  const runbox = document.getElementById("pathRuns");
  const wbox = document.getElementById("pathWalk");
  if(!ex){ rbox.innerHTML = ""; runbox.innerHTML = ""; wbox.innerHTML = ""; return; }
  const pa = ex.path;
  rbox.innerHTML = '<div class="verdict"><div class="k" style="font-size:10px;color:var(--dim)">' +
    "SUGGESTED BUILD RATIO</div><b style='font-size:22px'>" + pa.ratio.label + "</b>" +
    '<div class="why">objective <b>' + pa.objective + "</b>: " + pa.score_detail +
    " &nbsp;&middot;&nbsp; crossing when the work could feed " +
    fmt(pa.threshold*100, 0) + "% of build power" +
    " &nbsp;&middot;&nbsp; going right pays until energy covers " +
    eShort(pa.e_need_projected) + " E/s</div></div>";

  let h = '<table class="data"><tr><th>cross at</th><th>overs</th><th>crosses</th>' +
    "<th>ratio</th><th>score</th><th>what the score says</th></tr>";
  pa.runs.forEach(r => {
    const hi = Math.abs(r.threshold - pa.threshold) < 1e-9;
    h += "<tr" + (hi ? ' class="hi"' : "") + "><td>" + fmt(r.threshold*100, 0) +
      "%</td><td>" + r.overs + "</td><td>" + r.crosses + "</td><td>" +
      (r.ratio.per_cross == null ? "-" : fmt(r.ratio.per_cross, 2)) + "</td><td>" +
      fmt(r.score, 3) + "</td><td style='text-align:left'>" + r.score_detail +
      (hi ? "  <b>chosen</b>" : "") + "</td></tr>";
  });
  h += "</table>";
  runbox.innerHTML = h;

  const rows = pa.steps.filter(x => x.kind !== "over").slice(0, 24);
  const overs = pa.steps.filter(x => x.kind === "over").length;
  let w = '<table class="data"><tr><th>t</th><th>move</th><th>unit</th><th>+s</th>' +
    "<th>feeds</th><th>mex</th><th>regime</th><th>why</th></tr>";
  w += "<tr><td>0s</td><td><b>over x" + overs + "</b></td><td>" + CFG.target +
    "</td><td>-</td><td>-</td><td>-</td><td>-</td>" +
    "<td style='text-align:left'>building energy while it still pays</td></tr>";
  rows.forEach(x => {
    const t = x.t_end != null ? x.t_end : x.t;
    w += "<tr><td>" + fmt(t, 0) + "s</td><td><b>" + x.kind.toUpperCase() +
      "</b></td><td>" + (x.unit || "-") + "</td><td>" +
      (x.dt == null ? "-" : fmt(x.dt, 1)) + "</td><td>" +
      (x.feed_ratio == null ? "-" : fmt(x.feed_ratio*100, 0) + "%") + "</td><td>" +
      (x.mex == null ? "-" : x.mex) + "</td><td>" + (x.regime || "-") +
      "</td><td style='text-align:left'>" + (x.why || "") + "</td></tr>";
  });
  w += "</table>";
  if(pa.exit_reason)
    w += '<div class="spark" style="margin-top:6px"><b>Walk ended at ' +
      fmt(pa.elapsed, 0) + "s.</b> " + pa.exit_reason +
      (pa.off_chart ? " &nbsp;&rarr;&nbsp; next move is off this chart: <b>" +
        pa.off_chart + "</b>" : "") + "</div>";
  w += '<div class="spark" style="margin-top:4px">Waiting is not idling: energy already ' +
    "covers the budget and hands are not yet justified, so the position is waiting for " +
    "extractors its workers are already walking to. " + fmt(pa.waited_sec, 0) +
    "s of the " + fmt(pa.elapsed, 0) + "s was spent waiting.</div>";
  wbox.innerHTML = w;
}

function drawBudget(){
  const ex = extrasNow();
  const box = document.getElementById("budget");
  if(!ex){ box.innerHTML = ""; return; }
  const b = ex.budget, ph = ex.phases;
  const flatWrong = Math.abs(b.flat_estimate - b.m_per_s_projected) >= 0.01;
  let h = '<div class="tiles">' + [
    ["position", b.position || "-", b.count + " spots on " + b.map],
    ["standing", b.standing, b.m_per_s_current.toFixed(2) + " m/s now"],
    ["room", b.room, b.m_per_s_remaining.toFixed(2) + " m/s still to claim"],
    ["projected", b.m_per_s_projected.toFixed(2), "m/s with the budget held"],
    ["claiming", ph.mex.phase, ph.mex.expected_complete_sec == null ? "all claimed"
      : "all in +" + fmt(ph.mex.expected_complete_sec, 0) + "s"],
    ["spending", ph.energy.phase, "need " + eShort(ph.energy.e_need_projected) +
      " E/s and " + fmt(ph.energy.bp_need_projected, 0) + " BP"]
  ].map(t => '<div class="tile"><div class="k">' + t[0] + '</div><div class="v">' + t[1] +
    '</div><div class="s">' + t[2] + "</div></div>").join("") + "</div>";
  if(b.room <= 0)
    h += '<div class="verdict" style="border-left-color:var(--warn)"><b>CAPPED</b>' +
      '<div class="why">No room left. Metal-bound here does not mean "build another ' +
      'extractor" &mdash; the ceiling is fixed. An advanced extractor, reclaim, or a ' +
      'converter are the only ways up.</div></div>';
  h += '<table class="data" style="max-width:640px"><tr><th>n</th><th>distance</th>' +
    "<th>walk</th><th>m/s</th><th>cumulative</th><th>held</th></tr>";
  let c = 0;
  b.spots.forEach(sp => {
    c += sp.metal_per_s;
    const rich = (b.rich_spots || []).indexOf(sp.n) >= 0;
    h += "<tr" + (sp.n <= b.standing ? ' class="hi"' : "") + "><td>" + sp.n +
      (rich ? " <b style='color:var(--metal)'>RICH</b>" : "") + "</td><td>" +
      fmt(sp.distance, 0) + "</td><td>" + fmt(sp.walk_sec, 1) + "s</td><td>" +
      sp.metal_per_s.toFixed(3) + "</td><td>" + c.toFixed(2) + "</td><td>" +
      (sp.n <= b.standing ? "yes" : "-") + "</td></tr>";
  });
  h += "</table>";
  h += '<div class="spark" style="margin-top:6px">Walks are measured from the spawn, ' +
    "which answers reachability. The cadence and the claim plan instead route " +
    "nearest-next from where the builder is standing: " + fmt(b.walk_routed_sec, 0) +
    "s routed against " + fmt(b.walk_sum_from_spawn_sec, 0) +
    "s if you wrongly summed the from-spawn figures. " +
    (flatWrong ? "A flat " + b.count + " x 1.825 would say " +
      b.flat_estimate.toFixed(2) + " m/s and be WRONG by " +
      (b.m_per_s_projected - b.flat_estimate).toFixed(2) + " m/s."
     : "No rich spot is in reach here, so a flat count happens to agree.") + "</div>";
  box.innerHTML = h;
}

/* ============ the cube ============ */
const cv = document.getElementById("cube"), cx2 = cv.getContext("2d");
function proj(x, y, z, scale, ox, oy){
  const cY = Math.cos(rotY), sY = Math.sin(rotY);
  const X = x*cY - z*sY, Z = x*sY + z*cY;
  const cX = Math.cos(rotX), sX = Math.sin(rotX);
  const Y = y*cX - Z*sX, D = y*sX + Z*cX;
  return [ox + X*scale, oy + Y*scale, D];
}
function drawCube(){
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const wantW = cv.clientWidth || 1000, wantH = 520;
  if(cv.width !== Math.round(wantW*dpr)){
    cv.width = Math.round(wantW*dpr); cv.height = Math.round(wantH*dpr);
  }
  cx2.setTransform(dpr, 0, 0, dpr, 0, 0);
  cx2.clearRect(0, 0, wantW, wantH);
  const st = currentState(), on = CFG.on;
  const depth = CFG.depth, gap = 5.2;
  const scale = Math.min(wantW/(CFG.nEnergy + depth.length*gap + 6), 30);
  const ox = wantW*0.30, oy = wantH*0.46;
  const quads = [];
  depth.forEach((wind, k) => {
    const z = (k - (depth.length - 1)/2)*gap;
    const active = k === planeIdx;
    for(let i = 0; i <= CFG.nBp; i++){
      for(let j = 0; j <= CFG.nEnergy; j++){
        const cs = cellState(st, i, j, wind);
        const r = regimeOf(cs.mInc, cs.eInc, cs.bp, on, CFG.overflowMargin);
        const x = j - CFG.nEnergy/2, y = i - CFG.nBp/2;
        const pts = [[x - 0.44, y - 0.44], [x + 0.44, y - 0.44],
                     [x + 0.44, y + 0.44], [x - 0.44, y + 0.44]]
          .map(p => proj(p[0], p[1], z, scale, ox, oy));
        const d = (pts[0][2] + pts[2][2])/2;
        quads.push({pts, d, col: COL[r.regime], a: active ? 0.95 : 0.22,
                    mark: (i === 0 && j === 0) ? k : -1, active});
      }
    }
    quads.push({label: fmt(wind, 1) + " E/s", lp: proj(-CFG.nEnergy/2 - 1.6, CFG.nBp/2 + 1.3, z, scale, ox, oy),
                d: proj(0, 0, z, scale, ox, oy)[2], active});
  });
  quads.sort((a, b) => a.d - b.d);
  for(const q of quads){
    if(q.label){
      cx2.fillStyle = q.active ? "#e6edf3" : "#5a6472";
      cx2.font = (q.active ? "bold " : "") + "11px ui-monospace,monospace";
      cx2.fillText(q.label, q.lp[0] - 14, q.lp[1]);
      continue;
    }
    cx2.globalAlpha = q.a;
    cx2.beginPath();
    cx2.moveTo(q.pts[0][0], q.pts[0][1]);
    for(let n = 1; n < 4; n++) cx2.lineTo(q.pts[n][0], q.pts[n][1]);
    cx2.closePath();
    cx2.fillStyle = q.col;
    cx2.fill();
    if(q.mark >= 0){
      cx2.globalAlpha = 1;
      cx2.strokeStyle = q.active ? "#ffffff" : "#8b96a5";
      cx2.lineWidth = q.active ? 2.2 : 1;
      cx2.stroke();
    }
  }
  cx2.globalAlpha = 1;
  // axes
  const a0 = proj(-CFG.nEnergy/2 - 0.8, CFG.nBp/2 + 0.8, 0, scale, ox, oy);
  const aE = proj(CFG.nEnergy/2 + 1.2, CFG.nBp/2 + 0.8, 0, scale, ox, oy);
  const aB = proj(-CFG.nEnergy/2 - 0.8, -CFG.nBp/2 - 1.2, 0, scale, ox, oy);
  cx2.strokeStyle = "#3b4a5e"; cx2.lineWidth = 1;
  cx2.beginPath(); cx2.moveTo(a0[0], a0[1]); cx2.lineTo(aE[0], aE[1]);
  cx2.moveTo(a0[0], a0[1]); cx2.lineTo(aB[0], aB[1]); cx2.stroke();
  cx2.fillStyle = "#8b96a5"; cx2.font = "11px ui-monospace,monospace";
  cx2.fillText("+ " + CFG.energySource + " ->", aE[0] - 40, aE[1] + 16);
  cx2.save();
  cx2.translate(aB[0] - 10, aB[1]);
  cx2.fillText("+ " + CFG.bpSource, 0, -4);
  cx2.restore();
  // hud
  const r0 = regimeOf(st.mInc, st.eInc, st.bp, on, CFG.overflowMargin);
  cx2.fillStyle = "#e6edf3"; cx2.font = "bold 13px ui-monospace,monospace";
  cx2.fillText((mode === "replay" ? mmss(st.t) : "sandbox") + "   " + REG[r0.regime].name, 12, 22);
  cx2.fillStyle = "#8b96a5"; cx2.font = "11px ui-monospace,monospace";
  cx2.fillText(fmt(st.mInc, 2) + " M/s   " + eShort(st.eInc) + " E/s   BP " + fmt(st.bp, 0) +
               "   wind " + fmt(st.wind, 1), 12, 39);
  cx2.fillText("ringed cell = where you are on each plane", 12, wantH - 12);
}
function fitPlane(){
  const st = currentState();
  let best = 0, bd = INF;
  CFG.depth.forEach((w, k) => { const d = Math.abs(w - st.wind); if(d < bd){ bd = d; best = k; } });
  planeIdx = best;
  const sel = document.getElementById("planeSel");
  if(sel.value !== String(best)) sel.value = String(best);
}
let lastT = 0;
function loop(ts){
  if(spin && !dragging){ rotY += (ts - lastT)*0.00016; }
  lastT = ts;
  drawCube();
  requestAnimationFrame(loop);
}
cv.addEventListener("pointerdown", ev => {
  dragging = true; cv.classList.add("drag"); cv.setPointerCapture(ev.pointerId);
  cv._px = ev.clientX; cv._py = ev.clientY;
});
cv.addEventListener("pointermove", ev => {
  if(!dragging) return;
  rotY += (ev.clientX - cv._px)*0.008;
  rotX = Math.max(-1.35, Math.min(1.35, rotX + (ev.clientY - cv._py)*0.006));
  cv._px = ev.clientX; cv._py = ev.clientY;
});
cv.addEventListener("pointerup", () => { dragging = false; cv.classList.remove("drag"); });

/* ============ tooltip ============ */
const tip = document.getElementById("tip");
function showTip(ev, text){
  tip.textContent = text;
  tip.style.display = "block";
  const r = tip.getBoundingClientRect();
  let x = ev.clientX + 14, y = ev.clientY + 14;
  if(x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
  if(y + r.height > innerHeight - 8) y = ev.clientY - r.height - 14;
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
function hideTip(){ tip.style.display = "none"; }

/* ============ notes ============ */
function drawNotes(){
  const st = currentState();
  const a = advisor(st);
  const top = a.profiles[0], bottom = a.profiles[a.profiles.length - 1];
  document.getElementById("notes").innerHTML =
    "<p><b>Every structure burns metal and energy in a fixed ratio.</b> At build power B a target draws " +
    "<code>Mc*B/W</code> metal per second and <code>Ec*B/W</code> energy per second, so the ratio is just " +
    "its own cost ratio Mc:Ec. That is why <b>&quot;I cannot spend my build power&quot; is a statement about the " +
    "target, never about the position</b>. Right now " + top.unit + " could eat " + fmt(top.share*100, 0) +
    "% of your " + fmt(st.bp, 0) + " build power and " + bottom.unit + " only " + fmt(bottom.share*100, 0) + "%.</p>" +
    "<p><b>The inverse is the signal to buy build power.</b> When the best target absorbs everything, resources " +
    "are no longer the limit and hands are. If energy is what blocks buying hands, the energy-friendly " +
    "generator comes first: Solar costs no energy to erect, so it is the only generator that is buildable " +
    "during an energy famine.</p>" +
    "<p><b>Metal bound is the goal.</b> The other three regimes are all forms of waste: idle builders, idle " +
    "metal, or spilled energy. Metal bound means nothing is being wasted and the only gain left is a higher " +
    "ceiling, which is another extractor.</p>" +
    "<p><b>Two lenses, deliberately not merged.</b> The regime lens asks which resource is short and names its " +
    "fix. The absorption lens asks which target consumes the surplus you actually have. They disagree when the " +
    "biggest absorber is not the strategically best buy, and that disagreement is information, not a bug. " +
    "The projection panel is the tiebreak: it charges both forward and counts what gets finished.</p>" +
    "<p class=spark>Model: bar-calc/bar_unified.py &mdash; regime_of, recommend, absorb_profile, target_advisor, " +
    "_project_row, effective_bproi. Numbers resolve from econ_model.json plus the newest engine unit dump. " +
    "The badge top right confirms this page reproduces Python cell for cell.</p>";
}

/* ============ wiring ============ */
function render(){
  fitPlane();
  drawTiles(); drawRibbon(); drawTable(); drawSpectrum();
  drawCadence(); drawPath(); drawBudget(); drawNotes();
  document.getElementById("frame").value = fi;
}
function stop(){ playing = false; clearInterval(timer); document.getElementById("play").textContent = "Play";
  document.getElementById("play").classList.remove("on"); }
function start(){
  playing = true;
  document.getElementById("play").textContent = "Pause";
  document.getElementById("play").classList.add("on");
  clearInterval(timer);
  timer = setInterval(() => {
    fi = (fi + 1) % P.frames.length;
    render();
  }, +document.getElementById("speed").value);
}
function fillSelects(){
  const names = Object.keys(OBJ);
  const set = (id, val, filter) => {
    const el = document.getElementById(id);
    el.innerHTML = names.filter(filter || (() => true))
      .map(n => '<option' + (n === val ? " selected" : "") + ">" + n + "</option>").join("");
    el.onchange = () => {
      CFG[id === "target" ? "target" : id === "bpsrc" ? "bpSource" : id === "esrc" ? "energySource" : "on"] = el.value;
      render();
    };
  };
  set("target", CFG.target);
  set("bpsrc", CFG.bpSource, n => OBJ[n].bpInc > 0);
  set("esrc", CFG.energySource, n => OBJ[n].wind || OBJ[n].eInc > 0);
  set("on", CFG.on);
  const ps = document.getElementById("planeSel");
  ps.innerHTML = CFG.depth.map((w, k) => '<option value="' + k + '">' + fmt(w, 1) + " E/s</option>").join("");
  ps.onchange = () => { planeIdx = +ps.value; };
}
function initSandbox(){
  const f = P.frames[fi];
  sand = {t:f.t, metal:f.metal, energy:f.energy, mInc:f.mInc, eInc:f.eInc, bp:f.bp,
          mCap:Math.max(1000, f.mCap), eCap:Math.max(1000, f.eCap), wind:f.wind, counts:{}};
  const bind = (id, key, max) => {
    const el = document.getElementById(id);
    if(max) el.max = max;
    el.value = sand[key];
    el.oninput = () => { sand[key] = +el.value;
      if(key === "metal") sand.mCap = Math.max(sand.mCap, sand.metal);
      if(key === "energy") sand.eCap = Math.max(sand.eCap, sand.energy);
      render(); };
  };
  bind("sMinc", "mInc"); bind("sEinc", "eInc"); bind("sBp", "bp");
  bind("sMbank", "metal", Math.max(4000, sand.mCap));
  bind("sEbank", "energy", Math.max(20000, sand.eCap));
  bind("sWind", "wind");
}
document.getElementById("mode").onclick = ev => {
  const b = ev.target.closest("button"); if(!b) return;
  mode = b.dataset.mode;
  document.querySelectorAll("#mode button").forEach(x => x.classList.toggle("on", x === b));
  document.getElementById("replayCtl").style.display = mode === "replay" ? "" : "none";
  document.getElementById("sandCtl").style.display = mode === "sandbox" ? "" : "none";
  if(mode === "sandbox"){ stop(); initSandbox(); }
  render();
};
document.getElementById("lens").onclick = ev => {
  const b = ev.target.closest("button"); if(!b) return;
  lens = b.dataset.lens;
  document.querySelectorAll("#lens button").forEach(x => x.classList.toggle("on", x === b));
  drawTable();
};
document.getElementById("play").onclick = () => playing ? stop() : start();
document.getElementById("speed").onchange = () => { if(playing) start(); };
const fr = document.getElementById("frame");
fr.max = P.frames.length - 1;
fr.value = fi;
fr.oninput = () => { stop(); fi = +fr.value; render(); };
document.getElementById("spin").onclick = ev => {
  spin = !spin; ev.target.classList.toggle("on", spin);
};
document.getElementById("reset").onclick = () => { rotY = -0.62; rotX = 0.42; };
addEventListener("resize", drawCube);

drawHead();
fillSelects();
paintParity();
render();
requestAnimationFrame(loop);
</script>
</body>
</html>
"""

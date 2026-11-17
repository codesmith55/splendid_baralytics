/**
 * milestone_engine.mjs — evaluate ordered milestone triggers against a BAR actions.json.
 *
 * Exported API:
 *   parseTrigger(phrase, opts)          → TriggerSpec
 *   parseTriggers(phrases, snapshots?)  → TriggerSpec[]
 *   runMilestones(actionsPath, teamId, triggers, windowS?) → Promise<MilestoneResult>
 *
 * Trigger types:
 *   count   — unit_created count for a unit class crosses a threshold
 *   each    — fires once per qualifying unit_created (multi-event)
 *   first   — fires on the first qualifying unit_created
 *   metric  — extra_stat_update field crosses a threshold
 *   event   — discrete game event (e.g. com_died)
 *
 * Unit classes:
 *   mex      any metal extractor (T1, medmex, moho)
 *   mex_t1   T1 mex only  (metalCost < 120)
 *   medmex   medium/T1.5 mex  (120 ≤ metalCost < 600)
 *   mex_t2   T2 moho  (metalCost ≥ 600, isMetalExtractor)
 *   t1factory  T1 bot/vehicle lab
 *   t2factory  T2 lab / advanced factory
 *   commander
 *
 * Sequence-skip detection:
 *   After all events are collected, adjacent trigger pairs are compared.
 *   If trigger[i+1] fired BEFORE trigger[i], a SequenceSkip warning is added.
 *   Additionally: when trigger[i] fires, we check if trigger[i+1] is ALREADY satisfied
 *   at that exact frame — "same-frame skip" is flagged separately.
 *
 * Snapshot state (attached to events where trigger.snapshot === true):
 *   { frame, game_s, metalCurrent, energyCurrent, metalIncome, totalValue, tpv,
 *     unitCounts, recentEcoUpdate }
 *
 * NOTE: unit_created fires when CONSTRUCTION STARTS, not when it completes.
 *   Mex build time ≈ 23–25s (T1), 62s (medmex), 75s (moho).
 *   Subtract build time from recorded timings to get income-start timing.
 */

import fs from "node:fs";
import readline from "node:readline";

// ── Unit classification ───────────────────────────────────────────────────────

/**
 * Classify a unit_def into a canonical class string.
 * Uses metalCost ranges and defName patterns.
 */
export function classifyDef(def) {
  if (!def) return null;
  if (def.isCommander) return "commander";
  if (def.isMetalExtractor) {
    const mc = def.metalCost ?? 0;
    if (mc >= 600) return "mex_t2";           // moho, advanced extractor
    if (mc >= 120) return "medmex";            // Legion legmext15, ARM caisson, etc.
    return "mex_t1";
  }
  if (def.isFactory) {
    // T2 factories are expensive (ARM t2lab ~720m, Legion leg_t2lab similar)
    return (def.metalCost ?? 0) >= 1500 ? "t2factory" : "t1factory";
  }
  return "unit";
}

/** Does the unit class satisfy the trigger's unitClass filter? */
function unitClassMatches(filter, defClass) {
  if (filter === "mex")    return ["mex_t1", "medmex", "mex_t2"].includes(defClass);
  if (filter === "any")    return true;
  return defClass === filter;
}

// ── Natural language trigger parser ──────────────────────────────────────────

const NUM_RE  = /\b(\d[\d,]*)\b/;

/**
 * Parse a single natural-language phrase into a TriggerSpec.
 *
 * Examples:
 *   "5 mex"            → count/mex/5
 *   "each medmex"      → each/medmex
 *   "T2 factory built" → first/t2factory
 *   "first T2 mex"     → first/mex_t2
 *   "TPV 6000"         → metric/tpv/6000
 *   "metal income 20"  → metric/metalIncome/20
 */
export function parseTrigger(phrase, { id = 0, snapshot = false } = {}) {
  const p   = phrase.toLowerCase().trim();
  const nm  = p.match(NUM_RE);
  const n   = nm ? parseInt(nm[1].replace(/,/g, ""), 10) : null;
  const isE = /\beach\b/.test(p);  // "each X" → multi-fire trigger

  // ── metric triggers ──────────────────────────────────────────────────────
  if (/tpv|total.player.value|player.value/.test(p) && n != null) {
    return _spec(id, phrase, `TPV ≥ ${n}`, "metric", { metric: "tpv", threshold: n, snapshot });
  }
  if (/metal.income|m\/s/.test(p) && n != null) {
    return _spec(id, phrase, `metal income ≥ ${n} m/s`, "metric", { metric: "metalIncome", threshold: n, snapshot });
  }
  if (/energy.income|e\/s/.test(p) && n != null) {
    return _spec(id, phrase, `energy income ≥ ${n} e/s`, "metric", { metric: "energyIncome", threshold: n, snapshot });
  }
  if (/metal.current|current.metal/.test(p) && n != null) {
    return _spec(id, phrase, `metal ≥ ${n}`, "metric", { metric: "metalCurrent", threshold: n, snapshot });
  }

  // ── event triggers ───────────────────────────────────────────────────────
  if (/commander.*died|com.*died|com.*lost|commander.*lost/.test(p)) {
    return _spec(id, phrase, "commander died", "event", { event: "com_died", snapshot });
  }

  // ── unit triggers — T2 mex / moho ────────────────────────────────────────
  if (/t2.mex|moho|t2.extractor|advanced.mex|advanced.extractor/.test(p)) {
    const cnt = n ?? 1;
    const type = isE ? "each" : (cnt === 1 && !nm ? "first" : "count");
    const lbl  = isE ? "each T2 mex started" : cnt === 1 ? "first T2 mex started" : `${cnt}th T2 mex started`;
    return _spec(id, phrase, lbl, type, { unitClass: "mex_t2", threshold: cnt, snapshot });
  }

  // ── unit triggers — T2 factory / lab ─────────────────────────────────────
  if (/t2.factor|t2.lab|t2.plant|advanced.*lab|adv.*lab|advanced.*factory/.test(p)) {
    const cnt = n ?? 1;
    const type = isE ? "each" : (cnt === 1 ? "first" : "count");
    const lbl  = isE ? "each T2 factory started" : cnt === 1 ? "first T2 factory started" : `${cnt} T2 factories started`;
    return _spec(id, phrase, lbl, type, { unitClass: "t2factory", threshold: cnt, snapshot });
  }

  // ── unit triggers — medmex ───────────────────────────────────────────────
  if (/medmex|med.mex|medium.mex|t1\.5|t15.mex|mext15|intermediate.mex/.test(p)) {
    const cnt = n ?? 1;
    if (isE) {
      return _spec(id, phrase, "each medmex started", "each", { unitClass: "medmex", threshold: 1, snapshot });
    }
    const type = cnt === 1 ? "first" : "count";
    const lbl  = cnt === 1 ? "first medmex started" : `${cnt} medmexes started`;
    return _spec(id, phrase, lbl, type, { unitClass: "medmex", threshold: cnt, snapshot });
  }

  // ── unit triggers — T1 factory ───────────────────────────────────────────
  if (/(?:t1.)?(?:factory|lab\b|bot.lab|vehicle.lab|plant)/.test(p) && !/t2/.test(p)) {
    const cnt = n ?? 1;
    const type = isE ? "each" : (cnt === 1 ? "first" : "count");
    const lbl  = isE ? "each T1 factory started" : cnt === 1 ? "first T1 factory started" : `${cnt} T1 factories started`;
    return _spec(id, phrase, lbl, type, { unitClass: "t1factory", threshold: cnt, snapshot });
  }

  // ── unit triggers — generic mex (any tier) ───────────────────────────────
  if (/\bmex(?:es)?\b/.test(p)) {
    const cnt = n ?? 1;
    if (isE) {
      return _spec(id, phrase, "each mex started", "each", { unitClass: "mex", threshold: 1, snapshot });
    }
    const type = cnt === 1 ? "first" : "count";
    const lbl  = cnt === 1 ? "first mex started" : `${cnt} mexes started`;
    return _spec(id, phrase, lbl, type, { unitClass: "mex", threshold: cnt, snapshot });
  }

  // fallback — unknown phrase, stored for forward-compat
  return _spec(id, phrase, phrase, "unknown", { snapshot });
}

function _spec(id, phrase, label, type, opts = {}) {
  return {
    id,
    phrase,
    label,
    type,                          // 'count' | 'each' | 'first' | 'metric' | 'event' | 'unknown'
    unitClass: opts.unitClass ?? null,
    threshold: opts.threshold ?? 1,
    metric:    opts.metric    ?? null,
    event:     opts.event     ?? null,
    snapshot:  opts.snapshot  ?? false,
  };
}

/**
 * Parse an array of phrases into TriggerSpecs.
 * @param {string[]} phrases   Ordered trigger phrases (index = sequence position)
 * @param {string[]} snapshots Phrases (or indices) of triggers that should snapshot
 */
export function parseTriggers(phrases, snapshots = []) {
  const snapSet = new Set(snapshots.map(s => String(s).toLowerCase().trim()));
  return phrases.map((ph, i) => {
    const snap = snapSet.has(String(i)) || snapSet.has(ph.toLowerCase().trim()) ||
                 [...snapSet].some(s => ph.toLowerCase().includes(s));
    return parseTrigger(ph, { id: i, snapshot: snap });
  });
}

// ── Core evaluation ───────────────────────────────────────────────────────────

/**
 * Run milestone triggers against an actions.json file.
 *
 * @param {string}        actionsPath  Path to actions.json (NDJSON)
 * @param {number}        teamId       Which team to analyse
 * @param {TriggerSpec[]} triggers     Ordered list from parseTriggers()
 * @param {number}        windowS      Analysis window in seconds (default 900 = 15 min)
 * @returns {Promise<MilestoneResult>}
 */
export async function runMilestones(actionsPath, teamId, triggers, windowS = 900) {
  const MAX_FRAME = windowS * 30;

  // per-defID class catalog built from unit_def events
  const defClasses = new Map();  // defID → class string

  // per-trigger state
  const trigState = triggers.map(() => ({ count: 0, firedAt: null, instances: [] }));

  // latest economy snapshot for the target team
  let latestEco = null;
  // per-trigger snapshot (captured at first fire)
  const snapshots = new Map();  // triggerId → snapshot

  // running unit counts for snapshot payloads
  const unitCounts = {};  // class → count

  const events = [];  // MilestoneEvent[]

  const stream = fs.createReadStream(actionsPath, { encoding: "utf8" });
  const rl     = readline.createInterface({ input: stream, crlfDelay: Infinity });

  for await (const line of rl) {
    if (!line.trim()) continue;
    let ev;
    try { ev = JSON.parse(line); } catch (_) { continue; }

    const action = ev.action;

    // ── unit_def: build classification catalog ──────────────────────────────
    if (action === "unit_def") {
      defClasses.set(ev.defID, classifyDef(ev));
      continue;
    }

    const evFrame = ev.frame ?? 0;
    if (evFrame > MAX_FRAME) break;

    const game_s = evFrame / 30;

    // ── extra_stat_update: track economy for metric triggers + snapshots ────
    if (action === "extra_stat_update" && ev.teamID === teamId) {
      const eco = {
        frame:        evFrame,
        game_s,
        metalCurrent: ev.metalCurrent  ?? 0,
        energyCurrent:ev.energyCurrent ?? 0,
        metalIncome:  ev.metalIncome   ?? 0,
        energyIncome: ev.energyIncome  ?? 0,
        totalValue:   ev.totalValue    ?? 0,
        tpv: (ev.totalValue ?? 0) + (ev.metalCurrent ?? 0) + (ev.energyCurrent ?? 0) / 70,
      };
      latestEco = eco;

      // check metric triggers
      for (let i = 0; i < triggers.length; i++) {
        const t = triggers[i];
        if (t.type !== "metric") continue;
        const val = eco[t.metric] ?? eco.tpv;
        if (val >= t.threshold && trigState[i].firedAt === null) {
          trigState[i].firedAt = game_s;
          const snap = t.snapshot ? _buildSnapshot(eco, unitCounts, evFrame) : null;
          if (snap) snapshots.set(i, snap);
          events.push(_event(i, t.label, evFrame, game_s, val, 1, snap));
          _checkSameFrameSkip(i, triggers, trigState, events, game_s, evFrame);
        }
      }
      continue;
    }

    // ── unit_created: track unit counts for count/each/first triggers ───────
    if (action === "unit_created" && ev.teamID === teamId) {
      const defClass = defClasses.get(ev.defID) ?? "unit";
      unitCounts[defClass] = (unitCounts[defClass] ?? 0) + 1;

      for (let i = 0; i < triggers.length; i++) {
        const t = triggers[i];
        if (!["count", "each", "first"].includes(t.type)) continue;
        if (!unitClassMatches(t.unitClass, defClass)) continue;

        const st = trigState[i];
        st.count++;

        if (t.type === "each") {
          // fires on every matching unit
          const snap = t.snapshot && st.instances.length === 0
            ? _buildSnapshot(latestEco, unitCounts, evFrame) : null;
          if (snap) snapshots.set(i, snap);
          const instanceN = st.instances.length + 1;
          st.instances.push(game_s);
          if (st.firedAt === null) st.firedAt = game_s;
          events.push(_event(i, `${t.label} #${instanceN}`, evFrame, game_s, st.count, instanceN, snap));
          if (instanceN === 1) _checkSameFrameSkip(i, triggers, trigState, events, game_s, evFrame);

        } else if (t.type === "count" && st.count >= t.threshold && st.firedAt === null) {
          st.firedAt = game_s;
          const snap = t.snapshot ? _buildSnapshot(latestEco, unitCounts, evFrame) : null;
          if (snap) snapshots.set(i, snap);
          events.push(_event(i, t.label, evFrame, game_s, st.count, 1, snap));
          _checkSameFrameSkip(i, triggers, trigState, events, game_s, evFrame);

        } else if (t.type === "first" && st.count >= t.threshold && st.firedAt === null) {
          st.firedAt = game_s;
          const snap = t.snapshot ? _buildSnapshot(latestEco, unitCounts, evFrame) : null;
          if (snap) snapshots.set(i, snap);
          events.push(_event(i, t.label, evFrame, game_s, st.count, 1, snap));
          _checkSameFrameSkip(i, triggers, trigState, events, game_s, evFrame);
        }
      }
      continue;
    }

    // ── unit_destroyed: commander death ──────────────────────────────────────
    if (action === "unit_killed" && ev.teamID === teamId) {
      const defClass = defClasses.get(ev.defID) ?? "unit";
      if (defClass === "commander") {
        for (let i = 0; i < triggers.length; i++) {
          const t = triggers[i];
          if (t.type === "event" && t.event === "com_died" && trigState[i].firedAt === null) {
            trigState[i].firedAt = game_s;
            const snap = t.snapshot ? _buildSnapshot(latestEco, unitCounts, evFrame) : null;
            if (snap) snapshots.set(i, snap);
            events.push(_event(i, t.label, evFrame, game_s, 1, 1, snap));
            _checkSameFrameSkip(i, triggers, trigState, events, game_s, evFrame);
          }
        }
      }
    }
  }

  rl.close();
  stream.destroy();

  // ── sequence-skip detection (post-processing) ────────────────────────────
  const skips = [];
  for (let i = 0; i < triggers.length - 1; i++) {
    const currFire = trigState[i].firedAt;
    const nextFire = trigState[i + 1].firedAt;
    if (currFire !== null && nextFire !== null && nextFire < currFire) {
      skips.push({
        type: "out_of_order",
        atGame_s: currFire,
        priorTriggerId: i,
        priorLabel: triggers[i].label,
        skipTriggerId: i + 1,
        skipLabel: triggers[i + 1].label,
        message: `"${triggers[i + 1].label}" fired at ${nextFire.toFixed(1)}s ` +
                 `BEFORE "${triggers[i].label}" at ${currFire.toFixed(1)}s — ` +
                 `sequence out of order (build was ahead of plan, or plan mis-ordered)`,
      });
    }
  }

  const unmatched = triggers
    .filter((t, i) => t.type !== "unknown" && trigState[i].firedAt === null)
    .map(t => t.id);

  return { triggers, events, skips, unmatched, window_s: windowS, teamId };
}

// ── helpers ───────────────────────────────────────────────────────────────────

function _event(triggerId, label, frame, game_s, value, instanceN, snapshot) {
  return { triggerId, label, frame, game_s, value, instanceN, snapshot: snapshot ?? null };
}

function _buildSnapshot(eco, unitCounts, frame) {
  if (!eco) return { frame, note: "no eco data before this event" };
  return {
    frame,
    game_s:        eco.game_s,
    metalCurrent:  eco.metalCurrent,
    energyCurrent: eco.energyCurrent,
    metalIncome:   eco.metalIncome,
    energyIncome:  eco.energyIncome,
    totalValue:    eco.totalValue,
    tpv:           eco.tpv,
    unitCounts:    { ...unitCounts },
  };
}

/**
 * When trigger[i] fires, check if trigger[i+1] was ALREADY satisfied at this frame.
 * This catches "same-frame" skips (previous trigger and next trigger fire simultaneously
 * or previous trigger fires after the next one).
 * The "out_of_order" post-processing check catches the inter-frame case.
 */
function _checkSameFrameSkip(i, triggers, trigState, events, game_s, frame) {
  if (i + 1 >= triggers.length) return;
  const nextFire = trigState[i + 1].firedAt;
  if (nextFire !== null && nextFire <= game_s) {
    // add a sequence_skip warning to the last event
    const lastEv = events[events.length - 1];
    if (lastEv && !lastEv.sequenceSkip) {
      lastEv.sequenceSkip = {
        type: "already_done",
        skipTriggerId: i + 1,
        skipLabel: triggers[i + 1].label,
        skipFiredAt: nextFire,
        message: `"${triggers[i + 1].label}" was already done (${nextFire.toFixed(1)}s) ` +
                 `when this trigger fired — next step may be redundant or mis-sequenced`,
      };
    }
  }
}

// ── Pretty-print helper ───────────────────────────────────────────────────────

export function formatResults(result, { verbose = false } = {}) {
  const lines = [];
  const w = 72;
  const hr = "─".repeat(w);

  lines.push(hr);
  lines.push("  MILESTONE RESULTS");
  if (result.game) lines.push(`  Game: ${result.game.file ?? ""} | team ${result.teamId}`);
  lines.push(hr);

  // Group events by triggerId
  const byTrigger = {};
  for (const ev of result.events) {
    (byTrigger[ev.triggerId] ??= []).push(ev);
  }

  for (const t of result.triggers) {
    const evs = byTrigger[t.id] ?? [];
    if (t.type === "unknown") {
      lines.push(`  [${String(t.id + 1).padStart(2)}] ${t.label.padEnd(35)} ⚠ unrecognised phrase`);
      continue;
    }
    if (evs.length === 0) {
      lines.push(`  [${String(t.id + 1).padStart(2)}] ${t.label.padEnd(35)} (not reached in ${result.window_s}s)`);
      continue;
    }
    for (const ev of evs) {
      const ts  = _fmt(ev.game_s);
      const val = t.type === "metric" ? `${ev.value.toFixed(1)}` : `×${ev.value}`;
      const skip = ev.sequenceSkip ? `  ⚠ SKIP: ${ev.sequenceSkip.message}` : "";
      lines.push(`  [${String(t.id + 1).padStart(2)}] ${ts}  ${ev.label.padEnd(33)} ${val}${skip}`);
      if (verbose && ev.snapshot) {
        const s = ev.snapshot;
        lines.push(`         eco: TPV=${s.tpv?.toFixed(0)} m=${s.metalCurrent?.toFixed(0)} e=${s.energyCurrent?.toFixed(0)} inc=${s.metalIncome?.toFixed(2)}m/s`);
      }
    }
  }

  if (result.skips.length > 0) {
    lines.push(hr);
    lines.push("  SEQUENCE WARNINGS:");
    for (const sk of result.skips) lines.push(`  ⚠ ${sk.message}`);
  }

  if (result.unmatched.length > 0) {
    lines.push(hr);
    lines.push(`  DID NOT FIRE: ${result.unmatched.map(i => `"${result.triggers[i].label}"`).join(", ")}`);
  }

  lines.push(hr);
  lines.push("  NOTE: timings are unit_created (construction start), not completion.");
  lines.push(`  Approx build times: T1 mex ~23s, medmex ~62s, T2 mex ~75s, T2 lab ~80s.`);
  lines.push(hr);
  return lines.join("\n");
}

function _fmt(s) {
  const m   = Math.floor(s / 60);
  const sec = (s % 60).toFixed(1).padStart(4, "0");
  return `${m}:${sec}`;
}

/**
 * live-reader.mjs — barbots Layer 1 reader
 *
 * Polls bar_analytic_server's /api/state and emits typed events for the adapter layer.
 * Requires Node.js 18+ (native fetch).
 *
 * Events emitted:
 *   'econ'         (teamID, allyTeamID, gameSeconds, ...econFields)  — every poll tick
 *   'builderIdle'  (builder, teamID, allyTeamID, gameSeconds)        — transition to idle
 *   'builderBusy'  (builder, teamID, allyTeamID, gameSeconds)        — transition to busy
 *   'gameReset'    (state)                                           — frame counter rolled back
 *   'gameEnd'      (state)                                           — game over event
 *   'error'        (err)                                             — fetch / parse failure
 *
 * Usage:
 *   import { LiveReader } from '../reader/live-reader.mjs';
 *   const reader = new LiveReader();
 *   reader.on('builderIdle', b => console.log('idle builder', b.unitID, 'at', b.x, b.z));
 *   reader.on('econ', ({ teamID, metalIncome }) => { ... });
 *   reader.start();
 */

import { EventEmitter } from 'events';

const DEFAULTS = { serverUrl: 'http://localhost:8787', pollMs: 500 };

export class LiveReader extends EventEmitter {
    constructor(opts = {}) {
        super();
        const { serverUrl, pollMs } = { ...DEFAULTS, ...opts };
        this._url = serverUrl.replace(/\/$/, '') + '/api/state';
        this._pollMs = pollMs;
        this._prevBuilders = {};   // uid -> {idle, building}
        this._prevFrame = -1;
        this._wasOver = false;
        this._running = false;
        this._timer = null;
    }

    start() {
        if (this._running) return;
        this._running = true;
        this._schedule();
    }

    stop() {
        this._running = false;
        if (this._timer) { clearTimeout(this._timer); this._timer = null; }
    }

    _schedule() {
        this._timer = setTimeout(() => this._tick(), this._pollMs);
    }

    async _tick() {
        try {
            const res = await fetch(this._url);
            if (res.ok) this._ingest(await res.json());
        } catch (err) {
            this.emit('error', err);
        }
        if (this._running) this._schedule();
    }

    _ingest(state) {
        const { frame, gameSeconds, teams = [], over } = state;

        // New game: frame counter rolled back
        if (frame < this._prevFrame) {
            this._prevBuilders = {};
            this._wasOver = false;
            this.emit('gameReset', state);
        }
        this._prevFrame = frame;

        if (over && !this._wasOver) {
            this._wasOver = true;
            this.emit('gameEnd', state);
        }

        for (const team of teams) {
            const { teamID, allyTeamID } = team;

            this.emit('econ', { teamID, allyTeamID, gameSeconds, ...econFields(team) });

            for (const builder of (team.builders || [])) {
                const uid = builder.unitID;
                const prev = this._prevBuilders[uid];
                if (!prev || prev.idle !== builder.idle) {
                    const ev = { ...builder, teamID, allyTeamID, gameSeconds };
                    this.emit(builder.idle ? 'builderIdle' : 'builderBusy', ev);
                }
                this._prevBuilders[uid] = { idle: builder.idle, building: builder.building };
            }
        }
    }

    /** Synchronous snapshot of the current state from the server (one-shot, no polling). */
    static async fetchState(serverUrl = DEFAULTS.serverUrl) {
        const res = await fetch(serverUrl.replace(/\/$/, '') + '/api/state');
        if (!res.ok) throw new Error(`/api/state returned ${res.status}`);
        return res.json();
    }
}

function econFields(t) {
    return {
        metalIncome:      t.metalIncome,
        energyIncome:     t.energyIncome,
        metalCurrent:     t.metalCurrent,
        metalStorage:     t.metalStorage,
        energyCurrent:    t.energyCurrent,
        energyStorage:    t.energyStorage,
        bpAvail:          t.bpAvail,
        bpUsed:           t.bpUsed,
        bpIdlePct:        t.bpAvail > 0 ? Math.round((1 - t.bpUsed / t.bpAvail) * 100) : 0,
        nMex:             t.nMex,
        nConv:            t.nConv,
        totalValue:       t.total,
        buckets:          t.buckets,
        builders:         t.builders || [],
        idleBuilderCount: t.idleBuilderCount || 0,
    };
}

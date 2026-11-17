// analysisDb.mjs — a tiny version-aware store of analyzed games/players.
//
// Each game record carries the `taxonomyVersion` it was analyzed with. When the taxonomy
// (metrics/unit_taxonomy.json) improves and its `version` bumps, `needsAnalysis()` flags stale
// games so a re-run can overwrite them. Plain JSON on disk (analysis_db.json); no deps.
//
// Record shape:
//   db = { schema, taxonomyVersion, updated, games: { [gameID]: GameRecord } }
//   GameRecord = { gameID, map, startedAt, durationSec, taxonomyVersion, analyzedAt,
//                  players: [ { name, side, allyTeamID,
//                              military: { byClassTech: {"main|1": value, ...}, total },
//                              ... } ] }
import fs from "node:fs";

export function loadDb(path) {
  try { return JSON.parse(fs.readFileSync(path, "utf8")); }
  catch { return { schema: 1, taxonomyVersion: null, updated: null, games: {} }; }
}

export function saveDb(path, db) {
  fs.writeFileSync(path, JSON.stringify(db, null, 2));
}

/** True if the game is missing or was analyzed with an older taxonomy than `taxVersion`. */
export function needsAnalysis(db, gameID, taxVersion) {
  const g = db.games[gameID];
  return !g || (g.taxonomyVersion || 0) < taxVersion;
}

/**
 * Insert/update a game record. Skips if the stored version is already >= taxVersion (unless force).
 * Returns true if it wrote, false if it left an up-to-date record untouched.
 * `stamp` is the analyzedAt timestamp (passed in — keeps this pure/testable).
 */
export function upsertGame(db, game, taxVersion, { force = false, stamp = null } = {}) {
  const ex = db.games[game.gameID];
  if (ex && !force && (ex.taxonomyVersion || 0) >= taxVersion) return false;
  db.games[game.gameID] = { ...game, taxonomyVersion: taxVersion, analyzedAt: stamp };
  db.taxonomyVersion = Math.max(db.taxonomyVersion || 0, taxVersion);
  db.updated = stamp;
  return true;
}

/** List gameIDs whose stored analysis is older than the current taxonomy. */
export function staleGames(db, taxVersion) {
  return Object.keys(db.games).filter(id => (db.games[id].taxonomyVersion || 0) < taxVersion);
}

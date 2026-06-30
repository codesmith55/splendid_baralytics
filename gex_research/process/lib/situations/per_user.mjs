// per_user.mjs — pass-through situation, presented per USER.
// In the engine a "team" is a single army; here we define it as the User controlling that team.
// One series per user; `teamID` is retained as the id of the team that user controls.
//
// Also re-exports splitAt from snapFormat.mjs so callers can do:
//   import { apply, splitAt } from "./per_user.mjs";
//   splitAt(user, 600)               → "Name @ 600s:  BP:7.0%  Eco:34.1%  ..."
//   splitAt(user, "peak", "breakout")→ full per-bucket breakdown
export { splitAt } from "../snapFormat.mjs";

export const meta = { id: "per_user", title: "Per-user (each user and the team they control)" };

export function apply(metricResult, ctx, params = {}) {
  const users = metricResult.teams.map(tm => {
    const r = ctx.roster.get(tm) || {};
    return {
      userId: r.userId ?? null,
      user: label(ctx, tm),
      teamID: tm,                 // the team this user controls (engine term)
      allyTeam: ctx.allyOf.get(tm) ?? null,
      faction: r.faction ?? null,
      startPos: ctx.startPos.get(tm) ?? null,
      final: metricResult.final[tm],
      peak: metricResult.peak?.[tm] ?? metricResult.final[tm],
      series: metricResult.series[tm],
    };
  });
  return { situationId: "per_user", users };
}

/** A user's display label: their name (+ persistent userId), falling back to the team they control. */
export function label(ctx, tm) {
  const r = ctx.roster.get(tm);
  if (r?.name) return `${r.name}${r.userId != null ? ` (user ${r.userId})` : ""}${r.faction ? " · " + r.faction : ""}`;
  return `User of team ${tm}`;
}

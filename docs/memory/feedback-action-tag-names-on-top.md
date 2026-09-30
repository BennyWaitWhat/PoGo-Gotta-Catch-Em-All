---
name: feedback-action-tag-names-on-top
description: Tag names must say the ACTION and sit first (2026-09-26); evolve tags ride along through evolution, so a mid-stage target gets "Stop at <Stage>" instead of any Evolve tag.
metadata:
  type: feedback
---

User 2026-09-26: "THEN WHY IS IT TAGGED FOR EVO? EVER WONDERED WHY I KEPT MAKING THAT MISTAKE?" (a Tympole tagged
Evolve Next + Evo Best GL whose target was Palpitoad -- he evolved on to Seismitoad twice), then picked option 1, then:
"Be clear with what I need to do simply in the tag names." and "And always put them on top."

**Why:** tags INHERIT through evolution ([[reference-pogo-tag-inheritance]]); the "then STOP" lived only in my chat report,
never in the game. A tag must be true for the mon on screen ([[feedback-labels-true-for-the-mon-on-screen]]) -- before AND
after he acts on it.

**How to apply:**
- A copy whose one promised stage can evolve again gets `Stop at <Stage>` INSTEAD of every evolve tag (granular_tags
  STOP_REPLACES + Evolve for Size); dynamic names live in system/analysis/stop_tags.json, empties are pushed empty and
  retired. `Stop <Stage>` when over 18 chars; no ':' (filenames).
- Action tags: `Power Up to 1500` / `Power Up to 2500` and `Unlock 2nd Move` -- since 2026-09-29 04:0x rank 1-2 own stage (pvp.action_rank 2; "i also just want to powerup and unlock 2nd moves for top2 rank pokemon"; rank 1-5 before) + pvpoke
  top-200 meta (see the dust-advice note below). Dust advice, not keep reasons.
- Any NEW tag: an imperative name he can act on without my report, <= 18 characters (longest ever accepted), and it goes
  at the TOP of order_tags.ORDER.
- **Grouped (same day, later):** "you could stop the excessive tagging and just group em by saying 'stop at middle stage'
  unless its something else" -> granular_tags.stop_tag_name returns ONE `Stop at Mid Stage` for every middle-stage target
  (a pvpoke evolution target that evolves again); only a non-middle stop keeps `Stop at <Stage>`. Don't mint per-species
  tags when one generic action tag says it; the report names the stage.

**2026-09-29 -- THE FOLD** ("fix the redundant tags? I either evolve once or evolve twice" + "I also like to see the separate PVP ones"): the evolve vocabulary is `Evolve Once` / `Evolve Twice` (count = where to stop) / `Evolve Gated`, plus `Evo Best GL` / `Evo Best UL` beside them on a PvP comb-up. ONE table: `granular_tags.evolve_advice` -> system/analysis/evolve_advice.json (promise > combup > shiny > size; steps via `steps_between`). Retired: Evolve Next, every Stop tag, Evo Best Gated, Evolve Shiny(+Gated), Evolve for Size (no separate push any more). The ride-along trap is accepted: after the first evolution the copy still says Evolve Once until the next cull -- the name itself says stop.

**2026-09-29 dust advice rules** ("I only want Rank 1-5 PVP pokemon to have their 2nd moves unlocked" / "only want to power pokemon who are ranked in the top 100 of pvpoke"): keep_config pvp.action_rank 5, power_up_meta_top 100 (pvpoke rankings-1500/2500.json by score; granular_tags.meta_top/meta_ok, shadow '_shadow' fallback), unlock_meta_top ("Do 1, meta gate on 2nd move too"), then BOTH 200 ("Can you make it pvpoke rank top 200?"). Power Up = ONE per (league, stage), none if a copy is already at its best level. Result at 200/200: Power Up 1500 2 / 2500 12, Unlock 2nd Move 21 (102 with no meta gate, 7 at 100). refresh_gamemaster refreshes the rankings monthly.

**2026-09-30 -- THE SECOND FOLD** ("So you want me to evolve all the pokemon tagged "Evo UL rank 1-5?"? Even if I have dups?" -> "And you're just finding this now but your swarm of agents didnt find or think of this? cmon. fix it."): a KEEP label read as an ACTION. `Evo GL/UL Rank 1-5` retired; THE copy to evolve wears `Evolve for GL` / `Evolve for UL` (renamed from `Evo Best GL/UL`), every other later-stage top 5 wears `GL/UL 1-5 No Evolve`. **How to apply:** before shipping or keeping any tag, ask "what will he DO when he sees this name?" -- if the name contains an action word (Evolve, Power Up, Unlock, Transfer), every member must be a copy he should act on NOW; otherwise rename it. audit_invariants I8.2 now fails any managed name with "Evo" that is not an evolve tag.

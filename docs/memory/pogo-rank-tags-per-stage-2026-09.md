---
name: pogo-rank-tags-per-stage-2026-09
description: "GL/UL Rank tags are the mon's OWN-stage rank (what Pokemod prints for the mon on screen); Evo GL/UL Rank 1 / 2-5 = a later stage reaches it; gl_rank column is chain-best-viable and must never be labelled as the mon's rank"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9f2eff52-4f4a-4130-a61e-420ac1dd82ff
  modified: 2026-09-09T02:57:52.192Z
---

**Decision (2026-09-08, user: "Why is Raboot tagged as GL rank 1 if... it isnt?").** A 0/15/15 Raboot had
`gl_rank=1` because the column is the chain's best VIABLE stage (Cinderace #1); Raboot's own stage is #7 and
the Pokemod overlay shows #7. Tags now split by stage (`Best GL` / `Best UL` retired 2026-09-09):
- `GL Rank 1` / `GL Rank 2-5` (and UL) = the mon's OWN-stage stat-product rank at the L50 ceiling.
- `Evo GL Rank 1` / `Evo GL Rank 2-5` (and UL) = the best rank a LATER stage of its line reaches.
Source: `granular_tags.own_and_evo_rank(row, 'gl'|'ul')` parses `<league>_chain_ranks`
('raboot:7(99.82%);cinderace:1(100.00%)'; own stage first, later stages after); own sid = `pvid(species, form)`.

**Gating:** an under-cap species pins every IV to L50, so its hundo ranks #1 at its own stage. Since 2026-09-09
Rank / Evo Rank tags are viability-gated (the stage's L50-hundo CP must exceed cap + viability_margin); since
2026-09-19 also cap-gated, because CP only goes up (below). Under-cap stages get no Rank tag (GL Rank 1 = 30,
UL Rank 1 = 23 on 2026-09-20).

**How to apply:** never label a mon with `gl_rank`/`ul_rank` as if it were the mon's own rank; say which
stage a number belongs to. Keep decisions were unchanged by this (labels only).
Related: [[reference-pokemod-overlay-rank-mechanics]], [[project-pokemod-labels-and-sync-lag]], [[feedback-labels-true-for-the-mon-on-screen]].

RANKS MUST ONLY COUNT STAGES THE SPECIMEN CAN REACH (2026-09-17, user: "the evo ranked tags are incorrect").
rank_cache ranked every mon through its whole gamemaster family graph, so a CaterpieGofest2026 was ranked
Butterfree GL #3 and a PikachuGofest2026CapYellow Raichu GL #1 -- forms with no evolution branch at all -- and a
male Snorunt would have ranked as Froslass. The false chain rank did two things: it produced wrong `Evo GL/UL
Rank N` tags, and it KEPT the Caterpie outright (gl_iv + pvp_rank) as a PvP asset it can never become. Fix at the
source: `rank_cache._reachable()` trims the chain to its own stage when the FORM cannot evolve and to its own
gender's branch for the six GENDER_TERMINALS families. 203 rows re-staged, exactly one keep changed (that
Caterpie -> pile, 4th of a 3-slot costume cap). GENDER_TERMINALS now lives in `evolvable_forms` (one definition,
shared with keep_policy.reach); `granular_tags.own_and_evo_rank` applies both gates; `audit_labels.py` checks
every Evo-rank tag member every pass. Costume-by-field mons are judged by `evolvable_forms.costume_can_evolve`
(game-master Noevolve rule + allowNoevolveEvolution); a Noevolve costume gets no Evo rank tag.

CAP-GATED RANK TAGS + "PvP Spread" (user 2026-09-19: "recheck all the ivs for each and every pokemon you have tagged
for gl and ul ... some are incorrect. some even over the cap"). A rank tag is a promise the mon can play that league,
and CP only goes UP, so:
  * an OWN-stage rank tag needs the mon's CURRENT cp <= the league cap (3 were wrong: Gardevoir 0/15/15 cp2494 and
    Charizard 0/13/15 cp2500 tagged Great, Magmar 2/12/15 cp1914);
  * an EVO rank tag needs the mon's cp AT THAT STAGE, at its current level, <= the cap -- evolving does not change the
    level, so a lv27 Wailmer only ever makes a 1620 CP Wailord (4 were wrong: Clamperl, Raboot, Wailmer, Croconaw).
CP is computed with the standard formula (exact on 5,511 of 5,644 = 97.6%; legendaries with stale pvpoke base stats
run ~2% high). CP_TOLERANCE = 1.03 (pvp_iv_rule.py) applies to BOTH tests: the own stage is judged on the real cp
column, later stages on the cp_at projection, and either counts as over the cap only above cap x 1.03.
keep_policy rule 15b still KEEPS those mons on purpose (it protects an elite spread that is over cap -- the Mareep
rule), so granular_tags emits `PvP Spread` (no Rank chip) for any PvP-kept mon left without a league tag;
audit_tags_membership accepts PvP Spread; `PvP Over Cap` is retired (RETIRED_TAGS). `audit_rank_tags.py` (#8 of
the 10 audits in full_audit.AUDITS) re-derives every rank tag per mon from the IVs: over-cap, stored-vs-fresh rank,
tag-vs-rank, stage viability, evo reachability. Tag-member counts are NOT capped at 512 -- the same tag held 833
members earlier that day; a stalled count after two pushes in a row is client cache lag.

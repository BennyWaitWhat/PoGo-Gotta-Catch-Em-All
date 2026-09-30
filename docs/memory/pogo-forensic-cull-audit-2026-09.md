---
name: pogo-forensic-cull-audit-2026-09
description: "2026-09-07 forensic audit of every Transfer pile ever: the rank MATH was always correct; the form->speciesId MAPPING fed it wrong base stats for 165 rows (Mewtwo 133/135 inverted, Corsola 3339 is Galarian, Slowking 2734 is normal) with ZERO decision impact; ONE provable wrong release (Mudbray 'pid749', NULL rank, GL #2 of 4096) -- a floor, not a ceiling."
metadata:
  type: project
---

**The metric is the STAT PRODUCT RANK** (PvPoke/PokeGenie "Rank #N + %"): `Atk*Def*floor(Sta)` at the
highest level under the league cap, all 4096 spreads ranked. Under a cap it ANTI-correlates with IV%
(low attack wins because CP weights attack linearly, def/sta by sqrt). Verified twice against the user's
own app: Armored Mewtwo (182/278/214) UL 12/15/13 -> #1108 / 96.88%, 12/13/14 -> #1151 / 96.82%; HP
13/15/15 @L27.5 = 160, 15/15/13 @L50 = 190. Stored `gl_rank` is the BEST rank across the evolution
chain (`gl_stage` names the winner); `ll_` is Little League (500), there is no Master League rank column.

**What was wrong:** not the arithmetic -- `form_overrides_complete.py`. 165 rows were ranked on the wrong
species' base stats (Mewtwo f133 'MewtwoA'=Armored had NO key and fell to normal; f135 'MewtwoNormal'
mapped to armored; Corsola f3339 'CorsolaSpring2026' sits on the GALARIAN base; Slowking f2734
'Slowking2022' is normal, not Galarian -- a code comment's premise "no bag row carries 2734" had
EXPIRED). Found by CP+HP reconstruction, which is decisive because CP is a pure function of base stats.
Decision impact: **zero** -- Mewtwo is rarity keep-all; the others hold by variant_floor.

**What was actually lost:** ONE provable case. Mudbray uid 33cb5f4757dde7c0, species parsed as
`"pid749"`, no override -> NULL ranks -> the old engine read NULL as "no protection" -> released; true
rank GL #2 of 4096, 99.65%. Closed by rule 15c (NULL rank => `rank_unknown` => KEEP). A preliminary
"24 wrongly culled / 18 unrecoverable" figure was WRONG -- it dropped the viability gate, which counts
Weedle/Pidgey-class spreads that pin to L50. Two Abra were policy evolution (viability_margin later set
to 0), not bugs.

**The evidence horizon:** snapshots only at 2026-05-19, 05-30, 07-25, 08-19, 09-02 and live; a 56-day
gap; NOTHING before 05-19 (oldest catch 2016). One loss is a floor, not a ceiling -- say so.

Related: [[pogo-pile-gate-2026-09]], [[feedback-pvp-rank-not-iv-threshold]], [[pogo-granular-tags-2026-09]].

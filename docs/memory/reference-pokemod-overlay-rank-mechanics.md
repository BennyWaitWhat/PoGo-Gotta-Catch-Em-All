---
name: reference-pokemod-overlay-rank-mechanics
description: "Pokemod's in-game rank line ('Tinkatink: LL2500(91.25%) GL13(98.00%) UL13(98.00%) / Tinkaton: UL1(100.00%)') = per-EVOLUTION-STAGE stat-product rank of the mon's IVs at the highest half-level under each cap with a LEVEL-50 ceiling (no best-buddy L51), every stage shown incl. stages that never reach the cap, no meta, no reach-gate. Reproduced exactly 2026-09-08 (LL off by one = tie handling). Our ranker uses the same L50 ceiling (MAX_LEVEL_IDX=98)."
metadata:
  type: reference
---

**Verified 2026-09-08** against the user's screen (13/15/15 Tinkatink, Osaka): with `lvmax=50` every figure
reproduces -- Tinkatink GL13/UL13 (98.00%), Tinkatuff GL11/UL11 (98.39%), Tinkaton GL1568 (95.53%) UL1 (100.00%);
Little League 2499 vs shown 2500 is tie ordering. With lvmax 51 Tinkaton is UL#14 (98.91%) and with 40 it is UL#8,
so **the ceiling decides ranks for species that reach the cap only near max level** -- always state which ceiling a
rank assumes. Armored Mewtwo-class species (cap reached ~L28) are ceiling-insensitive, which is why the earlier
1108/96.88% anchor matched under any ceiling.

**What the overlay is telling the player:** for each stage of the chain, how good THIS copy's IV spread is for
that stage in that league; identical GL/UL numbers on a stage mean the stage maxes out under both caps (the
degenerate "max level + best IV" ranking). The player reads the BEST stage and builds toward it ("evolve twice and
power up so it can be UL 1"). Our engine identifies keepers the same way (best stage across the chain, top-5 of
4096) and additionally requires that stage to reach the cap before it *tags* PvP; measured live: removing that
gate would add 658 labels and change 0 keep/transfer decisions.

Related: [[reference-pvp-rank-no-headroom-research]], [[pogo-viability-blind-best-stage-bug]], [[feedback-pvp-rank-not-iv-threshold]].

**ADDENDUM 2026-09-30 (CP multipliers):** cpm_table.py's 20 half levels (L20.5-29.5, L41.5-50.5) were up to 4.85e-6 below the game's own values; they now match the client game master and PvPoke's cpms (7.9e-8 on all 101). The overlay appears to rank on the older rounded values (inferred: the 12/15/13 Armored Mewtwo anchor it confirmed as #1108 only reproduces on them). The repo now says #1109: Armored Mewtwo 9/9/15, capped at L28.5, really out-scores it (4,544,518.8 vs 4,544,497.6). Expect an occasional +-1 against the overlay for spreads capped at those half levels next to a near-equal neighbour; on 2026-09-30 it changed 0 tags and 0 keep decisions.

---
name: pogo-pattern-pooled-lines-2026-09
description: Scatterbug/Spewpa/Vivillon keep ONE plain_line pool per PATTERN across the whole evo line (user rule 2026-09-08); pattern_pools.py + keep_config.pattern_line_pools; no comb-up for pooled lines; PvPoke has one id for all 20 Vivillon patterns
metadata: 
  node_type: memory
  type: project
  originSessionId: 9f2eff52-4f4a-4130-a61e-420ac1dd82ff
  modified: 2026-09-21T03:31:57.532Z
---

**Rule (user, 2026-09-08: "Fix Scatterbug so there's the top 3 of each region type only for its whole evo line").**
For lines whose FORM survives evolution (Vivillon's 20 patterns), all stages of one pattern share ONE
`caps.plain_line` pool: Jungle Scatterbug + Jungle Spewpa + Jungle Vivillon = 3 slots total, ranked by
the engine sort (IV, CP, uid). Pre-evo cap 2 does NOT apply inside a pool. Roster lives in
`keep_config.pattern_line_pools` = [{name:"vivillon", pids:[664,665,666]}]; helper module `pattern_pools.py`
(pool_key(pid, species_name, form) -> (('pool',line), pattern, 0) or None; is_pooled; is_pool_key).
Pattern = live Form-enum name minus the species prefix ('ScatterbugJungle' -> 'Jungle'); unknown/0 form
-> not pooled (falls back to per-(species, form), the safe direction).

**Why:** the general comb-up keys stage holdings by PvPoke speciesId, and PvPoke has ONE id for all
Vivillon patterns, so "is a Vivillon slot free?" was answered species-wide: a Jungle Scatterbug was judged
against Continental Vivillon copies (Rapidash-class bug, one level deeper) while the user owned zero
Jungle Vivillon. Two Scatterbugs sat in the pile that way.

**How to apply:** pooled lines never enter the comb-up (`_evo_ok` is False for them);
instead a pooled-line Evolve advisory marks the best kept pre-evo of a pattern that has NO final-stage
copy (never the last copy of its own form, never a trophy). Consumers that were changed together
(capped-vs-keep-all lesson): keep_policy 1b, granular_tags Variant ordinals, `_lawcheck.py`, `_evocheck.py`,
RUNBOOK, dashboard help. Other candidate lines with the same shape (Flabebe/Floette/Florges, Shellos,
Deerling, Burmy) are NOT pooled -- add them to the config only if the user asks. Measured effect on the
live bag: pile 24 -> 23 (Savanna 73% rescued; Jungle 82% stays out: Jungle pool = 98/96/93), 11
Evolve-Twice labels moved to the best pre-evo of each Vivillon-less pattern.
Related: [[pogo-capped-vs-keepall-bug-class]], [[pogo-forensic-cull-audit-2026-09]], [[pogo-rank-tags-per-stage-2026-09]].

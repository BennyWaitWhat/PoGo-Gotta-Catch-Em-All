---
name: pogo-form-enum-arbitrates-cp-ties
description: CP can't separate speciesIds that share a stat line; the live Form enum NAME can, and audit_invariants now does it.
metadata:
  type: project
---

CP reconstruction proves a STAT LINE, not WHICH tied speciesId a mon is -- `burmy_plant`/`burmy_sandy`/`burmy_trash`
are identical by CP but have different evolution chains, so a mis-mapping there changes the rank the cull runs on
and CP could never show it. That was a standing WARN in `audit_invariants` (I7) telling a human to check by hand.

`check_stat_line_fidelity()` now checks it automatically: score each tied candidate by how many of its suffix
tokens the live Form enum name for that form id confirms, minus the ones it contradicts (`DarmanitanStandard`
separates `darmanitan_standard` from `darmanitan_galarian_standard` only with the penalty term). A lone winner
that is not the mapped id is a **BLOCK**. Shadow twins are collapsed first or they split the vote.

Three classes are dismissed without accusation: a mapped PLAIN id (a costume Pikachu IS `pikachu` on purpose),
a tie where NO candidate evolves (a swap cannot move a rank), and a mapped id whose LATER stages contain every
rival's (compare later stages only -- `pikachu_shaymin` reaches the same raichu plain `pikachu` does).

**Result:** 132 unverifiable pairs -> 0. The audit runs 0 BLOCK / 0 WARN. It carries a self-test (GeodudeAlolan,
CastformSunny) that BLOCKs if the scorer ever stops being able to accuse -- verified by breaking it on purpose.

**How to apply:** when CP "cannot decide", reach for the live Form enum before asking a human. See
[[pogo-forensic-cull-audit-2026-09]] (the form->speciesId mis-mapping that caused a provable wrong release).

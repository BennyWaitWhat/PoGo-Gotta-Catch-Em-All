---
name: reference-hatched-mon-isegg-artifact
description: "PokemonProto.isEgg_ (@0x50) stays =1 on a freshly HATCHED pokemon for ~1-2 days after hatching; an egg is a SHAPE (no CP/IVs/level), not the bit. Blocking the pile on the bit alone false-blocked a legitimate Scorbunny; the same window coincided with its SetPokemonTags silently no-op'ing across 4 syncs."
metadata:
  type: reference
---

**Measured live 2026-09-08 00:41** with a gated read-only Frida attach (Frida 17: `ptr(a).readByteArray(n)`,
`Memory.readByteArray` is gone): a Sobble hatched 04:20Z that day still read `isEgg_=1` at ~20 h; a
Scorbunny hatched the previous day (05:25Z) had cleared to 0 -- although the bag walk minutes earlier
had still recorded it as 1; three control mons read 0. Both have CP (~600), level 20, all IVs >= 10
(the hatch floor), and NO pokeball / capture cell / weather -- the hatch fingerprint. Neither is in
the `eggs` table (which is itself stale: a hatched Pichu sits there with is_hatched=0).

**RULE:** `is_egg != 0` alone is NOT an egg. An egg has no CP, no IVs, no level. `preflight_transfer.py`
now blocks only on the egg SHAPE (`is_egg != 0 AND (cp NULL/<=0 OR iv_total NULL)`) and prints a
"recent HATCH, allowed" note for a CP-bearing row with the bit set. The bit-only guard had exit-4'd the
entire recrawl pipeline ("FAILED the keeper gate") on a legitimate 10/14/13 pile Scorbunny.

**Plausible, not proven:** that Scorbunny is the same mon whose Transfer tag write silently no-op'd on
4 consecutive daemon syncs while `isEgg_` was still 1 -- consistent with [[reference-fresh-catch-tag-write-lag]]
(SetPokemonTags on a fresh record can no-op). If a hatch refuses a tag, wait for the bit to clear.

Related: [[pogo-pile-gate-2026-09]], [[pogo-data-completeness-before-destructive-actions]].

**Confirmed 2026-09-13:** a Squirtle hatched 22:37Z (is_egg=1 in the DB) refused the Transfer tag in three syncs
(19:00, 19:01, 19:22), each reported as `Transfer short=1` and failing the whole sync (rc=1, set_db mirror
skipped). prune's verify now names the short members (species, IV, catch time) and DEFERS is_egg=1 members
instead of failing; the tag lands on a later pass once the flag clears. A verify miss that repeats across passes
on one mon: check is_egg before anything else.

**Locked mons refuse tag writes too (2026-09-16, user: "there's things such as buddy and gym and showcase pokemon").**
A Litten 57% from August stayed `extra` on Variant #2 across passes (the removal never persisted) -- a buddy, gym
defender or showcase entry ignores SetPokemonTags in both directions. prune's verify now DEFERS up to 3
short/extra per advisory tag (and up to 3 SHORT on Transfer); more than 3 is cache lag and fails the pass for a
retry. An EXTRA on Transfer still fails (a keeper one release away once it unlocks), except for an isEgg hatchling: prune defers those on every tag, Transfer included. The DB's
`has_pokemon_contest_info` / `is_deployed` / `is_best_buddy` columns are not read in-walk (pogo_pipeline has no
writer): about 44-49% of in-bag rows are NULL, the rest stale values from one-off May-June 2026 builds (rebuild_full /
add_v5; newest populated row created 2026-06-02; contest info was already marked WEAK/default-allocated when
written). Unreliable either way, so the verify cannot say which lock applies: read buddy/deployed/contest state live.
reconcile defers only isEgg hatchlings (db_only and cache_only); locked-mon drift still shows as DRIFT in reconcile.

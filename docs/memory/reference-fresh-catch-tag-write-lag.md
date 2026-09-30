---
name: reference-fresh-catch-tag-write-lag
description: "SetPokemonTags on a minutes-old catch can no-op (client acks OK, binding never lands in cache) — advisory tags self-heal next sync; don't burn a session on one"
metadata: 
  node_type: memory
  type: reference
  originSessionId: d44dc321-2608-42e7-870c-24289b882f3e
  modified: 2026-08-19T23:47:18.420Z
---

2026-08-19: a Turtwig caught at 23:36Z rejected its `Evolve 2` tag write at 23:40Z ("SetPokemonTags exc"
on first try, then two "apply_changes OK" acks that never appeared in the tag cache; reconcile kept
showing db_only=1 even after a 45s settle window). Not deployed (live gym coords 0,0), not a special —
only distinguishing fact: the catch was minutes old while the user was actively playing.

**Handling:** if the ONLY drift after a sync is an ADVISORY tag (Evolve Next/Twice/Shiny, GL/UL Rank, Evo GL/UL Rank, XXL) on a
freshly-caught mon, report it and move on — every future sync re-applies the delta automatically, and it
lands once the mon settles. Only escalate when Transfer or a trophy tag (Hundo/Nundo) drifts, or the same
uid still drifts a full cycle later. Diagnose with: reconcile `--verbose` for the uid → DB row +
policy_reasons → live proto read (deployment/buddy). Related: [[pogo-tag-system-2026]] (tag-write
cache-lag), [[feedback-no-app-restart-while-playing]].

**Stale bindings (2026-09-26).** After a verified-exact push, reconcile reported 12 "cached member proto(s) not in live
bag" (Hundo 2, XXL 1, Legacy 3, Best ML 2, Variant #1 4) -> false SYNC FAILED, report + post-tags skipped. A tag binding can
keep an OLDER proto object of a mon still in the bag. Fix (reviewed twice): ENUM_MEMBERS_JS returns memberUids
(PokemonProto.id_ @0x20, == uid_hex on all 5,775 stored protos) + tagId (PokemonTagProto @0x38) + export liveTagIds
(pokemonTagIds_ @0x180, RepeatedField array_@0x10 count_@0x18 items @+0x20). `reconcile_tags.stale_members` -> a stale
entry counts toward EXTRA always, toward already-tagged/SHORT only if the live tag list confirms it (else re-added). An
unconfirmed "ghost" extra is ignored on advisory tags but FAILS on Transfer; hatchlings never excuse a Transfer extra.
First live run: check prune's plan line for "stale-bound unconfirmed" counts.

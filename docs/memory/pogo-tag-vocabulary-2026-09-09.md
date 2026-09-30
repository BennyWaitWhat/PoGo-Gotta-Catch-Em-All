---
name: pogo-tag-vocabulary-2026-09-09
description: "The tag set after the 2026-09-09 re-evaluation (31 managed = 6 legacy + 25 vocabulary, 4 exempt, 23 retired on 2026-09-20), the EMPTY-SET contract that fixed the stale Safety Hold, rank tags gated to cap-reaching stages; empty shells delete in one session"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9f2eff52-4f4a-4130-a61e-420ac1dd82ff
  modified: 2026-09-22T18:19:07.320Z
---

**Re-evaluation (2026-09-09).** User: "I feel like I have too many tags and some are redundant" -> "drop 13 + gate" ->
"re-eval all the tags" -> "are any of the tags redundant with the in-game native filters?" -> "drop shadow".
53 device tags -> 31 managed on 2026-09-20 (`granular_tags.registry()`: 6 legacy + 25 vocabulary, incl. Evolve Shiny
since 2026-09-12) + 4 exempt (`EXEMPT_TAGSETS`: Armored ML/UL/Trade/Release); Remote Trade and Evolve for Size are
synced by their own scripts. Chips per kept mon 2.15 -> ~1.1.
- Retired: `granular_tags.RETIRED_TAGS` (23 on 2026-09-20, each with its reason). Seven of them repeat a native filter
  chip whose count matched the DB exactly (Legendary 572 = legendaries only, no Ultra Beasts; Mythical 40; Shiny 1481;
  Shadow 240; Event; Location/Special Background 54+239 = 293).
- `granular_tags.NATIVE_COVERED_REASONS` (7 on 2026-09-20, incl. favorite and shiny_ladder): a kept mon whose only
  reasons are these needs no tag of ours; the chip plus the absence of Transfer is the label.
- Rank tags (`GL/UL Rank 1`, `Rank 2-5`, `Evo ...`) are OWN-stage / later-stage AND gated to stages whose L50-hundo
  CP beats the league cap + viability_margin (an under-cap hundo is "#1" -- true, printed by Pokemod, useless).
  Effect: UL Rank 1 352 -> 21, GL Rank 1 176 -> 28, Evo UL Rank 1 113 -> 2 (Raichu 2467, Kadabra 2328... under 2500).
- `Adventure Effect` = the FORM that has the effect (derive_ae_roster schema 2 `species_ids` from the live registry
  + PvPoke movepools: Origin Dialga/Palkia, Black/White Kyurem, Crowned Zacian/Zamazenta, Dusk Mane/Dawn Wings
  Necrozma, Eternatus) = 38, like the chip (39). The KEEP rule 8 is form-level too now, so the 88 base-form copies
  are ordinary legendaries under the rarity cap (4 Necrozma + 1 hero Zamazenta went to the pile).
- Legacy 6 keep their filenames/colours: XXL, Hundo, Nundo, Traded by E+F, Legacy Moves, Transfer.
- NOT redundant (user corrected me): Nundo (`0*` is a 0-star search, not a nundo), XXL (top-N by showcase score,
  no search does that), Ultra Beast/Paradox/Rare Other (no chip).

**Empty-set contract (the "Safety Hold never resolved" bug).** build_tagsets writes a file for EVERY registered
tag, EMPTY when nobody qualifies; prune pushes want=<empty> and strips stale members, but never CREATES a device tag
for an empty want. Missing file still = "producer did not run, do not touch". Before: build() stopped emitting Safety
Hold, its 2026-09-03 file was never rewritten, prune pushed the stale file for 5 days.

**Retirement = strip, then delete.** A tight delete loop once collaterally deleted 'Mega', so `retire_tags.py`
deletes one shell at a time with a collateral census between deletions (full_audit calls it fail-soft after each
good sync, --max 3). Measured 2026-09-09: all 15 EMPTY shells deleted in ONE game session (3 s settle each, zero
refusals) -- the old "1-3 DeleteTag per session" limit did not bite on member-less tags; it likely bites on tags
that still hold members, so build_tagsets deletes the file -> prune strips members (verified server=0) -> delete.
retire_tags also deletes EMPTY managed shells (file present-and-empty, e.g. Safety Hold once its hold cleared);
prune recreates a tag the day someone qualifies again.

**Consumers that had to change together** (the capped-vs-keep-all lesson again): granular_tags, build_tagsets,
prune_tags, audit_tags_membership, audit_cull, system/scripts/audit_tags.py (in-pipeline; it still expected
GL_IV.txt and failed the recrawl with rc=4), dashboard TAG_FILES, RUNBOOK, system/tags/registry.json.
Related: [[pogo-granular-tags-2026-09]], [[pogo-rank-tags-per-stage-2026-09]], [[feedback-labels-true-for-the-mon-on-screen]], [[feedback-one-phone-pass-not-three]].

"Remote Trade" (2026-09-19): his OWN in-game tag, visible to Forever Friends, for trade offers. Filled by
`push_remote_trade.py` (modelled on push_armored_plan.py: one gated session, bag walk, per-mon deltas, batched
apply_changes, re-walk verify, _mirror_db) from `system/analysis/_remote_trade_picks.json`. The rule: group by
cosmetic variant (species, form, costume, background, Dmax/Gmax, shiny -- non-shinies too), keep the best 2 by IV
(KEEP_BEST), offer a copy only when its keep reasons are exactly {shiny}, {variant_floor} or {rarity} and it carries no
Variant #1 / Shiny - Only One / Last Copy tag; never the pile, traded/lucky, shadows, untradable per the game master or
caught in the last 30 days (remote trades have a 30-day catch lockout); at most 3 per species (SPECIES_CAP), best IV
first.
THE REAL GOTCHA (corrected 2026-09-19): "Remote Trade" and "Favorites" are NOT in the numbered tag list that
`GetCachedTagToPokemonBindingForIndex` walks -- TaggingRpcService exposes them as their own bindings,
`get_RemoteTradeTagBinding` and `get_FavoritesTagBinding` (binding+0x10 = tagProto, binding+0x18 = List<PokemonProto*>,
the same shape ENUM_MEMBERS_JS parses). enumerate_all_tag_members therefore never returns them, my lookup concluded the
tag did not exist, and create_tag made a SECOND ordinary tag with the same name (his 17 untouched, my 252 in a look-alike
at the bottom of his Tags screen). `fix_remote_trade_binding.py` repaired it: read the real binding, move every pick onto
its tagProto with the ordinary SetPokemonTags path, strip the old members, DeleteTag the duplicate. Lessons: identify a
tag by tagProto/tagId, NEVER by name (a name-keyed dict also silently collapses duplicates), and check the special
bindings before create_tag. The game's own write path is RemoteTradeRpcService.MarkRemoteTradable, not needed --
SetPokemonTags on the binding's tagProto works and the UI shows it immediately.

Remote Trade is refreshed EVERY cull (user 2026-09-19: "make this a part of your cull every time to update it"):
`remote_trade_picks.compute()` is the one definition of the offers and `sync_remote_trade.py` delta-applies them to
the binding's tagProto; full_audit.py runs it after the verify and NEVER fails the cull over it. sync_remote_trade
never calls create_tag -- if the binding is missing it skips.
**STUCK SINCE 2026-09-19 23:37 EDT (found 09-22 from transcripts):** the first push after `{'rarity'}` joined
SOLE_REASON (his "legendaries and stuff", 23:35) failed WHOLE -- verify read 511 (want 569), even its 13 removals did
not land -- and every pass since shows ~506-511 on the tag, +71..79 -13..18, no success line. Before it the same path
applied a +541 request fine. All changes go in ONE request (apply_changes batch=150), so one refused mon sinks all.
full_audit's filter HIDES the "client cache lag" line (now: `Remote Trade NOT confirmed: ...`, shown in the summary).
**CAUSE, read from the game 2026-09-22: 3 DEOXYS** (mythical; the game master calls Deoxys tradable, remote trade
never allows mythicals). The other 68 legendaries are fine. **The game's own verdict lives in
`Niantic.Holoholo.RemoteTrade.RemoteTradeRpcService`:** a `Dictionary<ulong, TradeExclusionProto.ExclusionReason>`
(get_NonRemoteTradablePokemon) + `HashSet<ulong>` time-locked (get_TimeLockedPokemon), EMPTY until
`UpdateNonRemoteTradablePokemon()` runs (the first managed call in a fresh session throws once -- retry). Reasons 0-20:
Unset, MythicalPokemon, Slashed, GymDeployed, Buddy, StaminaNotFull, EggNotHatched, ..., AlreadyTraded, ...,
Favorite, TempEvolved, FusionPokemon, FusionComponentPokemon, LastBreadPokemon, InEscrow, UntradableCatchCooldown,
RestrictedBackground. Live bag: code 1 covers mythicals AND shadows (96% of its non-mythical members), plus
AlreadyTraded 70, FusionComponent 5, Buddy 1. `sync_remote_trade.game_refusals()` drops them before every push.
Reading those collections: take the stride from `il2cpp_class_value_size(element class)` --
`il2cpp_class_array_element_size` returned 8 for these shared generic arrays and misread 2 of every 3 entries.
Also: `RemoteTradeRpcService.MarkRemoteTradable(List<MarkedPokemon>)` is the game's own write path (unused).
`fresh_tag_ids` is filled from the NUMBERED binding list (refresh_tag_bindings) and can NEVER show Remote Trade --
do not judge RT membership from it.

NEW TAG "Evolve for Size" (colour 6, 153 members, user "all 176 lets go"): the pre-evos whose PROJECTED evolved copy
would still be XXL-grade (z >= 4) at the target AND out-score his best entry there -- sync_evolve_size.py, refreshed by
full_audit on BOTH finish paths like Remote Trade. It is deliberately NOT "Evolve Next": that label means the cull
reserved an IV slot, and most of these (a 31% Magikarp) would never earn one -- the reason is size, so the tag says so.

**2026-09-24 03:30 -- two new managed tags (33 now):** `Evolve Shiny Gated` (a shiny that would earn Evolve Shiny but the game gates the evolution: item / task / buddy walk / time) and `Evolve Gated` (an Evolve Next/Twice promise whose promised stage is gated -- moved OUT of Next/Twice, which now mean "doable now"). Labels only, keep unchanged. Built by build_tagsets (refresh_evolve_shiny.compute_target(gated=...) and promises.json + evolvable_forms.gate_reason), registered in granular_tags.all_tags, audited by membership + tag-truth; the "Evolve Next may be empty" rule in audit_cull/membership counts gated promises as covered. User: "Why dont you tag the ones that need something separately? pls do." / "For everyone too."

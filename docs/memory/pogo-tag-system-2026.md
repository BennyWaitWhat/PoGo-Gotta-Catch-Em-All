---
name: pogo-tag-system-2026
description: "The PoGo server-tag system: 31 managed tags from granular_tags.registry() (registry.json is a stale snapshot), caps in keep_config.json, the only-non-native philosophy, the variant/cap model and displacement/collapse rules, the gated sync order, and the device lessons (foreground writes, cache-only reconcile, proto reallocation)."
metadata:
  node_type: memory
  type: reference
  originSessionId: bfa0e937-6d24-4247-b31e-7cb410360577
---

> **Tag vocabulary** = 31 managed tags from `granular_tags.registry()` (LEGACY_TAGS + all_tags(); Evolve Shiny
> joined on 2026-09-12; scheme in [[pogo-granular-tags-2026-09]]). See [[pogo-tag-vocabulary-2026-09-09]], though its
> 30-managed count predates that change.
> `system/tags/registry.json` is a stale one-off 2026-09-09 snapshot (30 tags, Evolve Shiny still exempt, no caps,
> no procedure) that doctor.py and refresh.py still read, so it is not authoritative. Caps live in
> `keep_config.json` ([[project-keep-config-dashboard]]); the middle-stage cap (`plain_line_preevo` = 2) is a `keep_config.py` DEFAULT. Colour values
> must be 0-8 — 9 is invalid and silently no-ops.

The server-tag system lives in `pogo_extract/system/` — `README.md` (model), `tags/registry.json` (the stale
snapshot above), `procedures/`, `issues/`, `scripts/` (hardened tooling), `analysis/`.

**Source-of-truth model:** server tags are authoritative (persist across app
restart/DB rebuild). `pokemon.db.auth_tag_names` is a MIRROR; reconcile direction
is server→DB. The live bag is ground truth for membership. A correct tag means
**server count = DB count = rule count** (`reconcile_tags.py --report`). **INVARIANT:** every keep tag = (its rule)
MINUS `Transfer`.

**▶ 2026-06-08 — BEST BUDDY RETIRED** (user: *"nuke best buddy ... the only best buddies i have are goated
anyway"*): the `best_buddy` keep-reason, tag and preflight axis are gone; 0 mons were sole-best_buddy, so the removal
transferred NOTHING.

**▶ 2026-06-05 (v8.0) — PICHU keep-all + CRAWLER COMPLETENESS.** (1) User: *"i like my pichu, leave them alone"* →
`PROTECTED_KEEP_ALL` (keep_config protected pids, reason `protected`) keeps EVERY Pichu regardless of caps; add a pid
for any future "leave them alone" species. (2) User: *"it needs to get everything"* — reflecting ALL 96 PokemonProto
+ 27 Display fields found `pogo_pipeline.parse_pokemon` never parsed **4 keep-criterion fields** (set only by retired
one-off scripts → silently stale): capture date (`creationTimeMs_`@0xa0), mega Level/Points (`Level`@0x18/`Points`@0x10
of the mega sub-proto), best-buddy badge (`PokemonBadge`@0x28==1), original owner (`originalOwnerNickname_`@0x100
string). ALL now parse live every crawl. Detail in [[reference-live-cosmetic-reads]].

**▶ 2026-06-05 (v7.9) — caps are MEASURED, never a formula:** edit the cap, recompute, count the live delta (a gross
estimate of ~87 cut copies measured out at 36 net). **Tooling:** `pogo_il2cpp.ADB_TARGET` is env-overridable (default
Tailscale) — run with `ADB_TARGET=4A181FDAP0013G` (USB serial) when Tailscale is down; the ZygiskFrida gadget attach
uses `127.0.0.1:27047` (adb forward), so only `ready_gate`'s device/foreground checks need the right serial.
**Recurring frida fix:** the gadget drops whenever PoGo's PID churns (saw 4 restarts/session, likely the Android
freezer): re-run `adb forward tcp:27047 tcp:27047` and retry; the ZygiskFrida gadget comes back with the next PoGo
launch. The churn's cause, the cached-apps freezer, is persistently disabled (settings global cached_apps_freezer =
disabled, user-approved 2026-06-06; see [[pogo-frida-stability]]): verify it, don't re-apply.

**▶ 2026-06-05 (v7.8) — SHINIES ARE CAPPED, NOT OFF-LIMITS.** User: *"I place a single shiny across all gyms ...
keep highest IVs."* That REVERSED the 2026-05-29 "shinies are off-limits, never transfer" rule; the shiny cap (per
species/form, by IV) lives in keep_config. Special shinies (hundo/costume/dex-only...) beyond the cap are still kept by
their OWN rule. **⚠️ DO NOT re-assert "shinies off-limits."**

**▶ 2026-06-04 (v7.7) — FORM-ENCODED COSTUMES (from the LIVE Form enum; user demanded TOTAL diligence, no
spot-checks).** PoGo bakes a whole class of costumes into the form NUMBER itself — `LaprasCostume2020`=2585,
`CaterpieGofest2026`=3346, `PsyduckSwim2025`=3019, `UmbreonGofest2024Mscarf`=2848, ... They carry **`fresh_costume`=0**,
so every rule that only read `fresh_costume` treated them as PLAIN (3 sat in Transfer). **FIX:** `costume_forms.py` (a
code is a costume iff its enum name isn't `<Species>Normal`, isn't regional, and carries a year 19xx/20xx or costume
keyword) → `keep_policy._truly_plain` routes costume-forms to the rule-1a cosmetic cap. **Re-dump the enum when new
costumes ship** (`system/scripts/game_read/classify_all_forms.py` → `form_enum.json`). LATENT: a future costume whose
enum name has no year/keyword would be missed → extend `costume_forms._KW`.

**▶ 2026-06-04 (v7.6) — EVERY VARIANT IS ITS OWN BUNDLE.** User: "every variant is supposed to be bundled too. wtf
dont you know your caps?" — after catching 2 Lapras (form **2585**) tagged Transfer.

**THE CAP MODEL — memorize this:** each distinct VARIANT of a species = its own bundle with its own top-N cap, and
**NOTHING is ever merged across variants.** The engine uses two keys:
- **PLAIN stage key** = `(pokemon_id, cf-form, gender only for GENDER_TERMINALS species)`, or the pattern pool for
  pooled lines (Vivillon).
- **COSMETIC variant key** (`_vkey`) = `(pokemon_id, cf-form [which carries form-encoded costumes], fresh_costume,
  [retired slot, always 0], fresh_natural_art_bg, costume_decoration_id, fresh_bread_mode 1/2)`, with no gender.
- Location cards are their own capped axis `(species, cf, card id)`.
- `special_bg_id` and `natural_art_background` are garbage columns; never key on them.
- Special-attribute rules (Hundo, Shiny, Legacy, Shadow_best, XXL, Location, PvP-spread, GL/UL-IV, Traded, Evolve)
  keep mons **on top of** the bundle caps.

**THE BUG:** `normalize_forms.py`'s `collapse` set MERGED distinct NONZERO form codes into one canonical (Lapras
322+2585, Caterpie 953+3346, Umbreon 1235+2848, ...) on a "pvpoke lists single-form ⇒ it's drift" heuristic — the SAME
blind spot that mis-flagged Dynamax. That dumped the 2585 Lapras into the 322 cap and transferred them. **FIX:**
`collapse` is GONE (always empty); each distinct nonzero `form` code keeps its own `(pid,cf)` bundle. The ONLY
normalization left is the **form-0 FOLD** (a bare form-0 UNSET → the species' most-common real code, to kill the
phantom-0 bucket; Tauros/Persian).

**LESSON (3rd time this class — Dynamax, then Lapras 2585): NEVER merge or transfer the user's proto-distinct variants
on a "the data says it's the same / garbage" heuristic.** Each distinct code/flag the user holds is a variant to
BUNDLE, not collapse. If something is genuinely drift the user wants merged, add it to an explicit per-code blocklist
— never auto-merge.

**▶ 2026-06-04 (v7.5) — DYNAMAX IS A REAL AXIS.** User: "just like my gmax, my dmax are bundled too bro... fix that."
A study agent had called `fresh_bread_mode==1` "garbage phantom-Dynamax", so Dynamax was treated as PLAIN — that
**transferred 43 Dynamax** and displaced plain mons that lost a cap slot to one (a **lucky iv43 Blastoise**; 2 of 5
**Duraludon**). `bread==1` is the game's REAL Dynamax flag, a collectible axis **exactly like Gmax**: `_truly_plain`
treats `bread in (1,2)` as NON-plain and each is its OWN per-(species,cf,bread) bundle; `bread==4`/other stays plain
(invalid enum). **LESSON: a workflow agent's "this data is garbage / X can't do Y" claim is a HYPOTHESIS — confirm
against the game's own flag + the user before deleting a collectible axis.**
Purified (`fresh_alignment==2`) is not its own keep axis: it competes as plain (asked about a piled 67% purified
Meganium, user "just asking" 2026-06-04, nothing changed). A purified axis would be the user's call.

**▶ 2026-06-04 — Raichu fix (DANGEROUS, audit-found):** `cf()` base_form let NULL-`form_region` regional codes (Alolan
Raichu form 50) masquerade as base-region → Kantonian Raichu collapsed onto the Alolan code → **3 keep-worthy Raichu
wrongly transferred**; base_form now excludes any code whose `pvid` is `_alolan/_galarian/_hisuian/_paldean`.

**▶ 2026-06-03 (v7.2) — FORM-AWARE EVOLUTION GRAPH.** `build_evo_graph` is **speciesId-keyed**: `reach()` resolves the
specimen's speciesId via `pvid(name, form)`, so regional pre-evos resolve their OWN family (Galarian
Zigzagoon→Obstagoon, Meowth→Perrserker, Farfetch'd→Sirfetchd, and **Hisuian Sneasel→Sneasler NOT Weavile**). A
**BST-monotonicity gate** drops any `family.evolutions` edge whose target baseStats-sum < source (the gamemaster's
REVERSED Sinistcha→Poltchageist) + an `EVO_FIX` forward Poltchageist→Sinistcha; curated `EVO_FIX` edges BYPASS the BST
gate (it had dropped Doublade→Aegislash_shield, Shield BST 524 < Doublade 547, and mis-tagged Honedge). An evolution
counts ONLY if its TARGET pid is in the live dex (user "Duraludon doesnt evolve"): pvpoke lists evolutions PoGo hasn't
enabled, so those sources are TERMINALS, and the pvpoke `released` flag is NOT a reliable availability signal — use the
DEX.

**▶ 2026-06-03 (v7) — PER-(STAGE,FORM) CAP** (user "the cap is for each stage/form"): the 2026-06-02 evolution-aware
LINE pool was WRONG — it pooled a whole line into ONE top-N and transferred FINAL forms (caught on 2 Arboliva culled
because the line slots were filled by hundo Smoliv+Arboliva). Each STAGE and each FORM keeps its OWN slots (the PLAIN
stage key above). Gender is a cap axis ONLY for the gender-evolvers (GENDER_TERMINALS: Combee/Salandit/Snorunt/Kirlia/
Ralts/Burmy) so a rare female keeps her own slots (never crowded by common males). `pogo_pipeline.parse_pokemon` reads
gender (display proto +0x14) on EVERY walk, and keep_policy `reach()` returns EMPTY (not full-reach) for UNKNOWN gender
on a gender-locked species — a NULL-gender MALE Combee had been wrongly tagged Evolve (male Combee is a dead-end). User rule: *"dont tag for transfer just because you found a
replacement in the evolve tags"*.
**CONDUCT (user, emphatic): RECRAWL + FULL-SYNC every operation, INCLUDING Transfer — never freeze a tag and never
"wait for the user"** (I over-read "dont tag transfer until I evolve", froze Transfer, said I'd wait, and got told off:
*"youre going to wait for me?????? no"*). Use `prune_tags.py --atomic` for big membership swaps (prune's per-mon untag
of 349 mons churned the Frida gadget mid-run → crash). Treat NULL/missing protection as PROTECTED.

**▶ 2026-05-30 (v4) — ranking + pipeline mechanics.** (1) **Shadow CP == non-shadow CP:** the shadow 1.2×/0.833×
multiplier is COMBAT-ONLY and applies to `stat_product` ONLY, in both `compute_all_ranks.py` and `rank_cache.py` (on
CP it had ranked a shadow cp996 at GL #3378 instead of #1048). Detail in [[pogo-mechanics-reference]]. (2)
**`rank_cache.py` = drop-in caching ranker** (per-`(species,cap,shadow)` 4096-combo stat-product tables, pickled to
`rank_tables.pkl` keyed by a gamemaster+CPM content-hash; bump `_content_hash` to force a rebuild). It re-ranks EVERY
in-bag mon every crawl — **NO per-mon skip** (standing user rule: a power-up or game update can change any mon between
crawls, so never skip). (3) **Ghost-purge in `step_reconcile_db`:** departed mons (in DB `in_bag=1` but absent from
the live walk) are marked `in_bag=0` immediately (saw **258 depart in one crawl** — this is why you RE-CRAWL before
syncing transfers), and physically DELETEd only after **2 consecutive** missing crawls, gated on walk≥70% of prior
bag. (4) **`ready_gate.ensure_ready_for_writes(sess,pid)`** (7-gate write pre-flight: device+pidof /
il2cpp+PID-stable / screen awake / battery≥15-or-powered+not-Doze / not-frozen / **FOREGROUND** / TaggingRpcService
singleton) is wired into `apply_tagsets.py`, `prune_tags.py` and `nuke_all_tags.py` (live runs only).

**▶ 2026-05-30 (v5) — triage review.** (1) **The rarity rule read the NULL-prone `is_legendary` COLUMN.** The enricher
leaves `is_legendary`/`is_mythical` NULL on many copies (9 of 16 Mewtwo!), so 40 legendaries — incl. an 89% Mewtwo,
Kyogre, Rayquaza, Lugia — were silently dumped into Transfer. FIX: keep_policy matches the authoritative pid ROSTER
(`from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS` → `RARE_PIDS`) OR'd with the
column. Treat NULL/missing protection as PROTECTED. (2) **NOT-a-bug (I retracted my own claim):** `is_best_buddy=1` is
on **601** mons (buddy-progress noise); the real Best Buddy badge `was_best_buddy_badge` was **17**. **LESSON: count a
column's value distribution to learn its SEMANTICS before "fixing" a rule to use it.**

**▶ 2026-05-30 (v4 cont.) — engine fold-in + atomic writes.** `pogo_pipeline.py` runs a `keep_tagsets` step
(keep_policy.py → build_tagsets.py, DB-only subprocesses) right after cull/sanity, so the tagset FILES refresh every
crawl and can never lag behind a forgotten manual step. (The server PUSH stays a deliberate step — needs foreground.)
**Atomic batched tag writes (1 RPC vs 20+):** `bulk_tag.js` export `bulkApplyChanges(svc, [{proto, add:[tagproto],
remove:[tagproto]}, …])` builds ONE `List<PokemonTagChanges>` (each item carries its OWN TagsToAdd + TagsToRemove) →
ONE `SetPokemonTags`. Field configs reuse the two PROVEN single-purpose paths (populated-add + null-remove =
`bulkTagMany`; empty-capacity-add + populated-remove = `bulkUntagOne`; the both-populated case just combines them).
Driver = `tag_ops.apply_changes(bt, svc, changes, batch=150)`. `prune_tags.py --atomic` accumulates EVERY tag's
adds+removes into one cross-tag change-map → 1-3 RPCs total (vs per-mon `untag_one` ≈0.5s each). **★ Verify-retry
lesson:** freshly-ADDED mons false-short the post-write set-equality check for a few seconds — tagging REALLOCATES
their proto and the new binding still references the OLD pointer until the cache settles (REMOVALS never trip this —
no new binding). `prune_tags` verify re-walks up to 3× before declaring drift; the gold standard remains a fresh
`reconcile_tags.py --report`.

**★★ THE FOREGROUND-WRITE LESSON (2026-05-29) — the single biggest device gotcha.** **Tag WRITES (AddTag/create_tag/apply_members/untag) silently NO-OP unless PoGo is TRULY foregrounded** (`dumpsys window | grep mCurrentFocus` == `com.nianticlabs.pokemongo/...UnityMainActivity`). Frida ATTACH, singleton lookup, bag-walk, and tag READS all work while PoGo is backgrounded/screen-off — so everything LOOKS fine — but `create_tag` returns "verify failed: not found" and applies vanish. An entire multi-hour failure cascade (DeleteTag "not persisting", apply "script destroyed" crashes, "no instances of TaggingRpcService", create "not found") was ALL this: PoGo had bounced to the Play Store / screen had slept / cold-start hadn't reached the map. **BEFORE any tag write: verify `mCurrentFocus` is PoGo's UnityMainActivity AND the screen is on.** If a fresh launch shows "no instances of TaggingRpcService", PoGo loaded the bag but not the tag service — open the Pokémon storage UI (or just ensure it's fully on the map, foregrounded) to instantiate it. Low battery (≤~10%) compounds the throttling. The fix for the whole session was the user confirming "you're in the foreground now" → every tag created+applied first-try.

**★ GL/UL PvP keep rule.** The KEEP is keep_policy rule 15b (reason `pvp_rank`) and it is CP-BLIND: any GL/UL rank 1-5
spread at a stage that can reach the league cap (maxcp(stage) > cap + keep_config pvp.viability_margin, which is 0) is
kept whatever this copy's CP, powered-up over-cap copies included; those carry PvP Spread, no Rank chip
([[pogo-pvp-fit-label-not-keep]]). Only `pvp_iv_rule.qualifies()`'s READY branch (the gl_iv/ul_iv reason) and the Rank
LABELS are cap-gated: a READY copy qualifies only at <= the league cap (a powered-up cp2494 Gardevoir can't enter
Great League). A top-5 pre-evo for a viable form qualifies outright; NO IV gate of any kind (see
[[feedback-pvp-rank-not-iv-threshold]]).

**The "under-cap hundo" artifact.** The ranker (`rank_cache.py`/`compute_all_ranks.py`) is mathematically CORRECT —
faithful PokeGenie/pvpoke (stat product at the highest level UNDER the cap). A hundo is normally a TERRIBLE GL/UL
spread, but when the ranked form's **max CP (L50) is below the league cap** the LEVEL cap binds before the CP cap →
every IV pins to L50 → the hundo becomes rank-1 by default (it once inflated `1 GL IV` to 143 and `1 UL IV` to 308,
mostly tiny pre-evos like Flabébé and Kirlia). The fix is the viability gate, not an IV rule: `maxcp(stage) > cap`
(+ `viability_margin`, 0 in keep_config.json since 2026-06-10; never raise it); 1400/2400 are legacy fallbacks only.
Hundo Umbreon (L50 max 2416) is NOT UL-viable under this gate.

**★ NAME RESOLVER fallback (`pogo_pipeline.py`).** `species_lookup` self-bootstraps from already-resolved DB names + a manual `SUPPLEMENTAL_NAMES`, so a NEVER-seen first-catch (Mudbray 749 / Mudsdale 750 / Whirlipede 544) stayed `pidN` forever — which ALSO blocks its PvP ranks (`compute_all_ranks` keys off the name → `to_pvpoke_id` fails). FIX: fall back to the PvPoke gamemaster national dex (`{p['dex']: p['speciesName']}`) for any pid the DB lacks; durable for all future first-catches. (Gotcha: `species_name LIKE 'pid%'` is case-INSENSITIVE in SQLite → matches Pidgey/Pidove; use `GLOB 'pid[0-9]*'`.)

**★ THE "META" vs "IV RANK" LESSON (2026-05-29, the big one) — never conflate these again.** When the user says GL/UL "rankings" they mean **the per-pokemon IV-spread rank** (`gl_rank`/`ul_rank`: 1 = the best possible PvP IV spread for THAT species, e.g. 0/15/15). They do **NOT** mean a PVPoke **species tier list** ("which species are meta-strong"). My `keep_policy` had gated the PvP keep on "is this species in the top-30 PVPoke meta" — so it dumped **rank-1 specimens of non-tier species into Transfer** (a UL#1 0/13/15 Charizard, plus rank-1 Primeape/Arcanine/Excadrill/Gardevoir/Blastoise/Magnezone...). FIX: removed the species-tier concept ENTIRELY (META_TOPN/meta_gl/meta_ul/score-filtering all deleted from keep_policy.py + build_tagsets.py). **`gl_rank`/`ul_rank` is the SPECIMEN's IV-spread rank, full stop — there is no "tier list" anywhere in this collection's policy.**

**★ RE-CRAWL FIRST, ALWAYS.** Rebuilding tags off a stale DB left **71 phantom transfer rows** that wouldn't apply — the mons were already gone from the live bag (full bag-walk resolved 0/71). The bag drifts every session. `pogo_pipeline.py` (no `--tag-transfers`) refreshes in_bag + recomputes ranks. Run it BEFORE keep_policy/build_tagsets or the transfer pile carries ghosts. `nuke_all_tags.py` deletes all server tags by cached id (collateral-safe) + verifies the wipe in a fresh re-attached session (DeleteTag persists when PoGo is warm; the cache just lags it).

**THREE server-sync lessons (2026-05-29) — these caused the whole "constant struggle"; do NOT relearn them:**
1. **Tag REMOVALS persist only with a FRESH `create_tag` tagproto.** untag/delete via the *enumeration's* tagProto pointer (what `reconcile --fix-server --allow-untag` and the old delete path used) silently no-ops — `SetPokemonTags` returns ok but nothing changes. Feed `bulk_untag_one` a tagproto from `create_tag()` (returns the existing tag) + a live bag-walk member proto and it persists exactly like an add. `safe_nuke`'s DeleteTag also fails to drop the tag from the cache within its 3s guard → it aborts; delete+recreate-in-one-session is unreliable for the same cache reason. **Use `prune_tags.py`** (bidirectional exact-sync: add missing + remove extras, fresh-everything, set-equality verify).
2. **uid normalization — DB `uid_hex` is zero-padded to 16 chars; the bag-walk yields decimals.** Compare EVERYTHING as unpadded hex `format(int(x,16),'x')` (or pad both). 296 in-bag uids have a leading zero; comparing padded file strings to unpadded bag hex makes them phantom-drift (false "extra" + false "short") and a naive sync wrongly strips them. `apply_tagsets` is immune (it resolves via decimal `int(u,16)`).
3. **Tagging REALLOCATES a mon's PokemonProto** → any proto→uid map built BEFORE the writes goes stale for the freshly-tagged mons, so a same-session re-enumeration false-negatives them as "short" even though the write persisted. **Verify in a FRESH session** (`reconcile_tags.py --report`, which maps proto→padded-DB-uid independently) or re-walk the bag after writes. `prune_tags.py` now re-walks post-write.

**Philosophy — only tag what PoGo can't filter natively.** In-game bag search
already has one-tap filters for Shiny, Shadow, Purified, Lucky, Legendary,
Mythical, Hatched, Traded, Dynamax, Gigantamax, Adventure Effect, Location/Special
Background, Event, Can Evolve, Can Mega Evolve, Buddies — so custom tags for those
are REDUNDANT (they were all nuked 2026-05-28). Keep only tags native search can't
reproduce.

**Renaming (reliable):** rename **in-place via `TaggingRpcService.EditTag(PokemonTagProto editedTag, bool)`** — overwrite the name String* at `tagProto+0x40` with `il2cpp_string_new(...)`, then EditTag; the Id (+0x38) and all members are preserved → zero collateral, no empty-tag window (use this, NOT delete+recreate). Reference-type args to `il2cpp_runtime_invoke` pass the object pointer directly in the args slot; value-type args pass a pointer to the value. Tool: `system/scripts/rename_tags.py`. Past "reverts" were the FOREGROUND-WRITE no-op, not EditTag: run `ready_gate` (foreground) before renames and VERIFY IN A FRESH SESSION (a same-session enum reads the locally-overwritten proto → false success). Tag names longer than 15 chars persist on the server (16-char Shiny - Only One, 18-char Location Card #1-3 were live). Do not assume a 15-char limit; read get_TagNameCharacterLimit live if a limit matters.

**Guards from the 2026-05-29 audit:** (1) any trash/transfer/sort tag MUST be in `cull_v9.EXCLUDED_AUTO_TAGS` —
`cull_v9._user_tag()` treats every other auth_tag as a KEEP reason, so the Transfer tag once PROTECTED all 43 of its
members while the 199 genuine fodder sat untagged. (2) Proto parse-failures produce phantom `pid0` rows
(pokemon_id=0, all-zero, in_bag=1 — they read as fake nundos); `pogo_pipeline.step_reconcile_db` skips pid0 entries.
(3) `deep_profiles.json` is a derived view, not a source — regenerate it (`deep_profile.py`) after any crawl or tag
change.

**Reliable tag-op procedure (PoGo MUST be open+foregrounded; verify with pidof first):**
1. **ALWAYS re-crawl first** — `python pogo_pipeline.py`. Standing user rule (2026-05-28): the bag drifts fast (they catch between turns; saw 4463→4491→4518 in one session), so never analyze stale data. `check_freshness.py` is only to confirm/quantify drift, not a substitute.
2. Sync in the gated order: keep_policy → build_tagsets → preflight_transfer → prune_tags --atomic → set_db_tags_from_files (or dashboard `POST /api/sync`) → reconcile_tags --report. apply_tagsets / tag_ops apply / prune_server_tag are for non-pile tags only; Transfer goes only through preflight_transfer → prune_tags --atomic ([[pogo-pile-gate-2026-09]]).
3. Delete: `system/scripts/safe_nuke_tags.py` ONLY (one-at-a-time, collateral-verified). NEVER the old mass `_nuke_tags.py`.
4. Reconcile: `system/scripts/reconcile_tags.py --report` (read-only; uses live bag-walk protos) / `--fix-db`. Never run `--fix-server`: it has no pile check (no is_pile_tag / stamp check) and re-adds the DB-mirror members of every managed tag, Transfer included. Transfer is written only through step 2 (preflight_transfer → prune_tags --atomic).

**Master-collection triage:** `system/scripts/deep_profile.py` → `system/analysis/deep_profiles.json` gives every in-bag
mon one **purpose** (COLLECTION / PVP / MEGA / MAX / ADVENTURE / RESERVE / TRADE / TRANSFER) plus its nuances (flags,
pvp{rank,need_moves+TM-type,evolve_to}, opps with power-up XL/dust cost, mega_Level/Points, bread_mode, ae_left).
`python system/scripts/refresh.py` (re-crawl→deep_profile→reconcile→verify) then `python system/scripts/query.py <cmd>`
(stats / best gl|ul / powerup / evolve / lucky / purify / fodder / flag <X> / tag <name> / mon <species> / need-moves).
PVPoke move data cached locally: `_gm_pvpoke.json` (move pools + eliteMoves), `_gl1500.json`/`_ul2500.json`
(recommended movesets + scores).

**Captured per system:** Mega levels (`mega_Level` 1-4 ladder, `mega_Points` energy) · Adventure Effects (`adventure_effects_left`) · Dynamax/GMax MODE (`bread_mode` 1/2) · **Max/GMax MOVE LEVELS** — the `breadMoves_` RepeatedField @ PokemonProto+456 (`extract_bread_moves.py` → `bread_moves`/`bread_max_level` DB cols; deep_profile surfaces `MaxMoveL{n}` flag + `max_move_level` field; `query.py max [dyn|gmax]`). Layout in [[pogo-il2cpp-internals]].

**Workflow hardening:**
- **`reconcile_tags.py --fix-server` is not a sanctioned sync — don't run it (step 4).** Its add path has no pile check: it re-adds db_only (DB-mirror) members of every managed tag, Transfer included. Its untag path is off unless you pass `--allow-untag` (and stripping >50% of a tag also needs `--force-mass`) because reconcile once trusted DB as authority and untagged all 143 "1 GL IV" members when the DB was momentarily stale (a rename mirror had silently failed, so DB rows still said the old name → DB count read as 0 → "server_only=143" → mass-strip). Lesson: **server-only members almost always mean the DB mirror is stale, not that the tag is wrong** — never auto-strip on that signal.
- **keep_policy.py (caps from keep_config.json) is the keep/transfer engine.** cull_v9 survives only for doctor/sanity/deep_profile purposes, and a deep_profile purpose can disagree with the Transfer pile.
- **`refresh.py` precheck reuses `pogo_il2cpp._resolve_device()`** (Tailscale→USB fallback) so a Tailscale drop no longer false-aborts the refresh. Agent-built scripts that import `pogo_il2cpp` now insert the repo root on `sys.path` (e.g. `safe_nuke_tags.py`) so they run standalone.

See [[pogo-il2cpp-internals]] (tag/proto offsets, cache-lag, collateral), [[feedback-pogo-session-conduct]], [[pogo-source-of-truth-db-rules]].


## Displacement / collapse

**SHINY DISPLACES THE PLAIN FLOOR (2026-06-08, keep_policy rule 1b)** — user: *"figure out which shinies in kanto take
up a variant floor top 3 slot by IV"* + *"as long as the variant floor 3 spot they use is ONLY tagged for that reason
... it can go regardless of if its protected or not"*. The plain cap = the plain slots LEFT in the MERGED top-N of
`{truly-plain + non-hundo shinies}` by IV — a plain a higher-IV shiny pushes out loses `variant_floor`, and if that was
its ONLY keep reason → Transfer. **Hundos exempt; Unown keeps its own count-based carve-out.** A displaced plain that
ALSO has a real axis (PvP / Legacy / XXL) STAYS.
**SHINY DISPLACES THE COSMETIC-VARIANT FLOOR too (rule 1a `_var_eff_cap`):** a non-hundo shiny of the SAME cosmetic
variant (costume/art-bg/deco/Dynamax/Gmax) occupies a variant slot by IV (merge shiny+plain, plain slots left = cap); a
displaced plain → Transfer ONLY if `variant_floor` was its SOLE keep reason (a displaced variant kept by
legacy/origin/location_card/hundo STAYS). Shiny WINS IV ties (user approved transferring a tied-IV 89% Wailmer over its
same-IV shiny).
**SPECIALS DISPLACE THE PLAIN-JANE FLOOR too (rule 1b `_eff_cap`, user "any variant any shiny ... can take up a plain
pokemon's spot"):** the displacing pool = EVERY non-hundo SPECIAL of (pid,cf) — shiny OR cosmetic variant — each
occupies a plain-floor slot by IV (specials WIN ties); a plain pushed out and not rescued by the evolve comb-up →
Transfer. Shadow is NOT a displacer (stays its own axis); hundos exempt; Unown stays count-based.
**COLLAPSE GOES UP, NEVER DOWN ([[pogo-ultracode-audit-2026-06-09]]).** A TRUE PLAIN (empty `_domattr`) kept only by
`variant_floor` is dropped if a KEPT sibling of the same (pid, cf, gender-terminal) with a richer `_domattr` exists at
strictly higher IV (user, of even a 98% plain Sneasel when a better Dmax/shiny/costume exists: *"they only take up
slots"*). `_domattr` is the identity set {shiny, abg=<fresh_natural_art_bg>, loc=<card id>, cos/cosf=<costume id>,
dmax, gmax, shadow}. Specials never collapse (their own caps limit them); hundos and any real axis
(legacy/origin/pvp/location_card/rarity/xxl/mighty/AE/dex_only/...) never collapse. **HARD LESSON: I misread
"collapse" ~4 times (kept narrowing/second-guessing) -> user furious "pretend these are your pokemon jesus christ."
When the user states a value lattice, APPLY it; don't re-ask the scope.**
**A pile that suddenly reads 0** usually means the user RELEASED the prior pile + RECRAWLED — check the DB mtime/bag
count before assuming a pile change is an engine regression.
**SYNC NEEDS POGO'S BAG LOADED IN MEMORY:** a sync fired right after a PoGo restart reads a PARTIAL/empty box — symptom
is the push log showing ALL tags `server=0` + a big "`N uids not in bag`" (e.g. 1641) + `[atomic] applied 0/0 mons in 0
RPC(s)`. That's HARMLESS (it changes nothing — 0 applied, remove 0), NOT a wipe. Just RETRY once the bag has loaded
(Hundo/etc. reading their real counts = loaded).


## CRITICAL: "reconcile OK" is a CACHE read, NOT proof the tag reached the server (2026-07-25)
A sync reported `Transfer 480/480 OK` + `All tags in sync`, and the Transfer tag was **EMPTY on the
phone**. All 480 mons were still in the bag (nothing released) -- the WRITE NEVER PERSISTED server-side.
ROOT CAUSE: `reconcile_tags.py` enumerates members via `TaggingRpcService.GetCachedTagToPokemonBinding
ForIndex` -- the CLIENT CACHE. A tag write populates that same cache, so the post-sync verification can
bless a write the server never accepted. A method dump of TaggingRpcService shows **no NAMED server-fetch
method** (only GetCached*/GetAllTags(cache)/AddTagCacheUpdatedCallback; 22 obfuscated methods (bfbl..bfcg) were unresolved in the
2026-05-08 dump), so the ONLY honest verification is: **force-stop PoGo -> relaunch (client refetches tags from the
server) -> reconcile.**
TOOL: `verify_tags_live.py` (+ dashboard `POST /api/verify`) does exactly that and exits 1 on drift.
Re-applying the 480 then verifying through a cold restart returned 480/480 OK = genuinely persisted.
**RULE (user: "always check my live phone. youve already proven unreliable with your own memory/db"):
never tell the user a sync succeeded on the strength of the post-sync reconcile alone -- for the
Transfer tag especially, verify with a restart, or say plainly that it is a cache-level check.**
Suspected trigger for the non-persist: the largest single-tag batch (480 adds) in one atomic push;
apply_members batches at 100 with retries, and the re-apply logged "all 4 batch(es) OK".


## HUNDOS NEVER CONSUME A CAP SLOT -- enforced in the FLOOR pools, not just the displacers (2026-07-25)
The "hundos exempt" rule was only implemented in the DISPLACING pools (`_var_eff_cap`/`_eff_cap`), while
the hundo itself still sat in rule 1a `vg` and rule 1b `stage_pool` -- so it OCCUPIED one of the N cap
slots. Net effect: with a hundo in the family, a "top-3 plains" cap really only kept **2** ordinary
copies. User caught it on Turtonator (6 owned -> kept hundo + 2 plains + shiny, tagged a 96%):
"i thought we've established before that hundos never take up a slot....". FIX: skip `iv_total==45` when
building BOTH pools (rule 4 keeps every hundo unconditionally anyway) -- a pure rescue, 0 newly piled.
**NUNDOS EXEMPTED TOO (2026-07-25, user "yes exempt nundos too")** via a shared `_slot_exempt(r)` helper used by BOTH
floor pools, while `rules.nundo` is ON (with it OFF a nundo competes for a slot like any other plain). 2026-09-17:
nundo is no longer keep-all even with rules.nundo ON. Only one per look is kept (trophy_pick, caps.nundo=1); the
non-chosen duplicate nundos can go to the pile. PRINCIPLE: an unconditionally-kept trophy must never spend a capped
collection slot; if it does, the user's configured cap silently shrinks.

## tag_ops.py `apply` is ADD-ONLY -- the server tag must be PRUNED separately (2026-08-19)
`cmd_apply` pushes the DB's members onto the tag and never removes anyone. A mon that stops
qualifying keeps its server tag forever. Harmless on a label tag, DANGEROUS on `Transfer` (the
pile the user releases from by hand): a **legendary Groudon 82.2% (decision=KEEP, reason=legendary)**
was still on the server's Transfer tag after the DB had dropped it. Count-only checks miss this --
verify_tags compares COUNTS, and 154-vs-153 looks like rounding until you diff the membership.
`system/scripts/prune_server_tag.py <Tag> [--dry]` enumerates server members, diffs against the DB, names every stale
one, and removes them via `tag_ops.apply_changes(remove=[tagproto])` -- for non-pile tags only. Transfer goes only
through the gated order in the procedure above; `auto_tag.py`, a second ungated pile producer, is retired.
**Membership read:** binding list at `binding+0x18` (count @ list+0x18, items @ list+0x10); elements
are OBJECT REFS, not raw ulongs -- **the uid is at element+0x20** (verified 154/154 against pokemon.db).
Reading the element pointers themselves yields heap addresses with a uniform 0x240 stride: that is
the tell that you are reading refs, not ids.

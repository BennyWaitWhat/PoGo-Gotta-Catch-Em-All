---
name: reference-live-cosmetic-reads
description: "pokemon.db display_form/display_costume have NULL gaps -- read form/costume/shiny LIVE off PokemonDisplayProto, never the DB."
metadata: 
  node_type: memory
  type: reference
  originSessionId: 13477788-96d8-4172-8c7d-deee9a225a6b
  modified: 2026-09-21T03:31:54.744Z
---

# Live form/costume/shiny reads — the bag DB form columns are UNRELIABLE

The bag-crawl `pokemon.db` `display_form` / `display_costume` columns have NULL gaps (e.g. shiny Wash Rotom was stored with a null form, so a DB query reported "0 Wash Rotom" when the trainer had 3 shiny). **Do NOT trust the DB for form / costume / shiny questions.** Read live off the proto. (Burned twice on GO Fest Tokyo 2026; user (rightly) annoyed.)

## Authoritative offsets (verified 2026-05-30 binary, self-discovered by reflection)
- `PokemonProto`: `pokemonId_`@0x28, `pokemonDisplay_`@0xd8 → `PokemonDisplayProto*`.
- `PokemonDisplayProto`: `costume_`@0x10 (enum int), `shiny_`@0x18 (bool/U8), `form_`@0x1c (Form enum int).
- Don't hardcode across builds — reflect (`il2cpp_class_get_fields`/`field_get_offset`); the readers below do.

## Dumping the Form & Costume enums
- They are NOT nested in `PokemonDisplayProto` (its nested types are only `Types` + `<>c`). Resolve via the FIELD TYPE: `il2cpp_field_get_type(form_)` → `il2cpp_class_from_type` → dump static-literal fields (flags STATIC 0x10 & LITERAL 0x40, value via `il2cpp_field_static_get_value`). Form enum ~1,505 entries at 0.427.0 (it grows every build, so re-dump rather than assume a count); Costume 87.
- Verified form IDs: Tauros Paldea **Aqua=3008, Blaze=3007**, Kanto/Normal=1086; **RotomWash=85**, RotomFan=83, RotomNormal=81. GO Fest 2026 cosmetics are FORMS not costumes: `PikachuGofest2026Cap{Blue=Mystic, Red=Valor, Yellow=Instinct}`, `CaterpieGofest2026`.

## New game_read tools (system/scripts/game_read/)
- `deep_read.py` — full `PlayerStatsProto` counters (all milestone/medal numbers) + `PokedexImpl` completeness (`PokedexEntryProto`: TimesEncountered/TimesCaptured/CapturedShiny/EncounteredShiny/TimesLuckyReceived/TimesPurified — shiny-dex = CapturedShiny nz) + Dynamax bag scan (`breadMoves_`@0x1c8 count>0 = Max-leveled; "Bread"=Dynamax).
- `scan_gofest_audit.py` — live form+costume+shiny per species, mapped via the live enums (the reliable way to answer "do I have shiny X-form").
- `enum_forms.py` — Form enum → name resolver.

## Nickname clearing (clear_nicknames.py)
- `PokemonBagImpl.NicknamePokemon(proto, "")` clears a nickname → reverts to species name. `nickname_`@0xb8 on PokemonProto; leave `originalOwnerNickname_`@0x100 alone.
- **Server hard-throttles renames**: ~1000 burst then a slow trickle. Rate-limit-REJECTED clears LOOK cleared locally but ROLL BACK on a real server re-sync. Verify the committed count with a COLD app restart (force-stop+relaunch), not a bg/fg cycle (which under-reports). Don't hammer the throttle — finish in spaced bursts.

## Capture date / creation time (FIXED 2026-06-05)
`creationTimeMs_` **@0xa0 (i64)** on `PokemonProto` = the catch timestamp (ms). The offset did **NOT** drift (reflection-verified 0xa0 on the 2026-06-05 build). The real bug: the LIVE crawler `pogo_pipeline.parse_pokemon` + its INSERT/UPDATE had **never read the field at all**, so EVERY fresh catch landed with NULL `creation_time_ms`/`creation_date` (the old populated values came from RETIRED build scripts — build_final/to_sqlite/mem_scan/rebuild_full — that did read 0xa0). Symptom that bit me: "newest by `creation_time_ms`" returned STALE catches (max stuck at the last legacy-built date, 06-02), so I mis-reported old shinies as "new catches" and guessed nonexistent league-#1s — the user (rightly) furious. **FIX:** `parse_pokemon` now reads `i64(bs, 0xa0)` (POGO_LAUNCH floor rejects 0/garbage) + a COALESCE-fill loop right after the gender patch writes `creation_time_ms`/`creation_date` for every parsed mon (COALESCE so a transient bad read never clobbers a good immutable value). Backfilled the existing 4643 once via a live REFLECTION read (`reflectScalars` → find `creationTimeMs_` offset → read i64); **0 NULL after**, recrawl confirms fresh catches stamp correctly. `creation_time_ms`/`creation_date` are METADATA (not keep criteria) → zero tag impact. **LESSON:** when a column is NULL for RECENT rows but populated for OLD ones, suspect the live pipeline DROPPED the read (or a legacy script had populated it) — do NOT assume "offset drift." Reflect the offset + read live to confirm before theorizing. The reliable "what did I catch recently / new league-#1s" query is now `creation_date` (per-mon, real) — never a guess.

## Mega level / points (FIXED 2026-06-05, same class of bug)
`PokemonMegaEvolutionLevelProto` — the sub-proto at `PokemonDisplayProto`+0x50 (i.e. `proto`+0xd8 → dispPtr, dispPtr+0x50 → mega ptr): **`Points`@0x10 (i64), `Level`@0x18 (i32)** (reflection-verified). The crawler ALREADY dumps this object's first 0x40 bytes as `megaBytes` (pogo_pipeline bag-walk JS) but only used it as a has-mega BOOLEAN (`fresh_has_mega_level`) — it NEVER parsed Level/Points out, so `mega_Level`/`mega_Points` were stale (last set by a retired one-off script; **9 mons wrong** — e.g. Gengar/Tyranitar had climbed to L3 since). **FIX:** `parse_pokemon` now reads `i32(mega_bs, 0x18)` (level) + `i64(mega_bs, 0x10)` (points) from `megaBytes`, plus a SET loop (**NOT** COALESCE — mega level CLIMBS 1→2→3 as you evolve, so overwrite when mega data is present; gate `1<=level<=3`). Backfilled 142 live. Distro 2026-06-05: L1:89 · L2:49 · L3:4 (Garchomp/Lucario/Gengar/Tyranitar maxed). `mega_Level` is METADATA (not a keep criterion) → zero tag impact. **SAME lesson as capture dates: the live pipeline omitted a field that was already in the dumped bytes.** When a column looks stale/NULL, first check whether `parse_pokemon` actually parses it out of the bytes it already has — don't assume the offset drifted or the data's missing.

## Completeness audit — EVERY keep-criterion field must parse LIVE (2026-06-05)
After capture-date + mega were both found stale, I reflected **ALL 96 PokemonProto + 27 PokemonDisplayProto scalar fields** (`il2cpp_class_get_fields`) and diffed vs `parse_pokemon`. Two more keep-criterion fields were stale (set only by a retired one-off script, never auto-refreshed):
- **`was_best_buddy_badge`** (Best Buddy tag) = `PokemonDisplayProto.PokemonBadge`@0x28 **== 1** (the only badge value in use; all 18 best-buddies have it). The pipeline read the badge into `fresh_pokemon_badge` but never derived this. FIX: `was_best_buddy_badge = 1 if badge==1 else 0` + a SET loop.
- **`original_owner_name`/`original_owner_nickname`** (Traded-by-E+F tag) = `PokemonProto.originalOwnerNickname_`@0x100 (C# string, e.g. EthanMateoVZ / Florandez). The pipeline dumped proto bytes but never read this STRING. FIX: bag-walk JS reads it (`onP.add(0x14).readUtf16String(len)`, len@0x10 — same C# string layout as the tag-name reads) → parse_pokemon stores it + a SET-when-present loop.
- **`adventure_effects_left`**: NOT a gap — the adventure_effect keep is roster-backed (`AE_IDS` pid set), so a stale column can't break it.
Verified by recrawl: best-buddy 18, owner 89 (28 E+F), matching the retired-script values exactly. PvP viability gate = maxcp > cap + `viability_margin`; keep_config.json has it at 0 by the user's deliberate choice since 2026-06-10, re-affirmed by the 2026-09-08 research. `keep_config.DEFAULTS` still says 100, so read `keep_config.pvp()`, never DEFAULTS.
**META-LESSON (4 gaps this session: capture-date, mega, best-buddy, owner): `pogo_pipeline.parse_pokemon` is the SINGLE source that must parse EVERY keep-criterion field — columns populated only by retired one-off scripts go stale silently and the bag-crawl never notices. To audit completeness, reflect ALL proto fields and diff against parse_pokemon's reads. (PokemonProto = 96 scalar fields, PokemonDisplayProto = 27, offsets dumped 2026-06-05.)**

## Partial-walk symptom after a PoGo restart (2026-06-05)
A recrawl right after PoGo RESTARTS can return a LOW bag count (saw **951 of ~4820**) with **NULL capture dates on ALL of them** — PoGo streams its bag from the server progressively and the protos aren't fully populated yet (`creationTimeMs_`@0xa0 reads 0). **This is NOT a parse bug — it's a half-loaded bag.** The pipeline's safeguards held perfectly: `step_reconcile_db`'s <70%-of-prior-bag gate blocked the 2-crawl-confirm purge (no deletions), and `prune_tags` printed "still not equal / Drift detected" and refused to strip the server tags. **RECOVERY:** wait for a live `pg.walk_bag_protos` count to return the full bag, then re-crawl — it re-marks the wrongly-in_bag=0 mons back to in_bag=1 and recomputes correct tags. **TELL:** a low bag count + mass-NULL capture dates = PoGo mid-reload; verify the live walk count before trusting or syncing a post-restart crawl. (PoGo churns pids often this session — the Android freezer / gadget behavior in [[pogo-frida-stability]].)

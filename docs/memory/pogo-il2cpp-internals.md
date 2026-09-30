---
name: pogo-il2cpp-internals
description: "Hard-won PoGo IL2CPP/Frida facts — Form enum location, evolution preserves proto ptr, bag-walk for proto resolution, MapField layout, JNI-vtable BLE sniffing."
metadata: 
  node_type: memory
  type: reference
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
---

Durable IL2CPP/Frida facts for PoGo internals (the working scripts in `pogo_extract` are the reference implementations):

- **Form enum**: the PokémonForm enum (~1,500 entries with sparse values up to ~3,380, e.g. 2745=ScatterbugArchipelago) is a class literally named `Form` in the **empty namespace** in `holo-protos.dll` — NOT `PokemonForm`/`HoloPokemonForm` (those don't exist or resolve to an unrelated 2-entry class). Find it by iterating image classes by name (`il2cpp_image_get_class_count`/`_get_class`), not `il2cpp_class_from_name` with a guessed namespace. See `dump_pokemon_form.py`.

- **Evolution preserves the PokemonProto pointer but assigns a NEW UID.** On evolve, PoGo mutates the existing `PokemonProto` in place (pokemon_id/form/stats change) but the `PokemonBagImpl.AllPokemon` LinkedHashMap gives it a new UID. Tag bindings store raw proto pointers (in the binding's `+0x18` `List<PokemonProto*>`), so tags carry over; but UID-keyed DB rows for the old UID become ghosts (`in_bag=0`). When refreshing tag state, re-walk the bag to rebuild proto-ptr→UID FIRST, then map binding pointers through that fresh map; old UIDs of recently-evolved mons won't appear — don't error on them.

- **Resolve protos via the bag walk, not the heap-scan index.** `bulk_tag.js index_pokemon()` only sees the materialized proto heap (~3200 of ~4600) — PoGo only materializes storage you've scrolled past, and a fresh restart empties it (resolved 0/13 protos cold). The bag walk (`get_AllPokemon` LinkedHashMap, `pogo_il2cpp.find_protos_for_uids`) sees every Pokémon regardless of scroll/restart state. Default all tag/untag proto resolution to the bag walk; reserve `index_pokemon` for when storage is known-warm.

- **`Niantic.Protobuf.Collections.MapField<K,V>` layout** (verified): +0x10 ValueEqualityComparer, **+0x18 list** (`LinkedList<KVP<K,V>>`), +0x20 KeyEqualityComparer, +0x28 map (Dictionary). The list at +0x18: head@+0x10, count@+0x18. `LinkedListNode<KVP>`: next@+0x18, key@+0x28 (String*), value@+0x30. (The field-list-dump ordering misleadingly suggested +0x28 for the list.)

- **`PokedexEntryProto.PokedexCategoryStatus` MapField is SPECIES-LEVEL, not per-form.** Keys are CATEGORY-NAME strings (verified live 2026-05-27): `SHINY`, `THREE_STAR`, `FOUR_STAR` (hundo), `SHADOW`, `PURIFIED`, `LUCKY`, `COSTUME`, `BREAD_MODE` (= Dynamax, cat=18), `BREAD_DOUGH_MODE` (= Gigantamax, cat=19), `SHINY_THREE_STAR`, `SHINY_FOUR_STAR`, `SIZE_XXS`, `SIZE_XXL`. ONE entry per category per pid; an `acq=1` on `SHINY` means "ever owned a shiny of this species" (any form). **Form-aware tracking lives in the per-region dicts** (nine regional dicts at +0x18..+0x58 on PokedexImpl; obfuscated names change per build: `cugs..cuha` on 2026-05-27, `cwdc..cwdk` on 0.427.0; address them by offset) — each regional dict holds an entry per pid only for forms native to that region (Kantonian Vulpix in Kanto's dict, Alolan Vulpix in Alola's dict, both sharing pid=37 but distinct entries with their own category flags). The All-dict at +0x10 is the union (any-form acquired). For species-level questions ("missing shinies overall") use All; for per-form ("missing Alolan Ninetales shiny") use the regional dict. See `_dex_deep_read.py`.

- **Enum values are non-sequential.** `il2cpp_class_get_fields` lists static literal field NAMES in declaration order, but their VALUES are not sequential — always read actual values with `il2cpp_field_static_get_value`.

- **BLE sniffing without the Java bridge** (frida-gadget via ZygiskFrida has no `Java`): hook `pgp::android::AndroidCharacteristic::nativeSaveValueChangedCallback(JNIEnv*, jobject, jbyteArray)` in `libholoholo.so` for inbound BLE bytes. Read the `jbyteArray` via the JNIEnv vtable directly — `GetArrayLength` @ index 171, `GetByteArrayElements` @ index 184, `ReleaseByteArrayElements` @ index 192 (offsets stable on Android 8+). Keep hooks under ~10 per session (40+ crashes the gadget); wrap attach+hook in a `pidof`-polling reconnect loop.

- **Level = cp_multiplier (proto +0x7c) + additional_cpm (proto +0xac).** PoGo splits the CPM across TWO float fields; the true level is `cpm_to_level(f32(0x7c) + f32(0xac))`. Reading only 0x7c gives a wildly-low level for powered-up mons (a maxed L50 Metagross decoded as L6). Fresh/unpowered catches have `additional_cpm≈0` so 0x7c-alone *happens* to work — which masks the bug on new catches and makes it look fine. `pogo_pipeline.parse_pokemon` is fixed to sum both; the DB `cp_multiplier` column is the base only and is NULL for freshly-INSERTed UIDs, so recompute level from the live proto sum, not from DB columns.

- **Multi-stat forms — verified IDs (never hardcode from memory; derive from `form_category.json` or the live enum):** Zacian 2576=CrownedSword / 2577=Hero · Zamazenta 2578=CrownedShield / 2579=Hero · Kyurem 146=Normal / 147=Black / 148=White · Necrozma 2717=Normal / 2718=DuskMane / 2719=DawnWings · Palkia 1859=Normal / 2830=Origin · Dialga 1856=Normal / 2829=Origin · Moltres 2799=Galarian · Ninetales 57=Kantonian / 58=Alolan · Meloetta 151=Aria. I had Crowned/Hero and Kyurem Black/White swapped from memory and it broke an entire ML analysis — always look the form id up.

- **`costume_decoration_id` is a TEXT column (`'0'`,`'11'`,…), not int.** `x != 0` is always true on it (str vs int) — it once flagged all 4463 mons as costumed. Use the int column `fresh_costume` for "has a costume".

- **Tag writes: `built==N` / `ok:true` ≠ persisted-and-visible.** `bulk_tag_many` / `AddTag` succeed server-side but the in-process `GetCachedTagToPokemonBindingForIndex` cache lags, and `AddTag` outright *fails* in the first ~seconds after an app restart (warm-up). So verify tag writes with a FRESH attach after a delay, not a same-session re-read, and retry creates with backoff. **Mass `DeleteTag` in a tight loop reads stale/reused tagProto pointers → COLLATERAL deletes** (it silently nuked the `Mega` tag and emptied `Costume`). Delete ONE tag, re-enumerate, verify every *other* tag's member count is unchanged, then proceed — `system/scripts/safe_nuke_tags.py` does exactly this. For any server tag WRITE use a fresh bag-walk proto, never a cached binding proto (those go stale → NullReferenceException).

Relates to [[pogo-pokedex-lifetime-not-bag]], [[pogo-frida-stability]], [[project-pogo-extract]], [[pogo-tag-system-2026]].

## PERFECT THROW -- CatchPokemonProto offsets + the reticle convention (2026-08-20)
Implemented Pokemod's "Perfect Throw" by rewriting the OUTGOING request in the existing
`CatchPokemonProto.WriteTo`/`_InternalSerialize` hook. That hook fires for the USER'S MANUAL throws
as well as the catcher's, which is what makes manual-encounter perfect throws possible at all.
It runs on the GAME thread during the RPC send -> no cross-thread il2cpp exposure.
**CatchPokemonProto offsets (0.421.0):** encounterId@0x10 (u64), pokeball@0x18 (s32),
**normalized_reticle_size@0x20 (DOUBLE)**, spawnPointGuid@0x28 (ptr), **hit_pokemon@0x30 (u8)**,
**spin_modifier@0x38 (DOUBLE)**, **normalized_hit_position@0x40 (DOUBLE)**, sflee@0x50 (u8).
**THE CONVENTION (verified, do not guess -- there are two contradictory ones in the wild):**
normalized_reticle_size runs **1.0 -> 2.0 where HIGHER = tighter circle**; Excellent is >1.7.
Proof: a real captured throw read **1.931**. Perfect Throw writes 1.90 + rand*0.08, spin_modifier
1.0 (curveball), hit 1, hit_position 1.0. REQ[] is recorded AFTER the rewrite so the log proves what
the server received.
**DO NOT CONFUSE** this with the client-side `PokeballThrow` struct the catcher fills for
TryCapture: BallType@0x10, **ReticleSize@0x14 where the catcher writes 0.02-0.12 (SMALLER = better)**,
HitBullseye@0x18, Spinning@0x19, Missed@0x1a. The game converts one to the other (~0.069 -> 1.931).
Toggle: flag `/data/local/tmp/pogo_perfect.on` + `catcher_ctl.sh perfect-on|perfect-off`;
`set_perfect` is flag-only so it is safe on the RPC thread. stats() exposes perfect / perfwant / pterr / ptc (PTC = {ns, bull, inv, scpa, wrote}); the desktop copy also has perfproto.
Perfect Throw in Pokemod is really FOUR things -- only throw-quality is done here; "recovers missed
balls", "stops the Pokemon dodging/attacking", and the AR+ bonus are separate mechanisms.

## PERFECT THROW -- CORRECTED: it is CLIENT-SIDE hooks, not a proto rewrite (2026-08-20)
My first attempt rewrote `normalized_reticle_size` in the outgoing CatchPokemonProto. **That is the
wrong mechanism** and the user called it out: it changes only what the server is told, never shows
"Excellent!" on screen, and does nothing for a ball that misses entirely (no request is even sent).
**Pokemod's agent bundle is already extracted at `system/analysis/pokemod/agent_js_0x*.js` (3.5MB,
browserify) -- READ IT instead of guessing.** Their module is class **`PerfectedThrow`** (note the
"ed"; searching "PerfectThrow" finds nothing). Its real hooks:
  - `Niantic.Holoholo.Encounter.EncounterPokemon.SetCanPerformActions` attach, force arg = false
    -> the Pokemon cannot attack, move or jump
  - `EncounterPokemon.get_Invulnerable` replace -> false
  - `Niantic.Holoholo.Encounter.Reticle.get_NormalizedSize` replace -> **`0.13*Math.random()`**
  - `Reticle.ScreenPositionOverBullseye` replace -> true   **(takes 1 PARAM, not 0)**
  - `Pokeball.Initialize` replace -> rebind `HitGround`/`HitKillZone` to a System.Action that calls
    `SetActive(true)` (+ bumps `<RaidBallCount>k__BackingField`) == "missed balls are recovered"
  - `CatchPokemonProto.CalculateSize` attach -> `this.SpinModifier=1` and `this.ArPlusValues =
    ARPlusEncounterValuesProto{Proximity: 0.45-0.50, Awareness: 0, PokemonFrightened: false}` == the
    AR+ XP bonus
  - `Headshot` is a SEPARATE module that PerfectedThrow enables alongside itself
**Threshold confirmation:** their amateur-mode constants are `2-1.7`, `2-1.3`, `2-1`, which proves
the client getter is INVERTED from the proto: client `0.13` -> proto `1.87`; Excellent boundary is
client 0.3 / proto 1.7. This matches the captured live throw of 1.931.
**Implemented in catch_loop_fast.py:** the first four hooks (`perfectResolve` / `perfectApply`,
applied from the PUMP so the RPC export stays flag-only). Ball recovery and AR+ are NOT implemented
(delegate creation + managed allocation). `get_NormalizedSize` returns a FLOAT -- on arm64 that is in
v0 and an onLeave retval CANNOT change it, so it must be `Interceptor.replace` + NativeCallback.
**Gotcha that hid the bug:** `il2cpp_class_get_method_from_name` needs an EXACT param count, so the
arity-0 lookup silently missed ScreenPositionOverBullseye and my all-four gate then disabled the
whole feature while the toggle still read ON. Added `mByName()` (walks one class's methods, any
arity) and made application per-hook. The log now prints
`PERFECT applied=N want=N hooks[...]` every cycle -- verified `applied=1` with all four true.

## PERFECT THROW / HEADSHOT -- the three bugs that cost an evening (2026-08-20)
1. **I FROZE THE GAME.** An il2cpp AOT method's native signature has a hidden TRAILING
   `const MethodInfo*`: `float get_NormalizedSize(Reticle* this, const MethodInfo*)`. My
   NativeCallbacks declared only `["pointer"]`, so every `Interceptor.replace` had a mismatched
   calling convention and PoGo hung with its render loop stuck (CPU fell to ~13%; healthy is ~190%).
   **Rule: include the trailing MethodInfo pointer, and prefer `attach`+`onLeave retval.replace()`
   for BOOL/int returns (x0, rewritable, no signature needed). Only a FLOAT return forces a
   `replace` -- on arm64 it comes back in v0 where retval cannot reach it.**
2. **`findClass()` is O(all classes in image)** and I called it up to 8x inside `install()`. That
   pushed install past Frida's RPC timeout -> "link drop: timeout was reached" on every attach, and
   the catcher never got going. Added `findClasses(image,[names])` (ONE walk, many names) and moved
   both resolvers OFF the RPC path into the pump (`PT_RESOLVED` guard in tick()). Attach is fast
   again. This is the same rule as everywhere else: heavy il2cpp belongs on the game thread.
3. **`il2cpp_class_get_fields` returns only a class's OWN fields.** Every own field of `Pokeball` on
   0.421.0 is an Int32/String/event, so `reticle` kept resolving to -1. It lives on a BASE class --
   walk the hierarchy with `il2cpp_class_get_parent` and match on the field's TYPE (names are
   obfuscated as dodk/dodl/doer/does and Pokemod's own name map is from an older build, so it does
   not apply). **Verified offsets on Pokeball's hierarchy (0.421.0):
   reticle @568 (`doer` : Niantic.Holoholo.Encounter.IReticle),
   pokemon @576 (`does` : Niantic.Holoholo.Encounter.IEncounterPokemon),
   `<BallType>k__BackingField` @868.**
**`Pokeball.Launch` fires only on MANUAL throws.** The auto-catcher's `TryCapture` path is headless
-- no Pokeball GameObject is created -- so the Headshot aim-lock counter stays 0 no matter how many
the catcher catches. Testing it REQUIRES a hand-thrown ball.
**Self-healing added:** `system/ondevice_toggle/watchdog.sh` (external supervisor: if catch_loop.log
goes quiet >240s while any feature flag is on -- STALE=240, checked every 30s; 100s caused a restart
loop -- tear down and re-attach) plus `rpc.exports.panicRevert`
+ a frame-stall check in the report loop that force-disables Perfect Throw if FRAME stops advancing.
The wedge it exists for: Frida's JS engine is single-threaded, so a busy pump starves RPC and the
Python side blocks forever in `futex_wait_queue` at 0% CPU while still holding the gadget -- looks
"up" from outside, does nothing.

## HEADSHOT: DO NOT reposition the ball (2026-08-21)
Pokemod's Headshot Lerps the Pokeball 90% toward the reticle at `Launch`. Reproducing that here
BROKE throws twice: the ball ended up somewhere that was not the Pokemon, `forged` (OnCollisionEnter
count) read 3 per throw = the ball bouncing on the GROUND, and on screen the ball sat inert at the
Pokemon's feet with the encounter dead. `IReticle.get_Transform()` evidently does not point where
the naive reading assumes. **The Launch hook now ONLY resolves the collider id; throw physics are
left untouched.** Do not re-enable repositioning without first proving where that transform is.
**Measured collision layout (0.421.0):** `Collision{m_Header@16, m_Pair@56:ContactPair, m_Flipped@96,
m_LegacyContacts@104}`, `ContactPair{m_ColliderID@16, m_OtherColliderID@20, m_StartPtr@24, ...}`.
Value-type field offsets are HEADER-INCLUSIVE (first instance field is @16, not @0), so inside the
embedded struct m_OtherColliderID is at 20-16=4 -> **absolute `collision + 60`**.
Collider id chain (works, returns e.g. -453982): `pokeball.pokemon`(@576) -> `get_GameObject()` ->
`GetComponentInChildren(typeof(Collider))` -> `GetInstanceID()`; needs `il2cpp_class_get_type` +
`il2cpp_type_get_object` to build the System.Type argument.
**What IS verified working:** reticle/bullseye/invulnerable/SetCanPerformActions hooks all fire, and
a hand-thrown ball produces `ret=1.929 [EXCELLENT] spin=1 hit=1 hpos=1` at the proto. What is NOT
solved: making a genuine MISS count as a hit.

## PERFECT THROW: ship the throw-quality half ONLY. Both Headshot hooks are HARMFUL here (2026-08-21)
Three consecutive broken encounters, each on live play, each requiring a force-restart:
1. Aim-lock at `IReticle.get_Transform()` -> ball landed short (3 ground contacts/throw).
2. Aim-lock at the Pokemon's GameObject transform -> **`aimTo=0,0,0`**: the encounter scene does NOT
   expose usable WORLD coordinates, so set_position threw the ball at the world origin.
3. Collision forge alone (writing the Pokemon's collider id into Collision.m_Pair) -> the ball lands,
   **the capture sequence never starts, and the encounter hangs with its ENTIRE UI gone** (no ball,
   no berry, no Run; BACK does nothing; only `am force-stop` recovers it).
**Conclusion: forging a hit for a ball that is not actually on the Pokemon corrupts the encounter.**
Pokemod can forge because their Launch hook genuinely relocates the ball first; without a working
relocation the forge is strictly worse than a miss. BOTH are now disabled behind comments.
**WHAT SHIPS AND WORKS (verified on hand-thrown balls):** `Reticle.get_NormalizedSize`->0.13*rand,
`Reticle.ScreenPositionOverBullseye`->true, `EncounterPokemon.get_Invulnerable`->false,
`SetCanPerformActions(arg=false)`, plus `spin_modifier=1.0` written to the outgoing proto.
Result: `ret=1.929 [EXCELLENT] spin=1 hit=1 hpos=1` on a ball that genuinely connects.
**NOT SOLVED: making a real MISS count.** That needs the ball actually moved onto the Pokemon, which
needs the encounter's real coordinate space -- do NOT retry it on the user's live game.

## STOP: client-side Perfect Throw hooks HANG the encounter. Proto-only is the safe build.
2026-08-21. FOUR hung encounters on the user's LIVE game, each needing `am force-stop` (BACK does
nothing, the encounter loses its ENTIRE UI -- no ball, no berry, no Run). Every client-side hook I
tried is implicated, not just the obvious ones:
  - Pokeball.Launch reposition (reticle target)      -> ball short, 3 ground contacts
  - Pokeball.Launch reposition (GameObject target)   -> aimTo=0,0,0 (no usable world coords)
  - OnCollisionEnter forge (m_OtherColliderID)       -> capture sequence never starts
  - Reticle.ScreenPositionOverBullseye=true + EncounterPokemon.get_Invulnerable=false +
    SetCanPerformActions(false)                      -> STILL hangs with the above disabled
**Common cause: every one of these asserts GEOMETRY the physics contradicts.** Pokemod can do it
because their Launch hook genuinely relocates the ball first, making the assertions true. Without a
working relocation they are lies, and the capture state machine stalls.
**SHIP THIS INSTEAD -- proto-only, in the CatchPokemonProto WriteTo hook, never hung anything:**
  +0x20 normalized_reticle_size = 1.90+rand*0.08 (Excellent is >1.7)
  +0x30 hit_pokemon = 1
  +0x38 spin_modifier = 1.0 (curveball)
  +0x40 normalized_hit_position = 1.0
The SERVER computes the throw bonus from these, so the catch-rate/XP benefit is real; the only thing
lost is the on-screen ring text. **PROCESS LESSON: I tested each hypothesis on the user's live
encounters and broke the game four times. Anything that can hang an encounter must be proven
somewhere else first -- and after the SECOND failure the correct move was to stop and ship the safe
variant, not to keep iterating on their session.**

## ITEM RECYCLING WORKS -- construct ItemData exactly as Pokemod's MagicBag does (2026-08-21)
`ItemBagImpl.RecycleItem(ItemInventoryItemWidget/ItemData, Int32, ISet<Item>)` -- the FIRST arg is a
UI data OBJECT, not an item id, and a scan for methods returning RecycleItemOutProto proves there is
no plain (id,count) entry point. Pokemod's `MagicBag.itemRecycler` shows the recipe:
    const exp = ExpirationData.$new(); exp.ExpireTime = 0;
    const data = ItemData.$new(itemId, 0, 0, currentCount, false, true, false, null, 0, exp);
    ItemBag.RecycleItem(data, discardCount, null)      // 3rd arg is simply NULL
Raw il2cpp: `il2cpp_object_new(ItemData)` + invoke its 10-arg `.ctor` (ints/bools passed as pointers
to int32/uint8, object args as ptr(0)), same for ExpirationData with ExpireTime=0.
**Verified 2026-08-21:** freed 771 items, bag 3684 (OVER the 3650 cap) -> 2974, headroom 676.
Poke 1623->1200, Ultra 341->300, MaxPotion 218->100, MaxRevive 250->150, Pinap 209->120.
**ITEM IDS -- Silver Pinap is 708 (`GoldenPinapBerry`), NOT 707.** I had protected 707; the real id
survived only because KEEP_TO is an ALLOWLIST and 708 was never in it. Luck, not the guard -- which
is exactly why the allowlist design matters. Berries: 701 Razz, 703 Nanab, 705 Pinap, 706 GoldenRazz,
708 GoldenPinap(=Silver Pinap), 709 Poffin. Tool: `system/scripts/game_write/item_cleanup.py`
(dry-run default, `--commit` to apply).

## Pokeball field layout + the RIGHT way to resolve classes (2026-08-21)
**Resolve classes the way Pokemod's `use("Niantic.Holoholo.Encounter.Reticle")` does: by FULL
NAMESPACE + NAME via `il2cpp_class_from_name`.** `pogo_il2cpp.py`'s preamble already exposes
`cFN(ns, cls)` for exactly this. Searching for a bare class name across images was my own invention,
is O(all classes), and can bind a same-named decoy.
Frida 17 note: `Module.findExportByName` does NOT exist -- use
`Process.findModuleByName("libil2cpp.so").enumerateExports()`.
**Niantic.Holoholo.Encounter.Pokeball -- own fields, all `System.Action` and WRITABLE (0.421.0):**
OutOfPokeballs@32, Spawned@40, DragBegun@48, DragEnded@56, Thrown@64(Action<Item>), **Missed@72**,
**HitPokemon@80**, **HitGround@88**, **HitKillZone@96**, Dropped@104, Deactivated@112,
FledAfterMiss@120, PokemonBreakingOut@128, PokemonBrokeOut@136, PokemonCaught@144, OutOfScope@152,
ThrownDebug@160, animator@168, effects@176, body@184(Rigidbody), sphereCollider@192,
pokeballThrowProperties@208, dodu@376(LazyInject<IEncounterInteractionState>),
dodv@384(LazyInject<IEncounterState>).
`reticle`/`pokemon` are NOT own fields -- they are on a base class (doer@568:IReticle,
does@576:IEncounterPokemon).
Probe tool: `system/scripts/game_read/probe_pokeball.py` (read-only).
**Working hypothesis for the hangs:** `ScreenPositionOverBullseye`->true makes the game take its
HIT path when the ball is actually on the ground, stalling the capture. `get_NormalizedSize` only
scales throw QUALITY and asserts nothing about position, so it is the one client hook that cannot
contradict physics -- now enabled ALONE as a single-variable test.

## FINAL VERDICT on client-side Perfect Throw: NOT POSSIBLE here. Proto-only is the answer.
2026-08-21, after SIX attempts, each tested on the user's live game (which was itself the process
mistake -- see the earlier note):
  1. Launch reposition @ IReticle transform      -> ball short, 3 ground contacts, encounter dead
  2. Launch reposition @ Pokemon GameObject      -> aimTo=**0,0,0**; encounter exposes no usable
                                                    WORLD coordinates, so the ball goes to origin
  3. OnCollisionEnter contact forge              -> capture never starts, encounter UI entirely gone
  4. bullseye + invulnerable + SetCanPerformActions -> same hang with 1-3 disabled
  5. get_NormalizedSize ALONE                    -> **CRASHED PoGo** (tombstone 2026-08-21 01:32:40)
       `StackVisitor::WalkStack -> Thread::VisitRoots -> MarkCompact::CheckpointMarkThreadRoots`
**#5 is the decisive one and it is not a logic bug.** A Frida `NativeCallback` installed on a hot
ENCOUNTER method leaves Frida trampolines on a GAME thread's stack; ART's compacting GC then faults
walking it. Same cross-thread GC vector as the RPC-thread crashes, reached from the other side.
Getting the hook "more correct" cannot avoid it. Pokemod does not hit this because its agent is
in-process and does not use Frida trampolines.
**Also measured: `FIRED{ns:0}` -- the game barely calls get_NormalizedSize on 0.421.0**, so even a
crash-free hook there would buy little.
**SHIPPED: proto-only**, written in the CatchPokemonProto WriteTo hook (game thread, during the RPC
send, no trampoline on a hot path): reticle 1.90+rand*0.08, hit=1, spin=1.0, hit_position=1.0.
VERIFIED `ret=1.903 [EXCELLENT] spin=1 hit=1 hpos=1` WITH ns never firing -- i.e. the benefit comes
entirely from the proto. The server computes the throw bonus from these fields, so catch rate and XP
are genuinely improved; the ONLY thing missing is the on-screen "Excellent!" text.

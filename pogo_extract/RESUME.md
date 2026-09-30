# Resume notes - Pokemon GO storage cull / tag project

State as of last session. Pick up here next time.

## What's locked in

### Cull rules (final, user-confirmed)
Universal ruleset, applied per-pokemon. **A pokemon is KEPT if any rule says keep; transferred only if no rule applies.**

**Untouchables:**
- hundo / nundo / lucky / best buddy / shadow / purified
- powered up (any dust invested past catch level)
- traded
- mega evolved
- has postcard / location background
- has adventure-effect uses remaining
- deployed in gym
- legendary / mythical / ultra-beast / paradox species
- adventure-effect species (Calyrex, Necrozma, Crowned)
- has legacy / event-exclusive move
- has seasonal costume decoration
- size XXS or size XL/XXL (jumbos and tinies)
- has user tag (only 5 known so far, full set pending)

**Capped:**
- top 10 shinies per species by IV%
- top 3 per (species, form) by IV%

### Final cull plan
- 5,413 total → **4,555 keep / 858 transfer**
- File: `cull_plan.csv` (per-pokemon decision + reason)
- Top transfer pools: Pikachu 66 / Unown 35 / Magikarp 17 / Ditto 18

### Tag plan
- File: `desired_tags.csv` (per-pokemon tag list)
- New tags designed: TX, TOP3, JUMBO, TINY, LEGACY, POSTCARD, BUDDY, POWERED, ADVENTURE, LEGENDARY, MYTHICAL, UB, PARADOX
- Existing user tags reused: Hundos, Nundos, Traded, Mega, MegaHundos
- Constraint: PoGo limits 14 tags/pokemon, 100 pokemon/tag → some categories need splitting (TX1...TX9, TOP3 chunks)

## Working recipe to inject into PoGo (the breakthrough)

Vanilla `frida-server` attaches successfully **with this exact sequence**, no Pokemod renames needed:

```
adb shell su -c '
am force-stop com.nianticlabs.pokemongo
setenforce 0
nohup /data/local/tmp/frida-server >/dev/null 2>&1 &
sleep 1
am start -n com.nianticlabs.pokemongo/com.nianticproject.holoholo.libholoholo.unity.UnityMainActivity
sleep 5
'
# THEN: ONE attach. NO retries, NO second attach.
python -c "import frida; s = frida.get_usb_device().attach(pid); ..."
```

**Critical constraints:**
- `setenforce 0` (SELinux permissive) is required - libconceal's ptrace hooks pass through this hole
- Single attach per PoGo launch. Second attach times out (libconceal activates after a few seconds).
- Fresh launch each time. Can't attach to already-running PoGo reliably.

This means: **one big script that does ALL operations in a single attach session.**

## Backup path: /proc/PID/mem direct write

Empirically proven: ARM64 kernel allows root to write to /proc/PID/mem even on r-x pages (FOLL_FORCE bypasses VMA protection, I-cache flushed automatically). Code injection without ptrace is possible if Frida path fails.

Documented in `mem_write_codeexec_research.md`. Backup only - Frida path is cleaner.

## Pending work to actually execute the cull

1. **Verify IL2CPP state in current PoGo.** Agent 1 reported `libil2cpp.so` not loaded ("no IL2CPP/Unity"). Earlier extraction worked WITH IL2CPP. Either Niantic restructured or agent saw PoGo pre-load. Check `grep il2cpp /proc/$(pidof com.nianticlabs.pokemongo)/maps` after the recipe above.

2. **Find the actual function names.** If IL2CPP gone, `IPokemonBag_ReleasePokemon` is now a native libnotmain.so export (offset already documented in `nickname_extra_results.json`). If IL2CPP still works, use existing `Niantic.Holoholo.Internal.PokemonBagImpl::NicknamePokemon` and `IPokemonBag.ReleasePokemon`.

3. **Write `bulk_ops.js`** - one Frida script that:
   - Resolves the release/nickname/tag-assign functions
   - Reads `cull_plan.csv` (858 UIDs to transfer) - probably via parameter passing in script body or RPC
   - Reads `desired_tags.csv` (5,413 tag assignments)
   - Iterates: for each cull UID, call ReleasePokemon
   - Iterates: for each pokemon, call AssignPokemonTags with the desired tag list
   - Reports progress via `send()`
   - Detaches

4. **Tag application function unknown.** We know `IPokemonBag_ReleasePokemon`, `NicknamePokemon`, but NOT the tag-assign function name. Need to find via global-metadata.dat search (it's at `/sdcard/Android/data/com.nianticlabs.pokemongo/files/il2cpp/Metadata/global-metadata.dat` - 38MB, already pulled to working dir as `global-metadata.dat`).

5. **Pokemod's anti-cheat bypass:** unclear if needed alongside the above recipe. The recipe got Frida attached without Pokemod injected. But Niantic might catch up later via server validation. Consider running with Pokemod's "Start Service" first IF the pure-Frida path fails.

## File inventory (working dir)

| File | What |
|---|---|
| `pokemon.db` | SQLite, 5,413 rows, all parsed fields + cull_decision/cull_reason |
| `pokemon_v3.json` | Original raw extraction (raw_proto hex per pokemon) |
| `cull_plan.csv` | Per-pokemon cull decision |
| `desired_tags.csv` | Per-pokemon tag assignment |
| `cull_summary.md` | Human-readable cull stats |
| `tag_scheme.md` | Tag design doc |
| `cull_engine.py` | Rules engine (re-runnable) |
| `references.py` | Legendary/mythical/UB/paradox/legacy-move lists |
| `add_extra_fields.py` | DB migration v1 |
| `add_v2_fields.py` | DB migration v2 |
| `generate_tag_assignments.py` | Tag plan generator |
| `proto_offsets_discovered.md` | v1 offset findings (7 fields) |
| `proto_offsets_discovered_v2.md` | v2 offset findings (5 more fields) |
| `phone_storage_survey.md` | Phone file system survey |
| `tag_extraction.md` | Tag extraction findings (5 sample bindings) |
| `tag_definitions.json` | 15 user tag names with colors |
| `uid_to_tags.json` | 5 known pokemon→tag bindings |
| `floyd_protocol.md` | Pokemod's renamed Frida wire protocol analysis |
| `floyd_client.py` | Patched Frida client (likely not needed) |
| `mem_write_codeexec_research.md` | /proc/mem write code injection POC |
| `libnotmain_decrypt_research.md` | iPogo .data is NOT encrypted (anti-analysis padding) |
| `ipogo_features.md` | iPogo feature audit (mostly negative) |
| `lnm_text.bin`, `lnm_rodata.bin`, `lnm_data.bin` | iPogo runtime memory dumps (data was 0 bytes - retry needed) |
| `pokemod-injector.bin` | Extracted Pokemod injector (rebranded Frida) |
| `pokemod.apk`, `ipogo.apk`, `libnotmain.so` | Mod APKs and main lib |
| `global-metadata.dat` | PoGo IL2CPP metadata (38MB) - search for tag-assignment function names |

## Stopping reason
After 6+ hours of execution-mechanism research and prototyping, hit hard walls. Cull plan + tag plan computed and saved. Execution path remains unsolved.

## What we tried for execution and learned

**Direct Niantic API replay: dead end.** Outer envelope is flatbuffers (private schema), signing key sealed in `libNianticLabsPlugin.so` (encrypted strings), Play Integrity attestation required. Community confirmed dead end 2018-2020.

**Frida + heap-scan-for-instance: structurally broken.** Klass byte pattern matches garbage in random heap locations, not real singletons. `get_NumberOfTags()` on 100 candidate matches returned 100 nonsense values; zero were the real `TaggingRpcService` instance. See `reference_il2cpp_heapscan_broken.md` memory note.

**Frida + setenforce 0 recipe: too fragile.** Each attach is non-deterministic - sometimes works, often dies during injection or libil2cpp not loaded in time. ~30% success rate per attempt. Can't reliably maintain a session long enough for bulk work.

**iPogo's encrypted .data: anti-analysis padding, not encrypted features.** Three independent investigations confirmed. Don't decrypt.

**Niantic IL2CPP method confirmed:** `Niantic.Holoholo.Tagging.TaggingRpcService.SetPokemonTags(List<PokemonTagChanges>)` is the bulk method. We CAN find the method but CAN'T find a real instance to invoke it on.

**The breakthrough we lacked:** finding real IL2CPP service instances. Two viable mechanisms:
- **Method hook + capture** - hook get_NumberOfTags, capture `args[0]` (this) when UI calls it. Requires user interaction to trigger.
- **Vector/Xposed module** - inject pre-libconceal at zygote fork. Provides direct IL2CPP runtime access without heap scanning. Requires Android Studio + Kotlin + NDK toolchain (~3-4 hours total to build and test).

**Toolchain on workstation:** JDK 17 + adb only. Missing: kotlinc, gradle, aapt2, ndk-build, apksigner, zipalign. Vector module build needs ~1GB toolchain install.

## Pivots to try next time

1. **Vector module build** with proper toolchain. Documented plan in `zygote_injection_research.md`.
2. **Pokemod IPC injection** - the `pokemod-injector` binary uses XOR-encrypted IPC at `/sdcard/inj.log`. We never investigated whether we can write our own commands to that pipe.
3. **Method-hook + UI-trigger capture** - hook a tag-service method, ask user to interact with tag UI, capture real instance, then call AddTag/SetPokemonTags on the captured pointer in the SAME Frida session.

## Hard truths

- Without persistent injection (Vector), Frida sessions die in seconds; can't do bulk operations.
- Without finding real service instances, heap-scan based hooks call garbage memory and silently corrupt nothing.
- Direct API is impossible.
- The community-standard answer for any reliable PoGo automation in 2026 is in-process injection via LSPosed/Vector/Riru-style modules. There is no shortcut.

## SESSION 2 BREAKTHROUGH (added 2026-05-09 late session)

**Solved:** Reliable persistent Frida injection into PoGo via `lico-n/ZygiskFrida v1.9.0` Magisk module. Bypasses all anti-cheat (no setenforce, no fragile recipe).

**Setup done (one-time):** module installed at `/data/adb/modules/zygiskfrida/`, gadget at `/data/local/tmp/re.zyg.fri/libgadget.so`, configs at same dir. Listen mode on TCP 27047 with `on_load: resume`. **PoGo MUST NOT be in Magisk denylist** or Shamiko hides our injection.

**Working pattern verified:**
1. PoGo launches → ZygiskFrida injects libgadget.so at zygote fork
2. Gadget listens on 127.0.0.1:27047
3. From workstation: `adb forward tcp:27047 tcp:27047` + `frida.get_device_manager().add_remote_device("127.0.0.1:27047")` + attach
4. Method invocation works (created server-side tag CLAUDE_TX, user confirmed visible in PoGo UI)
5. Tag structure readable - GetCachedTagToPokemonBindingForIndex returns binding, +0x10 offset = PokemonTagProto, +0x40 of that = name string ptr, name string at +0x14 in UTF-16-LE

**Real instance finding:**
- Heap scan by klass byte pattern: returns garbage matches with random "tag count" values
- Method hook + UI interaction: captures REAL instance (verified `0x71bed7fe80` returns count=18 matching user's actual tag count)
- Hooks that fire reliably during normal UI use: GetEnabledFilter (when tag manager active), AddTag (when user creates tag manually)
- Hook target: methodInfo->methodPointer at offset 0 of il2cpp_class_get_methods() return

**Remaining work for bulk tag application:**
1. Construct C# generic `List<Niantic.Holoholo.Tagging.PokemonTagChanges>` from JS - requires `il2cpp_class_inflate_generic_class` + List<T> constructor invocation + List.Add(item) calls
2. SetPokemonTags hook didn't fire when user added pokemon - likely generic method uses different dispatch (invokerMethod) than methodPointer; need to find correct hook target
3. Once List construction works: iterate desired_tags.csv, build one PokemonTagChanges per pokemon, build List, call SetPokemonTags(list) on real instance

**Memory entries added (load via memory system):**
- `reference_pogo_zygiskfrida_setup.md` - the working install
- `reference_il2cpp_heapscan_broken.md` - why heap scan fails + working patterns
- `reference_pogo_frida_recipe.md` - older recipe (superseded by ZygiskFrida)

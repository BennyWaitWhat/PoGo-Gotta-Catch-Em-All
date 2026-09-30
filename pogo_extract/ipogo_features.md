# iPogo Feature Surface — Static Reverse-Engineering Report

Generated 2026-05-08 from static analysis of `ipogo.apk` (16MB native + 7.4MB DEX launcher).
**Conclusion up front:** static analysis cannot enumerate iPogo's bulk-rename / mass-transfer / filter features because iPogo's Java APK is just a thin loader, and the actual mod runtime in `libnotmain.so` stores all UI/feature strings inside an encrypted `.data` blob that is decrypted at runtime. See [Section 7](#7-bulk-transfer-bulk-rename-and-filter-grammar---answer) for the answer to the load-bearing question.

---

## 1. iPogo's deployment architecture

iPogo is **not** a self-contained app. It is a code-injection pipeline:

```
+--------------------------+         +-------------------------------------+
| app.ipogo.android.       |         |  Pokemon GO process                 |
| launcher (7.4MB DEX)     |         |  (com.nianticlabs.pokemongo:pgp)    |
|                          |  ptrace |                                     |
| - copies files via su    +-------->+  libnotmain.so dlopen'd into PID    |
| - runs `/data/local/tmp/ |         |  hooks IL2CPP methods at runtime    |
|   injector` as root      |         |                                     |
| - launches PoGo activity |         |  reads/writes iPogo.db via SQLite   |
+--------------------------+         +-------------------------------------+
```

Three binary artifacts, all extracted to `/data/local/tmp/`:

| File | Size | Type | Role |
|------|------|------|------|
| `assets/libnotmain.so` | 16,224,368 B | ELF64 ARM64 stripped | Mod runtime - hooks PoGo's IL2CPP methods, runs feature logic inside PoGo's address space |
| `assets/injector` | 23,464 B | ELF64 ARM64 | ptrace-based loader: forks, attaches to PoGo PID, dlopens `libnotmain.so` |
| `assets/main.jar` | 2,785 B | JAR (inner DEX 4.9KB) | Stub loader - source unverified |

The Java side (`classes.dex`) contains only `Lapp/ipogo/android/launcher/*` classes - a Splash, MainActivity, and Resources stub. No iPogo features live in DEX.

### Boot sequence (decoded from `paranoid` string-obfuscated launcher, in `paranoid_decrypt.py`)

```
SplashScreen.<clinit>:
  Shell.setDefaultBuilder(timeout=10s, flags=8)

MainActivity.copyFile(libnotmain.so | injector):
  read APK asset -> /data/data/app.ipogo.android.launcher/cache/<name>
  su -c cp /data/data/app.ipogo.android.launcher/cache/<name> /data/local/tmp/

MainActivity.onCreate$lambda-2:
  pkill injector                                           # nuke prior copy
  su -c chmod +x /data/local/tmp/injector
  su -c chmod 0555 /data/local/tmp/libnotmain.so
  su -c "/system/bin/chcon -v u:object_r:apk_data_file:s0 /data/local/tmp/injector"
  su -c "/system/bin/chcon -v u:object_r:apk_data_file:s0 /data/local/tmp/libnotmain.so"
  su -c "/data/local/tmp/injector"                         # detaches; runs as daemon
  Handler.postDelayed(()-> am start -n com.nianticlabs.pokemongo/...UnityMainActivity, ~100ms)
```

### What `injector` does
It's a tiny ARM64 ELF that polls `/proc/mounts` and `proc events` (uid_change, exec) for the Pokemon GO process (looks for `com.nianticlabs.pokemongo:pgp` and `com.nianticlabs.pokemongo`), then `ptrace`-injects `libnotmain.so` via `dlopen`. The strings are clean: `Injecting`, `Injector PID not found`, `oldinstance: %s`, `PogoInject/vpgp`, `:pgp` suffix detection.

---

## 2. `iPogo.db` schema (the on-device persistence)

This is the only structured iPogo data on disk. Schema:

```sql
CREATE TABLE Filter     (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, settings TEXT);
CREATE TABLE Items      (id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT UNIQUE, amount INTEGER);
CREATE TABLE Journal    (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, latitude DOUBLE, longitude DOUBLE,
                         timestamp INTEGER, encounterId TEXT, pokemonId INTEGER, formId INTEGER,
                         costumeId INTEGER, fortId TEXT);
CREATE TABLE Last       (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, latitude FLOAT, longitude FLOAT);
CREATE TABLE Preference (feature TEXT UNIQUE, value INT);
CREATE TABLE Route      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, gpx TEXT);
```

### Live data observed in this DB

`Filter` table — **only 1 row** (`id=1, name='raidLevelIds', settings="'15,14,13,12,11,9,8,7,6,5'"`).
- The value is **CSV of integer IDs wrapped in literal single-quotes**.
- This is iPogo's raid filter (which raid tiers to show on the map).
- There is no row matching pokemon-bag filter, transfer queue, or rename ruleset.

`Preference` table — 9 rows of toggles with INT values:
| feature | value | meaning (inferred from native strings, e.g. `set_arplus`, `set_freezepokemon`) |
|---|---|---|
| ARPlus | 1 | AR+ throw-bonus (catch helper) |
| CatchPreview | 1 | preview screen before commit |
| Curveball | 1 | force curveball |
| EnhancedThrow | 1 | auto-aim throw |
| HideUIs | 0 | hide HUD overlays |
| Throw | 2 | throw type (0..N enum) |
| doubleTapToTeleport | 1 | tap-to-teleport gesture |
| freezePokemon | 1 | pokemon-on-map standstill (`set_freezepokemon` native hook) |
| tapToWalk | 1 | walk gesture |

`Items`, `Journal`, `Last`, `Route` are auxiliary (consumable inventory cache, deep-link history, last-known waypoint, recorded GPX walking routes). Empty-or-near-empty in this DB.

### Filter-table value format - what we know with certainty

- Type: TEXT, single column called `settings`.
- Single observed format: `'<csv-of-int-ids>'` - literal apostrophes are part of the value, comma-separated decimal ints inside.
- **No JSON, no key=value pairs, no boolean grammar visible.** The schema is too generic (`name TEXT UNIQUE`, `settings TEXT`) to declare a grammar - whatever serialization the native code uses, the column accepts it.
- **No second example to triangulate from.** With only `raidLevelIds` populated, we cannot infer whether other filter names use the same `'a,b,c'` format or a different one (JSON, key=val, etc.).

---

## 3. iPogo's native hook surface (what `libnotmain.so` calls into Pokemon GO)

`libnotmain.so` is a stripped ARM64 ELF. Sections:

```
.dynstr        110KB    standard libc/libstdc++ symbols
.rodata        134KB    iPogo's code constants (interesting bits)
protodesc_cold  82KB    google.protobuf descriptor.proto reflection data
.text          4.7MB    iPogo + bundled libs (protobuf, zstd, libunwind, libc++)
.data          9.4MB    HIGH-ENTROPY blob (entropy ~uniform across all bytes 00..0F)
.bss          122KB
```

### iPogo's own source files (referenced in C++ exception/log strings)
- `../../../../cpp/core.cpp`
- `../../../../cpp/corevgp.cpp`
- `../../../../cpp/pogohack.cpp`
- `../../../../cpp/il2cpp/il2cpp.cpp`
- `../../../../cpp/protos/protos-for-cpp-only.pb.cc`

### Hook framework (custom, simple PLT-style or Substrate-style)
Strings: `MAX_HOOKS`, `Too many hooks, increase MAX_HOOKS`, `Method '%s' not found for hooking`, `Method %s NOT for hooking`, `Can not hook this method: %s`, `b_hook`, `After patch:`, `Mprotect rw failed`.

Hooks are resolved by IL2CPP method-name lookup at runtime via these helpers (also in `.rodata`):
```
il2cpp_class_from_name           il2cpp_class_get_method_from_name
il2cpp_class_get_methods         il2cpp_class_get_name
il2cpp_class_get_parent          il2cpp_class_get_assemblyname
il2cpp_class_from_type           il2cpp_class_from_system_type
il2cpp_method_get_name           il2cpp_image_get_class
il2cpp_image_get_class_count     il2cpp_image_get_name
il2cpp_assembly_get_image        il2cpp_domain_get
il2cpp_domain_get_assemblies     il2cpp_domain_assembly_open
il2cpp_object_new                il2cpp_array_new
il2cpp_array_class_get           il2cpp_runtime_invoke
il2cpp_thread_attach             il2cpp_thread_detach
il2cpp_gchandle_new              il2cpp_gchandle_free
il2cpp_gc_disable                il2cpp_gc_enable
il2cpp_gc_is_disabled            il2cpp_type_get_name
il2cpp_type_get_object
```

### iPogo "feature setters" found in `.rodata` (these are commands the mod sends to itself)

These are **the entire iPogo command surface that exists in plaintext strings**:

```
set_arplus              set_autoconnectvgp     set_boostspawn
set_ButtonsVisible      set_challenge          set_fastmap
set_files_dir           set_freezepokemon      set_mappings
set_shinyscanner        set_skip_animations    set_skip_team_leader
set_skip_team_rocket    set_spin               set_text
set_throw               set_VisibleOnMap       setLevel0
setLocationNative
update_shinies          delete_items           ball_check
internal_cmd            generate_first_challenge      generate_next_challenge
generate_reconnect_response   reconnectvgp     decrypt_next
nativeProxyInvoke       nativeAttestResponse   nativeAddLocationProviders
nativeLocationUpdate    nativeGetApiKey        nativeGetGCPProjectNumber
nativeInstalled         setNativeInstalled     onSSLStateChange
PogoHackerVGPDLFUNC     onNewSessionEstablished
get_player_stats        get_session_key        get_PlayerStats
_stop_il2cpp            __stop_il2cpp          evaluateExpression
```

### Pokemon GO IL2CPP classes/methods iPogo hooks (visible in `.rodata`)

Anything iPogo wants to override or read in PoGo, it names. Inventory of `Niantic.Holoholo.*` strings in the binary:

```
Niantic.Holoholo.UI.Pokemon.PokemonInventoryGuiController        # the bag screen
Niantic.Holoholo.UI.Pokemon.PokemonInfoGuiController             # single-mon detail
Niantic.Holoholo.UI.Pokemon.PokemonInfoPanel                     # info panel widget
Niantic.Holoholo.UI.Pokemon.PokemonInfoDynoScrollRect            # bag scroll-rect
Niantic.Holoholo.UI.Items.ItemInventoryGuiController             # item bag
Niantic.Holoholo.UI.UserPromptsService                           # confirm dialogs
Niantic.Holoholo.Inventory.ItemInventoryItemWidget.ItemData      # item slot data
Niantic.Holoholo.Encounter.EncounterGuiController                # encounter screen
Niantic.Holoholo.Encounter.EncounterState                        # encounter FSM
Niantic.Holoholo.Encounter.EncounterInteractionState
Niantic.Holoholo.Encounter.EncounterPokemon
Niantic.Holoholo.Combat.CombatDirectorV2                         # PvP
Niantic.Holoholo.Combat.Contexts.InvasionCombatState             # rocket fights
Niantic.Holoholo.Cutscenes.PokemonCutsceneService                # evolve animations
Niantic.Holoholo.Cutscenes.PokemonCutsceneGuiController
Niantic.Holoholo.DeepLinking.DeepLinkingListener                 # ipogo://... handler
Niantic.Holoholo.Map.MapContentHandler                           # map data ingress
Niantic.Holoholo.Map.MapEntityService                            # spawned entities
Niantic.Holoholo.Map.MapPlaceDirectoryService                    # POIs/gyms/stops
Niantic.Holoholo.Map.MapViewHandler                              # map view
Niantic.Holoholo.Map.WildMapPokemon                              # wild spawn marker
Niantic.Holoholo.Map.GroundTapHandler                            # touch-on-ground
Niantic.Holoholo.Map.UI.CompassGuiController                     # compass widget
Niantic.Holoholo.MapRootState                                    # top-level map FSM
Niantic.Holoholo.Pgp.PgpService                                  # network manager
Niantic.Holoholo.Pgp.PgpGuiController
Niantic.Holoholo.Incident.IncidentService                        # rocket invasions
Niantic.Platform.Ditto.Rpc.RpcManager                            # protobuf RPC layer
Niantic.Promises.Promise                                         # async helper
Niantic.Protobuf.MessageExtensions
```

### Specific Pokemon GO method names referenced (mostly hook targets)

```
IPokemonBag                       (Niantic interface for the bag)
IPokemonBag_GetPokemon            (read accessor)
IPokemonBag_ReleasePokemon        (the release/transfer entry point - SINGLE pokemon)
AddPokemon                        (write into bag)
UpdateWildPokemon                 (map spawn upsert)
get_MapPokemon / get_Pokemon / get_PokemonProto
PokemonProtoGetPokemonDisplay     (read display fields for visuals)
release_pokemon                   (the c-side accessor for the same)
update_shinies                    (mass-mark shinies that the scanner found)
delete_items                      (matching item-bag operation)
ball_check                        (check ball inventory before throw)
ClickIcon, ClickRunAway, ResolveUrl, EnterState, ExitState   (FSM helpers)
PlayMegaEvolveCutscene, PlayPurifyCutscene,
PlayEvolveCutscene, PlayEggHatchCutscene                     (cutscene skips)
ReceiveCombatUpdate, SendBattleUpdate                        (PvP)
GroundTapped, MapPokemon, MapPoi, IPoi, GetGroundLocation    (map taps)
TouchScript.Gestures.TapGesture                              (gesture lib)
notifyOutgoingRPC, notifyIncomingRPC                         (RPC interception)
CombatProto.CombatPokemonProto.nickname                      (nickname proto field)
CatchPokemonProto.spawn_point_guid                           (catch proto)
IItemBag                                                     (item-bag interface)
PokemonInventoryGuiController, ItemInventoryGuiController    (the bag screens)
PgpGuiControllerHandleConnectionStateChange, *HandleTargetChange  (connection FSM)
HandleDismissComplete, HandleOpenComplete                    (UI lifecycle)
OpenGUI, CloseGUI, CurrentPageGui, PageChangeUpdate          (GUI navigation)
TargetChange, MemberwiseClone, MakeGenericType               (generic helpers)
```

### Key observations
- **`IPokemonBag_ReleasePokemon`** is iPogo's known hook point for releasing a single pokemon. It is the IL2CPP method name on Pokemon GO's side - iPogo calls it (or the underlying RPC) to transfer an individual pokemon to the professor.
- **No bulk variant is named.** No `ReleasePokemonMass`, `BulkRelease`, `ReleaseList`, or anything similar exists in any string in any section of any binary in the APK.
- **No rename hook is named at all.** No `SetNickname`, `Rename`, `EditNickname` symbol exists. The only `nickname` reference is the protobuf field `CombatProto.CombatPokemonProto.nickname`.

---

## 4. The `iPogo` log tag and other markers

- `iPogo` itself appears once at offset `0x81f0f` in `.rodata` - confirmed log tag (used in `POGO/%s [%s/%d]: %s` and `PogoHacker il2cpp: <%s>` log format strings).
- `Pogohacker`, `PogoHacker`, `PogoHackerVGPDLFUNC`, `PogoHackerVPGP : <%s>` - matches the codename in `corevgp.cpp` ("VGP" = the iPogo backend protocol).
- `ipogo.app` URL appears only in the launcher (decrypted): `https://ipogo.app/` and `https://ipogo.app/download/update-changelog.json`.

---

## 5. The encrypted `.data` section

The 9.4MB `.data` section has these properties:
- Bytes `00..0F` are evenly distributed (~50K each), which is impossible for a normal IL2CPP `.data` (would have heavy skew toward 00 from null pointers and zero-init).
- Only 0.9% of bytes are null (typical `.data` is 30-60% null).
- No standard XOR key recovers `Pokemon`, `Filter`, `transfer`, `IPokemonBag`, etc.
- No `gzip`/`zlib`/`zstd` magic header at start, mid, or any 4KB boundary.
- High-entropy throughout - first 16 bytes: `3182bf263b3a5d3779c8f8808b72fe66`.

**Interpretation:** the `.data` blob is encrypted - probably with a per-build key or a key derived at runtime (e.g., from `AUTH_TOKEN` in `Hawk2.xml` after iPogo's account login). The mod likely calls a routine in `.text` early in initialization that XOR/AES-decrypts portions of `.data` lazily into RAM.

This means **the actual iPogo UI labels and feature strings (menus, on-screen toasts, format-string templates, the bulk-action UI if any) live in this encrypted blob and cannot be recovered without dynamic analysis** (Frida memory dump after iPogo has booted, or unicorn-engine emulation of the decrypt routine).

---

## 6. Other on-device iPogo state (from this working dir)

- `Hawk2.xml` (`/data/data/app.ipogo.android.launcher/shared_prefs/Hawk2.xml`): Hawk-encrypted key/value store. Keys are **launcher-process** config (account/auth/launch flags), not in-game features:
  - `AUTH_TOKEN`, `REFRESH_TOKEN`, `EMAIL`, `DISCORD_TOKEN` (account)
  - `GAME_VERSION`, `GAME_ARCH`, `TIER` (build info; TIER probably free/premium)
  - `APP_THEME`, `ENABLE_GAY_MODE_TOGGLE`, `FIRST_LAUNCH`, `RECORDING_MODE_ENABLED` (UI prefs)
  - `USE_ROOT`, `DISABLE_OOM_PROTECTION`, `ROOT_SOLUTION` (root-mode toggles)

- `gameData.xml`, `app_db.sqlite` are **Niantic's** SharedPreferences/DB, not iPogo's. (Geofence cache for awareness service, fitness progress proto.)

---

## 7. Bulk transfer, bulk rename, and filter grammar - answer

After exhaustive static analysis of every readable section of every binary in `ipogo.apk`:

### Bulk / mass-transfer

**No evidence of a mass-transfer feature exists in static strings.**

- The single transfer hook visible is `IPokemonBag_ReleasePokemon`, which (per its IL2CPP signature in PoGo) transfers exactly **one** pokemon by reference.
- No string anywhere in the binary contains `mass`, `bulk`, `multi`, `batch`, `selectAll`, `release_many`, `transferList`, etc.
- No SQL template string like `INSERT INTO Filter` or `UPDATE Filter SET settings WHERE name = 'transferQueue'` exists.

It's possible that iPogo's UI offers a "select multiple, release them all" option that simply iterates `IPokemonBag_ReleasePokemon` per pokemon - that loop logic could live in encrypted `.data`. But the **static strings do not advertise such a feature** (compare: feature toggles like `set_freezepokemon`, `set_arplus` etc are visible in plaintext, so a similarly-named `set_bulktransfer` or `mass_release` would be too).

### Bulk / mass-rename

**No evidence of a rename-existing-pokemon feature exists at all.**

- The only `nickname` string in the binary is the protobuf field `CombatProto.CombatPokemonProto.nickname` - i.e., reading the nickname from a CombatPokemonProto, not setting it.
- No `SetNickname`, `Rename`, `UpdateNickname`, `EditPokemon`, etc.
- No format-string tokens like `{cp}`, `{iv}`, `{atk}`, `{def}`, `{sta}`, `{name}`, `{species}`, `{level}` exist anywhere in any binary.
- No regex/template/printf-style nickname builder is visible.

### Filter grammar

**The "filter" feature in `iPogo.db.Filter` is not the pokemon-bag filter.** It is a generic key/value store currently used (in this DB) only to hold raid-tier visibility (`raidLevelIds = '15,14,13,12,11,9,8,7,6,5'`).

What we can say about it from one observed row:
- Format: `'<int>,<int>,<int>,...'` (apostrophe-wrapped CSV of decimal IDs).
- No AND / OR / NOT / range operators visible.
- No JSON, no key=value pairs, no boolean expressions.
- The **only** filter known to exist is `raidLevelIds`. If iPogo has a pokemon-bag filter UI, it either uses a different name not yet populated, a different schema (Preference table?), or runtime-only state that never hits disk.

### How to trigger transfer from a UID list (e.g., your `cull_plan.csv` of 919 transfer-targets)

There is **no static-analysis-visible mechanism** for iPogo to accept a list of pokemon UIDs and transfer them. No content provider, no broadcast intent, no DB flag, no known JSON schema, no SQLite "queue" table.

**Practical paths forward** (each requires going beyond static analysis):

1. **Frida-hook iPogo's release path inside the PoGo process.** Since `IPokemonBag_ReleasePokemon` is the named hook, you can directly call it via your own Frida script using the IL2CPP API helpers iPogo itself uses (`il2cpp_class_from_name` + `il2cpp_class_get_method_from_name`). Pass each UID from `cull_plan.csv` in a loop. This works without iPogo, you don't need iPogo at all for this.

2. **Dynamic analysis of `libnotmain.so`.** Load it under a debugger or Frida, dump `.data` after the decrypt routine runs, and re-grep for `transfer` / `rename` / format strings. Without a teardown of the decrypt routine, this is the only route to enumerate hidden features.

3. **Inspect iPogo's UI live.** Take a screenshot of iPogo's in-game overlay during a session. If a "Mass Release" or "Auto-Rename" menu exists, you'll see it. If absent, the feature genuinely doesn't ship.

4. **Examine the iPogo VGP server.** The mod calls `https://ipogo.app/` for `update-changelog.json` and runs an authenticated session via `corevgp.cpp` (`reconnectvgp`, `set_autoconnectvgp`, `decrypt_next`, `Enc nonce :`, `generate_first_challenge`, `set_session_key`). Some features may be server-driven and fetched per-account - their schema is unknowable without traffic capture and the session key.

---

## 8. Artifacts produced during this investigation

All saved in `pogo_extract/`:

| File | Contents |
|------|----------|
| `libnotmain.so` | Extracted from APK assets/ |
| `classes.dex`, `main_classes.dex`, `main.jar` | Extracted DEX/JAR |
| `injector` | Extracted ARM64 ELF loader |
| `chunk0.json` | Paranoid-encrypted launcher string blob (665 chars) |
| `paranoid_decrypt.py`, `paranoid2.py` | Working paranoid string decoder (Java port of `io.michaelrocks.paranoid`) |
| `decoded_strings.txt` | Decoded launcher strings (su commands, asset paths, ipogo.app URL) |
| `strings_n4.txt`, `strings_n8.txt` | Plain ASCII strings from `libnotmain.so` |
| `strings_offsets.txt` | Same with file offsets |
| `strings_rodata.txt`, `strings_data.txt`, `strings_text.txt`, `strings_dynstr.txt`, `strings_protodesc_cold.txt` | Per-section string buckets |
| `rodata_clean.txt` | `.rodata` strings with libcxx/protobuf/sentry/etc boilerplate filtered out (1856 lines) |
| `niantic_classes.txt` | Unique `Niantic.*` class names referenced (33) |
| `injector_strings.txt` | Strings from the injector ELF |
| `clinit.txt`, `deobf_helper.txt` | Disassembly traces |

---

## 9. TL;DR

- **iPogo does not statically declare a bulk-transfer, bulk-rename, or pokemon-bag filter feature.** None of the keywords `transfer`, `mass`, `bulk`, `rename`, `nickname` (as a setter), `iv_min`/`cp_max`/etc, or `{cp}`/`{iv}`/etc format tokens appear in any string of any binary in the APK.
- **iPogo's `Filter` SQLite table is generic key/value, currently only used for `raidLevelIds` (raid-tier map filter).** Format is CSV-of-ints inside literal apostrophes.
- **All UI labels, menu structure, and any per-feature format strings live in an encrypted 9.4MB `.data` blob** that cannot be unmasked with static analysis only.
- For your cull-plan automation, the cleanest path is Frida-driving `IPokemonBag_ReleasePokemon` directly inside the PoGo process - skip iPogo's UI entirely, since iPogo provides no documented intent / DB / IPC entry point that would let an external process queue transfers.

# iPogo Filter / Transfer System - Investigation Report

Date: 2026-05-08
Phone: Pixel 9 Pro (rooted) at 100.98.158.56:5555
iPogo launcher: app.ipogo.android.launcher
PoGo: com.nianticlabs.pokemongo
Live DB pulled to: `ipogo_live.db` (61440 bytes, identical schema to outdated `iPogo.db`)

## TL;DR

The investigation hit a hard wall: **iPogo's filter logic is not in any decompilable code we can statically analyze.** The launcher APK is a thin shell; the actual mod (filter parsing, transfer execution, all gameplay logic) lives inside `assets/libnotmain.so`, a 16 MB stripped ARM64 ELF whose feature strings are obfuscated/encrypted (likely Hawk2-style at-rest encryption or runtime XOR). None of the relevant identifiers (`shiny`, `IV`, `transfer`, `costume`, `uid`, etc.) appear as plain text in the binary.

**The Filter table is NOT a per-pokemon rule store.** It is a generic key->CSV settings store. Each row is one named setting whose value is a comma-separated list of integer IDs. There is currently no second-tier filter expression language visible in the data.

## What is concretely known

### Schema (verified)

```sql
CREATE TABLE Filter      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, settings TEXT);
CREATE TABLE Preference  (feature TEXT UNIQUE, value INT);
CREATE TABLE Items       (id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT UNIQUE, amount INTEGER);
CREATE TABLE Last        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, latitude FLOAT, longitude FLOAT);
CREATE TABLE Journal     (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, latitude DOUBLE, longitude DOUBLE,
                          timestamp INTEGER, encounterId TEXT, pokemonId INTEGER, formId INTEGER,
                          costumeId INTEGER, fortId TEXT);
CREATE TABLE Route       (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, gpx TEXT);
```

### Live data (entire DB, evidence)

```
Filter:
  1 | raidLevelIds | 15,14,13,12,11,9,8,7,6,5
Preference:
  Throw=2  EnhancedThrow=1  Curveball=1  ARPlus=1  freezePokemon=1
  CatchPreview=1  tapToWalk=1  doubleTapToTeleport=1  HideUIs=0
Items: (empty)
Last:  99 | last | 40.7449798583984 | -73.9957733154297
Journal: 5 rows of type=teleport (lat/lng + timestamp; encounter/pokemon/form/costume all NULL)
Route: empty
```

### Filter table format - confirmed

- One row per **named setting**, not per filter rule.
- `name` is a fixed identifier (the only one observed: `raidLevelIds`).
- `settings` is **plain text CSV of integer IDs**. NOT JSON, NOT base64, NOT proto.
- `INSERT OR REPLACE INTO Filter (name, settings) VALUES (?, ?)` is the natural write pattern (UNIQUE on name).

This is a "checkbox group" persistence store. iPogo's UI presumably has settings panes whose multi-select state is serialized as CSV.

## What we could not determine (and why)

### The vocabulary of `name` keys

We have one observed key (`raidLevelIds`). The full list of valid keys lives only inside `libnotmain.so` and is encrypted. Static analysis dead-ends:

- The launcher APK (`ipogo.apk`) decompiles cleanly via jadx but contains only 4 Kotlin source files (MainActivity, SplashScreen, BuildConfig, R) plus io.michaelrocks.paranoid string deobfuscator. None of them open, query, or write the Filter table.
- The launcher's job is purely to copy `assets/libnotmain.so` and `assets/main.jar` to a privileged location, then spawn `Shell.su(...)` commands. The mod itself is everything inside libnotmain.so.
- libnotmain.so is a 16 MB stripped ARM64 ELF. `strings -n 6` returns 23,376 lines but the iPogo-specific identifiers (filter keys, UI labels, SQL templates) are NOT among them. Visible strings are limited to: protobuf field names from the Niantic .proto schema, zstd compression bindings, Lua VM tables, JNI plumbing. The PoGo proto fields (`individual_attack`, `nickname`, `costume`, `is_shiny`, etc.) are present because they're parsed from PoGo's own protos, not because iPogo exposes them as filter keys.
- Searching for `raidLevelIds` (the one key we know exists) produces ZERO hits in either libnotmain.so or the launcher dex. So all filter-key strings are encrypted at rest and decoded only at runtime.
- `app_resources_lib.jar` and `google_api_resources_lib.jar` from PoGo's cache are unrelated Firebase C++ JNI bridges (5 java files total).

### Whether iPogo supports per-pokemon UID filters

**Unknown.** No second-tier filter table exists in the schema. If iPogo supports `uid IN (...)` style targeting, it would have to live inside one of the `Filter.settings` rows under a key we haven't observed yet (e.g. `transferUidWhitelist=12345,67890,...`). Given that the existing `raidLevelIds` value is 10 small ints in 24 bytes, a full long UID list would also fit fine in a TEXT column. But there is no code-path evidence either way.

### How transfer is triggered

**Unknown.** No "trigger" column, no flag in Preference, no AndroidManifest intent in the launcher that mentions transfer. The most likely architecture is: iPogo intercepts PoGo's bag UI, and a "Transfer matching" button in iPogo's overlay invokes an in-process function that reads relevant Filter rows. There is no DB-level "execute now" knob visible in the schema.

The launcher's `AndroidManifest.bin` was extracted but only declares standard activities for the launcher itself; no content provider, no broadcast receiver that would accept an external "trigger transfer" intent.

### Filter criteria fields

Cannot enumerate definitively. The PoGo proto (which iPogo can read) does expose all the relevant fields - so the *theoretical* matchable set includes:
- `pokemon_id`, `pokemon_display.form`, `pokemon_display.costume`, `pokemon_display.shiny`, `pokemon_display.gender`
- `individual_attack`, `individual_defense`, `individual_stamina`, derived IV%
- `cp`, `level` (derived from cp_multiplier), `nickname`, `traded_time_ms`, `is_lucky`, `buddy_total_km_walked`
- `move_1`, `move_2`, hidden move; `is_bad` (escape pokemon flag), `favorite`

But which of these iPogo's UI exposes as a Filter row, and under what key name, is encrypted in libnotmain.so.

## What can be done programmatically (today, with confidence)

1. **Read** all Filter rows: `sqlite3 /data/data/com.nianticlabs.pokemongo/databases/iPogo "SELECT * FROM Filter"`.
2. **Modify** the value of a Filter row (e.g. change which raid levels are shown):
   ```sql
   UPDATE Filter SET settings='15,14,13,12,11' WHERE name='raidLevelIds';
   ```
3. **Insert** a row under a new candidate key:
   ```sql
   INSERT OR REPLACE INTO Filter(name, settings) VALUES ('foo', '1,2,3');
   ```
   This will succeed at the SQLite level. Whether iPogo uses the key depends on whether `foo` is one of its hardcoded keys.

But there is **no documented path** to: programmatically express "Ditto with IV<60% and not shiny and not lucky" as a Filter row, or to fire a "transfer all matching" intent. Both require either (a) running iPogo's UI manually, or (b) reverse engineering libnotmain.so dynamically.

## Recommended next step (out of scope for this 30-min budget)

To complete the spec, the remaining work is:

1. Start frida-server on device (`/data/local/tmp/frida-server` is already pre-staged).
2. Launch iPogo, attach to PoGo, hook `sqlite3_prepare_v2` / `sqlite3_bind_text`. Every iPogo write/read of the Filter table will appear with its plaintext key and value.
3. Use the iPogo UI in pinned "transfer filter" pane and record what gets written.
4. Hook the transfer entrypoint by setting a one-shot breakpoint on PoGo's `IPokemonBag_ReleasePokemon` IL2CPP method (the symbol is in libnotmain.so at offset 0x14310 and 0x7ba10 per strings) and read the call site.

The frida-inject and frida-server binaries already in this directory plus the existing `il2cpp_extract*.js` scripts give a head start.

## Sample filter (what we'd write IF the keys were known)

For "Ditto, IV<60%, not shiny, not lucky", the *speculative* schema (based on the only-known precedent `raidLevelIds`) might be:

```sql
INSERT OR REPLACE INTO Filter(name,settings) VALUES('transferPokemonIds','132');
INSERT OR REPLACE INTO Filter(name,settings) VALUES('transferIvMax','59');
INSERT OR REPLACE INTO Filter(name,settings) VALUES('transferShiny','0');
INSERT OR REPLACE INTO Filter(name,settings) VALUES('transferLucky','0');
```

But the actual key names are unverified. Treat this as a placeholder to be confirmed via Frida hook of `sqlite3_bind_text` while the user toggles options in iPogo's transfer UI.

## Files of record

- [ipogo_live.db](ipogo_live.db) - fresh dump, 2026-05-08 06:12 UTC (identical to outdated copy except for current state)
- [ipogo_extracted/libnotmain.so](ipogo_extracted/libnotmain.so) - 16 MB stripped ARM64 ELF, the real iPogo mod
- [ipogo_extracted/jadx_out/sources/app/ipogo/android/launcher/MainActivity.java](ipogo_extracted/jadx_out/sources/app/ipogo/android/launcher/MainActivity.java) - launcher entrypoint (only Kotlin/Java in the APK)
- [ipogo_extracted/libnotmain_strings.txt](ipogo_extracted/libnotmain_strings.txt) - full strings dump of libnotmain (none of the iPogo filter keys appear)

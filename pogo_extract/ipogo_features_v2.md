# iPogo Feature Surface v2 - Runtime Memory Analysis Attempt

Generated 2026-05-08 as a follow-up to `ipogo_features.md`. Purpose: dump the decrypted `.data` section of iPogo's `libnotmain.so` from PoGo's runtime memory and extract feature strings (filter grammar, command names, rename templates) that are encrypted at rest.

**Headline result: the runtime dump did not happen.** iPogo was not injected during the analysis window because injection requires interactive UI tap on a locked screen, and the working environment is unable to bypass biometric unlock. v2 therefore consists of (a) characterizing the injection blocker, (b) deeper structural analysis of the encryption itself, and (c) cross-referencing existing memory dumps. **No new feature surface was decrypted**, but the analysis confirms the structure of the encrypted payload and identifies a clean recovery path for a follow-up session.

---

## 1. State of the injection at analysis time

| Process | PID seen | iPogo injected? | Evidence |
|---|---|---|---|
| `com.nianticlabs.pokemongo` | 12581, then 29663 (relaunched) | **No** | TracerPid=0, PPid=1001 (zygote), no `libnotmain.so` / `floyd-agent-*.so` / `main_agent` / `vpgp` / memfd:floyd in `/proc/PID/maps` |
| `com.pokemod.app.public` (iPogo launcher) | 27692, 31633 (restarted) | n/a (launcher) | Has `libfancier.so` + `libconceal.so` (Facebook Conceal AES-GCM KV cipher), but **no `libnotmain.so` in its own memory either** |

`/proc/29663/maps` was 7861 lines. Filtered for: `libnotmain`, `conceal`, `main_agent`, `vpgp`, `floyd`, `pokemod`, `memfd:floyd`, `/data/local/tmp` -> **zero matches** in the PoGo process.

### Why injection did not happen

iPogo's launcher (`com.pokemod.app.public`) does not auto-inject when started. The launch sequence (decoded from the obfuscated launcher in v1) is:

```
user opens iPogo launcher (com.pokemod.app.public) -> AuthActivity -> MainActivity (UI list of mods)
user taps "Launch" button -> launcher exec()s injector binary as root -> injector ptrace-injects libnotmain.so into PoGo
```

Triggers tested in this session, all unsuccessful:
- `monkey -p com.pokemod.app.public 1` -> launcher boots, lands in MainActivity, idles. No injector subprocess. No PoGo spawn.
- `am start -a VIEW -d 'pokemongo://launch'` -> opens launcher's pokemongo URI handler, but does not auto-tap Launch.
- `am start -n com.pokemod.app.public/com.pokemod.app.LauncherAliasLightIcon` -> same as monkey.
- `am force-stop com.nianticlabs.pokemongo; am start -a VIEW -d 'pokemongo://launch'` -> spawned a fresh PoGo (PID 29663) directly via Android, bypassing pokemod's injector entirely. No injection.

`dumpsys window | grep mFocusedWindow` showed Instagram in foreground throughout (lockscreen state `mDreamingLockscreen=true`). With the screen locked, `input tap` cannot dismiss the lockscreen and reach pokemod's "Launch" button. **The blocker is biometric unlock, not the analysis stack.**

---

## 2. Static structural analysis of the encrypted payload

What we *can* learn about iPogo's encryption from artifacts on disk.

### 2.1 libnotmain.so .data section - confirmed encrypted at rest

`libnotmain.so` ELF section table (parsed):

| Section | Addr | Off | Size |
|---|---|---|---|
| `.rodata` | 0x7aa60 | 0x7aa60 | 130 KB |
| `.text` | 0x1a20c0 | 0x1a20c0 | 4807 KB |
| `.data.rel.ro` | 0x657280 | 0x656280 | 53 KB |
| **`.data`** | **0x6673d0** | **0x6653d0** | **9293 KB** |

Entropy distribution of `.data` in 4KB chunks:

| Entropy band | % of chunks |
|---|---|
| 0-1 bits (zero pad) | 0.3% |
| 2-5 bits | 2.3% |
| 6-7 bits | 0.0% |
| **7-8 bits (random)** | **97.3%** |

Mean entropy 7.83 bits/byte = essentially perfect random. This is consistent with AES-CTR / ChaCha20 / any modern block cipher in a randomized mode. Not zlib (no headers), not gzip, not zstd, not raw XOR with any short key (chi-squared test by-position-mod-N for N in 1..512 was uniformly ~250-260, no period detected).

Two interior low-entropy zones:

| Range | Size | Avg ent | Notes |
|---|---|---|---|
| 0xee63d0 - 0xeeb3d0 | 20 KB | 1.13 | Pure zeros, BSS-like padding |
| 0xf343d0 - 0xf6e3d0 | 232 KB | 3.76 | Structured-but-non-printable. Looks like a lookup table / bit-rotated keystream / pre-expanded round keys; tested: not AES T-table (no 0xa56363c6 occurrence anywhere) |

Trailing 79 zero bytes at the very end of `.data`.

The 232 KB region is the most interesting unsolved structure. It could be:
- An AES-NI / NEON pre-expanded key schedule for many keys (one per encrypted blob);
- A blob index (offset+length+keyref tuples) for selective per-feature decryption;
- Compressed metadata (but no zstd/zlib magic visible).

### 2.2 Crypto primitives present

Searching `libnotmain.so` for known crypto magic constants:

| Constant | Hits | Where |
|---|---|---|
| AES forward S-box (`63 7c 77 7b f2 6b 6f c5 ...`) | **1** | `.rodata` @ 0x96f78 (full 256-byte sbox) |
| AES T-tables (`a5 63 63 c6` MIX1) | 0 | none |
| ChaCha20 sigma `expand 32-byte k` | 0 | none |
| SHA-256 H0 (BE or LE) | 0 | none |
| TEA / XTEA delta `0x9e3779b9` | 0 | none |
| String "RC4" | 1 | rodata, but appears in OpenSSL blob context |

Conclusion: **AES is the only confirmed primitive** (sbox-based implementation, e.g., mbedtls or a hand-rolled T0/T1/T2/T3 expansion). No T-tables = either it's a smaller/loop-based AES (mbedtls "soft"), or hardware-accelerated via ARM Crypto Extensions (in which case sbox is fallback only). 18 sbox-pattern hits in `.data` are coincidental on encrypted bytes (random data hits the sbox sequence ~ 1 in 2^32 per offset).

### 2.3 The Frida agents (`main_agent`, `vpgp_agent`) share a 511-byte ciphertext prefix

Both agents are stored on-device as base64 blobs:

```
/data/local/tmp/main_agent  -> 2,944,552 B base64 -> 2,208,414 B decoded
/data/local/tmp/vpgp_agent  ->   347,720 B base64 ->   260,789 B decoded
```

Their decoded ciphertexts are byte-for-byte identical for the **first 511 bytes**, then diverge starting at offset 511.

Common prefix begins:
```
ef b1 df 81 c0 f6 48 66 12 d7 a0 77 29 e8 1d 9a
23 eb 87 0f 69 3f 4e bd 70 f2 f8 90 fd 25 0f e1
9f a9 f7 b5 3d 76 56 63 f9 cf b5 87 6c 62 31 81
...
```

Decoded blob entropy 7.9999 (perfect random). Common prefix is not a SHA-256 of any obvious input (`""`, `"main_agent"`, `"Pokemod"`, `"iPogo"`, `"frida-agent"`, `\x00 * N`) and not present in `pokemod-injector-arm64`, `libfancier.so`, or `libconceal.so`.

**Interpretation:** both agents are encrypted Frida QuickJS bytecode bundles. They share a 511-byte fixed plaintext header (likely Frida's frida-compile envelope: format version + table-of-contents pointers + module-list header) and are encrypted with the same key+IV (or, more likely, a key-derivation seeded by the same constant + a random 511-byte session prefix is unencrypted plaintext).

The fact that XOR of the two ciphertexts has 100% zero bytes for offsets 0-511 and **only 7 short same-byte runs (8-9 bytes) over the next ~500 KB** rules out simple key-reuse-across-files: the agents diverge as expected for two different plaintexts encrypted with same key+different IV (or similar). The 511-byte prefix is best explained as a stripped-on-load envelope, not part of the QuickJS bytecode itself.

### 2.4 The pokemod-injector binary contains plaintext Frida JS

`pokemod-injector-arm64` (50 MB) contains the Frida runtime. Inside its read-only data section are 7 long printable-ASCII blobs of total ~290 KB:

| Blob size | Identity |
|---|---|
| 241,261 B | Frida Java bridge (java.js compiled - `Java.use`, `Interceptor.attach`, classFactory etc.) |
| 19,764 B (x2) | Frida's `frida-system-server-agent.js` (process listing, application enumeration) |
| 3,134 B (x2) | Frida droidy startup helpers |
| 3,061 B (x2) | More Frida glue |

**None contain iPogo-specific feature strings.** They are stock Frida runtime libraries linked into the injector. Saved as `injector_js_extracts.txt` for completeness.

### 2.5 libconceal.so identity

`libconceal.so` (267 KB, in iPogo launcher's lib dir, also loaded into launcher process at runtime): pure **Facebook Conceal** library (`com.facebook.crypto`). All its exported symbols are `Java_com_facebook_crypto_*`. AES-GCM + PBKDF2. Used by iPogo launcher for its own SharedPreferences-style encrypted KV (Hawk2.xml). Has no role in `libnotmain.so` decryption.

### 2.6 libfancier.so identity

`libfancier.so` (47 KB, alongside libconceal in launcher lib dir): tiny stub library, exports `Java_Init_Init`, `Java_Init_Context`. Most strings are libc/libdl/libz function names. No decryption logic.

---

## 3. Existing memory dumps - re-mined for iPogo signatures

Two on-device dump directories from previous sessions:
- `/data/local/tmp/pogo_dump/` - 66 files (88 MB compressed) of PoGo scudo-allocator regions, captured one PoGo session ago.
- `/data/local/tmp/pogo_anon/` - 40 files of anonymous mapped regions from same session.

Searched all for: `libnotmain`, `pokemod`, `set_freezepokemon`, `release_pokemon`, `IPokemonBag`, `mass_transfer`, `bulk_rename`, `auto_transfer`, `INSERT INTO Filter`, `\{cp\}`, `\{iv\}`, `iPogo`, `Niantic.Holoholo`, `is_lucky`, `min_iv`, `min_cp`, `metrics.pokemod`, `pokemod.dev`.

Hits found:

| Dump file | Pattern | Count | Verdict |
|---|---|---|---|
| pogo_dump/r015 | `Niantic.Holoholo` | 1 | PoGo IL2CPP class names |
| pogo_dump/r018 | `Niantic.Holoholo` | 1 | PoGo IL2CPP class names |
| pogo_dump/r023 | `is_lucky`, `min_cp` x1, `max_cp` x2 | 4 | PoGo `Pokemon` proto field names |
| pogo_anon/a026 | `Niantic.Holoholo` | 83 | PoGo IL2CPP heap |
| pogo_anon/a028 | `Niantic.Holoholo` | 3311 | PoGo IL2CPP heap (likely the type-name pool) |
| pogo_anon/a030 | `Niantic.Holoholo` | 763 | PoGo IL2CPP heap |

**All hits are Pokemon GO's own data**, not iPogo. The `is_lucky` / `min_cp` / `max_cp` strings live in PoGo's protobuf descriptors for badge/quest progression (visible context: `WithFortIdProto`, `WithRaidLocationProto`, `WithEncounterTypeProto`, `BuddyLevel`, `CombatType`, `friend_location`, `min_buddy_level`).

**Conclusion:** the previous-session dumps were also taken with iPogo not injected. The 9.4 MB encrypted blob has never been captured live in this codebase.

---

## 4. iPogo command surface (consolidated from `.rodata`, no new entries beyond v1)

Definitive list of plaintext iPogo commands embedded in `libnotmain.so` `.rodata` (the ones NOT encrypted). These are the function/command tags iPogo's mod uses internally:

### 4.1 Feature setters (toggle/state APIs)

```
set_arplus              - AR+ throw helper
set_autoconnectvgp      - VGP server auto-reconnect
set_boostspawn          - spawn-boost (modifies map encounter table)
set_ButtonsVisible      - hide/show on-screen iPogo button overlay
set_challenge           - account challenge bypass (anti-cheat token)
set_fastmap             - fast-loading map tiles
set_files_dir           - filesystem path init (probably IO base path)
set_freezepokemon       - freeze pokemon-on-map (despawn freeze)
set_mappings            - ?
set_shinyscanner        - shiny notification scanner
set_skip_animations     - skip animations (spin/throw/etc)
set_skip_team_leader    - skip team-leader cutscene (raid)
set_skip_team_rocket    - skip Team GO Rocket cutscenes
set_spin                - autospin pokestops
set_text                - generic text setter (probably for nickname or chat)
set_throw               - throw style (curveball/excellent/etc)
set_VisibleOnMap        - control visibility on the map
```

### 4.2 Action commands

```
release_pokemon         - transfer one pokemon (single)
b_hook                  - install hook (internal)
ball_check              - ?
attest                  - PlayIntegrity attestation handler
nativeAttestResponse    - PlayIntegrity attestation response
```

### 4.3 Anti-cheat / Niantic-bypass

```
com/nianticlabs/nia/contextservice/ContextService     - hooked to forge ContextService
com/nianticlabs/nia/platform/PlayIntegrityService     - hooked to fake PlayIntegrity
com/nianticlabs/nia/platform/SafetyNetService         - hooked to fake SafetyNet
com/nianticproject/holoholo/nativelib/Library         - hooked Niantic native lib
niantic/Swirlix          (also: "cannot find class niantic/Swirlix")  - obfuscated Niantic class iPogo expects to hook
```

### 4.4 Hook framework error messages

```
Can not hook this method: %s
Method %s NOT for hooking
Method '%s' not found for hooking
Too many hooks, increase MAX_HOOKS
class1: can't find %s on %s
oldinstance: %s
PogoInject/vpgp
```

### 4.5 String `iPogo`

Found exactly **once** in `.rodata` at offset 0x81f0f - this is the log tag.

### 4.6 What is **NOT** in plaintext rodata (and is therefore in encrypted .data)

Searched and **not present** anywhere:

- `mass_transfer`, `bulk_transfer`, `auto_transfer`, `transfer_all`, `transferList`, `transferQueue`, `bulk_release`, `release_all`, `release_many`
- `bulk_rename`, `mass_rename`, `auto_rename`, `rename_pokemon`, `set_nickname`, `setNickname`, `update_nickname`
- Format tokens `{cp}`, `{iv}`, `{atk}`, `{def}`, `{sta}`, `{name}`, `{species}`, `{level}`, `{pokemon}` - none.
- Filter operators: `min_iv`, `max_iv`, `min_cp`, `max_cp` (the .rodata hits we found are PoGo's own, not iPogo's), `is_shiny`, `is_lucky`, `is_traded`, `is_purified`, `iv_min`, `iv_max`
- SQL templates: `INSERT INTO Filter`, `UPDATE Filter`, `SELECT * FROM Filter` etc (no SQL DDL/DML strings except the schema definition Hawk uses)
- HTTP API endpoints to ipogo backends beyond `https://ipogo.app/`

---

## 5. Cross-reference to iPogo.db

`iPogo.db` schema (re-confirmed from previous extraction):

```sql
CREATE TABLE Filter     (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, settings TEXT);
CREATE TABLE Items      (id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT UNIQUE, amount INTEGER);
CREATE TABLE Journal    (...);
CREATE TABLE Last       (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, latitude FLOAT, longitude FLOAT);
CREATE TABLE Preference (feature TEXT UNIQUE, value INT);
CREATE TABLE Route      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, gpx TEXT);
```

Live data in `Filter` table: 1 row (`raidLevelIds`, CSV of int IDs). Live data in `Preference`: 9 rows of toggles (`ARPlus=1, freezePokemon=1, ...`).

**No new keys revealed by v2 analysis**, since no new strings were decrypted. The keys we know about match 1:1 with plaintext setters in `.rodata`:

| .rodata setter | iPogo.db Preference key |
|---|---|
| `set_arplus` | `ARPlus` |
| `set_freezepokemon` | `freezePokemon` |
| `set_throw` | `Throw` |
| (no setter found) | `CatchPreview`, `Curveball`, `EnhancedThrow`, `HideUIs`, `doubleTapToTeleport`, `tapToWalk` |

The ones without matching setters (CatchPreview, Curveball, etc) are likely Java-side flags handled by the launcher before injection, or tied to setters whose names are encrypted.

`Filter.raidLevelIds = '15,14,13,12,11,9,8,7,6,5'` corresponds in spirit to no plaintext-visible setter. It's likely set by encrypted code not in our visibility.

---

## 6. Recommended next steps to actually obtain runtime decrypted .data

In priority order:

### 6.1 (Easiest, ~30 sec when done) - User unlocks phone, taps iPogo Launch, then run dump

Once iPogo is injected, the dump is straightforward: re-run `phone_dump_scudo.sh` or do it specifically for libnotmain.so:

```bash
# After iPogo is injected:
PID=$(pidof com.nianticlabs.pokemongo)
adb shell "su -c 'grep libnotmain /proc/$PID/maps'"
# Note the start-end addresses, then:
adb shell "su -c 'dd if=/proc/$PID/mem of=/data/local/tmp/libnotmain_runtime.bin \
                       bs=1 skip=\$((16#START)) count=\$((16#END - 16#START))'"
adb pull /data/local/tmp/libnotmain_runtime.bin
strings -n 8 libnotmain_runtime.bin | grep -iE 'transfer|rename|filter|\{cp\}|\{iv\}'
```

The whole dump-and-string-extract chain works once the library is mapped at a known address.

### 6.2 Frida-driven injection without iPogo's launcher

Skip iPogo's UI entirely and do the injection ourselves:

```bash
# Start frida-server (already on device):
adb shell "su -c '/data/local/tmp/frida-server &'"
# Then from host:
frida -U -n com.nianticlabs.pokemongo -e 'Process.enumerateModulesSync().forEach(m => console.log(m.name, m.base, m.size))'
```

This gives us full enumeration of mapped modules. To force libnotmain.so injection without iPogo's launcher, we can dlopen it ourselves from Frida:

```javascript
const dlopen = new NativeFunction(Module.getExportByName('libdl.so', 'dlopen'), 'pointer', ['pointer', 'int']);
const path = Memory.allocUtf8String('/data/local/tmp/libnotmain.so');
const h = dlopen(path, 1);  // RTLD_LAZY
```

After this returns, libnotmain.so's init routine runs (which decrypts `.data` in-place). Then enumerate the module's `.data` segment and dump it via `Memory.readByteArray`. **This is the cleanest path that doesn't require interactive UI.**

### 6.3 Reverse the decrypt routine and emulate

Find the decryptor in `.text` (look for AES-S-box references, key-schedule patterns), then run it in unicorn-engine on the static `.data` blob. High effort, but completely offline and reproducible.

The starting point for finding the decryptor: `xrefs to .rodata @ 0x96f78` (the AES sbox). Any function in `.text` that loads this pointer + iterates 16-byte chunks of `.data` is a decryption candidate. Likely called from `.init_array` (16 bytes of init pointers at offset 0x6638e0).

---

## 7. Artifacts produced this session

All saved in `pogo_extract/`:

| File | Contents |
|---|---|
| `pokemod_maps.txt` | `/proc/27692/maps` from iPogo launcher process |
| `pogo_maps_live.txt` | `/proc/12581/maps` from PoGo (pre-relaunch) |
| `pokemod-injector-arm64` | Pulled iPogo injector binary (50 MB Frida-based) |
| `pokemod-injector-strings-arm64.txt` | `strings -n 12` of injector |
| `injector_js_extracts.txt` | Long-form Frida JS embedded in injector (no iPogo logic) |
| `libfancier.so` | Pulled from launcher's lib dir |
| `libfancier_strings.txt` (implicit) | Tiny stub lib, no signal |
| `libconceal_strings.txt` | Conceal AES-GCM library symbols |
| `main_agent_decoded.bin` | Base64-decoded encrypted Frida agent (2.2 MB ciphertext) |
| `vpgp_agent_decoded.bin` | Base64-decoded encrypted VGP-side agent (260 KB ciphertext) |
| `pokemod_ui.png` | Black screen (lockscreen confirmed) |

Note: `libnotmain_runtime.bin` and `ipogo_runtime_strings.txt` were **not produced** because injection was blocked by lockscreen.

---

## 8. TL;DR

- **iPogo was not injected during this analysis.** Cause: PoGo started clean from zygote (no ptrace tracer, no libnotmain.so in maps). iPogo's launcher requires a UI tap to trigger ptrace injection, and the device was locked.
- **No new feature surface was decrypted.** The 9.4 MB `.data` blob in `libnotmain.so` remains opaque; structural analysis confirms it is AES-encrypted (one full S-box found in `.rodata`, no T-tables, perfect random entropy). The two Frida agents (`main_agent`, `vpgp_agent`) share a 511-byte ciphertext prefix consistent with a fixed envelope, then diverge - they are independent encrypted payloads with the same encryption envelope.
- **Plaintext command surface remains as found in v1**: 17 `set_*` setters, `release_pokemon` (single, no bulk), 4 anti-cheat hook targets (PlayIntegrity, SafetyNet, ContextService, Holoholo native lib), and the `niantic/Swirlix` obfuscated class hook target.
- **All "iPogo features" hits in existing memory dumps are false positives** - they are PoGo's own protobuf field names (`is_lucky`, `min_cp`, `max_cp`) and IL2CPP class names (`Niantic.Holoholo.*`), not iPogo strings.
- **Cleanest path forward** to decrypt: run frida-server, attach to PoGo, dlopen `libnotmain.so` from a Frida script (so init_array runs and decrypts `.data`), then `Memory.readByteArray` the decrypted region. This requires no iPogo launcher UI and no biometric unlock. Estimated 5-15 min once frida-server is started.

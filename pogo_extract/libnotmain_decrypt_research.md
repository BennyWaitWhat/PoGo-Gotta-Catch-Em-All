# libnotmain.so .data Decryption - Static Reverse-Engineering Research

Date: 2026-05-08
Time budget: 90 min (used)
Approach: Read-only static analysis of libnotmain.so, libconceal.so, libfancier.so, ipogo_extracted/injector

## Verdict

**No.** Offline AES decryption of `libnotmain.so` `.data` is **not feasible**, because the prior assumption was wrong.

The 8.5 MB high-entropy bulk in `.data` is **not encrypted plaintext that gets decrypted at load**. There is **no decryption routine called from `.init_array` or any other startup path that operates on the bulk region.**

## Evidence

### 1. AES is present but unused for `.data`

- AES-128 forward S-box at vaddr `0x96f78` and Rcon table at `0x97078` confirmed in `.rodata`.
- Full AES-128 implementation lives at:
  - `0x5ea4d0` AES_KeyExpand
  - `0x5ea878` AES_block_encrypt (10 rounds, AddRoundKey -> 9*[SubBytes/ShiftRows/MixColumns/AddRoundKey] -> SubBytes/ShiftRows/AddRoundKey)
  - `0x5ea944` AES_block_decrypt
  - `0x5eaaf8` AES_CBC_decrypt loop
  - `0x5eac10` AES_CBC_encrypt loop
  - `0x5edec0` AES context constructor
- All these routines are reachable, but **none are called from `.init_array`** (BFS depth 4 from all 32 init entries: 212 reachable functions, none of them is in the AES family).
- The AES implementation is C++-virtual-call-only (no direct BL call sites in init), so it is iPogo's **runtime communication crypto** (likely VGP session encryption with the iPogo server, called per-message), not a bulk-decrypt-on-load primitive.

### 2. The `.init_array` does not bulk-decrypt anything

- 32 init_array entries (relocated to `0x3bbaa4 .. 0x5e30e4`) are standard C++ static-storage constructors. Every one ends with a single short BL into a low-numbered helper (e.g. `0x3bbaa4: bl 0x3bba80; ret`).
- Of the 212 functions reachable from `.init_array` at BFS depth 4, **only 4 contain ADRP+ADD targeting the encrypted bulk**, and those 4 are vtable / atomic-pointer reads at the *boundary* of the cleartext region (e.g. `0x1a27e8 -> 0x6673d0` is a single C++ static-init `__cxa_atexit` registration, not a loop).
- No function in init reachability touches more than 4 distinct addresses inside the bulk.

### 3. The bulk is overwhelmingly not used by code

Across the entire `.text` section, ADRP+ADD (and ADRP+LDR) xrefs into the encrypted bulk (vaddr `0x6673d0..0xee63d0`, ~8.5 MB):

- **50 unique target addresses, 108 total xref instructions.**
- For comparison, the 257 KB cleartext region at `0xee63d0..0xeed3d0` and `0xf363d0..0xf703d0` receives 1325+155 = 1480+ unique xrefs and is the target of 1885 RELATIVE relocations.

If 8.5 MB of plaintext were genuinely needed by libnotmain's code, we would see thousands of xrefs distributed across it. We see ~50, all clustered near the cleartext boundary.

### 4. There is no external decryptor either

Sibling libraries shipped in the same APK:

- `libconceal.so` (267 KB): Facebook Conceal NativeGCMCipher / NativeMac / OpenSSL JNI wrapper. Used from Java, not for bulk decrypt of libnotmain.so.
- `libfancier.so` (47 KB): APK signature verifier / `/proc/self/maps` scanner / `base.odex` / `base.vdex` validator. Anti-tamper module.
- `ipogo_extracted/injector` (23 KB): ptrace-based `dlopen` injector. Just loads libnotmain.so via `__loader_dlopen` after attaching to the PoGo process. Does not modify libnotmain.so contents on the file system, and does not write into `.data` after dlopen.

None of these reads or writes the encrypted bulk of `.data`.

### 5. The bulk's properties are consistent with random padding / unused space, not stored ciphertext

- Whole-section Shannon entropy: 7.9912 bits/byte. Per-64KB chunks: 7.999 bits/byte (essentially perfectly uniform).
- Coefficient-of-variation on byte frequency in the first 64KB: 0.0657 - perfectly uniform. No XOR-with-skewed-key signature at any tested period (16, 32, 64, 128, 256, 512, 1024).
- No magic numbers anywhere (no zstd `28 b5 2f fd`, no gzip, no zip, no embedded ELF, no DEX).
- All 4096 16-byte blocks in the first 64KB are unique - no repeating ciphertext blocks.
- LOAD program header 3 maps `.data` with `FileSize = MemSize = 0x913510`, so the file image is what hits memory; no zero-fill expansion.

### 6. The two cleartext sub-regions are normal program data

- `0xee83d0..0xeeb3d0` (~12 KB): JIT-style trampoline stub at `0xee8b50` (`1f2003d5 1f2003d5 1f2003d5 1f2003d5  49 00 00 58  20 01 1f d6  cafebabe cafebabe` = 4 NOPs, `ldr x9, [pc+8]; br x9; <pointer-placeholder>`). One stub only; the rest of the "cleartext" is zero-pad.
- `0xf363d0..0xf703d0` (~232 KB): zero-pad, no relocations into it.

These are the only regions code references; they account for 2.7% of `.data`.

### 7. What the bulk most plausibly is

Given (a) iPogo's anti-analysis posture, (b) the fact that `libnotmain.so` is shipped as `assets/libnotmain.so` (not extracted by the linker), and (c) the bulk is loader-mapped but code-untouched, the most consistent reading is **anti-analysis padding**: a bytestring of random data designed to defeat strings-based reverse-engineering tools and inflate the analyst's surface area. It increases the file size, blows up the entropy of `.data`, and yields nothing when string-extracted.

A weaker secondary possibility: it's reserved space that some VGP session code populates after server handshake (which is why the AES primitives exist). But there is no static evidence of that path either - no function takes a buffer pointing into the bulk.

## What this means for the original goal (hidden filter / bulk-rename / mass-transfer surface)

Section 7 of `ipogo_features.md` framed the question as "the feature surface lives in encrypted .data, decrypt it and grep." This research overturns that frame:

- The encrypted `.data` does not contain UI strings, filter grammar, or SQL templates that get decrypted at load.
- The "missing" features (mass-transfer, bulk-rename, bag filter) are missing because **they are not present in `libnotmain.so` as plaintext under any decryption** - not because we lack the key.

Static analysis cannot find these features because they don't exist in the static binary. The cleanest paths forward are the dynamic ones already enumerated in the prior report (Frida hooks on `IPokemonBag_ReleasePokemon`, runtime UI inspection, server traffic capture).

## Why no POC `decrypt_libnotmain.py`

A POC would require (a) the algorithm and (b) the key. We confirmed AES-128 primitives but cannot tie them to a `.data` decryption call site, and there is no key material recoverable from `.text` or `.rodata` for a `.data` decryption that does not appear to occur.

If a future dynamic dump of `.data` after libnotmain.so is fully initialized in the PoGo process **is byte-identical to the static `.data`** (as the file-size / mem-size match implies), this hypothesis is confirmed: the bulk is never decrypted, only allocated.

## Step that blocks further offline work

Step 4 (decrypt offline) cannot proceed because Step 1 has no positive answer: there is no decryption routine in `libnotmain.so` that reads from `.data[0x6673d0..0xee63d0]` and writes back to it, in `.init_array` reachability or anywhere else (verified by full `.text` ADRP scan and BFS of init entries to depth 4).

The way to falsify this verdict is to (a) capture a memory snapshot of `libnotmain.so`'s `.data` from a running PoGo+iPogo process, (b) byte-compare to the static file. If they differ, something *is* mutating `.data` at runtime and the search needs to widen (likely to indirect / vtable / function-pointer-table calls that BFS through BL only would have missed). If they match byte-for-byte, the bulk is permanent dead weight and there is nothing to decrypt.

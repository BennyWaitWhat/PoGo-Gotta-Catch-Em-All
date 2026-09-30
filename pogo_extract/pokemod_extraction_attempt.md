# Pokemod PvP rank cache extraction - final attempt

**Date:** 2026-05-10
**Outcome:** No persistent UID-keyed rank cache exists in any Pokemod-controlled memory. Move forward with computed ranks (`pvp_rank_v2.py` / `compute_all_ranks.py`).

## Summary

Pokemod renders `PvP Rank: <N>` on the pokemon detail page **on demand**, computing
the value when the detail page is opened and discarding it when the page closes.
There is **no per-pokemon cache** to extract. The only "PvP Rank:" string in
memory is for the **single currently-displayed pokemon** at the moment of scan.

Computed ranks via `pvp_rank_v2.py` are the right path forward.

## What I tried

### 1. Scanned PoGo's process memory (PID 11320) for 10 known UIDs
Used Frida via gadget on `127.0.0.1:27047`. Scanned all `rw-` ranges (anon and file-backed) for each test UID's 8-byte LE pattern. Test UIDs sampled from `auth_tag_names LIKE '%test%'` and other in_bag pokemon with known computed `gl_rank`/`ul_rank`.

**Result:** UIDs DO appear in PoGo's memory, but only in the ranges `0x795a000000+` (PoGo's IL2CPP managed heap with `[anon:dalvik-...]` backing) and a couple adjacent dalvik regions. Stride analysis showed UIDs at strides 48/128/256 bytes - these are PokemonProto instances in the bag (sizeof PokemonProto ≈ 320B + alignment), NOT a Pokemod cache.

Bytes around each UID hit: at offset +12 from UID, all entries have `u16=121` (a PokemonProto field, likely a pokemon_id or family value), and offsets +8 and +10 are pointer-like. No 0-4096 range u16 at any offset matches the known gl/ul ranks. Aggressive offset search across all multi-UID ranges found zero offsets where 2+ UIDs match their computed rank.

Files: `scan_pokemod_rank_cache.py`, `scan_pokemod_rank_cache_v2.py`, `_scan_rank_cache.log`, `_scan_rank_cache_v2.log`.

### 2. Scanned pokemod-injector process memory (PIDs 11445, 13945)
Pokemod-injector runs as a **separate root process** at `/data/data/com.pokemod.app.public/files/injector/pokemod-injector`. It's actually the Frida (Floyd) framework - the binary contains `Floyd.Inject.ScriptRunner`, `Floyd.Session`, etc.

Started `frida-server` on the device (port 27042), attached via USB device, scanned all `rw-` regions in both injector PIDs.

**Result:** ZERO UID hits in either pokemod-injector process. The injector binary itself contains no `"PvP Rank: "`, `"pvpBtnLabel"`, `"GreatLeague"`, `"UltraLeague"`, `"1500"`, `"League"` strings (verified with binary grep against `pokemod-injector-arm64`). The injector is the Frida driver, not the rank renderer.

Files: `scan_injector_memory.py`, `_scan_injector.log`.

### 3. Scanned Pokemod APP process memory (com.pokemod.app.public, PID 10442)
Attached Frida to the Pokemod app process directly via USB device. Scanned all `rw-` ranges for UIDs and for the literal `"PvP Rank"` string.

**Result:** ZERO UID hits AND ZERO `"PvP Rank"` string hits. The Pokemod APK is purely the launcher/settings UI; runtime rendering does not happen here.

Files: `scan_pokemod_app.py`, `_scan_pokemod_app.log`.

### 4. Examined the 4 `"PvP Rank: "` hits in PoGo memory in detail
The 4 hits live in **anonymous rw heap regions** that look like V8/JavaScript engine heap (HeapObject pointer markers `fzy`, `i4{`, `Z;z`, `gzy` in surrounding bytes - these are V8 small-integer / pointer encodings):

| Address | Range | Content |
|---|---|---|
| `0x797a665b40` | 0x797a600000+1.5MB | `PvP Rank: {rank}::{"rank":10}` - V8 template-binding cache key with resolved value |
| `0x7a3b48cfea` | 0x7a3b282000+2.1MB | `pvpBtnLabel:"PvP Rank: {rank}",pvpBtnDesc:"Transfer Pokémon ranked below {rank} in PvP."` - JS source/literal |
| `0x7b34884298` | 0x7b34640000+2.5MB | `PvP Rank: 10` - the rendered display string for the currently-shown pokemon |
| `0x7c2f251650` | 0x7c2f190000+960KB | `pvpBtnLabel...PvP Rank: {rank}...pvpBtnDesc...Transfer Pokémon...` - parsed JS table |

Searched the same V8-heap range for "PvP Rank: 1", ..., "PvP Rank: 100" - **only "PvP Rank: 10" exists**. That's the single currently-displayed value.

Files: `examine_pvp_rank_hits.py`, `examine_render_buffers.py`.

### 5. Verified V8 heap holds no UID-keyed structure
Searched the V8-heap regions (the 4 anonymous rw ranges identified above) for each of 10 test UIDs in three encodings:
- UTF-16 LE decimal string (V8 string format)
- ASCII decimal string
- ASCII hex (lowercase + uppercase)

**Result:** ZERO hits across all 10 UIDs and all 3 encodings.

Files: `scan_v8_heap.py`, `_scan_v8_heap.log`.

## Conclusion: Pokemod's rendering architecture

Based on this evidence:

- Pokemod uses an embedded **V8 JavaScript engine** running inside PoGo's process (injected via Frida gadget on port 27047). The "PvP Rank: {rank}" template binding and the "Transfer Pokémon ranked below {rank} in PvP" config are JS strings.
- When the user opens the pokemon detail page, Pokemod's JS code:
  1. Reads the displayed pokemon's IVs/species from PoGo's IL2CPP heap (likely via Frida hooks),
  2. Computes the rank inline (probably reusing PvPoke's algorithm),
  3. Renders "PvP Rank: <N>" via Unity overlay or modified IL2CPP UI text,
  4. Discards the value when the page closes.
- There is **no persistent UID -> rank map** in any process's memory. The single "PvP Rank: 10" we see is just the on-screen value; if I'd had a different pokemon open, I'd see that one's rank instead.

This matches Pokemod's architecture (JS-based modding via V8) and explains why the binary has no `League`/`1500`/`stat_product` strings - those constants live in JS strings inside encrypted/packed JS bundles loaded at runtime.

**The shipped `pvp_rank_v2.py` (PvPoke gamemaster + standard stat-product algorithm) IS the same algorithm Pokemod uses; computed ranks should match.** Spot-check: scan 5 test pokemon, open them in the Pokemod UI, confirm the displayed rank matches our computed rank.

## Why the "obvious" approaches failed

- **No HashMap/array structure**: heap-scan would have found one if it existed. There's nothing to dump.
- **Hooking `il2cpp_string_new` / `String.Concat` / `String.Format`** (per `dig_pokemod_v2.py`): the rank string is allocated by V8, not IL2CPP, so these hooks miss it.
- **Pokemod-injector binary**: pure Frida framework. Contains no rank logic at all.
- **Pokemod app process**: launcher/settings only. No runtime rendering, no UIDs.

## Path forward

1. Use computed `gl_rank`/`ul_rank`/`ll_rank` from `pvp_rank_v2.py` and `compute_all_ranks.py`.
2. To validate: pick ~10 pokemon spanning rank 1-4096, open each in Pokemod, eyeball the displayed rank.
3. If discrepancies appear, the issue is the algorithm (CPM table, base stats, evolution-stage selection, shadow multiplier) - NOT a missing cache.

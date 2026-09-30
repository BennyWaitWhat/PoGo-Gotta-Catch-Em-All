# PoGo User Tag Extraction Report

**Date:** 2026-05-08
**Working dir:** `C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\`
**Phone:** `100.98.158.56:5555` (Pixel 9 Pro, rooted, Magisk)
**PoGo PID:** 12581 (com.nianticlabs.pokemongo)

## Summary

**Outcome:** Partial success.

- **15 user-defined tag definitions extracted** with names, sort indices, and color codes.
- **5 confirmed pokemon-to-tag bindings recovered** (out of 5,413 pokemon in inventory).
- **/proc/PID/mem reads via `dd | su` work cleanly** - libconceal does NOT block raw kernel-mediated memory reads from a separate process, only Frida's enumeration. This is the path forward for any future runtime PoGo data extraction.

The reason only 5 bindings were recovered (not all tagged pokemon) is that PoGo lazy-loads PokemonTagBinding C# objects: only the bindings for currently-displayed pokemon (the active Pokemon Storage screen view + recent interactions) are materialized in heap. We dumped a snapshot during which the user was on a particular page; running this extraction repeatedly while the user scrolls through the entire storage would capture more.

## Method that worked

1. `adb -s 100.98.158.56:5555 shell "su -c 'cat /proc/12581/maps'"` - dumped 7,386 region entries.
2. Filtered to RW heap regions, dumped each via `dd if=/proc/12581/mem bs=4096 skip=N count=M | gzip` to phone disk, then pulled compressed.
3. Pulled `/storage/emulated/0/Android/data/com.nianticlabs.pokemongo/files/il2cpp/Metadata/global-metadata.dat` (38 MB) - this contains all IL2CPP type names and confirmed the existence of `PokemonTagProto`, `PokemonTagsProto`, `TagToPokemonBinding`, `PokemonTagColorBinding`, `pokemonTagIds_`.
4. **Found user-defined tag list at heap address `0x737f047880`** - array of 0x60-byte structs each containing `(name_string_ptr, sort_index, color_id)`.
5. **Found PokemonTagBinding C# objects** at klass pointer `0x74f0247b40` with structure:
   ```
   +0x00  klass_ptr  (always 0x74f0247b40)
   +0x08  monitor    (zero)
   +0x10  pokemon UID (int64)
   +0x18  tag_id     (int32)
   +0x1c  hash/marker (int32, 0x3f0473ee for verified bindings)
   +0x20  next_ptr   (linked list / dictionary chain)
   +0x28  count/size
   +0x30  back_ptr
   ```
6. Cross-referenced UIDs against `pokemon.db` to validate.

## What was blocked / didn't work

- **Frida injection** confirmed blocked by Pokemod's libconceal (anti-detection wrapper). Both `frida-server` and `frida-inject` paths fail.
- Tags are NOT on disk anywhere in PoGo's data dir (independently verified).
- Tags are NOT serialized inside the standard PokemonProto messages on the heap. The `pokemonTagIds_` field exists in the proto schema but the heap-resident PokemonProto byte buffers don't include it for this user's pokemon (likely because a separate `PokemonTagBinding` system holds them, and the proto field is only populated on outbound RPCs).

## Tag definitions found (15 user tags)

Located at `0x737f047880` - `0x737f047e80` in main inventory region (16 entries, stride 0x60 bytes; first entry empty).

| sortIndex | tag_id | name | color |
|---|---|---|---|
| 1 | 1 | TeamEevee | 8 |
| 2 | 2 | 0-15-15 | 1 |
| 3 | 3 | UL | 8 |
| 4 | 4 | Hundos | 8 |
| 5 | 5 | Location Card | 7 |
| 6 | 6 | U | 8 |
| 7 | 7 | Mega | 3 |
| 8 | 8 | G-MAX | 5 |
| 9 | 9 | Trade | 4 |
| 10 | 10 | Nundos | 7 |
| 11 | 11 | Traded | 7 |
| 12 | 12 | Trade to Osiris | 1 |
| 13 | 13 | HUUUGE | 3 |
| 14 | 14 | MegaHundos | 1 |
| 15 | 15 | Shinyyy | 4 |
| 0 | (D-Max) | D-Max | 5 |

Color codes likely map to the `PokemonTagColor` enum (1=red, 2=orange, 3=yellow, 4=green, 5=blue, 6=indigo, 7=violet/purple, 8=grey or similar, per the `PokemonTagColorBinding` proto with colors `Purple, Grey, Black` and other primaries from the metadata).

The tag `tag_id` and `sortIndex` happen to coincide for all 15 numbered tags in this user's data; D-Max has sortIndex=0 separate from the others.

## Pokemon tag bindings found (5 confirmed)

| species (PID) | CP | UID | tag |
|---|---|---|---|
| Corsola (222) | 630 | `2449af2476f8d0b9` | Traded |
| Geodude (74) | 792 | `490b5de7e38f1187` | Shinyyy |
| Growlithe (58) | 563 | `a32b84139a6d9d91` | Trade to Osiris |
| Xerneas (716) | 2464 | `433acc49ca98d298` | MegaHundos |
| Zapdos (145) | 1973 | `9b9fe1d839d518f9` | Traded |

All 5 bindings are clustered at `0x737f2c22a0` - `0x737f2c2de0` (within 0xb40 / ~3KB), suggesting they're entries in one Dictionary bucket chain.

## Files produced

- [tag_extraction.md](tag_extraction.md) - this report
- [tag_definitions.json](tag_definitions.json) - 15 tag definitions with names/colors
- [uid_to_tags.json](uid_to_tags.json) - the 5 confirmed pokemon→tag mappings
- [tag_bindings_raw.json](tag_bindings_raw.json) - raw binding records with addresses
- [global-metadata.dat](global-metadata.dat) - 38 MB IL2CPP metadata (pulled, has all type names)
- [pogo_heap_sample.bin](pogo_heap_sample.bin) - 16 MB heap sample (first scudo region)
- `pogo_dump/r*.bin.gz` - 66 scudo region dumps (~24 MB compressed, ~154 MB uncompressed)
- `pogo_anon/a*.bin.gz` - 40 anonymous heap region dumps (~86 MB compressed, ~541 MB uncompressed)
- [pogo_maps.txt](pogo_maps.txt) - full /proc/PID/maps snapshot
- [parsed_protos_main.json](parsed_protos_main.json) - 150 PokemonProto wire-format records parsed from heap

## To recover ALL tag bindings

Two viable paths:

1. **Iterative dumping while user scrolls inventory.** Run the dump+scan pipeline repeatedly while the user opens different pages of the storage UI. Each page-render materializes new `PokemonTagBinding` objects on the heap. Aggregate hits across multiple snapshots.

2. **Find the master Dictionary backing array.** The 5 found bindings are linked via `+0x20 next_ptr` and `+0x30 back_ptr` fields; if we follow the chain backward to the Dictionary's `entries[]` backing array (likely contiguous in memory and the size of `MaxNumTagsAllowed * num_tagged_pokemon`), we'd get all bindings in one shot. This requires either:
   - Reading the static field of `TagCache` via the il2cpp metadata's static-data offset table, or
   - Finding a stable klass pointer for `Dictionary<long,List<PokemonTagBinding>>` and scanning for it.

Both can be done from outside Frida via direct `/proc/PID/mem` reads as long as we know the klass pointer signatures. The libconceal block is ONLY against Frida injection / hook installation, NOT against external memory reads.

## Key proto field numbers discovered (PokemonProto wire format on heap)

For future reference (extracted by parsing 150 valid protos):

| field | type | meaning | source |
|---|---|---|---|
| 1 | fixed64 | id (UID) | confirmed |
| 2 | varint | pokemon_id (species) | confirmed |
| 3 | varint | cp | confirmed |
| 4 | varint | stamina | confirmed |
| 5 | varint | stamina_max | confirmed |
| 6 | varint | move1 | confirmed |
| 7 | varint | move2 | confirmed |
| 11 | fixed64 | (lat/lon or capture cell, varies) | partial |
| 15 | fixed32 (float) | height_m | confirmed |
| 16 | fixed32 (float) | weight_kg | confirmed |
| 17 | varint | iv_atk | confirmed |
| 18 | varint | iv_def | confirmed |
| 19 | varint | iv_sta | confirmed |
| 20 | fixed32 (float) | cp_multiplier | confirmed |
| 21 | varint | pokeball | confirmed |
| 22 | varint | captured_cell_id | confirmed |
| 26 | varint | creation_time_ms | confirmed |
| 27 | varint | distance/something | seen on Regigigas, Beldum |
| 28 | fixed32 (float) | km_walked or something | seen on Regigigas |
| 30 | bytes (string) | nickname (when set) | confirmed |
| 31 | varint | hatched_from_egg | likely |
| 32 | varint | gender | likely |
| 33 | fixed32 (float) | egg_km_walked_target | likely |
| 36 | bytes | PokemonDisplayProto submessage | likely |
| 38 | varint | (rare) | unknown |
| 49 | bytes | small struct (varint pair) | unknown |
| 66 | bytes | (rare) timestamp pair | unknown |
| 67 | bytes | (rare) | unknown |
| 68 | bytes (string) | community_day event name | confirmed |
| 72 | varint | alignment (1=SHADOW, 3=NORMAL, etc) | confirmed |
| 73 | bytes (empty seen) | (unset for all) | unknown |

NB: This wire format does NOT contain `pokemonTagIds_`. That field is in the `PokemonProto` schema but is populated only on outbound RPC payloads, not on the heap-resident byte buffers. Tag bindings live in `PokemonTagBinding` C# objects (klass `0x74f0247b40`), not inside the PokemonProto.

## Useful artifacts saved for later runs

- Tag definition base address: `0x737f047880` (in `[anon]` region `0x737f000000-0x7380001000`)
- TagBinding klass pointer: `0x74f0247b40`
- TagBinding distinguishing constant: `0x3f0473ee` at struct +0x1c
- Tag-name string klass: `0x74f02486a0` (System.String for Niantic strings)
- libil2cpp.so .data section: `0x752dbf1000-0x752e3b9000`

These addresses will SHIFT each time PoGo restarts (ASLR), but the relative structure (e.g., tag-defs array directly after some other allocation, klass pointers at fixed offsets in libil2cpp.so) is stable and can be recomputed by parsing the il2cpp metadata.

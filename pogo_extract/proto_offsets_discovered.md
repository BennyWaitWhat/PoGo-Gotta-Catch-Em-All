# PokemonProto Offset Discovery Report

Method: statistical + cross-correlation against [pokemon.db](pokemon.db) known fields (5,413 pokemon, 512-byte raw_proto).

Working dir: `C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\`.

## Newly mapped offsets

### High confidence (cross-correlated with DB or strongly distinctive)

| Offset | Type | Field | Confidence | Evidence |
|--------|------|-------|------------|----------|
| **200** | float32 | `buddy_km_walked` | **HIGH** | 197 nz; 0.014-469 km; top values are level-50 best buddies (Kyurem 469 km, Mewtwo 350 km); float-only signature, never 0 for high-level BBs |
| **296** | byte (i32) | `is_purified` | **HIGH** | 52 byte=1; 51/62 known PURIFIED match (alignment from display also reads same bit). 1 false positive (Kyogre alignment=0). Plausible mismatch is partial-purification edge case |
| **336** | byte | `is_mega_evolved` | **HIGH** | 154 byte=1; 145/154 are mega-eligible species (Charizard, Blastoise, Gengar, Lopunny, Absol, Heracross, Diancie, Medicham, Sceptile, Swampert, Gallade, Scizor) |
| **340** | byte | `mega_evo_state` | **MED** | 17 byte=1, 19 byte=2 (within is_mega set); plausible "current_temp_evolution" enum (NORMAL / MEGA_X / MEGA_Y) |
| **344** | int32 | `mega_evolved_cp` | **HIGH** | 152 distinct positive ints in mega-evolved set; values 1212-3650 = mega-only CP values |
| **348** | float32 | `mega_evo_cpm_extra` | **HIGH** | 154 nz, all approximately 1.00-1.29 — mega evolution multiplier bonus over base CPM |
| **352** | float32 | `mega_evo_cpm` | **HIGH** | 155 nz; values exactly match official CPM table (0.094, 0.166, 0.215, 0.255 ...) — mega evolution effective CPM |
| **304** | string ptr (0x130) | `costume_decoration_id` | **HIGH** | Only 2 pokemon have content: PID 674 Pancham → `'season28_pancham'`, PID 562 Yamask → `'season28_gyamask'`. Seasonal cosmetic decoration string |

### Medium confidence (likely but not 100%)

| Offset | Type | Field | Confidence | Evidence |
|--------|------|-------|------------|----------|
| **144** | int32 | `numUpgrades` (or `battlesAttacked` count) | **MED** | 304 nz, range 1-4003. Top values all on best-buddy level-50 pokemon used in battles (Kyurem 4003, Zacian 2838, Palkia 2480). 185/304 are best buddies. Field name `numUpgrades_` exists in [field_names.txt](field_names.txt). 4003 is too high for power-up count, more likely `battlesAttacked`/total battle uses |
| **196** | int32 | `numPoweredUp` (or `buddy_walks_completed`) | **MED** | 121 nz, range 1-198. 119/121 also have buddy_km_walked (200) nonzero - strongly tied to buddy stats. Maxes around 200, fits power-up count 0-200 |
| **416** | int32 | unknown, `battlesDefended` candidate | **LOW** | 171 nz, distinct=171 (each is unique). Likely cumulative count or pointer leak, low correlation with known fields |

### Already-mapped offsets clarified (do not re-add)

- **252-255** = upper 4 bytes of `originalLocation` int64 at 248 (already mapped via `i64(248)`)
- **268-271** = upper 4 bytes of `tradedTimeMs` int64 at 264 (already mapped); apparent values 404-411 are just `ms >> 32` for 2024-2025 timestamps
- **192** = byte=1 for all 377 hatched + 181 others. Garbage / unrelated marker, do not map
- **488** / **492** = uninitialized stack data near proto end; no signal

## Key deductions about strings

- **0x40** (offset 64) = `deployedFortId` (string)
- **0xb8** (offset 184) = `nickname` (string)
- **0x100** (offset 256) = `originalOwnerNickname` (string)
- **0x130** (offset 304) = `seasonalCostumeDecorationId` / `cosmeticOverlayId` (string)
- **0x168** (offset 360) = unknown string field, ALWAYS empty for this user (probably `displayPokemonId` field's hidden string variant or a server-side label)
- **0x180** (offset 384) = same as 0x168, always empty

## Tags - NOT in PokemonProto, confirmed not on disk

User-set tags (red flag, gold star, etc) referenced as `pokemonTagIds_` in [field_names.txt](field_names.txt) are stored in a separate `PokemonTag` proto, not inside PokemonProto.

Verified absence on phone (`/data/data/com.nianticlabs.pokemongo/`):
- `app_database/` - only contains a single 7KB blob `792FB30D-3C11-4B1B-81F9-9402DDA5FAF7` (ARDK cache, not pokemon)
- `databases/` - only Google analytics, geofence, iPogo (mod), no Niantic-pokemon database
- `files/` - only Firebase/AppsFlyer/datastore, no pokemon storage
- `shared_prefs/com.nianticlabs.pokemongo.v2.playerprefs.xml` - 109 lines, zero "tag" references
- `find ... | grep "pokemonTag"` - zero matches across all of `/data/data/com.nianticlabs.pokemongo/`

**Conclusion**: PoGo holds tags in server-replicated memory only. To extract them, hook `Niantic.Holoholo.Pokemon.PokemonProto.pokemonTagIds_` (or sibling `PokemonTagProto`) at runtime via Frida and dump alongside the PokemonProto extraction. They will not appear in any local file.

## Mega evolution cluster - structure inferred

Bytes 336-356 form the `currentTempEvolution` sub-struct:

```
+336  byte  is_mega_evolved (1 = currently mega'd)
+340  byte  mega_evo_state    (1 = MEGA_X-style, 2 = MEGA_Y-style; only set on dual-mega species)
+344  int32 mega_cp           (CP while mega-evolved, e.g. Charizard 3650)
+348  float mega_extra_cpm    (multiplicative boost over base CPM, 1.00-1.29)
+352  float mega_cpm          (effective CPM after mega - matches CPM table exactly)
```

Offset 340 distinct value=1 only for 17 pokemon and value=2 for 19 - matches species that have two mega forms (Charizard X/Y, Mewtwo X/Y).

## Python dict ready to merge into `parse_proto()` in [build_final.py](build_final.py)

```python
NEW_OFFSETS = {
    # High-confidence additions
    144: ('numUpgrades_or_battlesAttacked', 'i32'),     # MED: counter, max 4003
    196: ('numPoweredUp_or_buddy_walks',    'i32'),     # MED: 1-198 range
    200: ('buddy_km_walked',                'f32'),     # HIGH: 0-1000 km float
    296: ('is_purified_flag',               'i32'),     # HIGH: 1 = purified (51/62 confirmed)
    336: ('is_mega_evolved',                'byte'),    # HIGH: 1 = currently mega
    340: ('mega_evo_state',                 'byte'),    # MED: 1=MEGA_X, 2=MEGA_Y enum
    344: ('mega_cp',                        'i32'),     # HIGH: CP while mega
    348: ('mega_extra_cpm',                 'f32'),     # HIGH: mega cpm boost (1.00-1.29)
    352: ('mega_cpm',                       'f32'),     # HIGH: effective mega CPM
}

# String pointers (decoded via existing strings dict in pokemon_v3.json)
NEW_STRING_OFFSETS = {
    '0x130': 'seasonal_costume_decoration_id',  # HIGH: 'season28_pancham' / 'season28_gyamask'
}
```

### Suggested parse_proto() patch

```python
def parse_proto(raw_hex):
    # ... existing code ...
    return {
        # ... existing fields ...
        # NEW
        'numUpgradesOrBattles':  i32(144),
        'numPoweredUpOrWalks':   i32(196),
        'buddyKmWalked':         f32(200),
        'isPurifiedFlag':        b(296),
        'isMegaEvolved':         b(336),
        'megaEvoState':          bs[340] if 340 < n else 0,
        'megaCp':                i32(344),
        'megaExtraCpm':          f32(348),
        'megaCpm':               f32(352),
    }
```

## Open questions / future work

1. **`numUpgrades` vs `battlesAttacked`** at offset 144 cannot be distinguished without ground truth. User has no DB for these but if you remember roughly how many raids you've used your Kyurem in vs power-ups, check if 4003 fits one or the other.
2. **`mega_expires_at_ms`** - not found in 336-512. May be stored in a parallel `currentTempEvolutionExpiryMs` field that is reset to 0 once mega expires (8h after activation). All 154 mega entries in this dump may be expired.
3. **`buddy_pokemon_id`** (i.e. is this pokemon currently set as buddy) - not found as a per-pokemon flag in PokemonProto. PoGo stores the current buddy at the player level (one buddy per player), so it's in PlayerData not per-pokemon.
4. **Tag/label data** is server-side; needs runtime Frida hook on the inventory response, not file extraction.

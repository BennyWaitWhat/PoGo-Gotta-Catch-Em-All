# PokemonProto Offset Discovery Report — V2

Continuation of `proto_offsets_discovered.md`. Method: byte-level statistical scan + cross-correlation against [pokemon.db](pokemon.db) (5,413 pokemon, 512-byte raw_proto).

Working dir: `C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\`.

## Summary of NEW findings (not in v1)

| Offset | Type | Hypothesized field | Confidence | NZ count | Validation |
|--------|------|---------------------|------------|----------|------------|
| **248** | f32 | `addedFriendshipScore_` | **HIGH** | 91 | 91/120 traded with non-zero, 1/5293 non-traded; values 0.0-0.73; varies per pokemon, not per owner. Example: Starmie f@248=0.7347 (max value) |
| **252** | i32 | `tradingOriginalOwnerHash_` | **HIGH** | 121 | 1 unique value PER original_owner (44 OyeBenny pokemon ALL have hash=1934650777, 9 peritomoreno15 pokemon ALL have hash=-1715453599). 1 anomaly: Hoothoot with hash=47 (likely uninit garbage) |
| **269** | byte | `is_traded_flag` | **HIGH** | 119 | 119/120 traded match (Jiggly outlier has corrupted bytes); 0/5293 non-traded false positives |
| **424** | i32 | `pokemon_size_category_` (XXS/XS/N/L/XL) | **HIGH** | 5369 | Confirmed via Pumpkaboo: weight 5kg→size=2, 7kg→size=3, 11kg→size=4, 13-17kg→size=5 (super-size form). Magikarp same: 9kg→3, 18-20kg→5. Distribution: 1=30 (XXS), 2=123 (XS), 3=4970 (NORMAL), 4=114 (L), 5=130 (XL) |
| **192** | byte | `is_special_acquisition_flag` | **MED** | 557 | 100% of hatched (377/377) + 180 non-hatched extras; 117/180 of extras are shiny, 32 traded, but no clean rule. Possibly `wasGiftReceived_` / `isReceived_` / `everInGym` (correlation with 2016+2025 creation dates) |

## Anti-findings (offsets that look promising but are NOT new fields)

| Offset | Why it looked promising | Why it's not new |
|--------|--------------------------|------------------|
| 277 | byte=1 for 82 (mostly BB) | These are upper byte of `i32@276 = move3` when move3 ID >= 256. Same field. |
| 280, 284, 288, 292 | i32 nz=274-624, looks correlated with powered_up | Upper bytes of `i64@264 traded_time_ms` and surrounding pointer fields - C# heap pointers, not data |
| 360, 368, 376, 384, 392, 416, 432, 456, 488 | i64 unique-per-pokemon | These are C# heap object pointers (high byte ~0x75/0x76 = stack/heap address). They point to sub-message objects (`PokemonDisplayProto`, `MoveSettings`, etc.), NOT scalar data |
| 268 | i32 in range 404-411 across 119 pokemon | Upper 4 bytes of `i64@264 traded_time_ms` (millis-since-epoch >> 32 ≈ 407 for 2024-2025) |
| 276 | i32 nz=248 small-range values | `move3` (already mapped). The 82 "byte277=1" pokemon have move3 ID >= 256 (newer moves like Aerial Ace=333) |
| 416, 420 | i32 nz=171 | Upper 4 bytes of i64 pointer at 416 (heap reference) |
| 488, 492 | i32 nz=700-700 | Same: i64 pointer at 488 (heap reference to extension data) |
| 16, 20 | i32 with bytes 0x72-0x77 high | C# vtable / klass pointer (object header). Not proto data. |
| 148 | i32 nz=23 vals 1-18 | UNCLEAR - too few samples to lock down. Could be `numTrainersDefeated_` per-week-counter or stat, but only 23 hits. **LOW confidence, do not map** |
| 176 | i32 nz=104 val=1 | UNCLEAR - mixed bag of pokemon, no clean DB correlation. **LOW confidence, do not map** |

## Reinterpretation of existing v1 mapping

**Offset 248 was previously labeled `originalLocation_` (int64).** This was technically correct at the int64 level (the bits ARE used as a location-like hash key). But the int64 is actually a **packed 2-field structure**:

- Lower 32 bits at +248 = `addedFriendshipScore_` interpreted as float32 (range 0.0-0.73)
- Upper 32 bits at +252 = `tradingOriginalOwnerHash_` interpreted as int32 (one constant per trader)

Validation: For 30 traded pokemon spot-checked, `original_location_hash` (from existing parser) reconstructs **exactly** as `f32(252)` concat `f32(248)` in hex. Per-owner `i32@252` is constant (1 distinct value across all 44 OyeBenny pokemon). Per-pokemon `f32@248` varies from 0 to 0.73, suggesting it's the trade-time friendship contribution.

These are MORE useful as separate fields than as a single packed hash.

## What was NOT found (anti-findings of attempted searches)

1. **`currentTempEvolutionExpiryMs`** (mega expiry timestamp) — not found anywhere in the 512-byte proto. All 154 currently-mega pokemon have only the substruct at 336-352 (state, cp, cpm). Hypothesis: when mega expires (8h after activation), Niantic clears the substruct and never stores expiry locally. To get the next-mega-eligible-time, hook the `nextMegaPossibleAtMs_` field at server-response level via Frida.

2. **`pokemonTagIds_`** (red flag, gold star, etc) — confirmed NOT in PokemonProto. List pointer search found no offset with the right shape (all 4-byte aligned slots are either heap pointers, scalars, or upper-bytes of 8-byte fields). Tags live in a parallel `PokemonTag` proto.

3. **`kmDistanceToHatch_`** — already mapped at offset 92 as `eggKmWalkedTarget` (f32). The 0.5km Pidgey eggs / 5km / 7km / 10km / 12km targets are stored there but only for hatched pokemon.

4. **`addedFriendshipScore_`, `initialFriendshipScore_`, `friendshipSourceType_`** — ONE of these is at f32@248 (0.0-0.73 range). Cannot distinguish which exactly; "added" most likely.

5. **List pointer for any repeated field** — not detected. PokemonProto has no inline-storage repeated field in this dump.

6. **`numUpgrades_` vs `battlesAttacked_`** at offset 144 — disambiguation attempt failed; per the v1 report the value range (1-4003) fits `battlesAttacked_` better than `numUpgrades_` (which would cap at ~80 power-ups).

## Unmapped string-pointer offsets

Already-mapped string pointers: `0x40` (deployedFortId), `0xb8` (nickname), `0x100` (originalOwnerNickname), `0x130` (seasonalCostumeDecorationId)

Confirmed-empty string pointers: `0x168` (offset 360), `0x180` (offset 384) - both have 0 nonempty across all 5413 pokemon

Probed but absent: 0x60, 0x80, 0xa0, 0xc0, 0xe0, 0x108, 0x118, 0x140, 0x150, 0x158 - none of these keys exist in the parsed `strings` dict in pokemon_v3.json. The 8-byte slots at these offsets ARE C# pointers in memory (e.g. offset 360, 368, 376, 384, 392 all have ~5400 unique pointer values like `0x75da2d73f0`) but they point to non-string sub-messages (move settings, capture details, display info).

## Validation examples (5 example UIDs per high-confidence finding)

### 269 = is_traded_flag
- 1389937042118799415 Pidgey (traded by ?)
- -2133657106957898130 Beedrill (traded)
- -5121075525600413510 Lickitung (traded by OyeBenny)
- -5268815121106058926 Ledian (traded)
- 7992126442434091890 Palkia (traded)

### 248 (f32) = addedFriendshipScore (top 5 values)
- 0.7347 — Starmie (uid 8979621816557407302)
- 0.7317 — Unown (6187154055053857915)
- 0.7069 — Kricketot (-250329507154074827, traded by OyeBenny)
- 0.6941 — Maractus (-1970109155917756524)
- 0.6679 — Spinarak (4749118558793719193, traded by Florandez)

### 252 (i32) = tradingOriginalOwnerHash (5 distinct trader hashes)
- hash=1934650777 → 44 pokemon traded by OyeBenny
- hash=-1715453599 → 9 pokemon by peritomoreno15
- hash=-1651325187 → 12 pokemon by Palkia-trader (likely "Palkia source")
- hash=-1025602254 → 3 pokemon by Florandez
- hash=-556890085 → 4 pokemon by YeetForKobe

### 424 = pokemon_size_category
- size=1 (XXS): -7433925423918024805 Gyarados (44.4kg = wild, but smallest in proto?)
- size=2 (XS): 6495067371666524342 Fuecoco (4.39kg = very small)
- size=3 (NORMAL): -3731517210835781245 Unown (1.89kg)
- size=4 (L): 7780324419376389025 Pikachu (9.7kg = larger Pikachu)
- size=5 (XL): 5112805191089922257 Pumpkaboo (13.3kg = super-size form)

## Python dict ready to merge into `add_extra_fields.py`'s parser

```python
# Add to NEW_OFFSETS:
NEW_OFFSETS_V2 = {
    248: ('added_friendship_score',        'f32'),     # HIGH: 0.0-0.73 trade boost; only nonzero on traded
    252: ('trading_original_owner_hash',   'i32'),     # HIGH: int32 hash, constant per trader (44 OyeBenny share same)
    269: ('is_traded_flag',                'byte'),    # HIGH: 119/120 traded match; alternative source for is_traded
    424: ('pokemon_size_category',         'i32'),     # HIGH: 1=XXS, 2=XS, 3=NORMAL (default), 4=L, 5=XL/XXL
    192: ('is_special_acquisition_flag',   'byte'),    # MED: hatched + 180 special; unclear meaning
}

# Note: existing 'originalLocation' i64(248) mapping is REDUNDANT with the new pair.
# Recommendation: keep existing i64(248) for backwards compat AND add the two new f32+i32 readings.
```

### Suggested parse_proto() patch for `build_final.py`

```python
def parse_proto(raw_hex):
    # ... existing code ...
    return {
        # ... existing fields ...
        # V2 NEW
        'addedFriendshipScore':    f32(248),  # f32 read of low half of original_location int64
        'tradingOriginalOwnerHash': i32(252),  # i32 read of high half
        'isTradedFlag':            b(269),
        'pokemonSizeCategory':     i32(424),  # 1=XXS, 2=XS, 3=NORMAL, 4=L, 5=XL/XXL
        'isSpecialAcquisition':    b(192),    # MED conf - special obtainment method
    }
```

### Suggested SQL columns to add

```sql
ALTER TABLE pokemon ADD COLUMN added_friendship_score REAL;
ALTER TABLE pokemon ADD COLUMN trading_original_owner_hash INTEGER;
ALTER TABLE pokemon ADD COLUMN is_traded_flag INTEGER;
ALTER TABLE pokemon ADD COLUMN pokemon_size_category INTEGER;
ALTER TABLE pokemon ADD COLUMN is_special_acquisition INTEGER;

-- Friendly size labels via update:
UPDATE pokemon SET pokemon_size_label = CASE pokemon_size_category
    WHEN 1 THEN 'XXS' WHEN 2 THEN 'XS' WHEN 3 THEN 'NORMAL'
    WHEN 4 THEN 'L'   WHEN 5 THEN 'XL'
    ELSE NULL END;
```

## Open questions / future work

1. **Offset 192** has the most surprising pattern: 100% of hatched + 180 specific non-hatched. The non-hatched 180 are split: 117 shiny, 32 traded, all unique species, mostly creation-date 2025-12 or 2016-08. Best guess: `wasInGym_` or `everPlayedWithBuddy_` historical flag. Needs runtime Frida hook on `Niantic.Holoholo.Pokemon.PokemonProto` field iteration to disambiguate.

2. **Offsets 148, 176** are real fields (i32 with stable distinct values) but DB column counts are too low (23 / 104) to triangulate against any known field. Skip mapping until more data arrives.

3. **Mega expiry timestamp** is provably absent from the 512-byte proto. Hook server response or check `MasterClientUserGetCorruption` for the next-mega-cooldown field at runtime.

4. **C# heap pointers** at offsets 360, 368, 376, 384, 392, 416, 432, 456, 488 point to sub-message objects. To extract those messages' fields, walk the pointer with a Frida memory-read. The 5,413 pokemon have ~5,400 unique heap addresses each, suggesting each pokemon has its own allocated sub-message instances (PokemonDisplayProto, captureDetails, moveSettings).

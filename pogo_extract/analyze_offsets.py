"""
Analyze v3 dump to find offsets for missing fields:
- shiny (look at distribution of bool offsets in display)
- traded fields (originalOwnerNickname pointer)
- mega level (currentTempEvolution)
- buddy walked, power-ups, battle stats
- isBad, fromFort, hatchedFromEgg
"""
import json, struct
from collections import Counter, defaultdict

data = json.load(open('pokemon_v3.json'))
print(f"Loaded {len(data)} pokemon")

# Analyze PokemonProto fields beyond offset 280
# Look at what offsets contain non-zero/non-default values
# Strings: examine all string pointers

# Find string pointers that are NEITHER empty (0x7b81c1cf40) NOR null
non_empty_strings = defaultdict(list)
for p in data:
    for off, val in (p.get('strings') or {}).items():
        if val == '': continue  # empty string
        if val and isinstance(val, list):
            ptr_hex, content = val
            if content:
                non_empty_strings[off].append((p['pokemonId'], content))

print("\n=== Non-empty strings by offset ===")
for off, items in sorted(non_empty_strings.items()):
    print(f"  Offset {off}: {len(items)} pokemon have a string")
    for sp, txt in items[:5]:
        safe_txt = txt.encode('ascii', errors='replace').decode('ascii')
        print(f"    Species #{sp}: '{safe_txt}'")

# Look at PokemonProto byte 280-512 distribution
# Aggregate non-zero values at each offset
print("\n=== PokemonProto byte distribution (280-512) ===")
offset_values = defaultdict(Counter)
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) < 600: continue  # need 300 bytes
    bytes_data = bytes.fromhex(raw)
    for off in range(280, min(512, len(bytes_data)), 4):
        if off + 4 > len(bytes_data): break
        v = struct.unpack_from('<i', bytes_data, off)[0]
        offset_values[off][v] += 1

# Find offsets with interesting variety
print("Offsets with diverse values (potential fields):")
interesting_offsets = []
for off in sorted(offset_values.keys()):
    counter = offset_values[off]
    distinct = len(counter)
    most_common = counter.most_common(3)
    nonzero = sum(c for v, c in counter.items() if v != 0)
    if distinct > 10 and nonzero > 100:
        interesting_offsets.append(off)
        print(f"  +{off:03d}: {distinct} distinct values, {nonzero} non-zero. Top: {most_common}")

# Look for INT64 fields (8-byte aligned)
print("\n=== int64 fields after offset 280 ===")
i64_offsets = defaultdict(Counter)
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) < 600: continue
    bytes_data = bytes.fromhex(raw)
    for off in range(280, min(504, len(bytes_data)), 8):
        if off + 8 > len(bytes_data): break
        v = struct.unpack_from('<q', bytes_data, off)[0]
        if v != 0:
            i64_offsets[off][v] += 1

# Identify int64 fields - timestamps will have specific value ranges
print("Offsets with timestamp-like int64 values (>1.5e12 = recent ms):")
for off in sorted(i64_offsets.keys()):
    counter = i64_offsets[off]
    big_vals = sum(c for v, c in counter.items() if 1.5e12 < v < 2e12)
    nonzero = sum(counter.values())
    if big_vals > 10:
        print(f"  +{off}: {big_vals}/{nonzero} look like timestamps")

# Analyze PokemonDisplayProto bytes for shiny
print("\n=== PokemonDisplay byte distribution ===")
display_offset_values = defaultdict(Counter)
for p in data:
    raw = p.get('display_raw') or ''
    if len(raw) < 200: continue
    bytes_data = bytes.fromhex(raw)
    # Look at every byte for bool patterns
    for off in range(16, min(64, len(bytes_data))):
        b = bytes_data[off]
        if b in (0, 1):
            display_offset_values[f'b_{off}'][b] += 1
    # Also int32 every 4 bytes
    for off in range(16, min(64, len(bytes_data)), 4):
        if off + 4 > len(bytes_data): break
        v = struct.unpack_from('<i', bytes_data, off)[0]
        display_offset_values[f'i_{off}'][v] += 1

# Look for bool-like distributions (0 or 1, mostly 0)
print("Bool candidates in display (>1% 1s, <50% 1s):")
for key, counter in sorted(display_offset_values.items()):
    if not key.startswith('b_'): continue
    zeros = counter.get(0, 0)
    ones = counter.get(1, 0)
    if zeros + ones < 100: continue
    if 0.005 < ones/(zeros+ones) < 0.5:
        print(f"  {key}: {ones} ones, {zeros} zeros ({ones/(zeros+ones)*100:.2f}% true)")

# For non-bool fields in display
print("\nInt32 values in display:")
for key, counter in sorted(display_offset_values.items()):
    if not key.startswith('i_'): continue
    distinct = len(counter)
    nonzero = sum(c for v, c in counter.items() if v != 0)
    if distinct > 3:
        top = counter.most_common(5)
        print(f"  {key}: {distinct} distinct, {nonzero} non-zero. Top: {top}")

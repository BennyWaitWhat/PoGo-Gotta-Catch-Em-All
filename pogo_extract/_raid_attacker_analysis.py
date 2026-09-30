"""
Raid Attacker Analysis: find the user's best owned attacker per type.

Reads pokemon.db (read-only) + pvpoke_gamemaster.json + move_id_to_name.json
to build a per-type raid attacker dossier.

Scoring:
  - Base attack stat from gamemaster
  - IV attack (0-15)
  - Level (via CPM)
  - Shadow bonus: x1.2 attack multiplier
  - STAB: whether the pokemon's types include the attack type
  - Charged move type match: whether the pokemon has a charged move of that type
"""

import json, sqlite3, os, sys
from pathlib import Path

BASE = Path(r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract")

# ── CPM table (level -> CP multiplier) ──
CPM_TABLE = {
    1: 0.094, 1.5: 0.135137432, 2: 0.16639787, 2.5: 0.192650919,
    3: 0.21573247, 3.5: 0.236572661, 4: 0.25572005, 4.5: 0.273530381,
    5: 0.29024988, 5.5: 0.306057378, 6: 0.3210876, 6.5: 0.335445036,
    7: 0.34921268, 7.5: 0.362457751, 8: 0.37523559, 8.5: 0.387592416,
    9: 0.39956728, 9.5: 0.411193551, 10: 0.42250001, 10.5: 0.432926420,
    11: 0.44310755, 11.5: 0.453059959, 12: 0.46279839, 12.5: 0.472336093,
    13: 0.48168495, 13.5: 0.4908558, 14: 0.49985844, 14.5: 0.508701765,
    15: 0.51739395, 15.5: 0.525942511, 16: 0.53435433, 16.5: 0.542635738,
    17: 0.55079269, 17.5: 0.558830576, 18: 0.56675452, 18.5: 0.574569153,
    19: 0.58227891, 19.5: 0.589887917, 20: 0.59740001, 20.5: 0.604818814,
    21: 0.61215729, 21.5: 0.619399365, 22: 0.62656713, 22.5: 0.633644533,
    23: 0.64065295, 23.5: 0.647576426, 24: 0.65443563, 24.5: 0.661214806,
    25: 0.667934, 25.5: 0.674577537, 26: 0.68116492, 26.5: 0.687680648,
    27: 0.69414365, 27.5: 0.700538673, 28: 0.70688421, 28.5: 0.713164996,
    29: 0.71939909, 29.5: 0.725571552, 30: 0.7317, 30.5: 0.734741009,
    31: 0.73776948, 31.5: 0.740785574, 32: 0.74378943, 32.5: 0.746781211,
    33: 0.74976104, 33.5: 0.752729087, 34: 0.75568551, 34.5: 0.758630378,
    35: 0.76156384, 35.5: 0.764486065, 36: 0.76739717, 36.5: 0.770297266,
    37: 0.7731865, 37.5: 0.776064962, 38: 0.77893275, 38.5: 0.781790055,
    39: 0.78463697, 39.5: 0.787473578, 40: 0.79030001, 40.5: 0.792803968,
    41: 0.79530001, 41.5: 0.797800015, 42: 0.80030001, 42.5: 0.802800015,
    43: 0.80530001, 43.5: 0.807800015, 44: 0.81030001, 44.5: 0.812800015,
    45: 0.81530001, 45.5: 0.817800015, 46: 0.82030001, 46.5: 0.822800015,
    47: 0.82530001, 47.5: 0.827800015, 48: 0.83030001, 48.5: 0.832800015,
    49: 0.83530001, 49.5: 0.837800015, 50: 0.84029999, 50.5: 0.842800015,
    51: 0.84530001,
}

def get_cpm(level):
    if level in CPM_TABLE:
        return CPM_TABLE[level]
    # Interpolate
    lower = max(l for l in CPM_TABLE if l <= level)
    upper = min(l for l in CPM_TABLE if l >= level)
    if lower == upper:
        return CPM_TABLE[lower]
    frac = (level - lower) / (upper - lower)
    return CPM_TABLE[lower] + frac * (CPM_TABLE[upper] - CPM_TABLE[lower])


# ── Load gamemaster ──
with open(BASE / "pvpoke_gamemaster.json", "r", encoding="utf-8") as f:
    gm = json.load(f)

# Build species lookup: speciesId -> {baseAtk, types}
# We need to map from DB species_name + alignment to gamemaster speciesId
species_data = {}
for p in gm["pokemon"]:
    sid = p["speciesId"]
    species_data[sid] = {
        "dex": p["dex"],
        "name": p["speciesName"],
        "atk": p["baseStats"]["atk"],
        "def": p["baseStats"]["def"],
        "hp": p["baseStats"]["hp"],
        "types": [t for t in p["types"] if t != "none"],
        "fast": p.get("fastMoves", []),
        "charged": p.get("chargedMoves", []),
    }

# Build move type lookup from gamemaster
move_types = {}
for m in gm["moves"]:
    move_types[m["moveId"]] = m["type"]
    # Also store power for PvE (the gamemaster has PvP power, but type is same)

# Load move_id_to_name mapping
with open(BASE / "move_id_to_name.json", "r", encoding="utf-8") as f:
    move_id_map = json.load(f)  # str(int) -> move_name

# ── Load deep_profiles for species type info fallback ──
with open(BASE / "system" / "analysis" / "deep_profiles.json", "r", encoding="utf-8") as f:
    deep_profiles = json.load(f)

# Map uid -> profile moves
profile_moves = {}
for p in deep_profiles:
    profile_moves[p["uid"]] = p.get("moves", [])

# ── Query pokemon.db ──
conn = sqlite3.connect(f"file:{BASE / 'pokemon.db'}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

query = """
SELECT uid_hex, species_name, pokemon_id, iv_atk, iv_def, iv_sta, level, cp,
       alignment_name, move1, move2, move3, can_mega_evolve,
       is_legendary, is_mythical, is_ultra_beast, form, nickname,
       is_best_buddy, is_purified_flag
FROM pokemon
WHERE in_bag = 1 AND is_egg = 0
ORDER BY cp DESC
"""

rows = conn.execute(query).fetchall()
conn.close()

# ── Map DB species to gamemaster speciesId ──
def db_to_gm_id(species_name, alignment_name, pokemon_id):
    """Try to find gamemaster speciesId from DB species_name."""
    base = species_name.lower().replace(" ", "_").replace("-", "_").replace("'", "").replace(".", "").replace(":", "")

    # Shadow
    if alignment_name == "SHADOW":
        shadow_id = base + "_shadow"
        if shadow_id in species_data:
            return shadow_id
        # Try without shadow (use base stats, apply multiplier manually)
        if base in species_data:
            return base

    # Purified - use normal stats
    if base in species_data:
        return base

    # Try common transformations
    for attempt in [base, base.replace("_", "")]:
        if attempt in species_data:
            return attempt

    return None


# ── Known top raid attackers per type (for gap analysis reference) ──
# These are the consensus best raid attackers per type in Pokemon GO as of 2026
IDEAL_ATTACKERS = {
    "fire": ["Shadow Moltres", "Shadow Chandelure", "Shadow Blaziken", "Reshiram", "Shadow Entei", "Mega Charizard Y", "Shadow Charizard"],
    "water": ["Shadow Kyogre", "Shadow Feraligatr", "Shadow Swampert", "Primal Kyogre", "Shadow Kingler", "Mega Blastoise"],
    "grass": ["Shadow Sceptile", "Shadow Venusaur", "Shadow Torterra", "Mega Venusaur", "Kartana", "Shadow Tangrowth"],
    "electric": ["Shadow Electivire", "Shadow Magnezone", "Shadow Raikou", "Shadow Zapdos", "Mega Manectric", "Zekrom", "Xurkitree"],
    "ice": ["Shadow Mamoswine", "Shadow Weavile", "Shadow Glaceon", "Mega Glalie", "Galarian Darmanitan", "Shadow Mewtwo (Ice Beam)"],
    "fighting": ["Shadow Machamp", "Shadow Hariyama", "Mega Blaziken", "Shadow Conkeldurr", "Mega Lucario", "Terrakion", "Marshadow"],
    "poison": ["Shadow Roserade", "Shadow Victreebel", "Mega Beedrill", "Shadow Toxicroak", "Mega Gengar (Sludge Bomb)", "Nihilego"],
    "ground": ["Shadow Garchomp", "Shadow Mamoswine", "Primal Groudon", "Shadow Rhyperior", "Shadow Excadrill", "Mega Garchomp", "Shadow Golurk"],
    "flying": ["Shadow Moltres", "Shadow Staraptor", "Shadow Ho-Oh", "Mega Pidgeot", "Mega Rayquaza", "Shadow Honchkrow"],
    "psychic": ["Shadow Mewtwo", "Shadow Alakazam", "Shadow Espeon", "Mega Gardevoir", "Shadow Metagross (Psychic)", "Shadow Latios"],
    "bug": ["Shadow Pinsir", "Shadow Scizor", "Mega Beedrill", "Mega Scizor", "Shadow Yanmega", "Shadow Escavalier"],
    "rock": ["Shadow Tyranitar", "Shadow Rhyperior", "Mega Aerodactyl", "Shadow Rampardos", "Shadow Aggron", "Mega Tyranitar"],
    "ghost": ["Shadow Chandelure", "Mega Gengar", "Shadow Banette", "Shadow Mismagius", "Giratina-O", "Lunala"],
    "dragon": ["Shadow Dragonite", "Shadow Salamence", "Mega Rayquaza", "Shadow Garchomp", "Dialga", "Palkia", "Reshiram"],
    "dark": ["Shadow Tyranitar", "Shadow Weavile", "Shadow Honchkrow", "Mega Houndoom", "Shadow Absol", "Hydreigon", "Darkrai"],
    "steel": ["Shadow Metagross", "Mega Scizor", "Shadow Excadrill", "Shadow Dialga", "Zacian", "Solgaleo"],
    "fairy": ["Shadow Gardevoir", "Shadow Granbull", "Mega Gardevoir", "Shadow Togekiss", "Xerneas", "Zacian"],
    "normal": ["Shadow Regigigas", "Shadow Snorlax", "Mega Pidgeot (Return/HB)", "Shadow Ursaluna"],
}


# ── Build per-type attack scoring ──
# For each pokemon, compute "effective attack stat" for each type it can attack with
# Score = (BaseAtk + IV_Atk) * CPM * shadow_bonus * STAB
# We care about: does it have a charged move of that type?

TYPES = ["fire", "water", "grass", "electric", "ice", "fighting", "poison", "ground",
         "flying", "psychic", "bug", "rock", "ghost", "dragon", "dark", "steel", "fairy", "normal"]

best_per_type = {t: [] for t in TYPES}

for row in rows:
    uid = row["uid_hex"]
    species = row["species_name"]
    pid = row["pokemon_id"]
    iv_atk = row["iv_atk"] or 0
    iv_def = row["iv_def"] or 0
    iv_sta = row["iv_sta"] or 0
    level = row["level"] or 1
    cp = row["cp"] or 0
    alignment = row["alignment_name"] or "NORMAL"
    m1 = row["move1"]
    m2 = row["move2"]
    m3 = row["move3"]
    is_bb = row["is_best_buddy"]
    nick = row["nickname"] or ""

    # Resolve gamemaster entry
    gm_id = db_to_gm_id(species, alignment, pid)

    # Get types from gamemaster
    if gm_id and gm_id in species_data:
        sd = species_data[gm_id]
        base_atk = sd["atk"]
        poke_types = sd["types"]
    else:
        # Fallback: skip if we can't find base stats
        continue

    # Get move names
    move_names = []
    for mid in [m1, m2, m3]:
        if mid and str(mid) in move_id_map:
            move_names.append(move_id_map[str(mid)])
        elif mid:
            move_names.append(f"UNKNOWN_{mid}")

    # Also check profile moves as fallback
    if uid in profile_moves and not move_names:
        move_names = profile_moves[uid]

    # Get move types
    move_type_list = []
    for mn in move_names:
        if mn in move_types:
            move_type_list.append(move_types[mn])
        else:
            move_type_list.append("unknown")

    # Charged move types (move2, move3)
    charged_types = set()
    fast_type = None
    if len(move_type_list) >= 1:
        fast_type = move_type_list[0]
    if len(move_type_list) >= 2:
        charged_types.add(move_type_list[1])
    if len(move_type_list) >= 3:
        charged_types.add(move_type_list[2])

    # Combine all move types for attack coverage
    all_move_types = set()
    if fast_type:
        all_move_types.add(fast_type)
    all_move_types.update(charged_types)

    # CPM
    cpm = get_cpm(level)

    # Shadow bonus
    shadow_mult = 1.2 if alignment == "SHADOW" else 1.0

    # For each type this pokemon can attack with
    for attack_type in TYPES:
        has_charged = attack_type in charged_types
        has_fast = fast_type == attack_type
        has_any_move = attack_type in all_move_types

        if not has_any_move:
            continue

        # STAB: if the pokemon's own types include the attack type
        stab = 1.2 if attack_type in poke_types else 1.0

        # Effective attack = (base_atk + iv_atk) * cpm * shadow * stab
        eff_atk = (base_atk + iv_atk) * cpm * shadow_mult * stab

        # Bonus for having both fast AND charged of same type (full DPS)
        full_coverage = has_fast and has_charged
        # Penalty if only fast move (charged does different type damage)
        move_quality = 1.0 if full_coverage else (0.85 if has_charged else 0.6)

        raid_score = eff_atk * move_quality

        label = species
        if alignment == "SHADOW":
            label = f"Shadow {species}"
        elif alignment == "PURIFIED":
            label = f"Purified {species}"

        entry = {
            "label": label,
            "species": species,
            "uid": uid,
            "iv_atk": iv_atk,
            "iv_def": iv_def,
            "iv_sta": iv_sta,
            "iv_str": f"{iv_atk}/{iv_def}/{iv_sta}",
            "level": level,
            "cp": cp,
            "alignment": alignment,
            "is_shadow": alignment == "SHADOW",
            "base_atk": base_atk,
            "stab": stab > 1,
            "fast_type": fast_type,
            "charged_types": list(charged_types),
            "full_coverage": full_coverage,
            "eff_atk": round(eff_atk, 1),
            "raid_score": round(raid_score, 1),
            "moves": move_names,
            "best_buddy": is_bb,
            "nickname": nick,
        }
        best_per_type[attack_type].append(entry)


# Sort each type by raid_score descending and keep top 5
for t in TYPES:
    best_per_type[t].sort(key=lambda x: x["raid_score"], reverse=True)
    best_per_type[t] = best_per_type[t][:5]


# ── Output dossier ──
print("=" * 90)
print("  RAID ATTACKER DOSSIER - Best Owned Pokemon Per Attack Type")
print("=" * 90)
print()
print("Scoring: (BaseAtk + IV_Atk) * CPM * ShadowBonus(1.2) * STAB(1.2) * MoveQuality")
print("MoveQuality: 1.0 = fast+charged same type, 0.85 = charged only, 0.6 = fast only")
print()

for t in TYPES:
    entries = best_per_type[t]
    print(f"{'-' * 90}")
    print(f"  {t.upper()} attackers")
    print(f"{'-' * 90}")
    if not entries:
        print("  (none found with matching moves)")
        print()
        continue

    print(f"  {'#':<3} {'Pokemon':<30} {'IVs':<12} {'Lv':<6} {'CP':<7} {'Score':<8} {'Moves'}")
    for i, e in enumerate(entries, 1):
        shadow_tag = ""
        fast_match = "*" if e["fast_type"] == t else " "
        charged_match = ""
        for ct in e["charged_types"]:
            if ct == t:
                charged_match = "*"
        move_str = f"{fast_match}{e['moves'][0]}" if e['moves'] else ""
        if len(e['moves']) > 1:
            move_str += f" / {charged_match}{e['moves'][1]}"
        if len(e['moves']) > 2:
            cm2_match = "*" if move_types.get(e['moves'][2]) == t else ""
            move_str += f" / {cm2_match}{e['moves'][2]}"

        cov = "FULL" if e["full_coverage"] else ("chrg" if t in [move_types.get(m, "") for m in e["moves"][1:]] else "fast")
        stab_tag = "STAB" if e["stab"] else ""
        shadow_tag = "SHDW" if e["is_shadow"] else ""
        tags = " ".join(filter(None, [shadow_tag, stab_tag, cov]))

        print(f"  {i:<3} {e['label']:<30} {e['iv_str']:<12} {e['level']:<6} {e['cp']:<7} {e['raid_score']:<8.1f} {move_str}")
        if tags:
            print(f"      [{tags}]")
    print()

# ── Gap Analysis ──
print()
print("=" * 90)
print("  GAP ANALYSIS - Types Where You Need Better Attackers")
print("=" * 90)
print()

# Evaluate gaps
gaps = []
for t in TYPES:
    entries = best_per_type[t]
    if not entries:
        gaps.append((t, 0, "NO attackers with matching moves found"))
        continue

    best = entries[0]
    score = best["raid_score"]

    # Check quality indicators
    issues = []

    # Low score relative to what's possible
    if score < 200:
        issues.append(f"best score only {score:.0f} (weak)")
    elif score < 250:
        issues.append(f"best score {score:.0f} (moderate)")

    # No shadow attacker
    has_shadow = any(e["is_shadow"] for e in entries)
    if not has_shadow:
        issues.append("no shadow attacker")

    # No full coverage (fast+charged same type)
    has_full = any(e["full_coverage"] for e in entries)
    if not has_full:
        issues.append("no fast+charged type match")

    # Low IV attack on best
    if best["iv_atk"] < 13:
        issues.append(f"best has only {best['iv_atk']} ATK IV")

    # Low level on best
    if best["level"] < 40:
        issues.append(f"best only L{best['level']}")

    # Few options (depth)
    if len(entries) < 3:
        issues.append(f"only {len(entries)} option(s)")

    if issues:
        gaps.append((t, score, "; ".join(issues)))

# Sort gaps by score ascending (worst first)
gaps.sort(key=lambda x: x[1])

print(f"{'Type':<12} {'Best Score':<12} {'Issues'}")
print(f"{'-' * 80}")
for t, score, issue_str in gaps:
    print(f"{t.upper():<12} {score:<12.0f} {issue_str}")

print()

# Count shadow attackers per type
print()
print("=" * 90)
print("  SHADOW ATTACKER INVENTORY")
print("=" * 90)
print()
shadow_count = 0
for t in TYPES:
    shadows = [e for e in best_per_type[t] if e["is_shadow"]]
    if shadows:
        shadow_count += 1
        for s in shadows:
            print(f"  {t.upper():<12} {s['label']:<30} {s['iv_str']:<10} L{s['level']:<5} CP {s['cp']:<6} Score {s['raid_score']:.0f}")

print(f"\n  Shadow coverage: {shadow_count}/{len(TYPES)} types")

# Recommendations
print()
print("=" * 90)
print("  TOP RECOMMENDATIONS")
print("=" * 90)
print()

# Sort gaps to find the most critical ones
critical_gaps = [(t, s, i) for t, s, i in gaps if s < 250 or "NO attackers" in i]
critical_gaps.sort(key=lambda x: x[1])

for t, score, issues in critical_gaps[:8]:
    print(f"  {t.upper()}: {issues}")
    ideal = IDEAL_ATTACKERS.get(t, [])
    if ideal:
        print(f"    Target: {', '.join(ideal[:3])}")
    print()

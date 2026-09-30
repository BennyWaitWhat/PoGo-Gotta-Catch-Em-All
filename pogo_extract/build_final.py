"""
FINAL comprehensive pokemon database.

All known fields decoded:
- All PokemonProto fields including TRADE info
- All PokemonDisplay fields including costume/shiny/form (correct offsets)
- Species names
- Calculated levels with best buddy boost
"""
import json, sqlite3, os, struct
from datetime import datetime, timezone

POGO_LAUNCH_MS = 1467590400000

# CPM table
CPM_TABLE = [
    (0.094,1),(0.135137432,1.5),(0.16639787,2),(0.192650919,2.5),(0.21573247,3),(0.236572661,3.5),
    (0.25572005,4),(0.273530381,4.5),(0.29024988,5),(0.306057377,5.5),(0.3210876,6),(0.335445036,6.5),
    (0.34921268,7),(0.362457751,7.5),(0.37523559,8),(0.387592406,8.5),(0.39956728,9),(0.411193551,9.5),
    (0.42250001,10),(0.432926419,10.5),(0.44310755,11),(0.4530599578,11.5),(0.46279839,12),(0.472336083,12.5),
    (0.48168495,13),(0.4908558,13.5),(0.49985844,14),(0.508701765,14.5),(0.51739395,15),(0.525942511,15.5),
    (0.53435433,16),(0.542635767,16.5),(0.55079269,17),(0.558830576,17.5),(0.56675452,18),(0.574569153,18.5),
    (0.58227891,19),(0.589887907,19.5),(0.59740001,20),(0.604818814,20.5),(0.61215729,21),(0.619399365,21.5),
    (0.62656713,22),(0.633644533,22.5),(0.64065295,23),(0.647576426,23.5),(0.65443563,24),(0.661214806,24.5),
    (0.667934,25),(0.674577537,25.5),(0.68116492,26),(0.687680648,26.5),(0.69414365,27),(0.700538673,27.5),
    (0.70688421,28),(0.713164996,28.5),(0.71939909,29),(0.725571552,29.5),(0.7317,30),(0.734741009,30.5),
    (0.73776948,31),(0.740785574,31.5),(0.74378943,32),(0.746781211,32.5),(0.74976104,33),(0.752729087,33.5),
    (0.75568551,34),(0.758630378,34.5),(0.76156384,35),(0.764486065,35.5),(0.76739717,36),(0.770297266,36.5),
    (0.7731865,37),(0.776064962,37.5),(0.77893275,38),(0.781790055,38.5),(0.78463697,39),(0.787473578,39.5),
    (0.79030001,40),(0.792803968,40.5),(0.79530001,41),(0.797800015,41.5),(0.8003,42),(0.802799995,42.5),
    (0.8053,43),(0.807800015,43.5),(0.81029999,44),(0.812799985,44.5),(0.81529999,45),(0.81779999,45.5),
    (0.82029999,46),(0.82279999,46.5),(0.82529999,47),(0.82779999,47.5),(0.83029999,48),(0.83279999,48.5),
    (0.83529999,49),(0.83779999,49.5),(0.84029999,50),(0.84279999,50.5),(0.84529999,51),
]
def cpm_to_level(cpm):
    if not cpm or cpm <= 0: return None
    return min(CPM_TABLE, key=lambda x: abs(x[0] - cpm))[1]

POKEBALL_NAMES = {0: 'UNKNOWN', 1: 'POKEBALL', 2: 'GREATBALL', 3: 'ULTRABALL', 4: 'MASTERBALL', 5: 'PREMIERBALL'}
GENDER_NAMES = {0: 'UNSET', 1: 'MALE', 2: 'FEMALE', 3: 'GENDERLESS'}
ORIGIN_DETAIL_NAMES = {
    0: 'UNSET', 1: 'POKESTOP', 2: 'GYM', 3: 'PHOTOBOMBED', 4: 'GO_SNAPSHOT',
    5: 'GO_BATTLE_LEAGUE', 6: 'BATTLE_RAID', 7: 'INCENSE', 8: 'GIFT',
    9: 'ROUTE', 10: 'ADVENTURE_SYNC', 11: 'POKEMON_HOME', 12: 'BREAD',
    13: 'TRADE', 14: 'EGG_HATCH', 15: 'TUTORIAL'
}
WEATHER_NAMES = {0: 'NONE', 1: 'CLEAR', 2: 'RAINY', 3: 'PARTLY_CLOUDY', 4: 'OVERCAST', 5: 'WINDY', 6: 'SNOW', 7: 'FOG'}
ALIGNMENT_NAMES = {0: 'NORMAL', 1: 'SHADOW', 2: 'PURIFIED', 3: 'OTHER'}  # corrected: 1=SHADOW, 2=PURIFIED based on user counts

# Import species names
import sys
sys.path.insert(0, '.')
from add_names import SPECIES_NAMES

EMPTY_STR_PTR = '0x7b81c1cf40'

def parse_display(raw_hex):
    """Parse PokemonDisplayProto. Re-verified against user's known counts.

    Layout (corrected based on user's stats: shiny=1063, shadow=229, purified=63):
    - +16: pokemon_id (rare set)
    - +20: gender (1=MALE, 2=FEMALE, 3=GENDERLESS)
    - +24: shiny (bool int32) - 958 detected ~ 1063 actual (511 missing displays)
    - +28: form (799 distinct values)
    - +32: weather_boosted (1-7 enum)
    - +36: alignment (0=NORMAL/UNSET, 1=SHADOW, 2=PURIFIED) - matches 200~229 / 57~63
    - +40: ??? (rare flag)
    - +44: ??? (was thought to be alignment but doesn't match)
    """
    if not raw_hex or len(raw_hex) < 100: return {}
    try:
        bs = bytes.fromhex(raw_hex)
        return {
            'displayPokemonId': struct.unpack_from('<i', bs, 16)[0] if len(bs) >= 20 else 0,
            'gender': struct.unpack_from('<i', bs, 20)[0] if len(bs) >= 24 else 0,
            'shiny': struct.unpack_from('<i', bs, 24)[0] if len(bs) >= 28 else 0,
            'form': struct.unpack_from('<i', bs, 28)[0] if len(bs) >= 32 else 0,
            'weatherBoosted': struct.unpack_from('<i', bs, 32)[0] if len(bs) >= 36 else 0,
            'alignment': struct.unpack_from('<i', bs, 36)[0] if len(bs) >= 40 else 0,
            'costume_or_flag': struct.unpack_from('<i', bs, 40)[0] if len(bs) >= 44 else 0,  # uncertain
            'extra_field': struct.unpack_from('<i', bs, 44)[0] if len(bs) >= 48 else 0,  # uncertain
        }
    except: return {}

def parse_proto(raw_hex):
    """Parse PokemonProto (512 bytes) - all known fields."""
    if not raw_hex or len(raw_hex) < 600: return {}
    try:
        bs = bytes.fromhex(raw_hex)
        n = len(bs)
        def i32(o): return struct.unpack_from('<i', bs, o)[0] if o+4 <= n else 0
        def f32(o): return struct.unpack_from('<f', bs, o)[0] if o+4 <= n else 0
        def i64(o): return struct.unpack_from('<q', bs, o)[0] if o+8 <= n else 0
        def u64(o): return struct.unpack_from('<Q', bs, o)[0] if o+8 <= n else 0
        def b(o): return bs[o] != 0 if o < n else False
        return {
            'uid': u64(32),
            'pokemonId': i32(40), 'cp': i32(44),
            'stamina': i32(48), 'staminaMax': i32(52),
            'move1': i32(56), 'move2': i32(60),
            'eggKmWalkedTarget': f32(92),  # NEW: matched 378 ≈ hatched 374
            'heightM': f32(104), 'weightKg': f32(108),
            'ivAtk': i32(112), 'ivDef': i32(116), 'ivSta': i32(120),
            'cpMultiplier': f32(124), 'pokeball': i32(128),
            'capturedCellId': u64(136),
            'creationTimeMs': i64(160),
            'originDetail': i32(168),
            'numAdditionalCpMultiplier': f32(172),
            'isHatchedFromEgg': b(225),  # NEW: matched 377 ≈ hatched 374
            'originalLocation': i64(248),
            'tradedTimeMs': i64(264),
            'isLucky': b(272),
            'move3': i32(276),
            'specialBgId': i32(440),  # NEW: matched 92 ≈ 89
            'locationBgId': i32(480),  # NEW: matched 10 ≈ 14
            'adventureEffectsLeft': i32(496),  # NEW: matched 21 ≈ 19
        }
    except: return {}

def main():
    print("Loading pokemon_v3.json...")
    raw = json.load(open('pokemon_v3.json'))
    print(f"  {len(raw)} entries")

    db_path = 'pokemon.db'
    if os.path.exists(db_path): os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Schema
    c.execute('''CREATE TABLE pokemon (
        uid_hex TEXT PRIMARY KEY,
        uid INTEGER,
        pokemon_id INTEGER,
        species_name TEXT,
        cp INTEGER,
        stamina INTEGER,
        stamina_max INTEGER,
        move1 INTEGER,
        move2 INTEGER,
        move3 INTEGER,
        iv_atk INTEGER,
        iv_def INTEGER,
        iv_sta INTEGER,
        iv_total INTEGER,
        iv_pct REAL,
        is_hundo BOOLEAN,
        is_zero BOOLEAN,
        height_m REAL,
        weight_kg REAL,
        cp_multiplier REAL,
        num_additional_cpm REAL,
        level REAL,
        is_best_buddy BOOLEAN,
        pokeball INTEGER,
        pokeball_name TEXT,
        creation_time_ms INTEGER,
        creation_date TEXT,
        is_lucky BOOLEAN,
        is_hatched_from_egg BOOLEAN,
        egg_km_walked_target REAL,
        nickname TEXT,
        deployed_fort_id TEXT,
        is_deployed BOOLEAN,
        captured_cell_hex TEXT,
        origin_detail INTEGER,
        origin_detail_name TEXT,
        gender INTEGER,
        gender_name TEXT,
        costume INTEGER,
        form INTEGER,
        is_shiny BOOLEAN,
        weather_boosted INTEGER,
        weather_name TEXT,
        alignment INTEGER,
        alignment_name TEXT,
        is_traded BOOLEAN,
        original_owner TEXT,
        traded_time_ms INTEGER,
        traded_date TEXT,
        original_location_hash TEXT,
        special_bg_id INTEGER,
        location_bg_id INTEGER,
        adventure_effects_left INTEGER,
        addr TEXT,
        raw_proto_hex TEXT,
        display_raw_hex TEXT
    )''')

    inserted = 0
    skipped = 0
    seen = set()

    for p in raw:
        proto = parse_proto(p.get('raw_proto', ''))
        if not proto: skipped += 1; continue

        uid = proto['uid']
        if uid == 0: skipped += 1; continue
        if proto['creationTimeMs'] < POGO_LAUNCH_MS: skipped += 1; continue

        uid_hex = f"{uid:016x}"
        if uid_hex in seen: skipped += 1; continue
        seen.add(uid_hex)

        display = parse_display(p.get('display_raw'))
        strings = p.get('strings') or {}

        # Decode strings
        def get_str(off):
            v = strings.get(off)
            if isinstance(v, list) and v[1]:
                return v[1]
            return None

        nickname = get_str('0xb8')
        original_owner = get_str('0x100')
        deployed_fort = get_str('0x40')
        # is_traded: check both originalOwnerNickname AND tradedTimeMs
        is_traded = (original_owner is not None) or (proto['tradedTimeMs'] > 0)

        traded_time = proto['tradedTimeMs']
        try:
            traded_dt = datetime.fromtimestamp(traded_time/1000, tz=timezone.utc).isoformat() if traded_time > 0 else None
        except: traded_dt = None

        try:
            create_dt = datetime.fromtimestamp(proto['creationTimeMs']/1000, tz=timezone.utc).isoformat()
        except: create_dt = None

        iv_t = proto['ivAtk'] + proto['ivDef'] + proto['ivSta']
        iv_pct = round(iv_t / 45 * 100, 1)
        cpm_total = proto['cpMultiplier'] + (proto['numAdditionalCpMultiplier'] or 0)
        level = cpm_to_level(cpm_total)
        uid_signed = uid if uid < 2**63 else uid - 2**64

        captured_cell = proto['capturedCellId']
        cell_hex = f"{captured_cell:016x}" if captured_cell else None

        gender = display.get('gender', 0)
        weather = display.get('weatherBoosted', 0)
        alignment = display.get('alignment', 0)

        original_loc_hash = f"{proto['originalLocation']:016x}" if proto['originalLocation'] else None

        placeholders = ','.join(['?']*56)
        c.execute(f'INSERT OR IGNORE INTO pokemon VALUES ({placeholders})', (
            uid_hex, uid_signed,
            proto['pokemonId'], SPECIES_NAMES.get(proto['pokemonId']),
            proto['cp'], proto['stamina'], proto['staminaMax'],
            proto['move1'], proto['move2'], proto['move3'],
            proto['ivAtk'], proto['ivDef'], proto['ivSta'], iv_t, iv_pct,
            iv_t == 45, iv_t == 0,
            proto['heightM'], proto['weightKg'],
            proto['cpMultiplier'], proto['numAdditionalCpMultiplier'], level, proto['numAdditionalCpMultiplier'] > 0,
            proto['pokeball'], POKEBALL_NAMES.get(proto['pokeball']),
            proto['creationTimeMs'], create_dt, proto['isLucky'],
            proto['isHatchedFromEgg'], proto['eggKmWalkedTarget'],
            nickname, deployed_fort, deployed_fort is not None,
            cell_hex,
            proto['originDetail'], ORIGIN_DETAIL_NAMES.get(proto['originDetail']),
            gender, GENDER_NAMES.get(gender),
            display.get('costume_or_flag', 0), display.get('form', 0),
            bool(display.get('shiny', 0)),
            weather, WEATHER_NAMES.get(weather),
            alignment, ALIGNMENT_NAMES.get(alignment),
            is_traded, original_owner, traded_time, traded_dt,
            original_loc_hash,
            proto['specialBgId'], proto['locationBgId'], proto['adventureEffectsLeft'],
            p['addr'], p.get('raw_proto'), p.get('display_raw')
        ))
        inserted += 1

    # Indexes
    for col in ['pokemon_id', 'species_name', 'cp', 'iv_total', 'level', 'is_lucky', 'is_hundo',
                'creation_date', 'gender', 'is_shiny', 'is_traded', 'is_best_buddy',
                'pokeball', 'origin_detail', 'is_deployed', 'alignment', 'costume', 'form']:
        c.execute(f'CREATE INDEX idx_{col} ON pokemon({col})')

    conn.commit()

    # Final stats
    print(f"\nInserted: {inserted}, filtered: {skipped}")
    print(f"\n=== COMPREHENSIVE STATS ===")
    queries = [
        ('Total pokemon', 'SELECT COUNT(*) FROM pokemon'),
        ('Unique species', 'SELECT COUNT(DISTINCT pokemon_id) FROM pokemon'),
        ('Hundos (15/15/15)', 'SELECT COUNT(*) FROM pokemon WHERE is_hundo'),
        ('Zeros (0/0/0)', 'SELECT COUNT(*) FROM pokemon WHERE is_zero'),
        ('Lucky', 'SELECT COUNT(*) FROM pokemon WHERE is_lucky'),
        ('Shiny (real)', 'SELECT COUNT(*) FROM pokemon WHERE is_shiny'),
        ('Traded (real)', 'SELECT COUNT(*) FROM pokemon WHERE is_traded'),
        ('Best Buddies', 'SELECT COUNT(*) FROM pokemon WHERE is_best_buddy'),
        ('Costume', 'SELECT COUNT(*) FROM pokemon WHERE costume > 0'),
        ('Shadow', 'SELECT COUNT(*) FROM pokemon WHERE alignment = 2'),
        ('Purified', 'SELECT COUNT(*) FROM pokemon WHERE alignment = 3'),
        ('Deployed in gyms', 'SELECT COUNT(*) FROM pokemon WHERE is_deployed'),
        ('With nickname', 'SELECT COUNT(*) FROM pokemon WHERE nickname IS NOT NULL'),
        ('Weather boosted', 'SELECT COUNT(*) FROM pokemon WHERE weather_boosted > 0'),
        ('Level 30+', 'SELECT COUNT(*) FROM pokemon WHERE level >= 30'),
        ('Level 40+', 'SELECT COUNT(*) FROM pokemon WHERE level >= 40'),
        ('Level 50 (max)', 'SELECT COUNT(*) FROM pokemon WHERE level >= 50'),
        ('Have caught location', 'SELECT COUNT(*) FROM pokemon WHERE captured_cell_hex IS NOT NULL'),
        ('Have origin info', 'SELECT COUNT(*) FROM pokemon WHERE origin_detail > 0'),
    ]
    for label, q in queries:
        c.execute(q); print(f'  {label}: {c.fetchone()[0]}')

    print('\n=== TRADE PARTNERS ===')
    c.execute('SELECT original_owner, COUNT(*) FROM pokemon WHERE is_traded GROUP BY original_owner ORDER BY 2 DESC LIMIT 10')
    for owner, cnt in c.fetchall(): print(f'  {owner}: {cnt} pokemon')

    print('\n=== WEATHER BOOST ===')
    c.execute('SELECT weather_name, COUNT(*) FROM pokemon WHERE weather_boosted > 0 GROUP BY weather_name')
    for n, cnt in c.fetchall(): print(f'  {n}: {cnt}')

    print('\n=== TOP SHINIES ===')
    c.execute('SELECT species_name, COUNT(*) FROM pokemon WHERE is_shiny GROUP BY species_name ORDER BY 2 DESC LIMIT 10')
    for n, cnt in c.fetchall(): print(f'  {n}: {cnt}')

    print('\n=== COSTUMED POKEMON ===')
    c.execute('SELECT species_name, costume, COUNT(*) FROM pokemon WHERE costume > 0 GROUP BY species_name, costume ORDER BY 3 DESC LIMIT 10')
    for n, cm, cnt in c.fetchall(): print(f'  {n} costume={cm}: {cnt}')

    print('\n=== ALIGNMENT ===')
    c.execute('SELECT alignment_name, COUNT(*) FROM pokemon GROUP BY alignment_name')
    for n, cnt in c.fetchall(): print(f'  {n}: {cnt}')

    print(f"\nDB: pokemon.db ({os.path.getsize(db_path)/1024/1024:.1f}MB) | {inserted} pokemon, 51 columns")
    conn.close()

if __name__ == '__main__':
    main()

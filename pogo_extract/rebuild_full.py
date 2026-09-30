"""
Re-decode existing pokemon_full.json with the now-known offsets.
Builds the FINAL comprehensive DB with all fields decoded.
"""
import json, sqlite3, os, struct
from datetime import datetime, timezone

POGO_LAUNCH_MS = 1467590400000

# Known PokemonProto offsets (verified against live memory)
PROTO_FIELDS = {
    'klass':                  (0,   'ptr'),    # IL2CPP class pointer
    'monitor':                (8,   'ptr'),
    'pokemonRequirementsPtr': (16,  'ptr'),    # ptr to UnknownFieldSet or similar
    'id_':                    (32,  'i64u'),   # uid (uint64)
    'pokemonId_':             (40,  'i32'),    # species
    'cp_':                    (44,  'i32'),
    'stamina_':               (48,  'i32'),
    'staminaMax_':            (52,  'i32'),
    'move1_':                 (56,  'i32'),
    'move2_':                 (60,  'i32'),
    'deployedFortId_':        (64,  'str'),
    'heightM_':               (104, 'f32'),
    'weightKg_':              (108, 'f32'),
    'individualAttack_':      (112, 'i32'),
    'individualDefense_':     (116, 'i32'),
    'individualStamina_':     (120, 'i32'),
    'cpMultiplier_':          (124, 'f32'),
    'pokeball_':              (128, 'i32'),
    'capturedCellId_':        (136, 'i64u'),  # S2 cell where caught
    'creationTimeMs_':        (160, 'i64'),
    'originDetail_':          (168, 'i32'),   # enum: 1=POKESTOP, 2=GYM, 3=PHOTOBOMBED, etc.
    'numAdditionalCpMultiplier_': (172, 'f32'),  # best buddy boost
    'nickname_':              (184, 'str'),
    'pokemonDisplay_':        (216, 'ptr_display'),
    'isLucky_':               (272, 'bool'),
    'move3_':                 (276, 'i32'),
    'capturePoint':           (320, 'i64u'),  # Possibly other cell
    'captureLat':             (324, 'f32'),
    'captureLng':             (332, 'f32'),
}

# Origin detail enum (Holoholo.Rpc.PokemonOriginDetail)
ORIGIN_DETAIL_NAMES = {
    0: 'UNSET', 1: 'POKESTOP', 2: 'GYM', 3: 'PHOTOBOMBED', 4: 'GO_SNAPSHOT',
    5: 'GO_BATTLE_LEAGUE', 6: 'BATTLE_RAID', 7: 'INCENSE', 8: 'GIFT',
    9: 'ROUTE', 10: 'ADVENTURE_SYNC', 11: 'POKEMON_HOME', 12: 'BREAD',
    13: 'TRADE', 14: 'EGG_HATCH', 15: 'TUTORIAL'
}

# Pokeball enum
POKEBALL_NAMES = {0: 'UNKNOWN', 1: 'POKEBALL', 2: 'GREATBALL', 3: 'ULTRABALL', 4: 'MASTERBALL', 5: 'PREMIERBALL'}

# Gender enum
GENDER_NAMES = {0: 'UNSET', 1: 'MALE', 2: 'FEMALE', 3: 'GENDERLESS'}

# CPM -> level
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

def s2_cell_to_latlng(cell_id):
    """Convert S2 cell ID to approximate lat/lng (S2 level 17 cells are ~150m)."""
    if not cell_id: return None, None
    # Simplified S2 decoding - full impl would use s2 library
    # The face is high 3 bits
    face = (cell_id >> 60) & 0xF
    return None, None  # TODO: use s2sphere lib

def parse_proto(raw_hex):
    """Parse a raw 320-byte hex string into a fields dict."""
    if not raw_hex or len(raw_hex) < 600: return {}
    data = bytes.fromhex(raw_hex)
    if len(data) < 320: return {}

    fields = {}
    for name, (off, kind) in PROTO_FIELDS.items():
        try:
            if off + (8 if kind in ['i64', 'i64u', 'ptr', 'ptr_display'] else 4) > len(data):
                continue
            if kind == 'i32':
                fields[name] = struct.unpack_from('<i', data, off)[0]
            elif kind == 'i64':
                fields[name] = struct.unpack_from('<q', data, off)[0]
            elif kind == 'i64u':
                fields[name] = struct.unpack_from('<Q', data, off)[0]
            elif kind == 'f32':
                fields[name] = struct.unpack_from('<f', data, off)[0]
            elif kind == 'bool':
                fields[name] = bool(data[off])
            elif kind == 'ptr' or kind == 'ptr_display':
                fields[name] = struct.unpack_from('<Q', data, off)[0]
            elif kind == 'str':
                fields[name] = struct.unpack_from('<Q', data, off)[0]  # ptr value (string contents not in raw)
        except: pass
    return fields

def main():
    print("Loading pokemon_full.json...")
    raw = json.load(open('pokemon_full.json'))
    print(f"  {len(raw)} entries")

    db_path = 'pokemon.db'
    if os.path.exists(db_path): os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE pokemon (
        uid_hex TEXT PRIMARY KEY,
        uid INTEGER,
        pokemon_id INTEGER,
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
        nickname TEXT,
        deployed_fort_id TEXT,
        is_deployed BOOLEAN,
        captured_cell_id INTEGER,
        captured_cell_hex TEXT,
        origin_detail INTEGER,
        origin_detail_name TEXT,
        gender INTEGER,
        gender_name TEXT,
        costume INTEGER,
        form INTEGER,
        is_shiny BOOLEAN,
        alignment INTEGER,
        weather_boosted INTEGER,
        addr TEXT,
        display_raw TEXT,
        raw_proto_hex TEXT
    )''')

    inserted = 0
    skipped = 0
    seen = set()

    for p in raw:
        if not p.get('raw_proto'):
            skipped += 1; continue

        # Re-parse with full field set
        fields = parse_proto(p['raw_proto'])

        uid = fields.get('id_', 0)
        if uid == 0:
            skipped += 1; continue
        create_ms = fields.get('creationTimeMs_', 0)
        if create_ms < POGO_LAUNCH_MS:
            skipped += 1; continue

        uid_hex = f"{uid:016x}"
        if uid_hex in seen:
            skipped += 1; continue
        seen.add(uid_hex)

        pokemon_id = fields.get('pokemonId_', 0)
        cp = fields.get('cp_', 0)
        stamina = fields.get('stamina_', 0)
        stamina_max = fields.get('staminaMax_', 0)
        move1 = fields.get('move1_', 0)
        move2 = fields.get('move2_', 0)
        move3 = fields.get('move3_', 0)
        iv_atk = fields.get('individualAttack_', 0)
        iv_def = fields.get('individualDefense_', 0)
        iv_sta = fields.get('individualStamina_', 0)
        iv_t = iv_atk + iv_def + iv_sta
        iv_pct = round(iv_t / 45 * 100, 1)
        height = fields.get('heightM_', 0)
        weight = fields.get('weightKg_', 0)
        cpm = fields.get('cpMultiplier_', 0)
        num_addl_cpm = fields.get('numAdditionalCpMultiplier_', 0)
        level = cpm_to_level(cpm + (num_addl_cpm or 0))
        pokeball = fields.get('pokeball_', 0)
        captured_cell = fields.get('capturedCellId_', 0)
        captured_cell_hex = f"{captured_cell:016x}" if captured_cell else None
        # SQLite INTEGER is signed 64-bit, convert
        captured_cell_signed = captured_cell if captured_cell < 2**63 else captured_cell - 2**64
        origin = fields.get('originDetail_', 0)
        is_lucky = fields.get('isLucky_', False)

        deployed_fort_ptr = fields.get('deployedFortId_', 0)
        # Empty string ptr (System.String.Empty) sentinel value
        EMPTY_STR_PTR = 0x7b81c1cf40
        is_deployed = (deployed_fort_ptr != 0 and deployed_fort_ptr != EMPTY_STR_PTR)

        # Display fields (from previously enriched data)
        gender = costume = form = alignment = weather = 0
        is_shiny = False
        if 'display' in p and p['display']:
            d = p['display']
            gender = d.get('0x14', 0)
            # IL2CPP field order in PokemonDisplayProto:
            # gender(0x14), costume(0x18), shiny(0x1c?), form(0x20?), weather, alignment
            # Based on samples, 0x1c is often form (Unown=20)
            costume = d.get('0x18', 0)  # might be 0
            form = d.get('0x1c', 0)
            # shiny is bool - check b_0x18 OR b_0x20
            is_shiny = bool(d.get('b_0x20', 0)) or bool(d.get('b_0x24', 0))
            alignment = d.get('0x24', 0) or 0
            weather = d.get('0x28', 0) or 0

        try:
            dt = datetime.fromtimestamp(create_ms/1000, tz=timezone.utc).isoformat()
        except: dt = None

        uid_signed = uid if uid < 2**63 else uid - 2**64

        placeholders = ','.join(['?'] * 44)
        c.execute(f'INSERT OR IGNORE INTO pokemon VALUES ({placeholders})', (
            uid_hex, uid_signed, pokemon_id, cp, stamina, stamina_max,
            move1, move2, move3,
            iv_atk, iv_def, iv_sta, iv_t, iv_pct,
            iv_t == 45, iv_t == 0,
            height, weight, cpm, num_addl_cpm, level, num_addl_cpm > 0,
            pokeball, POKEBALL_NAMES.get(pokeball),
            create_ms, dt, is_lucky,
            p.get('nickname'),
            hex(deployed_fort_ptr) if deployed_fort_ptr else None, is_deployed,
            captured_cell_signed, captured_cell_hex,
            origin, ORIGIN_DETAIL_NAMES.get(origin),
            gender, GENDER_NAMES.get(gender), costume, form, is_shiny, alignment, weather,
            p['addr'], json.dumps(p.get('display', {})), p.get('raw_proto')
        ))
        # 44 cols expected
        inserted += 1

    # Indexes
    for col in ['pokemon_id', 'cp', 'iv_total', 'level', 'is_lucky', 'is_hundo',
                'creation_date', 'gender', 'is_shiny', 'pokeball', 'origin_detail',
                'is_deployed', 'is_best_buddy']:
        c.execute(f'CREATE INDEX idx_{col} ON pokemon({col})')

    conn.commit()

    # Stats
    print(f"\nInserted: {inserted}, filtered: {skipped}")
    print(f"\n=== Stats ===")
    queries = [
        ('SELECT COUNT(*) FROM pokemon', 'Total'),
        ('SELECT COUNT(DISTINCT pokemon_id) FROM pokemon', 'Species'),
        ('SELECT COUNT(*) FROM pokemon WHERE is_hundo', 'Hundos'),
        ('SELECT COUNT(*) FROM pokemon WHERE is_zero', 'Zeros'),
        ('SELECT COUNT(*) FROM pokemon WHERE is_lucky', 'Lucky'),
        ('SELECT COUNT(*) FROM pokemon WHERE is_shiny', 'Shiny (estimated)'),
        ('SELECT COUNT(*) FROM pokemon WHERE is_best_buddy', 'Best Buddy'),
        ('SELECT COUNT(*) FROM pokemon WHERE is_deployed', 'Deployed in gyms'),
        ('SELECT COUNT(*) FROM pokemon WHERE captured_cell_id != 0', 'Have location'),
        ('SELECT COUNT(*) FROM pokemon WHERE level >= 30', 'Level 30+'),
        ('SELECT COUNT(*) FROM pokemon WHERE level >= 40', 'Level 40+'),
    ]
    for q, label in queries:
        c.execute(q); print(f'  {label}: {c.fetchone()[0]}')

    print(f"\n=== Origin distribution ===")
    c.execute('SELECT origin_detail_name, COUNT(*) FROM pokemon GROUP BY origin_detail_name ORDER BY 2 DESC')
    for n, cnt in c.fetchall(): print(f'  {n or "UNSET"}: {cnt}')

    print(f"\n=== Best Buddies (top 10 by num_additional_cpm) ===")
    c.execute('SELECT pokemon_id, cp, level, num_additional_cpm FROM pokemon WHERE is_best_buddy ORDER BY num_additional_cpm DESC LIMIT 10')
    for r in c.fetchall(): print(f'  #{r[0]} CP{r[1]} L{r[2]} +cpm={r[3]:.4f}')

    print(f"\nDB: pokemon.db ({os.path.getsize(db_path)/1024:.0f} KB)")
    conn.close()

if __name__ == '__main__':
    main()

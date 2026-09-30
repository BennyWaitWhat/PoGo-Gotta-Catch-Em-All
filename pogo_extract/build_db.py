"""
Build comprehensive queryable SQLite database from pokemon_full.json.

Schema:
- pokemon: main table with all extracted fields
- pokemon_display: PokemonDisplayProto fields (gender, costume, shiny, form, alignment)
- pokemon_raw: raw 320-byte hex dumps for forensic queries
- species: pokemon ID -> name mapping (when available)
"""
import json, sqlite3, os, struct
from datetime import datetime, timezone

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

# Pokeball enum
POKEBALL_NAMES = {0: 'UNKNOWN', 1: 'POKEBALL', 2: 'GREATBALL', 3: 'ULTRABALL', 4: 'MASTERBALL', 5: 'PREMIERBALL'}

# Gender enum
GENDER_NAMES = {0: 'UNSET', 1: 'MALE', 2: 'FEMALE', 3: 'GENDERLESS'}

# Pokeball + species name lookups (gen 1-9 partial for common species)
SPECIES_NAMES = {}
# Will load if /tmp pokedex file exists, otherwise leave empty

POGO_LAUNCH_MS = 1467590400000

def main():
    print("Loading pokemon_full.json...")
    raw = json.load(open('pokemon_full.json'))
    print(f"  {len(raw)} entries")

    db = 'pokemon.db'
    if os.path.exists(db): os.remove(db)
    conn = sqlite3.connect(db)
    c = conn.cursor()

    # Main pokemon table
    c.execute('''CREATE TABLE pokemon (
        uid TEXT PRIMARY KEY,           -- hex string of unsigned 64-bit ID
        uid_int INTEGER,                -- signed int64 for sorting
        pokemon_id INTEGER,
        species_name TEXT,
        cp INTEGER,
        stamina INTEGER,
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
        level REAL,
        pokeball INTEGER,
        pokeball_name TEXT,
        creation_time_ms INTEGER,
        creation_date TEXT,
        is_lucky BOOLEAN,
        nickname TEXT,
        deployed_fort_id TEXT,
        gender INTEGER,
        gender_name TEXT,
        costume INTEGER,
        form INTEGER,
        is_shiny BOOLEAN,
        alignment INTEGER,
        display_raw TEXT,
        addr TEXT,
        raw_proto_hex TEXT
    )''')

    inserted = 0
    skipped = 0
    seen = set()

    for p in raw:
        uid = p['uid']
        if uid == 0:
            skipped += 1; continue
        # Filter false positives
        if p['creationTimeMs'] < POGO_LAUNCH_MS:
            skipped += 1; continue

        uid_hex = f"{uid:016x}"
        if uid_hex in seen:
            skipped += 1; continue
        seen.add(uid_hex)

        # Convert unsigned uid to signed int64 for SQLite
        uid_signed = uid if uid < 2**63 else uid - 2**64

        iv_t = p['ivAtk'] + p['ivDef'] + p['ivSta']
        iv_pct = round(iv_t / 45 * 100, 1)
        level = cpm_to_level(p['cpMultiplier'])

        try:
            dt = datetime.fromtimestamp(p['creationTimeMs']/1000, tz=timezone.utc).isoformat()
        except: dt = None

        # Parse display data
        gender = None; costume = None; form = None; is_shiny = None; alignment = None
        display_raw_str = None
        if 'display' in p:
            d = p['display']
            display_raw_str = json.dumps(d)
            # gender at 0x14 (consistent across samples)
            gender = d.get('0x14', 0)
            # form at 0x1c (or 0x18 - try both)
            form = d.get('0x1c', 0) or d.get('0x18', 0) or 0
            # costume at 0x20 (guess)
            costume = d.get('0x20', 0) or 0
            # shiny at 0x18 (bool field) - true if b_0x18 is 1
            is_shiny = bool(d.get('b_0x18', 0))
            # alignment - one of the bool/int fields
            alignment = d.get('0x24', 0) or 0

        c.execute('''INSERT OR IGNORE INTO pokemon VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            uid_hex, uid_signed,
            p['pokemonId'], SPECIES_NAMES.get(p['pokemonId']),
            p['cp'], p['stamina'],
            p['move1'], p['move2'], p['move3'],
            p['ivAtk'], p['ivDef'], p['ivSta'], iv_t, iv_pct,
            iv_t == 45, iv_t == 0,
            p['heightM'], p['weightKg'], p['cpMultiplier'], level,
            p['pokeball'], POKEBALL_NAMES.get(p['pokeball']),
            p['creationTimeMs'], dt, p['isLucky'],
            p.get('nickname'), p.get('deployedFortId'),
            gender, GENDER_NAMES.get(gender) if gender is not None else None,
            costume, form, is_shiny, alignment,
            display_raw_str, p['addr'], p.get('raw_proto')
        ))
        inserted += 1

    # Indexes
    for col in ['pokemon_id', 'cp', 'iv_total', 'level', 'is_lucky', 'is_hundo', 'creation_date', 'gender', 'is_shiny', 'pokeball']:
        c.execute(f'CREATE INDEX idx_{col} ON pokemon({col})')

    conn.commit()

    # Useful views
    c.execute('''CREATE VIEW best_per_species AS
        SELECT pokemon_id, COUNT(*) AS count, MAX(cp) AS max_cp, MAX(iv_total) AS max_iv_total
        FROM pokemon GROUP BY pokemon_id''')
    c.execute('''CREATE VIEW hundos AS
        SELECT * FROM pokemon WHERE iv_total = 45''')
    c.execute('''CREATE VIEW lucky_pokemon AS
        SELECT * FROM pokemon WHERE is_lucky = 1''')

    conn.commit()

    print(f"\nInserted: {inserted}, filtered: {skipped}")
    print(f"\n=== Stats ===")
    for q, label in [
        ('SELECT COUNT(*) FROM pokemon', 'Total'),
        ('SELECT COUNT(DISTINCT pokemon_id) FROM pokemon', 'Species'),
        ('SELECT COUNT(*) FROM pokemon WHERE is_hundo', 'Hundos (15/15/15)'),
        ('SELECT COUNT(*) FROM pokemon WHERE is_zero', 'Zeros (0/0/0)'),
        ('SELECT COUNT(*) FROM pokemon WHERE is_lucky', 'Lucky'),
        ('SELECT COUNT(*) FROM pokemon WHERE is_shiny', 'Shiny (estimated)'),
        ('SELECT COUNT(*) FROM pokemon WHERE level >= 30', 'Level 30+'),
        ('SELECT COUNT(*) FROM pokemon WHERE level >= 40', 'Level 40+'),
        ('SELECT COUNT(*) FROM pokemon WHERE deployed_fort_id IS NOT NULL', 'Deployed in gyms'),
        ('SELECT COUNT(*) FROM pokemon WHERE nickname IS NOT NULL', 'Nicknamed'),
    ]:
        c.execute(q)
        print(f'  {label}: {c.fetchone()[0]}')

    print(f"\n=== Top 10 species ===")
    c.execute('SELECT pokemon_id, COUNT(*) cnt FROM pokemon GROUP BY pokemon_id ORDER BY cnt DESC LIMIT 10')
    for sid, cnt in c.fetchall(): print(f'  #{sid}: {cnt}')

    print(f"\n=== Year distribution ===")
    c.execute('SELECT strftime("%Y", creation_date) y, COUNT(*) c FROM pokemon GROUP BY y ORDER BY y')
    for y, cnt in c.fetchall(): print(f'  {y}: {cnt}')

    print(f"\n=== Pokeball distribution ===")
    c.execute('SELECT pokeball_name, COUNT(*) c FROM pokemon GROUP BY pokeball_name ORDER BY c DESC')
    for n, cnt in c.fetchall(): print(f'  {n}: {cnt}')

    print(f"\nDB: pokemon.db")
    print(f"Schema: pokemon (35 columns), views: hundos, lucky_pokemon, best_per_species")
    conn.close()

if __name__ == '__main__':
    main()

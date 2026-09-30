"""
Convert pokemon_dump.json into a queryable SQLite database with enrichment:
- Calculated level from cpMultiplier
- IV percentage
- ISO timestamp from creation_time_ms
- Species name from global-metadata strings (if accessible)
"""
import json, sqlite3, os, re

# CPM -> level lookup (1.0 to 51.0 in 0.5 steps; from PoGo data)
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
    if cpm is None or cpm <= 0: return None
    best = min(CPM_TABLE, key=lambda x: abs(x[0] - cpm))
    return best[1]

def calc_cp(species_id, atk_iv, def_iv, sta_iv, cpm, base_stats):
    if species_id not in base_stats: return None
    a, d, s = base_stats[species_id]
    cp = ((a + atk_iv) * (d + def_iv) ** 0.5 * (s + sta_iv) ** 0.5 * cpm * cpm) / 10
    return max(10, int(cp))

def main():
    print("Loading pokemon_dump.json...")
    pokemon = json.load(open('pokemon_dump.json'))
    print(f"  {len(pokemon)} entries")

    db_path = 'pokemon.db'
    if os.path.exists(db_path): os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''
    CREATE TABLE pokemon (
        uid INTEGER PRIMARY KEY,
        pokemon_id INTEGER,
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
        height_m REAL,
        weight_kg REAL,
        cp_multiplier REAL,
        level REAL,
        pokeball INTEGER,
        creation_time_ms INTEGER,
        creation_date TEXT,
        is_lucky INTEGER,
        addr TEXT
    )''')

    from datetime import datetime, timezone
    POGO_LAUNCH_MS = 1467590400000  # 2016-07-04
    inserted = 0
    filtered_out = 0
    seen_uid = set()

    for p in pokemon:
        # Filter out false positives: zero creation time, zero uid
        if p['creationTimeMs'] < POGO_LAUNCH_MS or p['uid'] == 0:
            filtered_out += 1
            continue

        uid = p['uid']
        if uid in seen_uid:
            filtered_out += 1
            continue
        seen_uid.add(uid)

        iv_total = p['ivAtk'] + p['ivDef'] + p['ivSta']
        iv_pct = round(iv_total / 45 * 100, 1)
        level = cpm_to_level(p['cpMultiplier'])

        try:
            dt = datetime.fromtimestamp(p['creationTimeMs'] / 1000, tz=timezone.utc).isoformat()
        except (OSError, ValueError, OverflowError):
            dt = None

        c.execute('''INSERT OR IGNORE INTO pokemon VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            uid, p['pokemonId'], p['cp'], p['stamina'],
            p['move1'], p['move2'], p['move3'],
            p['ivAtk'], p['ivDef'], p['ivSta'], iv_total, iv_pct,
            p['heightM'], p['weightKg'], p['cpMultiplier'], level,
            p['pokeball'], p['creationTimeMs'], dt,
            1 if p['isLucky'] else 0, p['addr']
        ))
        inserted += 1

    # Indexes for fast queries
    c.execute('CREATE INDEX idx_species ON pokemon(pokemon_id)')
    c.execute('CREATE INDEX idx_iv ON pokemon(iv_total)')
    c.execute('CREATE INDEX idx_cp ON pokemon(cp)')
    c.execute('CREATE INDEX idx_level ON pokemon(level)')
    c.execute('CREATE INDEX idx_lucky ON pokemon(is_lucky)')

    conn.commit()

    # Summary
    print(f"Inserted: {inserted}, dedupe-skipped: {skipped}")
    print(f"\n=== Sanity queries ===")
    c.execute('SELECT COUNT(*) FROM pokemon'); print(f"Total: {c.fetchone()[0]}")
    c.execute('SELECT COUNT(DISTINCT pokemon_id) FROM pokemon'); print(f"Species: {c.fetchone()[0]}")
    c.execute('SELECT COUNT(*) FROM pokemon WHERE iv_total = 45'); print(f"Hundos (15/15/15): {c.fetchone()[0]}")
    c.execute('SELECT COUNT(*) FROM pokemon WHERE iv_total = 0'); print(f"Zeros (0/0/0): {c.fetchone()[0]}")
    c.execute('SELECT COUNT(*) FROM pokemon WHERE is_lucky = 1'); print(f"Lucky: {c.fetchone()[0]}")
    c.execute('SELECT COUNT(*) FROM pokemon WHERE level >= 40'); print(f"Level 40+: {c.fetchone()[0]}")
    c.execute('SELECT MIN(creation_date), MAX(creation_date) FROM pokemon WHERE creation_date IS NOT NULL')
    mn, mx = c.fetchone(); print(f"Date range: {mn} to {mx}")

    print(f"\nDB written: {db_path}")
    print(f"Schema: pokemon(uid, pokemon_id, cp, stamina, move1-3, iv_atk/def/sta/total/pct, height_m, weight_kg, cp_multiplier, level, pokeball, creation_time_ms/date, is_lucky, addr)")
    conn.close()

if __name__ == '__main__':
    main()

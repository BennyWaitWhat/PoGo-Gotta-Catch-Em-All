"""Find which hundos (100% IV) the user is missing per region."""
import sqlite3, json
gm = json.load(open('pvpoke_gamemaster.json'))

# Build species id list from PvPoke (only base species, no shadows/megas)
all_species = {}  # dex -> set of (form_label, speciesName)
for sp in gm['pokemon']:
    sid = sp.get('speciesId','')
    if any(x in sid for x in ('_shadow','_mega','_xl','_galarian_zen','_meteor','_ash','_blade','_school','_complete','_construct','_ultra','_unbound')):
        continue
    dex = sp.get('dex', 0)
    if dex < 1: continue
    name = sp.get('speciesName','')
    all_species.setdefault(dex, set()).add(name)

# Regions (Hisui shares dex range with Sinnoh/Unova/Hoenn — handle separately by name)
REGIONS = [
    ('Kanto', 1, 151),
    ('Johto', 152, 251),
    ('Hoenn', 252, 386),
    ('Sinnoh', 387, 493),
    ('Unova', 494, 649),
    ('Kalos', 650, 721),
    ('Alola', 722, 809),
    ('Galar', 810, 898),
    ('Hisui', 899, 905),
    ('Paldea', 906, 1025),
]

c = sqlite3.connect('pokemon.db').cursor()
have_hundo = set(r[0] for r in c.execute("SELECT DISTINCT pokemon_id FROM pokemon WHERE in_bag=1 AND iv_total=45").fetchall())
print(f"Hundo species owned (any region/form): {len(have_hundo)} unique pokemon_ids\n")

print("=== Missing hundos per region ===\n")
for region, lo, hi in REGIONS:
    region_dex = sorted([d for d in all_species.keys() if lo <= d <= hi])
    missing = []
    for d in region_dex:
        if d not in have_hundo:
            names = sorted(all_species[d])
            missing.append((d, names[0]))
    print(f"--- {region} ({lo}-{hi}) -- have {len(region_dex)-len(missing)}/{len(region_dex)}, missing {len(missing)} ---")
    for d, name in missing:
        print(f"  {d:4d}  {name}")
    print()

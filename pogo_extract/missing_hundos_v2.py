"""V2: Build exact missing-hundo list per PoGo's regional dex (cugs-cuha dicts)."""
import json
data = json.load(open('pokedex_regional.json'))
gm = json.load(open('pvpoke_gamemaster.json'))

# Build authoritative pid -> name
pid_name = {}
for sp in gm['pokemon']:
    sid = sp.get('speciesId','')
    if any(x in sid for x in ('_shadow','_mega','_xl')): continue
    dex = sp.get('dex',0)
    if dex < 1: continue
    if dex not in pid_name:
        pid_name[dex] = sp.get('speciesName','')

REGIONS = [
    ('Kanto',  'cugs'),
    ('Johto',  'cugt'),
    ('Hoenn',  'cugu'),
    ('Sinnoh', 'cugv'),
    ('Unova',  'cugw'),
    ('Kalos',  'cugx'),
    ('Alola',  'cugy'),
    ('Galar',  'cugz'),
    ('Paldea', 'cuha'),
]

print("=== Per-region dex hundo status ===\n")
for region, dict_label in REGIONS:
    entries = data[dict_label]
    have_hundo = [e for e in entries if e['hundo']]
    missing = [e for e in entries if not e['hundo']]
    missing_with_capture = [e for e in missing if e['captured'] > 0]
    missing_no_capture = [e for e in missing if e['captured'] == 0]
    print(f"## {region} ({dict_label}) -- {len(have_hundo)}/{len(entries)} hundos -- missing {len(missing)}")
    if missing_with_capture:
        print(f"  Caught (have at least one) but no hundo yet ({len(missing_with_capture)}):")
        for e in sorted(missing_with_capture, key=lambda x: x['pid']):
            name = pid_name.get(e['pid'], f'pid_{e["pid"]}')
            print(f"    {e['pid']:4d}  {name:30s}  caught={e['captured']:5d}")
    if missing_no_capture:
        print(f"  Never caught ({len(missing_no_capture)}):")
        for e in sorted(missing_no_capture, key=lambda x: x['pid']):
            name = pid_name.get(e['pid'], f'pid_{e["pid"]}')
            print(f"    {e['pid']:4d}  {name:30s}  encountered={e['encountered']}")
    print()

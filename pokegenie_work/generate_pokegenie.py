"""Generate a complete PokeGenie scan_data.json for the user's full current bag,
REPLACING old scans, with imageId from image_map.json when available. Field map reverse-
engineered from 6568 ground-truth entries (workflow wf_024767ce). PvP blocks omitted
(optional; PokeGenie recomputes from the exact IVs).

Two robustness fixes:
 - CPM: ~788 rows have cp_multiplier=0 in the DB -> derive CPM from level instead.
 - Base stats: chosen by which candidate form REPRODUCES the DB CP (self-correcting),
   so misresolved forms (e.g. armored vs regular Mewtwo) get the right maxCP."""
import sqlite3, json, os, sys, datetime
sys.path.insert(0, r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract")
from pvp_iv_rule import pvid

ROOT = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract"
PGDIR = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pokegenie_work\extracted"
OUT = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pokegenie_out"

# build_art.py writes image_map.json and scan_thumb/<imageId>.jpg from PokeMiners assets,
# preferring shiny and exact form/costume/gender art. Missing matches omit imageId so
# PokeGenie uses its default. Do not regenerate this map with the old add_images.py workflow.
_imgmap_path = os.path.join(OUT, 'image_map.json')
IMAGE_MAP = json.load(open(_imgmap_path, encoding='utf-8')) if os.path.exists(_imgmap_path) else {}
print('image_map: %d entries' % len(IMAGE_MAP))

mid2name = json.load(open(os.path.join(ROOT, 'move_id_to_name.json'), encoding='utf-8'))
gm = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))
BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
GM_NAME = {m['moveId']: m['name'] for m in gm['moves']}
# every candidate base-stat set per dex (deduped), for CP-matched form resolution
BY_DEX = {}
for _p in gm['pokemon']:
    _dex, _sid, _bs = _p.get('dex'), _p['speciesId'], _p.get('baseStats', {})
    if not _dex or not _bs or any(x in _sid for x in ('_mega', '_xl')): continue
    key = (_bs.get('atk'), _bs.get('def'), _bs.get('hp'))
    seen = BY_DEX.setdefault(_dex, [])
    if key not in [(b.get('atk'), b.get('def'), b.get('hp')) for b in seen]:
        seen.append(_bs)

CPM50 = 0.84029999
DUST = {1:200,2:200,3:400,4:400,5:600,6:600,7:800,8:800,9:1000,10:1000,11:1300,12:1300,13:1600,
        14:1600,15:1900,16:1900,17:2200,18:2200,19:2500,20:2500,21:3000,22:3000,23:3500,24:3500,
        25:4000,26:4000,27:4500,28:4500,29:5000,30:5000,31:6000,32:6000,33:7000,34:7000,35:8000,
        36:8000,37:9000,38:9000,39:10000,40:10000,41:11000,42:11000,43:12000,44:12000,45:13000,
        46:13000,47:14000,48:14000,49:15000,50:15000}
FORMREG = {'alolan':'Alola','galarian':'Galarian','hisuian':'Hisuian','paldean':'Paldean'}

def movename(mid):
    if not mid: return ""
    raw = mid2name.get(str(int(mid)))
    if not raw: return ""
    base = raw[:-5] if raw.endswith('_FAST') else raw
    nm = GM_NAME.get(base) or GM_NAME.get(raw)
    if nm: return nm
    if base.startswith('HIDDEN_POWER'): return 'Hidden Power'
    return ' '.join(w.capitalize() for w in base.split('_'))

def cp_at(b, a, d, s, cpm):
    return max(10, int((b.get('atk',0)+a) * (b.get('def',0)+d)**0.5 * (b.get('hp',0)+s)**0.5 * cpm*cpm / 10))
def hp_at(b, s, cpm):
    return max(10, int((b.get('hp',0)+s) * cpm))

conn = sqlite3.connect(os.path.join(ROOT, 'pokemon.db')); conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM pokemon WHERE in_bag=1 ORDER BY pokemon_id, iv_total DESC").fetchall()

# canonical CPM per level (to fill the ~788 rows whose cp_multiplier is 0).
# pass 1: any nonzero total CPM covers the level; pass 2: prefer a clean base CPM.
CPM_BY_LEVEL = {}
for r in rows:
    own = (r['cp_multiplier'] or 0) + (r['additional_cpm'] or 0)
    if own > 0: CPM_BY_LEVEL[r['level']] = own
for r in rows:
    if (r['cp_multiplier'] or 0) > 0 and (r['additional_cpm'] or 0) == 0:
        CPM_BY_LEVEL[r['level']] = r['cp_multiplier']
gaps = sorted(l for l in set(r['level'] for r in rows)
              if l not in CPM_BY_LEVEL and any(((rr['cp_multiplier'] or 0)+(rr['additional_cpm'] or 0))==0 for rr in rows if rr['level']==l))
if gaps: print("WARN zero-CPM rows at levels with NO reference:", gaps)

def cpm_for(r):
    own = (r['cp_multiplier'] or 0) + (r['additional_cpm'] or 0)
    return own if own > 0 else CPM_BY_LEVEL.get(r['level'], 0.094)

def base_for(r, cpm, a, d, s, dbcp):
    """Pick the base-stat set whose CP reproduces the DB CP at this level; else trust pvid."""
    pv = BS.get(pvid(r['species_name'], r['form'] or 0))
    cands = ([pv] if pv else []) + BY_DEX.get(r['pokemon_id'], [])
    for b in cands:
        if dbcp and abs(cp_at(b, a, d, s, cpm) - dbcp) <= 1:
            return b, True
    return (pv or (cands[0] if cands else {})), False

entries = []; matched = fallback = 0
for i, r in enumerate(rows):
    a, d, s = r['iv_atk'] or 0, r['iv_def'] or 0, r['iv_sta'] or 0
    lvl = float(r['level'] or 1); lvlstr = f"{lvl:.1f}"
    cpm = cpm_for(r); dbcp = r['cp'] or 0
    base, ok = base_for(r, cpm, a, d, s, dbcp)
    matched += ok; fallback += (not ok)
    ivpct = (a + d + s) / 45.0
    comb = {"attackIV": a, "defenseIV": d, "staminaIV": s, "pokemonLevel": lvlstr}
    e = {
        "id": str(i), "pokemonNumber": r['pokemon_id'], "pokemonName": r['species_name'],
        "avgAttackIV": a, "minAttackIV": a, "maxAttackIV": a,
        "avgDefenseIV": d, "minDefenseIV": d, "maxDefenseIV": d,
        "avgStaminaIV": s, "minStaminaIV": s, "maxStaminaIV": s,
        "ivPercentage": ivpct, "ivLower": ivpct, "ivUpper": ivpct,
        "cp": dbcp, "hp": r['stamina'] or 0, "dust": DUST.get(int(lvl), 0),
        "pokemonLevelLower": lvlstr, "pokemonLevelUpper": "",
        "scannedIvComb": comb, "singleValidIvComb": dict(comb), "singleIVComb": True,
        "minBattleIV": a + d, "maxBattleIV": a + d, "setPokemonLevel": round((lvl - 1) * 2),
        "arcAngle": (cpm - 0.094) / (CPM50 - 0.094) * 180, "cpNext": 0,
        "gender": 3 if (r['gender'] in (0, None)) else int(r['gender']),
        "shadowPokemon": int(r['fresh_alignment'] or 0), "isLuckyPokemon": bool(r['is_lucky']),
        "quickMove": movename(r['move1']), "chargeMove": movename(r['move2']),
        "chargeMove2": movename(r['move3']), "hiddenPowerType": "",
        "height": "%.2f" % (r['height_m'] or 0), "weight": "%.2f" % (r['weight_kg'] or 0),
        "maxCPLower": max(cp_at(base, a, d, s, CPM50), dbcp), "maxCPUpper": max(cp_at(base, a, d, s, CPM50), dbcp),
        "maxHPLower": max(hp_at(base, s, CPM50), r['stamina'] or 0), "maxHPUpper": max(hp_at(base, s, CPM50), r['stamina'] or 0),
        "buddyBoost": False, "weatherBoost": False, "hatchedFromEgg": bool(r['hatched_from_egg']),
        "defendingGym": False, "favSelection": 0, "capturePriority": 0, "megaSwitched": False,
        "selectedMegaEvol": 0, "userManuallySetPokemonLevel": False, "unread": True,
        "trainerLevel": 0, "appOverallL": "0", "appStatsL": "0",
        "pvpPinned": False, "pvpSelected": False, "pvpStatus": 1,
    }
    reg = (r['form_region'] or '').strip().lower()
    if reg in FORMREG: e["form"] = FORMREG[reg]
    if r['creation_time_ms']:
        dt = datetime.datetime.fromtimestamp(r['creation_time_ms'] / 1000)
        e["captureDay"], e["captureMonth"], e["captureYear"] = dt.day, dt.month, dt.year
        e["timeOfScan"] = dt.strftime('%Y-%m-%dT%H:%M:%S') + '-0400'
    else:
        e["captureDay"] = e["captureMonth"] = e["captureYear"] = 0
        e["timeOfScan"] = "2026-06-04T12:00:00-0400"
    _iid = IMAGE_MAP.get(r['uid_hex'])
    if _iid:
        e["imageId"] = _iid
    entries.append(e)

os.makedirs(OUT, exist_ok=True)
json.dump(entries, open(os.path.join(OUT, 'scan_data.json'), 'w', encoding='utf-8'), separators=(',', ':'))
meta = json.load(open(os.path.join(PGDIR, 'metadata.json'), encoding='utf-8'))
meta['numScans'] = len(entries); meta['lastBackupDate'] = "2026-06-04T12:00:00-0400"
meta['lastNameGenDate'] = meta['lastBackupDate']; meta['lastPokedexBackupDate'] = meta['lastBackupDate']
json.dump(meta, open(os.path.join(OUT, 'metadata.json'), 'w', encoding='utf-8'))

arc0 = sum(1 for e in entries if e['arcAngle'] == 0)
mlt = sum(1 for e in entries if e['maxCPLower'] < e['cp'])
print(f"GENERATED {len(entries)} | base CP-matched {matched}, pvid-fallback {fallback}")
print(f"arcAngle==0: {arc0} | maxCP<cp: {mlt}")
print("with imageId: %d of %d" % (sum(1 for e in entries if e.get('imageId')), len(entries)))

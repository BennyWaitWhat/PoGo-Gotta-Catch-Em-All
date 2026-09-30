import json
import re
import sqlite3
from collections import Counter

BASE = r'C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract'

with open(f'{BASE}\\form_enum.json', 'r', encoding='utf-8') as f:
    form_enum = json.load(f)

REGIONAL_TOKENS = ['ALOLA', 'GALARIAN', 'HISUIAN', 'PALDEA', 'PALDEACOMBAT',
                   'PALDEABLAZE', 'PALDEAAQUA', 'UNOVAN']

EVENT_TOKENS = ['GOTOUR', 'HORIZONS', 'PARTYHAT', 'BELLE', 'ROCKSTAR', 'COSPLAY',
                'ORIGINAL', 'SPIKY', 'SPRING', 'SUMMER', 'WINTER', 'HOLIDAY',
                'FESTIVAL', 'COSTUME', 'FLOWER']

COSMETIC_FAMILIES = {
    'PUMPKABOO': ['SMALL', 'AVERAGE', 'LARGE', 'SUPER'],
    'GOURGEIST': ['SMALL', 'AVERAGE', 'LARGE', 'SUPER'],
    'BURMY':     ['PLANT', 'SANDY', 'TRASH'],
    'WORMADAM':  ['PLANT', 'SANDY', 'TRASH'],
    'FURFROU':   ['NATURAL', 'HEART', 'STAR', 'DIAMOND', 'DEBUTANTE',
                  'MATRON', 'DANDY', 'LAREINE', 'KABUKI', 'PHARAOH'],
    'VIVILLON':  ['ARCHIPELAGO', 'CONTINENTAL', 'ELEGANT', 'FANCY', 'GARDEN',
                  'HIGHPLAINS', 'ICYSNOW', 'JUNGLE', 'MARINE', 'MEADOW',
                  'MODERN', 'MONSOON', 'OCEAN', 'POKEBALL', 'POLAR', 'RIVER',
                  'SANDSTORM', 'SAVANNA', 'SUN', 'TUNDRA'],
    'SCATTERBUG': ['ARCHIPELAGO', 'CONTINENTAL', 'ELEGANT', 'FANCY', 'GARDEN',
                   'HIGHPLAINS', 'ICYSNOW', 'JUNGLE', 'MARINE', 'MEADOW',
                   'MODERN', 'MONSOON', 'OCEAN', 'POKEBALL', 'POLAR', 'RIVER',
                   'SANDSTORM', 'SAVANNA', 'SUN', 'TUNDRA'],
    'SPEWPA':    ['ARCHIPELAGO', 'CONTINENTAL', 'ELEGANT', 'FANCY', 'GARDEN',
                  'HIGHPLAINS', 'ICYSNOW', 'JUNGLE', 'MARINE', 'MEADOW',
                  'MODERN', 'MONSOON', 'OCEAN', 'POKEBALL', 'POLAR', 'RIVER',
                  'SANDSTORM', 'SAVANNA', 'SUN', 'TUNDRA'],
    'FLABEBE':   ['RED', 'YELLOW', 'ORANGE', 'BLUE', 'WHITE'],
    'FLOETTE':   ['RED', 'YELLOW', 'ORANGE', 'BLUE', 'WHITE'],
    'FLORGES':   ['RED', 'YELLOW', 'ORANGE', 'BLUE', 'WHITE'],
}

def classify(fid: int, name: str) -> str:
    upper = name.upper()
    # Strip leading species prefix from match space when checking suffix tokens
    if fid == 0 or upper.endswith('NORMAL') or upper.endswith('UNSET'):
        return 'default'
    for tok in REGIONAL_TOKENS:
        if tok in upper:
            return 'regional'
    # Cosmetic family check before event so SPRING/etc don't override
    # only for genuine multi-pattern species (size/pattern/color).
    for species, suffixes in COSMETIC_FAMILIES.items():
        if upper.startswith(species):
            tail = upper[len(species):]
            if tail in suffixes:
                return 'cosmetic_family'
    for tok in EVENT_TOKENS:
        if tok in upper:
            return 'event'
    return 'form'

# Run classifier
classifications = {}
counts = Counter()
defies = []

for k, v in form_enum.items():
    fid = int(k)
    cat = classify(fid, v)
    classifications[fid] = cat
    counts[cat] += 1

# Identify forms that "defy classification" - the spec defines this as forms
# needing manual review. These are forms that fall into "form" by default
# but look like they might belong elsewhere, or where a real human should
# eye-check the assignment. We use heuristics to surface candidates.
DEFY_PATTERNS = [
    # Items that landed in "form" but contain numeric/date suffixes
    re.compile(r'\d{4}'),                       # year stamp -> probably event
    re.compile(r'(?i)copy|fall|vs\d|wcs|wildarea|adventurehat|gogglesred'),
    # Color suffix on a non-cosmetic-family species (gimmighoul coin, etc)
    re.compile(r'(?i)coin[a-z]\d'),
]

# Forms with non-obvious classification (manual review list)
for fid, cat in classifications.items():
    name = form_enum[str(fid)]
    upper = name.upper()

    # Surface candidates where classification might be wrong
    if cat == 'form':
        # year-stamped names that didn't match an event token
        if re.search(r'\d{4}', upper) or re.search(r'\d{2,}$', upper):
            defies.append((fid, name, cat, 'numeric/date suffix - likely event'))
            continue
        # Costume2020/Copy2019 outliers
        if 'COPY' in upper or 'FALL' in upper or 'WCS' in upper or 'KARIYUSHI' in upper \
           or 'POPSTAR' in upper or 'JEJU' in upper or 'KURTA' in upper \
           or 'DIWALI' in upper or 'WILDAREA' in upper or 'DOCTOR' in upper \
           or 'TSHIRT' in upper or 'GOGGLES' in upper or 'MONOCLE' in upper \
           or 'TRAINCONDUCTOR' in upper or 'BB2026' in upper \
           or 'VISOR' in upper or 'FOSSIL' in upper or 'TIARA' in upper \
           or 'SCARF' in upper or 'FLYING0' in upper or 'FLYING5' in upper \
           or 'ANNIVERSARY' in upper or 'JEJU' in upper or 'COINA' in upper:
            defies.append((fid, name, cat, 'event-like token not in EVENT_TOKENS spec'))
            continue
    if cat == 'event':
        # Seasonal forms tagged event but probably gameplay (Deerling/Sawsbuck)
        if upper.startswith('DEERLING') or upper.startswith('SAWSBUCK'):
            defies.append((fid, name, cat, 'seasonal gameplay form - SPRING/SUMMER/WINTER token; consider "form"'))
            continue
        # Magearna OriginalColor - "ORIGINAL" token but actually a gameplay form
        if upper == 'MAGEARNAORIGINALCOLOR':
            defies.append((fid, name, cat, 'ORIGINAL token but actually gameplay form variant'))
            continue

# Save classifications JSON
out_path = f'{BASE}\\form_category.json'
# Save with string keys (JSON-natural) but also dump python dict literal
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump({str(k): v for k, v in sorted(classifications.items())},
              f, indent=2)

# Cross-reference with pokemon.db
conn = sqlite3.connect(f'{BASE}\\pokemon.db')
cur = conn.cursor()
cur.execute("SELECT DISTINCT form FROM pokemon WHERE in_bag = 1")
db_forms = sorted(r[0] for r in cur.fetchall() if r[0] is not None)
unmapped_in_db = [f for f in db_forms if f not in classifications]

cur.execute("SELECT DISTINCT display_form FROM pokemon WHERE in_bag = 1")
db_display_forms = sorted(r[0] for r in cur.fetchall() if r[0] is not None)
unmapped_display = [f for f in db_display_forms if f not in classifications]

# Pretty print summary
print('='*60)
print('CATEGORY COUNTS:')
print('='*60)
for cat in ['default', 'regional', 'event', 'cosmetic_family', 'form']:
    print(f'  {cat:18s} {counts[cat]:5d}')
print(f'  {"TOTAL":18s} {sum(counts.values()):5d}')

print()
print('='*60)
print(f'DEFIES CLASSIFICATION (manual review needed): {len(defies)}')
print('='*60)
for fid, name, cat, reason in defies:
    print(f'  [{cat:16s}] {fid:5d} {name:45s} -- {reason}')

print()
print('='*60)
print('CROSS-REFERENCE WITH pokemon.db (in_bag=1):')
print('='*60)
print(f'  Distinct `form` values in bag:         {len(db_forms)}')
print(f'  Of those, NOT in form_enum.json:       {len(unmapped_in_db)}')
if unmapped_in_db:
    print('  Unmapped form IDs:')
    for f in unmapped_in_db:
        # Count occurrences
        cur.execute("SELECT COUNT(*), GROUP_CONCAT(DISTINCT species_name) FROM pokemon WHERE in_bag=1 AND form=?", (f,))
        cnt, species = cur.fetchone()
        print(f'    form={f:5d}  count={cnt:4d}  species={species}')
print()
print(f'  Distinct `display_form` values in bag: {len(db_display_forms)}')
print(f'  Of those, NOT in form_enum.json:       {len(unmapped_display)}')
if unmapped_display:
    print('  Unmapped display_form IDs:')
    for f in unmapped_display:
        cur.execute("SELECT COUNT(*), GROUP_CONCAT(DISTINCT species_name) FROM pokemon WHERE in_bag=1 AND display_form=?", (f,))
        cnt, species = cur.fetchone()
        print(f'    display_form={f:5d}  count={cnt:4d}  species={species}')

conn.close()
print()
print(f'Wrote {out_path}')

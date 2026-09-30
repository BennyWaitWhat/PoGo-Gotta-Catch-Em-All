import sqlite3, json, os, sys
from collections import defaultdict

DB = 'pokemon.db'
OUT = 'agent_outputs/hundo_audit.json'

REGIONS = [
    ('Kanto',    1,   151),
    ('Johto',    152, 251),
    ('Hoenn',    252, 386),
    ('Sinnoh',   387, 493),
    ('Unova',    494, 649),
    ('Kalos',    650, 721),
    ('Alola',    722, 809),
    ('Galar',    810, 905),
    ('Paldea',   906, 1025),
]

def region_for(pid):
    for name, lo, hi in REGIONS:
        if lo <= pid <= hi:
            return name
    return 'Unknown'

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT * FROM pokemon WHERE in_bag=1 AND is_hundo=1")
hundos = [dict(r) for r in cur.fetchall()]

# Backfill alignment classification: alignment_name NULL with is_purified_flag=0 -> NORMAL
def alignment_class(p):
    n = p['alignment_name']
    if n in ('SHADOW', 'PURIFIED'):
        return n
    return 'NORMAL'

# 1. Total
total = len(hundos)

# 2. Per region
by_region = defaultdict(int)
for p in hundos:
    by_region[region_for(p['pokemon_id'])] += 1
region_order = [r[0] for r in REGIONS] + ['Unknown']
per_region = {r: by_region[r] for r in region_order if by_region.get(r)}

# 3. Special status (each category is independent; a mon can be in multiple e.g. shiny+lucky)
shiny  = [p for p in hundos if p['is_shiny'] == 1]
lucky  = [p for p in hundos if p['is_lucky'] == 1]
shadow = [p for p in hundos if alignment_class(p) == 'SHADOW']
purified = [p for p in hundos if alignment_class(p) == 'PURIFIED']
normal = [p for p in hundos if alignment_class(p) == 'NORMAL']
best_buddy = [p for p in hundos if p['is_best_buddy'] == 1]
lucky_trade_hundos = lucky  # any lucky is by definition trade-acquired

specials = {
    'shiny':       len(shiny),
    'lucky':       len(lucky),
    'shadow':      len(shadow),
    'purified':    len(purified),
    'normal':      len(normal),
    'best_buddy':  len(best_buddy),
    'traded':      sum(1 for p in hundos if p['is_traded'] == 1),
}

# 4. Species with multiple hundos
# - High-level "I have N Lapras hundos": group by species_name (forms/costumes collapsed).
# - Dup detection bucket: (species_name, form, costume) - a different form/costume is a distinct collectible.

def species_key(p):
    return p['species_name'] or f"pid_{p['pokemon_id']}"

def dup_bucket_key(p):
    return (species_key(p), p['form'] or 0, p['costume'] or 0)

by_species_full = defaultdict(list)
for p in hundos:
    by_species_full[species_key(p)].append(p)

by_dup_bucket = defaultdict(list)
for p in hundos:
    by_dup_bucket[dup_bucket_key(p)].append(p)

multi_species = {s: len(lst) for s, lst in by_species_full.items() if len(lst) > 1}
multi_species_sorted = dict(sorted(multi_species.items(), key=lambda kv: (-kv[1], kv[0])))

# 5. Duplicate candidates: per species with >1 hundos, the non-special copies beyond the first (sorted by power level)
# "Specialness" tiers (sticky - keep them):
#   - shiny
#   - lucky
#   - shadow
#   - purified
#   - best buddy
#   - traded (lucky-friend etc - sentimental)
# Power proxy: cp (current). Higher = more invested.
# Within a species: rank by (is_special_desc, power_desc). Keepers = rank 0. Dupes = rank >= 1 AND not special.

def specialness_score(p):
    # higher = keep
    s = 0
    if p['is_shiny'] == 1: s += 100
    if p['is_lucky'] == 1: s += 80
    if alignment_class(p) == 'SHADOW': s += 60
    if alignment_class(p) == 'PURIFIED': s += 40
    if p['is_best_buddy'] == 1: s += 30
    if p['is_traded'] == 1: s += 10
    return s

def is_special(p):
    return specialness_score(p) > 0

duplicate_candidates = []
species_breakdown = []

for sp, lst in by_species_full.items():
    if len(lst) <= 1:
        continue
    # Sort by specialness desc, then cp desc, then level desc
    ranked = sorted(lst, key=lambda p: (-specialness_score(p), -(p['cp'] or 0), -(p['level'] or 0)))
    keepers = []
    dups = []
    seen_keeper = False
    for p in ranked:
        if not seen_keeper:
            keepers.append(p)
            seen_keeper = True
            continue
        if is_special(p):
            keepers.append(p)
        else:
            dups.append(p)

    species_breakdown.append({
        'species': sp,
        'total_hundos': len(lst),
        'keepers': len(keepers),
        'transfer_candidates': len(dups),
        'transfer_uids': [d['uid_hex'] for d in dups],
    })
    for d in dups:
        duplicate_candidates.append({
            'uid_hex': d['uid_hex'],
            'species_name': d['species_name'],
            'pokemon_id': d['pokemon_id'],
            'cp': d['cp'],
            'level': d['level'],
            'iv_atk': d['iv_atk'],
            'iv_def': d['iv_def'],
            'iv_sta': d['iv_sta'],
            'is_shiny': d['is_shiny'],
            'is_lucky': d['is_lucky'],
            'alignment_name': alignment_class(d),
            'is_best_buddy': d['is_best_buddy'],
            'is_traded': d['is_traded'],
            'is_powered_up': d['is_powered_up'],
            'gender_name': d['gender_name'],
            'form': d['form'],
            'costume': d['costume'],
            'creation_date': d['creation_date'],
            'nickname': d['nickname'],
            'region': region_for(d['pokemon_id']),
        })

species_breakdown.sort(key=lambda x: (-x['transfer_candidates'], -x['total_hundos'], x['species']))

# Snapshot of every multi-hundo species with detail rows (for the user to inspect)
multi_species_detail = []
for sp in sorted(by_species_full.keys(), key=lambda s: (-len(by_species_full[s]), s)):
    lst = by_species_full[sp]
    if len(lst) <= 1: continue
    rows = sorted(lst, key=lambda p: (-specialness_score(p), -(p['cp'] or 0)))
    multi_species_detail.append({
        'species': sp,
        'count': len(lst),
        'copies': [{
            'uid_hex': p['uid_hex'],
            'cp': p['cp'],
            'level': p['level'],
            'is_shiny': p['is_shiny'],
            'is_lucky': p['is_lucky'],
            'alignment': alignment_class(p),
            'is_best_buddy': p['is_best_buddy'],
            'is_traded': p['is_traded'],
            'is_powered_up': p['is_powered_up'],
            'special_score': specialness_score(p),
            'gender_name': p['gender_name'],
            'form': p['form'],
            'costume': p['costume'],
            'creation_date': p['creation_date'],
        } for p in rows],
    })

out = {
    'audit_date': '2026-05-20',
    'criteria': {
        'in_bag': 1,
        'is_hundo': 1,
        'iv_total': 45,
    },
    'totals': {
        'total_hundos': total,
        'expected_per_recent_stats': 569,
        'match': total == 569,
    },
    'per_region': per_region,
    'special_status': specials,
    'special_status_notes': (
        'Categories overlap: a hundo can be both shiny and lucky, etc. '
        'normal/shadow/purified are mutually exclusive (alignment). '
        '4 hundos had NULL alignment_name with is_purified_flag=0 - counted as NORMAL.'
    ),
    'multi_hundo_species_count': len(multi_species_sorted),
    'multi_hundo_species': multi_species_sorted,
    'multi_hundo_species_detail': multi_species_detail,
    'duplicate_candidates': duplicate_candidates,
    'duplicate_candidate_count': len(duplicate_candidates),
    'species_breakdown': species_breakdown,
    'keeper_rules': {
        'always_keep': [
            'first hundo per species (the best-powered or most-special copy)',
            'any shiny hundo',
            'any lucky hundo',
            'any shadow hundo (uncleansed)',
            'any purified hundo (cleansed)',
            'any best-buddy hundo',
            'any traded hundo (sentimental)',
        ],
        'dup_definition': 'A non-special hundo copy that ranks below the top keeper in its species AND has no special flag.',
        'power_proxy': 'CP (current). Higher CP -> more invested -> retain over lower-CP duplicate.',
    },
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w') as f:
    json.dump(out, f, indent=2, default=str)

print(f'Wrote {OUT}')
print(f'Total hundos: {total} (expected 569: {total==569})')
print(f'Multi-hundo species: {len(multi_species_sorted)}')
print(f'Duplicate transfer candidates: {len(duplicate_candidates)}')
print('Per region:', per_region)
print('Specials:', specials)
print('Top multi-hundo species:')
for sp, c in list(multi_species_sorted.items())[:15]:
    print(f'  {sp}: {c}')

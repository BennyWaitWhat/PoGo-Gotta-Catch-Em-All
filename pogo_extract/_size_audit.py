import sqlite3, json, os
from collections import defaultdict

con = sqlite3.connect('pokemon.db')
con.row_factory = sqlite3.Row
cur = con.cursor()

SIZE_NAMES = {0: 'XXS', 1: 'XS', 2: 'NORMAL', 3: 'NORMAL', 4: 'L', 5: 'XXL'}
# Per project knowledge: server uses 5 categories. Map enum -> name.
# Looking at counts: 0=28, 1=26, 2=111, 3=4305, 4=101, 5=127
# Standard PoGo size_category enum: 0=UNSET, 1=XXS, 2=XS, 3=NORMAL/UNSET-DEFAULT, 4=XL, 5=XXL
# But user spec says: XXS, XS, NORMAL, L, XXL. The bag has all 6 buckets (0..5).
# Use both: numeric distribution AND named per the user's labels.
ENUM_LABEL = {0: 'XXS', 1: 'XS', 2: 'NORMAL_SMALL', 3: 'NORMAL', 4: 'L', 5: 'XXL'}

# Per memory: JUMBO rule = top-2 weight UNION top-2 height per (sp, form, costume) bucket among size=5
# TINY = size_category=1 (likely)

out = {}

# 1) Distribution
cur.execute("""
SELECT pokemon_size_category, COUNT(*) FROM pokemon
WHERE in_bag=1
GROUP BY pokemon_size_category
ORDER BY pokemon_size_category
""")
dist_bag = [{'size': r[0], 'label': ENUM_LABEL.get(r[0], 'UNKNOWN'), 'count': r[1]} for r in cur.fetchall()]

cur.execute("""
SELECT pokemon_size_category, COUNT(*) FROM pokemon
GROUP BY pokemon_size_category
ORDER BY pokemon_size_category
""")
dist_all = [{'size': r[0], 'label': ENUM_LABEL.get(r[0], 'UNKNOWN'), 'count': r[1]} for r in cur.fetchall()]

out['distribution'] = {
    'in_bag_only': dist_bag,
    'all_rows': dist_all,
    'note': 'enum: 0=XXS, 1=XS, 2=NORMAL_SMALL, 3=NORMAL, 4=L, 5=XXL (user requested XXS/XS/NORMAL/L/XXL labels)',
}

# 2) JUMBO groups by species+form
cur.execute("""
SELECT species_name, form, COUNT(*) as n
FROM pokemon
WHERE in_bag=1 AND pokemon_size_category=5
GROUP BY species_name, form
ORDER BY n DESC, species_name
""")
jumbo_groups = [{'species': r[0], 'form': r[1], 'count': r[2]} for r in cur.fetchall()]
out['jumbo_groups'] = jumbo_groups

# 3) TINY groups (size=1)
cur.execute("""
SELECT species_name, form, COUNT(*) as n
FROM pokemon
WHERE in_bag=1 AND pokemon_size_category=1
GROUP BY species_name, form
ORDER BY n DESC, species_name
""")
tiny_groups = [{'species': r[0], 'form': r[1], 'count': r[2]} for r in cur.fetchall()]
out['tiny_groups'] = tiny_groups

# Also XXS
cur.execute("""
SELECT species_name, form, COUNT(*) as n
FROM pokemon
WHERE in_bag=1 AND pokemon_size_category=0
GROUP BY species_name, form
ORDER BY n DESC, species_name
""")
xxs_groups = [{'species': r[0], 'form': r[1], 'count': r[2]} for r in cur.fetchall()]
out['xxs_groups'] = xxs_groups

# 4) Top 5 heaviest/tallest per species
# Pull all pokemon w/ height/weight + needed fields
cur.execute("""
SELECT uid_hex, species_name, form, costume, height_m, weight_kg,
       pokemon_size_category, auth_tag_names, is_shiny, iv_total, iv_pct, nickname
FROM pokemon
WHERE in_bag=1 AND height_m IS NOT NULL AND weight_kg IS NOT NULL
""")
rows = cur.fetchall()

by_species = defaultdict(list)
for r in rows:
    by_species[r['species_name']].append(dict(r))

top5_per_species = {}
for sp, lst in by_species.items():
    heaviest = sorted(lst, key=lambda x: x['weight_kg'], reverse=True)[:5]
    tallest = sorted(lst, key=lambda x: x['height_m'], reverse=True)[:5]
    def pick(r):
        return {
            'uid_hex': r['uid_hex'],
            'form': r['form'],
            'costume': r['costume'],
            'height_m': r['height_m'],
            'weight_kg': r['weight_kg'],
            'size_cat': r['pokemon_size_category'],
            'is_shiny': bool(r['is_shiny']),
            'nickname': r['nickname'],
            'iv_pct': r['iv_pct'],
            'tags': r['auth_tag_names'] or '',
        }
    top5_per_species[sp] = {
        'heaviest': [pick(r) for r in heaviest],
        'tallest': [pick(r) for r in tallest],
    }
out['top5_per_species'] = top5_per_species

# 5) JUMBO candidates: per project memory rule:
# JUMBO = (top-2 weight) UNION (top-2 height) per (sp, form, costume) bucket, AMONG size=5 pokemon
cur.execute("""
SELECT uid_hex, species_name, form, costume, height_m, weight_kg,
       pokemon_size_category, auth_tag_names, nickname
FROM pokemon
WHERE in_bag=1 AND pokemon_size_category=5
""")
xxl_rows = [dict(r) for r in cur.fetchall()]

# Group by (species, form, costume)
bucket = defaultdict(list)
for r in xxl_rows:
    key = (r['species_name'], r['form'], r['costume'])
    bucket[key].append(r)

candidates_should_be_jumbo = []
already_tagged = []
qualifying_uids = set()

for key, lst in bucket.items():
    # top-2 by weight
    top_w = sorted(lst, key=lambda x: x['weight_kg'] or 0, reverse=True)[:2]
    # top-2 by height
    top_h = sorted(lst, key=lambda x: x['height_m'] or 0, reverse=True)[:2]
    qualifying = {r['uid_hex'] for r in top_w} | {r['uid_hex'] for r in top_h}
    qualifying_uids |= qualifying
    for r in lst:
        is_qual = r['uid_hex'] in qualifying
        has_jumbo = 'JUMBO' in (r['auth_tag_names'] or '')
        if is_qual and not has_jumbo:
            candidates_should_be_jumbo.append({
                'uid_hex': r['uid_hex'],
                'species': r['species_name'],
                'form': r['form'],
                'costume': r['costume'],
                'height_m': r['height_m'],
                'weight_kg': r['weight_kg'],
                'nickname': r['nickname'],
                'current_tags': r['auth_tag_names'] or '',
                'qualifies_via': (
                    ('weight' if r['uid_hex'] in {x['uid_hex'] for x in top_w} else '') +
                    ('+' if r['uid_hex'] in {x['uid_hex'] for x in top_w} and r['uid_hex'] in {x['uid_hex'] for x in top_h} else '') +
                    ('height' if r['uid_hex'] in {x['uid_hex'] for x in top_h} else '')
                ),
            })
        if has_jumbo:
            already_tagged.append({
                'uid_hex': r['uid_hex'],
                'species': r['species_name'],
                'form': r['form'],
                'still_qualifies': is_qual,
            })

# Also flag JUMBO-tagged that no longer qualify (lost top-2)
no_longer_qualifies = [x for x in already_tagged if not x['still_qualifies']]

out['jumbo_audit'] = {
    'rule': 'JUMBO = top-2 weight UNION top-2 height per (species, form, costume) bucket among size_category=5',
    'total_xxl_in_bag': len(xxl_rows),
    'distinct_buckets': len(bucket),
    'qualifying_count': len(qualifying_uids),
    'already_jumbo_tagged': len(already_tagged),
    'candidates_missing_jumbo': candidates_should_be_jumbo,
    'tagged_but_no_longer_qualifies': no_longer_qualifies,
}

# Save
os.makedirs('agent_outputs', exist_ok=True)
with open('agent_outputs/size_audit.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=2, default=str)

# Summary print
print('=== SIZE AUDIT SUMMARY ===')
print()
print('Distribution (in_bag=1):')
for d in dist_bag:
    print(f"  size={d['size']} ({d['label']}): {d['count']}")
print()
print(f'JUMBO species/form groups: {len(jumbo_groups)}')
print('Top 10:')
for g in jumbo_groups[:10]:
    print(f"  {g['species']} (form={g['form']}): {g['count']}")
print()
print(f'TINY (size=1) species/form groups: {len(tiny_groups)}')
print('Top 10:')
for g in tiny_groups[:10]:
    print(f"  {g['species']} (form={g['form']}): {g['count']}")
print()
print(f'XXL pokemon: {len(xxl_rows)}')
print(f'Distinct (sp,form,costume) buckets among XXL: {len(bucket)}')
print(f'Total qualifying (top-2 weight UNION top-2 height): {len(qualifying_uids)}')
print(f'Already JUMBO-tagged: {len(already_tagged)}')
print(f'NEW JUMBO candidates (qualify but untagged): {len(candidates_should_be_jumbo)}')
print(f'JUMBO-tagged but no longer qualifies: {len(no_longer_qualifies)}')
print()
print('Wrote agent_outputs/size_audit.json')

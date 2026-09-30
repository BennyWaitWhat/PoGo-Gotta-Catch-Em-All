import sqlite3, json, os
from collections import defaultdict

with open('form_category.json') as f:
    fc = json.load(f)

regionals = {k: v for k, v in fc.items() if v.get('category') == 'regional'}
key_to_meta = {}
for k, v in regionals.items():
    pid, form = k.split('_')
    key_to_meta[(int(pid), int(form))] = v

con = sqlite3.connect('pokemon.db')
cur = con.cursor()

pairs = list(key_to_meta.keys())
where_clause = " OR ".join([f"(pokemon_id={pid} AND form={form})" for pid, form in pairs])
q = f"""
SELECT pokemon_id, form, uid_hex, nickname, iv_pct, iv_total, is_hundo, is_shiny,
       cp, level, cull_decision_v9, cull_reason_v9, is_lucky, is_traded
FROM pokemon
WHERE in_bag=1 AND ({where_clause})
"""
cur.execute(q)
all_rows = cur.fetchall()
print(f'Total regional pokemon in_bag: {len(all_rows)}')

def region_of(form_name):
    if 'ALOLA' in form_name: return 'Alolan'
    if 'GALARIAN' in form_name: return 'Galarian'
    if 'HISUIAN' in form_name: return 'Hisuian'
    if 'PALDEA' in form_name: return 'Paldean'
    if 'UNOVAN' in form_name: return 'Unovan'
    return 'Unknown'

per_form = defaultdict(lambda: {
    'count': 0, 'best_iv': 0.0, 'best_iv_total': 0, 'hundo_count': 0,
    'shiny_count': 0, 'lucky_count': 0, 'traded_count': 0,
    'keep_count': 0, 'transfer_count': 0, 'transfer_examples': [],
})

for row in all_rows:
    pid, form, uid_hex, nick, iv_pct, iv_tot, hundo, shiny, cp, lvl, dec, reason, lucky, traded = row
    key = (pid, form)
    e = per_form[key]
    e['count'] += 1
    iv_pct_val = iv_pct or 0.0
    if iv_pct_val > e['best_iv']:
        e['best_iv'] = iv_pct_val
        e['best_iv_total'] = iv_tot or 0
    if hundo: e['hundo_count'] += 1
    if shiny: e['shiny_count'] += 1
    if lucky: e['lucky_count'] += 1
    if traded: e['traded_count'] += 1
    if dec == 'KEEP':
        e['keep_count'] += 1
    elif dec == 'TRANSFER':
        e['transfer_count'] += 1
        e['transfer_examples'].append({
            'uid_hex': uid_hex, 'nickname': nick,
            'iv_pct': round(iv_pct_val, 1), 'cp': cp, 'reason': reason,
        })

output = {
    'meta': {
        'generated': '2026-05-20',
        'source': 'pokemon.db (in_bag=1) + form_category.json (category=regional)',
        'total_regional_forms_defined': len(regionals),
        'total_regional_in_bag': len(all_rows),
    },
    'by_form': {},
    'gaps_zero_owned': [],
    'singletons_at_risk': [],
    'transferring_suspicious': [],
    'hundo_holders': [],
    'well_stocked': [],
    'by_region': {},
}

for key, meta in key_to_meta.items():
    pid, form = key
    species = meta['species']
    form_name = meta['form_name']
    region = region_of(form_name)
    form_key = f'{pid}_{form}'

    entry = per_form.get(key)
    if entry is None or entry['count'] == 0:
        output['by_form'][form_key] = {
            'pokemon_id': pid, 'form': form, 'species': species, 'form_name': form_name,
            'region': region, 'count': 0, 'best_iv': None,
            'hundo_count': 0, 'shiny_count': 0, 'lucky_count': 0, 'traded_count': 0,
            'cull_distribution': {'KEEP': 0, 'TRANSFER': 0},
            'transfer_examples': [], 'status': 'MISSING',
        }
        output['gaps_zero_owned'].append({
            'pokemon_id': pid, 'form': form, 'species': species,
            'form_name': form_name, 'region': region,
        })
        continue

    count = entry['count']
    keep_count = entry['keep_count']
    status_tags = []
    if count == 1: status_tags.append('SINGLETON')
    if keep_count == 0 and count > 0: status_tags.append('ALL_TRANSFERRING')
    if entry['hundo_count'] > 0: status_tags.append('HAS_HUNDO')
    if count >= 5: status_tags.append('WELL_STOCKED')
    if entry['shiny_count'] > 0: status_tags.append('HAS_SHINY')

    form_entry = {
        'pokemon_id': pid, 'form': form, 'species': species, 'form_name': form_name,
        'region': region, 'count': count, 'best_iv': round(entry['best_iv'], 1),
        'best_iv_total': entry['best_iv_total'],
        'hundo_count': entry['hundo_count'], 'shiny_count': entry['shiny_count'],
        'lucky_count': entry['lucky_count'], 'traded_count': entry['traded_count'],
        'cull_distribution': {'KEEP': entry['keep_count'], 'TRANSFER': entry['transfer_count']},
        'transfer_examples': entry['transfer_examples'],
        'status': status_tags,
    }
    output['by_form'][form_key] = form_entry

    if 'SINGLETON' in status_tags:
        output['singletons_at_risk'].append({
            'species': species, 'form_name': form_name, 'region': region,
            'best_iv': round(entry['best_iv'], 1),
            'is_hundo': entry['hundo_count'] > 0,
            'is_shiny': entry['shiny_count'] > 0,
            'is_being_transferred': entry['transfer_count'] > 0,
        })
    if entry['hundo_count'] > 0:
        output['hundo_holders'].append({
            'species': species, 'form_name': form_name, 'region': region,
            'hundo_count': entry['hundo_count'], 'count': count,
        })
    if entry['transfer_count'] > 0:
        keepers_left = entry['keep_count']
        flags = []
        if keepers_left == 0:
            flags.append('NO_KEEPERS_LEFT')
        elif keepers_left == 1 and entry['transfer_count'] >= 1:
            flags.append('ONLY_1_KEEPER')
        max_transfer_iv = max((x['iv_pct'] for x in entry['transfer_examples']), default=0)
        if max_transfer_iv >= entry['best_iv'] - 0.001 and max_transfer_iv > 0:
            flags.append('TRANSFERRING_BEST_IV')
        if flags:
            output['transferring_suspicious'].append({
                'species': species, 'form_name': form_name, 'region': region,
                'keepers_left': keepers_left, 'transfer_count': entry['transfer_count'],
                'best_iv': round(entry['best_iv'], 1),
                'flag_reasons': flags,
                'transfer_examples': entry['transfer_examples'],
            })
    if count >= 5:
        output['well_stocked'].append({
            'species': species, 'form_name': form_name, 'region': region,
            'count': count, 'best_iv': round(entry['best_iv'], 1),
        })

region_stats = defaultdict(lambda: {
    'forms_defined': 0, 'forms_owned': 0, 'total_specimens': 0,
    'hundo_count': 0, 'missing_forms': [],
})
for key, meta in key_to_meta.items():
    region = region_of(meta['form_name'])
    region_stats[region]['forms_defined'] += 1
    entry = per_form.get(key)
    if entry and entry['count'] > 0:
        region_stats[region]['forms_owned'] += 1
        region_stats[region]['total_specimens'] += entry['count']
        region_stats[region]['hundo_count'] += entry['hundo_count']
    else:
        region_stats[region]['missing_forms'].append(meta['form_name'])
output['by_region'] = dict(region_stats)

os.makedirs('agent_outputs', exist_ok=True)
with open('agent_outputs/regional_audit.json', 'w') as f:
    json.dump(output, f, indent=2)

print('Wrote agent_outputs/regional_audit.json')
print()
print('=== SUMMARY ===')
print(f"Total regional forms defined: {len(regionals)}")
print(f"Total regional pokemon in_bag: {len(all_rows)}")
print(f"Forms with zero owned (gaps): {len(output['gaps_zero_owned'])}")
print(f"Singletons (only 1): {len(output['singletons_at_risk'])}")
print(f"Hundo holders: {len(output['hundo_holders'])}")
print(f"Suspicious transfers: {len(output['transferring_suspicious'])}")
print(f"Well-stocked (>=5): {len(output['well_stocked'])}")
print()
print('=== BY REGION ===')
for r, s in region_stats.items():
    print(f"{r}: {s['forms_owned']}/{s['forms_defined']} forms, {s['total_specimens']} total, {s['hundo_count']} hundo")
    if s['missing_forms']:
        print(f"  MISSING: {s['missing_forms']}")

print()
print('=== SINGLETONS ===')
for s in output['singletons_at_risk']:
    flags = []
    if s['is_hundo']: flags.append('HUNDO')
    if s['is_shiny']: flags.append('SHINY')
    if s['is_being_transferred']: flags.append('!!TRANSFERRING!!')
    print(f"  {s['species']:14s} {s['form_name']:40s} best_iv={s['best_iv']:5.1f} {' '.join(flags)}")

print()
print('=== HUNDO HOLDERS ===')
for h in output['hundo_holders']:
    print(f"  {h['species']:14s} {h['form_name']:40s} hundos={h['hundo_count']} total={h['count']}")

print()
print('=== SUSPICIOUS TRANSFERS ===')
for t in output['transferring_suspicious']:
    print(f"  {t['species']:14s} {t['form_name']:40s} keepers_left={t['keepers_left']} xfer={t['transfer_count']} flags={t['flag_reasons']}")
    for ex in t['transfer_examples'][:3]:
        print(f"     -> {ex['nickname']} iv={ex['iv_pct']} cp={ex['cp']} reason={ex['reason']}")

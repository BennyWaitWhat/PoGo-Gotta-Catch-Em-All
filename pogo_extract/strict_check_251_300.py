import sqlite3
import json
from collections import Counter

conn = sqlite3.connect('pokemon.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

with open('agent_outputs/bucket_251_300.json', 'r') as f:
    orig = json.load(f)

all_candidates = []
for sb in orig['sub_buckets']:
    for cand in sb['additional_candidates']:
        all_candidates.append(cand)

print(f"Total original candidates: {len(all_candidates)}")

strict_candidates = []
drops = []


def safe(x):
    return x if x is not None else 99999


for cand in all_candidates:
    pid = cand['pokemon_id']
    form = cand['form']
    fc = cand['fresh_costume']
    uid_hex = cand['uid_hex']
    iv_total = cand['iv_total']

    if iv_total >= 37:
        drops.append({
            'uid_hex': uid_hex,
            'species_name': cand['species_name'],
            'pid': pid, 'form': form, 'fc': fc,
            'iv_total': iv_total,
            'reason': f'too high IV (iv_total={iv_total} >= 37)'
        })
        continue

    c.execute("SELECT COUNT(*) as cnt FROM pokemon WHERE pokemon_id=? AND form=? AND fresh_costume=?",
              (pid, form, fc))
    bucket_count = c.fetchone()['cnt']

    if bucket_count < 4:
        drops.append({
            'uid_hex': uid_hex,
            'species_name': cand['species_name'],
            'pid': pid, 'form': form, 'fc': fc,
            'iv_total': iv_total,
            'bucket_count': bucket_count,
            'reason': f'bucket too small (count={bucket_count} < 4)'
        })
        continue

    c.execute("""SELECT uid_hex, gl_rank, ul_rank, ll_rank, iv_total, is_shiny, cp
                 FROM pokemon WHERE pokemon_id=? AND form=? AND fresh_costume=?
                 ORDER BY iv_total DESC, cp DESC""", (pid, form, fc))
    bucket_rows = c.fetchall()

    min_gl = min(safe(r['gl_rank']) for r in bucket_rows)
    min_ul = min(safe(r['ul_rank']) for r in bucket_rows)
    min_ll = min(safe(r['ll_rank']) for r in bucket_rows)

    me = next((r for r in bucket_rows if r['uid_hex'] == uid_hex), None)
    if me is None:
        drops.append({
            'uid_hex': uid_hex,
            'species_name': cand['species_name'],
            'pid': pid, 'form': form, 'fc': fc,
            'iv_total': iv_total,
            'reason': 'candidate not found in DB'
        })
        continue

    gl_top = [r for r in bucket_rows if safe(r['gl_rank']) == min_gl]
    ul_top = [r for r in bucket_rows if safe(r['ul_rank']) == min_ul]
    ll_top = [r for r in bucket_rows if safe(r['ll_rank']) == min_ll]

    sole_rank1 = False
    leagues_sole = []
    if safe(me['gl_rank']) == min_gl and len(gl_top) == 1:
        sole_rank1 = True
        leagues_sole.append('GL')
    if safe(me['ul_rank']) == min_ul and len(ul_top) == 1:
        sole_rank1 = True
        leagues_sole.append('UL')
    if safe(me['ll_rank']) == min_ll and len(ll_top) == 1:
        sole_rank1 = True
        leagues_sole.append('LL')

    if sole_rank1:
        drops.append({
            'uid_hex': uid_hex,
            'species_name': cand['species_name'],
            'pid': pid, 'form': form, 'fc': fc,
            'iv_total': iv_total,
            'reason': f'sole rank-1 in league(s) {",".join(leagues_sole)}'
        })
        continue

    same_bucket_candidates = [
        cd for cd in all_candidates
        if cd['pokemon_id'] == pid and cd['form'] == form and cd['fresh_costume'] == fc
    ]
    n_candidates_in_bucket = len(same_bucket_candidates)
    remaining_after_cull = bucket_count - n_candidates_in_bucket

    if remaining_after_cull < 3:
        drops.append({
            'uid_hex': uid_hex,
            'species_name': cand['species_name'],
            'pid': pid, 'form': form, 'fc': fc,
            'iv_total': iv_total,
            'bucket_count': bucket_count,
            'candidates_in_bucket': n_candidates_in_bucket,
            'remaining_after_cull': remaining_after_cull,
            'reason': f'not 3+ kept after cull (bucket={bucket_count}, candidates={n_candidates_in_bucket}, remaining={remaining_after_cull})'
        })
        continue

    strict_candidates.append({
        **cand,
        'strict_meta': {
            'bucket_count': bucket_count,
            'candidates_in_bucket': n_candidates_in_bucket,
            'remaining_after_cull': remaining_after_cull,
            'gl_rank': me['gl_rank'],
            'ul_rank': me['ul_rank'],
            'll_rank': me['ll_rank']
        }
    })

print(f"Strict candidates passing: {len(strict_candidates)}")
print(f"Drops: {len(drops)}")
print()
print("=== STRICT CANDIDATES ===")
for s in strict_candidates:
    print(f"  {s['uid_hex'][:12]}... {s['species_name']:14s} pid={s['pokemon_id']} form={s['form']} fc={s['fresh_costume']} iv={s['iv_total']} shiny={s['is_shiny']} bucket={s['strict_meta']['bucket_count']} remaining={s['strict_meta']['remaining_after_cull']}")

print()
print("=== DROPS ===")
for d in drops:
    print(f"  {d['uid_hex'][:12]}... {d['species_name']:14s} pid={d['pid']} form={d['form']} fc={d['fc']} -> {d['reason']}")

reason_categories = Counter()
for d in drops:
    r = d['reason']
    if 'too high IV' in r:
        reason_categories['too_high_iv'] += 1
    elif 'bucket too small' in r:
        reason_categories['bucket_too_small'] += 1
    elif 'sole rank-1' in r:
        reason_categories['sole_rank1'] += 1
    elif 'not 3+ kept' in r:
        reason_categories['insufficient_remaining'] += 1
    else:
        reason_categories['other'] += 1

print()
print("=== DROP CATEGORIES ===")
for cat, cnt in reason_categories.most_common():
    print(f"  {cat}: {cnt}")

out = {
    'range': [251, 300],
    'orig_count': len(all_candidates),
    'strict_count': len(strict_candidates),
    'drop_count': len(drops),
    'strict_criteria': {
        'iv_total_lt': 37,
        'min_bucket_count': 4,
        'not_sole_rank1': True,
        'min_remaining_after_cull': 3
    },
    'drop_categories': dict(reason_categories),
    'strict_candidates': strict_candidates,
    'drops': drops
}

with open('agent_outputs/bucket_251_300_strict.json', 'w') as f:
    json.dump(out, f, indent=2)

print()
print("Written: agent_outputs/bucket_251_300_strict.json")

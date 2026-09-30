import json
import sqlite3
from collections import defaultdict

DB = 'pokemon.db'
IN_PATH = 'agent_outputs/bucket_901_950.json'
OUT_PATH = 'agent_outputs/bucket_901_950_strict.json'

with open(IN_PATH, 'r') as f:
    data = json.load(f)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

bucket_size = {}
bucket_ranks = defaultdict(list)
for row in cur.execute(
    """
    SELECT uid_hex, pokemon_id, form, fresh_costume, iv_total, gl_rank, ul_rank, ll_rank
    FROM pokemon
    WHERE pokemon_id BETWEEN 901 AND 950
      AND in_bag = 1
    """
):
    key = (row['pokemon_id'], row['form'] or 0, row['fresh_costume'] or 0)
    bucket_size[key] = bucket_size.get(key, 0) + 1
    best = min(
        r for r in (row['gl_rank'], row['ul_rank'], row['ll_rank'])
        if r is not None and r > 0
    ) if any(
        r is not None and r > 0 for r in (row['gl_rank'], row['ul_rank'], row['ll_rank'])
    ) else None
    bucket_ranks[key].append((row['uid_hex'], best))

rank1_uids = set()
for key, entries in bucket_ranks.items():
    valid = [(uid, r) for uid, r in entries if r is not None]
    if not valid:
        continue
    min_rank = min(r for _, r in valid)
    if min_rank == 1:
        for uid, r in valid:
            if r == 1:
                rank1_uids.add(uid)

strict_sub_buckets = []
total_strict = 0
total_input = 0

for sb in data.get('sub_buckets', []):
    in_cands = sb.get('additional_candidates', [])
    total_input += len(in_cands)
    out_cands = []
    rejected = []
    for c in in_cands:
        key = (c['pokemon_id'], c.get('form', 0) or 0, c.get('fresh_costume', 0) or 0)
        size = bucket_size.get(key, 0)
        iv_total = c.get('iv_total', 99)
        uid = c['uid_hex']
        ranks = [c.get('gl_rank'), c.get('ul_rank'), c.get('ll_rank')]
        valid_ranks = [r for r in ranks if r is not None and r > 0]
        is_rank1 = uid in rank1_uids
        only_rank1_rep = False
        if is_rank1:
            other_rank1 = [u for u in rank1_uids if u != uid]
            same_bucket_rank1 = [
                u for u in other_rank1
                if any(
                    (br_uid == u) for br_uid, _ in bucket_ranks.get(key, [])
                )
            ]
            only_rank1_rep = (len(same_bucket_rank1) == 0)

        criteria = {
            'iv_lt_37': iv_total < 37,
            'bucket_size_ge_4': size >= 4,
            'not_only_rank1_rep': not only_rank1_rep,
        }
        bucket_size_val = size
        c_out = dict(c)
        c_out['bucket_size'] = bucket_size_val
        c_out['is_rank1_in_bucket'] = is_rank1
        c_out['only_rank1_rep'] = only_rank1_rep
        c_out['strict_criteria'] = criteria
        if all(criteria.values()):
            out_cands.append(c_out)
        else:
            rejected.append({
                'uid_hex': uid,
                'species': c.get('species'),
                'form': c.get('form'),
                'fresh_costume': c.get('fresh_costume'),
                'iv_total': iv_total,
                'bucket_size': bucket_size_val,
                'is_rank1_in_bucket': is_rank1,
                'only_rank1_rep': only_rank1_rep,
                'failed': [k for k, v in criteria.items() if not v],
            })
    total_strict += len(out_cands)
    strict_sub_buckets.append({
        'range': sb.get('range'),
        'input_count': len(in_cands),
        'strict_count': len(out_cands),
        'rejected_count': len(rejected),
        'strict_candidates': out_cands,
        'rejected': rejected,
    })

paldea_starters = {906, 907, 908, 909, 910, 911, 912, 913, 914, 928, 929, 930}
paldea_count = 0
for sb in strict_sub_buckets:
    for c in sb['strict_candidates']:
        if c['pokemon_id'] in paldea_starters:
            paldea_count += 1

out = {
    'range': data.get('range'),
    'criteria': {
        'iv_total_lt_37': True,
        'bucket_size_ge_4': True,
        'not_only_rank1_representative': True,
    },
    'input_total': total_input,
    'strict_total': total_strict,
    'paldea_starter_count_in_strict': paldea_count,
    'caveats': [
        'Paldea starter lines (Sprigatito 906, Fuecoco 909, Quaxly 912 plus mid-evolutions; Smoliv 928) dominate. User may be banking these for evolution candy / future tradeable XL candy. Review before transferring.',
    ],
    'sub_buckets': strict_sub_buckets,
}

with open(OUT_PATH, 'w') as f:
    json.dump(out, f, indent=2)

print(f'Input candidates: {total_input}')
print(f'Strict candidates: {total_strict}')
print(f'Paldea starter family in strict: {paldea_count}')
print(f'Written -> {OUT_PATH}')
species_counts = defaultdict(int)
for sb in strict_sub_buckets:
    for c in sb['strict_candidates']:
        species_counts[c['species']] += 1
print('Strict by species:')
for sp, n in sorted(species_counts.items(), key=lambda x: -x[1]):
    print(f'  {sp}: {n}')

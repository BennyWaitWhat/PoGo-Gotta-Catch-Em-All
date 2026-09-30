"""Build agent_outputs/bucket_851_900.json."""
import sqlite3, json, os

DB = 'pokemon.db'
OUT = 'agent_outputs/bucket_851_900.json'

PROTECTED_PIDS = {778, 242, 664, 924, 744}  # Mimikyu, Blissey, Scatterbug, Tandemaus, Rockruff

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()


def is_protected(p):
    """Return (protected, reason) - candidates can NEVER be protected pokemon."""
    if p['is_hundo']:
        return True, 'hundo'
    if p['is_zero']:
        return True, 'nundo'
    if (p['alignment'] or 0) == 1:  # SHADOW
        return True, 'shadow'
    if (p['alignment'] or 0) == 2 or (p['is_purified_flag'] or 0):  # PURIFIED
        return True, 'purified'
    if p['is_lucky']:
        return True, 'lucky'
    if p['is_best_buddy']:
        return True, 'best_buddy'
    if p['is_deployed']:
        return True, 'deployed'
    if p['is_legendary']:
        return True, 'legendary'
    if p['is_mythical']:
        return True, 'mythical'
    if p['pokemon_id'] in PROTECTED_PIDS:
        return True, f'protected_pid_{p["pokemon_id"]}'
    if (p['costume'] or 0) != 0:
        return True, 'costume'
    if (p['fresh_pokemon_badge'] or p['display_pokemon_badge'] or 0) != 0:
        return True, 'badge'
    if (p['bread_move_count'] or p['fresh_bread_count'] or 0) != 0:
        return True, 'bread'
    if (p['has_location_card'] or p['fresh_has_location_card'] or 0) == 1:
        return True, 'location_card'
    if (p['is_strong_pokemon'] or p['fresh_is_strong'] or 0) == 1:
        return True, 'strong'
    if (p['is_mega_evolved'] or 0) == 1 or (p['has_mega_evolved_v2'] or 0) == 1:
        return True, 'mega_evolved'
    # PvP top-15
    for r_key in ('gl_rank', 'ul_rank', 'll_rank'):
        rv = p[r_key]
        if rv is not None and rv <= 15:
            return True, f'{r_key}_top15'
    # user-tagged with anything other than CLAUDE_TX/Traded
    tags = (p['auth_tag_names'] or '').strip()
    if tags:
        names = [t.strip() for t in tags.split(',') if t.strip()]
        for n in names:
            if n not in ('CLAUDE_TX', 'Traded'):
                return True, f'user_tag:{n}'
    return False, None


def build_sub_bucket(lo, hi):
    cur.execute(
        'SELECT * FROM pokemon WHERE in_bag=1 AND pokemon_id BETWEEN ? AND ?',
        (lo, hi),
    )
    rows = [dict(r) for r in cur.fetchall()]

    # group by (pokemon_id, form, fresh_costume)
    groups = {}
    for r in rows:
        key = (r['pokemon_id'], r['form'] or 0, r['fresh_costume'] or 0)
        groups.setdefault(key, []).append(r)

    species_summary = []
    additional_candidates = []
    total_keep = sum(1 for r in rows if r['cull_decision_v9'] == 'KEEP')
    total_transfer = sum(1 for r in rows if r['cull_decision_v9'] == 'TRANSFER')

    for key, members in sorted(groups.items()):
        pid, form, fcos = key
        species_name = members[0]['species_name']
        keeps = [m for m in members if m['cull_decision_v9'] == 'KEEP']
        transfers = [m for m in members if m['cull_decision_v9'] == 'TRANSFER']
        best_iv = max(m['iv_total'] or 0 for m in members)
        best_iv_pct = max(m['iv_pct'] or 0 for m in members)
        distinct_forms = sorted({m['form'] or 0 for m in members})
        distinct_fresh_forms = sorted({m['fresh_form'] or 0 for m in members})
        species_summary.append({
            'pokemon_id': pid,
            'species': species_name,
            'form': form,
            'fresh_costume': fcos,
            'count': len(members),
            'keep': len(keeps),
            'transfer': len(transfers),
            'best_iv': best_iv,
            'best_iv_pct': round(best_iv_pct, 1),
            'distinct_forms': distinct_forms,
            'distinct_fresh_forms': distinct_fresh_forms,
        })

        # additional candidates: surplus KEEPs beyond top-2 in this group, that are NOT protected
        if len(keeps) > 2:
            sorted_keeps = sorted(
                keeps,
                key=lambda r: (r['iv_total'] or 0, r['cp'] or 0, r['level'] or 0),
                reverse=True,
            )
            surplus = sorted_keeps[2:]  # rank>2
            for s in surplus:
                prot, prot_reason = is_protected(s)
                if prot:
                    continue
                additional_candidates.append({
                    'uid_hex': s['uid_hex'],
                    'pokemon_id': s['pokemon_id'],
                    'species': s['species_name'],
                    'form': s['form'] or 0,
                    'fresh_form': s['fresh_form'] or 0,
                    'fresh_costume': s['fresh_costume'] or 0,
                    'cp': s['cp'],
                    'level': s['level'],
                    'iv_total': s['iv_total'],
                    'iv_pct': round(s['iv_pct'] or 0, 1),
                    'iv_atk': s['iv_atk'],
                    'iv_def': s['iv_def'],
                    'iv_sta': s['iv_sta'],
                    'shiny': bool(s['is_shiny']),
                    'gl_rank': s['gl_rank'],
                    'ul_rank': s['ul_rank'],
                    'll_rank': s['ll_rank'],
                    'gl_pct': round(s['gl_pct'] or 0, 2),
                    'cull_decision_v9': s['cull_decision_v9'],
                    'cull_reason_v9': s['cull_reason_v9'],
                    'reason_candidate': f'surplus_in_group (rank>2 of {len(keeps)} keeps)',
                })

    return {
        'range': [lo, hi],
        'total': len(rows),
        'total_keep': total_keep,
        'total_transfer': total_transfer,
        'species': species_summary,
        'additional_candidates': additional_candidates,
        'summary': {
            'distinct_species_groups': len(groups),
            'additional_candidate_count': len(additional_candidates),
        },
    }


sub_buckets = []
for lo in range(851, 900, 10):
    hi = lo + 9
    sub_buckets.append(build_sub_bucket(lo, hi))

total = sum(sb['total'] for sb in sub_buckets)
total_keep = sum(sb['total_keep'] for sb in sub_buckets)
total_transfer = sum(sb['total_transfer'] for sb in sub_buckets)
total_candidates = sum(len(sb['additional_candidates']) for sb in sub_buckets)

# protected pids in this range
cur.execute('SELECT DISTINCT pokemon_id FROM pokemon WHERE in_bag=1 AND pokemon_id BETWEEN 851 AND 900')
pids_in_range = {r[0] for r in cur.fetchall()}
protected_pids_in_range = sorted(pids_in_range & PROTECTED_PIDS)

result = {
    'range': [851, 900],
    'sub_buckets': sub_buckets,
    'overall_notes': {
        'total_pokemon': total,
        'total_keep_v9': total_keep,
        'total_transfer_v9': total_transfer,
        'additional_transfer_candidates': total_candidates,
        'method': (
            'For each (pokemon_id, form, fresh_costume) group, sort KEEPs by '
            '(iv_total, cp, level) desc and flag any beyond top-2 as candidates '
            'unless protected (hundo/nundo/shadow/purified/lucky/best_buddy/'
            'deployed/PvP top-15/user-tagged/legendary/mythical/protected_pid/'
            'costume/badge/bread/location_card/strong/mega_evolved).'
        ),
        'protected_pids_in_range': protected_pids_in_range,
    },
}

os.makedirs('agent_outputs', exist_ok=True)
with open(OUT, 'w') as f:
    json.dump(result, f, indent=2)

print(f'WROTE {OUT}')
print(f'total={total} keep={total_keep} transfer={total_transfer} additional_candidates={total_candidates}')
for sb in sub_buckets:
    print(f"  {sb['range'][0]}-{sb['range'][1]}: total={sb['total']} keep={sb['total_keep']} transfer={sb['total_transfer']} candidates={len(sb['additional_candidates'])}")

import sqlite3, json
from collections import defaultdict

c = sqlite3.connect('pokemon.db')
c.row_factory = sqlite3.Row
cur = c.cursor()

PROTECTED_PIDS = {778, 242, 664, 924, 744}

def is_protected(p):
    if p['is_hundo']: return True, 'hundo'
    if p['is_zero']: return True, 'nundo'
    if p['alignment'] == 2: return True, 'shadow'
    if p['alignment'] == 3: return True, 'purified'
    if p['is_purified_flag']: return True, 'purified_flag'
    if p['is_lucky']: return True, 'lucky'
    if p['is_best_buddy']: return True, 'best_buddy'
    if p['is_deployed']: return True, 'deployed'
    if p['is_legendary']: return True, 'legendary'
    if p['is_mythical']: return True, 'mythical'
    if p['pokemon_id'] in PROTECTED_PIDS:
        return True, 'protected_pid_' + str(p['pokemon_id'])
    if p['gl_rank'] and p['gl_rank'] <= 15: return True, 'gl_rank_' + str(p['gl_rank'])
    if p['ul_rank'] and p['ul_rank'] <= 15: return True, 'ul_rank_' + str(p['ul_rank'])
    if p['ll_rank'] and p['ll_rank'] <= 15: return True, 'll_rank_' + str(p['ll_rank'])
    tags = p['auth_tag_names'] or ''
    if tags:
        for t in tags.split(';'):
            t = t.strip()
            if t and t not in ('CLAUDE_TX', 'Traded'):
                return True, 'user_tag:' + t
    if p['costume'] and p['costume'] != 0: return True, 'costume_' + str(p['costume'])
    if p['display_pokemon_badge'] and p['display_pokemon_badge'] != 0: return True, 'badge_' + str(p['display_pokemon_badge'])
    if p['bread_move_count'] and p['bread_move_count'] != 0: return True, 'bread_' + str(p['bread_move_count'])
    if p['has_location_card'] == 1: return True, 'location_card'
    if p['is_strong_pokemon'] == 1: return True, 'strong'
    if p['is_mega_evolved'] == 1 or p['has_mega_evolved_v2'] == 1: return True, 'mega_evolved'
    if p['is_shiny']: return True, 'shiny_de_facto'
    return False, None

sub_buckets = []
all_additional = []

for sb_idx in range(5):
    start = 601 + sb_idx * 10
    end = start + 9
    cur.execute('SELECT * FROM pokemon WHERE in_bag=1 AND pokemon_id BETWEEN ? AND ? ORDER BY pokemon_id, fresh_form, fresh_costume, iv_total DESC', (start, end))
    rows = [dict(r) for r in cur.fetchall()]

    groups = defaultdict(list)
    for p in rows:
        key = (p['pokemon_id'], p['species_name'], p['fresh_form'] if p['fresh_form'] is not None else p['form'], p['fresh_costume'] if p['fresh_costume'] is not None else p['costume'])
        groups[key].append(p)

    species_summaries = []
    additional_candidates = []

    for key, members in sorted(groups.items()):
        pid, name, form, costume = key
        members_sorted = sorted(members, key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        best_iv = members_sorted[0]['iv_total'] if members_sorted else 0
        best_iv_pct = members_sorted[0]['iv_pct'] if members_sorted else 0
        distinct_forms_in_pid = len(set(((p['fresh_form'] if p['fresh_form'] is not None else p['form']), (p['fresh_costume'] if p['fresh_costume'] is not None else p['costume'])) for p in rows if p['pokemon_id'] == pid))
        keep_n = sum(1 for p in members if p['cull_decision_v9'] == 'KEEP')
        xfer_n = sum(1 for p in members if p['cull_decision_v9'] == 'TRANSFER')

        species_summaries.append({
            'pokemon_id': pid,
            'species_name': name,
            'form': form,
            'fresh_costume': costume,
            'count': len(members),
            'best_iv': best_iv,
            'best_iv_pct': round(best_iv_pct or 0, 2),
            'distinct_forms_in_pid': distinct_forms_in_pid,
            'keep': keep_n,
            'transfer': xfer_n,
        })

        keepers = [p for p in members if p['cull_decision_v9'] == 'KEEP']
        if len(keepers) <= 1:
            continue
        keepers_sorted = sorted(keepers, key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0), -((x['level'] or 0))))
        for p in keepers_sorted[1:]:
            protected, reason = is_protected(p)
            if protected:
                continue
            additional_candidates.append({
                'uid_hex': p['uid_hex'],
                'pokemon_id': p['pokemon_id'],
                'species_name': p['species_name'],
                'form': p['fresh_form'] if p['fresh_form'] is not None else p['form'],
                'fresh_costume': p['fresh_costume'] if p['fresh_costume'] is not None else p['costume'],
                'cp': p['cp'],
                'iv_total': p['iv_total'],
                'iv_pct': round(p['iv_pct'] or 0, 2),
                'iv_atk': p['iv_atk'], 'iv_def': p['iv_def'], 'iv_sta': p['iv_sta'],
                'level': p['level'],
                'is_shiny': p['is_shiny'],
                'gl_rank': p['gl_rank'],
                'ul_rank': p['ul_rank'],
                'll_rank': p['ll_rank'],
                'auth_tag_names': p['auth_tag_names'],
                'reason': 'surplus_in_bucket; best_iv_in_bucket=' + str(best_iv) + ' this_iv=' + str(p['iv_total']) + '; bucket_size=' + str(len(members)),
                'current_cull_v9': p['cull_decision_v9'],
                'cull_reason_v9': p['cull_reason_v9'],
            })

    keep_total = sum(s['keep'] for s in species_summaries)
    xfer_total = sum(s['transfer'] for s in species_summaries)

    sub_buckets.append({
        'range': str(start) + '-' + str(end),
        'summary': {
            'total': len(rows),
            'keep': keep_total,
            'transfer': xfer_total,
            'additional_candidates_count': len(additional_candidates),
        },
        'species': species_summaries,
        'additional_candidates': additional_candidates,
    })
    all_additional.extend(additional_candidates)

result = {
    'range': '601-650',
    'sub_buckets': sub_buckets,
    'overall_notes': {
        'total_pokemon': sum(sb['summary']['total'] for sb in sub_buckets),
        'cull_v9_keep': sum(sb['summary']['keep'] for sb in sub_buckets),
        'cull_v9_transfer': sum(sb['summary']['transfer'] for sb in sub_buckets),
        'additional_transfer_candidates': len(all_additional),
        'protected_categories_excluded': ['hundo', 'nundo', 'shadow', 'purified', 'lucky', 'best_buddy', 'deployed', 'GL/UL/LL_top_15', 'user_tags(non-CLAUDE_TX/Traded)', 'legendary', 'mythical', 'pid in {778,242,664,924,744}', 'costume!=0', 'badge!=0', 'bread!=0', 'location_card=1', 'strong=1', 'mega_evolved', 'shiny_de_facto'],
        'protection_methodology': 'For each (species, form, fresh_costume) bucket: keep top-1 by iv_total; treat lower-IV KEEPers as candidates only if all protection flags are clear. Shiny added as de-facto protection (cull_v9 has never transferred a shiny: 1051/1051 KEEP). ultra_beast/paradox not present in 601-650 gen-5 range.',
    }
}

with open('agent_outputs/bucket_601_650.json', 'w') as f:
    json.dump(result, f, indent=2)

print('TOTAL:', result['overall_notes']['total_pokemon'])
print('V9 KEEP:', result['overall_notes']['cull_v9_keep'])
print('V9 TRANSFER:', result['overall_notes']['cull_v9_transfer'])
print('ADDITIONAL CANDIDATES:', result['overall_notes']['additional_transfer_candidates'])
for sb in sub_buckets:
    print('  ' + sb['range'] + ': total=' + str(sb['summary']['total']) + ' keep=' + str(sb['summary']['keep']) + ' xfer=' + str(sb['summary']['transfer']) + ' addl=' + str(sb['summary']['additional_candidates_count']))

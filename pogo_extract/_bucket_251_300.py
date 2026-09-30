import sqlite3, json, os

con = sqlite3.connect('pokemon.db')
con.row_factory = sqlite3.Row
cur = con.cursor()

PROTECTED_PIDS = {778, 242, 664, 924, 744}
ALLOWED_USER_TAGS = {'CLAUDE_TX', 'Traded'}


def is_protected(r):
    reasons = []
    if r['is_hundo']:
        reasons.append('hundo')
    if r['is_zero']:
        reasons.append('nundo')
    if r['iv_total'] is not None and r['iv_total'] == 0 and 'nundo' not in reasons:
        reasons.append('nundo')
    if r['alignment'] == 2 or r['fresh_alignment'] == 2:
        reasons.append('shadow')
    if r['alignment'] == 3 or r['fresh_alignment'] == 3 or r['is_purified_flag'] == 1:
        reasons.append('purified')
    if r['is_lucky']:
        reasons.append('lucky')
    if r['is_best_buddy']:
        reasons.append('best_buddy')
    if r['is_deployed']:
        reasons.append('deployed')
    if r['is_legendary']:
        reasons.append('legendary')
    if r['is_mythical']:
        reasons.append('mythical')
    for stage, rnk in (('GL', r['gl_rank']), ('UL', r['ul_rank']), ('LL', r['ll_rank'])):
        if rnk is not None and rnk <= 15:
            reasons.append(f'{stage}_top15(rank={rnk})')
    tags = r['auth_tag_names']
    if tags:
        tag_set = {t.strip() for t in tags.split(';') if t.strip()}
        user_tags = tag_set - ALLOWED_USER_TAGS
        if user_tags:
            reasons.append('user_tag:' + ','.join(sorted(user_tags)))
    if r['pokemon_id'] in PROTECTED_PIDS:
        reasons.append(f'protected_pid({r["pokemon_id"]})')
    costume = r['costume'] or 0
    fresh_costume = r['fresh_costume'] or 0
    if costume != 0 or fresh_costume != 0:
        reasons.append(f'costume({costume}/{fresh_costume})')
    badge = r['display_pokemon_badge'] or 0
    fresh_badge = r['fresh_pokemon_badge'] or 0
    if badge != 0 or fresh_badge != 0:
        reasons.append(f'badge({badge}/{fresh_badge})')
    bread = r['bread_move_count'] or 0
    bread_mode = r['bread_mode'] or 0
    fresh_bm = r['fresh_bread_mode'] or 0
    if bread != 0 or bread_mode != 0 or fresh_bm != 0:
        reasons.append(f'bread({bread},mode={bread_mode}/{fresh_bm})')
    if r['has_location_card'] == 1 or r['fresh_has_location_card'] == 1:
        reasons.append('location_card')
    if r['is_strong_pokemon'] == 1 or r['fresh_is_strong'] == 1:
        reasons.append('strong')
    if r['is_mega_evolved'] == 1:
        reasons.append('mega_evolved')
    return (len(reasons) > 0, reasons)


def fmt_pkmn(r):
    return {
        'uid_hex': r['uid_hex'],
        'species_name': r['species_name'],
        'pokemon_id': r['pokemon_id'],
        'form': r['form'],
        'fresh_costume': r['fresh_costume'],
        'cp': r['cp'],
        'iv_pct': r['iv_pct'],
        'iv_total': r['iv_total'],
        'level': r['level'],
        'is_shiny': r['is_shiny'],
        'gl_rank': r['gl_rank'],
        'ul_rank': r['ul_rank'],
        'll_rank': r['ll_rank'],
        'auth_tag_names': r['auth_tag_names'],
        'cull_decision_v9': r['cull_decision_v9'],
        'cull_reason_v9': r['cull_reason_v9'],
    }


sub_bucket_ranges = [(251, 260), (261, 270), (271, 280), (281, 290), (291, 300)]
sub_buckets = []
overall_additional_count = 0
overall_total = 0

for start, end in sub_bucket_ranges:
    rows = cur.execute(
        "SELECT * FROM pokemon WHERE in_bag=1 AND pokemon_id BETWEEN ? AND ? "
        "ORDER BY pokemon_id, form, fresh_costume, iv_total DESC",
        (start, end)
    ).fetchall()
    overall_total += len(rows)
    species_groups = {}
    for r in rows:
        key = (r['pokemon_id'], r['species_name'], r['form'] or 0, r['fresh_costume'] or 0)
        species_groups.setdefault(key, []).append(r)

    species_out = []
    additional = []
    for key, grp in sorted(species_groups.items()):
        pid, sp, form, fc = key
        keeps = [g for g in grp if g['cull_decision_v9'] == 'KEEP']
        transfers = [g for g in grp if g['cull_decision_v9'] == 'TRANSFER']
        best_iv = max((g['iv_pct'] or 0) for g in grp)
        species_out.append({
            'pokemon_id': pid,
            'species_name': sp,
            'form': form,
            'fresh_costume': fc,
            'count': len(grp),
            'keep_count': len(keeps),
            'transfer_count': len(transfers),
            'best_iv_pct': round(best_iv, 2),
            'distinct_forms_in_pid': len({(g['form'] or 0) for g in grp}),
        })

        keep_sorted = sorted(
            keeps,
            key=lambda g: (
                int(g['is_shiny'] or 0),
                g['iv_total'] or 0,
                g['cp'] or 0,
            ),
            reverse=True
        )
        kept_slots = 1
        slot_used = 0
        for g in keep_sorted:
            protected, prot_reasons = is_protected(g)
            if protected:
                continue
            if slot_used < kept_slots:
                slot_used += 1
                continue
            entry = fmt_pkmn(g)
            entry['surplus_reason'] = (
                f"surplus in ({sp}, form={form}, fresh_costume={fc}); "
                f"already keeping {kept_slots} non-protected; this is non-protected #{slot_used+1}"
            )
            additional.append(entry)

    overall_additional_count += len(additional)
    sub_buckets.append({
        'range': [start, end],
        'summary': {
            'total': len(rows),
            'keep': sum(1 for r in rows if r['cull_decision_v9'] == 'KEEP'),
            'transfer': sum(1 for r in rows if r['cull_decision_v9'] == 'TRANSFER'),
            'distinct_species_groups': len(species_groups),
            'additional_candidate_count': len(additional),
        },
        'species': species_out,
        'additional_candidates': additional,
    })

# Overall notes
notes = []
notes.append("Range 251-300 contains no legendary/ultra_beast/paradox protected species; Celebi (251) is mythical and auto-protected.")
notes.append("None of the never-cull-pids (242 Blissey, 664 Scatterbug, 744 Rockruff, 778 Mimikyu, 924 Tandemaus) fall in this range.")
notes.append("Surplus rule: per (species, form, fresh_costume) bucket, keep top-1 non-protected by (shiny, iv_total, cp); the rest are surplus candidates IF they themselves do not match any protection criterion.")
notes.append("All protection flags from instructions enforced: hundo, nundo (is_zero or iv_total==0), shadow (alignment=2), purified (alignment=3 or is_purified_flag=1), lucky, best_buddy, deployed, GL/UL/LL top-15, user tag (anything not CLAUDE_TX/Traded), legendary, mythical, costume!=0, badge!=0, bread (count or mode), location_card, strong, mega_evolved.")

output = {
    'range': [251, 300],
    'overall_total': overall_total,
    'overall_additional_candidate_count': overall_additional_count,
    'sub_buckets': sub_buckets,
    'overall_notes': notes,
}

os.makedirs('agent_outputs', exist_ok=True)
out_path = 'agent_outputs/bucket_251_300.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, default=str)

print('OVERALL TOTAL:', overall_total)
print('ADDITIONAL CANDIDATES:', overall_additional_count)
for sb in sub_buckets:
    print(sb['range'], sb['summary'])
print('written', out_path)

"""V5: V4 rules + new shiny-specific rules (top 5 per bucket + 3+star, chain-protected)."""
import sqlite3, csv
from references import (
    LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS,
    ADVENTURE_EFFECT_IDS, has_legacy_move,
)

PROTECTED_SHINY_PIDS = {
    129, 130,                                     # Magikarp/Gyarados
    133, 134, 135, 136, 196, 197, 470, 471, 700,  # Eevee chain
    172, 25, 26,                                  # Pikachu chain
    669, 670, 671,                                # Flabebe chain
    384, 888,                                     # Rayquaza, Zacian
}
PVP_RANK_KEEP = 20
SHINY_TOP_N = 5

def star(t): return 4 if t >= 45 else 3 if t >= 37 else 2 if t >= 30 else 1 if t >= 23 else 0

def base_untouchable(p, xxl_top3_uids):
    rs = []
    if p['is_hundo']: rs.append('hundo')
    if p['is_zero']: rs.append('nundo')
    if p['is_lucky']: rs.append('lucky')
    if p['is_best_buddy']: rs.append('best_buddy')
    if p['is_deployed']: rs.append('deployed_in_gym')
    if (p['fresh_alignment'] or 0) == 1: rs.append('shadow')
    elif (p['fresh_alignment'] or 0) == 2: rs.append('purified')
    if (p['is_traded_flag_v2'] or 0) == 1: rs.append('traded')
    auth = p['auth_tag_names'] or ''
    user_tags = [t for t in auth.split(';') if t and t != 'CLAUDE_TX']
    if user_tags: rs.append(f"user_tag_{user_tags[0]}")
    if (p['fresh_bread_mode'] or 0) != 0: rs.append(f"bread_{p['fresh_bread_mode']}")
    if (p['fresh_has_location_card'] or 0) == 1: rs.append('location_card')
    if (p['fresh_costume'] or 0) != 0: rs.append(f"costume_{p['fresh_costume']}")
    if (p['fresh_is_strong'] or 0) == 1: rs.append('is_strong')
    if (p['fresh_pokemon_badge'] or 0) != 0: rs.append('adventure_effect')
    if (p['fresh_current_temp_evolution'] or 0) != 0: rs.append('current_mega_evolved')
    if (p['fresh_has_mega_level'] or 0) == 1: rs.append('has_mega_level')
    if p['gl_rank'] and p['gl_rank'] <= PVP_RANK_KEEP: rs.append(f"gl_top{p['gl_rank']}")
    if p['ul_rank'] and p['ul_rank'] <= PVP_RANK_KEEP: rs.append(f"ul_top{p['ul_rank']}")
    if p['ll_rank'] and p['ll_rank'] <= PVP_RANK_KEEP: rs.append(f"ll_top{p['ll_rank']}")
    if p['uid_hex'] in xxl_top3_uids: rs.append('xxl_top3_heaviest')
    pid = p['pokemon_id']
    if pid in LEGENDARY_IDS: rs.append('legendary')
    if pid in MYTHICAL_IDS: rs.append('mythical')
    if pid in ULTRA_BEAST_IDS: rs.append('ultra_beast')
    if pid in PARADOX_IDS: rs.append('paradox')
    if pid in ADVENTURE_EFFECT_IDS: rs.append('adventure_effect_species')
    if has_legacy_move(pid, [p['move1'], p['move2'], p['move3']]): rs.append('legacy_move')
    return rs

def main():
    conn = sqlite3.connect('pokemon.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    cols = {r[1] for r in c.execute('PRAGMA table_info(pokemon)').fetchall()}
    if 'cull_decision_v5' not in cols: c.execute('ALTER TABLE pokemon ADD COLUMN cull_decision_v5 TEXT')
    if 'cull_reason_v5' not in cols: c.execute('ALTER TABLE pokemon ADD COLUMN cull_reason_v5 TEXT')
    conn.commit()

    rows = [dict(r) for r in c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()]
    print(f"Loaded {len(rows)}")

    # XXL top-3-heaviest
    xxl_groups = {}
    for p in rows:
        if (p['pokemon_size_category'] or 0) == 5:
            key = (p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)
            xxl_groups.setdefault(key, []).append(p)
    xxl_top3_uids = set()
    for key, lst in xxl_groups.items():
        lst.sort(key=lambda x: -(x['weight_kg'] or 0))
        for p in lst[:3]: xxl_top3_uids.add(p['uid_hex'])

    keep_reasons = {}
    for p in rows:
        for r in base_untouchable(p, xxl_top3_uids):
            keep_reasons.setdefault(p['uid_hex'], []).append(r)

    # === SHINY-specific rules ===
    # Protected chains: ALL shinies in those chains kept
    for p in rows:
        if p['fresh_shiny'] and p['pokemon_id'] in PROTECTED_SHINY_PIDS:
            keep_reasons.setdefault(p['uid_hex'], []).append('shiny_protected_chain')

    # Other shinies: per (species, form, costume) bucket, top N + all 3+star
    shiny_buckets = {}
    for p in rows:
        if p['fresh_shiny'] and p['pokemon_id'] not in PROTECTED_SHINY_PIDS:
            key = (p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)
            shiny_buckets.setdefault(key, []).append(p)
    for key, lst in shiny_buckets.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst):
            s = star(p['iv_total'] or 0)
            if i < SHINY_TOP_N:
                keep_reasons.setdefault(p['uid_hex'], []).append(f'shiny_top{SHINY_TOP_N}_rank{i+1}')
            elif s >= 3:
                keep_reasons.setdefault(p['uid_hex'], []).append(f'shiny_3star+_rank{i+1}')

    # === Non-shiny: top 3 per (species, form, costume) bucket by IV ===
    by_bucket = {}
    for p in rows:
        if not p['fresh_shiny']:
            key = (p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)
            by_bucket.setdefault(key, []).append(p)
    for key, lst in by_bucket.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst[:3]):
            keep_reasons.setdefault(p['uid_hex'], []).append(f'top3_iv_rank{i+1}')

    keep_count = xfer_count = 0
    for p in rows:
        uid = p['uid_hex']
        reasons = keep_reasons.get(uid, [])
        if reasons:
            decision = 'KEEP'; reason_str = ';'.join(reasons[:8])
            keep_count += 1
        else:
            decision = 'TRANSFER'; reason_str = 'no_keep_rule'
            xfer_count += 1
        c.execute('UPDATE pokemon SET cull_decision_v5=?, cull_reason_v5=? WHERE uid_hex=?',
                  (decision, reason_str, uid))
    conn.commit()
    print(f'\nKEEP: {keep_count}  TRANSFER: {xfer_count}')

    # Sanity: count violations in transfer list
    print('\n=== Sanity check on transfer list (these should all be 0) ===')
    queries = [
        ('hundo', 'is_hundo=1'),
        ('nundo', 'is_zero=1'),
        ('shadow', 'fresh_alignment=1'),
        ('purified', 'fresh_alignment=2'),
        ('gmax/dmax', 'fresh_bread_mode != 0'),
        ('lucky', 'is_lucky=1'),
        ('traded', 'is_traded_flag_v2=1'),
        ('costume', 'fresh_costume != 0'),
        ('loc_card', 'fresh_has_location_card=1'),
        ('badge', 'fresh_pokemon_badge != 0'),
        ('strong', 'fresh_is_strong=1'),
        ('GL top 20', 'gl_rank<=20'),
        ('UL top 20', 'ul_rank<=20'),
        ('LL top 20', 'll_rank<=20'),
        ('shiny in protected chain', f"fresh_shiny=1 AND pokemon_id IN ({','.join(str(p) for p in PROTECTED_SHINY_PIDS)})"),
        ('user-tagged (not CLAUDE_TX)', "auth_tag_names != '' AND auth_tag_names != 'CLAUDE_TX' AND auth_tag_names IS NOT NULL"),
    ]
    for label, where in queries:
        n = c.execute(f"SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND cull_decision_v5='TRANSFER' AND {where}").fetchone()[0]
        marker = '!' if n > 0 else ' '
        print(f'  {marker} {label:30s}: {n}')

    print('\n=== Top transfer species ===')
    for r in c.execute("""SELECT species_name, COUNT(*) as n FROM pokemon
                          WHERE cull_decision_v5='TRANSFER' AND in_bag=1
                          GROUP BY species_name ORDER BY n DESC LIMIT 25"""):
        print(f'  {r[0]:25s} {r[1]}')

if __name__ == '__main__':
    main()

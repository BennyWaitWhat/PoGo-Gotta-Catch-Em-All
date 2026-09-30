"""V4 cull with PvP top-20 exclusion."""
import sqlite3, csv
from references import (
    LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS,
    ADVENTURE_EFFECT_IDS, has_legacy_move,
)

LEGENDARY_KANTO = {144, 145, 146, 150, 151}
PVP_RANK_KEEP = 20

def untouchable_reasons(p, xxl_top3_uids):
    rs = []
    if p['is_hundo']: rs.append("hundo")
    if p['is_zero']: rs.append("nundo")
    if p['is_lucky']: rs.append("lucky")
    if p['is_best_buddy']: rs.append("best_buddy")
    if p['is_deployed']: rs.append("deployed_in_gym")
    if (p['fresh_alignment'] or 0) == 1: rs.append("shadow")
    elif (p['fresh_alignment'] or 0) == 2: rs.append("purified")
    if (p['is_traded_flag_v2'] or 0) == 1: rs.append("traded")
    auth = p['auth_tag_names'] or ''
    user_tags = [t for t in auth.split(';') if t and t not in ('CLAUDE_TX',)]
    if user_tags: rs.append(f"user_tag_{user_tags[0]}")
    if (p['fresh_bread_mode'] or 0) != 0: rs.append(f"bread_{p['fresh_bread_mode']}")
    if (p['fresh_has_location_card'] or 0) == 1: rs.append("location_card")
    if (p['fresh_costume'] or 0) != 0: rs.append(f"display_costume_{p['fresh_costume']}")
    if (p['fresh_is_strong'] or 0) == 1: rs.append("is_strong")
    if (p['fresh_pokemon_badge'] or 0) != 0: rs.append("adventure_effect")
    if (p['fresh_current_temp_evolution'] or 0) != 0: rs.append("current_mega_evolved")
    if (p['fresh_has_mega_level'] or 0) == 1: rs.append("has_mega_level")
    # PvP top 20 - any league - any chain stage
    if p['gl_rank'] and p['gl_rank'] <= PVP_RANK_KEEP: rs.append(f"gl_top{p['gl_rank']}")
    if p['ul_rank'] and p['ul_rank'] <= PVP_RANK_KEEP: rs.append(f"ul_top{p['ul_rank']}")
    if p['ll_rank'] and p['ll_rank'] <= PVP_RANK_KEEP: rs.append(f"ll_top{p['ll_rank']}")
    # XXL top 3 heaviest
    if p['uid_hex'] in xxl_top3_uids: rs.append("xxl_top3_heaviest")
    pid = p['pokemon_id']
    if pid in LEGENDARY_IDS: rs.append("legendary")
    if pid in MYTHICAL_IDS: rs.append("mythical")
    if pid in ULTRA_BEAST_IDS: rs.append("ultra_beast")
    if pid in PARADOX_IDS: rs.append("paradox")
    if pid in ADVENTURE_EFFECT_IDS: rs.append("adventure_effect_species")
    if has_legacy_move(pid, [p['move1'], p['move2'], p['move3']]): rs.append("legacy_move")
    return rs

def main():
    conn = sqlite3.connect('pokemon.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    cols = {r[1] for r in c.execute("PRAGMA table_info(pokemon)").fetchall()}
    if 'cull_decision_v4' not in cols: c.execute("ALTER TABLE pokemon ADD COLUMN cull_decision_v4 TEXT")
    if 'cull_reason_v4' not in cols: c.execute("ALTER TABLE pokemon ADD COLUMN cull_reason_v4 TEXT")
    conn.commit()

    rows = [dict(r) for r in c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()]
    print(f"Loaded {len(rows)} pokemon (in_bag=1)")

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
        for r in untouchable_reasons(p, xxl_top3_uids):
            keep_reasons.setdefault(p['uid_hex'], []).append(r)

    # Top 10 shinies/species
    by_species_shiny = {}
    for p in rows:
        if p['fresh_shiny']:
            by_species_shiny.setdefault(p['pokemon_id'], []).append(p)
    for pid, lst in by_species_shiny.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst[:10]):
            keep_reasons.setdefault(p['uid_hex'], []).append(f"shiny_top10_rank{i+1}")

    # Top 3 per (species, form, costume) by IV
    by_bucket = {}
    for p in rows:
        key = (p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)
        by_bucket.setdefault(key, []).append(p)
    for key, lst in by_bucket.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst[:3]):
            keep_reasons.setdefault(p['uid_hex'], []).append(f"top3_iv_rank{i+1}")

    keep_count = xfer_count = 0
    for p in rows:
        uid = p['uid_hex']
        reasons = keep_reasons.get(uid, [])
        if reasons:
            decision = "KEEP"; reason_str = ";".join(reasons[:8])
            keep_count += 1
        else:
            decision = "TRANSFER"; reason_str = "no_keep_rule"
            xfer_count += 1
        c.execute("UPDATE pokemon SET cull_decision_v4=?, cull_reason_v4=? WHERE uid_hex=?",
                  (decision, reason_str, uid))
    conn.commit()
    print(f"\n=== V4 ===")
    print(f"  KEEP: {keep_count}  TRANSFER: {xfer_count}")
    print()
    print("=== Top transfer species ===")
    for r in c.execute("""SELECT species_name, COUNT(*) as n FROM pokemon
                          WHERE cull_decision_v4='TRANSFER' AND in_bag=1
                          GROUP BY species_name ORDER BY n DESC LIMIT 20"""):
        print(f"  {r[0]:25s} {r[1]}")

if __name__ == '__main__':
    main()

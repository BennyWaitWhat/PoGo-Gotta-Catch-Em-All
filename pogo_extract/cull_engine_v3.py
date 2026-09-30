"""V3 cull engine: v2 rules + revised XXL rule + dropped XXS/XL/user-tag protection.

Changes from v2:
  - XXL rule: per (species, form, costume) bucket, keep top 3 heaviest XXL pokemon.
    XXL pokemon outside top 3 weight are NOT protected by size.
  - XXS no longer untouchable (dropped).
  - XL no longer untouchable (dropped).
  - User-tag protection dropped entirely (most user tags deleted; rely on hard fields).

Untouchables (any one => keep):
  - Hundo / Nundo / Lucky / Best Buddy
  - Shadow / Purified / Powered up (numUpgrades > 0) / Traded
  - Mega-evolved (current_temp_evolution OR has_mega_level)
  - DMAX/GMAX (bread_mode != 0)
  - LocationCard (has_location_card=1)
  - Costume (display_costume != 0)
  - Adventure Effect (PokemonBadge != 0)
  - IsStrongPokemon
  - XXL top 3 heaviest in bucket
  - Legendary / Mythical / UB / Paradox / Adventure-Effect species
  - Legacy moves

Caps/universals:
  - Top 10 shinies/species (by IV)
  - Top 3 per (species, form, costume) bucket by IV
"""
import sqlite3, csv
from references import (
    LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS,
    ADVENTURE_EFFECT_IDS, has_legacy_move,
)

DB = 'pokemon.db'

def untouchable_reasons(p, xxl_top3_uids):
    rs = []
    if p['is_hundo']:                            rs.append("hundo")
    if p['is_zero']:                             rs.append("nundo")
    if p['is_lucky']:                            rs.append("lucky")
    if p['is_best_buddy']:                       rs.append("best_buddy")
    if p['is_deployed']:                         rs.append("deployed_in_gym")
    if (p['fresh_alignment'] or 0) == 1:         rs.append("shadow")
    elif (p['fresh_alignment'] or 0) == 2:       rs.append("purified")
    if (p['is_traded_flag_v2'] or 0) == 1:       rs.append("traded")
    # User tags from authoritative binding service (excludes CLAUDE_TX)
    auth = p['auth_tag_names'] or ''
    user_tags = [t for t in auth.split(';') if t and t != 'CLAUDE_TX']
    if user_tags:                                rs.append(f"user_tag_{user_tags[0]}")

    if (p['fresh_bread_mode'] or 0) != 0:        rs.append(f"bread_{p['fresh_bread_mode']}")
    if (p['fresh_has_location_card'] or 0) == 1: rs.append("location_card")
    if (p['fresh_costume'] or 0) != 0:           rs.append(f"display_costume_{p['fresh_costume']}")
    if (p['fresh_is_strong'] or 0) == 1:         rs.append("is_strong")
    if (p['fresh_pokemon_badge'] or 0) != 0:     rs.append("adventure_effect")
    if (p['fresh_current_temp_evolution'] or 0) != 0: rs.append("current_mega_evolved")
    if (p['fresh_has_mega_level'] or 0) == 1:    rs.append("has_mega_level")

    # XXL top 3 heaviest in bucket
    if p['uid_hex'] in xxl_top3_uids:            rs.append("xxl_top3_heaviest")

    pid = p['pokemon_id']
    if pid in LEGENDARY_IDS:                     rs.append("legendary")
    if pid in MYTHICAL_IDS:                      rs.append("mythical")
    if pid in ULTRA_BEAST_IDS:                   rs.append("ultra_beast")
    if pid in PARADOX_IDS:                       rs.append("paradox")
    if pid in ADVENTURE_EFFECT_IDS:              rs.append("adventure_effect_species")
    if has_legacy_move(pid, [p['move1'], p['move2'], p['move3']]):
        rs.append("legacy_move")

    return rs

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    cols = {r[1] for r in c.execute("PRAGMA table_info(pokemon)").fetchall()}
    if 'cull_decision_v3' not in cols:
        c.execute("ALTER TABLE pokemon ADD COLUMN cull_decision_v3 TEXT")
    if 'cull_reason_v3' not in cols:
        c.execute("ALTER TABLE pokemon ADD COLUMN cull_reason_v3 TEXT")
    conn.commit()

    rows = [dict(r) for r in c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()]
    print(f"Loaded {len(rows)} pokemon (in_bag=1)")

    # Build XXL top-3-heaviest set per (species, form, costume)
    xxl_groups = {}
    for p in rows:
        if (p['pokemon_size_category'] or 0) == 5:
            key = (p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)
            xxl_groups.setdefault(key, []).append(p)
    xxl_top3_uids = set()
    for key, lst in xxl_groups.items():
        lst.sort(key=lambda x: -(x['weight_kg'] or 0))
        for p in lst[:3]:
            xxl_top3_uids.add(p['uid_hex'])
    print(f"XXL pokemon: {sum(len(v) for v in xxl_groups.values())} in {len(xxl_groups)} species buckets")
    print(f"  XXL top-3-heaviest protected: {len(xxl_top3_uids)}")

    keep_reasons = {}
    def add_reason(uid, reason):
        keep_reasons.setdefault(uid, []).append(reason)

    for p in rows:
        for r in untouchable_reasons(p, xxl_top3_uids):
            add_reason(p['uid_hex'], r)

    # Top 10 shinies/species (by IV)
    by_species_shiny = {}
    for p in rows:
        if p['fresh_shiny']:
            by_species_shiny.setdefault(p['pokemon_id'], []).append(p)
    for pid, lst in by_species_shiny.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst[:10]):
            add_reason(p['uid_hex'], f"shiny_top10_rank{i+1}")

    # Top 3 per (species, form, costume) by IV
    by_bucket = {}
    for p in rows:
        key = (p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)
        by_bucket.setdefault(key, []).append(p)
    for key, lst in by_bucket.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst[:3]):
            add_reason(p['uid_hex'], f"top3_iv_rank{i+1}")

    keep_count = 0; xfer_count = 0
    for p in rows:
        uid = p['uid_hex']
        reasons = keep_reasons.get(uid, [])
        if reasons:
            decision = "KEEP"
            reason_str = ";".join(reasons[:8])
            keep_count += 1
        else:
            decision = "TRANSFER"
            reason_str = "no_keep_rule"
            xfer_count += 1
        c.execute("UPDATE pokemon SET cull_decision_v3=?, cull_reason_v3=? WHERE uid_hex=?",
                  (decision, reason_str, uid))
    conn.commit()

    print(f"\n=== V3 ({len(rows)} pokemon in bag) ===")
    print(f"  KEEP:     {keep_count} ({keep_count/len(rows)*100:.1f}%)")
    print(f"  TRANSFER: {xfer_count} ({xfer_count/len(rows)*100:.1f}%)")

    print(f"\n=== Top transfer species ===")
    for row in c.execute("""SELECT species_name, COUNT(*) as n FROM pokemon
                            WHERE cull_decision_v3='TRANSFER' AND in_bag=1
                            GROUP BY species_name ORDER BY n DESC LIMIT 25"""):
        print(f"  {row[0]:25s} {row[1]}")

    print(f"\n=== Top keep reasons ===")
    reason_counts = {}
    for r in c.execute("SELECT cull_reason_v3 FROM pokemon WHERE cull_decision_v3='KEEP' AND in_bag=1").fetchall():
        for tok in r[0].split(";"):
            reason_counts[tok] = reason_counts.get(tok, 0) + 1
    for tok, n in sorted(reason_counts.items(), key=lambda x: -x[1])[:25]:
        print(f"  {n:5d}  {tok}")

    print("\nExporting cull_plan_v3.csv...")
    with open('cull_plan_v3.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['uid_hex','pokemon_id','species_name','form','fresh_costume','cp',
                    'iv_pct','iv_total','iv_atk','iv_def','iv_sta','weight_kg',
                    'pokemon_size_category','is_shiny','is_lucky','is_traded',
                    'level','nickname','cull_decision_v3','cull_reason_v3'])
        for r in c.execute("""SELECT uid_hex,pokemon_id,species_name,form,fresh_costume,cp,
                                     iv_pct,iv_total,iv_atk,iv_def,iv_sta,weight_kg,
                                     pokemon_size_category,is_shiny,is_lucky,is_traded,
                                     level,nickname,cull_decision_v3,cull_reason_v3
                              FROM pokemon WHERE in_bag=1
                              ORDER BY species_name, form, fresh_costume, cull_decision_v3, iv_pct DESC"""):
            w.writerow(r)
    print("  cull_plan_v3.csv written")

    conn.close()

if __name__ == '__main__':
    main()

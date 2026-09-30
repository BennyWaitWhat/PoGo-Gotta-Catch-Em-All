"""V2 cull engine using fresh proto data + all newly-discovered untouchable rules.

UNTOUCHABLES (any one => keep):
  Existing v1:
    - hundo / nundo
    - is_lucky
    - is_best_buddy (added_friendship_score >= 200000)
    - is_deployed (in_gym)
    - alignment != 0 (shadow OR purified)
    - is_powered_up
    - is_traded_flag_v2 / is_traded
    - is_mega_evolved (legacy flag)
    - special_bg_id, location_bg_id, adventure_effects_left (legacy fields)
    - costume_decoration_id
    - pokemon_size_category in (1, 5)  - XXS/XL/XXL
    - legendary/mythical/UB/paradox species
    - legacy moves
    - adventure_effect_species

  V2 NEW (from fresh proto poll):
    - fresh_bread_mode != 0       (DMAX/GMAX - 308 pokemon)
    - fresh_has_location_card = 1 (location bg + special bg - 104 pokemon)
    - fresh_costume != 0          (PokemonDisplayProto.Costume - 161 pokemon)
    - fresh_is_strong = 1         (IsStrongPokemon)
    - fresh_pokemon_badge != 0    (Adventure Effect badge - 17 pokemon)
    - fresh_current_temp_evolution != 0 (currently mega-evolved - 156)
    - fresh_has_mega_level = 1    (has MegaEvolutionLevel sub-message - 156)
    - fresh_tag_count > 0 AND fresh_tag_ids has non-CLAUDE_TX tag (user-tagged)

CAPS:
  - top 10 shinies/species (by IV%)
  - top 2 shadows/species (subsumed by alignment-untouchable)

UNIVERSAL:
  - top 3 per (species, form, costume) bucket by IV%
"""
import sqlite3, csv
from references import (
    LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS,
    ADVENTURE_EFFECT_IDS, has_legacy_move,
)

DB = 'pokemon.db'
CLAUDE_TX = '15974071496501899036'

def untouchable_reasons(p):
    rs = []
    # Existing v1 rules
    if p['is_hundo']:                            rs.append("hundo")
    if p['is_zero']:                             rs.append("nundo")
    if p['is_lucky']:                            rs.append("lucky")
    if p['is_best_buddy']:                       rs.append("best_buddy")
    if p['is_deployed']:                         rs.append("deployed_in_gym")
    if (p['alignment'] or 0) != 0:               rs.append(f"alignment_{p['alignment_name'] or p['alignment']}")
    if (p['is_powered_up'] or 0) == 1:           rs.append("powered_up")
    if (p['is_traded_flag_v2'] or 0) == 1 or (p['is_traded'] or 0) == 1:
        rs.append("traded")
    if (p['is_mega_evolved'] or 0) == 1:         rs.append("mega_evolved_v1")
    if (p['special_bg_id'] or 0) > 0:            rs.append("postcard_special_bg")
    if (p['location_bg_id'] or 0) > 0:           rs.append("location_bg_v1")
    if (p['adventure_effects_left'] or 0) > 0:   rs.append("adventure_effects_left")
    if p['costume_decoration_id']:               rs.append(f"costume_dec_{p['costume_decoration_id']}")
    sc = p['pokemon_size_category'] or 0
    if sc == 1:                                  rs.append("size_XXS")
    elif sc == 5:                                rs.append("size_XL_or_XXL")

    # V2 NEW rules from fresh proto data
    if (p['fresh_bread_mode'] or 0) != 0:        rs.append(f"bread_mode_{p['fresh_bread_mode']}")
    if (p['fresh_has_location_card'] or 0) == 1: rs.append("location_card_v2")
    if (p['fresh_costume'] or 0) != 0:           rs.append(f"display_costume_{p['fresh_costume']}")
    if (p['fresh_is_strong'] or 0) == 1:         rs.append("is_strong_pokemon")
    if (p['fresh_pokemon_badge'] or 0) != 0:     rs.append(f"adventure_effect_{p['fresh_pokemon_badge']}")
    if (p['fresh_current_temp_evolution'] or 0) != 0: rs.append("currently_mega_evolved")
    if (p['fresh_has_mega_level'] or 0) == 1:    rs.append("has_mega_level")
    # Bucket: alignment from fresh poll (matches user 63 purified, 219 shadow)
    fa = p['fresh_alignment'] or 0
    if fa == 1: rs.append("fresh_shadow")
    elif fa == 2: rs.append("fresh_purified")

    # User-tagged (any tag besides CLAUDE_TX)
    tids = p['fresh_tag_ids'] or ''
    other_tags = [t for t in tids.split(';') if t and t != CLAUDE_TX]
    if other_tags:
        rs.append(f"user_tagged_{len(other_tags)}")

    # Species-based
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

    # Add v2 columns if missing
    cols = {r[1] for r in c.execute("PRAGMA table_info(pokemon)").fetchall()}
    if 'cull_decision_v2' not in cols:
        c.execute("ALTER TABLE pokemon ADD COLUMN cull_decision_v2 TEXT")
    if 'cull_reason_v2' not in cols:
        c.execute("ALTER TABLE pokemon ADD COLUMN cull_reason_v2 TEXT")
    conn.commit()

    rows = [dict(r) for r in c.execute("SELECT * FROM pokemon").fetchall()]
    print(f"Loaded {len(rows)} pokemon")

    keep_reasons = {}
    def add_reason(uid, reason):
        keep_reasons.setdefault(uid, []).append(reason)

    for p in rows:
        for r in untouchable_reasons(p):
            add_reason(p['uid_hex'], r)

    # Top 10 shinies/species
    by_species_shiny = {}
    for p in rows:
        if p['is_shiny']:
            by_species_shiny.setdefault(p['pokemon_id'], []).append(p)
    for pid, lst in by_species_shiny.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst[:10]):
            add_reason(p['uid_hex'], f"shiny_top10_rank{i+1}")

    # Top 3 per (species, form, fresh_costume) by IV
    by_bucket = {}
    for p in rows:
        key = (p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)
        by_bucket.setdefault(key, []).append(p)
    for key, lst in by_bucket.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst[:3]):
            add_reason(p['uid_hex'], f"top3_bucket_rank{i+1}")

    # Compose decisions
    keep_count = 0
    xfer_count = 0
    print("\nWriting decisions back to DB...")
    for p in rows:
        uid = p['uid_hex']
        reasons = keep_reasons.get(uid, [])
        if reasons:
            decision = "KEEP"
            reason_str = ";".join(reasons[:8])
            keep_count += 1
        else:
            decision = "TRANSFER"
            reason_str = "no_keep_rule_matched"
            xfer_count += 1
        c.execute("UPDATE pokemon SET cull_decision_v2=?, cull_reason_v2=? WHERE uid_hex=?",
                  (decision, reason_str, uid))
    conn.commit()

    print(f"\n=== V2 FINAL ===")
    print(f"  Total: {len(rows)}")
    print(f"  KEEP:     {keep_count} ({keep_count/len(rows)*100:.1f}%)")
    print(f"  TRANSFER: {xfer_count} ({xfer_count/len(rows)*100:.1f}%)")

    print(f"\n=== Top species by transfer count ===")
    for row in c.execute("""SELECT species_name, COUNT(*) as n FROM pokemon
                            WHERE cull_decision_v2='TRANSFER' GROUP BY species_name
                            ORDER BY n DESC LIMIT 25""").fetchall():
        print(f"  {row[0]:25s} {row[1]}")

    print(f"\n=== Top INDIVIDUAL keep reasons ===")
    reason_counts = {}
    for r in c.execute("SELECT cull_reason_v2 FROM pokemon WHERE cull_decision_v2='KEEP'").fetchall():
        for tok in r[0].split(";"):
            reason_counts[tok] = reason_counts.get(tok, 0) + 1
    for tok, n in sorted(reason_counts.items(), key=lambda x: -x[1])[:30]:
        print(f"  {n:5d}  {tok}")

    print("\nExporting cull_plan_v2.csv...")
    with open('cull_plan_v2.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['uid_hex','pokemon_id','species_name','form','fresh_costume','cp',
                    'iv_pct','iv_total','iv_atk','iv_def','iv_sta',
                    'is_shiny','is_lucky','is_traded','alignment_name',
                    'level','nickname','cull_decision_v2','cull_reason_v2'])
        for r in c.execute("""SELECT uid_hex,pokemon_id,species_name,form,fresh_costume,cp,
                                     iv_pct,iv_total,iv_atk,iv_def,iv_sta,
                                     is_shiny,is_lucky,is_traded,alignment_name,
                                     level,nickname,cull_decision_v2,cull_reason_v2
                              FROM pokemon
                              ORDER BY species_name, form, fresh_costume, cull_decision_v2, iv_pct DESC"""):
            w.writerow(r)
    print("  cull_plan_v2.csv written")

    # Diff with v1
    print(f"\n=== V1 vs V2 diff ===")
    n_v1_xfer = c.execute("SELECT COUNT(*) FROM pokemon WHERE cull_decision='TRANSFER'").fetchone()[0]
    n_v2_xfer = c.execute("SELECT COUNT(*) FROM pokemon WHERE cull_decision_v2='TRANSFER'").fetchone()[0]
    print(f"  V1 transferables: {n_v1_xfer}")
    print(f"  V2 transferables: {n_v2_xfer}")
    n_v1_only = c.execute("SELECT COUNT(*) FROM pokemon WHERE cull_decision='TRANSFER' AND cull_decision_v2='KEEP'").fetchone()[0]
    n_v2_only = c.execute("SELECT COUNT(*) FROM pokemon WHERE cull_decision='KEEP' AND cull_decision_v2='TRANSFER'").fetchone()[0]
    print(f"  In V1.transfer but V2.keep: {n_v1_only}  (V2 saved them)")
    print(f"  In V1.keep but V2.transfer: {n_v2_only}  (V2 newly cull)")

    conn.close()

if __name__ == '__main__':
    main()

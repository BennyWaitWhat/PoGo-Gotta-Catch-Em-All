"""V9 dry-run: simulate shadow cull, no DB writes.

Shadow rule:
  Keep shadow if ANY of:
    - top 3 by IV in (pokemon_id, form) bucket
    - purifiable to hundo (every IV >= 13)
    - shiny
    - legendary/mythical/UB/paradox/adventure-effect
    - user-tagged (auth_tag_names minus EXCLUDED_AUTO_TAGS)
    - protected shiny chain
    - other base-untouchable reason already promoted by v8 (hundo, nundo, lucky-special,
      traded-special, best buddy, deployed, gmax/dmax, costume, location card, badge,
      strong, mega state, top-15 PvP, XXL top 3, legacy move, full-protect species,
      Mimikyu/Blissey)
    - only specimen of that species (sole-specimen preservation)
"""
import sqlite3
from references import (
    LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS,
    ADVENTURE_EFFECT_IDS, has_legacy_move,
)

PROTECTED_SHINY_PIDS = {
    129, 130, 133, 134, 135, 136, 196, 197, 470, 471, 700,
    172, 25, 26, 669, 670, 671, 384, 888,
}
FULL_PROTECT_PIDS = {778, 242}
PVP_RANK_KEEP = 15
SHADOW_TOP_N = 3
EXCLUDED_AUTO_TAGS = {'CLAUDE_TX', 'Traded'}
SPECIAL_PIDS = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS | ADVENTURE_EFFECT_IDS


def is_purifiable_hundo(p):
    return (p['iv_atk'] is not None and p['iv_def'] is not None and p['iv_sta'] is not None
            and p['iv_atk'] >= 13 and p['iv_def'] >= 13 and p['iv_sta'] >= 13)


def has_v8_non_shadow_protection(p, xxl_top3_uids):
    """Return list of v8 protection reasons that DON'T come from being shadow."""
    rs = []
    if p['is_hundo']: rs.append('hundo')
    if p['is_zero']: rs.append('nundo')
    if p['is_lucky']:
        owner = (p['original_owner_name'] or '').lower()
        if owner in ('florandez', 'ethanmateovz') or not owner:
            rs.append(f'lucky_from_{owner or "unknown"}')
    if p['is_best_buddy']: rs.append('best_buddy')
    if p['is_deployed']: rs.append('deployed_in_gym')
    if (p['is_traded_flag_v2'] or 0) == 1:
        owner = (p['original_owner_name'] or '').lower()
        if owner in ('florandez', 'ethanmateovz') or not owner:
            rs.append(f'traded_from_{owner or "unknown"}')
    auth = p['auth_tag_names'] or ''
    user_tags = [t for t in auth.split(';') if t and t not in EXCLUDED_AUTO_TAGS]
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
    if pid in FULL_PROTECT_PIDS: rs.append('full_protect_species')
    if pid in LEGENDARY_IDS: rs.append('legendary')
    if pid in MYTHICAL_IDS: rs.append('mythical')
    if pid in ULTRA_BEAST_IDS: rs.append('ultra_beast')
    if pid in PARADOX_IDS: rs.append('paradox')
    if pid in ADVENTURE_EFFECT_IDS: rs.append('adventure_effect_species')
    if has_legacy_move(pid, [p['move1'], p['move2'], p['move3']]): rs.append('legacy_move')
    if p['fresh_shiny'] and pid in PROTECTED_SHINY_PIDS:
        rs.append('shiny_protected_chain')
    return rs


def main():
    conn = sqlite3.connect('pokemon.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    rows = [dict(r) for r in c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()]

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

    species_counts = {}
    for p in rows:
        species_counts[p['pokemon_id']] = species_counts.get(p['pokemon_id'], 0) + 1

    shadows = [p for p in rows if (p['fresh_alignment'] or 0) == 1]
    print(f"Total shadows in bag: {len(shadows)}")

    shadow_buckets = {}
    for p in shadows:
        key = (p['pokemon_id'], p['form'] or 0)
        shadow_buckets.setdefault(key, []).append(p)

    keep = []
    xfer = []
    bucket_report = []

    for key, lst in sorted(shadow_buckets.items()):
        pid, form = key
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        kept_n = 0
        xferred_n = 0
        for i, p in enumerate(lst):
            reasons = has_v8_non_shadow_protection(p, xxl_top3_uids)
            if i < SHADOW_TOP_N:
                reasons.append(f'shadow_top{SHADOW_TOP_N}_rank{i+1}')
            if is_purifiable_hundo(p):
                reasons.append('shadow_purifiable_hundo')
            if p['fresh_shiny']:
                reasons.append('shadow_shiny')
            if pid in SPECIAL_PIDS:
                reasons.append('shadow_special_category')
            if species_counts.get(pid, 0) == 1:
                reasons.append('sole_specimen_of_species')

            if reasons:
                keep.append((p, reasons))
                kept_n += 1
            else:
                xfer.append((p, 'no_keep_rule_shadow'))
                xferred_n += 1
        species_name = lst[0]['species_name']
        bucket_report.append((species_name, pid, form, len(lst), kept_n, xferred_n))

    print(f"\nShadow KEEP: {len(keep)}    Shadow TRANSFER: {len(xfer)}")
    print(f"Net reduction: {len(xfer)} of 215 shadows ({100*len(xfer)/215:.1f}%)\n")

    print("=" * 80)
    print(f"{'Species':<28}{'PID':>6}{'Form':>6}{'Count':>8}{'Keep':>8}{'Xfer':>8}")
    print("=" * 80)
    for sp, pid, form, total, kept_n, xferred_n in sorted(bucket_report, key=lambda x: -x[5]):
        marker = ' <--' if xferred_n > 0 else ''
        print(f"{sp:<28}{pid:>6}{form:>6}{total:>8}{kept_n:>8}{xferred_n:>8}{marker}")

    print("\n" + "=" * 80)
    print("Transfer candidates (sample - first 30):")
    print("=" * 80)
    print(f"{'Species':<26}{'IV':>5}{'CP':>6}{'Lvl':>6}  IVs   Moves")
    for p, _ in xfer[:30]:
        ivs = f"{p['iv_atk']}/{p['iv_def']}/{p['iv_sta']}"
        print(f"  {p['species_name']:<24}{p['iv_total'] or 0:>5}{p['cp'] or 0:>6}"
              f"{p['level'] or 0:>6}  {ivs:<10}")

    print("\n" + "=" * 80)
    print("Sanity checks")
    print("=" * 80)

    legendary_shadows = [p for p in shadows if p['pokemon_id'] in LEGENDARY_IDS]
    mythical_shadows = [p for p in shadows if p['pokemon_id'] in MYTHICAL_IDS]
    ub_shadows = [p for p in shadows if p['pokemon_id'] in ULTRA_BEAST_IDS]
    paradox_shadows = [p for p in shadows if p['pokemon_id'] in PARADOX_IDS]
    print(f"Shadow legendaries: {len(legendary_shadows)}")
    print(f"Shadow mythicals:   {len(mythical_shadows)}")
    print(f"Shadow ultra beasts: {len(ub_shadows)}")
    print(f"Shadow paradoxes:   {len(paradox_shadows)}")

    distinct_shadow_pids = {p['pokemon_id'] for p in shadows}
    sole_pids = [pid for pid in distinct_shadow_pids if species_counts.get(pid, 0) == 1]
    print(f"\nShadow species where shadow is the ONLY specimen of that pokemon_id: {len(sole_pids)}")
    if sole_pids:
        for pid in sorted(sole_pids):
            sp = next(p['species_name'] for p in shadows if p['pokemon_id'] == pid)
            print(f"  pid={pid} {sp}")

    shiny_shadows = [p for p in shadows if p['fresh_shiny']]
    print(f"\nShadow shinies: {len(shiny_shadows)}")
    purifiable_shadows = [p for p in shadows if is_purifiable_hundo(p)]
    print(f"Shadow purifiable-to-hundo (>=13/13/13): {len(purifiable_shadows)}")

    print("\nTransfer counts per species:")
    xfer_by_species = {}
    for p, _ in xfer:
        xfer_by_species[p['species_name']] = xfer_by_species.get(p['species_name'], 0) + 1
    for sp, n in sorted(xfer_by_species.items(), key=lambda x: -x[1]):
        print(f"  {sp:<28}{n}")

    print("\nNo DB writes performed (dry-run).")


if __name__ == '__main__':
    main()

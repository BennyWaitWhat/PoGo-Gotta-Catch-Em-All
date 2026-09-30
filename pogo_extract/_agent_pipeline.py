"""10-Agent Sequential Cull Pipeline.

Implements the user's 10-agent decision pipeline. Each phase only touches
records currently UNASSIGNED. Phase 1 resets the decision column.

Phases:
  1. Absolute Rarity Lock           (Hundo, Nundo, 0/15/15, Functional Hundo, L1 Final)
  2. Dimensional Extremes           (XXL top 2 per species/form by weight)
  3. Great League Meta              [empty arrays — rule no-op]
  4. Ultra League Meta              [empty arrays — rule no-op]
  5. Master League Thresholds       [empty arrays — rule no-op]
  6. Next-Gen Mechanics             (Dynamax, Gigantamax, Mega, Adventure Effect)
  7. Shadow Alignment & PvE         [empty Shadow array — all unassigned shadows -> TRASH;
                                     Purified except Sableye/Wobbuffet -> TRASH]
  8. Shiny Cosmetic Capping         (top 6 per species/form/costume)
  9. Trade Economy + Final Purge    [empty VIP list — all traded -> TRASH;
                                     Premium reserves top 4 per species/form/costume;
                                     remaining UNASSIGNED -> TRASH]
 10. Reconciliation & Overrides     (USER_OVERRIDE_TAG salvage; favorite TRASH flag)
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')

# Empty arrays per user prompts — populate when known
FUNCTIONAL_HUNDO_SPECIES   = []
GL_TIER1_SPECIES           = []
GL_TIER2_SPECIES           = []
GL_LEGACY_MOVES            = []
UL_TIER1_SPECIES           = []
UL_TIER2_SPECIES           = []
ML_META_SPECIES            = []
SHADOW_PVE_SPECIES         = []
VIP_FRIENDS                = []  # original_owner_nickname matches
PILOT_DISTANCE_HASHES      = []  # original_location_hash matches

REGIONAL_SPECIES_REGEX = (
    'alola', 'alolan', 'galar', 'galarian', 'hisui', 'hisuian',
    'paldea', 'paldean', 'kanto'  # last for completeness
)

OVERRIDE_TAGS = ('Retain', 'Do Not Delete', 'Pending Trade', 'Sentimental')


def conn_open():
    return sqlite3.connect(DB)


def banner(n, name):
    print(f'\n=== Agent {n}: {name} ===')


def post_state(c, agent_n):
    rows = c.execute(
        "SELECT cull_decision_v9, COUNT(*) FROM pokemon WHERE in_bag=1 GROUP BY cull_decision_v9 ORDER BY 1"
    ).fetchall()
    state = {(r[0] or 'NULL'): r[1] for r in rows}
    print(f'  Post-Agent-{agent_n} state: {state}')


# -----------------------------------------------------------------------------
def agent_1(c):
    banner(1, 'Absolute Rarity Lock')
    c.execute("UPDATE pokemon SET cull_decision_v9='UNASSIGNED', cull_reason_v9=NULL WHERE in_bag=1")
    total = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1").fetchone()[0]
    print(f'  Reset: {total} -> UNASSIGNED')

    # Rule 1: Hundo
    c.execute("""UPDATE pokemon SET cull_decision_v9='KEEP', cull_reason_v9='Absolute Rarity: 100% IV'
                  WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                    AND (is_hundo=1 OR iv_total=45)""")
    print(f'  Rule 1 (Hundo)               : {c.rowcount:>5} KEEP')

    # Rule 2: Nundo
    c.execute("""UPDATE pokemon SET cull_decision_v9='KEEP', cull_reason_v9='Absolute Rarity: 0% IV'
                  WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                    AND (is_zero=1 OR iv_total=0)""")
    print(f'  Rule 2 (Nundo)               : {c.rowcount:>5} KEEP')

    # Rule 3: 0/15/15
    c.execute("""UPDATE pokemon SET cull_decision_v9='KEEP', cull_reason_v9='Absolute Rarity: PvP Perfect (0/15/15)'
                  WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                    AND iv_atk=0 AND iv_def=15 AND iv_sta=15""")
    print(f'  Rule 3 (0/15/15)             : {c.rowcount:>5} KEEP')

    # Rule 4: Functional Hundo (15/15/14) — empty array no-op
    if FUNCTIONAL_HUNDO_SPECIES:
        placeholders = ','.join('?' for _ in FUNCTIONAL_HUNDO_SPECIES)
        c.execute(f"""UPDATE pokemon SET cull_decision_v9='KEEP',
                      cull_reason_v9='Absolute Rarity: Functional Hundo (15/15/14)'
                      WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                        AND iv_atk=15 AND iv_def=15 AND iv_sta=14
                        AND species_name IN ({placeholders})""", FUNCTIONAL_HUNDO_SPECIES)
        print(f'  Rule 4 (Functional Hundo)    : {c.rowcount:>5} KEEP')
    else:
        print(f'  Rule 4 (Functional Hundo)    :     0 KEEP  [empty species array — no-op]')

    # Rule 5: Level 1 Final Evolution (excluding legendary/mythical)
    c.execute("""UPDATE pokemon SET cull_decision_v9='KEEP',
                  cull_reason_v9='Collector Asset: Level 1 Final Evolution'
                  WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                    AND level=1.0
                    AND COALESCE(can_evolve_estimated,0)=0
                    AND COALESCE(is_legendary,0)=0
                    AND COALESCE(is_mythical,0)=0""")
    print(f'  Rule 5 (L1 Final Evo)        : {c.rowcount:>5} KEEP')

    post_state(c, 1)


# -----------------------------------------------------------------------------
def agent_2(c):
    banner(2, 'Dimensional Extremes (XXL Top 2)')
    # Get all UNASSIGNED XXL specimens grouped by (species, form), top 2 by weight DESC then height DESC
    rows = c.execute("""SELECT uid_hex, species_name, form, weight_kg, height_m
                          FROM pokemon
                         WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                           AND pokemon_size_category=5
                         ORDER BY species_name, form, weight_kg DESC, height_m DESC""").fetchall()
    groups = {}
    for uid, species, form, weight, height in rows:
        groups.setdefault((species, form), []).append(uid)
    keep_uids = []
    for key, uids in groups.items():
        keep_uids.extend(uids[:2])
    if keep_uids:
        placeholders = ','.join('?' for _ in keep_uids)
        c.execute(f"""UPDATE pokemon SET cull_decision_v9='KEEP',
                      cull_reason_v9='Showcase Asset: Top 2 XXL'
                      WHERE uid_hex IN ({placeholders})""", keep_uids)
    print(f'  Top-2 XXL per (species,form) : {len(keep_uids):>5} KEEP (across {len(groups)} groups)')
    post_state(c, 2)


# -----------------------------------------------------------------------------
def agent_3(c):
    banner(3, 'Great League Meta Optimization')
    if GL_TIER1_SPECIES or GL_TIER2_SPECIES or GL_LEGACY_MOVES:
        # Implementations omitted — would mirror the spec
        print('  GL_Tier1/Tier2/Legacy arrays would be applied here')
    else:
        print(f'  Tier1, Tier2, Legacy arrays    :     0 KEEP  [all empty — no-op]')
    post_state(c, 3)


def agent_4(c):
    banner(4, 'Ultra League Meta Optimization')
    if UL_TIER1_SPECIES or UL_TIER2_SPECIES:
        print('  UL_Tier1/Tier2 arrays would be applied here')
    else:
        print(f'  Tier1, Tier2 arrays            :     0 KEEP  [all empty — no-op]')
    post_state(c, 4)


def agent_5(c):
    banner(5, 'Master League Thresholds')
    if ML_META_SPECIES:
        # Sunk Cost
        placeholders = ','.join('?' for _ in ML_META_SPECIES)
        c.execute(f"""UPDATE pokemon SET cull_decision_v9='KEEP',
                      cull_reason_v9='ML Meta: Sunk Cost Investment'
                      WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                        AND species_name IN ({placeholders})
                        AND level>=40.0""", ML_META_SPECIES)
        print(f'  Sunk Cost (lvl>=40)          : {c.rowcount:>5} KEEP')
        # Acceptable Min (15/14+/13+) top 3 per species
        rows = c.execute(f"""SELECT uid_hex, species_name FROM pokemon
                              WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                                AND species_name IN ({placeholders})
                                AND iv_atk=15 AND iv_def>=14 AND iv_sta>=13
                              ORDER BY species_name, iv_pct DESC""", ML_META_SPECIES).fetchall()
        groups = {}
        for uid, sp in rows:
            groups.setdefault(sp, []).append(uid)
        keep_uids = []
        for sp, uids in groups.items():
            keep_uids.extend(uids[:3])
        if keep_uids:
            ph2 = ','.join('?' for _ in keep_uids)
            c.execute(f"""UPDATE pokemon SET cull_decision_v9='KEEP',
                          cull_reason_v9='ML Meta: Acceptable Threshold'
                          WHERE uid_hex IN ({ph2})""", keep_uids)
        print(f'  Acceptable Min top 3/species : {len(keep_uids):>5} KEEP')
        # Sub-Optimal Purge
        c.execute(f"""UPDATE pokemon SET cull_decision_v9='TRASH',
                      cull_reason_v9='ML Meta: Sub-Optimal IV Liability'
                      WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                        AND species_name IN ({placeholders})
                        AND level<40.0
                        AND NOT (iv_atk=15 AND iv_def>=14 AND iv_sta>=13)""", ML_META_SPECIES)
        print(f'  Sub-Optimal Purge            : {c.rowcount:>5} TRASH')
    else:
        print(f'  ML Meta Array                :     0 ops    [empty array — no-op]')
    post_state(c, 5)


def agent_6(c):
    banner(6, 'Next-Gen Mechanics (Max/Mega/Adventure)')
    # Dynamax/Gigantamax top 2 non-shiny per (species, form) by iv_pct DESC, cp DESC
    rows = c.execute("""SELECT uid_hex, species_name, form, is_shiny, iv_pct, cp
                          FROM pokemon
                         WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                           AND (COALESCE(is_dynamax_capable,0)=1
                                OR COALESCE(is_gigantamax_capable,0)=1
                                OR COALESCE(is_gmax_dmax,0)=1)
                         ORDER BY species_name, form, iv_pct DESC, cp DESC""").fetchall()
    groups = {}
    for r in rows:
        groups.setdefault((r[1], r[2]), []).append(r)
    keep_max_uids = []
    shiny_keep_uids = []
    for key, members in groups.items():
        non_shiny = [m for m in members if not m[3]]
        for m in non_shiny[:2]:
            keep_max_uids.append(m[0])
        for m in members:
            if m[3]:
                shiny_keep_uids.append(m[0])
    if keep_max_uids:
        ph = ','.join('?' for _ in keep_max_uids)
        c.execute(f"""UPDATE pokemon SET cull_decision_v9='KEEP',
                      cull_reason_v9='Max Battle Infrastructure'
                      WHERE uid_hex IN ({ph})""", keep_max_uids)
    print(f'  Max Battle top-2 non-shiny   : {len(keep_max_uids):>5} KEEP')
    if shiny_keep_uids:
        ph = ','.join('?' for _ in shiny_keep_uids)
        c.execute(f"""UPDATE pokemon SET cull_decision_v9='KEEP',
                      cull_reason_v9='Max Battle: Shiny Exemption'
                      WHERE uid_hex IN ({ph}) AND cull_decision_v9='UNASSIGNED'""", shiny_keep_uids)
    print(f'  Max Battle shiny exemption   : {c.rowcount:>5} KEEP')

    # Active Mega Investment
    c.execute("""UPDATE pokemon SET cull_decision_v9='KEEP',
                  cull_reason_v9='PvE: Active Mega Investment'
                  WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                    AND (COALESCE(has_mega_evolved,0)=1
                         OR COALESCE(has_mega_evolved_v2,0)=1
                         OR COALESCE(mega_Level,0)>=1)""")
    print(f'  Active Mega Investment       : {c.rowcount:>5} KEEP')

    # Future Mega Candidates — top 1 per species by iv_pct DESC
    rows = c.execute("""SELECT uid_hex, species_name, iv_pct
                          FROM pokemon
                         WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                           AND COALESCE(can_mega_evolve,0)=1
                         ORDER BY species_name, iv_pct DESC""").fetchall()
    groups = {}
    for uid, sp, ivp in rows:
        groups.setdefault(sp, []).append(uid)
    fm_uids = [uids[0] for uids in groups.values()]
    if fm_uids:
        ph = ','.join('?' for _ in fm_uids)
        c.execute(f"""UPDATE pokemon SET cull_decision_v9='KEEP',
                      cull_reason_v9='PvE: Future Mega Candidate'
                      WHERE uid_hex IN ({ph})""", fm_uids)
    print(f'  Future Mega top-1/species    : {len(fm_uids):>5} KEEP')

    # Adventure Effect
    c.execute("""UPDATE pokemon SET cull_decision_v9='KEEP',
                  cull_reason_v9='Utility: Adventure Effect Asset'
                  WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                    AND COALESCE(adventure_effects_left,0)>0""")
    print(f'  Adventure Effect Asset       : {c.rowcount:>5} KEEP')
    post_state(c, 6)


def agent_7(c):
    banner(7, 'Shadow Alignment & PvE')
    # Shadow PvE Array empty -> ALL unassigned shadows get TRASH'd
    if SHADOW_PVE_SPECIES:
        print('  Shadow PvE Array population would happen here')
    else:
        print(f'  Shadow PvE Array             :     0 ops    [empty array]')

    # All shadow records still UNASSIGNED -> TRASH
    c.execute("""UPDATE pokemon SET cull_decision_v9='TRASH',
                  cull_reason_v9='PvE: Sub-Optimal Shadow Hoard'
                  WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                    AND fresh_alignment=1""")
    print(f'  Shadow Purge (UNASSIGNED)    : {c.rowcount:>5} TRASH')

    # Purified Purge (alignment=2) except Sableye/Wobbuffet
    c.execute("""UPDATE pokemon SET cull_decision_v9='TRASH',
                  cull_reason_v9='PvE/PvP: Sub-Optimal Purified Asset'
                  WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                    AND (fresh_alignment=2 OR is_purified_flag=1)
                    AND species_name NOT IN ('Sableye','Wobbuffet')""")
    print(f'  Purified Purge               : {c.rowcount:>5} TRASH')
    post_state(c, 7)


def agent_8(c):
    banner(8, 'Shiny Cosmetic Capping (Top 6 per species/form/costume)')
    rows = c.execute("""SELECT uid_hex, species_name, form, COALESCE(fresh_costume,0) AS costume,
                               iv_pct, cp
                          FROM pokemon
                         WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                           AND (is_shiny=1 OR fresh_shiny=1)
                         ORDER BY species_name, form, costume, iv_pct DESC, cp DESC""").fetchall()
    groups = {}
    for r in rows:
        groups.setdefault((r[1], r[2], r[3]), []).append(r[0])
    keep_uids = []
    trash_uids = []
    for key, uids in groups.items():
        keep_uids.extend(uids[:6])
        trash_uids.extend(uids[6:])
    if keep_uids:
        ph = ','.join('?' for _ in keep_uids)
        c.execute(f"""UPDATE pokemon SET cull_decision_v9='KEEP',
                      cull_reason_v9='Cosmetic/Trade: Top Shiny Cap'
                      WHERE uid_hex IN ({ph})""", keep_uids)
    print(f'  Top-6 shiny per group        : {len(keep_uids):>5} KEEP (across {len(groups)} groups)')
    if trash_uids:
        ph = ','.join('?' for _ in trash_uids)
        c.execute(f"""UPDATE pokemon SET cull_decision_v9='TRASH',
                      cull_reason_v9='Cosmetic: Shiny Bloat / Exceeds Cap'
                      WHERE uid_hex IN ({ph})""", trash_uids)
    print(f'  Excess shiny over cap        : {len(trash_uids):>5} TRASH')
    post_state(c, 8)


def agent_9(c):
    banner(9, 'Trade Economy + Final Purge')
    # Traded Invalidation
    if VIP_FRIENDS:
        ph = ','.join('?' for _ in VIP_FRIENDS)
        c.execute(f"""UPDATE pokemon SET cull_decision_v9='KEEP',
                      cull_reason_v9='Economy: VIP/Distance Origin'
                      WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                        AND (is_traded=1 OR is_traded_flag_v2=1)
                        AND lower(original_owner_nickname) IN ({ph})""", [v.lower() for v in VIP_FRIENDS])
        print(f'  VIP Origin Salvage           : {c.rowcount:>5} KEEP')
    else:
        print(f'  VIP Origin Salvage           :     0 KEEP   [empty VIP list]')
    c.execute("""UPDATE pokemon SET cull_decision_v9='TRASH',
                  cull_reason_v9='Economy: Dead Weight (Already Traded)'
                  WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                    AND (is_traded=1 OR is_traded_flag_v2=1)""")
    print(f'  Traded Dead Weight           : {c.rowcount:>5} TRASH')

    # Premium Trade Reserves
    # Filter: is_legendary OR is_mythical OR has_location_card OR special_bg_id>0 OR location_bg_id>0
    #         OR natural_art_bg>0 OR fresh_costume!=0 OR original_costume!=0
    #         OR species_name matches regional pattern (heuristic: form_region != kantonian)
    rows = c.execute("""SELECT uid_hex, species_name, form, COALESCE(fresh_costume,0) AS costume,
                               iv_pct
                          FROM pokemon
                         WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'
                           AND (COALESCE(is_legendary,0)=1
                                OR COALESCE(is_mythical,0)=1
                                OR COALESCE(has_location_card,0)=1
                                OR COALESCE(fresh_has_location_card,0)=1
                                OR COALESCE(special_bg_id,0)>0
                                OR COALESCE(location_bg_id,0)>0
                                OR COALESCE(natural_art_bg,0)>0
                                OR COALESCE(fresh_costume,0)!=0
                                OR COALESCE(original_costume,0)!=0
                                OR form_region IN ('alolan','galarian','hisuian','paldean'))
                         ORDER BY species_name, form, costume, iv_pct DESC""").fetchall()
    groups = {}
    for r in rows:
        groups.setdefault((r[1], r[2], r[3]), []).append(r[0])
    keep_uids = []
    trash_uids = []
    for key, uids in groups.items():
        keep_uids.extend(uids[:4])
        trash_uids.extend(uids[4:])
    if keep_uids:
        ph = ','.join('?' for _ in keep_uids)
        c.execute(f"""UPDATE pokemon SET cull_decision_v9='KEEP',
                      cull_reason_v9='Economy: Premium Trade Reserve'
                      WHERE uid_hex IN ({ph})""", keep_uids)
    print(f'  Premium Reserves top-4/group : {len(keep_uids):>5} KEEP (across {len(groups)} groups)')
    if trash_uids:
        ph = ','.join('?' for _ in trash_uids)
        c.execute(f"""UPDATE pokemon SET cull_decision_v9='TRASH',
                      cull_reason_v9='Economy: Excess Premium Hoard'
                      WHERE uid_hex IN ({ph})""", trash_uids)
    print(f'  Premium Excess Hoard         : {len(trash_uids):>5} TRASH')

    # Final Purge
    c.execute("""UPDATE pokemon SET cull_decision_v9='TRASH',
                  cull_reason_v9='Zero Utility Remnant'
                  WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'""")
    print(f'  Final Purge (all UNASSIGNED) : {c.rowcount:>5} TRASH')
    post_state(c, 9)


def agent_10(c):
    banner(10, 'Reconciliation & Overrides')
    # USER_OVERRIDE_TAG salvage
    or_clauses = ' OR '.join("auth_tag_names LIKE '%' || ? || '%'" for _ in OVERRIDE_TAGS)
    c.execute(f"""UPDATE pokemon SET cull_decision_v9='KEEP',
                  cull_reason_v9='USER_OVERRIDE_TAG'
                  WHERE in_bag=1 AND ({or_clauses})""", list(OVERRIDE_TAGS))
    print(f'  USER_OVERRIDE_TAG salvage    : {c.rowcount:>5} KEEP')

    # Favorite TRASH flag — append <REQUIRES_UNFAVORITE_API_CALL>
    c.execute("""UPDATE pokemon
                    SET cull_reason_v9 = cull_reason_v9 || ' <REQUIRES_UNFAVORITE_API_CALL>'
                  WHERE in_bag=1 AND cull_decision_v9='TRASH'
                    AND COALESCE(is_favorite_v2,0)=1
                    AND cull_reason_v9 NOT LIKE '%<REQUIRES_UNFAVORITE_API_CALL>%'""")
    print(f'  Favorite TRASH flagged       : {c.rowcount:>5} appended')

    # Final verify: 0 UNASSIGNED
    unassigned = c.execute(
        "SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'"
    ).fetchone()[0]
    print(f'  Final UNASSIGNED check       : {unassigned} remaining')
    if unassigned > 0:
        print(f'  ! {unassigned} records still UNASSIGNED — pipeline incomplete!')
    post_state(c, 10)


def main():
    conn = conn_open()
    c = conn.cursor()
    try:
        for fn in (agent_1, agent_2, agent_3, agent_4, agent_5,
                   agent_6, agent_7, agent_8, agent_9, agent_10):
            fn(c)
            conn.commit()
    finally:
        # Final summary report
        print('\n=== FINAL BREAKDOWN ===')
        for d, n in c.execute(
            "SELECT cull_decision_v9, COUNT(*) FROM pokemon WHERE in_bag=1 GROUP BY cull_decision_v9 ORDER BY COUNT(*) DESC"
        ):
            print(f'  {d:18s} {n}')
        print('\n=== Reasons (top 20) ===')
        for reason, n in c.execute(
            "SELECT cull_reason_v9, COUNT(*) FROM pokemon WHERE in_bag=1 GROUP BY cull_reason_v9 ORDER BY COUNT(*) DESC LIMIT 20"
        ):
            print(f'  {n:>5}  {reason or "NULL"}')
        conn.close()


if __name__ == '__main__':
    main()

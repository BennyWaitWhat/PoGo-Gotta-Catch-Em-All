"""Agent 1: Absolute Rarity Lock.

Resets cull_decision_v9 for all in_bag=1 records to 'UNASSIGNED', then applies
5 absolute-rarity rules sequentially. Each rule only assigns to records still
UNASSIGNED — once a record is KEEP'd, subsequent rules skip it.

Rules (sequential):
  1. Hundo Protection       — is_hundo=1 OR iv_total=45  → "Absolute Rarity: 100% IV"
  2. Nundo Protection       — is_zero=1 OR iv_total=0   → "Absolute Rarity: 0% IV"
  3. PvP Perfection         — iv_atk=0 AND iv_def=15 AND iv_sta=15
                              → "Absolute Rarity: PvP Perfect (0/15/15)"
  4. Functional Hundo       — iv_atk=15 AND iv_def=15 AND iv_sta=14
                              AND species_name IN (<<USER ARRAY EMPTY>>)
                              → "Absolute Rarity: Functional Hundo (15/15/14)"
                              (RULE IS NO-OP — user's species array was empty)
  5. Level 1 Final Evolution — level=1.0 AND can_evolve_estimated=false
                              AND NOT (is_legendary OR is_mythical)
                              → "Collector Asset: Level 1 Final Evolution"

Output: pokemon.db updated. cull_decision_v9 left as 'UNASSIGNED' for records
not matched by any rule — Agent 2 will evaluate those.
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')

# Rule 4 species array — user supplied empty. Fill when known.
FUNCTIONAL_HUNDO_SPECIES = []


def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # --- Reset ---
    pre_decisions = c.execute(
        "SELECT cull_decision_v9, COUNT(*) FROM pokemon WHERE in_bag=1 GROUP BY cull_decision_v9"
    ).fetchall()
    print(f'Pre-reset decisions in_bag:')
    for d, n in pre_decisions:
        print(f'  {d!r:18s} {n}')

    c.execute("UPDATE pokemon SET cull_decision_v9='UNASSIGNED', cull_reason_v9=NULL WHERE in_bag=1")
    conn.commit()
    total = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND cull_decision_v9='UNASSIGNED'").fetchone()[0]
    print(f'\nReset: {total} records → UNASSIGNED\n')

    # --- Rule 1: Hundo Protection ---
    c.execute("""
        UPDATE pokemon
           SET cull_decision_v9 = 'KEEP',
               cull_reason_v9   = 'Absolute Rarity: 100% IV'
         WHERE in_bag = 1
           AND cull_decision_v9 = 'UNASSIGNED'
           AND (is_hundo = 1 OR iv_total = 45)
    """)
    n1 = c.rowcount
    conn.commit()
    print(f'Rule 1 — Hundo Protection           : {n1:>5} KEEP')

    # --- Rule 2: Nundo Protection ---
    c.execute("""
        UPDATE pokemon
           SET cull_decision_v9 = 'KEEP',
               cull_reason_v9   = 'Absolute Rarity: 0% IV'
         WHERE in_bag = 1
           AND cull_decision_v9 = 'UNASSIGNED'
           AND (is_zero = 1 OR iv_total = 0)
    """)
    n2 = c.rowcount
    conn.commit()
    print(f'Rule 2 — Nundo Protection           : {n2:>5} KEEP')

    # --- Rule 3: PvP Perfection (0/15/15) ---
    c.execute("""
        UPDATE pokemon
           SET cull_decision_v9 = 'KEEP',
               cull_reason_v9   = 'Absolute Rarity: PvP Perfect (0/15/15)'
         WHERE in_bag = 1
           AND cull_decision_v9 = 'UNASSIGNED'
           AND iv_atk = 0 AND iv_def = 15 AND iv_sta = 15
    """)
    n3 = c.rowcount
    conn.commit()
    print(f'Rule 3 — PvP Perfection (0/15/15)   : {n3:>5} KEEP')

    # --- Rule 4: Functional Hundo (15/15/14) for whitelisted species ---
    if FUNCTIONAL_HUNDO_SPECIES:
        placeholders = ','.join('?' for _ in FUNCTIONAL_HUNDO_SPECIES)
        c.execute(f"""
            UPDATE pokemon
               SET cull_decision_v9 = 'KEEP',
                   cull_reason_v9   = 'Absolute Rarity: Functional Hundo (15/15/14)'
             WHERE in_bag = 1
               AND cull_decision_v9 = 'UNASSIGNED'
               AND iv_atk = 15 AND iv_def = 15 AND iv_sta = 14
               AND species_name IN ({placeholders})
        """, FUNCTIONAL_HUNDO_SPECIES)
        n4 = c.rowcount
        conn.commit()
    else:
        n4 = 0
    print(f'Rule 4 — Functional Hundo (15/15/14): {n4:>5} KEEP  (empty species array — rule no-op; awaiting list)')

    # --- Rule 5: Level 1 Final Evolution ---
    # can_evolve_estimated may be NULL on the 313 new captures (legacy column not
    # refreshed for new UIDs). Literal rule: false. Treat NULL as 0 per the user's
    # `== false` directive (NULL is not true). is_legendary / is_mythical are
    # backfilled by the enricher for all 4442 in-bag — exclude where 1.
    c.execute("""
        UPDATE pokemon
           SET cull_decision_v9 = 'KEEP',
               cull_reason_v9   = 'Collector Asset: Level 1 Final Evolution'
         WHERE in_bag = 1
           AND cull_decision_v9 = 'UNASSIGNED'
           AND level = 1.0
           AND COALESCE(can_evolve_estimated, 0) = 0
           AND COALESCE(is_legendary, 0) = 0
           AND COALESCE(is_mythical, 0) = 0
    """)
    n5 = c.rowcount
    conn.commit()
    print(f'Rule 5 — Level 1 Final Evolution    : {n5:>5} KEEP')

    # --- Final state ---
    post_decisions = c.execute(
        "SELECT cull_decision_v9, COUNT(*) FROM pokemon WHERE in_bag=1 GROUP BY cull_decision_v9"
    ).fetchall()
    print(f'\nPost-Agent-1 decisions in_bag:')
    for d, n in post_decisions:
        print(f'  {d!r:18s} {n}')

    # --- Reason breakdown (for KEEP) ---
    print('\nKEEP reasons assigned by Agent 1:')
    for reason, n in c.execute(
        "SELECT cull_reason_v9, COUNT(*) FROM pokemon WHERE in_bag=1 AND cull_decision_v9='KEEP' "
        "GROUP BY cull_reason_v9 ORDER BY n DESC"
    ):
        print(f'  {n:>5}  {reason}')

    # --- Sample of each rule's catches (top 5 by IV/CP) ---
    print('\nSample (top 3 by cp/iv per rule):')
    for reason in [
        'Absolute Rarity: 100% IV',
        'Absolute Rarity: 0% IV',
        'Absolute Rarity: PvP Perfect (0/15/15)',
        'Collector Asset: Level 1 Final Evolution',
    ]:
        rows = c.execute("""
            SELECT uid_hex, pokemon_id, species_name, iv_atk, iv_def, iv_sta, cp, level
              FROM pokemon
             WHERE in_bag=1 AND cull_decision_v9='KEEP' AND cull_reason_v9=?
             ORDER BY iv_total DESC, cp DESC LIMIT 3
        """, (reason,)).fetchall()
        if not rows: continue
        print(f'\n  [{reason}]')
        for r in rows:
            print(f'    {r[0]} #{r[1]:>4} {r[2]:14s} {r[3]}/{r[4]}/{r[5]} cp={r[6]} lvl={r[7]}')

    conn.close()
    print('\n=== Agent 1 complete. UNASSIGNED records ready for Agent 2. ===')


if __name__ == '__main__':
    main()

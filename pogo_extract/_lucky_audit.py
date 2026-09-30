import sqlite3, json, os

con = sqlite3.connect('pokemon.db')
con.row_factory = sqlite3.Row
cur = con.cursor()

PROTECTED = {'florandez', 'ethanmateovz'}

def q(sql, *args):
    cur.execute(sql, args)
    return cur.fetchall()

# 1. Total luckies in bag
total_in_bag = q("SELECT COUNT(*) AS n FROM pokemon WHERE is_lucky=1 AND in_bag=1")[0]['n']
total_all = q("SELECT COUNT(*) AS n FROM pokemon WHERE is_lucky=1")[0]['n']

# 2. By original_owner_name (in_bag only)
by_owner = [dict(r) for r in q("""
    SELECT COALESCE(NULLIF(original_owner_name,''),'(unknown)') AS owner,
           COUNT(*) AS n
    FROM pokemon
    WHERE is_lucky=1 AND in_bag=1
    GROUP BY owner
    ORDER BY n DESC, owner
""")]

# 3. By species (in_bag only)
by_species = [dict(r) for r in q("""
    SELECT species_name, COUNT(*) AS n
    FROM pokemon
    WHERE is_lucky=1 AND in_bag=1
    GROUP BY species_name
    ORDER BY n DESC, species_name
""")]

# 4. Lucky hundos
hundos = [dict(r) for r in q("""
    SELECT uid_hex, species_name, cp, iv_atk, iv_def, iv_sta, level,
           original_owner_name, is_shiny, form, costume, creation_date
    FROM pokemon
    WHERE is_lucky=1 AND in_bag=1 AND is_hundo=1
    ORDER BY species_name
""")]

# 5. Candidates for transfer: luckies NOT from protected owners
unprotected = [dict(r) for r in q("""
    SELECT uid_hex, species_name, cp, iv_atk, iv_def, iv_sta, iv_pct, level,
           original_owner_name, is_shiny, is_hundo, form, costume,
           cull_decision_v9, cull_reason_v9,
           cull_decision_v8, cull_reason_v8,
           pokemon_size_category, creation_date
    FROM pokemon
    WHERE is_lucky=1 AND in_bag=1
      AND (original_owner_name IS NULL
           OR (LOWER(original_owner_name) NOT IN ('florandez','ethanmateovz')))
    ORDER BY species_name, iv_pct DESC
""")]

# Protected vs unprotected counts
protected_count = q("""
    SELECT COUNT(*) AS n FROM pokemon
    WHERE is_lucky=1 AND in_bag=1
      AND LOWER(original_owner_name) IN ('florandez','ethanmateovz')
""")[0]['n']

# Stricter rule analysis on unprotected luckies:
# - what does the latest cull v9 / v8 currently say about them?
# - flag luckies that v9 marks as cull/transfer
v_decisions = {}
for row in unprotected:
    d9 = (row.get('cull_decision_v9') or '').upper()
    v_decisions.setdefault(d9 or '(null)', 0)
    v_decisions[d9 or '(null)'] += 1

# Stricter rule candidates: luckies that are low IV, not shiny, not hundo, not jumbo,
# from unprotected owners - these are the most defensible to cull under strict rules
strict_candidates = [dict(r) for r in q("""
    SELECT uid_hex, species_name, cp, iv_atk, iv_def, iv_sta, iv_pct, level,
           original_owner_name, is_shiny, is_hundo, pokemon_size_category,
           cull_decision_v9, cull_reason_v9
    FROM pokemon
    WHERE is_lucky=1 AND in_bag=1
      AND (original_owner_name IS NULL
           OR LOWER(original_owner_name) NOT IN ('florandez','ethanmateovz'))
      AND COALESCE(is_shiny,0)=0
      AND COALESCE(is_hundo,0)=0
      AND COALESCE(pokemon_size_category,0) < 5
      AND iv_pct < 90.0
    ORDER BY iv_pct ASC, species_name
""")]

# Also flag luckies that v9 explicitly marks for cull/transfer
v9_cull = [dict(r) for r in q("""
    SELECT uid_hex, species_name, cp, iv_pct, original_owner_name,
           cull_decision_v9, cull_reason_v9
    FROM pokemon
    WHERE is_lucky=1 AND in_bag=1
      AND UPPER(COALESCE(cull_decision_v9,'')) IN ('CULL','TRANSFER')
    ORDER BY species_name
""")]

out = {
    'summary': {
        'total_luckies_in_bag': total_in_bag,
        'total_luckies_all_rows': total_all,
        'protected_owner_count': protected_count,
        'unprotected_owner_count': total_in_bag - protected_count,
        'protected_owners': sorted(PROTECTED),
    },
    'by_original_owner': by_owner,
    'top_giver': by_owner[0] if by_owner else None,
    'by_species': by_species,
    'top_species': by_species[0] if by_species else None,
    'lucky_hundos': {
        'count': len(hundos),
        'rows': hundos,
    },
    'transfer_candidates_unprotected': {
        'count': len(unprotected),
        'cull_v9_decision_breakdown': v_decisions,
        'rows': unprotected,
    },
    'stricter_rule_candidates': {
        'description': 'Unprotected, not shiny, not hundo, not jumbo (size<5), iv_pct<90',
        'count': len(strict_candidates),
        'rows': strict_candidates,
    },
    'already_marked_cull_v9': {
        'description': 'Luckies the latest cull rules (v9) already flag CULL/TRANSFER',
        'count': len(v9_cull),
        'rows': v9_cull,
    },
}

os.makedirs('agent_outputs', exist_ok=True)
with open('agent_outputs/lucky_audit.json','w',encoding='utf-8') as f:
    json.dump(out, f, indent=2)

print('Wrote agent_outputs/lucky_audit.json')
print('Total in bag:', total_in_bag)
print('Top giver:', out['top_giver'])
print('Top species:', out['top_species'])
print('Hundos:', len(hundos))
print('Unprotected:', len(unprotected))
print('Strict-rule candidates:', len(strict_candidates))
print('Already cull_v9:', len(v9_cull))
print('v9 decision breakdown for unprotected:', v_decisions)

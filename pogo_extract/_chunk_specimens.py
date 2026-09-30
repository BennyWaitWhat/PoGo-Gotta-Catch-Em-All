"""Split in-bag specimens into 20 non-overlapping chunks for parallel agent
processing. Each chunk gets its own CSV with the full live attribute set.

Output: rescan_report/chunks_for_agents/chunk_NN.csv (NN = 01..20)
"""
import csv, math, os, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')
OUT_DIR = os.path.join(HERE, 'rescan_report', 'chunks_for_agents')
N_CHUNKS = 20

# Columns the agents need. Kept lean to control token cost — agents can query
# the DB for additional fields if a specific specimen needs deeper checking.
COLUMNS = [
    'uid_hex', 'pokemon_id', 'species_name', 'form', 'form_region', 'gender',
    'cp', 'level', 'iv_atk', 'iv_def', 'iv_sta', 'iv_total', 'iv_pct',
    'is_shiny', 'fresh_alignment', 'alignment_name',
    'is_lucky', 'is_best_buddy', 'was_best_buddy_badge',
    'is_three_star', 'is_four_star', 'is_zero',
    'is_legendary', 'is_mythical', 'is_ultra_beast', 'is_paradox',
    'can_mega_evolve', 'is_gigantamax_capable', 'is_adventure_effect_species',
    'fresh_pokemon_badge', 'fresh_costume', 'fresh_has_location_card',
    'fresh_is_strong', 'fresh_bread_mode', 'fresh_current_temp_evolution',
    'fresh_has_mega_level', 'has_mega_evolved',
    'adventure_effects_left', 'pokemon_size_category',
    'gl_rank', 'gl_pct', 'gl_stage', 'ul_rank', 'ul_pct', 'ul_stage',
    'll_rank', 'll_pct', 'll_stage',
    'original_owner_name', 'nickname', 'favorite', 'marked_remote_tradable',
    'is_traded_flag_v2', 'hatched_from_egg', 'caught_in_party', 'from_fort',
    'creation_time_ms', 'pokeball_item', 'weather_boost',
    'cull_decision_v9', 'cull_reason_v9',
    'move1', 'move2', 'move3',
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    cols_sql = ', '.join(COLUMNS)
    rows = conn.execute(f"SELECT {cols_sql} FROM pokemon WHERE in_bag=1 ORDER BY uid_hex").fetchall()
    conn.close()
    total = len(rows)
    chunk_size = math.ceil(total / N_CHUNKS)
    print(f'Total in-bag: {total}; splitting into {N_CHUNKS} chunks of ~{chunk_size}')
    for i in range(N_CHUNKS):
        chunk = rows[i*chunk_size:(i+1)*chunk_size]
        if not chunk: break
        path = os.path.join(OUT_DIR, f'chunk_{i+1:02d}.csv')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            for r in chunk:
                w.writerow(['' if v is None else str(v) for v in r])
        print(f'  chunk_{i+1:02d}.csv: {len(chunk)} rows')


if __name__ == '__main__':
    main()

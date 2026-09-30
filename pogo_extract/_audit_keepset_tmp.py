import sqlite3, os, sys
sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.abspath(__file__))
con = sqlite3.connect(os.path.join(ROOT, 'pokemon.db'))
allcols = [r[1] for r in con.execute('PRAGMA table_info(pokemon)')]
con.close()

# --- Genuine value-reads, assembled from manual verification of each live file ---

# keep_policy.py (SELECT *; columns accessed via r['col']) -- verified by reading source
keep_policy = set("""
uid_hex pokemon_id species_name cp iv_atk iv_def iv_sta iv_total form
fresh_costume fresh_alignment fresh_shiny fresh_bread_mode fresh_is_strong
fresh_has_location_card height_m weight_kg pokemon_size_category is_zero
is_lucky is_traded is_traded_flag_v2 was_best_buddy_badge original_owner_name
adventure_effects_left is_legendary is_mythical is_ultra_beast is_paradox
gl_rank gl_stage ul_rank ul_stage cull_decision_v9 in_bag
""".split())

# cull_v9.py (SELECT *; r['col']) -- verified
cull_v9 = set("""
uid_hex pokemon_id cp iv_total form fresh_costume fresh_alignment fresh_shiny
fresh_bread_mode fresh_is_strong fresh_has_location_card fresh_has_mega_level
fresh_current_temp_evolution fresh_pokemon_badge weight_kg pokemon_size_category
is_hundo is_zero is_lucky is_traded_flag_v2 is_best_buddy is_deployed
original_owner_name adventure_effects_left auth_tag_names
gl_rank gl_stage gl_pct ul_rank ul_stage ul_pct ll_rank in_bag
cull_decision_v9 cull_reason_v9
""".split())

# build_tagsets.py (explicit SELECT + SQL-tag WHERE literals) -- verified
build_tagsets = set("""
uid_hex pokemon_id form fresh_costume fresh_alignment species_name
iv_atk iv_def iv_sta iv_total cp gl_rank ul_rank gl_stage ul_stage
weight_kg height_m pokemon_size_category is_zero was_best_buddy_badge
is_traded is_traded_flag_v2 is_lucky original_owner_name auth_tag_names in_bag
""".split())

# compute_all_ranks.py (explicit SELECT; NOTE costume slot is fresh_costume; bare 'costume' arg ignored)
compute_ranks = set("""
uid_hex species_name pokemon_id form fresh_costume iv_atk iv_def iv_sta
fresh_alignment in_bag gl_rank gl_pct gl_stage ul_rank ul_pct ul_stage
ll_rank ll_pct ll_stage
""".split())  # rank OUTPUT cols it WRITES; reads only the first 9

# detect_legacy.py (explicit SELECT) -- LIVE pipeline step feeding cull legacy_uids + 3 Legacy Moves
detect_legacy = set("""
uid_hex pokemon_id species_name move1 move2 move3 form iv_total alignment in_bag
""".split())

# tag_ops.py + apply_tagsets.py (tag write/mirror)
tag_pipeline = set("uid_hex auth_tag_names in_bag".split())

# pogo_pipeline.py step_tag_transfers reads uid + cull_decision_v9 (+in_bag)
pipeline_xfer = set("uid cull_decision_v9 in_bag".split())

# Columns that compute_all_ranks WRITES but nothing READS downstream (write-only)
ranker_writeonly = set("ll_pct ll_stage ll_chain_ranks gl_chain_ranks ul_chain_ranks".split())

readers = {
 'keep_policy': keep_policy, 'cull_v9': cull_v9, 'build_tagsets': build_tagsets,
 'compute_ranks(reads)': compute_ranks - ranker_writeonly,
 'detect_legacy': detect_legacy, 'tag_pipeline': tag_pipeline, 'pipeline_xfer': pipeline_xfer,
}

KEEP = set()
for s in readers.values():
    KEEP |= s
# remove any accidental write-only inclusion that has no reader
KEEP -= (ranker_writeonly - KEEP)  # no-op safety

# sanity: every KEEP col must actually exist
missing = [c for c in KEEP if c not in allcols]
assert not missing, missing

KEEP_ORDERED = [c for c in allcols if c in KEEP]
DROP_ORDERED = [c for c in allcols if c not in KEEP]

print("CORRECTED KEEP SET:", len(KEEP_ORDERED))
print(', '.join(KEEP_ORDERED))
print()
print("DROP SET:", len(DROP_ORDERED))
print(', '.join(DROP_ORDERED))
print()

# Diff against the EXISTING doc's 47-col keep list
existing47 = set("""
uid_hex uid pokemon_id species_name cp iv_atk iv_def iv_sta iv_total
form fresh_costume fresh_alignment fresh_shiny fresh_bread_mode
fresh_is_strong fresh_has_location_card fresh_has_mega_level
fresh_current_temp_evolution fresh_pokemon_badge height_m weight_kg
pokemon_size_category is_hundo is_zero is_lucky is_traded is_traded_flag_v2
is_best_buddy is_deployed was_best_buddy_badge original_owner_name
adventure_effects_left is_legendary is_mythical is_ultra_beast is_paradox
in_bag auth_tag_names gl_rank gl_pct gl_stage ul_rank ul_pct ul_stage
ll_rank cull_decision_v9 cull_reason_v9
""".split())
print("=== DELTA vs existing 47-col doc ===")
print("In CORRECTED but MISSING from existing doc (doc BUG -> would be wrongly dropped):")
print('  ', sorted(KEEP - existing47))
print("In existing doc but NOT in my corrected read-set (candidate over-keeps):")
print('  ', sorted(existing47 - KEEP))

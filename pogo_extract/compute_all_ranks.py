if __name__ != '__main__':
    raise ImportError("compute_all_ranks.py is a SCRIPT, not a module: importing it opens pokemon.db relative to the CWD, re-ranks every in_bag row and commits. Import CPM from cpm_table instead.")
"""Compute GL/UL ranks for all in-bag pokemon. Store best rank across evolution chain.

FIXES APPLIED:
- Level cap = 50 (idx 98), not 51. Confirmed by Perrserker UL match.
- Complete FORM_OVERRIDES from form_overrides_complete.py.
"""
import json, sqlite3, math, time
from form_overrides_complete import FORM_OVERRIDES

# MAX_LEVEL_IDX + the CPM table + the league CP caps come from cpm_table.py, the SINGLE
# SOURCE OF TRUTH (defect D4). DO NOT paste a literal table back in here -- import it.
from cpm_table import MAX_LEVEL_IDX, LL_CAP, GL_CAP, UL_CAP, cpm_list

with open('pvpoke_gamemaster.json') as f:
    gm = json.load(f)
pokemon_db = {p['speciesId']: p for p in gm['pokemon']}

CPM = cpm_list()

# FORM_OVERRIDES imported from form_overrides_complete.py (160 entries, all 1400 forms covered)

def to_pvpoke_id(species_name, form_code, costume=0):
    if (species_name, form_code) in FORM_OVERRIDES:
        return FORM_OVERRIDES[(species_name, form_code)]
    base = species_name.lower().replace(' ', '_').replace("'", '').replace('.', '').replace('-', '_').replace('é', 'e')
    return base

def compute_cp(ba, bd, bs, ia, idf, ista, cpm, shadow=False):
    # CP is shadow-INDEPENDENT (the 1.2x/0.833x shadow boost is COMBAT-ONLY, not in CP).
    # Do NOT apply the shadow multiplier here or shadows cap at the wrong level and
    # high-attack shadow IV-ranks are wildly wrong (fixed 2026-05-29; matches PvPoke).
    return max(10, int((ba+ia)*cpm * math.sqrt((bd+idf)*cpm) * math.sqrt((bs+ista)*cpm) / 10))

def stat_product(ba, bd, bs, ia, idf, ista, cpm, shadow=False):
    am = 1.2 if shadow else 1.0; dm = 5/6 if shadow else 1.0
    return (ba+ia)*cpm*am * (bd+idf)*cpm*dm * math.floor((bs+ista)*cpm)

def find_max_idx(ba, bd, bs, ia, idf, ista, cap, shadow=False):
    for i in range(MAX_LEVEL_IDX, -1, -1):
        if compute_cp(ba, bd, bs, ia, idf, ista, CPM[i], shadow) <= cap:
            return i
    return -1

def all_combos_sorted(ba, bd, bs, cap, shadow=False):
    """Return list of 4096 stat products sorted desc."""
    sps = []
    for a in range(16):
        for de in range(16):
            for s in range(16):
                idx = find_max_idx(ba, bd, bs, a, de, s, cap, shadow)
                if idx >= 0:
                    # find_max_idx scans down from MAX_LEVEL_IDX, so idx is always in
                    # [-1, MAX_LEVEL_IDX]; the old `idx <= MAX_LEVEL_IDX else CPM[MAX_LEVEL_IDX]`
                    # ternary was unreachable dead code. (lockdown 2026-09-02)
                    cpm = CPM[idx]
                    sps.append(stat_product(ba, bd, bs, a, de, s, cpm, shadow))
                else:
                    sps.append(0)
    sorted_sp = sorted(sps, reverse=True)
    return sps, sorted_sp

# Pre-compute species rankings cache: (species_id, cap, shadow) -> (sps, sorted_sp)
ranking_cache = {}
def get_rankings(species_id, cap, shadow):
    key = (species_id, cap, shadow)
    if key in ranking_cache: return ranking_cache[key]
    p = pokemon_db.get(species_id)
    if not p:
        ranking_cache[key] = None
        return None
    bs = p['baseStats']
    sps, sorted_sp = all_combos_sorted(bs['atk'], bs['def'], bs['hp'], cap, shadow)
    ranking_cache[key] = (sps, sorted_sp, bs)
    return ranking_cache[key]

def compute_rank_for_iv(species_id, ia, idf, ista, cap, shadow):
    r = get_rankings(species_id, cap, shadow)
    if r is None: return None
    sps, sorted_sp, bs = r
    iv_idx = ia*256 + idf*16 + ista
    target_sp = sps[iv_idx]
    if target_sp == 0: return None
    rank = sorted_sp.index(target_sp) + 1
    pct = target_sp / sorted_sp[0] * 100 if sorted_sp[0] else 0
    return {'rank': rank, 'pct': pct, 'sp': target_sp}

def get_evolutions(species_id):
    p = pokemon_db.get(species_id)
    if not p: return [species_id]
    chain = [species_id]
    fam = p.get('family', {})
    for evo in fam.get('evolutions', []):
        if evo not in chain:
            chain.append(evo)
            for s in get_evolutions(evo)[1:]:
                if s not in chain: chain.append(s)
    return chain

# ----
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

# Add columns
cols = {r[1] for r in c.execute('PRAGMA table_info(pokemon)').fetchall()}
new_cols = [
    ('ll_rank', 'INTEGER'), ('ll_pct', 'REAL'), ('ll_stage', 'TEXT'), ('ll_chain_ranks', 'TEXT'),
    ('gl_rank', 'INTEGER'), ('gl_pct', 'REAL'), ('gl_stage', 'TEXT'), ('gl_chain_ranks', 'TEXT'),
    ('ul_rank', 'INTEGER'), ('ul_pct', 'REAL'), ('ul_stage', 'TEXT'), ('ul_chain_ranks', 'TEXT'),
]
for col, typ in new_cols:
    if col not in cols:
        c.execute(f'ALTER TABLE pokemon ADD COLUMN {col} {typ}')
conn.commit()

rows = c.execute("""SELECT uid_hex, species_name, pokemon_id, form, fresh_costume,
    iv_atk, iv_def, iv_sta, fresh_alignment FROM pokemon WHERE in_bag=1""").fetchall()
print(f'Computing ranks for {len(rows)} pokemon...')

unknown_species = set()
done = 0
t0 = time.time()
for r in rows:
    uid_hex, sp, pid, form, costume, ia, idf, ista, align = r
    shadow = (align == 1)
    sid = to_pvpoke_id(sp, form or 0, costume or 0)
    if sid not in pokemon_db:
        # We cannot rank this specimen (its (species,form) has no gamemaster speciesId -- a
        # missing/wrong FORM_OVERRIDES entry). The old code just `continue`d, which LEFT ANY
        # PREVIOUSLY-COMPUTED RANKS IN PLACE: after an evolution or a mapping change the row
        # kept ranks belonging to a DIFFERENT form and every downstream PvP protection was
        # decided from stale numbers. NULL them instead so the state is honestly "unknown"
        # -- preflight_transfer alarms 'pvp_unknown' on a both-NULL-rank mon in the pile, so
        # unknown now means PROTECTED rather than silently mis-ranked. (lockdown 2026-09-02)
        unknown_species.add(f'{sp} f={form} -> "{sid}" (not in pvpoke gamemaster)')
        c.execute("""UPDATE pokemon SET
            ll_rank=NULL, ll_pct=NULL, ll_stage=NULL, ll_chain_ranks=NULL,
            gl_rank=NULL, gl_pct=NULL, gl_stage=NULL, gl_chain_ranks=NULL,
            ul_rank=NULL, ul_pct=NULL, ul_stage=NULL, ul_chain_ranks=NULL
            WHERE uid_hex=?""", (uid_hex,))
        continue
    chain = get_evolutions(sid)

    # For each league, find the BEST (lowest rank) across all stages
    best_ll = None; best_gl = None; best_ul = None
    ll_chain = []; gl_chain = []; ul_chain = []
    for stage_id in chain:
        ll = compute_rank_for_iv(stage_id, ia, idf, ista, LL_CAP, shadow)
        gl = compute_rank_for_iv(stage_id, ia, idf, ista, GL_CAP, shadow)
        ul = compute_rank_for_iv(stage_id, ia, idf, ista, UL_CAP, shadow)
        if ll:
            ll_chain.append(f"{stage_id}:{ll['rank']}({ll['pct']:.2f}%)")
            if best_ll is None or ll['rank'] < best_ll['rank']:
                best_ll = {**ll, 'stage': stage_id}
        if gl:
            gl_chain.append(f"{stage_id}:{gl['rank']}({gl['pct']:.2f}%)")
            if best_gl is None or gl['rank'] < best_gl['rank']:
                best_gl = {**gl, 'stage': stage_id}
        if ul:
            ul_chain.append(f"{stage_id}:{ul['rank']}({ul['pct']:.2f}%)")
            if best_ul is None or ul['rank'] < best_ul['rank']:
                best_ul = {**ul, 'stage': stage_id}

    c.execute("""UPDATE pokemon SET
        ll_rank=?, ll_pct=?, ll_stage=?, ll_chain_ranks=?,
        gl_rank=?, gl_pct=?, gl_stage=?, gl_chain_ranks=?,
        ul_rank=?, ul_pct=?, ul_stage=?, ul_chain_ranks=?
        WHERE uid_hex=?""",
        (best_ll['rank'] if best_ll else None,
         best_ll['pct']  if best_ll else None,
         best_ll['stage'] if best_ll else None,
         ';'.join(ll_chain) if ll_chain else None,
         best_gl['rank'] if best_gl else None,
         best_gl['pct']  if best_gl else None,
         best_gl['stage'] if best_gl else None,
         ';'.join(gl_chain) if gl_chain else None,
         best_ul['rank'] if best_ul else None,
         best_ul['pct']  if best_ul else None,
         best_ul['stage'] if best_ul else None,
         ';'.join(ul_chain) if ul_chain else None,
         uid_hex))
    done += 1
    if done % 500 == 0:
        elapsed = time.time() - t0
        print(f'  {done}/{len(rows)}  ({elapsed:.0f}s)')

conn.commit()
print(f'\nDone. {done} ranked.')
# LOUD, not a footnote: an unmapped (species,form) means every PvP keep axis is blind for those
# mons. Their rank columns are now NULL (see above) so preflight_transfer.py can alarm on them
# instead of releasing them un-judged.
#
# STILL exit 0 -- but the ORIGINAL justification is dead and must not be quoted again: 'enamorus'
# form 2803 IS mapped now (form_overrides_complete.py:174 -> 'enamorus_therian'), and the live bag
# has ZERO in_bag rows with gl_rank and ul_rank both NULL (re-derived 2026-09-07, 5728 rows: 0 NULL
# in gl_rank, ul_rank OR ll_rank). Nothing is unmapped today, so 'exiting would deadlock every
# pipeline run' is no longer true of anything.
#
# The exit code is nevertheless left ALONE here, because changing it would gate NOTHING: the crawl
# runs system/scripts/rank_cache.py (pogo_pipeline.py, the compute_ranks_legacy step), NOT this
# file, and rank_cache.main() likewise returns 0 on unknowns -- it does not even print this banner,
# just a plain 'Unknown species: N' count. So 'fail the pipeline on an unmapped form' is a decision
# about rank_cache.py, and making THIS script exit non-zero would only buy false confidence.
# Fix the mapping in form_overrides_complete.py to clear the banner. (lockdown 2026-09-02;
# banner re-verified against the live bag + the live pipeline 2026-09-07)
if unknown_species:
    print('\n' + '!' * 72)
    print(f'!! {len(unknown_species)} UNMAPPED (species,form) COMBO(S) -- ranks NULLed, PvP axes BLIND:')
    for u in sorted(unknown_species):
        print(f'!!   {u}')
    print('!! Add the missing entries to form_overrides_complete.py. Until then these mons carry')
    print('!! NULL gl/ul ranks and must be treated as PvP-UNKNOWN (= protected), never as "no rank".')
    print('!' * 72)
else:
    print('Unknown species (not in PvPoke): 0')
print(f'\nQuery: SELECT * FROM pokemon WHERE gl_rank IS NOT NULL ORDER BY gl_rank LIMIT 20')

# Stats
n_with_gl = c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND gl_rank IS NOT NULL').fetchone()[0]
n_top10 = c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND gl_rank<=10').fetchone()[0]
n_top100 = c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND gl_rank<=100').fetchone()[0]
ul_top100 = c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND ul_rank<=100').fetchone()[0]
print(f'\nWith GL rank: {n_with_gl}')
print(f'GL rank <=10: {n_top10}')
print(f'GL rank <=100: {n_top100}')
print(f'UL rank <=100: {ul_top100}')

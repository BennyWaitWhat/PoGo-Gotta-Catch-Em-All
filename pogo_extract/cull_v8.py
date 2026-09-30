"""V8: V7 + bump per-form retention for Scatterbug/Tandemaus/Rockruff to 2,
       and full-protect Mimikyu (778) and Blissey (242)."""
import sqlite3, json, time
_T0 = time.time()
def _tick(label): print(f"[t+{time.time()-_T0:6.2f}s] {label}")
_tick("start")
from references import (
    LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS,
    ADVENTURE_EFFECT_IDS, has_legacy_move,
)
_tick("references imported")

PROTECTED_SHINY_PIDS = {
    129, 130, 133, 134, 135, 136, 196, 197, 470, 471, 700,
    172, 25, 26, 669, 670, 671, 384, 888,
}
FULL_PROTECT_PIDS = {778, 242}  # Mimikyu, Blissey
PER_FORM_TOP2_PIDS = {664, 924, 744}  # Scatterbug, Tandemaus, Rockruff
PVP_RANK_KEEP = 15
SHINY_TOP_N = 5
PRE_EVO_TOP_N = 2
PRE_EVO_TOP2_N = 2
FINAL_TOP_N = 3
EXCLUDED_AUTO_TAGS = {'CLAUDE_TX', 'Traded'}

def star(t): return 4 if t >= 45 else 3 if t >= 37 else 2 if t >= 30 else 1 if t >= 23 else 0

with open('pvpoke_gamemaster.json') as f:
    gm = json.load(f)
_tick(f"pvpoke_gamemaster.json loaded ({len(gm['pokemon'])} entries)")
final_form_pids = set()
non_final_pids = set()
for p in gm['pokemon']:
    pid = p.get('dex', 0)
    fam = p.get('family', {})
    if not fam.get('evolutions'):
        final_form_pids.add(pid)
    else:
        non_final_pids.add(pid)
_tick("final/non-final pid sets built")

def base_untouchable(p, xxl_top3_uids):
    rs = []
    if p['is_hundo']: rs.append('hundo')
    if p['is_zero']: rs.append('nundo')
    if p['is_lucky']:
        owner = (p['original_owner_name'] or '').lower()
        if owner in ('florandez', 'ethanmateovz') or not owner:
            rs.append(f'lucky_from_{owner or "unknown"}')
    if p['is_best_buddy']: rs.append('best_buddy')
    if p['is_deployed']: rs.append('deployed_in_gym')
    if (p['fresh_alignment'] or 0) == 1: rs.append('shadow')
    elif (p['fresh_alignment'] or 0) == 2: rs.append('purified')
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
    return rs

def main():
    conn = sqlite3.connect('pokemon.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    cols = {r[1] for r in c.execute('PRAGMA table_info(pokemon)').fetchall()}
    if 'cull_decision_v8' not in cols: c.execute('ALTER TABLE pokemon ADD COLUMN cull_decision_v8 TEXT')
    if 'cull_reason_v8' not in cols: c.execute('ALTER TABLE pokemon ADD COLUMN cull_reason_v8 TEXT')
    conn.commit()
    _tick("schema ensured")
    _q = time.time()
    rows = [dict(r) for r in c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()]
    _tick(f"SELECT * loaded {len(rows)} rows ({time.time()-_q:.2f}s)")
    print(f"Loaded {len(rows)}")

    _p = time.time()
    xxl_groups = {}
    for p in rows:
        if (p['pokemon_size_category'] or 0) == 5:
            key = (p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)
            xxl_groups.setdefault(key, []).append(p)
    xxl_top3_uids = set()
    for key, lst in xxl_groups.items():
        lst.sort(key=lambda x: -(x['weight_kg'] or 0))
        for p in lst[:3]: xxl_top3_uids.add(p['uid_hex'])
    _tick(f"xxl_top3 set built ({time.time()-_p:.3f}s, {len(xxl_top3_uids)} uids)")

    _p = time.time()
    keep_reasons = {}
    for p in rows:
        for r in base_untouchable(p, xxl_top3_uids):
            keep_reasons.setdefault(p['uid_hex'], []).append(r)
    _tick(f"base_untouchable pass done ({time.time()-_p:.3f}s)")

    for p in rows:
        if p['fresh_shiny'] and p['pokemon_id'] in PROTECTED_SHINY_PIDS:
            keep_reasons.setdefault(p['uid_hex'], []).append('shiny_protected_chain')
    shiny_buckets = {}
    for p in rows:
        if p['fresh_shiny'] and p['pokemon_id'] not in PROTECTED_SHINY_PIDS:
            key = (p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)
            shiny_buckets.setdefault(key, []).append(p)
    for key, lst in shiny_buckets.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst):
            s = star(p['iv_total'] or 0)
            if i < SHINY_TOP_N:
                keep_reasons.setdefault(p['uid_hex'], []).append(f'shiny_top{SHINY_TOP_N}_rank{i+1}')
            elif s >= 3:
                keep_reasons.setdefault(p['uid_hex'], []).append(f'shiny_3star+_rank{i+1}')

    species_form_buckets = {}
    for p in rows:
        if p['fresh_shiny']: continue
        if (p['fresh_costume'] or 0) != 0: continue
        key = (p['pokemon_id'], p['form'] or 0)
        species_form_buckets.setdefault(key, []).append(p)
    _p = time.time()
    for (pid, form), lst in species_form_buckets.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        is_final = pid in final_form_pids
        if is_final:
            keep_n = FINAL_TOP_N; label = 'final_top'
        elif pid in PER_FORM_TOP2_PIDS:
            keep_n = PRE_EVO_TOP2_N; label = 'preevo2_top'
        else:
            keep_n = PRE_EVO_TOP_N; label = 'preevo_top'
        for i, p in enumerate(lst[:keep_n]):
            keep_reasons.setdefault(p['uid_hex'], []).append(f'{label}{keep_n}_rank{i+1}')
    _tick(f"species/form bucket pass done ({time.time()-_p:.3f}s)")

    _p = time.time()
    keep_count = xfer_count = 0
    for p in rows:
        uid = p['uid_hex']
        reasons = keep_reasons.get(uid, [])
        if reasons:
            decision = 'KEEP'; reason_str = ';'.join(reasons[:8])
            keep_count += 1
        else:
            decision = 'TRANSFER'; reason_str = 'no_keep_rule'
            xfer_count += 1
        c.execute('UPDATE pokemon SET cull_decision_v8=?, cull_reason_v8=? WHERE uid_hex=?',
                  (decision, reason_str, uid))
    _tick(f"per-uid UPDATE loop done ({len(rows)} rows in {time.time()-_p:.2f}s = {(time.time()-_p)*1000/max(1,len(rows)):.2f}ms/row)")
    conn.commit()
    _tick("commit done")
    print(f'\nKEEP: {keep_count}  TRANSFER: {xfer_count}')

    print('\n=== Sanity (all should be 0) ===')
    PROTECTED = ','.join(str(p) for p in PROTECTED_SHINY_PIDS)
    queries = [
        ('hundo', 'is_hundo=1'), ('nundo', 'is_zero=1'),
        ('shadow', 'fresh_alignment=1'), ('purified', 'fresh_alignment=2'),
        ('gmax/dmax', 'fresh_bread_mode != 0'),
        ('costume', 'fresh_costume != 0'),
        ('loc_card', 'fresh_has_location_card=1'),
        ('badge', 'fresh_pokemon_badge != 0'),
        ('strong', 'fresh_is_strong=1'),
        ('GL top 15', 'gl_rank<=15'), ('UL top 15', 'ul_rank<=15'), ('LL top 15', 'll_rank<=15'),
        ('shiny in protected chain', f"fresh_shiny=1 AND pokemon_id IN ({PROTECTED})"),
        ('user-tagged (non-Traded)', "auth_tag_names IS NOT NULL AND auth_tag_names NOT IN ('','CLAUDE_TX','Traded')"),
        ('Mimikyu/Blissey', 'pokemon_id IN (778,242)'),
        ('lucky special', "is_lucky=1 AND lower(original_owner_name) IN ('florandez','ethanmateovz')"),
        ('traded special', "is_traded_flag_v2=1 AND lower(original_owner_name) IN ('florandez','ethanmateovz')"),
    ]
    for label, where in queries:
        n = c.execute(f"SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND cull_decision_v8='TRANSFER' AND {where}").fetchone()[0]
        marker = '!' if n > 0 else ' '
        print(f'  {marker} {label:30s}: {n}')

    print('\n=== Top transfer species ===')
    _p = time.time()
    for r in c.execute("""SELECT species_name, COUNT(*) as n FROM pokemon
                          WHERE cull_decision_v8='TRANSFER' AND in_bag=1
                          GROUP BY species_name ORDER BY n DESC LIMIT 25"""):
        print(f'  {r[0]:25s} {r[1]}')
    _tick(f"top-species GROUP BY query ({time.time()-_p:.3f}s)")

if __name__ == '__main__':
    main()
    _tick("done")

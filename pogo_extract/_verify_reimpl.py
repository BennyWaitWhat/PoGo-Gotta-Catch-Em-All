import sqlite3, json, sys
from collections import defaultdict

DB = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/pokemon.db"
TAGDIR = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/system/analysis/tagsets"

from form_overrides_complete import FORM_OVERRIDES

# ---------- load pvpoke base stats ----------
gm = json.load(open("pvpoke_gamemaster.json", encoding="utf-8"))
BS = {p['speciesId']: p['baseStats'] for p in gm['pokemon']}

def own_id(species_name, form):
    o = FORM_OVERRIDES.get((species_name, form))
    if o is not None:
        return o
    return (species_name.lower().replace(' ', '_').replace(chr(39), '')
            .replace('.', '').replace('-', '_').replace(chr(233), 'e'))

def maxcp(sid):
    b = BS.get(sid)
    if b is None:
        return None
    atk, dfn, hp = b['atk'], b['def'], b['hp']
    return int(((atk + 15) * (dfn + 15) ** 0.5 * (hp + 15) ** 0.5 * 0.84029999 ** 2) / 10)

# ---------- load rows ----------
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cols = ("uid_hex, pokemon_id, species_name, form, iv_atk, iv_def, iv_sta, iv_total, "
        "fresh_costume, fresh_bread_mode, fresh_alignment, fresh_shiny, is_hundo, is_zero, "
        "is_legendary, is_mythical, is_ultra_beast, is_paradox, "
        "adventure_effects_left, was_best_buddy_badge, fresh_is_strong, fresh_has_location_card, "
        "is_traded, is_lucky, original_owner_name, size_enum, pokemon_size_category, "
        "weight_kg, height_m, gl_rank, gl_stage, ul_rank, ul_stage")
rows = [dict(r) for r in con.execute(f"SELECT {cols} FROM pokemon WHERE in_bag=1")]
con.close()

def g(r, k):
    return r[k]

def i0(v):
    return 0 if v is None else v

# normalize None form/costume/bread to 0
for r in rows:
    r['_form'] = i0(r['form'])
    r['_cost'] = i0(r['fresh_costume'])
    r['_bread'] = i0(r['fresh_bread_mode'])
    r['_pid'] = r['pokemon_id']
    r['_ivt'] = i0(r['iv_total'])
    r['_shadow'] = (r['fresh_alignment'] == 1)
    r['_shiny'] = (r['fresh_shiny'] == 1)

KEEP = set()
reasons = defaultdict(list)
def keep(uid, why):
    KEEP.add(uid)
    reasons[uid].append(why)

# ---------- 1. variant_floor ----------
# top-3 by iv_total per (pid, form, fresh_costume, fresh_bread_mode) among non-shadow non-shiny
# gmax (bread_mode==2) -> top-4
vf = defaultdict(list)
for r in rows:
    if r['_shadow'] or r['_shiny']:
        continue
    key = (r['_pid'], r['_form'], r['_cost'], r['_bread'])
    vf[key].append(r)
for key, lst in vf.items():
    n = 4 if key[3] == 2 else 3
    lst.sort(key=lambda r: -r['_ivt'])
    for r in lst[:n]:
        keep(r['uid_hex'], 'variant_floor')

# ---------- 2. shadow_best ----------
# strongest-iv shadow per (pid, form)
sb = defaultdict(list)
for r in rows:
    if not r['_shadow']:
        continue
    sb[(r['_pid'], r['_form'])].append(r)
for key, lst in sb.items():
    lst.sort(key=lambda r: -r['_ivt'])
    keep(lst[0]['uid_hex'], 'shadow_best')

# ---------- 3. SHINY = ALL fresh_shiny ----------
for r in rows:
    if r['_shiny']:
        keep(r['uid_hex'], 'shiny')

# ---------- 4. hundo iv_total==45 ----------
for r in rows:
    if r['_ivt'] == 45:
        keep(r['uid_hex'], 'hundo')

# ---------- 5. rarity top-6 by iv per (pid,form) among legendary/mythical/UB/paradox ----------
rar = defaultdict(list)
for r in rows:
    if r['is_legendary'] or r['is_mythical'] or r['is_ultra_beast'] or r['is_paradox']:
        rar[(r['_pid'], r['_form'])].append(r)
for key, lst in rar.items():
    lst.sort(key=lambda r: -r['_ivt'])
    for r in lst[:6]:
        keep(r['uid_hex'], 'rarity')

# ---------- 6. legacy top-4 by iv per (pid,form) in legacy_accurate.json ----------
leg = json.load(open("legacy_accurate.json", encoding="utf-8"))
leg_uids = {e['uid_hex'] for e in leg}
by_uid = {r['uid_hex']: r for r in rows}
legpool = defaultdict(list)
for u in leg_uids:
    r = by_uid.get(u)
    if r is None:  # not in_bag, skip
        continue
    legpool[(r['_pid'], r['_form'])].append(r)
for key, lst in legpool.items():
    lst.sort(key=lambda r: -r['_ivt'])
    for r in lst[:4]:
        keep(r['uid_hex'], 'legacy')

# ---------- 7. xxl: top-2 wt UNION top-2 ht per (pid,form) size=5 ----------
# size column ambiguity: test both size_enum and pokemon_size_category
def xxl_set(sizecol):
    out = set()
    xx = defaultdict(list)
    for r in rows:
        if r[sizecol] == 5:
            xx[(r['_pid'], r['_form'])].append(r)
    for key, lst in xx.items():
        bywt = sorted(lst, key=lambda r: -(r['weight_kg'] or 0))
        byht = sorted(lst, key=lambda r: -(r['height_m'] or 0))
        for r in bywt[:2]:
            out.add(r['uid_hex'])
        for r in byht[:2]:
            out.add(r['uid_hex'])
    return out

xxl_se = xxl_set('size_enum')
xxl_pc = xxl_set('pokemon_size_category')
# DECISION: size_enum is NULL on many genuine size-5 rows; pokemon_size_category
# reads 5 correctly. Use pokemon_size_category as the authoritative size column.
XXLCOL = 'pokemon_size_category'
for u in xxl_pc:
    keep(u, 'xxl')

# ---------- 8. adventure ----------
ADV_PIDS = {483, 484, 646, 800, 888, 889}
for r in rows:
    if i0(r['adventure_effects_left']) > 0 or r['_pid'] in ADV_PIDS:
        keep(r['uid_hex'], 'adventure')

# ---------- 9. nundo is_zero=1 & pid!=0 ----------
for r in rows:
    if r['is_zero'] == 1 and r['_pid'] != 0:
        keep(r['uid_hex'], 'nundo')

# ---------- 10. best_buddy ----------
for r in rows:
    if r['was_best_buddy_badge'] == 1:
        keep(r['uid_hex'], 'best_buddy')

# ---------- 11. origin (traded/lucky) & owner in {ethanmateovz, florandez} ----------
ORIGIN_OWNERS = {'ethanmateovz', 'florandez'}
for r in rows:
    own = (r['original_owner_name'] or '').lower()
    if (r['is_traded'] == 1 or r['is_lucky'] == 1) and own in ORIGIN_OWNERS:
        keep(r['uid_hex'], 'origin')

# ---------- 12. mighty fresh_is_strong=1 ----------
for r in rows:
    if r['fresh_is_strong'] == 1:
        keep(r['uid_hex'], 'mighty')

# ---------- 13. location_card fresh_has_location_card=1 ----------
for r in rows:
    if r['fresh_has_location_card'] == 1:
        keep(r['uid_hex'], 'location_card')

# ---------- 14. dex_only_copy: sole owner of (pid,form) ----------
pf_count = defaultdict(int)
pf_list = defaultdict(list)
for r in rows:
    pf_count[(r['_pid'], r['_form'])] += 1
    pf_list[(r['_pid'], r['_form'])].append(r)
for key, c in pf_count.items():
    if c == 1:
        keep(pf_list[key][0]['uid_hex'], 'dex_only_copy')

# ---------- 15/16/17. gl_iv, ul_iv, pvp_spread ----------
# gl_iv: in_bag=1 (all rows are) AND iv_atk<=1 AND maxcp(gl_stage)>=1400 AND
#   ((own_id==gl_stage AND gl_rank<=5) OR (own_id!=gl_stage AND iv_def>=14 AND iv_sta>=14))
def league_iv(stage_col, rank_col, cap):
    cnt = 0
    miss_stage = set()
    for r in rows:
        if i0(r['iv_atk']) > 1:
            continue
        stage = r[stage_col]
        if stage is None:
            continue
        mc = maxcp(stage)
        if mc is None:
            miss_stage.add(stage)
            continue
        if mc < cap:
            continue
        oid = own_id(r['species_name'], r['_form'])
        rank = r[rank_col]
        if oid == stage:
            ok = (rank is not None and rank <= 5)
        else:
            ok = (i0(r['iv_def']) >= 14 and i0(r['iv_sta']) >= 14)
        if ok:
            keep(r['uid_hex'], 'gl_iv' if stage_col == 'gl_stage' else 'ul_iv')
            cnt += 1
    return cnt, miss_stage

gl_cnt, gl_miss = league_iv('gl_stage', 'gl_rank', 1400)
ul_cnt, ul_miss = league_iv('ul_stage', 'ul_rank', 2500)

# pvp_spread 0/15/15
for r in rows:
    if i0(r['iv_atk']) == 0 and i0(r['iv_def']) == 15 and i0(r['iv_sta']) == 15:
        keep(r['uid_hex'], 'pvp_spread')

# ============ TRANSFER ============
inbag = {r['uid_hex'] for r in rows}
my_transfer = inbag - KEEP

# load expected transfer
exp = set()
with open(f"{TAGDIR}/6_Transfer.txt", encoding="utf-8") as f:
    for ln in f:
        s = ln.strip()
        if s:
            exp.add(s)

only_mine = my_transfer - exp   # I transfer, they keep
only_exp = exp - my_transfer    # they transfer, I keep

print("=== SIZES ===")
print("in_bag:", len(inbag), "KEEP:", len(KEEP), "MY_TRANSFER:", len(my_transfer), "EXP_TRANSFER:", len(exp))
print("gl_iv kept:", gl_cnt, "ul_iv kept:", ul_cnt)
print("gl_miss_stage:", gl_miss, "ul_miss_stage:", ul_miss)
print("xxl size_enum count:", len(xxl_se), "pokemon_size_category count:", len(xxl_pc), "diff:", len(xxl_se ^ xxl_pc))
print()
print("=== SYMMETRIC DIFF ===")
print("only_mine (I transfer / they KEEP):", len(only_mine))
print("only_exp  (they transfer / I KEEP):", len(only_exp))
print("symmetric_difference:", len(only_mine) + len(only_exp))

# build detail for each diff
def detail(uid, side):
    r = by_uid.get(uid)
    if r is None:
        return f"{uid} [{side}] NOT IN BAG"
    why = ','.join(reasons.get(uid, [])) or '(no keep reason)'
    return (f"{r['species_name']}(pid{r['_pid']},f{r['_form']}) iv={r['_ivt']} "
            f"atk/def/sta={r['iv_atk']}/{r['iv_def']}/{r['iv_sta']} "
            f"shadow={int(r['_shadow'])} shiny={int(r['_shiny'])} cost={r['_cost']} bread={r['_bread']} "
            f"glr={r['gl_rank']}/{r['gl_stage']} ulr={r['ul_rank']}/{r['ul_stage']} "
            f"[{side}] mykeep_reason={why}")

print()
print("=== ONLY MINE (I say transfer, tagset KEEPs) ===")
for u in sorted(only_mine):
    print(" ", detail(u, "I->T"))
print()
print("=== ONLY EXP (tagset transfers, I KEEP) ===")
for u in sorted(only_exp):
    print(" ", detail(u, "EXP->T,I->K"))

# Tie-break analysis: for each diff, is there an equal-iv sibling in same bucket on the other side?
def tiebreak_check(uid):
    """Return True if this disagreement is plausibly an equal-iv tie within its variant_floor/shadow/rarity/legacy/xxl bucket."""
    r = by_uid[uid]
    # check variant_floor bucket
    key = (r['_pid'], r['_form'], r['_cost'], r['_bread'])
    sibs = vf.get(key, [])
    ivs = sorted({s['_ivt'] for s in sibs}, reverse=True)
    n = 4 if key[3] == 2 else 3
    if len(sibs) > n:
        # cutoff iv is the nth value
        cutoff = sorted([s['_ivt'] for s in sibs], reverse=True)[n-1]
        if r['_ivt'] == cutoff:
            return f"vf-cutoff-tie(iv={cutoff})"
    # shadow_best bucket: single pick by max iv_total; tie if another shadow shares max iv
    if r['_shadow']:
        skey = (r['_pid'], r['_form'])
        sl = sb.get(skey, [])
        if len(sl) > 1:
            maxiv = max(s['_ivt'] for s in sl)
            if r['_ivt'] == maxiv and sum(1 for s in sl if s['_ivt'] == maxiv) > 1:
                return f"shadow_best-tie(iv={maxiv})"
    # rarity bucket
    rkey = (r['_pid'], r['_form'])
    if rkey in rar and len(rar[rkey]) > 6:
        cutoff = sorted([s['_ivt'] for s in rar[rkey]], reverse=True)[5]
        if r['_ivt'] == cutoff:
            return f"rarity-cutoff-tie(iv={cutoff})"
    # legacy bucket
    if rkey in legpool and len(legpool[rkey]) > 4:
        cutoff = sorted([s['_ivt'] for s in legpool[rkey]], reverse=True)[3]
        if r['_ivt'] == cutoff:
            return f"legacy-cutoff-tie(iv={cutoff})"
    # xxl: weight/height ties
    if r[XXLCOL] == 5:
        xkey = (r['_pid'], r['_form'])
        lst = [x for x in rows if x[XXLCOL]==5 and (x['_pid'],x['_form'])==xkey]
        if len(lst) > 2:
            wts = sorted([(x['weight_kg'] or 0) for x in lst], reverse=True)
            hts = sorted([(x['height_m'] or 0) for x in lst], reverse=True)
            if (r['weight_kg'] or 0) == wts[1] or (r['height_m'] or 0) == hts[1]:
                return "xxl-cutoff-tie"
    return None

print()
print("=== TIE-BREAK CLASSIFICATION ===")
all_diffs = sorted(only_mine | only_exp)
non_tie = []
for u in all_diffs:
    tb = tiebreak_check(u)
    r = by_uid[u]
    side = "I->T" if u in only_mine else "EXP->T"
    if tb:
        print(f"  TIE  {r['species_name']} iv={r['_ivt']} [{side}] {tb}")
    else:
        non_tie.append(u)
        print(f"  REAL {r['species_name']} iv={r['_ivt']} [{side}] reasons={reasons.get(u,[])}")
print()
print("NON-TIE (real) diffs:", len(non_tie))

import json, math, sys, statistics
sys.path.insert(0, 'pokegenie_work')
from _cpm_probe import best_for_cap

gm = json.load(open(r'pogo_extract/pvpoke_gamemaster.json'))
bydex = {}
for p in gm['pokemon']:
    bydex.setdefault(p['dex'], []).append(p)

def resolve(pokeId):
    if not pokeId:
        return None
    parts = str(pokeId).split('_')
    try:
        dx = int(parts[0])
    except Exception:
        return None
    region = parts[1] if len(parts) > 1 else None
    cands = bydex.get(dx, [])
    if not cands:
        return None
    if region:
        for c in cands:
            if region.lower() in c['speciesId'].lower():
                return c
    for c in cands:
        if c['speciesId'] == c['speciesName'].lower().replace(' ', '_').replace('.', '').replace("'", ''):
            return c
    return sorted(cands, key=lambda c: len(c['speciesId']))[0]

# cache: (speciesId, cap, maxlevel) -> (all_sps_sorted_desc, rank1_sp, best_per_iv dict)
CACHE = {}
def species_table(p, cap, maxlevel):
    key = (p['speciesId'], cap, maxlevel)
    if key in CACHE:
        return CACHE[key]
    bs = p['baseStats']
    per_iv = {}
    for ia in range(16):
        for idd in range(16):
            for iss in range(16):
                b = best_for_cap(bs['atk'], bs['def'], bs['hp'], ia, idd, iss, cap, maxlevel)
                per_iv[(ia, idd, iss)] = b
    sps = sorted((v['sp'] for v in per_iv.values()), reverse=True)
    rank1 = sps[0]
    CACHE[key] = (sps, rank1, per_iv)
    return CACHE[key]

def rank_of(sp, sps_desc):
    # rank = 1 + number strictly greater
    lo = 0
    # sps_desc descending; count strictly greater
    import bisect
    # convert to ascending for bisect
    # number strictly greater = total - bisect_right(ascending, sp)
    asc = sps_desc[::-1]
    import bisect as bs2
    greater = len(asc) - bs2.bisect_right(asc, sp)
    return greater + 1

d = json.load(open(r'pokegenie_work/extracted/scan_data.json'))

LEAGUE = {0: (1500, 50), 1: (2500, 50), 2: (500, 50)}

def check(keyname, league, limit=None):
    ok_lvl = ok_cp = ok_prod = ok_rank = 0
    tot = 0
    prod_err = []
    rank_exact = 0
    fails = []
    cap, maxlevel = LEAGUE[league]
    for e in d:
        g = e.get(keyname)
        if not g or g.get('status') != 1:
            continue
        if not e.get('singleIVComb'):
            continue
        sc = e.get('singleValidIvComb') or {}
        if 'attackIV' not in sc:
            continue
        p = resolve(g.get('pokeId'))
        if not p:
            continue
        iv = (sc['attackIV'], sc['defenseIV'], sc['staminaIV'])
        sps, rank1, per_iv = species_table(p, cap, maxlevel)
        b = per_iv[iv]
        if not b:
            continue
        tot += 1
        enc = round((b['level'] - 1) * 2)
        prod = round(b['sp'] / rank1 * 10000)
        rk = rank_of(b['sp'], sps)
        rankavg = (rk - 1) / (len(sps) - 1)  # /4095
        if enc == g['levelLower']:
            ok_lvl += 1
        if b['cp'] == g['maxCP']:
            ok_cp += 1
        if prod == g['prodLower']:
            ok_prod += 1
        else:
            prod_err.append(abs(prod - g['prodLower']))
        if abs(rankavg - g['rankAvg']) < 1e-9:
            rank_exact += 1
        else:
            if len(fails) < 8:
                fails.append((p['speciesName'], iv, 'enc', enc, g['levelLower'],
                              'cp', b['cp'], g['maxCP'], 'prod', prod, g['prodLower'],
                              'rank', round(rankavg, 6), g['rankAvg']))
        if limit and tot >= limit:
            break
    print(f"=== {keyname} (league {league}, cap {cap}) ===  N={tot}")
    print(f"  level match: {ok_lvl}/{tot} ({100*ok_lvl/tot:.1f}%)")
    print(f"  maxCP match: {ok_cp}/{tot} ({100*ok_cp/tot:.1f}%)")
    print(f"  prod  match: {ok_prod}/{tot} ({100*ok_prod/tot:.1f}%)  mean|err| {statistics.mean(prod_err) if prod_err else 0:.2f}  max {max(prod_err) if prod_err else 0}")
    print(f"  rankAvg exact: {rank_exact}/{tot} ({100*rank_exact/tot:.1f}%)")
    for f in fails:
        print("   FAIL", f)

check('pvpGreatResult', 0)
check('pvpUltraResult', 1)
check('pvpLittleResult', 2)

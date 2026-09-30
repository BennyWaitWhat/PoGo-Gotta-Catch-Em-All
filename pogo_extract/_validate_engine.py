import json, math, sqlite3
from collections import Counter

DB = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\pokemon.db"
GM = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\pvpoke_gamemaster.json"
GT = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pokegenie_work\extracted\scan_data.json"

gm = json.load(open(GM, encoding="utf-8"))
byid = {p["speciesId"]: p for p in gm["pokemon"]}
bydex = {}
for p in gm["pokemon"]:
    bydex.setdefault(p["dex"], p)

# ---- Build canonical CPM table from DB (authoritative for this account) ----
# effective cpm = cp_multiplier + additional_cpm ; pick the modal value per level
c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
votes = {}
for r in c.execute("select level, cp_multiplier, additional_cpm from pokemon where in_bag=1 and cp_multiplier is not null"):
    lv = r["level"]; add = r["additional_cpm"] or 0.0
    eff = round(r["cp_multiplier"] + add, 8)
    votes.setdefault(lv, Counter())[eff] += 1
CPM = {}
for lv, ctr in votes.items():
    CPM[lv] = ctr.most_common(1)[0][0]

# Fill standard half-levels we might need for PvP sweep using known constant table
STD = {
1.0:0.094,1.5:0.135137432,2.0:0.16639787,2.5:0.192650919,3.0:0.21573247,3.5:0.236572661,
4.0:0.25572005,4.5:0.273530381,5.0:0.29024988,5.5:0.306057377,6.0:0.3210876,6.5:0.335445036,
7.0:0.34921268,7.5:0.362457751,8.0:0.37523559,8.5:0.387592406,9.0:0.39956728,9.5:0.411193551,
10.0:0.42250001,10.5:0.432926419,11.0:0.44310755,11.5:0.453059958,12.0:0.46279839,12.5:0.472336083,
13.0:0.48168495,13.5:0.490855813,14.0:0.49985844,14.5:0.508701765,15.0:0.51739395,15.5:0.525942511,
16.0:0.53435433,16.5:0.542635767,17.0:0.55079269,17.5:0.558830576,18.0:0.56675452,18.5:0.574629862,
19.0:0.58227891,19.5:0.589887917,20.0:0.59740001,20.5:0.604818814,21.0:0.61215729,21.5:0.619399365,
22.0:0.62656713,22.5:0.633644533,23.0:0.64065295,23.5:0.647576426,24.0:0.65443563,24.5:0.661214806,
25.0:0.667934,25.5:0.674577537,26.0:0.68116492,26.5:0.687680648,27.0:0.69414365,27.5:0.700538673,
28.0:0.70688421,28.5:0.713164996,29.0:0.71939909,29.5:0.725563749,30.0:0.7317,30.5:0.734741009,
31.0:0.73776948,31.5:0.740796879,32.0:0.74378943,32.5:0.746781211,33.0:0.74976104,33.5:0.752729087,
34.0:0.75568551,34.5:0.758632576,35.0:0.76156384,35.5:0.764484794,36.0:0.76739717,36.5:0.770297266,
37.0:0.7731865,37.5:0.776064962,38.0:0.77893275,38.5:0.781779565,39.0:0.78463697,39.5:0.787473578,
40.0:0.79030001,40.5:0.792803968,41.0:0.79530001,41.5:0.797803,42.0:0.8003,42.5:0.802799,
43.0:0.8053,43.5:0.807799,44.0:0.81030,44.5:0.812799,45.0:0.81530,45.5:0.817799,
46.0:0.82030,46.5:0.822799,47.0:0.82530,47.5:0.827799,48.0:0.83030,48.5:0.832799,
49.0:0.83530,49.5:0.837799,50.0:0.84030,
}
# cross-check DB-derived vs STD at integer levels
mism = []
for lv, v in sorted(CPM.items()):
    if lv in STD and abs(STD[lv]-v) > 1e-6:
        mism.append((lv, v, STD[lv]))
print("CPM DB-vs-STD mismatches (integer/half):", mism[:20])
# Use STD as the working table (clean), but report agreement
WORK = STD

LEVELS = [round(1.0 + 0.5*i, 1) for i in range(99)]  # 1.0 .. 50.0

def cp(base, ivs, lvl):
    a = base["atk"] + ivs[0]; d = base["def"] + ivs[1]; s = base["hp"] + ivs[2]
    m = WORK[lvl]
    return max(10, int((a * math.sqrt(d) * math.sqrt(s) * m*m) / 10))

def hp(base, sta_iv, lvl):
    return max(10, int((base["hp"] + sta_iv) * WORK[lvl]))

def ivpct(ivs):
    return (ivs[0]+ivs[1]+ivs[2]) / 45.0

# stat product for PvP (shadow uses 1.2 atk / 0.83333 def shadow mult? PvPoke uses raw stats
# for ranking; shadow bonus applies in battle sim, but rank% is vs same-shadow ceiling)
def stat_product(base, ivs, lvl, shadow=False):
    m = WORK[lvl]
    a = (base["atk"] + ivs[0]) * m
    d = (base["def"] + ivs[1]) * m
    s = (base["hp"] + ivs[2]) * m
    if shadow:
        a *= 1.2; d *= (1.0/1.2)
    h = int(s)
    return a * d * h

def best_under_cap(base, ivs, cap, shadow=False, lvl_cap=50.0):
    # highest stat-product reachable at or below cp cap
    best = None; bestlvl = None
    for lvl in LEVELS:
        if lvl > lvl_cap: break
        if cp(base, ivs, lvl) > cap:
            break
        sp = stat_product(base, ivs, lvl, shadow)
        if best is None or sp >= best:
            best = sp; bestlvl = lvl
    return best, bestlvl

def species_ceiling(base, cap, shadow=False):
    # max stat product over all IV combos at/under cap (rank-1 reference)
    ceil = 0.0
    for ai in range(16):
        for di in range(16):
            for si in range(16):
                sp, _ = best_under_cap(base, (ai,di,si), cap, shadow)
                if sp and sp > ceil:
                    ceil = sp
    return ceil

# floor for IV ranking in GL/UL is 0/0/0 traded? PvPoke ranks consider full 0-15 space.
def pvp_block(base, ivs, cap, shadow=False):
    sp, lvl = best_under_cap(base, ivs, cap, shadow)
    ceil = species_ceiling(base, cap, shadow)
    rank = sp/ceil if ceil else 0.0
    maxcp = cp(base, ivs, lvl) if lvl else 0
    return {"sp": sp, "lvl": lvl, "ceil": ceil, "rankPct": rank, "maxCP": maxcp}

# ----------------- VALIDATE 3 PICKS -----------------
picks = {
 "Trevenant(low-atk GL)": dict(dex=709, sid="trevenant", ivs=(0,15,15), lvl=22.0, cp=1497, sta=133, shadow=False, db_glrank=1, db_glpct=100.0, db_ulrank=8, db_ulpct=99.50495049504951),
 "Charizard(hundo)":      dict(dex=6,   sid="charizard",  ivs=(15,15,15),lvl=15.0, cp=1238, sta=103, shadow=False, db_glrank=1666, db_glpct=95.1515077827067, db_ulrank=1381, db_ulpct=96.47145609261327),
 "Venusaur(shadow)":      dict(dex=3,   sid="venusaur",  ivs=(14,14,12),lvl=13.0, cp=996,  sta=97,  shadow=True,  db_glrank=1048, db_glpct=96.18901005403785, db_ulrank=2574, db_ulpct=95.49820290635569),
}

for name, p in picks.items():
    base = byid[p["sid"]]["baseStats"]
    print("\n==============", name, base, "ivs", p["ivs"], "L", p["lvl"], "==============")
    mycp = cp(base, p["ivs"], p["lvl"])
    myhp = hp(base, p["ivs"][2], p["lvl"])
    print(f"  CP  mine={mycp}  DB/actual={p['cp']}  {'OK' if mycp==p['cp'] else 'MISMATCH'}")
    print(f"  HP  mine={myhp}  DB stamina={p['sta']}  {'OK' if myhp==p['sta'] else 'MISMATCH'}")
    print(f"  IV% mine={ivpct(p['ivs']):.6f}")
    gl = pvp_block(base, p["ivs"], 1500, p["shadow"])
    ul = pvp_block(base, p["ivs"], 2500, p["shadow"])
    print(f"  GL  rankPct mine={gl['rankPct']:.6f} (DBpct/100={p['db_glpct']/100:.6f})  bestLvl={gl['lvl']} maxCP={gl['maxCP']}")
    print(f"  UL  rankPct mine={ul['rankPct']:.6f} (DBpct/100={p['db_ulpct']/100:.6f})  bestLvl={ul['lvl']} maxCP={ul['maxCP']}")

import json
GT = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pokegenie_work\extracted\scan_data.json"
d = json.load(open(GT, encoding="utf-8"))

def find(name, ai, di, si, lvl=None):
    out=[]
    for e in d:
        if e["pokemonName"]==name and e["minAttackIV"]==ai and e["minDefenseIV"]==di and e["minStaminaIV"]==si and e.get("singleIVComb"):
            if lvl is None or e["pokemonLevelLower"]==lvl:
                out.append(e)
    return out

# 1) Trevenant 0/15/15 (low-atk GL). 2) Charizard 15/15/15 hundo. 3) any Shadow Venusaur-like (shadowPokemon==1)
for q in [("Trevenant",0,15,15),("Charizard",15,15,15)]:
    res=find(*q)
    print("\n### GT", q, "->", len(res), "matches")
    if res:
        e=res[0]
        for k in ["pokemonNumber","cp","hp","dust","pokemonLevelLower","ivPercentage","maxCPLower","maxCPUpper","maxHPLower","shadowPokemon","quickMove","chargeMove"]:
            print("  ",k,"=",e.get(k))
        g=e.get("pvpGreatResult"); u=e.get("pvpUltraResult")
        if g: print("   GL:", {k:g[k] for k in ["rankAvg","maxCP","levelLower","prodLower","dustCostLower","candyCostLower","xlCandyCostLower","status","shadow"]})
        if u: print("   UL:", {k:u[k] for k in ["rankAvg","maxCP","levelLower","prodLower","dustCostLower","candyCostLower","xlCandyCostLower","status","shadow"]})

# shadow example: any shadow with a pvp block
shad=[e for e in d if e.get("shadowPokemon")==1 and e.get("singleIVComb") and e.get("pvpGreatResult")]
print("\n### GT shadow examples:", len(shad))
for e in shad[:3]:
    g=e["pvpGreatResult"]
    print("  ", e["pokemonName"], "IV", (e["minAttackIV"],e["minDefenseIV"],e["minStaminaIV"]),"L",e["pokemonLevelLower"],
          "shadowPokemon",e["shadowPokemon"], "| GL shadow flag", g.get("shadow"), "rankAvg", round(g["rankAvg"],4), "maxCP", g["maxCP"])

# Dust-by-level table from GT (level -> dust) to confirm dust formula
dust_by_lvl={}
for e in d:
    lv=e.get("pokemonLevelLower"); du=e.get("dust")
    if lv and du is not None:
        dust_by_lvl.setdefault(lv,set()).add(du)
print("\n### dust by level (sample):")
for lv in sorted(dust_by_lvl, key=lambda x: float(x))[:60]:
    vals=dust_by_lvl[lv]
    if len(vals)==1: print("  L",lv,"->",list(vals)[0])
    else: print("  L",lv,"-> MULTI",sorted(vals))

import json, sqlite3, os

DB = "C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/pokemon.db"
TAGDIR = "C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/system/analysis/tagsets"
GM = "C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/pvpoke_gamemaster.json"

# --- maxcp ---
d = json.load(open(GM))
BS = {p['speciesId']: p['baseStats'] for p in d['pokemon']}
def maxcp(sid):
    b = BS.get(sid)
    if not b:
        return None
    atk, df, hp = b['atk'], b['def'], b['hp']
    return int(((atk+15)*(df+15)**0.5*(hp+15)**0.5*0.84029999**2)/10)

# --- load tag files (strings verbatim) ---
def load(name):
    p = os.path.join(TAGDIR, name)
    s = set()
    with open(p) as f:
        for line in f:
            t = line.strip()
            if t:
                s.add(t)
    return s

transfer = load("6_Transfer.txt")
ul_iv = load("1_UL_IV.txt")
print("6_Transfer.txt lines:", len(transfer))
print("1_UL_IV.txt lines:", len(ul_iv))

# --- query DB ---
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()
rows = cur.execute("""
  SELECT uid_hex, in_bag, gl_rank, gl_stage, ul_rank, ul_stage,
         iv_atk, iv_def, iv_sta, is_shiny, species_name, pokemon_id
  FROM pokemon WHERE in_bag=1
""").fetchall()
print("in_bag=1 total:", len(rows))

# --- PvP criteria ---
def qualifies(r):
    reasons = []
    gl_rank = r['gl_rank']; gl_stage = r['gl_stage']
    ul_rank = r['ul_rank']; ul_stage = r['ul_stage']
    a, dd, s = r['iv_atk'], r['iv_def'], r['iv_sta']
    # GL: gl_rank<=5 AND maxcp(gl_stage)>=1400
    if gl_rank is not None and gl_rank <= 5 and gl_stage:
        mc = maxcp(gl_stage)
        if mc is not None and mc >= 1400:
            reasons.append(f"GL r{gl_rank} {gl_stage} maxcp={mc}")
    # UL: ul_rank<=5 AND maxcp(ul_stage)>=2400
    if ul_rank is not None and ul_rank <= 5 and ul_stage:
        mc = maxcp(ul_stage)
        if mc is not None and mc >= 2400:
            reasons.append(f"UL r{ul_rank} {ul_stage} maxcp={mc}")
    # rank-1 IV spread 0/15/15
    if a == 0 and dd == 15 and s == 15:
        reasons.append("IV 0/15/15")
    return reasons

qualified = []
for r in rows:
    rs = qualifies(r)
    if rs:
        qualified.append((r, rs))

print("PvP-qualified in_bag mons:", len(qualified))

# --- count how many qualified are in transfer (MUST be 0) ---
offenders = []
for r, rs in qualified:
    if r['uid_hex'] in transfer:
        offenders.append((r, rs))

print("=== OFFENDERS in 6_Transfer.txt:", len(offenders), "===")
for r, rs in offenders:
    print(f"  {r['uid_hex']} {r['species_name']} shiny={r['is_shiny']} | {'; '.join(rs)}")

# Also flag: any shiny among offenders is doubly wrong (all shinies kept)
shiny_off = [o for o in offenders if o[0]['is_shiny']]
print("  (of which shiny:", len(shiny_off), ")")

# --- Charizard UL rank-1 ~0/13/15 check ---
print("\n=== Charizard UL rank-1 check ===")
chz = cur.execute("""
  SELECT uid_hex, in_bag, gl_rank, ul_rank, ul_stage, iv_atk, iv_def, iv_sta, is_shiny, species_name
  FROM pokemon
  WHERE species_name LIKE '%harizard%' OR ul_stage='charizard' OR gl_stage='charizard'
""").fetchall()
print("Charizard-ish rows found:", len(chz))
for r in chz:
    print(f"  {r['uid_hex']} {r['species_name']} in_bag={r['in_bag']} ul_rank={r['ul_rank']} ul_stage={r['ul_stage']} IV={r['iv_atk']}/{r['iv_def']}/{r['iv_sta']} shiny={r['is_shiny']} maxcp(ul)={maxcp(r['ul_stage']) if r['ul_stage'] else None}")
    print(f"     in_transfer={r['uid_hex'] in transfer}  in_1_UL_IV={r['uid_hex'] in ul_iv}")

# Identify the specific UL rank-1 ~0/13/15 charizard
target = [r for r in chz if r['ul_rank']==1 and r['iv_atk']==0 and r['iv_def']==13 and r['iv_sta']==15]
print("\nExact UL r1 0/13/15 charizard matches:", len(target))
for r in target:
    print(f"  {r['uid_hex']} in_transfer={r['uid_hex'] in transfer} in_1_UL_IV={r['uid_hex'] in ul_iv}")

# Save offenders json for verdict
result = {
    "transfer_count": len(transfer),
    "ul_iv_count": len(ul_iv),
    "in_bag_total": len(rows),
    "pvp_qualified": len(qualified),
    "offenders_in_transfer": len(offenders),
    "offender_uids": [o[0]['uid_hex'] for o in offenders],
}
print("\nSUMMARY:", json.dumps(result))
con.close()

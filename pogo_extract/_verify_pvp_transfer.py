import json, sqlite3, os

ROOT = "C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
DB = os.path.join(ROOT, "pokemon.db")
GM = os.path.join(ROOT, "pvpoke_gamemaster.json")
TAGDIR = os.path.join(ROOT, "system/analysis/tagsets")

# --- load gamemaster baseStats per speciesId ---
gm = json.load(open(GM))
BS = {p['speciesId']: p['baseStats'] for p in gm['pokemon']}

def maxcp(sid):
    """Max CP at level 51 (cpm 0.84029999) with the given speciesId's base stats,
    assuming perfect 15/15/15 IVs added to base."""
    b = BS.get(sid)
    if b is None:
        return None
    atk = b['atk']; dfn = b['def']; hp = b['hp']
    return int(((atk + 15) * (dfn + 15) ** 0.5 * (hp + 15) ** 0.5 * 0.84029999 ** 2) / 10)

# --- read 6_Transfer.txt: uid_hex strings verbatim, compare as strings ---
def read_tagfile(name):
    p = os.path.join(TAGDIR, name)
    s = set()
    with open(p, 'r', encoding='utf-8') as f:
        for line in f:
            t = line.strip()
            if t:
                s.add(t)   # verbatim, no int(), no reformat
    return s

transfer = read_tagfile("6_Transfer.txt")
ul_iv = read_tagfile("1_UL_IV.txt")
gl_iv = read_tagfile("1_GL_IV.txt")
print(f"6_Transfer.txt lines: {len(transfer)}")
print(f"1_UL_IV.txt lines: {len(ul_iv)}")
print(f"1_GL_IV.txt lines: {len(gl_iv)}")

# --- query DB for all in_bag=1 mons w/ the criteria inputs ---
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()
cur.execute("""
  SELECT uid_hex, species_name, iv_atk, iv_def, iv_sta,
         gl_rank, gl_stage, ul_rank, ul_stage
  FROM pokemon
  WHERE in_bag=1
""")
rows = cur.fetchall()
print(f"in_bag=1 rows: {len(rows)}")

# --- independently find every PvP-valuable mon (ANY of a/b/c) ---
pvp_valuable = []   # list of dicts
for r in rows:
    uid = r['uid_hex']
    atk = r['iv_atk']; dfn = r['iv_def']; sta = r['iv_sta']
    glr = r['gl_rank']; uls = r['ul_stage']; uls_r = r['ul_rank']
    gl_stage = r['gl_stage']; ul_stage = r['ul_stage']

    reasons = []

    # (a) gl_rank<=5 AND maxcp(gl_stage)>=1400
    if glr is not None and glr <= 5 and gl_stage:
        mc = maxcp(gl_stage)
        if mc is not None and mc >= 1400:
            reasons.append(f"GL(rank={glr},maxcp[{gl_stage}]={mc}>=1400)")

    # (b) ul_rank<=5 AND maxcp(ul_stage)>=2400
    if uls_r is not None and uls_r <= 5 and ul_stage:
        mc = maxcp(ul_stage)
        if mc is not None and mc >= 2400:
            reasons.append(f"UL(rank={uls_r},maxcp[{ul_stage}]={mc}>=2400)")

    # (c) rank-1 IV: atk=0 & def=15 & sta=15
    if atk == 0 and dfn == 15 and sta == 15:
        reasons.append("PvP-IV(0/15/15)")

    if reasons:
        pvp_valuable.append({
            'uid': uid,
            'species': r['species_name'],
            'iv': f"{atk}/{dfn}/{sta}",
            'gl_rank': glr,
            'gl_stage': gl_stage,
            'gl_maxcp': maxcp(gl_stage) if gl_stage else None,
            'ul_rank': uls_r,
            'ul_stage': ul_stage,
            'ul_maxcp': maxcp(ul_stage) if ul_stage else None,
            'reasons': reasons,
        })

print(f"\nTotal independently-identified PvP-valuable in_bag mons: {len(pvp_valuable)}")

# --- how many of those are in 6_Transfer.txt (string compare) ---
offenders = [m for m in pvp_valuable if m['uid'] in transfer]
print(f"PvP-valuable mons ALSO in 6_Transfer.txt (MUST be 0): {len(offenders)}")
print("="*80)
if offenders:
    for m in offenders:
        print(f"OFFENDER uid={m['uid']} {m['species']} IV={m['iv']} "
              f"gl_rank={m['gl_rank']} gl_maxcp={m['gl_maxcp']} "
              f"ul_rank={m['ul_rank']} ul_maxcp={m['ul_maxcp']} | {';'.join(m['reasons'])}")
else:
    print("No offenders: zero PvP-valuable mons in transfer.")
print("="*80)

con.close()

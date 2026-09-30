import sqlite3, os
ROOT = "C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
DB = os.path.join(ROOT, "pokemon.db")
TAGDIR = os.path.join(ROOT, "system/analysis/tagsets")

def read_tagfile(name):
    s=set()
    with open(os.path.join(TAGDIR,name),encoding='utf-8') as f:
        for line in f:
            t=line.strip()
            if t: s.add(t)
    return s

transfer = read_tagfile("6_Transfer.txt")
ul_iv = read_tagfile("1_UL_IV.txt")

con=sqlite3.connect(DB); con.row_factory=sqlite3.Row; cur=con.cursor()
# Find UL rank-1 Charizards in bag
cur.execute("""
  SELECT uid_hex, species_name, iv_atk, iv_def, iv_sta, gl_rank, gl_stage, ul_rank, ul_stage
  FROM pokemon
  WHERE in_bag=1 AND ul_rank=1 AND species_name LIKE '%harizard%'
""")
rows=cur.fetchall()
print(f"UL rank-1 Charizard candidates in bag: {len(rows)}")
for r in rows:
    uid=r['uid_hex']
    in_transfer = uid in transfer
    in_ul_iv = uid in ul_iv
    print(f"  uid={uid} {r['species_name']} IV={r['iv_atk']}/{r['iv_def']}/{r['iv_sta']} "
          f"ul_rank={r['ul_rank']} ul_stage={r['ul_stage']} gl_rank={r['gl_rank']}")
    print(f"     in 6_Transfer.txt={in_transfer} (must be False)  |  in 1_UL_IV.txt={in_ul_iv} (must be True)")

# Also: any Charizard with ul_rank=1 near 0/13/15 specifically
print("\n--- All in-bag Charizard with ~0/13/15 IV ---")
cur.execute("""
  SELECT uid_hex, species_name, iv_atk, iv_def, iv_sta, ul_rank, ul_stage, gl_rank
  FROM pokemon
  WHERE in_bag=1 AND species_name LIKE '%harizard%' AND iv_atk=0 AND iv_def=13 AND iv_sta=15
""")
for r in cur.fetchall():
    uid=r['uid_hex']
    print(f"  uid={uid} {r['species_name']} IV={r['iv_atk']}/{r['iv_def']}/{r['iv_sta']} "
          f"ul_rank={r['ul_rank']} ul_stage={r['ul_stage']} | transfer={uid in transfer} ul_iv={uid in ul_iv}")
con.close()

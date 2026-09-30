"""
Compute the protected uid_hex set for keep-rule "shadow" of the finalized PoGo keep policy.
READ-ONLY. No device / no Frida.

Rule (KEEP_POLICY.md section 2):
  Shadows only (fresh_alignment == 1, in_bag == 1). Keep the UNION of:
    (a) the single strongest by iv_total (tiebreak cp) per (pokemon_id, form).
    (b) any shadow with gl_rank<=10 or ul_rank<=10 whose RANKED shadow form reaches the
        league cap, where:
          maxCP(speciesId)@L50 = floor((atk+15)*sqrt(def+15)*sqrt(hp+15)*0.84029999^2/10)
          baseStats from pvpoke_gamemaster.json (pokemon[].baseStats)
          shadow forms use "<speciesId>_shadow"
          relevant stage = gl_stage for a GL top-10 qualifier, ul_stage for a UL top-10 qualifier
          require GL maxcp>=1400 (1500-cap league) / UL maxcp>=2400 (2500-cap league)
"""
import sqlite3, math, json, os

BASE = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
DB = os.path.join(BASE, "pokemon.db")
GM = os.path.join(BASE, "pvpoke_gamemaster.json")
OUTDIR = os.path.join(BASE, "system", "analysis", "policy_sets")
OUT = os.path.join(OUTDIR, "shadow.txt")

gm = json.load(open(GM, encoding="utf-8"))
BASESTATS = {p["speciesId"]: p["baseStats"] for p in gm["pokemon"]}

def maxcp(species_id):
    bs = BASESTATS.get(species_id)
    if bs is None:
        return None
    atk = bs["atk"] + 15
    df  = bs["def"] + 15
    hp  = bs["hp"]  + 15
    return math.floor(atk * math.sqrt(df) * math.sqrt(hp) * (0.84029999 ** 2) / 10)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()
cur.execute("""
    SELECT uid_hex, pokemon_id, species_name, form, iv_total, cp,
           gl_rank, ul_rank, gl_stage, ul_stage
    FROM pokemon
    WHERE in_bag = 1 AND fresh_alignment = 1
""")
rows = [dict(r) for r in cur.fetchall()]
con.close()

# ---- (a) single strongest by iv_total (tiebreak cp) per (pokemon_id, form) ----
best = {}  # (pid, form) -> row
for r in rows:
    key = (r["pokemon_id"], r["form"])
    cur_best = best.get(key)
    # higher iv_total wins; tiebreak higher cp; final deterministic tiebreak uid_hex
    cand = (r["iv_total"], r["cp"] if r["cp"] is not None else -1, r["uid_hex"])
    if cur_best is None:
        best[key] = r
    else:
        cb = (cur_best["iv_total"], cur_best["cp"] if cur_best["cp"] is not None else -1, cur_best["uid_hex"])
        if cand > cb:
            best[key] = r

set_a = {r["uid_hex"] for r in best.values()}

# ---- (b) top-10 GL/UL, CP-floored on the league's ranked shadow form ----
GL_FLOOR = 1400
UL_FLOOR = 2400
set_b = set()
b_detail = []
for r in rows:
    qualifies = False
    reason = None
    gl = r["gl_rank"]; ul = r["ul_rank"]
    if gl is not None and gl <= 10 and r["gl_stage"]:
        sid = r["gl_stage"] + "_shadow"
        mc = maxcp(sid)
        if mc is not None and mc >= GL_FLOOR:
            qualifies = True
            reason = f"GL rank {gl} via {sid} maxCP={mc}>={GL_FLOOR}"
    if not qualifies and ul is not None and ul <= 10 and r["ul_stage"]:
        sid = r["ul_stage"] + "_shadow"
        mc = maxcp(sid)
        if mc is not None and mc >= UL_FLOOR:
            qualifies = True
            reason = f"UL rank {ul} via {sid} maxCP={mc}>={UL_FLOOR}"
    if qualifies:
        set_b.add(r["uid_hex"])
        b_detail.append((r["species_name"], r["uid_hex"], reason))

protected = set_a | set_b

os.makedirs(OUTDIR, exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    for u in sorted(protected):
        f.write(u + "\n")

# ---- diagnostics ----
print("total shadow rows (in_bag=1, fresh_alignment=1):", len(rows))
print("distinct (pokemon_id,form) groups / set_a size:", len(set_a))
print("set_b (top-10, CP-floored) size:", len(set_b))
print("set_b detail:")
for d in b_detail:
    print("   ", d)
print("union protected count:", len(protected))
print("set_b mons already in set_a:", set_b & set_a)
print("set_b mons NOT in set_a (net new):", set_b - set_a)

# Examine the top-10 candidates that were REJECTED by the CP floor, for the writeup
print("\n--- all gl_rank<=10 or ul_rank<=10 shadow candidates and their floor verdict ---")
for r in rows:
    gl = r["gl_rank"]; ul = r["ul_rank"]
    if (gl is not None and gl <= 10) or (ul is not None and ul <= 10):
        notes = []
        if gl is not None and gl <= 10:
            sid = r["gl_stage"] + "_shadow"; mc = maxcp(sid)
            notes.append(f"GL r{gl} {sid} cap={mc} {'PASS' if mc and mc>=GL_FLOOR else 'FAIL'}")
        if ul is not None and ul <= 10:
            sid = r["ul_stage"] + "_shadow"; mc = maxcp(sid)
            notes.append(f"UL r{ul} {sid} cap={mc} {'PASS' if mc and mc>=UL_FLOOR else 'FAIL'}")
        print(f"  {r['species_name']:10s} uid={r['uid_hex']} iv={r['iv_total']} cp={r['cp']} | " + " ; ".join(notes))

# sample for the report: 6 items, species + deciding stat
print("\n--- sample (6) ---")
sample_rows = sorted(best.values(), key=lambda r: (-r["iv_total"], -(r["cp"] or 0)))[:6]
for r in sample_rows:
    print(f"  {r['species_name']} (form {r['form']}) iv_total={r['iv_total']} [best-in-group, part a]  uid={r['uid_hex']}")

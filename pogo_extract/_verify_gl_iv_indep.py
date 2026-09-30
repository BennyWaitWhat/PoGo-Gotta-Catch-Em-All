import sqlite3, json, os

BASE = "C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
DB = os.path.join(BASE, "pokemon.db")
GM = os.path.join(BASE, "pvpoke_gamemaster.json")
TAGDIR = os.path.join(BASE, "system/analysis/tagsets")
GLFILE = os.path.join(TAGDIR, "1_GL_IV.txt")
XFER = os.path.join(TAGDIR, "6_Transfer.txt")

# --- Build base stats map exactly per spec ---
gm = json.load(open(GM, encoding="utf-8"))
BS = {p['speciesId']: p['baseStats'] for p in gm['pokemon']}

def maxcp(sid):
    if sid is None or sid not in BS:
        return None
    b = BS[sid]
    atk, dfn, hp = b['atk'], b['def'], b['hp']
    # spec formula verbatim
    return int(((atk+15)*(dfn+15)**0.5*(hp+15)**0.5*0.84029999**2)/10)

# --- Read DB ---
c = sqlite3.connect(DB)
cur = c.cursor()
cur.execute("""SELECT uid_hex, species_name, iv_atk, iv_def, iv_sta,
                      gl_rank, ul_rank, gl_stage, ul_stage, in_bag
               FROM pokemon""")
rows = cur.fetchall()
c.close()

# sanity: uid_hex format check
bad_fmt = [r[0] for r in rows if r[0] is None or len(r[0]) != 16]
print("rows total:", len(rows))
print("uid_hex not 16-char:", len(bad_fmt), bad_fmt[:5])

derived = set()
ctx = {}
unresolved = []   # qualifies on rank/bag but gl_stage missing from GM -> maxcp None
qualifying_rank = 0
for uid, name, ia, idf, ist, gr, ur, gstage, ustage, inbag in rows:
    ctx[uid] = dict(name=name, ia=ia, idf=idf, ist=ist, gr=gr, ur=ur,
                    gstage=gstage, ustage=ustage, inbag=inbag)
    if inbag != 1:
        continue
    if gr is None:
        continue
    if not (gr <= 5):
        continue
    qualifying_rank += 1
    mc = maxcp(gstage)
    if mc is None:
        unresolved.append((uid, name, gstage, gr, ia, idf, ist))
        continue
    if mc >= 1400:
        derived.add(uid)

# --- Transfer set (string compare, verbatim) ---
xfer = set(l.strip() for l in open(XFER, encoding="utf-8") if l.strip())
# guard: dup / whitespace
file_lines = [l.strip() for l in open(GLFILE, encoding="utf-8") if l.strip()]
fileset = set(file_lines)

derived_final = derived - xfer

extra = fileset - derived_final      # in file, not in my derived (keep mon shouldn't be here)
missing = derived_final - fileset    # in my derived, not in file

removed_by_xfer = derived & xfer     # keep-rule mons that are also transfer

print("\n=== COUNTS ===")
print("qualifying (in_bag=1, gl_rank<=5):", qualifying_rank)
print("rule_set (maxcp>=1400, before xfer subtract):", len(derived))
print("xfer_count:", len(xfer))
print("rule INTERSECT xfer (removed by subtract):", len(removed_by_xfer))
print("derived_final (after subtract):", len(derived_final))
print("file_count:", len(fileset), "(raw lines:", len(file_lines), ")")
print("extra (file - derived):", len(extra))
print("missing (derived - file):", len(missing))
print("MATCH:", len(extra) == 0 and len(missing) == 0)

print("\n=== UNRESOLVED gl_stage (qualifies rank/bag, sid not in GM) ===", len(unresolved))
for u in unresolved[:20]:
    print("  ", u)

print("\n=== removed-by-xfer examples ===", len(removed_by_xfer))
for u in sorted(removed_by_xfer)[:10]:
    x = ctx[u]
    print(f"  {u} {x['name']} IV {x['ia']}-{x['idf']}-{x['ist']} gl_rank={x['gr']} stage={x['gstage']} maxcp={maxcp(x['gstage'])}")

def show(u):
    x = ctx.get(u)
    if not x:
        return f"{u} <not in DB>"
    return (f"{u} {x['name']} IV {x['ia']}-{x['idf']}-{x['ist']} "
            f"gl_rank={x['gr']} ul_rank={x['ur']} stage={x['gstage']} "
            f"maxcp={maxcp(x['gstage'])} in_bag={x['inbag']} inXfer={u in xfer}")

print("\n=== EXTRA (in file, NOT in derived) ===")
for u in sorted(extra)[:8]:
    print("  ", show(u))

print("\n=== MISSING (in derived, NOT in file) ===")
for u in sorted(missing)[:8]:
    print("  ", show(u))

# also: does file contain anything not even in DB?
not_in_db = fileset - set(ctx.keys())
print("\nfile uids not present in DB at all:", len(not_in_db), sorted(not_in_db)[:8])
# does file contain any xfer mon directly?
file_and_xfer = fileset & xfer
print("file INTERSECT xfer (keep tag containing transfer mon):", len(file_and_xfer), sorted(file_and_xfer)[:8])

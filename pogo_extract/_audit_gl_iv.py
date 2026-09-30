"""Independent re-derivation of the '1 GL IV' tag. Does NOT import build_tagsets
or keep_policy. Uses pvp_iv_rule.qualifies (that IS the rule per the audit spec),
the gamemaster baseStats, and the live pokemon.db. Applies the MINUS 6_Transfer
invariant. Compares to the on-disk tagset file and to policy_reasons.json gl_iv."""
import sqlite3, json, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from pvp_iv_rule import qualifies as pvp_iv_qualifies, pvid, maxcp

DB = os.path.join(ROOT, 'pokemon.db')
TAGFILE = os.path.join(ROOT, 'system', 'analysis', 'tagsets', '1_GL_IV.txt')
XFERFILE = os.path.join(ROOT, 'system', 'analysis', 'tagsets', '6_Transfer.txt')
PRJSON = os.path.join(ROOT, 'system', 'analysis', 'policy_reasons.json')
GL_FLOOR = 1400

gm = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))
BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}

c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
rows = c.execute("""SELECT uid_hex, species_name, form, iv_atk, iv_def, iv_sta,
    gl_stage, gl_rank, cp, in_bag FROM pokemon WHERE in_bag=1""").fetchall()

derived_raw = set()
for r in rows:
    if pvp_iv_qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'],
                        r['iv_sta'], r['gl_stage'], r['gl_rank'], GL_FLOOR, BS):
        derived_raw.add(r['uid_hex'])

TRANSFER = set(open(XFERFILE).read().split()) if os.path.exists(XFERFILE) else set()
derived = derived_raw - TRANSFER

file_set = set(open(TAGFILE).read().split())

pr = json.load(open(PRJSON, encoding='utf-8'))
pr_gl_iv = {u for u, reasons in pr.items() if 'gl_iv' in reasons}

# ghost check via full DB (file member may not be in_bag=1, or may be absent)
allbag = {r['uid_hex'] for r in rows}
ghosts = sorted(u for u in file_set if u not in allbag)

only_in_file = sorted(file_set - derived)
only_in_rule = sorted(derived - file_set)

print("file_count   :", len(file_set))
print("derived_raw  :", len(derived_raw), "(before MINUS 6_Transfer)")
print("derived_count:", len(derived), "(after MINUS 6_Transfer)")
print("transfer_size:", len(TRANSFER))
print("raw&transfer overlap:", len(derived_raw & TRANSFER))
print("exact_match  :", file_set == derived)
print("ghost_count  :", len(ghosts), ghosts)
print("only_in_file :", only_in_file)
print("only_in_rule :", only_in_rule)
print("pr_gl_iv_count:", len(pr_gl_iv))
print("file==pr_gl_iv:", file_set == pr_gl_iv)
print("derived==pr_gl_iv:", derived == pr_gl_iv)
print("pr_gl_iv-file:", sorted(pr_gl_iv - file_set))
print("file-pr_gl_iv:", sorted(file_set - pr_gl_iv))

print("== spot checks ==")
sample = list(file_set)[:3]
byuid = {r['uid_hex']: r for r in rows}
for u in sample:
    r = byuid.get(u)
    if r is None:
        print(u, "NOT in_bag=1 rows!"); continue
    pv = pvid(r['species_name'], r['form'] or 0); mc = maxcp(r['gl_stage'], BS)
    ready = (pv == r['gl_stage'])
    role = "READY(pvid==stage)" if ready else "BUILD def>=14:%s sta>=14:%s" % ((r['iv_def'] or 0)>=14, (r['iv_sta'] or 0)>=14)
    print("%s %s form=%s IV=%s/%s/%s gl_stage=%s gl_rank=%s cp=%s in_bag=%s | maxcp=%s(>=%s:%s) atk<=1:%s rank<=5:%s %s -> qual=%s" % (
        r['uid_hex'], r['species_name'], r['form'], r['iv_atk'], r['iv_def'], r['iv_sta'],
        r['gl_stage'], r['gl_rank'], r['cp'], r['in_bag'], mc, GL_FLOOR, mc>=GL_FLOOR,
        (r['iv_atk'] or 0)<=1, r['gl_rank'] is not None and r['gl_rank']<=5, role,
        pvp_iv_qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'], r['iv_sta'], r['gl_stage'], r['gl_rank'], GL_FLOOR, BS)))
c.close()

"""Corrected side-quest on FRESH data: shiny-displaces-plain.

Find (species, cf-form) where an in-bag SHINY (iv NOT in {0,45}) would DISPLACE a plain
kept ONLY by variant_floor, if shinies counted toward the per-form top-3 cap.

A plain is displaceable ONLY if its policy_reasons set is EXACTLY {"variant_floor"}.
Per (pid, cf-form): K = sole-variant_floor plains; S = non-0/45 shinies.
NEW top-3 = top-3 by IV (tie-break CP, matching topn) of (K union S).
displaced = K not in NEW top-3. Adversarially re-check displaced has NO other protection.
"""
import sqlite3, json, os
from collections import defaultdict, Counter

ROOT = "C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
DB = ROOT + "/pokemon.db"
REASONS = ROOT + "/system/analysis/policy_reasons.json"

c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
rows = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()
reasons = {u: set(rs) for u, rs in json.load(open(REASONS)).items()}

# ---- replicate keep_policy cf(r) form normalization EXACTLY ----
_REGSUF = ('_alolan', '_galarian', '_hisuian', '_paldean')
# need pvid for regional-code check; import from project
import sys
sys.path.insert(0, ROOT)
from pvp_iv_rule import pvid
from costume_forms import is_costume_form
def _is_regional_code(nm, f):
    return any(x in pvid(nm, f) for x in _REGSUF)

# ---- replicate keep_policy _truly_plain(r): no cosmetic / Dynamax axis ----
# (variant_floor is assigned by BOTH rule 1a [cosmetic variants] and rule 1b [plain
# line cap]. The task's "plain" = the rule-1b pool ONLY -> must gate on _truly_plain,
# else costume/Dynamax variants get mis-counted as displaceable plains.)
def _truly_plain(r):
    return (not (r['fresh_costume'] or 0) and not (r['special_bg_id'] or 0)
            and not (r['natural_art_background'] or 0)
            and not (r['costume_decoration_id'] and str(r['costume_decoration_id']) != '0')
            and (r['fresh_bread_mode'] or 0) not in (1, 2)
            and not is_costume_form(r['fresh_form']))
_basecnt = defaultdict(Counter)
for r in rows:
    _f = r['form'] or 0
    _reg = (r['form_region'] or '').strip().lower()
    if _f != 0 and _reg in ('', 'normal', 'kantonian', 'none', 'null') and not _is_regional_code(r['species_name'], _f):
        _basecnt[r['pokemon_id']][_f] += 1
base_form = {pid: cnt.most_common(1)[0][0] for pid, cnt in _basecnt.items() if len(cnt) == 1}
def cf(r):
    _f = r['form'] or 0
    return base_form.get(r['pokemon_id'], _f) if _f == 0 else _f

# topn tie-break identical to keep_policy.topn
def sortkey(r):
    return (-(r['iv_total'] or 0), -(r['cp'] or 0))

# ---- partition ----
# S = shinies competing for the PLAIN top-3: non-0/45 IV, and plain-SHAPED otherwise
# (not shadow, not a cosmetic/Dynamax variant) -- a shiny that is ALSO a costume lives on
# its own variant axis and does not contest the plain line cap.
shinies_by = defaultdict(list)
for r in rows:
    if (r['fresh_shiny'] and (r['iv_total'] or 0) not in (0, 45)
            and r['fresh_alignment'] != 1 and _truly_plain(r)):
        shinies_by[(r['pokemon_id'], cf(r))].append(r)

# K = displaceable plains: _truly_plain, non-shiny, non-shadow, kept with reason set
# EXACTLY {"variant_floor"} (so every OTHER protection is respected).
sole_vf_by = defaultdict(list)
for r in rows:
    u = r['uid_hex']
    rs = reasons.get(u)
    if rs is None:
        continue  # Transfer -> not a kept plain
    if rs == {"variant_floor"} and _truly_plain(r) and not r['fresh_shiny'] and r['fresh_alignment'] != 1:
        sole_vf_by[(r['pokemon_id'], cf(r))].append(r)

CAP = 3
# Build the REAL plain pool per (pid,cf) exactly as rule 1b sees it: every _truly_plain,
# non-shiny, non-shadow specimen (regardless of co-reasons). The current top-3 (by IV/CP)
# is what variant_floor protects at-stage; injecting S and re-taking top-3 tells us which
# of those slots a shiny would steal. A plain is "displaced" ONLY if (a) it currently
# occupies a top-3 plain slot AND (b) its reason set is EXACTLY {variant_floor} AND (c) it
# falls out of the NEW top-3 once shinies compete.
plain_pool_by = defaultdict(list)
for r in rows:
    if _truly_plain(r) and not r['fresh_shiny'] and r['fresh_alignment'] != 1:
        plain_pool_by[(r['pokemon_id'], cf(r))].append(r)

instances = []          # displaced plains
groups_hit = set()
for key, Klist in sole_vf_by.items():
    S = shinies_by.get(key, [])
    if not S:
        continue  # no shiny competing -> nothing displaces
    pool = plain_pool_by[key]
    cur_top = sorted(pool, key=sortkey)[:CAP]
    cur_top_uids = {r['uid_hex'] for r in cur_top}
    new_top = sorted(pool + S, key=sortkey)[:CAP]
    new_top_uids = {r['uid_hex'] for r in new_top}
    for k in Klist:
        # k must currently hold a top-3 plain slot (sole-VF plains always do, but assert it)
        # and must fall out once shinies are injected.
        if k['uid_hex'] in cur_top_uids and k['uid_hex'] not in new_top_uids:
            instances.append(k)
            groups_hit.add(key)

# ---- ADVERSARIAL re-verification: each displaced plain must have NO other protection ----
bad = []
for k in instances:
    rs = reasons.get(k['uid_hex'], set())
    if rs != {"variant_floor"}:
        bad.append((k['uid_hex'], sorted(rs)))
    # also: must genuinely be non-shiny, non-shadow plain
    if k['fresh_shiny'] or k['fresh_alignment'] == 1:
        bad.append((k['uid_hex'], 'NOT-PLAIN'))
    if (k['iv_total'] or 0) in (0, 45):
        bad.append((k['uid_hex'], 'IV-0-or-45'))

# species/form name map
def fname(r):
    return f"{r['species_name']} (pid {r['pokemon_id']}, cf-form {cf(r)})"

print("=== RESULT ===")
print("instances (displaced plain count):", len(instances))
print("distinct (pid,form) groups hit:", len(groups_hit))
print("ADVERSARIAL violations:", len(bad))
if bad:
    for b in bad[:20]:
        print("  VIOLATION", b)

# per-group detail for examples
print("\n=== PER-GROUP DETAIL ===")
detail = []
for key in sorted(groups_hit, key=lambda k: k[0]):
    Klist = sole_vf_by[key]
    S = shinies_by[key]
    pool = plain_pool_by[key]
    cur_top = sorted(pool, key=sortkey)[:CAP]
    cur_top_uids = {r['uid_hex'] for r in cur_top}
    new_top = sorted(pool + S, key=sortkey)[:CAP]
    new_top_uids = {r['uid_hex'] for r in new_top}
    disp = [k for k in Klist if k['uid_hex'] in cur_top_uids and k['uid_hex'] not in new_top_uids]
    rname = Klist[0]['species_name']
    print(f"\n{rname} pid={key[0]} cf-form={key[1]}")
    print(f"  plain pool={len(pool)} cur_top3 ivs={[(x['iv_total'],x['cp']) for x in cur_top]}")
    print(f"  competing shinies (S)={len(S)} ivs={sorted([(x['iv_total'],x['cp']) for x in S], reverse=True)}")
    print(f"  new_top3 (incl shiny) ivs={[(x['iv_total'],x['cp'],'SHINY' if x['fresh_shiny'] else '') for x in new_top]}")
    print(f"  displaced={len(disp)} disp_ivs={[(x['iv_total'],x['cp']) for x in disp]}")
    detail.append((rname, key, len(pool), len(S), len(disp),
                   sorted([x['iv_total'] for x in S], reverse=True),
                   sorted([x['iv_total'] for x in disp], reverse=True)))

# emit machine summary
print("\n=== JSON ===")
print(json.dumps({
    "instances": len(instances),
    "groups": len(groups_hit),
    "violations": len(bad),
    "detail": [{"species": d[0], "pid": d[1][0], "cf_form": d[1][1],
                "K": d[2], "S": d[3], "displaced": d[4],
                "shiny_ivs": d[5], "displaced_ivs": d[6]} for d in detail]
}, indent=1))

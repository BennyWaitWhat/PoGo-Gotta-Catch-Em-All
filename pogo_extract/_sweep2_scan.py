import os, re
ROOT = os.path.dirname(os.path.abspath(__file__))
targets = [
 'system/scripts/keep_policy.py','system/scripts/build_tagsets.py','system/scripts/preflight_transfer.py',
 'costume_forms.py','references.py','pvp_iv_rule.py','_lawcheck.py','_spotdata.py','_evocheck.py',
 'compute_all_ranks.py','keep_config.py','audit_cull.py','audit_tags_membership.py','full_audit.py',
 'system/scripts/rank_cache.py','system/scripts/refresh_evolve_shiny.py','dashboard.py',
 'system/scripts/prune_tags.py','system/scripts/reconcile_tags.py',
]
pat = re.compile(r"[\'\"]([A-Za-z0-9_./\-]+\.(json|txt|pkl|db|csv))[\'\"]")
for t in targets:
    p = os.path.join(ROOT, t.replace('/', os.sep))
    if not os.path.exists(p):
        print("--- %s: MISSING" % t); continue
    src = open(p, encoding='utf-8', errors='replace').read()
    hits = sorted(set(m[0] for m in pat.findall(src)))
    print("--- %s:" % t)
    for h in hits: print("      ", h)

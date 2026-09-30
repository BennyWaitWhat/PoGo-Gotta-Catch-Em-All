import sqlite3, re, os, sys
sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))
con = sqlite3.connect(os.path.join(ROOT, 'pokemon.db'))
cols = [r[1] for r in con.execute('PRAGMA table_info(pokemon)')]
con.close()

LIVE = {
 'keep_policy.py'      : 'system/scripts/keep_policy.py',
 'keep_engine.py'      : 'system/scripts/keep_engine.py',
 'build_tagsets.py'    : 'system/scripts/build_tagsets.py',
 'apply_tagsets.py'    : 'system/scripts/apply_tagsets.py',
 'tag_ops.py'          : 'system/scripts/tag_ops.py',
 'cull_v9.py'          : 'cull_v9.py',
 'compute_all_ranks.py': 'compute_all_ranks.py',
 'pvp_iv_rule.py'      : 'pvp_iv_rule.py',
 'references.py'       : 'references.py',
 'pogo_pipeline.py'    : 'pogo_pipeline.py',
 'detect_legacy.py'    : 'detect_legacy.py',
}
texts = {}
for name, path in LIVE.items():
    fp = os.path.join(ROOT, path)
    if os.path.exists(fp):
        texts[name] = open(fp, encoding='utf-8').read()
    else:
        print("MISSING LIVE FILE:", path)

hits = {}
for col in cols:
    pat = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(col) + r'(?![A-Za-z0-9_])')
    found = [name for name, txt in texts.items() if pat.search(txt)]
    hits[col] = found

mentioned = {c: f for c, f in hits.items() if f}
unmentioned = [c for c in cols if not hits[c]]
print("TOTAL COLS:", len(cols))
print("=== MENTIONED IN >=1 LIVE FILE ===", len(mentioned))
for c in cols:
    if hits[c]:
        print(f"{c:34s} | {','.join(hits[c])}")
print()
print("=== ZERO LIVE MENTION (drop, modulo SELECT *) ===", len(unmentioned))
print(', '.join(unmentioned))

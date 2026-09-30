"""Parse the master-triage workflow result: write the 10 system dossiers to
system/analysis/dossiers/, and tally the per-mon purpose corrections by pattern
so we can fix the deterministic priority systematically."""
import json, os, sys, re
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE))
OUT=sys.argv[1] if len(sys.argv)>1 else None
if not OUT:
    print('pass the workflow .output path'); sys.exit(1)
raw=open(OUT,encoding='utf-8',errors='ignore').read()
top=json.loads(raw)
data=top.get('result', top)   # payload is nested under 'result'

corr=data.get('corrections',[]); gems=data.get('gems',[]); anom=data.get('anomalies',[]); systems=data.get('systems',[])
print(f"reviewed={data.get('reviewed')}  corrections={len(corr)}  gems={len(gems)}  anomalies={len(anom)}  systems={len(systems)}")

# write dossiers
dd=os.path.join(ROOT,'system','analysis','dossiers'); os.makedirs(dd,exist_ok=True)
for s in systems:
    name=s.get('system','?'); doss=s.get('dossier') or ''
    if isinstance(doss,dict): doss=json.dumps(doss,indent=2)
    open(os.path.join(dd,f'{name}.md'),'w',encoding='utf-8').write(str(doss))
print('dossiers written:', [s.get('system') for s in systems])

# tally corrections by from->to
pat=Counter((c.get('from'),c.get('to')) for c in corr)
print('\ncorrection patterns (from -> to : count):')
for (f,t),n in pat.most_common():
    print(f'  {f} -> {t}: {n}')
# save corrections for application
json.dump(corr, open(os.path.join(ROOT,'system','analysis','purpose_corrections.json'),'w'), indent=1)
print('\nsaved purpose_corrections.json')
print('\nsample anomalies:')
for a in anom[:15]: print('  -',a)

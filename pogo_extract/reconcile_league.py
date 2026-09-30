"""League tag rule (GL/UL): rank<=10 AND the ACTUALLY-RANKED stage form's max CP passes the
league CP gate (GL >=1425, UL >2425), keep top 2 per species. Stage form = gl_stage/ul_stage
(no evo traversal, no Mega). Self-healing; warm-up untag.

Usage: python reconcile_league.py GL   |   python reconcile_league.py UL
"""
import frida, sys, time, sqlite3, json
from collections import defaultdict
sys.path.insert(0,'.')
import pogo_il2cpp as pg, pogo_pipeline as pl

LEAGUE = (sys.argv[1] if len(sys.argv)>1 else 'GL').upper()
CFG = {
  'GL': dict(tag='GL', rank='gl_rank', pct='gl_pct', stage='gl_stage', cpmin=1425, strict=False),
  'UL': dict(tag='UL', rank='ul_rank', pct='ul_pct', stage='ul_stage', cpmin=2425, strict=True),
}[LEAGUE]
CAP = 2

gm = json.load(open('pvpoke_gamemaster.json'))
by_sid = {p['speciesId']: p for p in gm['pokemon']}
CPM_L50 = 0.84029999
_cache = {}
def stage_maxcp(sid):
    if sid in _cache: return _cache[sid]
    p = by_sid.get(sid)
    if not p: _cache[sid]=None; return None
    bs = p.get('baseStats',{})
    cp = max(10, int(((bs.get('atk',0)+15)*(bs.get('def',0)+15)**0.5*(bs.get('hp',0)+15)**0.5*CPM_L50**2)/10))
    _cache[sid]=cp; return cp

def passes(cp):
    if cp is None: return False
    return cp > CFG['cpmin'] if CFG['strict'] else cp >= CFG['cpmin']

c = sqlite3.connect('pokemon.db').cursor()
rows = c.execute(f"SELECT uid_hex, pokemon_id, {CFG['rank']}, {CFG['pct']}, {CFG['stage']} FROM pokemon WHERE in_bag=1 AND {CFG['rank']} IS NOT NULL AND {CFG['rank']}<=10").fetchall()
bypid = defaultdict(list)
for uh,pid,rank,pct,stage in rows:
    if stage and passes(stage_maxcp(stage)):
        bypid[pid].append((uh,rank,pct))
target=set()
for pid,l in bypid.items():
    l.sort(key=lambda x:(x[1], -(x[2] or 0)))
    for r in l[:CAP]: target.add(r[0])

def has(a,n): return a and n in [t for t in a.split(';') if t]
allr=c.execute("SELECT uid_hex, auth_tag_names FROM pokemon WHERE in_bag=1").fetchall()
server={uh for uh,a in allr if has(a,CFG['tag'])}
to_add=target-server; to_remove=server-target
print(f"{LEAGUE}: target={len(target)} server={len(server)} add={len(to_add)} remove={len(to_remove)}")

def us(uh):
    u=int(c.execute('SELECT uid FROM pokemon WHERE uid_hex=?',(uh,)).fetchone()[0]); return str(u if u>=0 else u+2**64)

for attempt in range(10):
    try:
        sess,pid=pg.get_session(); s=pl.step_singletons(sess); SVC=s['svc']; BAG=s['bag']
        allu=list(to_add|to_remove)
        found=pg.find_protos_for_uids(sess, BAG, [us(u) for u in allu])
        bt=sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read()); bt.on('message',lambda m,d:None); bt.load(); bt.exports_sync.init_status()
        ft=bt.exports_sync.find_tag_id_by_name(SVC, CFG['tag'])
        addp=[found[us(u)] for u in to_add if us(u) in found]
        if addp:
            bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], addp[:1]); time.sleep(0.6)
            for i in range(0,len(addp),60): bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], addp[i:i+60]); time.sleep(0.3)
        rem=[found[us(u)] for u in to_remove if us(u) in found]
        if rem:
            try: bt.exports_sync.bulk_untag_one(SVC, rem[0], ft['tagProtoAddr']); time.sleep(0.5)
            except: pass
            for rnd in range(2):
                for p in rem:
                    try: bt.exports_sync.bulk_untag_one(SVC, p, ft['tagProtoAddr'])
                    except: pass
                    time.sleep(0.18)
        time.sleep(1.5)
        chk=bt.exports_sync.get_pokemon_for_tag(SVC, ft['idx'])
        print(f"server {CFG['tag']} now={chk.get('dump',{}).get('+0x18_listish',{}).get('count')} (target {len(target)})")
        sess.detach(); break
    except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError, frida.ServerNotRunningError, RuntimeError) as e:
        print(f"[retry {attempt+1}] {type(e).__name__}"); time.sleep(4)

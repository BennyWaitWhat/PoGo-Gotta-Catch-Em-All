"""GL tag rule: per species (pokemon_id), individuals with gl_rank<=10, keep top 3 (lowest gl_rank, gl_pct tiebreak).
Apply across ALL species. Reconcile server GL tag to this target. Self-healing, bag-walk proto resolution."""
import frida, sys, time, sqlite3
from collections import defaultdict
sys.path.insert(0,'.')
import pogo_il2cpp as pg, pogo_pipeline as pl

_LEAGUE = (sys.argv[1] if len(sys.argv) > 1 else 'GL').upper()
_CFG = {'GL': ('GL','gl_rank','gl_pct'), 'UL': ('UL','ul_rank','ul_pct'), 'LL': ('LL','ll_rank','ll_pct')}
TAGNAME, RANK_COL, PCT_COL = _CFG[_LEAGUE]
CAP = int(sys.argv[2]) if len(sys.argv) > 2 else 2

def has_tag(auth, name):
    return auth and name in [t for t in auth.split(';') if t]

c = sqlite3.connect('pokemon.db').cursor()
rows = c.execute(f"SELECT uid_hex, uid, pokemon_id, species_name, {RANK_COL}, {PCT_COL}, auth_tag_names FROM pokemon WHERE in_bag=1 AND {RANK_COL} IS NOT NULL AND {RANK_COL}<=10").fetchall()
bypid = defaultdict(list)
for r in rows: bypid[r[2]].append(r)
target = set()
for pid, lst in bypid.items():
    lst.sort(key=lambda x:(x[4], -(x[5] or 0)))
    for r in lst[:CAP]: target.add(r[0])

allrows = c.execute("SELECT uid_hex, auth_tag_names FROM pokemon WHERE in_bag=1").fetchall()
server = {uh for uh, auth in allrows if has_tag(auth, TAGNAME)}
to_add = target - server
to_remove = server - target
print(f"target={len(target)} server={len(server)} add={len(to_add)} remove={len(to_remove)}")

def us(uh):
    u=int(c.execute('SELECT uid FROM pokemon WHERE uid_hex=?',(uh,)).fetchone()[0]); return str(u if u>=0 else u+2**64)

for attempt in range(10):
    try:
        sess, pid = pg.get_session()
        s = pl.step_singletons(sess); SVC=s['svc']; BAG=s['bag']
        allu = list(to_add | to_remove)
        found = pg.find_protos_for_uids(sess, BAG, [us(u) for u in allu])
        print(f"resolved {len(found)}/{len(allu)} protos")
        bt = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
        bt.on('message', lambda m,d:None); bt.load(); bt.exports_sync.init_status()
        ft = bt.exports_sync.find_tag_id_by_name(SVC, TAGNAME)
        add_protos = [found[us(u)] for u in to_add if us(u) in found]
        if add_protos:
            bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], add_protos[:1]); time.sleep(0.6)
            built=0
            for i in range(0, len(add_protos), 60):
                r = bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], add_protos[i:i+60])
                built += r.get('built',0); time.sleep(0.3)
            print(f"added {built}/{len(add_protos)}")
        for u in to_remove:
            if us(u) in found:
                bt.exports_sync.bulk_untag_one(SVC, found[us(u)], ft['tagProtoAddr']); time.sleep(0.25)
        time.sleep(1.5)
        chk = bt.exports_sync.get_pokemon_for_tag(SVC, ft['idx'])
        cnt = chk.get('dump',{}).get('+0x18_listish',{}).get('count')
        print(f"server {TAGNAME} now={cnt} (target {len(target)})")
        sess.detach()
        break
    except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError, frida.ServerNotRunningError) as e:
        print(f"[retry {attempt+1}] {type(e).__name__}"); time.sleep(4)

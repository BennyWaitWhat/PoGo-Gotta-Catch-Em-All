"""Reconcile JUMBO tag to rule: top-2 weight u top-2 height per (pid,form,fresh_costume) among XXL.
Adds under-tagged, removes over-tagged. Bag-walk proto resolution. Self-healing."""
import frida, sys, time, sqlite3
from collections import defaultdict
sys.path.insert(0,'.')
import pogo_il2cpp as pg, pogo_pipeline as pl

c = sqlite3.connect('pokemon.db').cursor()
xxl = c.execute("SELECT uid_hex, uid, pokemon_id, form, fresh_costume, weight_kg, height_m, auth_tag_names FROM pokemon WHERE in_bag=1 AND pokemon_size_category=5").fetchall()
groups = defaultdict(list)
for r in xxl: groups[(r[2], r[3] or 0, r[4] or 0)].append(r)
target = set()
for k, lst in groups.items():
    for r in sorted(lst, key=lambda x:-(x[5] or 0))[:2]: target.add(r[0])
    for r in sorted(lst, key=lambda x:-(x[6] or 0))[:2]: target.add(r[0])
server = {r[0] for r in xxl if r[7] and 'JUMBO' in r[7]}
to_add = target - server
to_remove = server - target
print(f"target={len(target)} server={len(server)} add={len(to_add)} remove={len(to_remove)}")

def us(uh):
    u=int(c.execute('SELECT uid FROM pokemon WHERE uid_hex=?',(uh,)).fetchone()[0]); return str(u if u>=0 else u+2**64)

for attempt in range(8):
    try:
        sess, pid = pg.get_session()
        SVC = pl.step_singletons(sess)['svc']; BAG = pl.step_singletons.__wrapped__(sess)['bag'] if hasattr(pl.step_singletons,'__wrapped__') else None
        if not BAG:
            BAG = pl.step_singletons(sess)['bag']
        allu = list(to_add | to_remove)
        found = pg.find_protos_for_uids(sess, BAG, [us(u) for u in allu])
        bt = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
        bt.on('message', lambda m,d:None); bt.load(); bt.exports_sync.init_status()
        ft = bt.exports_sync.find_tag_id_by_name(SVC, 'JUMBO')
        # add
        add_protos = [found[us(u)] for u in to_add if us(u) in found]
        if add_protos:
            bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], add_protos[:1]); time.sleep(0.6)
            bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], add_protos)
        # remove
        for u in to_remove:
            if us(u) in found:
                bt.exports_sync.bulk_untag_one(SVC, found[us(u)], ft['tagProtoAddr']); time.sleep(0.3)
        time.sleep(1.5)
        chk = bt.exports_sync.get_pokemon_for_tag(SVC, ft['idx'])
        cnt = chk.get('dump',{}).get('+0x18_listish',{}).get('count')
        print(f"applied: +{len(add_protos)} -{len(to_remove)} | server JUMBO now={cnt} (target {len(target)})")
        sess.detach()
        break
    except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError, frida.ServerNotRunningError) as e:
        print(f"[retry {attempt+1}] {type(e).__name__}"); time.sleep(4)

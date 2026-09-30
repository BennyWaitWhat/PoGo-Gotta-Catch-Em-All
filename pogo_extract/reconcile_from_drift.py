"""Apply tag_drift.json: per tag, add the 'add' uids and remove the 'remove' uids.
Bag-walk proto resolution, warm-up untag, self-healing reconnect."""
import frida, sys, time, json, sqlite3
sys.path.insert(0,'.')
import pogo_il2cpp as pg, pogo_pipeline as pl

drift = json.load(open('tag_drift.json'))
c = sqlite3.connect('pokemon.db').cursor()
def us(uh):
    r=c.execute('SELECT uid FROM pokemon WHERE uid_hex=?',(uh,)).fetchone()
    if not r: return None
    u=int(r[0]); return str(u if u>=0 else u+2**64)

# gather all uids needed
all_uids=set()
for t,d in drift.items():
    all_uids |= set(d['add']) | set(d['remove'])

for attempt in range(10):
    try:
        sess,pid=pg.get_session(); s=pl.step_singletons(sess); SVC=s['svc']; BAG=s['bag']
        umap={uh:us(uh) for uh in all_uids if us(uh)}
        found=pg.find_protos_for_uids(sess, BAG, list(umap.values()))
        proto={uh:found[u] for uh,u in umap.items() if u in found}
        bt=sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read()); bt.on('message',lambda m,d:None); bt.load(); bt.exports_sync.init_status()
        for tag,d in drift.items():
            ft=bt.exports_sync.find_tag_id_by_name(SVC, tag)
            if not ft.get('ok'):
                print(f'{tag}: tag missing, skip'); continue
            adds=[proto[uh] for uh in d['add'] if uh in proto]
            rems=[proto[uh] for uh in d['remove'] if uh in proto]
            if adds:
                bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], adds[:1]); time.sleep(0.5)
                for i in range(0,len(adds),60): bt.exports_sync.bulk_tag_many(SVC, ft['tagProtoAddr'], adds[i:i+60]); time.sleep(0.3)
            if rems:
                try: bt.exports_sync.bulk_untag_one(SVC, rems[0], ft['tagProtoAddr']); time.sleep(0.5)  # warm-up
                except: pass
                for rnd in range(2):
                    for p in rems:
                        try: bt.exports_sync.bulk_untag_one(SVC, p, ft['tagProtoAddr'])
                        except: pass
                        time.sleep(0.18)
            time.sleep(1)
            chk=bt.exports_sync.get_pokemon_for_tag(SVC, ft['idx'])
            print(f"{tag}: +{len(adds)} -{len(rems)} -> server now {chk.get('dump',{}).get('+0x18_listish',{}).get('count')}")
        sess.detach(); break
    except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError, frida.ServerNotRunningError, RuntimeError) as e:
        print(f'[retry {attempt+1}] {type(e).__name__}'); time.sleep(4)

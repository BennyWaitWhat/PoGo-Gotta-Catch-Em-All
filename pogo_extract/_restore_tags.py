"""Restore named tags on the server from the DB auth_tag_names mirror (additive,
safe). Recreates the tag if missing, applies all DB members. Usage:
python _restore_tags.py "Mega:6" "Costume:4"   (name:color)"""
import sqlite3, sys, time, os
import pogo_il2cpp as pg
sys.stdout.reconfigure(encoding='utf-8')
HERE=os.path.dirname(os.path.abspath(__file__)); DB=os.path.join(HERE,'pokemon.db')

def main():
    specs=[a for a in sys.argv[1:] if ':' in a]
    targets=[(s.split(':')[0], int(s.split(':')[1])) for s in specs]
    conn=sqlite3.connect(DB)
    members={}
    for name,_ in targets:
        members[name]=[r[0] for r in conn.execute(
            "SELECT uid_hex FROM pokemon WHERE in_bag=1 AND (';'||COALESCE(auth_tag_names,'')||';') LIKE ?",
            (f'%;{name};%',))]
        print(f'{name}: DB has {len(members[name])} members')
    conn.close()
    allu=sorted({u for v in members.values() for u in v})

    sess,pid=pg.get_session(); print('pid',pid)
    try:
        bag=pg.pick_singleton(sess,'Niantic.Holoholo.Internal','PokemonBagImpl')
        svc=pg.pick_singleton(sess,'Niantic.Holoholo.Tagging','TaggingRpcService')
        pm=pg.find_protos_for_uids(sess,bag,sorted({str(int(u,16)) for u in allu}))
        print(f'bag-walk {len(pm)}/{len(allu)}')
        bt=sess.create_script(open('bulk_tag.js',encoding='utf-8').read()); bt.on('message',lambda m,d:None); bt.load(); bt.exports_sync.init_status()
        for name,color in targets:
            ft=bt.exports_sync.find_tag_id_by_name(svc,name)
            if not ft.get('ok'):
                for a in range(3):
                    bt.exports_sync.add_tag_on_instance(svc,name,color); time.sleep(3.0 if a==0 else 5.0)
                    ft=bt.exports_sync.find_tag_id_by_name(svc,name)
                    if ft.get('ok'): break
            if not ft.get('ok'): print(f'  ! create {name} failed'); continue
            tp=ft['tagProtoAddr']
            uids=members[name]; protos=[pm[str(int(u,16))] for u in uids if str(int(u,16)) in pm]
            done=0; B=100; i=0
            while i<len(protos):
                cp=protos[i:i+B]
                r=None
                for _ in range(3):
                    r=bt.exports_sync.bulk_tag_many(svc,tp,cp)
                    if r.get('ok') and r.get('built',0)==len(cp): break
                    time.sleep(0.6)
                if r.get('ok'): done+=len(cp)
                else: print(f'    ! {name} batch {i}: {r}')
                i+=B
                if i<len(protos): time.sleep(0.4)
            print(f'  {name}: applied {done}/{len(uids)}')
        bt.unload()
    finally:
        sess.detach()
    print('done')

if __name__=='__main__':
    main()

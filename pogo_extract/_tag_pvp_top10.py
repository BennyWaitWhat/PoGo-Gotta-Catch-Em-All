"""Create 'GL Top 10' and 'UL Top 10' tags and apply the best build-target per
meta pick (from pvp_top10_plan.json). Single Frida session, mirror DB."""
import sqlite3, json, time, sys
import pogo_il2cpp as pg
sys.stdout.reconfigure(encoding='utf-8')

PLAN = json.load(open('rescan_report/pvp_top10_plan.json'))
TAGS = {'GL': ('GL Top 10', 1), 'UL': ('UL Top 10', 2)}  # (name, color)

def main():
    want = {}
    for league, entries in PLAN.items():
        uids = [e['uid'] for e in entries if e.get('uid')]
        want[league] = sorted(set(uids))
        print(f'{TAGS[league][0]}: {len(want[league])} specimens')
    all_uids = sorted({u for v in want.values() for u in v})

    sess, pid = pg.get_session()
    print(f'pid={pid}')
    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        proto_map = pg.find_protos_for_uids(sess, bag, sorted({str(int(u,16)) for u in all_uids}))
        print(f'bag-walk: {len(proto_map)}/{len(all_uids)}')

        bt = sess.create_script(open('bulk_tag.js', encoding='utf-8').read())
        bt.on('message', lambda m,d: None); bt.load(); bt.exports_sync.init_status()
        conn = sqlite3.connect('pokemon.db')

        for league,(name,color) in TAGS.items():
            uids = want[league]
            if not uids: continue
            # find-or-create tag
            ftid = bt.exports_sync.find_tag_id_by_name(svc, name)
            if not ftid.get('ok'):
                bt.exports_sync.add_tag_on_instance(svc, name, color); time.sleep(2)
                ftid = bt.exports_sync.find_tag_id_by_name(svc, name)
            if not ftid.get('ok'):
                print(f'  ! could not create {name}: {ftid}'); continue
            tagproto = ftid['tagProtoAddr']
            protos, vuids = [], []
            for u in uids:
                p = proto_map.get(str(int(u,16)))
                if p: protos.append(p); vuids.append(u)
            res=None
            for _ in range(3):
                res = bt.exports_sync.bulk_tag_many(svc, tagproto, protos)
                if res.get('ok') and res.get('built',0)==len(protos): break
                time.sleep(0.8)
            print(f'  {name}: {res}')
            if res.get('ok'):
                cur=conn.cursor()
                for u in vuids:
                    row=cur.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?",(u,)).fetchone()
                    tags=[t for t in ((row[0] if row else None) or '').split(';') if t]
                    if name not in tags: tags.append(name)
                    cur.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",(';'.join(tags),u))
                conn.commit()
        conn.close(); bt.unload()
    finally:
        sess.detach()
    print('done')

if __name__ == '__main__':
    main()

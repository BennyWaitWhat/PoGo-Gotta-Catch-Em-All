"""Tag the new qualifiers found after the re-crawl. Additive only.
Single Frida session: find each tag, bag-walk the new uids, bulk_tag_many, mirror DB.
"""
import sqlite3, time, sys
import pogo_il2cpp as pg
sys.stdout.reconfigure(encoding='utf-8')

# tag -> [uid_hex...] (from _new_qualifiers.py output)
NEW = {
    'Hundos':  ['27b86897e43ce881', '5991e0b968336f76'],   # Emolga, Larvitar
    '0-15-15': ['7bbd825e86e27ae3'],                         # Lapras
    'Hatched': ['64c5caaf30a4e21b', '931e50176360cdf4', 'f01f3bca70d43db2'],  # Smoochum, Happiny, Geodude
    'GL':      ['5991e0b968336f76'],                         # Larvitar
    'JUMBO':   ['c37c09ac65bc839e'],                         # Zigzagoon XXL
}

def main():
    all_uids = sorted({u for v in NEW.values() for u in v})
    print(f'Tagging {sum(len(v) for v in NEW.values())} pairs across {len(NEW)} tags ({len(all_uids)} distinct specimens)')

    sess, pid = pg.get_session()
    print(f'pid={pid}')
    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        proto_map = pg.find_protos_for_uids(sess, bag, sorted({str(int(u,16)) for u in all_uids}))
        print(f'bag-walk: {len(proto_map)}/{len(all_uids)} protos')

        bt = sess.create_script(open('bulk_tag.js', encoding='utf-8').read())
        bt.on('message', lambda m,d: None); bt.load(); bt.exports_sync.init_status()

        conn = sqlite3.connect('pokemon.db')
        for name, uids in NEW.items():
            ftid = bt.exports_sync.find_tag_id_by_name(svc, name)
            if not ftid.get('ok'):
                print(f'  ! {name}: tag not found on server: {ftid}'); continue
            tagproto = ftid['tagProtoAddr']
            protos, vuids = [], []
            for u in uids:
                p = proto_map.get(str(int(u,16)))
                if p: protos.append(p); vuids.append(u)
            if not protos:
                print(f'  ! {name}: no protos resolved'); continue
            res = None
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
        conn.close()
        bt.unload()
    finally:
        sess.detach()
    print('done')

if __name__ == '__main__':
    main()

"""Retry the 100 Legendary specimens that hit NullRef on batch 100-200.

Uses the existing 'Legendary' tag on server (don't AddTag again). Fresh
bag-walk (proto pointers may have been stale on prior pass), then bulk_tag_many
in smaller chunks (25) so a single bad proto only takes its batch down.
"""
import json, os, sqlite3, time
import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')
BULK_TAG_JS = os.path.join(HERE, 'bulk_tag.js')
MISSING_FILE = os.path.join(HERE, 'rescan_report', 'agent_tags', '_legendary_missing.json')


def main():
    with open(MISSING_FILE, encoding='utf-8') as f:
        plan = json.load(f)
    uids = plan['uids']
    print(f"Retrying {len(uids)} Legendary specimens (smaller batches, fresh proto walk)")

    print('\nAttaching...')
    sess, pid = pg.get_session()
    print(f'  pid={pid}')

    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        print(f'  bag @ {bag}\n  svc @ {svc}')

        bt = sess.create_script(open(BULK_TAG_JS, encoding='utf-8').read())
        bt.on('message', lambda m, d: None)
        bt.load()
        bt.exports_sync.init_status()

        ftid = bt.exports_sync.find_tag_id_by_name(svc, 'Legendary')
        if not ftid.get('ok'):
            print(f"  ! 'Legendary' not on server: {ftid}")
            return
        tagproto = ftid['tagProtoAddr']
        print(f"  'Legendary' @ {tagproto}")

        uids_dec = sorted({str(int(u, 16)) for u in uids})
        proto_map = pg.find_protos_for_uids(sess, bag, uids_dec)
        print(f'  bag-walk: {len(proto_map)}/{len(uids_dec)} protos')

        protos = [proto_map.get(str(int(u, 16))) for u in uids]
        pairs = [(u, p) for u, p in zip(uids, protos) if p is not None]
        vuids = [u for u, _ in pairs]
        vprotos = [p for _, p in pairs]
        print(f'  {len(vprotos)} usable')

        done = []
        bad = []
        BATCH = 25
        i = 0
        while i < len(vprotos):
            cu = vuids[i:i+BATCH]; cp = vprotos[i:i+BATCH]
            res = bt.exports_sync.bulk_tag_many(svc, tagproto, cp)
            if res.get('ok') and res.get('built', 0) == len(cp):
                done.extend(cu)
                print(f"    ok {i}-{i+len(cp)}")
            else:
                print(f"    ! batch {i}: {res}")
                # fall back to one-by-one for this chunk
                for uh, pp in zip(cu, cp):
                    r2 = bt.exports_sync.bulk_tag_many(svc, tagproto, [pp])
                    if r2.get('ok') and r2.get('built', 0) == 1:
                        done.append(uh)
                    else:
                        bad.append((uh, r2))
                    time.sleep(0.3)
            i += BATCH
            if i < len(vprotos): time.sleep(0.5)

        print(f"\n  applied {len(done)}/{len(uids)}")
        if bad:
            print(f"  {len(bad)} stragglers failed even individually:")
            for uh, r in bad[:10]:
                print(f"    {uh}  {r}")

        # Mirror DB
        cnx = sqlite3.connect(DB); cur = cnx.cursor()
        for uh in done:
            row = cur.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
            tags = [t for t in ((row[0] if row else None) or '').split(';') if t]
            if 'Legendary' not in tags: tags.append('Legendary')
            cur.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
                        (';'.join(tags), uh))
        cnx.commit(); cnx.close()

        bt.unload()
    finally:
        sess.detach()


if __name__ == '__main__':
    main()

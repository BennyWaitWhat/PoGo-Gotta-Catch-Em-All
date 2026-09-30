"""Refine JUMBO down to the top-2 (weight ∪ height) per species. The 7
losers keep their data (they stay in_bag), only the JUMBO tag is removed.

Reads rescan_report/agent_tags/_jumbo_prune.json (the drop list pre-computed).
Single Frida session — bag-walk for the 7 protos, then bulkUntagOne per UID.
Mirror the change to DB auth_tag_names.
"""
import json, os, sqlite3, time
import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')
BULK_TAG_JS = os.path.join(HERE, 'bulk_tag.js')
PRUNE_FILE = os.path.join(HERE, 'rescan_report', 'agent_tags', '_jumbo_prune.json')


def main():
    with open(PRUNE_FILE, encoding='utf-8') as f:
        plan = json.load(f)
    drops = plan['drop']
    print(f'Untag {len(drops)} specimens from JUMBO (keepers: {plan["n_keep"]})')

    # Show what we're untagging
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    print()
    for uh in drops:
        r = conn.execute(
            "SELECT species_name, cp, iv_total, weight_kg, height_m FROM pokemon WHERE uid_hex=?",
            (uh,)).fetchone()
        if r:
            print(f'  {uh}  {r[0]:<14} cp={r[1]:>4}  iv={r[2]:>2}/45  weight={r[3]:.2f}kg  height={r[4]:.2f}m')
    conn.close()

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

        ftid = bt.exports_sync.find_tag_id_by_name(svc, 'JUMBO')
        if not ftid.get('ok'):
            print(f"  ! 'JUMBO' tag not found: {ftid}")
            return
        tagproto = ftid['tagProtoAddr']
        print(f"  JUMBO tagProto @ {tagproto}")

        uids_dec = sorted({str(int(u, 16)) for u in drops})
        proto_map = pg.find_protos_for_uids(sess, bag, uids_dec)
        print(f'  bag-walk: {len(proto_map)}/{len(uids_dec)} protos')

        done = []
        for uh in drops:
            dec = str(int(uh, 16))
            p = proto_map.get(dec)
            if p is None:
                print(f"  ! {uh} not in bag, skip")
                continue
            res = bt.exports_sync.bulk_untag_one(svc, p, tagproto)
            ok = res.get('ok')
            print(f"  {uh}  -> {res}")
            if ok:
                done.append(uh)
            time.sleep(0.4)

        bt.unload()

        # Mirror DB: strip 'JUMBO' from auth_tag_names for the dropped ones
        cnx = sqlite3.connect(DB); cur = cnx.cursor()
        for uh in done:
            row = cur.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
            tags = [t for t in ((row[0] if row else None) or '').split(';') if t and t != 'JUMBO']
            cur.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
                        (';'.join(tags) if tags else None, uh))
        cnx.commit(); cnx.close()
        print(f'\n  Untagged on server + DB: {len(done)}/{len(drops)}')
    finally:
        sess.detach()


if __name__ == '__main__':
    main()

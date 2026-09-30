"""Untag every member of the 3 review tags so we start with a clean slate.

Tags emptied:
  1. Shiny Evos
  2. Shadow Evos
  3. Purify

The tag definitions stay on the server (delete-via-RPC not implemented here);
you can delete them in-game in 2 taps each, or run a follow-up tag-delete script.
Membership is wiped to zero, which is what 'start clean' meant.
"""
import os, sqlite3, sys, time
import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')
BULK_TAG_JS = os.path.join(HERE, 'bulk_tag.js')

TAGS_TO_EMPTY = ['1. Shiny Evos', '2. Shadow Evos', '3. Purify']


def main():
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    plans = {}
    for tag in TAGS_TO_EMPTY:
        rows = conn.execute(
            "SELECT uid_hex FROM pokemon WHERE in_bag=1 AND auth_tag_names LIKE ?",
            ('%' + tag + '%',)
        ).fetchall()
        uids = [r[0] for r in rows if tag in (conn.execute(
            "SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (r[0],)
        ).fetchone()[0] or '').split(';')]
        plans[tag] = uids
    conn.close()

    total = sum(len(u) for u in plans.values())
    print(f'Plan: untag {total} memberships across {len(TAGS_TO_EMPTY)} tags')
    for tag, uids in plans.items():
        print(f'  {tag:18s}: {len(uids)} members')
    if total == 0:
        print('Nothing to do.')
        return

    all_uids_dec = sorted({str(int(u, 16)) for uids in plans.values() for u in uids})

    print('\nAttaching...')
    sess, pid = pg.get_session()
    print(f'  pid={pid}')

    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        print(f'  bag @ {bag}\n  svc @ {svc}')

        proto_map = pg.find_protos_for_uids(sess, bag, all_uids_dec)
        print(f'  bag-walk resolved {len(proto_map)}/{len(all_uids_dec)} protos')

        bt = sess.create_script(open(BULK_TAG_JS, encoding='utf-8').read())
        bt.on('message', lambda m, d: None)
        bt.load()
        bt.exports_sync.init_status()

        applied = {tag: [] for tag in plans}
        errors = {tag: [] for tag in plans}
        for tag, uids in plans.items():
            ftid = bt.exports_sync.find_tag_id_by_name(svc, tag)
            if not ftid.get('ok'):
                print(f'  ! tag {tag!r} not on server: {ftid}')
                continue
            tag_proto = ftid['tagProtoAddr']
            print(f"\n=== Untagging '{tag}' ({len(uids)} members) ===")
            for uh in uids:
                pp = proto_map.get(str(int(uh, 16)))
                if pp is None:
                    print(f"  SKIP {uh}: no proto")
                    continue
                res = bt.exports_sync.bulk_untag_one(svc, pp, tag_proto)
                if res.get('ok'):
                    applied[tag].append(uh)
                else:
                    errors[tag].append((uh, res))
                time.sleep(0.3)
            print(f'  untagged: {len(applied[tag])}/{len(uids)}')
            if errors[tag]:
                print(f'  errors: {len(errors[tag])} (likely proto staleness; rerun to retry)')
        bt.unload()
    finally:
        sess.detach()

    # Mirror to local DB
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    for tag, uids in applied.items():
        for uh in uids:
            cur = c.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
            if cur:
                tags = [t for t in (cur[0] or '').split(';') if t and t != tag]
                c.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
                          (';'.join(tags) if tags else None, uh))
    conn.commit()
    conn.close()

    print('\n=== Summary ===')
    for tag, uids in applied.items():
        n_err = len(errors[tag])
        marker = '!' if n_err else ' '
        print(f'  {marker} {tag:18s} untagged {len(uids)}/{len(plans[tag])}'
              + (f'  errors={n_err}' if n_err else ''))


if __name__ == '__main__':
    main()

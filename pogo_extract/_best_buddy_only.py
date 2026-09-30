"""Nuke ALL server tags. Create exactly one: 'Best Buddy'. Tag the 17 specimens
with was_best_buddy_badge=1. Done. No retries. Single Frida session.
"""
import os, sqlite3, sys, time, shutil
import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')
BULK_TAG_JS = os.path.join(HERE, 'bulk_tag.js')

JS_HELPERS = r"""
function enumerateTagsFull(svcAddrStr) {
    _ensureInit();
    var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, gnt = null, gctb = null;
    while ((m = IL2.cGM(svcCls, iter)) && !m.isNull()) {
        var nm = IL2.mGN(m).readCString();
        if (nm === 'get_NumberOfTags') gnt = m;
        if (nm === 'GetCachedTagToPokemonBindingForIndex') gctb = m;
    }
    var svc = ptr(svcAddrStr);
    var ret = rI(gnt, svc, ptr(0), null);
    var totalTags = ret.add(0x10).readS32();
    var out = [];
    for (var i = 0; i < totalTags; i++) {
        var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
        var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
        var bp = rI(gctb, svc, args, null);
        if (bp.isNull()) continue;
        var tagProto = bp.add(0x10).readPointer();
        var name = '';
        try {
            var ns = tagProto.add(0x40).readPointer();
            if (!ns.isNull()) {
                var len = ns.add(0x10).readS32();
                if (len > 0 && len < 100) {
                    var chars = [];
                    for (var ci = 0; ci < len; ci++) chars.push(String.fromCharCode(ns.add(0x14 + ci*2).readU16()));
                    name = chars.join('');
                }
            }
        } catch(e) {}
        var tagIdStr = '0';
        try { tagIdStr = tagProto.add(0x38).readU64().toString(); } catch(e) {}
        out.push({idx: i, name: name, tagId: tagIdStr});
    }
    return out;
}

function deleteTagById(svcAddrStr, tagIdStr) {
    _ensureInit();
    var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, dm = null;
    while ((m = IL2.cGM(svcCls, iter)) && !m.isNull()) {
        if (IL2.mGN(m).readCString() === 'DeleteTag') { dm = m; break; }
    }
    if (!dm) return {ok:false, err:'no DeleteTag'};
    var idBuf = Memory.alloc(8);
    idBuf.writeU64(uint64(tagIdStr));
    var args = Memory.alloc(Process.pointerSize);
    args.writePointer(idBuf);
    var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
    rI(dm, ptr(svcAddrStr), args, exc);
    if (!exc.readPointer().isNull()) return {ok:false, err:'exception'};
    return {ok:true};
}

rpc.exports.enumerateTagsFull = enumerateTagsFull;
rpc.exports.deleteTagById = deleteTagById;
"""


def main():
    # 1. Read DB → the 17 Best Buddy UIDs
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    bb_uids = [r[0] for r in conn.execute(
        "SELECT uid_hex, species_name, cp, iv_total FROM pokemon "
        "WHERE in_bag=1 AND was_best_buddy_badge=1 ORDER BY iv_total DESC, cp DESC"
    ).fetchall()]
    # Re-query to also show what we're tagging
    bb_rows = conn.execute(
        "SELECT uid_hex, species_name, cp, iv_total, level "
        "FROM pokemon WHERE in_bag=1 AND was_best_buddy_badge=1 "
        "ORDER BY iv_total DESC, cp DESC"
    ).fetchall()
    conn.close()
    print(f'Best Buddy candidates (was_best_buddy_badge=1): {len(bb_uids)}')
    for r in bb_rows:
        print(f"  {r[0]}  {r[1]:18s} cp={r[2]:>4} iv={r[3]:>2}/45 lvl={r[4]}")

    # Snapshot
    stamp = time.strftime('%Y-%m-%d_%H%M%S')
    snap = os.path.join(HERE, '.db_snapshots', f'pokemon.db.{stamp}.pre_bbonly.bak')
    os.makedirs(os.path.dirname(snap), exist_ok=True)
    shutil.copy2(DB, snap)
    print(f'\nSnapshot: {snap}')

    # 2. Single Frida session — nuke all + create + tag
    print('\nAttaching...')
    sess, pid = pg.get_session()
    print(f'  pid={pid}')

    try:
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        print(f'  svc @ {svc}\n  bag @ {bag}')

        helper = pg.get_script_with_helpers(sess, JS_HELPERS)

        # Nuke loop — delete all, re-enumerate, repeat until 0 (handles cache stragglers)
        for pass_no in range(4):
            tags = helper.exports_sync.enumerate_tags_full(svc)
            if not tags:
                print(f'\n  Pass {pass_no+1}: server clean (0 tags) OK')
                break
            print(f'\n  Pass {pass_no+1}: deleting {len(tags)} tag(s)...')
            for t in tags:
                helper.exports_sync.delete_tag_by_id(svc, t['tagId'])
                time.sleep(0.4)
            time.sleep(2)
        else:
            remaining = helper.exports_sync.enumerate_tags_full(svc)
            if remaining:
                print(f'  ! {len(remaining)} stubborn tag(s) remain after 4 passes; aborting')
                helper.unload()
                return
        helper.unload()

        # 3. Create the one tag + apply membership
        if not bb_uids:
            print('No Best Buddy specimens to tag. Server is clean. Done.')
            return

        bt = sess.create_script(open(BULK_TAG_JS, encoding='utf-8').read())
        bt.on('message', lambda m, d: None)
        bt.load()
        bt.exports_sync.init_status()

        print(f"\n  AddTag('Best Buddy', color=1) -> ", end='', flush=True)
        res = bt.exports_sync.add_tag_on_instance(svc, 'Best Buddy', 1)
        print(res)
        time.sleep(2)
        ftid = bt.exports_sync.find_tag_id_by_name(svc, 'Best Buddy')
        if not ftid.get('ok'):
            print(f"  ! 'Best Buddy' not findable after AddTag: {ftid}")
            bt.unload()
            return
        bb_proto = ftid['tagProtoAddr']
        print(f"  'Best Buddy' tagProto @ {bb_proto}")

        # Resolve protos for the 17 UIDs
        uids_dec = sorted({str(int(u, 16)) for u in bb_uids})
        proto_map = pg.find_protos_for_uids(sess, bag, uids_dec)
        print(f"  bag-walk resolved {len(proto_map)}/{len(uids_dec)} protos")

        # Single bulk_tag_many for the 17
        protos = [proto_map.get(str(int(u, 16))) for u in bb_uids]
        valid_pairs = [(u, p) for u, p in zip(bb_uids, protos) if p is not None]
        valid_uids = [u for u, _ in valid_pairs]
        valid_protos = [p for _, p in valid_pairs]
        print(f"\n=== Tagging 'Best Buddy' ({len(valid_protos)} specimens) ===")
        res = bt.exports_sync.bulk_tag_many(svc, bb_proto, valid_protos)
        print(f"  result: {res}")

        bt.unload()
    finally:
        sess.detach()

    # 4. Mirror DB: clear ALL auth_tag_names, set 'Best Buddy' on the applied ones
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE pokemon SET auth_tag_names=NULL WHERE in_bag=1")
    if res.get('ok') and res.get('built', 0) == len(valid_protos):
        for uh in valid_uids:
            c.execute("UPDATE pokemon SET auth_tag_names='Best Buddy' WHERE uid_hex=?", (uh,))
    conn.commit()
    conn.close()

    print(f"\n=== Done ===")
    print(f"  Server tags: 1 ('Best Buddy')")
    print(f"  Tagged: {len(valid_uids)}/{len(bb_uids)} Best Buddies")


if __name__ == '__main__':
    main()

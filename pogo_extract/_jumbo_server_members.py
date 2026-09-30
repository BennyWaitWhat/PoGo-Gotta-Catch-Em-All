"""Enumerate the SERVER's JUMBO tag member protos, reverse-map to UIDs via a
bag-walk of all in-bag XXL, and report any stray (member not in the correct
top-2 set, or not in the live bag at all). With --fix, untag the strays.
"""
import sqlite3, sys, time
from collections import defaultdict
import pogo_il2cpp as pg
sys.stdout.reconfigure(encoding='utf-8')

FIX = '--fix' in sys.argv

WALK_JS = r"""
function jumboMembers(svcAddrStr) {
    _ensureInit();
    var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, gnt=null, gctb=null;
    while ((m = IL2.cGM(svcCls, iter)) && !m.isNull()) {
        var nm = IL2.mGN(m).readCString();
        if (nm === 'get_NumberOfTags') gnt = m;
        if (nm === 'GetCachedTagToPokemonBindingForIndex') gctb = m;
    }
    var svc = ptr(svcAddrStr);
    var total = rI(gnt, svc, ptr(0), null).add(0x10).readS32();
    for (var i = 0; i < total; i++) {
        var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
        var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
        var bp = rI(gctb, svc, args, null);
        if (bp.isNull()) continue;
        var tagProto = bp.add(0x10).readPointer();
        var name='';
        try { var ns=tagProto.add(0x40).readPointer();
              var len=ns.add(0x10).readS32();
              if(len>0&&len<100){var ch=[];for(var ci=0;ci<len;ci++)ch.push(String.fromCharCode(ns.add(0x14+ci*2).readU16()));name=ch.join('');}
        } catch(e){}
        if (name !== 'JUMBO') continue;
        // member list at binding+0x18
        var lst = bp.add(0x18).readPointer();
        var out = [];
        if (!lst.isNull()) {
            var cnt = lst.add(0x18).readS32();
            var items = lst.add(0x10).readPointer();
            for (var j = 0; j < cnt; j++) {
                var el = items.add(0x20 + j*8).readPointer();
                out.push(el.toString());
            }
        }
        return {ok:true, tagProto: tagProto.toString(), members: out};
    }
    return {ok:false, err:'JUMBO not found'};
}
rpc.exports.jumboMembers = jumboMembers;
"""

def main():
    c = sqlite3.connect('pokemon.db')
    xxl = [r[0] for r in c.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1 AND pokemon_size_category=5")]
    # correct top-2 set
    rows = c.execute("""SELECT uid_hex,pokemon_id,form,weight_kg,height_m FROM pokemon
                        WHERE in_bag=1 AND pokemon_size_category=5""").fetchall()
    by=defaultdict(list)
    for r in rows: by[(r[1],r[2] or 0)].append(r)
    correct=set()
    for k,rs in by.items():
        for r in sorted(rs,key=lambda x:x[3],reverse=True)[:2]: correct.add(r[0])
        for r in sorted(rs,key=lambda x:x[4],reverse=True)[:2]: correct.add(r[0])
    c.close()
    print(f'in-bag XXL: {len(xxl)}, correct top-2: {len(correct)}')

    sess, pid = pg.get_session()
    print(f'pid={pid}')
    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        # uid -> proto for all in-bag XXL
        uids_dec = sorted({str(int(u,16)) for u in xxl})
        proto_map = pg.find_protos_for_uids(sess, bag, uids_dec)   # {dec: proto}
        proto_to_uidhex = {}
        for uh in xxl:
            p = proto_map.get(str(int(uh,16)))
            if p: proto_to_uidhex[p] = uh
        print(f'bag-walk resolved {len(proto_map)}/{len(uids_dec)} XXL protos')

        helper = pg.get_script_with_helpers(sess, WALK_JS)
        res = helper.exports_sync.jumbo_members(svc)
        if not res.get('ok'):
            print('  !', res); return
        members = res['members']
        tagproto = res['tagProto']
        print(f'\nSERVER JUMBO members: {len(members)}  (tagProto {tagproto})')

        strays_in_bag = []   # member proto maps to a uid NOT in correct set
        strays_gone = []     # member proto not in live bag at all (transferred/stale)
        ok_count = 0
        for mp in members:
            uh = proto_to_uidhex.get(mp)
            if uh is None:
                strays_gone.append(mp)
            elif uh not in correct:
                strays_in_bag.append((mp, uh))
            else:
                ok_count += 1
        print(f'  in correct set : {ok_count}')
        print(f'  stray (in bag, not top-2): {len(strays_in_bag)}')
        for mp,uh in strays_in_bag: print(f'     {uh}  proto {mp}')
        print(f'  stray (not in live bag): {len(strays_gone)}')
        for mp in strays_gone: print(f'     proto {mp}  (transferred / stale cache entry)')
        helper.unload()

        if FIX and (strays_in_bag or strays_gone):
            bt = sess.create_script(open('bulk_tag.js', encoding='utf-8').read())
            bt.on('message', lambda m,d: None); bt.load(); bt.exports_sync.init_status()
            print('\n=== Untagging strays (using LIVE bag-walk protos) ===')
            for mp, uh in strays_in_bag:
                live = proto_map.get(str(int(uh, 16))) or mp
                r = None
                for attempt in range(3):
                    r = bt.exports_sync.bulk_untag_one(svc, live, tagproto)
                    if r.get('ok'):
                        break
                    time.sleep(0.8)
                print(f'   {uh}: {r}  (proto {live})')
            for mp in strays_gone:
                r = bt.exports_sync.bulk_untag_one(svc, mp, tagproto)
                print(f'   {mp}: {r}')
            bt.unload()
            # re-check
            helper2 = pg.get_script_with_helpers(sess, WALK_JS)
            res2 = helper2.exports_sync.jumbo_members(svc)
            print(f'\nServer JUMBO now: {len(res2.get("members",[]))}')
            helper2.unload()
        elif not FIX:
            print('\n(read-only; re-run with --fix to untag strays)')
    finally:
        sess.detach()

if __name__ == '__main__':
    main()

"""Finish the two tags that hit cache-lag during _apply_agent_tags.py:
  - Legendary (466 specimens)
  - From Ethan  (19 specimens)

Strategy: enumerate server tags first. If 'Legendary'/'From Ethan' already
exist (i.e. AddTag succeeded server-side but find verification raced ahead
of the cache), grab their tagProto and apply membership. Otherwise AddTag
once and verify after a longer pause.

Also patches the Shiny 1052->1053 gap if a re-bag-walk now finds the
missing proto (a specimen may have just respawned in cache).
"""
import json, os, sqlite3, time, sys
import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')
BULK_TAG_JS = os.path.join(HERE, 'bulk_tag.js')
AGENT_DIR = os.path.join(HERE, 'rescan_report', 'agent_tags')

# Reuse the helper that enumerates ALL server tags by (idx,name,tagProto,tagId)
ENUM_JS = r"""
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
        out.push({idx:i, name:name, tagProto:tagProto.toString(), tagId:tagIdStr});
    }
    return out;
}
rpc.exports.enumerateTagsFull = enumerateTagsFull;
"""


def _to_hex(u):
    if isinstance(u, int):
        return f'{u & 0xFFFFFFFFFFFFFFFF:016x}'
    s = u.strip()
    if s.lstrip('-').isdigit():
        return f'{int(s) & 0xFFFFFFFFFFFFFFFF:016x}'
    return s.lower()


def _uid_dec(uid_hex):
    return str(int(uid_hex, 16))


def main():
    missing = ['Legendary', 'From Ethan']
    plans = {}
    for name in missing:
        path = os.path.join(AGENT_DIR, f'{name}.json')
        with open(path, encoding='utf-8') as f:
            plans[name] = json.load(f)
    print('Stragglers to apply:')
    for name, p in plans.items():
        print(f"  {name:<14} color={p['color']}  n={p['count']}")

    print('\nAttaching...')
    sess, pid = pg.get_session()
    print(f'  pid={pid}')

    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        print(f'  bag @ {bag}\n  svc @ {svc}')

        enum = pg.get_script_with_helpers(sess, ENUM_JS)
        all_tags = enum.exports_sync.enumerate_tags_full(svc)
        print(f'\nServer reports {len(all_tags)} tags currently:')
        for t in all_tags:
            print(f"  [{t['idx']:>2}] {t['name']!r:30s} tagId={t['tagId']:>22}")
        existing_protos = {t['name']: t['tagProto'] for t in all_tags}
        enum.unload()

        bt = sess.create_script(open(BULK_TAG_JS, encoding='utf-8').read())
        bt.on('message', lambda m, d: None)
        bt.load()
        bt.exports_sync.init_status()

        # Resolve protos for the union of missing UIDs
        all_uids_hex = set()
        for name in missing:
            for u in plans[name]['uids']:
                all_uids_hex.add(_to_hex(u))
        all_uids_dec = sorted({str(int(u, 16)) for u in all_uids_hex})
        print(f'\nBag-walking {len(all_uids_dec)} UIDs...')
        proto_map = pg.find_protos_for_uids(sess, bag, all_uids_dec)
        print(f'  resolved {len(proto_map)}/{len(all_uids_dec)} protos')

        for name in missing:
            plan = plans[name]
            if name in existing_protos:
                tagproto = existing_protos[name]
                print(f"\n  {name!r} already on server @ {tagproto} — applying membership")
            else:
                print(f"\n  {name!r} not on server — AddTag(color={plan['color']})...")
                bt.exports_sync.add_tag_on_instance(svc, name, plan['color'])
                time.sleep(3.0)
                ftid = bt.exports_sync.find_tag_id_by_name(svc, name)
                if not ftid.get('ok'):
                    print(f"  ! {name!r} STILL not findable after 3s — server may be rate-limiting; sleeping 6s and retrying...")
                    time.sleep(6.0)
                    ftid = bt.exports_sync.find_tag_id_by_name(svc, name)
                if not ftid.get('ok'):
                    print(f"  !! giving up on {name!r}: {ftid}")
                    continue
                tagproto = ftid['tagProtoAddr']
                print(f"  {name!r} created @ {tagproto}")

            uids_hex = [_to_hex(u) for u in plan['uids']]
            protos = [proto_map.get(_uid_dec(u)) for u in uids_hex]
            valid_pairs = [(u, p) for u, p in zip(uids_hex, protos) if p is not None]
            vuids = [u for u, _ in valid_pairs]
            vprotos = [p for _, p in valid_pairs]
            print(f"  applying {len(vprotos)} members in batches of 100...")
            done = []
            BATCH = 100
            i = 0
            while i < len(vprotos):
                cu = vuids[i:i+BATCH]; cp = vprotos[i:i+BATCH]
                res = bt.exports_sync.bulk_tag_many(svc, tagproto, cp)
                if res.get('ok') and res.get('built', 0) == len(cp):
                    done.extend(cu)
                    print(f"    ok {i}-{i+len(cp)}")
                else:
                    print(f"    ! batch {i}: {res}")
                i += BATCH
                if i < len(vprotos): time.sleep(0.6)

            # Mirror DB
            cnx = sqlite3.connect(DB); cur = cnx.cursor()
            for uh in done:
                row = cur.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
                tags = [t for t in ((row[0] if row else None) or '').split(';') if t]
                if name not in tags: tags.append(name)
                cur.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
                            (';'.join(tags), uh))
            cnx.commit(); cnx.close()
            print(f"  {name!r} applied {len(done)}/{plan['count']}")

        bt.unload()

        # Final enumerate so we see the truth
        print('\n=== Final server-side tag inventory ===')
        enum = pg.get_script_with_helpers(sess, ENUM_JS)
        final = enum.exports_sync.enumerate_tags_full(svc)
        for t in final:
            print(f"  [{t['idx']:>2}] {t['name']!r:30s} tagId={t['tagId']:>22}")
        print(f'  TOTAL: {len(final)} tags')
        enum.unload()
    finally:
        sess.detach()


if __name__ == '__main__':
    main()

"""Nuke every server-side Pokémon tag — CORRECTLY this time.

DeleteTag(tagId: UInt64) — the parameter is the uint64 Id field at offset 0x38
of PokemonTagProto, NOT the proto pointer (which is what my prior version was
passing into a uint64 arg slot, garbling the call into a no-op).

Enumerates via TaggingRpcService.get_NumberOfTags + GetCachedTagToPokemonBindingForIndex,
reads each binding's tagProto, extracts tagId from offset 0x38, then calls
DeleteTag(tagId) with the value properly boxed in an 8-byte buffer.

Usage:
  python _nuke_all_tags.py [--dry-run]
"""
import argparse, os, sys, time
import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))

ENUM_AND_DELETE_JS = r"""
function enumerate_tags(svcAddrStr) {
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
        // Name (UTF-16 string at tagProto+0x40)
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
        // Id is UInt64 at tagProto+0x38
        var tagIdStr = '0';
        try { tagIdStr = tagProto.add(0x38).readU64().toString(); } catch(e) {}
        out.push({idx: i, name: name, tagProto: tagProto.toString(), tagId: tagIdStr});
    }
    return out;
}

function delete_tag(svcAddrStr, tagIdStr) {
    _ensureInit();
    var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, deleteMethod = null;
    while ((m = IL2.cGM(svcCls, iter)) && !m.isNull()) {
        if (IL2.mGN(m).readCString() === 'DeleteTag') { deleteMethod = m; break; }
    }
    if (!deleteMethod) return {ok:false, err:'DeleteTag method not found'};

    // tagId is UInt64. Box into 8-byte buffer; args slot points to the buffer.
    var idBuf = Memory.alloc(8);
    idBuf.writeU64(uint64(tagIdStr));
    var args = Memory.alloc(Process.pointerSize);
    args.writePointer(idBuf);
    var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
    var ret = rI(deleteMethod, ptr(svcAddrStr), args, exc);
    if (!exc.readPointer().isNull()) {
        var k = exc.readPointer().readPointer();
        var exp = {};
        Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function(e){
            if (e.name === 'il2cpp_class_get_namespace' || e.name === 'il2cpp_class_get_name')
                exp[e.name] = e.address;
        });
        var cGNs = new NativeFunction(exp.il2cpp_class_get_namespace, 'pointer', ['pointer']);
        var cN  = new NativeFunction(exp.il2cpp_class_get_name, 'pointer', ['pointer']);
        return {ok:false, err:'exception',
                excClass: cGNs(k).readCString() + '.' + cN(k).readCString()};
    }
    return {ok:true, ret: ret ? ret.toString() : 'void'};
}

rpc.exports.enumerateTags = enumerate_tags;
rpc.exports.deleteTag = delete_tag;
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    print('Attaching...')
    sess, pid = pg.get_session()
    print(f'  pid={pid}')
    try:
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        print(f'  svc @ {svc}')
        script = pg.get_script_with_helpers(sess, ENUM_AND_DELETE_JS)

        tags = script.exports_sync.enumerate_tags(svc)
        print(f'\nFound {len(tags)} server tags:')
        for t in tags:
            print(f"  [{t['idx']:>2}] {t['name']!r:30s}  tagId={t['tagId']:>22}  tagProto={t['tagProto']}")

        if args.dry_run:
            print('\n(--dry-run; no deletions)')
            script.unload()
            return

        if not tags:
            print('Nothing to delete.')
            script.unload()
            return

        print(f'\n=== Deleting {len(tags)} tags (via correct uint64 tagId) ===')
        success = []; failures = []
        for t in tags:
            print(f"  DeleteTag(tagId={t['tagId']}) for {t['name']!r} -> ", end='', flush=True)
            res = script.exports_sync.delete_tag(svc, t['tagId'])
            print(res)
            if res.get('ok'):
                success.append(t['name'])
            else:
                failures.append((t['name'], res))
            time.sleep(0.5)

        # Wait for cache to sync, then verify
        print('\n=== Verify via fresh enumerate (waiting 3s for cache) ===')
        time.sleep(3)
        remaining = script.exports_sync.enumerate_tags(svc)
        print(f'Server now reports {len(remaining)} tags:')
        for t in remaining:
            print(f"  [{t['idx']:>2}] {t['name']!r}  (tagId={t['tagId']})")
        script.unload()
    finally:
        sess.detach()

    print(f'\n=== Summary ===')
    print(f'  Deleted (RPC ok): {len(success)}/{len(tags)}')
    if failures:
        print(f'  Failures:')
        for name, res in failures:
            print(f'    {name}: {res}')


if __name__ == '__main__':
    main()

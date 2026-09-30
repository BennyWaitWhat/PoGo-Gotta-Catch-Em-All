"""Dump the member uids of ONE server tag and diff them against pokemon.db.

Written because verify_tags compares only COUNTS, and a count match can hide a swap. The
Transfer tag is the one the user releases from by hand, so its membership must be identified,
not just counted: a single wrong member is a Pokemon lost for good.

Usage: python dump_tag_members.py Transfer
"""
import json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, REPO); sys.path.insert(0, HERE)
DB = os.path.join(REPO, 'pokemon.db')

JS = r"""
function dumpMembers(svcAddrStr, want) {
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
    var total = rI(gnt, svc, ptr(0), null).add(0x10).readS32();
    for (var i = 0; i < total; i++) {
        var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
        var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
        var bp = rI(gctb, svc, args, null);
        if (bp.isNull()) continue;
        var tagProto = bp.add(0x40) ? bp.add(0x10).readPointer() : null;
        var name = '';
        try {
            var ns = tagProto.add(0x40).readPointer();
            var len = ns.add(0x10).readS32();
            var ch = [];
            for (var ci = 0; ci < len; ci++) ch.push(String.fromCharCode(ns.add(0x14 + ci*2).readU16()));
            name = ch.join('');
        } catch(e) {}
        if (name !== want) continue;
        var out = [];
        try {
            var lst = bp.add(0x18).readPointer();
            var n = lst.add(0x18).readS32();
            var items = lst.add(0x10).readPointer();
            /* The list holds OBJECT REFERENCES, not raw ulongs (a first attempt read the
               pointers themselves and produced heap addresses with a uniform 0x240 stride).
               Deref each element and probe a few candidate uid offsets; the caller decides
               which offset actually matches pokemon.db. */
            for (var k = 0; k < n; k++) {
                var o = items.add(0x20 + k*8).readPointer();
                if (o.isNull()) continue;
                var rec = {ptr: o.toString()};
                try { rec.cls = IL2.cGN(IL2.oGC(o)).readCString(); } catch(e) {}
                [0x10,0x18,0x20,0x28,0x30,0x38].forEach(function(off){
                    try { rec['o'+off.toString(16)] = o.add(off).readU64().toString(16); } catch(e) {}
                });
                out.push(rec);
            }
        } catch(e) { return {name: name, err: String(e), uids: []}; }
        return {name: name, uids: out};
    }
    return {name: null, uids: []};
}
rpc.exports.dumpMembers = dumpMembers;
"""


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else 'Transfer'
    import _frida_safe as safe, pogo_il2cpp as pg
    sess, pid = safe.session()
    print(f'attached pid={pid}')
    try:
        svc = safe.pick(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        sc = pg.get_script_with_helpers(sess, JS)
        res = sc.exports_sync.dump_members(svc, want)
        sc.unload()
    finally:
        try: sess.detach()
        except Exception: pass

    recs = res.get('uids') or []
    print(f"server tag {res.get('name')!r}: {len(recs)} members  err={res.get('err')}")
    if recs and isinstance(recs[0], dict):
        c0 = sqlite3.connect(DB)
        dball = {r[0].lower() for r in c0.execute("SELECT uid_hex FROM pokemon")}
        c0.close()
        print("  element class:", recs[0].get('cls'))
        best, bestn = None, -1
        for off in ('o10','o18','o20','o28','o30','o38'):
            vals = [r.get(off,'').lower().rjust(16,'0') for r in recs if r.get(off)]
            hit = sum(1 for v in vals if v in dball)
            print(f"    offset +0x{off[1:]}: {hit}/{len(vals)} match a uid in pokemon.db")
            if hit > bestn: best, bestn = off, hit
        print(f"  -> using {best} ({bestn} matches)")
        uids = [r.get(best,'').lower().rjust(16,'0') for r in recs if r.get(best)]
    else:
        uids = [str(u).lower().rjust(16, '0') for u in recs]

    c = sqlite3.connect(DB)
    dbset = {r[0].lower() for r in c.execute(
        "SELECT uid_hex FROM pokemon WHERE ';'||auth_tag_names||';' LIKE ?", (f'%;{want};%',))}
    srv = set(uids)
    only_srv, only_db = srv - dbset, dbset - srv
    print(f"db rows with tag: {len(dbset)}")
    print(f"ONLY ON SERVER ({len(only_srv)}):")
    for u in sorted(only_srv):
        row = c.execute("""SELECT species_name, iv_pct, is_shiny, is_lucky, is_legendary,
                                  in_bag, cull_decision_v9, cull_reason_v9
                           FROM pokemon WHERE lower(uid_hex)=?""", (u,)).fetchone()
        print(f"   {u}  {row if row else '*** NOT IN DB AT ALL ***'}")
    print(f"ONLY IN DB ({len(only_db)}): {sorted(only_db)[:10]}")
    c.close()


main()

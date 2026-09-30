"""Remove server tag members that pokemon.db no longer tags.

WHY THIS EXISTS: tag_ops.py `apply` is ADD-ONLY. It pushes the DB's members onto the tag but
never removes anyone, so a mon that stops qualifying keeps its tag on the server forever. That
is harmless for a label tag and dangerous for `Transfer`, which is the pile the user releases
from by hand: on 2026-08-19 a legendary Groudon (82.2%, decision=KEEP, reason=legendary) was
found still sitting on the server's Transfer tag after the DB had already dropped it.

Membership uids live at +0x20 of each element object in the binding's list (verified 154/154
against pokemon.db; the elements are object refs, not raw ulongs).

Usage:
  python prune_server_tag.py Transfer --dry
  python prune_server_tag.py Transfer
"""
import sys, argparse, os, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, REPO); sys.path.insert(0, HERE)
DB = os.path.join(REPO, 'pokemon.db')
from tag_ops import is_pile_tag as _is_pile   # distinct name: main() re-imports tag_ops locally

ENUM_JS = r"""
function tagMembers(svcAddrStr, want) {
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
        var ib = Memory.alloc(4); ib.writeS32(i);
        var args = Memory.alloc(Process.pointerSize); args.writePointer(ib);
        var bp = rI(gctb, svc, args, null);
        if (bp.isNull()) continue;
        var name = '';
        try {
            var ns = bp.add(0x10).readPointer().add(0x40).readPointer();
            var len = ns.add(0x10).readS32(); var ch = [];
            for (var ci = 0; ci < len; ci++) ch.push(String.fromCharCode(ns.add(0x14+ci*2).readU16()));
            name = ch.join('');
        } catch(e) {}
        if (name !== want) continue;
        var out = [];
        var lst = bp.add(0x18).readPointer();
        var n = lst.add(0x18).readS32();
        var items = lst.add(0x10).readPointer();
        for (var k = 0; k < n; k++) {
            var o = items.add(0x20 + k*8).readPointer();
            if (!o.isNull()) out.push(o.add(0x20).readU64().toString(16));  /* uid @ +0x20 */
        }
        return out;
    }
    return [];
}
rpc.exports.tagMembers = tagMembers;
"""


def main():
    # 2026-09-07 PILE GATE: this tool has no keeper check and no pre-flight stamp. The release pile
    # is synced ONLY by preflight_transfer.py -> prune_tags.py --atomic (bidirectional, stamp-gated).
    # Label tags remain usable here. Checked before any attach so a refusal never costs a Frida session.
    for _a in sys.argv[1:]:
        if _is_pile(_a):
            sys.exit("REFUSING: '%s' is the irreversible release pile. Use preflight_transfer.py -> "
                     "prune_tags.py --atomic, which verifies the pre-flight stamp." % _a)
    ap = argparse.ArgumentParser()
    ap.add_argument('tag')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    import _frida_safe as safe, pogo_il2cpp as pg, tag_ops

    conn = sqlite3.connect(DB)
    # 2026-09-07 exact containment, NOT LIKE. The old '%;{tag};%' pattern let a name carrying a
    # LIKE wildcard resolve the release pile's membership while is_pile_tag() returned False for
    # that same spelling ('_ransfer', 'Transfe%' -> the pile's 25 rows, gate says not-pile).
    # Same test as tag_ops.cmd_apply, so 'which rows does this tag name select' has ONE answer.
    dbset = {r[0].lower().rjust(16, '0') for r in conn.execute(
        "SELECT uid_hex FROM pokemon WHERE in_bag=1 AND "
        "instr(';'||COALESCE(auth_tag_names,'')||';', ';'||?||';') > 0",
        (a.tag,))}

    sess, pid = safe.session()
    print(f'attached pid={pid}')
    try:
        svc = safe.pick(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        sc = pg.get_script_with_helpers(sess, ENUM_JS)
        srv = [u.lower().rjust(16, '0') for u in (sc.exports_sync.tag_members(svc, a.tag) or [])]
        sc.unload()
        stale = sorted(set(srv) - dbset)
        print(f"server={len(srv)} db={len(dbset)} stale={len(stale)}")
        if not stale:
            print("nothing to prune"); return 0

        # Identify every stale member before touching anything -- a keeper on this tag is the
        # whole reason the prune exists, so it gets named in the log, not silently dropped.
        for u in stale:
            row = conn.execute(
                "SELECT species_name, iv_pct, cull_decision_v9, cull_reason_v9 FROM pokemon "
                "WHERE lower(uid_hex)=?", (u,)).fetchone()
            print(f"   STALE {u}  {row if row else '(not in db)'}")
        if a.dry:
            print("dry run -- nothing removed"); return 0

        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        uid_decs = sorted({str(int(u, 16)) for u in stale})
        proto_map = pg.find_protos_for_uids(sess, bag, uid_decs)
        print(f"bag-walk: {len(proto_map)}/{len(uid_decs)} protos resolved")

        bt = tag_ops._load_bulk_tag_script(sess)
        try:
            tag_ops.ensure_ready(sess, svc, bt)
            tp = tag_ops.create_tag(bt, svc, a.tag, 1)   # find-or-create; returns the tagproto
            changes = [{'proto': proto_map[d], 'remove': [tp]}
                       for d in uid_decs if d in proto_map]
            n = tag_ops.apply_changes(bt, svc, changes)
            print(f"removed {n}/{len(changes)} stale members from '{a.tag}'")
        finally:
            bt.unload()
    finally:
        try: sess.detach()
        except Exception: pass
        conn.close()
    return 0


sys.exit(main())

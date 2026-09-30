"""fix_remote_trade_binding.py -- ONE-SHOT (2026-09-19): put the shiny trade offers into the GAME's own Remote Trade
tag, and delete the look-alike user tag I created by mistake.

What I got wrong: the "Remote Trade" tag on his Tags screen ("Visible to Forever Friends") is NOT an ordinary user
tag. TaggingRpcService exposes it -- like Favorites -- through `get_RemoteTradeTagBinding`, outside the numbered tag
list that `GetCachedTagToPokemonBindingForIndex` walks. My lookup therefore did not find it (and my name-keyed dict
would have hidden it anyway), create_tag made a SECOND tag with the same name, and his 17 stayed untouched.

This repair, in one gated session:
  1. read the real binding (tagProto + current members) from get_RemoteTradeTagBinding;
  2. find the duplicate ordinary tag named "Remote Trade" in the numbered list;
  3. per-mon deltas -- every pick gains the REAL tag and loses the duplicate; his old members that are not picks lose
     the real tag (the "clean out the current ones" he asked for);
  4. verify off the binding itself, then DeleteTag the emptied duplicate and mirror pokemon.db.
Never releases anything.
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
os.chdir(ROOT)

TAG = 'Remote Trade'
PICKS = os.path.join(ROOT, 'system', 'analysis', '_remote_trade_picks.json')
norm = lambda u: format(int(u, 16), 'x')

BINDING_JS = r"""
function readBinding(bp) {
    var out = {tagProto: null, members: []};
    if (bp.isNull()) return out;
    out.tagProto = bp.add(0x10).readPointer().toString();
    try {
        var lst = bp.add(0x18).readPointer();
        if (!lst.isNull()) {
            var cnt = lst.add(0x18).readS32();
            var items = lst.add(0x10).readPointer();
            for (var j = 0; j < cnt; j++) {
                var el = items.add(0x20 + j * 8).readPointer();
                if (!el.isNull()) out.members.push(el.toString());
            }
        }
    } catch (e) { out.err = e.toString(); }
    return out;
}
rpc.exports.remoteTradeBinding = function(svcAddrStr) {
    _ensureInit();
    var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
    var m, g = null;
    while ((m = IL2.cGM(svcCls, it)) && !m.isNull()) {
        if (IL2.mGN(m).readCString() === 'get_RemoteTradeTagBinding') { g = m; break; }
    }
    if (!g) return {err: 'no get_RemoteTradeTagBinding'};
    return readBinding(rI(g, ptr(svcAddrStr), ptr(0), null));
};
"""


def main():
    import pogo_il2cpp as pg, tag_ops
    from reconcile_tags import ENUM_MEMBERS_JS
    from ready_gate import ensure_ready_for_writes
    from nuke_all_tags import JS as NUKE_JS

    want_all = {norm(u) for u in json.load(open(PICKS, encoding='utf-8'))}
    pg.wait_ready_to_attach(timeout_s=300)
    sess, pid = pg.get_session(); print('attached pid %d' % pid)
    try:
        ensure_ready_for_writes(sess, pid)
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        bm = pg.walk_bag_protos(sess, bag)
        h2p = {format(int(d), 'x'): pp for d, pp in bm.items()}
        p2h = {pp: uh for uh, pp in h2p.items()}
        want = {u for u in want_all if u in h2p}
        print('bag-walk %d protos | picks live in the bag: %d/%d' % (len(h2p), len(want), len(want_all)))

        sc = pg.get_script_with_helpers(sess, BINDING_JS)
        try:
            b = sc.exports_sync.remote_trade_binding(svc)
        finally:
            sc.unload()
        if b.get('err') or not b.get('tagProto'):
            raise SystemExit('ABORT: could not read the Remote Trade binding: %s' % b)
        real_proto = b['tagProto']
        real_mem = {p2h[p] for p in b['members'] if p in p2h}
        print("the GAME's Remote Trade tag: proto %s, %d member(s)" % (real_proto, len(real_mem)))

        en = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
        try:
            listed = en.exports_sync.enumerate_all_tag_members(svc)
        finally:
            en.unload()
        dupes = [t for t in listed if t['name'] == TAG and t['tagProto'] != real_proto]
        print('duplicate ordinary tag(s) named %r: %d' % (TAG, len(dupes)))
        dupe_proto = dupes[0]['tagProto'] if dupes else None
        dupe_mem = {p2h[p] for p in (dupes[0].get('members') or []) if p in p2h} if dupes else set()

        deltas = {}
        for u in want:
            add = [real_proto] if u not in real_mem else []
            rem = [dupe_proto] if (dupe_proto and u in dupe_mem) else []
            if add or rem:
                deltas[u] = {'add': add, 'remove': rem}
        for u in real_mem - want:                       # clean out the ones that were tagged before
            if u in h2p:
                deltas.setdefault(u, {'add': [], 'remove': []})['remove'].append(real_proto)
        for u in dupe_mem - want:
            if u in h2p and dupe_proto:
                deltas.setdefault(u, {'add': [], 'remove': []})['remove'].append(dupe_proto)
        print('change records: %d (adds %d, removes %d)'
              % (len(deltas), sum(len(d['add']) for d in deltas.values()), sum(len(d['remove']) for d in deltas.values())))

        bt = tag_ops._load_bulk_tag_script(sess)
        try:
            tag_ops.ensure_ready(sess, svc, bt)
            try:
                bt.exports_sync.bulk_apply_changes(svc, [])
            except Exception as e:
                print('  (warm-up threw, ignored: %s)' % e)
            time.sleep(0.5)
            changes = [{'proto': h2p[u], 'add': d['add'], 'remove': d['remove']} for u, d in sorted(deltas.items())]
            n = tag_ops.apply_changes(bt, svc, changes, batch=150)
            print('apply_changes -> %d/%d' % (n, len(changes)))
            if n != len(changes):
                raise SystemExit('ABORT: partial apply -- duplicate NOT deleted, nothing mirrored.')
        finally:
            bt.unload()

        print('\n=== VERIFY off the binding ===')
        ok = False
        for attempt in range(3):
            time.sleep(5 if attempt == 0 else 7)
            bm2 = pg.walk_bag_protos(sess, bag)
            q2h = {pp: format(int(d), 'x') for d, pp in bm2.items()}
            sc = pg.get_script_with_helpers(sess, BINDING_JS)
            try:
                b2 = sc.exports_sync.remote_trade_binding(svc)
            finally:
                sc.unload()
            got = {q2h[p] for p in (b2.get('members') or []) if p in q2h}
            print('  attempt %d: the game tag has %d member(s) (want %d)' % (attempt + 1, len(got), len(want)))
            if got == want:
                ok = True; break
        if not ok:
            print('DRIFT -- duplicate NOT deleted. Re-run to settle.'); return 1

        sc = pg.get_script_with_helpers(sess, NUKE_JS)
        try:
            full = sc.exports_sync.enum_tags_full(svc)
            tid = next((t['tagId'] for t in full if t['name'] == TAG and int(t.get('memberCount') or 0) == 0), None)
            if tid is None:
                print('the emptied duplicate is not visible yet -- run again shortly to delete it.'); return 1
            print('DeleteTag(duplicate %r id=%s) -> %s' % (TAG, tid, sc.exports_sync.del_tag(svc, tid)))
        finally:
            sc.unload()
        tag_ops._mirror_db(TAG, sorted(want))
        print('DONE: the game\'s Remote Trade tag holds %d shiny offers; the duplicate is deleted.' % len(want))
        return 0
    finally:
        sess.detach()


if __name__ == '__main__':
    sys.exit(main())

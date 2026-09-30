"""Order the in-game tag list: the tags you act on first (user 2026-09-24: "reorder all the tags, but the most active
ones i use on top" -> "Ok" to the proposed order).

HOW THE GAME STORES IT (read live 2026-09-24): Holoholo.Rpc.PokemonTagProto = Id @0x38 (UInt64), Name @0x40,
Color @0x48, SortIndex @0x4c (Int32, 0-based: the list shows 0 first). A change is saved through
TaggingRpcService.EditTag(editedTag, updateCacheSubscribers), which sends EditPokemonTagProto{repeated TagToEdit} and
returns IPromise<EditPokemonTagOutProto>; the server answers one EditResult per tag (Success=1, TagDoesNotExist=3,
InvalidTagName=4, InvalidTagSortIndex=5, ...). This script writes ONLY SortIndex, waits for the server's answer to
every edit, and stops on anything but Success. Name, id, colour and members are never written -- it cannot touch
what the Transfer tag holds.

  python system/scripts/order_tags.py --read      # the live order
  python system/scripts/order_tags.py --dry-run   # the edits it would send
  python system/scripts/order_tags.py --test      # a no-change save, then swap XXL <-> Hundo (the mechanics test)
  python system/scripts/order_tags.py             # apply ORDER; no-op when the phone already matches
"""
import json, os, sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
os.chdir(ROOT)

# THE ORDER (user 2026-09-24 "Ok"): things you act on, then PvP reference, then collection reference. Tags not listed
# keep their relative order after these.
ORDER = [
    'Transfer',                        # FIRST (user 2026-09-30: "can you please put the transfers tag on top?")
    # WHAT TO DO, ON TOP (user 2026-09-26: "And always put them on top."): Stop at <stage> (spliced in below), then the
    # dust advice. Names say the action (granular_tags POWER_UP_GL / SECOND_MOVE).
    'Evolve Once', 'Evolve Twice', 'Evolve Gated', 'Evolve for GL', 'Evolve for UL',   # the folds (2026-09-29, -30)
    'Power Up to 1500', 'Power Up to 2500', 'Unlock 2nd Move',
    'GL Rank 1-5', 'UL Rank 1-5', 'GL 1-5 No Evolve', 'UL 1-5 No Evolve', 'Best GL', 'Best UL', 'Best ML', '0-15-15',
    'Hundo', 'Nundo', 'XXL', 'Shiny - Only One', 'Shiny #4+', 'Legacy Moves', 'Adventure Effect', 'Ultra Beast',
    'Never Cull', 'Traded by E+F', 'Variant #1', 'Variant #2', 'Variant #3', 'Variant #4+',
    'Safety Hold',                     # only on the phone while something is held for bad data; last, out of the way
]
import granular_tags as _gt
RESULT = {0: 'Unset', 1: 'Success', 2: 'ErrorPlayerLevelTooLow', 3: 'TagDoesNotExist', 4: 'InvalidTagName',
          5: 'InvalidTagSortIndex', 6: 'TagNameContainsProfanity'}

JS = r"""
var API = null;
function _api() {
    if (API) return API;
    _ensureInit();
    var e = {};
    Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function (s) {
        if (s.name.indexOf('il2cpp_') === 0) e[s.name] = s.address;
    });
    function b(n, r, a) { return e[n] ? new NativeFunction(e[n], r, a) : null; }
    API = {oc: b('il2cpp_object_get_class', 'pointer', ['pointer']),
           flds: b('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']),
           fnm: b('il2cpp_field_get_name', 'pointer', ['pointer']),
           foff: b('il2cpp_field_get_offset', 'size_t', ['pointer']),
           ftyp: b('il2cpp_field_get_type', 'pointer', ['pointer']),
           fflg: b('il2cpp_field_get_flags', 'int', ['pointer']),
           tnm: b('il2cpp_type_get_name', 'pointer', ['pointer']),
           cft: b('il2cpp_class_from_type', 'pointer', ['pointer']),
           isVT: b('il2cpp_class_is_valuetype', 'bool', ['pointer']),
           cnm: b('il2cpp_class_get_name', 'pointer', ['pointer']),
           parent: b('il2cpp_class_get_parent', 'pointer', ['pointer']),
           ghNew: b('il2cpp_gchandle_new', 'pointer', ['pointer', 'bool']),     // Il2CppGCHandle is a POINTER (Unity 2021.2+)
           ghGet: b('il2cpp_gchandle_get_target', 'pointer', ['pointer']),
           ghFree: b('il2cpp_gchandle_free', 'void', ['pointer'])};
    return API;
}
function _classFields(k) {
    var y = _api(), it = Memory.alloc(8), f, out = [];
    it.writePointer(ptr(0));
    while ((f = y.flds(k, it)) && !f.isNull()) {
        if (y.fflg(f) & 0x10) continue;                               // static
        var t = y.ftyp(f);
        out.push({name: y.fnm(f).readCString(), off: Number(y.foff(f)), type: y.tnm(t).readCString(),
                  vt: y.isVT(y.cft(t)) ? 1 : 0});
    }
    return out;
}
function _method(name) {
    var cl = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
    var m;
    while ((m = IL2.cGM(cl, it)) && !m.isNull()) { if (IL2.mGN(m).readCString() === name) return m; }
    return null;
}
function _str(p) {
    if (p.isNull()) return null;
    var n = p.add(0x10).readS32();
    return (n >= 0 && n < 200) ? p.add(0x14).readUtf16String(n) : null;
}
// Field offsets by NAME from the live class, so a game update that moves them cannot make this write a wrong field.
var OFF = null;
function _off(tp) {
    if (OFF) return OFF;
    var o = {};
    _classFields(_api().oc(tp)).forEach(function (f) { o[f.name] = f; });
    if (!o.Id || !o.Name || !o.SortIndex || !/UInt64/.test(o.Id.type) || !/String/.test(o.Name.type) || !/Int32/.test(o.SortIndex.type))
        throw new Error('PokemonTagProto layout changed: ' + JSON.stringify(Object.keys(o)));
    OFF = {id: o.Id.off, name: o.Name.off, sort: o.SortIndex.off, color: o.Color ? o.Color.off : null};
    return OFF;
}
function _tags(svc) {
    var gn = _method('get_NumberOfTags'), gb = _method('GetCachedTagToPokemonBindingForIndex');
    var tot = rI(gn, ptr(svc), ptr(0), null).add(0x10).readS32();
    var out = [];
    for (var i = 0; i < tot; i++) {
        var ib = Memory.alloc(4); ib.writeS32(i);
        var ar = Memory.alloc(Process.pointerSize); ar.writePointer(ib);
        var bp = rI(gb, ptr(svc), ar, null);
        if (bp.isNull()) continue;
        var tp = bp.add(0x10).readPointer(), o = _off(tp);
        out.push({addr: tp.toString(), id: tp.add(o.id).readU64().toString(), name: _str(tp.add(o.name).readPointer()),
                  sort: tp.add(o.sort).readS32(), color: o.color === null ? null : tp.add(o.color).readS32()});
    }
    return out;
}
// A managed object's fields, one level deep. Reference fields are only followed when the metadata says the field is
// a reference type (never a struct read as a pointer), and EditPokemonTagOutProto.EditResult is decoded.
function _repeated(rf) {
    var y = _api(), arr = null, cnt = null, fl = _classFields(y.oc(rf));
    fl.forEach(function (f) {
        if (/\[\]$/.test(f.type)) arr = rf.add(f.off).readPointer();
        else if (/Int32/.test(f.type)) cnt = rf.add(f.off).readS32();
    });
    var diag = {fields: fl.map(function (f) { return f.name + '@' + f.off + ':' + f.type; }), arr: arr && arr.toString(), count: cnt};
    if (arr === null || cnt === null || cnt < 0 || cnt > 64) return diag;
    try {
        var v = [];
        for (var i = 0; i < cnt; i++) v.push(arr.add(0x20 + 4 * i).readS32());
        return v;
    } catch (e) { diag.err = String(e); return diag; }
}
function _allFields(k) {                                          // own + inherited (the value lives in the base Promise)
    var y = _api(), out = [];
    for (var c = k; c && !c.isNull(); c = y.parent(c)) {
        if (y.cnm(c).readCString() === 'Object') break;
        out = out.concat(_classFields(c));
    }
    return out;
}
function _dump(obj) {
    var y = _api(), o = {cls: y.cnm(y.oc(obj)).readCString(), f: {}};
    _allFields(y.oc(obj)).forEach(function (f) {
        var a = obj.add(f.off);
        if (f.vt) { o.f[f.name] = /Boolean|Byte/.test(f.type) ? a.readU8() : a.readS32(); return; }
        var p = a.readPointer();
        if (p.isNull()) { o.f[f.name] = null; return; }
        var c = y.cnm(y.oc(p)).readCString();
        if (c === 'EditPokemonTagOutProto') {
            var rf = p.add(0x10).readPointer();
            o.f[f.name] = {cls: c, EditResult: rf.isNull() ? null : _repeated(rf)};
            return;
        }
        o.f[f.name] = {cls: c};
    });
    return o;
}
rpc.exports.read = function (svc) { _ensureInit(); return _tags(svc); };
// Set ONE tag's SortIndex -- found by its Id in a FRESH enumeration, never a stored address (a cache rebuild frees the
// old protos) -- and save it with EditTag. Returns a GC handle on the promise so the caller can wait for the server.
rpc.exports.setSort = function (svc, id, idx, notify) {
    _ensureInit();
    var y = _api(), t = null;
    _tags(svc).forEach(function (x) { if (x.id === id) t = x; });
    if (!t) return {ok: false, err: 'tag id ' + id + ' not found'};
    var tp = ptr(t.addr), o = _off(tp);
    tp.add(o.sort).writeS32(idx);
    var em = _method('EditTag');
    var b = Memory.alloc(1); b.writeU8(notify ? 1 : 0);
    var args = Memory.alloc(2 * Process.pointerSize);
    args.writePointer(tp); args.add(Process.pointerSize).writePointer(b);
    var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
    var p = IL2.rI(em, ptr(svc), args, exc);
    if (!exc.readPointer().isNull()) {
        tp.add(o.sort).writeS32(t.sort);
        var ex = exc.readPointer(), msg = {};
        _classFields(y.oc(ex)).forEach(function (f) { if (/String/.test(f.type)) msg[f.name] = _str(ex.add(f.off).readPointer()); });
        return {ok: false, err: 'EditTag threw ' + y.cnm(y.oc(ex)).readCString() + ' ' + JSON.stringify(msg), was: t.sort};
    }
    var after = {name: _str(tp.add(o.name).readPointer()), id: tp.add(o.id).readU64().toString(), sort: tp.add(o.sort).readS32()};
    return {ok: true, was: t.sort, before: {name: t.name, id: t.id}, after: after,
            promise: p.isNull() ? null : y.ghNew(p, 0).toString()};
};
rpc.exports.promise = function (h) {
    _ensureInit();
    var p = _api().ghGet(ptr(h));
    return p.isNull() ? null : _dump(p);
};
rpc.exports.release = function (h) { _ensureInit(); _api().ghFree(ptr(h)); return true; };
// Put a tag's LOCAL SortIndex back (after a server refusal) so the cache does not show an order the server never took.
rpc.exports.restore = function (svc, id, idx) {
    _ensureInit();
    var hit = false;
    _tags(svc).forEach(function (x) { if (x.id === id) { ptr(x.addr).add(_off(ptr(x.addr)).sort).writeS32(idx); hit = true; } });
    return hit;
};
"""


def _attach(pg):
    pg.wait_ready_to_attach(timeout_s=300)
    sess, pid = pg.get_session()
    svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
    return sess, pid, svc


def _show(tags, title):
    print('\n%s (%d tags):' % (title, len(tags)))
    for t in sorted(tags, key=lambda t: (t['sort'], t['name'] or '')):
        print('  %4s  %s' % (t['sort'], t['name']))


def _server_answer(sc, h, timeout=20):
    """Wait for EditTag's promise to settle; returns (results list or None, last dump)."""
    t0, last = time.time(), None
    while time.time() - t0 < timeout:
        last = sc.exports_sync.promise(h)
        for v in ((last or {}).get('f') or {}).values():
            if isinstance(v, dict) and v.get('cls') == 'EditPokemonTagOutProto':
                return v.get('EditResult'), last
            if isinstance(v, dict) and 'Exception' in (v.get('cls') or ''):
                return ['exception %s' % v['cls']], last
        time.sleep(0.25)
    return None, last


def edit(sc, svc, tag, idx, notify=True, verbose=False):
    """One SortIndex edit, confirmed by the server. Returns True on Success; on anything else the local value is put
    back and False is returned (the caller stops)."""
    import tag_ops
    res = sc.exports_sync.set_sort(svc, tag['id'], idx, notify)
    if not res.get('ok') and 'threw' in (res.get('err') or ''):     # seen once, right after an aborted run: retry once
        time.sleep(2)
        res = sc.exports_sync.set_sort(svc, tag['id'], idx, notify)
    if not res.get('ok'):
        print('  ! %-20s EditTag failed: %s' % (tag['name'], res.get('err')))
        return False
    b, a = res['before'], res['after']
    if b['name'] != a['name'] or b['id'] != a['id'] or tag_ops.is_pile_tag(a['name'] or '') != tag_ops.is_pile_tag(b['name'] or ''):
        raise SystemExit('ABORT: tag identity changed during a move (%r -> %r)' % (b, a))
    ans, dump = _server_answer(sc, res['promise']) if res.get('promise') else (None, None)
    if res.get('promise'):
        sc.exports_sync.release(res['promise'])
    names = [RESULT.get(x, x) for x in ans] if isinstance(ans, list) else ans
    good = isinstance(ans, list) and ans and all(x == 1 for x in ans)
    print('  %-20s %2s -> %2s   server: %s' % (tag['name'], res['was'], idx, names if names is not None else 'NO ANSWER'))
    if verbose or not good:
        print('     promise:', json.dumps(dump)[:600])
    if not good:
        sc.exports_sync.restore(svc, tag['id'], res['was'])
    return good


def plan(tags):
    names = [t['name'] for t in sorted(tags, key=lambda t: (t['sort'], t['name'] or ''))]
    want = [n for n in ORDER if n in names] + [n for n in names if n not in ORDER]
    return {n: i for i, n in enumerate(want)}                 # 0-based, like the game


def keep_order(pg, sess, svc, log=print):
    """THE CULL HOOK (sync_post_tags.py, in its already write-gated session): read the order; when a tag was created,
    deleted or moved, send the whole order again (every tag, in target order, each confirmed by the server).
    Returns (tags sent, ok). No writes at all when the phone already matches."""
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        tags = sc.exports_sync.read(svc)
        extra = sorted(t['name'] for t in tags if t['name'] not in ORDER)
        if extra:
            log('TAG ORDER note: not in ORDER, kept below the listed tags: %s' % ', '.join(extra))
        if len({t['name'] for t in tags}) != len(tags):
            log('TAG ORDER skipped: two tags share a name'); return 0, False
        target = plan(tags)
        if all(t['sort'] == target[t['name']] for t in tags):
            log('TAG ORDER in place (%d tags)' % len(tags)); return 0, True
        drift = sorted(t['name'] for t in tags if t['sort'] != target[t['name']])
        by = {t['name']: t for t in tags}
        seq = sorted(target.items(), key=lambda kv: kv[1])
        # One refused tag no longer stops the rest (2026-09-30: XXL's EditTag threw NullReferenceException twice and
        # the pass stopped there, so Transfer and everything after XXL kept their old places). A refused edit is put
        # back by edit(); the others still move; the next cull retries the refused ones. Only SortIndex is written.
        refused = [n for k, (n, i) in enumerate(seq) if not edit(sc, svc, by[n], i, notify=(k == len(seq) - 1))]
        after = sc.exports_sync.read(svc)
        ok = not refused and all(t['sort'] == plan(after)[t['name']] for t in after)
        top = [t['name'] for t in sorted(after, key=lambda t: (t['sort'], t['name'] or ''))][:3]
        log('TAG ORDER %s: %d out of place (%s); %d edits sent, %d confirmed by the server%s; top now: %s'
            % ('restored' if not refused else 'partly restored', len(drift), ', '.join(drift), len(seq),
               len(seq) - len(refused), (' -- REFUSED: ' + ', '.join(refused)) if refused else '', ', '.join(top)))
        return len(seq) - len(refused), ok
    finally:
        sc.unload()


def main():
    import pogo_il2cpp as pg
    mode = 'read' if '--read' in sys.argv else 'dry' if '--dry-run' in sys.argv else 'test' if '--test' in sys.argv else 'apply'
    sess, pid, svc = _attach(pg)
    sc = None
    try:
        sc = pg.get_script_with_helpers(sess, JS)
        tags = sc.exports_sync.read(svc)
        _show(tags, 'LIVE ORDER')
        if len({t['name'] for t in tags}) != len(tags):
            raise SystemExit('ABORT: two tags share a name -- ordering by name would be ambiguous')
        target = plan(tags)
        in_place = all(t['sort'] == target[t['name']] for t in tags)
        if mode == 'read':
            print('\nmatches ORDER' if in_place else '\ndiffers from ORDER')
            return 0
        if mode == 'dry':
            for n, i in sorted(target.items(), key=lambda kv: kv[1]):
                cur = next(t['sort'] for t in tags if t['name'] == n)
                print('  %-20s %2s -> %2s%s' % (n, cur, i, '' if cur != i else '  (already)'))
            return 0
        if mode == 'apply' and in_place:
            print('\nTAG ORDER already as intended -- nothing sent')
            return 0
        from ready_gate import ensure_ready_for_writes
        ensure_ready_for_writes(sess, pid)                       # EditTag silently no-ops unless foregrounded
        by = {t['name']: t for t in tags}
        if mode == 'test':
            h, x = by['Hundo'], by['XXL']
            print('\nTEST 1: save Hundo with its SAME index (changes nothing)')
            if not edit(sc, svc, h, h['sort'], verbose=True):
                return 1
            print('TEST 2: swap XXL <-> Hundo')
            if not edit(sc, svc, x, h['sort'], notify=False, verbose=True):
                return 1
            if not edit(sc, svc, h, x['sort'], verbose=True):
                return 1
        else:
            # EVERY tag, in target order: correct whether the server assigns indices outright or shifts the others
            # (moving tag k to slot k never disturbs slots 0..k-1). One edit at a time, each confirmed.
            seq = sorted(target.items(), key=lambda kv: kv[1])
            print('\nAPPLYING %d edits' % len(seq))
            for k, (n, i) in enumerate(seq):
                if not edit(sc, svc, by[n], i, notify=(k == len(seq) - 1)):
                    print('STOPPED at %s -- the server refused; nothing after it was sent' % n)
                    return 1
        _show(sc.exports_sync.read(svc), 'SAME SESSION')
    finally:
        if sc is not None:
            sc.unload()
        sess.detach()
    if mode in ('read', 'dry'):
        return 0
    time.sleep(3)
    sess2, _pid2, svc2 = _attach(pg)
    try:
        sc2 = pg.get_script_with_helpers(sess2, JS)
        after = sc2.exports_sync.read(svc2)
        sc2.unload()
    finally:
        sess2.detach()
    _show(after, 'FRESH SESSION')
    if mode == 'apply':
        ok = all(t['sort'] == plan(after)[t['name']] for t in after) and \
            [t['name'] for t in sorted(after, key=lambda t: t['sort'])][:len(ORDER)] == [n for n in ORDER if n in plan(after)]
        print('\nTAG ORDER %s' % ('VERIFIED' if ok else 'NOT as intended'))
        return 0 if ok else 1
    return 0


def _selfcheck():
    t = [{'name': 'Mine', 'sort': 0}, {'name': 'Hundo', 'sort': 1}, {'name': 'Transfer', 'sort': 2}, {'name': 'Zed', 'sort': 3}]
    p = plan(t)
    assert p == {'Transfer': 0, 'Hundo': 1, 'Mine': 2, 'Zed': 3}, p        # listed first, unlisted after in their order
    print('selfcheck ok')


if __name__ == '__main__':
    sys.exit(_selfcheck() if '--selfcheck' in sys.argv else main())

"""Read LIVE player state from the game -- currently the real Pokemon storage capacity.

WHY THIS EXISTS: the storage cap was HARDCODED (11150) in gen_artifacts.py from a stale note and was
flat wrong (user 2026-07-25: "Where on earth are you getting this 11,000 number from"). Never hardcode
a game-owned number again -- read it from PlayerService.get_MaxPokemon (verified live getter, found via
system/scripts/game_read/recon_storage.py), and write it to player_state.json for downstream consumers.

Usage: python read_player_state.py        (read-only; needs PoGo running + foreground)

2026-09-02 REWRITE -- this file used to carry its OWN copy of the IL2CPP runtime, and that copy was
missing every safety the shared one has. It mattered because this script runs as a dashboard step
(/api/recrawl and /api/full_audit) and /api/cancel tree-kills exactly that child:

  1. NO DEAD-MAN SWITCH. instances() called il2cpp_stop_gc_world() / start_gc_world() directly with no
     rpc.exports.dispose. stopWorld freezes every managed thread; if the HOST died between the two
     (cancel, timeout kill, broken pipe, crash) the paired start never ran and the game stayed frozen
     until force-killed -- verbatim the failure the shared runtime was written to prevent ("you froze
     the fucking game again", 2026-08-19). Of the 14 files that bind il2cpp_stop_gc_world, pogo_il2cpp
     was the ONLY one with a dispose. This file now runs on that shared runtime, so unload/detach --
     including detach after host death -- restarts the world.
  2. UNBALANCED START ON THE ERROR PATH. `catch (e) { if (h.start) h.start(); }` called start
     unconditionally, so a throw from lFree(st) -- which happens AFTER start already ran -- issued a
     second, unmatched il2cpp_start_gc_world (GC world-stop depth underflow). The shared runtime guards
     this with a WORLD_STOPPED flag that makes the second call a no-op.
  3. NO EXCEPTION OUT-PARAM. Both runtime_invoke calls passed ptr(0) as Il2CppException**, so a managed
     exception had nowhere to be written and came back indistinguishable from a real value. Every other
     invoke in the tree allocates a slot. Now checked, and a throwing instance is skipped rather than
     silently contributing a garbage capacity.
  4. main() RAN AT IMPORT. There was no __main__ guard, so `import read_player_state` attached Frida and
     stopped the GC world as a side effect of the import.
"""
import json, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import pogo_il2cpp as pg

# Appended to pogo_il2cpp.JS_PREAMBLE, so IL2 / _ensureInit / liveness_find_instances / WORLD_STOPPED /
# _stopWorld / _startWorld and -- critically -- rpc.exports.dispose all come from the shared runtime.
# Assigning onto rpc.exports (rather than replacing it) keeps that dispose export intact.
EXTRA_JS = r"""
// The shared preamble binds what the bag walk needs; PlayerService is found by bare class name across
// EVERY image (its namespace is not assumed), which needs four more exports. Bound lazily, once.
var PS = null;
function _psExports() {
    if (PS) return PS;
    _ensureInit();
    var il = Process.findModuleByName('libil2cpp.so');
    var e = {};
    il.enumerateExports().forEach(function (x) { if (x.name.indexOf('il2cpp_') === 0) e[x.name] = x.address; });
    function b(n, r, a) { return e[n] ? new NativeFunction(e[n], r, a) : null; }
    PS = {
        iGCC: b('il2cpp_image_get_class_count', 'uint32', ['pointer']),
        iGC:  b('il2cpp_image_get_class', 'pointer', ['pointer', 'uint32']),
        CGN:  b('il2cpp_class_get_name', 'pointer', ['pointer']),
        CGNS: b('il2cpp_class_get_namespace', 'pointer', ['pointer'])
    };
    return PS;
}

function findClassAnywhere(clsName) {
    _ensureInit();
    var X = _psExports();
    if (!X.iGCC || !X.iGC || !X.CGN) return null;
    var sp = Memory.alloc(4);
    var asms = IL2.dGA(IL2.dG(), sp);
    var na = sp.readS32();
    for (var i = 0; i < na; i++) {
        var im = IL2.aGI(asms.add(i * Process.pointerSize).readPointer());
        var cnt = X.iGCC(im);
        for (var c = 0; c < cnt; c++) {
            var k = X.iGC(im, c);
            if (k.isNull()) continue;
            var nm;
            try { nm = X.CGN(k).readCString(); } catch (e) { continue; }
            if (nm === clsName) {
                var ns = '';
                try { ns = X.CGNS(k).readCString() || ''; } catch (e) {}
                return { klass: k, ns: ns };
            }
        }
    }
    return null;
}

// runtime_invoke WITH a real Il2CppException** slot. A managed throw is reported, never silently
// returned as if it were a value.
function _invokeChecked(method, instance) {
    var exc = Memory.alloc(Process.pointerSize);
    exc.writePointer(ptr(0));
    var r = IL2.rI(method, instance, ptr(0), exc);
    if (!exc.readPointer().isNull()) return { threw: true };
    return { ret: r };
}

function _boxedInt32(method, instance) {
    var c = _invokeChecked(method, instance);
    if (c.threw || !c.ret || c.ret.isNull()) return null;
    return c.ret.add(0x10).readS32();   // boxed Int32 payload
}

rpc.exports.maxPokemon = function () {
    _ensureInit();
    var f = findClassAnywhere('PlayerService');
    if (!f) return { err: 'PlayerService class not found' };
    var m = IL2.cMN(f.klass, Memory.allocUtf8String('get_MaxPokemon'), 0);
    if (!m || m.isNull()) return { err: 'get_MaxPokemon not found' };

    // liveness_find_instances (shared) stops the GC world INSIDE a guarded block and restarts it in
    // every exit path, and rpc.exports.dispose restarts it if this process dies mid-scan.
    var inst = liveness_find_instances(f.klass);
    if (inst.err) return { err: inst.err };
    var insts = inst.hits;

    var out = [], threw = 0;
    for (var i = 0; i < insts.length; i++) {
        var v = _boxedInt32(m, ptr(insts[i]));
        if (v === null) { threw++; continue; }
        out.push(v);
    }
    // also try the item-storage sibling if present, for completeness
    var mi = IL2.cMN(f.klass, Memory.allocUtf8String('get_MaxItems'), 0);
    var items = [];
    if (mi && !mi.isNull()) {
        for (var j = 0; j < insts.length; j++) {
            var vi = _boxedInt32(mi, ptr(insts[j]));
            if (vi !== null) items.push(vi);
        }
    }
    // per-instance view (2026-09-12) so the caller can CACHE the live instance and skip the scan next time
    var per = [];
    for (var k = 0; k < insts.length; k++) {
        per.push({ addr: insts[k], maxPokemon: _boxedInt32(m, ptr(insts[k])),
                   maxItems: (mi && !mi.isNull()) ? _boxedInt32(mi, ptr(insts[k])) : null });
    }
    return { ns: f.ns, klass: f.klass.toString(), instances: insts.length, skipped: threw, maxPokemon: out, maxItems: items, perInstance: per };
};

// NO-SCAN path (2026-09-12): read the getters on a KNOWN PlayerService instance (address cached per game pid by
// pogo_pipeline.step_read_player_state). A pure invoke on a live object; no liveness scan, no world stop. Returns
// null values if the object is not a PlayerService any more, and the caller falls back to the scan.
rpc.exports.maxPokemonAt = function (addrStr, klassStr) {
    _ensureInit();
    // klassStr: the PlayerService klass pointer cached with the instance (stable for the process lifetime), so the
    // 71k-class findClassAnywhere scan (~6 s) is only paid on a cache miss. The object's klass pointer must match.
    var k = klassStr ? ptr(klassStr) : null;
    if (!k) { var f = findClassAnywhere('PlayerService'); if (!f) return { err: 'PlayerService class not found' }; k = f.klass; }
    try { if (!ptr(addrStr).readPointer().equals(k)) return { err: 'cached address is not a PlayerService' }; }
    catch (e) { return { err: 'cached address unreadable' }; }
    var m = IL2.cMN(k, Memory.allocUtf8String('get_MaxPokemon'), 0);
    var mi = IL2.cMN(k, Memory.allocUtf8String('get_MaxItems'), 0);
    if (!m || m.isNull()) return { err: 'get_MaxPokemon not found' };
    return { maxPokemon: _boxedInt32(m, ptr(addrStr)), maxItems: (mi && !mi.isNull()) ? _boxedInt32(mi, ptr(addrStr)) : null,
             klass: k.toString() };
};
"""


def main():
    sess, pid = pg.get_session()
    print(f'attached pid {pid}')
    sc = None
    try:
        # THE LIVE GRAPH'S PlayerService (H01, 2026-09-29): "multiple service instances can exist; the real one holds the
        # live cap" was false -- after an in-process rebuild the OLD graph's PlayerService still answers, with the cap of
        # the moment it froze (or of the other account). pick_singleton returns the live graph's player or refuses.
        psvc = pg.pick_singleton(sess, 'Niantic.Holoholo', 'PlayerService')
        sc = pg.get_script_with_helpers(sess, EXTRA_JS)
        r = sc.exports_sync.max_pokemon_at(psvc, None)
        print('raw:', r)
        if r.get('err'):
            print('FAILED: ' + r['err'], file=sys.stderr)
            return 1
        cap = r.get('maxPokemon')
        if not (cap and 100 < cap < 100000):
            print('FAILED: no plausible MaxPokemon value (got %s) on the live PlayerService %s' % (cap, psvc), file=sys.stderr)
            return 1
        items = [v for v in [r.get('maxItems')] if v and 50 < v < 100000]
        state = {'max_pokemon_storage': cap, 'source': 'PlayerService.get_MaxPokemon (live)'}
        if items:
            state['max_item_storage'] = max(items)
        prev = {}
        if os.path.exists('player_state.json'):
            try:
                prev = json.load(open('player_state.json'))
            except Exception:
                pass
        with open('player_state.json', 'w') as f:
            json.dump(state, f, indent=1)
        print('LIVE max pokemon storage = %d%s' % (cap, ('  (was %s)' % prev.get('max_pokemon_storage')) if prev else ''))
        if items:
            print('LIVE max item storage    = %d' % max(items))
        print('wrote player_state.json')
        return 0
    finally:
        # unload FIRST: that is what fires rpc.exports.dispose, which un-freezes the game if anything
        # above threw between stopWorld and startWorld.
        if sc is not None:
            try:
                sc.unload()
            except Exception:
                pass
        try:
            sess.detach()
        except Exception:
            pass


if __name__ == '__main__':
    sys.exit(main())

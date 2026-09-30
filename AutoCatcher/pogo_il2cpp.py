"""Shared Frida + IL2CPP helpers for PoGo extraction scripts.

Consolidates the repetitive boilerplate (adb connect/forward/pidof, frida.attach,
IL2CPP export binding, holo-game.dll image lookup, liveness API plumbing,
PokemonBagImpl LinkedHashMap walking) into a single import surface.

Usage:
    import pogo_il2cpp as pg
    sess, pid = pg.get_session()
    pokedex_addr = pg.find_singleton(sess, 'Niantic.Holoholo.Internal', 'PokedexImpl')
    bag_addr    = pg.find_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
    protos      = pg.walk_bag_protos(sess, bag_addr)
"""
import frida
import subprocess
import os

ADB_TARGET = os.environ.get('ADB_TARGET', '100.98.158.56:5555')  # env override (e.g. ADB_TARGET=<usb-serial>) for when Tailscale is down
FRIDA_REMOTE = '127.0.0.1:27047'
POGO_PKG = 'com.nianticlabs.pokemongo'

JS_PREAMBLE = r"""
var IL2 = null;
var GAME_IMAGE = null;
var CLASS_CACHE = {};
var METHOD_CACHE = {};

function _ensureInit() {
    if (IL2) return;
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {};
    il2cpp.enumerateExports().forEach(function(e){
        if (e.name.indexOf('il2cpp_') === 0) exp[e.name] = e.address;
    });
    function bind(n, ret, args) {
        if (!exp[n]) return null;
        return new NativeFunction(exp[n], ret, args, {exceptions:'propagate'});
    }
    IL2 = {
        dG:    bind('il2cpp_domain_get', 'pointer', []),
        dGA:   bind('il2cpp_domain_get_assemblies', 'pointer', ['pointer','pointer']),
        aGI:   bind('il2cpp_assembly_get_image', 'pointer', ['pointer']),
        iGN:   bind('il2cpp_image_get_name', 'pointer', ['pointer']),
        cFN:   bind('il2cpp_class_from_name', 'pointer', ['pointer','pointer','pointer']),
        cGM:   bind('il2cpp_class_get_methods', 'pointer', ['pointer','pointer']),
        cMN:   bind('il2cpp_class_get_method_from_name', 'pointer', ['pointer','pointer','int']),
        mGN:   bind('il2cpp_method_get_name', 'pointer', ['pointer']),
        rI:    bind('il2cpp_runtime_invoke', 'pointer', ['pointer','pointer','pointer','pointer']),
        // only used to NAME a managed exception in rI's error text (see below)
        objGC: bind('il2cpp_object_get_class', 'pointer', ['pointer']),
        cGN:   bind('il2cpp_class_get_name', 'pointer', ['pointer']),
        rcInit:bind('il2cpp_runtime_class_init', 'void', ['pointer']),
        tA:    bind('il2cpp_thread_attach', 'pointer', ['pointer']),
        alloc: bind('il2cpp_alloc', 'pointer', ['size_t']),
        free:  bind('il2cpp_free', 'void', ['pointer']),
        livenessAlloc:       bind('il2cpp_unity_liveness_allocate_struct', 'pointer', ['pointer','int','pointer','pointer','pointer']),
        livenessFromStatics: bind('il2cpp_unity_liveness_calculation_from_statics', 'void', ['pointer']),
        livenessFinalize:    bind('il2cpp_unity_liveness_finalize', 'void', ['pointer']),
        livenessFreeStruct:  bind('il2cpp_unity_liveness_free_struct', 'void', ['pointer']),
        stopWorld:  bind('il2cpp_stop_gc_world', 'void', []),
        startWorld: bind('il2cpp_start_gc_world', 'void', []),
    };
    IL2.tA(IL2.dG());
    var sp = Memory.alloc(4);
    var asms = IL2.dGA(IL2.dG(), sp);
    var na = sp.readS32();
    for (var a = 0; a < na; a++) {
        var img = IL2.aGI(asms.add(a * Process.pointerSize).readPointer());
        if (IL2.iGN(img).readCString() === 'holo-game.dll') {
            GAME_IMAGE = img;
            break;
        }
    }
}

function cFN(ns, cls) {
    _ensureInit();
    var key = ns + '|' + cls;
    if (CLASS_CACHE[key]) return CLASS_CACHE[key];
    var k = IL2.cFN(GAME_IMAGE, Memory.allocUtf8String(ns), Memory.allocUtf8String(cls));
    CLASS_CACHE[key] = k;
    return k;
}

function cMN(klass, name, argc) {
    _ensureInit();
    var key = klass.toString() + '|' + name + '|' + argc;
    if (METHOD_CACHE[key]) return METHOD_CACHE[key];
    var m = IL2.cMN(klass, Memory.allocUtf8String(name), argc);
    METHOD_CACHE[key] = m;
    return m;
}

function _excName(p) {
    try {
        if (IL2.objGC && IL2.cGN) {
            var n = IL2.cGN(IL2.objGC(p));
            if (n && !n.isNull()) return ' (' + n.readCString() + ')';
        }
    } catch (e) {}
    return '';
}

// runtime_invoke with an Il2CppException** out-param that is actually INSPECTED.
// Before: the slot was allocated and then ignored, so a managed throw returned NULL, the caller faulted
// on the next field read, and _bag_walk_core reported truncated=true -- i.e. a real managed failure was
// diagnosed as "the bag walk broke". Now it raises with the exception's class name.
// A caller that supplies its OWN exc buffer owns the check (delete_tags-style probes read it directly),
// so only the slot we allocate here is inspected.
function rI(method, instance, args, exc) {
    _ensureInit();
    var mine = false;
    if (!exc) {
        exc = Memory.alloc(Process.pointerSize);
        exc.writePointer(ptr(0));
        mine = true;
    }
    var ret = IL2.rI(method, instance, args || ptr(0), exc);
    if (mine) {
        var e = exc.readPointer();
        if (!e.isNull()) throw new Error('IL2CPP managed exception from runtime_invoke' + _excName(e));
    }
    return ret;
}

function class_init(klass) {
    _ensureInit();
    if (IL2.rcInit) IL2.rcInit(klass);
}

// NO JS INSIDE THE STOPPED WORLD (AutoCatcher session, 2026-09-24): Frida has ONE JS lock for every script in the
// gadget. The JS NativeCallbacks below ran while the GC world was stopped; if the catcher's JS on UnityMain held that
// lock when the stop suspended it, our callback waited forever and PoGo froze (the likely 21:04 death and older cull
// freezes). The walk now runs in C (CModule): stop -> allocate -> from_statics -> finalize -> start, callbacks in C,
// all state in a JS-allocated buffer (CModule statics live on a read-only page here -- writing one SIGSEGV'd PoGo).
// A compile failure throws before anything is stopped; the JS walk below stays as the fallback.
var LV_SRC = [
 'typedef unsigned long size_t;',
 'typedef struct { void **out; int max; int n; } Hits;',
 'extern void *il2cpp_unity_liveness_allocate_struct(void *filter, int max, void *cb, void *ud, void *re);',
 'extern void il2cpp_unity_liveness_calculation_from_statics(void *st);',
 'extern void il2cpp_unity_liveness_finalize(void *st);',
 'extern void il2cpp_unity_liveness_free_struct(void *st);',
 'extern void il2cpp_stop_gc_world(void);',
 'extern void il2cpp_start_gc_world(void);',
 'extern void *il2cpp_alloc(size_t n);',
 'extern void il2cpp_free(void *p);',
 'static void on_objs(void **objs, int count, void *ud) { Hits *h = (Hits *)ud; int i; for (i = 0; i < count && h->n < h->max; i++) h->out[h->n++] = objs[i]; }',
 'static void *on_re(void *p, size_t size, void *ud) { if (p != 0 && size == 0) { il2cpp_free(p); return 0; } return il2cpp_alloc(size); }',
 'int find_instances(void *klass, void *hits) {',
 '  void *st; ((Hits *)hits)->n = 0;',
 '  il2cpp_stop_gc_world();',
 '  st = il2cpp_unity_liveness_allocate_struct(klass, 0, (void *)on_objs, hits, (void *)on_re);',
 '  if (st != 0) { il2cpp_unity_liveness_calculation_from_statics(st); il2cpp_unity_liveness_finalize(st); }',
 '  il2cpp_start_gc_world();',
 '  if (st != 0) il2cpp_unity_liveness_free_struct(st);',
 '  return ((Hits *)hits)->n;',
 '}'].join('\n');
var LV = null;          // the CModule stays referenced for the script's lifetime
var LV_ERR = null;      // why the C walk is unavailable (then the JS walk is used)
function liveness_find_instances(klass) {
    _ensureInit();
    if (!LV && !LV_ERR) {
        try {
            var ex = {}, syms = {};
            Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function (x) { ex[x.name] = x.address; });
            ['il2cpp_unity_liveness_allocate_struct', 'il2cpp_unity_liveness_calculation_from_statics', 'il2cpp_unity_liveness_finalize',
             'il2cpp_unity_liveness_free_struct', 'il2cpp_stop_gc_world', 'il2cpp_start_gc_world', 'il2cpp_alloc', 'il2cpp_free'].forEach(function (n) {
                if (!ex[n]) throw new Error('missing ' + n);
                syms[n] = ex[n];
            });
            var cm = new CModule(LV_SRC, syms);
            LV = {cm: cm, find: new NativeFunction(cm.find_instances, 'int', ['pointer', 'pointer'], {exceptions: 'propagate'})};
        } catch (e) {
            LV_ERR = String(e);
        }
    }
    if (LV) {
        class_init(klass);                                   // outside the stopped world, as before
        var MAX = 256, hbuf = Memory.alloc(16 + 8 * MAX);
        hbuf.writePointer(hbuf.add(16)); hbuf.add(8).writeS32(MAX); hbuf.add(12).writeS32(0);
        var n = LV.find(klass, hbuf), out = [];
        for (var i = 0; i < n; i++) out.push(hbuf.add(16 + 8 * i).readPointer().toString());
        return {hits: out, via: 'c'};
    }
    return liveness_find_instances_js(klass);
}
// The original JS walk: the fallback when the CModule cannot be built. It runs JS callbacks inside the stopped world,
// so it is only safe while no other Frida script is attached (culls then keep the catcher pause).
function liveness_find_instances_js(klass) {
    _ensureInit();
    if (!IL2.livenessAlloc || !IL2.livenessFromStatics) {
        return {err: 'liveness API not exported'};
    }
    class_init(klass);
    var hits = [];
    var onObjects = new NativeCallback(function(objects, count, userData) {
        for (var i = 0; i < count; i++) {
            hits.push(objects.add(i * Process.pointerSize).readPointer().toString());
        }
    }, 'void', ['pointer','int','pointer']);
    var realloc = new NativeCallback(function(handle, size, userData) {
        if (!handle.isNull() && size.compare(0) === 0) { IL2.free(handle); return ptr(0); }
        return IL2.alloc(size);
    }, 'pointer', ['pointer','size_t','pointer']);
    // try/FINALLY, not try/catch (2026-09-02): every unsafe copy of this function in the tree
    // (read_player_state, dex_badge_probe, read_pokedex_liveness, the _event_*.py family) restarted the
    // world only in a `catch`, which misses any exit the catch does not cover and double-calls start on
    // the ones it does. The WORLD_STOPPED flag makes the extra _startWorld() a no-op, so `finally` is
    // strictly safer -- and this is the ONE idiom that should be copied from.
    try {
        _stopWorld();
        var state = IL2.livenessAlloc(klass, 0, onObjects, ptr(0), realloc);
        IL2.livenessFromStatics(state);
        if (IL2.livenessFinalize) IL2.livenessFinalize(state);
        _startWorld();
        if (IL2.livenessFreeStruct) IL2.livenessFreeStruct(state);
    } catch(e) {
        return {err: 'liveness threw: ' + e.toString()};
    } finally {
        _startWorld();
    }
    return {hits: hits};
}

// DEAD-MAN SWITCH (2026-08-19, "you froze the fucking game again"): stopWorld freezes every managed
// thread. If the HOST python dies mid-walk (timeout kill, broken pipe from `| head`, crash), the paired
// startWorld never runs and the game stays frozen until the user force-kills it. Frida invokes
// rpc.exports.dispose when the script is unloaded -- including on session detach after host death --
// so track the stopped state and ALWAYS restart the world there. Balanced via the flag: dispose after
// a clean walk is a no-op, and unmatched startWorld calls (GC depth underflow) are impossible.
var WORLD_STOPPED = false;
function _stopWorld() { if (IL2.stopWorld) { IL2.stopWorld(); WORLD_STOPPED = true; } }
function _startWorld() { if (WORLD_STOPPED) { WORLD_STOPPED = false; if (IL2.startWorld) { try { IL2.startWorld(); } catch(e) {} } } }

// Core PokemonBagImpl LinkedHashMap walk. Returns the FULL struct so the caller can VERIFY completeness:
//   { map: {uid: proto}, declared: <list count>, walked: <nodes traversed>, truncated: <bool> }
// NO STOP-THE-WORLD HERE (2026-09-09, "You froze the game again ... its getting old"). The 2026-09-02 version
// wrapped this walk in il2cpp_stop_gc_world on the belief that IL2CPP's collector MOVES objects. It does not:
// IL2CPP uses bdwgc, a non-moving collector, so list nodes never relocate. What the stop DID do was deadlock
// the game: the walk called il2cpp_runtime_invoke(get_AllPokemon) INSIDE the stopped world, and a managed call
// that has to allocate under heap pressure (2.9-3.2 GB RSS tonight) starts a collection that waits for a world
// only this thread can restart. Two ANR traces (00:09, 00:41) show every Unity thread in sigsuspend inside
// libil2cpp -- the signature of exactly that. The recrawl's pipelineWalk never stopped the world and never froze.
// Concurrent mutation of the list (a catch or a release mid-walk) is still caught by the declared/walked/
// truncated check below, and the Python wrapper re-walks; that was always the real risk, not relocation.
function _bag_walk_core(bagAddrStr, filterUids) {
    _ensureInit();
    var bagCls = cFN('Niantic.Holoholo.Internal', 'PokemonBagImpl');
    var ga = cMN(bagCls, 'get_AllPokemon', 0);
    var bag = ptr(bagAddrStr);
    var wanted = null;
    if (filterUids) {
        wanted = {};
        for (var i = 0; i < filterUids.length; i++) wanted[filterUids[i]] = true;
    }
    var out = {};
    var lcount = -1, walked = 0, truncated = false, errMsg = null;
    try {
        var values = rI(ga, bag, ptr(0), null);   // managed call: NEVER inside a stopped world (see above)
        var lhm = values.add(0x10).readPointer();
        var list = lhm.add(0x18).readPointer();
        var head = list.add(0x10).readPointer();
        lcount = list.add(0x18).readS32();
        var node = head;
        var iters = 0;
        while (node && !node.isNull() && iters < lcount + 200) {
            try {
                var uid = node.add(0x28).readU64().toString();
                if (!wanted || wanted[uid]) out[uid] = node.add(0x30).readPointer().toString();
                walked++;
                var next = node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) break;   // reached the list end (full traversal)
                node = next;
            } catch(e) {   // a node faulted: chain broken here -> report incomplete
                truncated = true; errMsg = 'node fault: ' + e; break;
            }
            iters++;
        }
        // THE ONE UNFLAGGED EXIT (fixed 2026-09-02). This loop has three ways out: the list-end break
        // above (complete), the node fault above (flagged), and the iteration cap in the `while`
        // condition -- which set nothing. On a cap exit walked == lcount+200 >= declared and truncated
        // stayed false, so walk_bag_protos' completeness test passed and a capped walk was returned as
        // "GUARANTEED COMPLETE". Needs the LinkedList count to understate the real chain, so it is
        // narrow -- but it is the only silent one, and this is a pure guard: a healthy walk breaks out
        // long before the cap and is unaffected.
        if (iters >= lcount + 200) {
            truncated = true;
            errMsg = 'iteration cap hit (' + iters + ' >= declared ' + lcount + ' + 200) -- list count understates the chain, or the chain loops';
        }
    } catch(e) {
        truncated = true;
        errMsg = String(e && e.message ? e.message : e);
    } finally {
        _startWorld();
    }
    return { map: out, declared: lcount, walked: walked, truncated: truncated, err: errMsg };
}

rpc.exports = {
    init: function() { _ensureInit(); return {ok: true, gameImage: GAME_IMAGE ? GAME_IMAGE.toString() : null}; },
    findSingleton: function(ns, cls) {
        var klass = cFN(ns, cls);
        if (klass.isNull()) return {err: 'class not found: ' + ns + '.' + cls};
        return liveness_find_instances(klass);
    },
    // back-compat: return just {uid: proto} (callers that only count length / map directly). Now GC-safe.
    bagWalk: function(bagAddrStr) { return _bag_walk_core(bagAddrStr, null).map; },
    bagFindForUids: function(bagAddrStr, uids) { return _bag_walk_core(bagAddrStr, uids).map; },
    // completeness-checked: returns {map, declared, walked, truncated} so Python can verify + retry.
    bagWalkChecked: function(bagAddrStr) { return _bag_walk_core(bagAddrStr, null); },
    bagFindForUidsChecked: function(bagAddrStr, uids) { return _bag_walk_core(bagAddrStr, uids); },
    // Frida calls this on script unload (incl. session detach after the host process dies).
    // If a liveness scan was interrupted between stopWorld and startWorld, THIS un-freezes the game.
    dispose: function() { _startWorld(); },
    // RESCUE (2026-09-09): restart the world UNCONDITIONALLY. Only pogo_il2cpp.rescue_frozen_world calls this,
    // and only after the /proc probe has seen UnityMain in sigsuspend for >= 3 s -- a real GC pause is
    // milliseconds, so a world stopped that long was stopped by a tool and abandoned.
    forceStartWorld: function() { WORLD_STOPPED = false; if (IL2.startWorld) { try { IL2.startWorld(); return {ok: true}; } catch(e) { return {ok: false, err: String(e)}; } } return {ok: false, err: 'no il2cpp_start_gc_world'}; },
    // SINGLETON CACHE VALIDATION (2026-09-09): is `addrStr` still a live instance of ns.cls? A pure memory read
    // of the object's klass pointer -- no liveness scan, no world stop. Lets pick_singleton reuse an address
    // found earlier in the SAME game process instead of scanning the heap again.
    checkInstance: function(addrStr, ns, cls) {
        try { var k = cFN(ns, cls); if (k.isNull()) return false; return ptr(addrStr).readPointer().equals(k); } catch(e) { return false; }
    }
};
"""


def _resolve_device():
    """Pick a live adb device: ADB_TARGET (Tailscale) if connected, else the
    first USB 'device'. Returns serial or None. Survives a Tailscale drop by
    re-issuing `adb connect` (idempotent) before checking state."""
    try:
        # Revive a dropped Tailscale link: `adb connect` is a no-op when the
        # endpoint is already 'device', but re-establishes a stale/offline one.
        # Bounded so a fully-down host can't hang the reconnect loop.
        subprocess.run(['adb', 'connect', ADB_TARGET], capture_output=True, timeout=20)
    except Exception:
        pass
    try:
        st = subprocess.run(['adb', '-s', ADB_TARGET, 'get-state'], capture_output=True, text=True)
        if st.stdout.strip() == 'device':
            return ADB_TARGET
    except Exception:
        pass
    # FALLBACK = the PHONE on USB, nothing else (2026-09-19). `adb devices` also lists every other network adb endpoint
    # the PC knows -- a Smart TV on the same Tailscale net was picked and searched for Pokemon GO. Accept only a USB
    # serial (network serials are host:port) that actually has Pokemon GO installed.
    try:
        out = subprocess.check_output(['adb', 'devices'], stderr=subprocess.DEVNULL).decode()
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) != 2 or parts[1] != 'device' or parts[0] == ADB_TARGET or ':' in parts[0]:
                continue
            pm = subprocess.run(['adb', '-s', parts[0], 'shell', 'pm', 'path', POGO_PKG],
                                capture_output=True, text=True, timeout=20)
            if 'package:' in (pm.stdout or ''):
                return parts[0]
    except Exception:
        pass
    return None


def _adb_pidof(dev=None):
    """Run adb pidof on dev (default ADB_TARGET). Returns int PID or None."""
    dev = dev or ADB_TARGET
    try:
        out = subprocess.check_output(
            ['adb', '-s', dev, 'shell', 'pidof', POGO_PKG],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        return int(out) if out else None
    except (subprocess.CalledProcessError, ValueError):
        return None


def _adb_focus(dev=None):
    """Return the current foreground window string (mCurrentFocus), or ''."""
    dev = dev or ADB_TARGET
    try:
        out = subprocess.check_output(
            ['adb', '-s', dev, 'shell', 'dumpsys', 'window'],
            stderr=subprocess.DEVNULL
        ).decode(errors='ignore')
        for line in out.splitlines():
            if 'mCurrentFocus' in line:
                return line.strip()
    except Exception:
        pass
    return ''


def restart_pogo_and_wait(launch_timeout=90, settle=8):
    """Force-stop PoGo, relaunch, and BLOCK until it's truly ready to take
    IL2CPP calls — i.e. a *new* PID is up, the activity is focused, libil2cpp.so
    is loaded in that process, AND a fresh PokemonBagImpl walk returns >100 mons.

    This is the readiness gate that prevents the post-restart failures:
      - "enumerateExports of null"  -> libil2cpp not loaded yet
      - stale-bag no-op writes      -> we re-prove the bag walks before returning

    Returns (frida.Session, int pid) on a confirmed-ready process.
    Raises RuntimeError if it never reaches readiness within launch_timeout.
    """
    import time as _t
    dev = _resolve_device()
    if not dev:
        raise RuntimeError('No ADB device reachable for restart.')
    if dev == ADB_TARGET:
        subprocess.run(['adb', 'connect', ADB_TARGET], capture_output=True)
    old_pid = _adb_pidof(dev)
    subprocess.run(['adb', '-s', dev, 'shell', 'am', 'force-stop', POGO_PKG], capture_output=True)
    _t.sleep(3)
    # Relaunch via monkey (no need to know the exact activity name).
    subprocess.run(
        ['adb', '-s', dev, 'shell', 'monkey', '-p', POGO_PKG,
         '-c', 'android.intent.category.LAUNCHER', '1'],
        capture_output=True)

    deadline = _t.time() + launch_timeout
    pid = None
    # Phase 1: wait for a NEW pid + the Unity activity focused.
    while _t.time() < deadline:
        _t.sleep(2)
        pid = _adb_pidof(dev)
        foc = _adb_focus(dev)
        if pid and pid != old_pid and 'pokemongo' in foc.lower():
            break
    if not pid or pid == old_pid:
        raise RuntimeError('PoGo did not relaunch (no new PID / not focused).')

    # Phase 2: give the engine time to load libil2cpp + sync the bag, then PROVE
    # readiness by attaching and walking the bag. Retry until it walks >100.
    _t.sleep(settle)
    last_err = 'never attached'
    while _t.time() < deadline:
        try:
            sess, p2 = get_session()
        except Exception as e:
            last_err = f'attach: {e}'
            _t.sleep(3)
            continue
        try:
            # init() throws/returns no gameImage if libil2cpp isn't mapped yet.
            sc = get_script_with_helpers(sess)
            try:
                ini = sc.exports_sync.init()
                if not ini.get('gameImage'):
                    last_err = 'libil2cpp not loaded (no gameImage)'
                    raise RuntimeError(last_err)
            finally:
                sc.unload()
            bag = pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
            n = len(walk_bag_protos(sess, bag))
            if n > 100:
                return sess, p2          # CONFIRMED ready
            last_err = f'bag walk only {n} mons'
        except Exception as e:
            last_err = str(e)
        try:
            sess.detach()
        except Exception:
            pass
        _t.sleep(3)
    raise RuntimeError(f'PoGo relaunched (pid {pid}) but never reached readiness: {last_err}')


class NotReadyToAttach(RuntimeError):
    """PoGo is running but NOT safe to instrument yet (cold start). Poll via adb, never via attach."""


def _adb_ready_to_attach(devser, pid, min_age_s=45):
    """PURE-ADB pre-attach gate (2026-08-24, 'stop crashing it. fix your methods.').

    Attaching Frida to a MID-LOAD Unity process crashes it: every game death this week clustered
    around attach/create_script against a cold-starting PID (transport timeout -> app dead -> new PID).
    Tools used to PROBE readiness by attaching in a retry loop -- each probe was itself a crash roll.
    This gate answers "is it safe?" from /proc alone, zero instrumentation:
      1. libil2cpp.so must be mapped in /proc/<pid>/maps (il2cpp fully loaded), and
      2. the process must be >= min_age_s old (past the init storm), from /proc/<pid>/stat starttime.
    Returns (ok, reason).
    """
    # /proc/<pid>/maps of another app needs root (Magisk su); stat/uptime/getconf are readable unprivileged.
    # EVERY failure below returns (False, reason) rather than raising. This gate is fail-closed for
    # get_session (an exception there just aborts), but wait_ready_to_attach calls it UNGUARDED inside a
    # 240s poll -- so a single TimeoutExpired from a slow adb, or a ValueError from a non-numeric /proc
    # read during a process transition, used to kill a poll that should have kept polling (and, worse,
    # kill it with a traceback rather than a diagnosis).
    try:
        out = subprocess.run(['adb', '-s', devser, 'shell',
                              f"su -c 'grep -m1 -c libil2cpp.so /proc/{pid}/maps' 2>/dev/null; "
                              f'cut -d" " -f22 /proc/{pid}/stat 2>/dev/null; '
                              'cut -d" " -f1 /proc/uptime; getconf CLK_TCK'],
                             capture_output=True, text=True, timeout=15).stdout.split()
    except subprocess.TimeoutExpired:
        return False, f'adb /proc read timed out for pid {pid} (device busy or link down)'
    except Exception as e:
        return False, f'adb /proc read failed for pid {pid}: {e}'
    if len(out) < 4:
        return False, f'/proc read failed for pid {pid} (process gone mid-check?)'
    mapped, start_ticks, uptime_s, hz = out[0], out[1], out[2], out[3]
    if mapped.strip() != '1':
        return False, f'libil2cpp.so not yet mapped in pid {pid} (cold start)'
    try:
        age = float(uptime_s) - int(start_ticks) / int(hz)
    except (ValueError, ZeroDivisionError):
        return False, (f'/proc gave non-numeric values for pid {pid} '
                       f'(start={start_ticks!r} uptime={uptime_s!r} hz={hz!r}) -- treating as NOT ready')
    if age < min_age_s:
        return False, f'pid {pid} is only {age:.0f}s old (< {min_age_s}s) -- init storm, unsafe to attach'
    return True, f'pid {pid} ready (il2cpp mapped, {age:.0f}s old)'


def wait_ready_to_attach(timeout_s=240, min_age_s=45):
    """Block until PoGo is attach-safe, polling ONLY via adb (no Frida). Returns the ready pid.

    Use this instead of attach-retry loops when waiting out an app launch."""
    import time as _t
    devser = _resolve_device()
    if not devser:
        raise RuntimeError('No ADB device reachable.')
    deadline = _t.time() + timeout_s
    last = 'no pid yet'
    while _t.time() < deadline:
        pid = _adb_pidof(devser)
        if pid:
            ok, last = _adb_ready_to_attach(devser, pid, min_age_s)
            if ok:
                return pid
        _t.sleep(5)
    raise RuntimeError(f'PoGo never became attach-safe in {timeout_s}s ({last})')


# ---- SHARED PHONE-ACCESS MARKER (agreed with the Pokemon Inventory session, 2026-09-29) ----------------------------------
# /data/local/tmp/pogo_desktop_busy = "<name> <epoch-deadline>" (root-created, 666). ADVISORY: every DESKTOP Frida attacher
# writes it while attached and logs a foreign live one -- nobody waits or refuses (user, 2026-09-29). We hold it with a
# deadline <= 300 s ahead, refreshed every 120 s; it is cleared on detach / exit, only if it is still ours. The on-phone
# catcher is exempt (culls overlap it by design). Deadlines are compared with the PHONE's clock.
BUSY_FILE = '/data/local/tmp/pogo_desktop_busy'
BUSY_NAME = 'AutoCatcher/%d' % os.getpid()
BUSY_WAIT_S = 120
_BUSY = {'dev': None, 'stop': None}


def _busy_state(devser):
    """(holder, deadline, phone_now) -- holder None when the marker is free/empty/unreadable."""
    out = subprocess.run(['adb', '-s', devser, 'shell', f'cat {BUSY_FILE} 2>/dev/null; echo; date +%s'],
                         capture_output=True, text=True, timeout=15).stdout.split()
    try:
        now = int(out[-1])
    except (ValueError, IndexError):
        now = 0
    if len(out) >= 3 and out[-2].isdigit():
        return out[-3], int(out[-2]), now
    return None, 0, now


def _busy_write(devser, text):
    subprocess.run(['adb', '-s', devser, 'shell',
                    f"su -c '[ -f {BUSY_FILE} ] || {{ touch {BUSY_FILE}; chmod 666 {BUSY_FILE}; }}; echo \"{text}\" > {BUSY_FILE}'"],
                   capture_output=True, text=True, timeout=15)


def busy_acquire(devser, wait_s=BUSY_WAIT_S):
    """Report a foreign holder (advisory -- never wait), then hold the marker and keep it fresh while attached."""
    import threading
    import time as _t
    # ADVISORY ONLY (user 2026-09-29: "everything should be working while each tool is in there. no one should be pausing
    # anything for anyone"): a foreign live marker is REPORTED, never waited on and never refused. Overlap is safe because
    # every desktop attacher uses the C liveness walk.
    who, dl, now = _busy_state(devser)
    if who and who not in (BUSY_NAME, 'free') and now and dl > now:
        print(f'[phone busy] {who} is also attached (marker until +{dl - now}s) -- continuing: the marker is advisory', flush=True)
    _busy_write(devser, f'{BUSY_NAME} {(now or int(_t.time())) + 300}')
    if _BUSY['stop'] is None:
        stop = threading.Event()
        _BUSY.update(dev=devser, stop=stop)

        def _refresh():
            while not stop.wait(120):
                try:
                    who, _dl, now2 = _busy_state(devser)
                    if who in (None, BUSY_NAME, 'free'):
                        _busy_write(devser, f'{BUSY_NAME} {now2 + 300}')
                except Exception:
                    pass
        threading.Thread(target=_refresh, daemon=True).start()
        import atexit
        atexit.register(busy_release)


def busy_release():
    """Clear the marker if it is still ours (called on detach and at exit)."""
    dev, stop = _BUSY.get('dev'), _BUSY.get('stop')
    if stop is not None:
        stop.set()
    _BUSY.update(dev=None, stop=None)
    if not dev:
        return
    try:
        who, _dl, _now = _busy_state(dev)
        if who == BUSY_NAME:
            _busy_write(dev, 'free 0')
    except Exception:
        pass


def get_session(retries=3, allow_cold=False):
    """ADB connect + forward + pidof + frida.attach. Retries on PID change.

    Refuses to attach to a cold-starting process (see _adb_ready_to_attach) unless allow_cold=True --
    attaching mid-load is what has been CRASHING the game. Callers that want to wait out a launch
    call wait_ready_to_attach() first instead of attach-probing.

    Returns (frida.Session, int pid).
    """
    import threading
    devser = _resolve_device()
    if not devser:
        raise RuntimeError('No ADB device reachable (reconnect Tailscale 100.98.158.56:5555 or plug in USB).')
    if devser == ADB_TARGET:
        subprocess.run(['adb', 'connect', ADB_TARGET], capture_output=True)
    pid0 = None
    if not allow_cold:
        pid0 = _adb_pidof(devser)
        if not pid0:
            raise RuntimeError(f'PoGo not running ({POGO_PKG}) on {devser}')
        ok, why = _adb_ready_to_attach(devser, pid0)
        if not ok:
            raise NotReadyToAttach(why + ' -- wait (wait_ready_to_attach) instead of attaching')
    busy_acquire(devser)   # the shared phone-access marker (see above)
    subprocess.run(['adb', '-s', devser, 'forward', 'tcp:27047', 'tcp:27047'], capture_output=True)
    # adb forward's local socket accepts regardless of whether frida-server is
    # alive, so a plain connect can't detect a dead server — run attach in a
    # thread with a hard timeout so a dead frida-server fails fast, not hangs.
    res = {}
    cancelled = threading.Event()   # set by the timeout path so a late attach detaches instead of leaking
    def _attach():
        try:
            dev = frida.get_device_manager().add_remote_device(FRIDA_REMOTE)
            for _ in range(retries):
                pid = _adb_pidof(devser)
                if not pid:
                    res['err'] = f'PoGo not running ({POGO_PKG}) on {devser}'; return
                # THE GATE MUST FOLLOW THE PID (2026-09-02). The readiness check above ran on pid0, but
                # this loop RE-READS the pid every iteration and used to attach it ungated. The loop
                # exists precisely for the case where the pid changed -- which is exactly the case where
                # the new pid is cold-starting, i.e. an ungated attach-probe retry loop, the crash roll
                # _adb_ready_to_attach was written to eliminate ("stop crashing it. fix your methods.").
                # Never attach a pid that has not passed the /proc gate in THIS call.
                if not allow_cold and pid != pid0:
                    ok2, why2 = _adb_ready_to_attach(devser, pid)
                    if not ok2:
                        res['err'] = (f'PoGo restarted mid-attach (pid {pid0} -> {pid}) and the new pid is '
                                      f'not attach-safe: {why2} -- wait (wait_ready_to_attach) instead')
                        res['not_ready'] = True
                        return
                try:
                    s = dev.attach(pid)
                except frida.ProcessNotFoundError as e:
                    res['err'] = str(e)
                    continue
                if cancelled.is_set():
                    # the host already gave up on us; do not leave an attached session nobody owns.
                    # Callers that retry (_frida_safe 4x, verify_tags_live 6x) would otherwise stack
                    # orphaned sessions on one process.
                    try:
                        s.detach()
                    except Exception:
                        pass
                    return
                res['sess'] = s; res['pid'] = pid; return
        except Exception as e:
            res['err'] = str(e)
    t = threading.Thread(target=_attach, daemon=True); t.start(); t.join(15)
    if t.is_alive():
        cancelled.set()
        busy_release()
        raise RuntimeError(f'Frida attach timed out via {devser}; the cause is unknown. '
                           'Check ADB, the gadget transport, game PID and crash log before re-attaching.')
    if 'sess' in res:
        try:        # Stage 5 (speed study 2026-09-24): the session knows its own pid -- pick_singleton needs no adb
            res['sess']._pogo_pid = res['pid']
        except Exception:
            pass
        try:
            res['sess'].on('detached', lambda *a: busy_release())
        except Exception:
            pass
        return res['sess'], res['pid']
    busy_release()
    if res.get('not_ready'):
        raise NotReadyToAttach(res['err'])
    raise RuntimeError(res.get('err', 'attach failed'))


def get_script_with_helpers(sess, extra_js=''):
    """Create + load a Frida script containing the standard IL2CPP preamble.

    Pass `extra_js` to append script-specific RPC exports. To merge with the
    preamble's rpc.exports, define your additions before `rpc.exports = {...}`
    or wrap them yourself.

    Returns the loaded frida.Script. Caller invokes rpc.init() if needed
    (findSingleton / bagWalk auto-init).
    """
    js = JS_PREAMBLE + '\n' + extra_js if extra_js else JS_PREAMBLE
    script = sess.create_script(js)
    script.load()
    return script



# Copied 2026-09-29 from pogo_extract/pogo_il2cpp.py (the Pokemon Inventory session's H01 fix) -- the AutoCatcher copy
# keeps its own file; keep the two in step by re-copying, never by importing across folders.
# ---- THE LIVE SERVICE GRAPH (2026-09-29) -------------------------------------------------------------------------------
# PoGo can REBUILD its whole service graph inside one process (seen 05:00: a second PokemonBagImpl, TaggingRpcService,
# InventoryCache, PlayerService, RpcHandler ...). The old objects stay allocated and keep their last contents, so a cached
# address -- or the "biggest bag" pick -- reads a FROZEN bag and tag table while the game shows something else. The live
# graph is the one whose InventoryCache.latestTimestamp (last server inventory update, ms) is newest; every service of a
# graph points at that graph's PlayerService, which is how the other singletons are matched to it.
_GRAPH_JS = r"""
var _GX = {}; Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function (x) { _GX[x.name] = x.address; });
function _gf(n, r, a) { return _GX[n] ? new NativeFunction(_GX[n], r, a) : null; }
var _GIL = { fields: _gf('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']), name: _gf('il2cpp_field_get_name', 'pointer', ['pointer']),
  off: _gf('il2cpp_field_get_offset', 'uint32', ['pointer']), flags: _gf('il2cpp_field_get_flags', 'int', ['pointer']),
  type: _gf('il2cpp_field_get_type', 'pointer', ['pointer']), tname: _gf('il2cpp_type_get_name', 'pointer', ['pointer']),
  parent: _gf('il2cpp_class_get_parent', 'pointer', ['pointer']), cname: _gf('il2cpp_class_get_name', 'pointer', ['pointer']) };
function _gcs(p) { try { return p.isNull() ? '' : p.readCString(); } catch (e) { return ''; } }
function _gk(o) { var k = o.readPointer(); var nm = k.add(0x10).readPointer().readCString();
  if (!/^[A-Za-z_][\w`<>.,]*$/.test(nm) || nm.length > 200) throw new Error('not an object'); return k; }
function _gfind(o, test) {                       // first instance field (own class, then parents) passing test(name, typeName)
  var k = _gk(o), depth = 0;
  while (k && !k.isNull() && depth < 6) {
    var it = Memory.alloc(Process.pointerSize); it.writePointer(NULL); var fd;
    while ((fd = _GIL.fields(k, it)) && !fd.isNull()) {
      if (_GIL.flags(fd) & 0x10) continue;
      if (test(_gcs(_GIL.name(fd)), _gcs(_GIL.tname(_GIL.type(fd))))) return o.add(_GIL.off(fd));
    }
    var par = _GIL.parent(k); if (!par || par.isNull() || _gcs(_GIL.cname(par)) === 'Object') break; k = par; depth++;
  }
  return null;
}
rpc.exports.graphOf = function (addr) {           // {player, inv, ts, now} of the graph this service object belongs to
  try {
    var o = ptr(addr), out = {player: null, inv: null, ts: null, now: Date.now()};   // now: the PHONE's clock (H03)
    var pp = _gfind(o, function (n, t) { return /(^|\.)I?PlayerService$/.test(t); });
    if (pp) out.player = pp.readPointer().toString();
    // H01 2026-09-29: an IPokemonBag reference ties a service to its graph too (ItemBagImpl.cuwq, PlayerService.crpb;
    // AutoCatcher/tools/buddy_tapper.py:170 reads the same field)
    var bp = _gfind(o, function (n, t) { return /(^|\.)I?PokemonBag$/.test(t); });
    out.bag = bp ? bp.readPointer().toString() : null;
    var ip = _gfind(o, function (n, t) { return /(^|\.)I?InventoryCache$/.test(t); });   // PokedexImpl holds the interface
    if (ip) { var inv = ip.readPointer(); out.inv = inv.toString();
      if (!inv.isNull()) { var tp = _gfind(inv, function (n, t) { return n === 'latestTimestamp'; }); if (tp) out.ts = tp.readS64().toString(); } }
    return out;
  } catch (e) { return {err: String(e)}; }
};
rpc.exports.invTs = function (addr) {             // InventoryCache.latestTimestamp of an InventoryCache object itself
  try { var tp = _gfind(ptr(addr), function (n, t) { return n === 'latestTimestamp'; }); return tp ? tp.readS64().toString() : null; }
  catch (e) { return null; }
};
"""


def _graph_of(sess, addrs):
    s = get_script_with_helpers(sess, _GRAPH_JS)
    try:
        return {a: s.exports_sync.graph_of(a) for a in addrs}
    finally:
        s.unload()


class GraphRefusal(RuntimeError):
    """The live service graph -- or this class's member of it -- cannot be told apart from a stale copy. NEVER caught to
    fall back to a size / first-hit / cached guess: that guess is how four culls read a frozen bag (H01, 2026-09-29)."""


class GraphChanged(GraphRefusal):
    """The game rebuilt its service graph DURING this session: whatever this session read or wrote through the old
    objects is unverified (revalidate_graph)."""


def live_graph(sess, fresh=False):
    """{'bag', 'player', 'inv', 'ts', 'bags'}: the LIVE service graph of this game process, found once per session (one
    liveness scan of PokemonBagImpl). Raises when two graphs cannot be told apart -- a guess here is a frozen cull.
    fresh=True re-derives it with a new scan and re-memoizes it (revalidate_graph, H01 2026-09-29)."""
    g = None if fresh else getattr(sess, '_pogo_graph', None)
    if g is not None:
        return g
    script = get_script_with_helpers(sess)
    try:
        r = script.exports_sync.find_singleton('Niantic.Holoholo.Internal', 'PokemonBagImpl')
    finally:
        script.unload()
    if 'err' in r:
        raise RuntimeError('live_graph: %s' % r['err'])
    hits = r.get('hits', [])
    rescue_frozen_world(sess, 'liveness scan for the live graph')
    if not hits:
        raise RuntimeError('live_graph: no PokemonBagImpl instance')
    info = _graph_of(sess, hits)
    ranked = sorted(hits, key=lambda h: -int((info.get(h) or {}).get('ts') or -1))
    top = info.get(ranked[0]) or {}
    if len(hits) > 1:
        t0 = int(top.get('ts') or -1)
        t1 = int((info.get(ranked[1]) or {}).get('ts') or -1)
        if t0 <= 0 or t0 == t1:
            raise GraphRefusal('live_graph: %d PokemonBagImpl graphs and no newer inventory timestamp to tell the live one '
                               '(%s) -- refusing to guess (a stale graph reads a frozen bag)' % (len(hits), info))
        print('[live_graph] the game holds %d service graphs (it rebuilt them without a restart): reading the live one, '
              'inventory updated %s ms, not the stale one at %s ms' % (len(hits), t0, t1), flush=True)
    sess._pogo_graph = {'bag': ranked[0], 'player': top.get('player'), 'inv': top.get('inv'), 'ts': top.get('ts'),
                        'bags': len(hits),
                        # WHAT THE WALK TRIPWIRES JUDGE (H03, 2026-09-29). The pick above only RANKS graphs; nothing ever
                        # asked whether the winner is live. With ONE PokemonBagImpl found (the rebuilt graph not reached by
                        # the scan, or only the stale one left) there is no comparison at all, and ts was kept on this
                        # session object only -- never persisted, never compared across passes. walk_tripwires.check_graph
                        # reads these: the phone's own clock at this read (GRAPH_STALE: now - ts), every other graph's
                        # timestamp (MULTI_GRAPH), and the pass-to-pass history (FROZEN_REPEAT / GRAPH_TS_BACKWARDS).
                        'now': top.get('now'), 'ts_other': [(info.get(h) or {}).get('ts') for h in ranked[1:]]}
    return sess._pogo_graph


def graph_membership(sess, named):
    """{name: {'addr', 'player', 'inv'}} for the service objects a pass read ({name: addr}), so the walk tripwires can
    prove every one of them belongs to the walked graph (MIXED_GRAPH) or say which could not be proven
    (UNPROVEN_SERVICE). Plain field reads through _GRAPH_JS -- no liveness scan, no world stop. Never raises."""
    named = {k: v for k, v in (named or {}).items() if v}
    try:
        info = _graph_of(sess, sorted(set(named.values())))
    except Exception as e:
        return {k: {'addr': v, 'err': str(e)[:120]} for k, v in named.items()}
    return {k: {'addr': v, 'player': (info.get(v) or {}).get('player'), 'inv': (info.get(v) or {}).get('inv')}
            for k, v in named.items()}


_GRAPH_CLASSES = {'PokemonBagImpl', 'TaggingRpcService', 'PokedexImpl', 'InventoryCache', 'PlayerService', 'IapService',
                  'AdventureEffectService', 'RemoteTradeRpcService'}


# _GRAPH_CLASSES is NOT a gate any more (H01, 2026-09-29): pick_singleton sends EVERY class through the live graph. The
# hand list missed ItemBagImpl (item_cleanup.py --commit discards by its counts; it carries IPlayerService cuwm) and
# GameMasterData, and its members fell back to the klass-only cache / first hit / biggest value whenever _same_graph_pick
# could not read a PlayerService reference.


def revalidate_graph(sess):
    """RE-DERIVE the live graph NOW (one liveness scan, fresh) and compare it with the graph this session has been reading
    and writing through (H01, 2026-09-29). live_graph memoizes on the session, so a rebuild DURING a session was invisible
    and a post-write verify re-read the very objects it had just written through. Raises GraphChanged when the live bag /
    player moved; the new graph is memoized either way, so a caller that wants to continue re-picks from it."""
    old = getattr(sess, '_pogo_graph', None)
    new = live_graph(sess, fresh=True)
    if old is not None and (old.get('bag') != new.get('bag') or old.get('player') != new.get('player')):
        raise GraphChanged('the game rebuilt its service graph during this session (bag %s -> %s, player %s -> %s): '
                           'everything read or written through the old objects is unverified'
                           % (old.get('bag'), new.get('bag'), old.get('player'), new.get('player')))
    return new


def _graph_link(i, g):
    """True when graphOf-info i points at the live graph g: its PlayerService, its InventoryCache (PokedexImpl holds the
    interface) or its PokemonBag (ItemBagImpl) is g's."""
    return bool(i) and any(i.get(k) and i.get(k) == g.get(k) for k in ('player', 'inv', 'bag'))


def _has_graph_ref(i):
    return bool(i) and any(i.get(k) for k in ('player', 'inv', 'bag'))


def _is_instance(sess, addr, namespace, class_name):
    """A pure klass-pointer read (no scan, no world stop): is addr still a namespace.class_name object?"""
    s = get_script_with_helpers(sess)
    try:
        return bool(s.exports_sync.check_instance(addr, namespace, class_name))
    except Exception:
        return False
    finally:
        s.unload()


def _same_graph_pick(sess, namespace, class_name, cached, g):
    """The instance of class_name that belongs to the live graph g. Never None and never a guess (H01, 2026-09-29):
      * a cached address is used only when it is STILL a class_name object (klass read -- a collected object's block is
        reused by bdwgc, and a GUI controller injecting the live PlayerService would otherwise pass) AND links to g;
      * else one scan: the instance linked to g; or, when no instance of the class carries any graph reference, the ONE
        instance there is. Two unlinked instances, or instances linked only to other graphs, raise GraphRefusal -- the
        old code returned None here and pick_singleton fell back to the unvalidated cache / first hit / biggest value."""
    if cached and _is_instance(sess, cached, namespace, class_name):
        if _graph_link(_graph_of(sess, [cached]).get(cached) or {}, g):
            return cached
    script = get_script_with_helpers(sess)
    try:
        r = script.exports_sync.find_singleton(namespace, class_name)
    finally:
        script.unload()
    rescue_frozen_world(sess, 'liveness scan for %s.%s' % (namespace, class_name))
    if 'err' in r:
        raise RuntimeError('pick_singleton(%s.%s): %s' % (namespace, class_name, r['err']))
    hits = r.get('hits', [])
    if not hits:
        raise RuntimeError('no instances of %s.%s' % (namespace, class_name))   # ready_gate keys its storage-UI hint on this
    info = _graph_of(sess, hits)
    mine = [h for h in hits if _graph_link(info.get(h), g)]
    if mine:
        return mine[0]
    if not any(_has_graph_ref(info.get(h)) for h in hits):
        if len(hits) == 1:
            return hits[0]                           # one instance and no graph reference: nothing to confuse it with
        raise GraphRefusal('%s.%s: %d instances and none carries a PlayerService / InventoryCache / PokemonBag reference '
                           'to tell the live one -- refusing to guess (a stale copy answers like a live one)'
                           % (namespace, class_name, len(hits)))
    raise GraphRefusal('no instances of %s.%s in the live graph (player %s): the %d instance(s) found belong to an older '
                       'service graph -- refusing to read a stale copy (open the screen that creates it, then retry)'
                       % (namespace, class_name, g.get('player'), len(hits)))


def find_singleton(sess, namespace, class_name):
    """Resolve a single live instance of `namespace.class_name` via liveness API.

    Asserts exactly 1 hit. Returns ptr-as-str ('0x72f0...'). For classes where
    multiple instances may appear (PokemonBagImpl, TaggingRpcService, PokedexImpl),
    use `pick_singleton` instead.
    """
    script = get_script_with_helpers(sess)
    try:
        r = script.exports_sync.find_singleton(namespace, class_name)
        if 'err' in r:
            raise RuntimeError(f'find_singleton({namespace}.{class_name}): {r["err"]}')
        hits = r.get('hits', [])
        if len(hits) != 1:
            raise AssertionError(
                f'expected exactly 1 instance of {namespace}.{class_name}, got {len(hits)}: {hits}'
            )
        return hits[0]
    finally:
        script.unload()


_SVC_PROBE_JS = r"""
rpc.exports.probeNumberOfTags = function(addr) {
    _ensureInit();
    var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, gnt = null;
    while ((m = IL2.cGM(svcCls, iter)) && !m.isNull()) {
        if (IL2.mGN(m).readCString() === 'get_NumberOfTags') { gnt = m; break; }
    }
    try {
        var ret = rI(gnt, ptr(addr), ptr(0), null);
        var n = ret.add(0x10).readS32();
        return {ok:true, n: n};
    } catch(e) { return {ok:false, err: e.toString()}; }
};
rpc.exports.probeStardust = function(addr) {
    _ensureInit();
    try {
        var k = cFN('Niantic.Holoholo.Storefront', 'IapService');
        var m = cMN(k, 'get_Stardusts', 0);
        if (!m || m.isNull()) return {ok:false, err:'no get_Stardusts'};
        var r = rI(m, ptr(addr), ptr(0), null);
        return {ok:true, n: r.isNull() ? 0 : r.add(0x10).readS32()};
    } catch(e) { return {ok:false, err: e.toString()}; }
};
rpc.exports.probeDexCount = function(addr) {
    _ensureInit();
    try {
        var inst = ptr(addr);
        var dict = inst.add(0x10).readPointer();
        if (dict.isNull()) return {ok:false, err:'null dict'};
        var entries = dict.add(0x18).readPointer();
        if (entries.isNull()) return {ok:false, err:'null entries'};
        var count = entries.add(0x18).readS32();
        return {ok:true, n: count};
    } catch(e) { return {ok:false, err: e.toString()}; }
};
"""


def _adb_unitymain_wchan(devser, pid):
    """Kernel wait channel of the UnityMain thread ('' if unreadable). 'sigsuspend' = parked by the GC's
    stop-the-world; a real collection holds that for milliseconds, a tool that stopped the world and never
    restarted it holds it forever (the 2026-09-09 freezes)."""
    try:
        # MUST run under su: /proc is mounted hidepid=invisible, so an unprivileged adb shell reads
        # wchan back as "0" for every thread and this probe silently reported "not frozen" on a game
        # that WAS frozen (2026-09-12). Root reads the real value.
        # base64 over stdin: `adb shell su -c <script>` mangles the nested quoting/$() every time.
        import base64 as _b64
        # ONE pipeline instead of a 160-thread cat loop: the loop cost ~6 s per probe over Tailscale (2026-09-12).
        inner = ("for f in $(grep -lx UnityMain /proc/%d/task/*/comm 2>/dev/null); do cat ${f%%comm}wchan 2>/dev/null; echo; done"
                 % int(pid))   # only the ~8 UnityMain threads are read; /proc wchan has no newline, hence the echo
        _enc = _b64.b64encode(inner.encode()).decode()
        out = subprocess.run(['adb', '-s', devser, 'shell',
                              'echo %s | base64 -d | su -c sh' % _enc],
                             capture_output=True, text=True, timeout=10).stdout
        # There are several UnityMain threads; ANY one parked in sigsuspend means the world is stopped.
        vals = out.split()
        return 'sigsuspend' if 'sigsuspend' in out else (vals[0] if vals else '')   # substring: robust to run-together values
    except Exception:
        return ''


def game_world_frozen(pid=None, samples=3, gap_s=1.0):
    """True iff UnityMain sits in sigsuspend across `samples` probes `gap_s` apart (default: 3 s frozen).
    Pure adb /proc reads -- safe to call while nothing is attached. False on any read failure."""
    import time as _t
    devser = _resolve_device()
    if not devser:
        return False
    pid = pid or _adb_pidof(devser)
    if not pid:
        return False
    for i in range(samples):
        if 'sigsuspend' not in _adb_unitymain_wchan(devser, pid):
            return False
        if i + 1 < samples:
            _t.sleep(gap_s)
    return True


def rescue_frozen_world(sess, where=''):
    """If the game is frozen (game_world_frozen), restart the GC world through THIS session and say so loudly.
    Returns True when a rescue was performed. Call after any export that stops the world."""
    try:
        if not game_world_frozen(samples=3, gap_s=1.0):
            return False
    except Exception:
        return False
    print('!! GAME FROZEN after %s: UnityMain in sigsuspend >= 3 s -- restarting the GC world (rescue)' % (where or 'a Frida call'), flush=True)
    scr = None
    try:
        scr = get_script_with_helpers(sess)
        r = scr.exports_sync.force_start_world()
        print('!! rescue result: %s' % r, flush=True)
    except Exception as e:
        print('!! rescue FAILED: %s' % e, flush=True)
    finally:
        if scr is not None:
            try:
                scr.unload()
            except Exception:
                pass
    return True


_SINGLETON_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'system', 'analysis', 'singleton_cache.json')


def _singleton_cache_get(pid, key):
    try:
        import json as _j
        d = _j.load(open(_SINGLETON_CACHE, encoding='utf-8'))
        return d.get(str(pid), {}).get(key)
    except Exception:
        return None


def _singleton_cache_put(pid, key, addr):
    try:
        import json as _j
        d = {}
        if os.path.exists(_SINGLETON_CACHE):
            try:
                d = _j.load(open(_SINGLETON_CACHE, encoding='utf-8'))
            except Exception:
                d = {}
        d = {str(pid): d.get(str(pid), {})}       # one game process at a time; older pids are dead anyway
        d[str(pid)][key] = addr
        _j.dump(d, open(_SINGLETON_CACHE, 'w', encoding='utf-8'))
    except Exception:
        pass


def _cached_singleton_ok(sess, class_name, addr, namespace):
    """A cached address must pass the SAME plausibility probe the live scan applies to a candidate, not just
    the klass-pointer check. PoGo keeps a STALE second instance of PokemonBagImpl / TaggingRpcService around
    (see _pick_singleton_live); after a big tag write the cached TaggingRpcService read 0 bindings for every
    tag (2026-09-09 01:00, reconcile 'produced no tag table') because the type check cannot tell the live
    instance from the stale one. Cheap reads only -- no liveness scan, no world stop."""
    scr = get_script_with_helpers(sess, _SVC_PROBE_JS)
    try:
        if not scr.exports_sync.check_instance(addr, namespace, class_name):
            return False
        if class_name == 'PokemonBagImpl':
            return len(scr.exports_sync.bag_walk(addr)) >= 100
        if class_name == 'TaggingRpcService':
            pr = scr.exports_sync.probe_number_of_tags(addr)
            n = pr.get('n', -1) if pr.get('ok') else -1
            return 0 < n < 200
        if class_name == 'PokedexImpl':
            pr = scr.exports_sync.probe_dex_count(addr)
            n = pr.get('n', -1) if pr.get('ok') else -1
            return 500 <= n <= 4000
        return True
    except Exception:
        return False
    finally:
        scr.unload()


def pick_singleton(sess, namespace, class_name, fresh=False):
    """Resolve the live singleton of namespace.class_name -- from the per-pid CACHE when the address still
    validates (a klass-pointer read, no world stop), else via the liveness scan (which stops the GC world),
    followed by a freeze probe. 2026-09-09: the liveness scan is the last world-stopping call in the tool
    chain, so it now runs ONCE per game process instead of 2-3 times per pass."""
    key = namespace + '.' + class_name
    # THE ATTACHED PID (Stage 5, speed study 2026-09-24): get_session stamps it on the session, so a pick costs no adb
    # round trips (it used to run adb connect + get-state + pidof, ~3 calls over Tailscale, ~10-12 picks a pass). It is
    # also the more correct cache key: the session belongs to that pid. A session from elsewhere has no stamp -> the
    # old adb path, unchanged.
    pid = getattr(sess, '_pogo_pid', None)
    if pid is None:
        try:
            devser = _resolve_device()
            pid = _adb_pidof(devser) if devser else None
        except Exception:
            pid = None
    if pid and not fresh:                            # fresh=True: the cached address read garbage -- re-pick
        cached = _singleton_cache_get(pid, key)
        if cached and _cached_singleton_ok(sess, class_name, cached, namespace):
            return cached
    addr = _pick_singleton_live(sess, namespace, class_name)
    rescue_frozen_world(sess, 'liveness scan for %s' % key)
    if pid and addr:
        _singleton_cache_put(pid, key, addr)
    return addr


def _pick_singleton_live(sess, namespace, class_name):
    """Like find_singleton but handles multi-instance via class-specific probes.

    PoGo sometimes presents 2 live instances of PokemonBagImpl / TaggingRpcService
    / PokedexImpl (one real, one stale). Probes each candidate to pick the working
    one. Falls back to first hit for unknown classes.
    """
    script = get_script_with_helpers(sess)
    try:
        r = script.exports_sync.find_singleton(namespace, class_name)
        if 'err' in r:
            raise RuntimeError(f'pick_singleton({namespace}.{class_name}): {r["err"]}')
        hits = r.get('hits', [])
    finally:
        script.unload()
    if not hits:
        raise RuntimeError(f'no instances of {namespace}.{class_name}')
    if len(hits) == 1:
        return hits[0]

    if class_name == 'PokemonBagImpl':
        s = get_script_with_helpers(sess)
        try:
            best, best_n = None, -1
            for c in hits:
                try:
                    n = len(s.exports_sync.bag_walk(c))
                    if n > best_n: best, best_n = c, n
                except Exception: pass
            if best_n < 100:
                raise RuntimeError(f'No PokemonBagImpl with >100 entries (best={best_n})')
            return best
        finally:
            s.unload()
    if class_name == 'TaggingRpcService':
        s = get_script_with_helpers(sess, _SVC_PROBE_JS)
        try:
            best, best_n = None, -1
            for c in hits:
                try:
                    pr = s.exports_sync.probe_number_of_tags(c)
                    n = pr.get('n', -1) if pr.get('ok') else -1
                    if 0 < n < 200 and n > best_n: best, best_n = c, n
                except Exception: pass
            if best is None:
                raise RuntimeError(f'No TaggingRpcService with plausible NumberOfTags ({len(hits)} candidates)')
            return best
        finally:
            s.unload()
    if class_name == 'IapService':
        # 2026-09-19: the first hit was a stale instance after a restart and read stardust 0 / coins 0. The live one
        # holds the account's balance; take the largest (a genuinely empty balance still yields a valid pick).
        s = get_script_with_helpers(sess, _SVC_PROBE_JS)
        try:
            best, best_n = None, -1
            for c in hits:
                try:
                    pr = s.exports_sync.probe_stardust(c)
                    n = pr.get('n', -1) if pr.get('ok') else -1
                    if n > best_n: best, best_n = c, n
                except Exception: pass
            return best or hits[0]
        finally:
            s.unload()
    if class_name == 'PokedexImpl':
        s = get_script_with_helpers(sess, _SVC_PROBE_JS)
        try:
            best, best_n = None, -1
            for c in hits:
                try:
                    pr = s.exports_sync.probe_dex_count(c)
                    n = pr.get('n', -1) if pr.get('ok') else -1
                    if 500 <= n <= 4000 and n > best_n: best, best_n = c, n
                except Exception: pass
            if best is None:
                raise RuntimeError(f'No PokedexImpl with plausible dict size ({len(hits)} candidates)')
            return best
        finally:
            s.unload()
    # Unknown class — return first hit
    return hits[0]


def walk_bag_protos(sess, bag_addr_str, retries=5, min_count=100):
    """Walk PokemonBagImpl LinkedHashMap. Returns {uid_str: proto_ptr_str}.

    GUARANTEED COMPLETE: the walk freezes the GC and reports the declared list count; if the traversal
    came up short (a node faulted, or the bag was mid-load) we RE-WALK rather than return a partial map.
    A silently-truncated walk used to make reconcile/preflight read fewer tagged protos than really exist
    and report phantom DRIFT (user 2026-06-16: "WTF is this partial walk"). Raises if it can't get a
    complete walk after `retries` tries -- callers must never act on a known-incomplete bag read."""
    import time as _time
    script = get_script_with_helpers(sess)
    try:
        last = {}
        for attempt in range(retries):
            r = script.exports_sync.bag_walk_checked(bag_addr_str)
            last = r
            declared, walked, trunc = r.get('declared', -1), r.get('walked', 0), bool(r.get('truncated'))
            complete = (not trunc) and declared >= min_count and walked >= declared
            if complete:
                return r['map']
            _time.sleep(0.4)   # let the GC settle / bag finish loading, then re-walk
        raise RuntimeError(
            'bag walk INCOMPLETE after %d tries: walked %s of declared %s (truncated=%s, min=%d) -- '
            'refusing to return a partial bag map%s' % (
                retries, last.get('walked'), last.get('declared'), last.get('truncated'), min_count,
                ('  [%s]' % last['err']) if last.get('err') else ''))
    finally:
        script.unload()


def find_protos_for_uids(sess, bag_addr_str, uid_str_list, retries=5, min_count=100):
    """Walk PokemonBagImpl filtered to a target UID set. Returns {uid_str: proto_ptr_str}.

    COMPLETENESS-CHECKED since 2026-09-02. This used to call the UNCHECKED bagFindForUids export, which
    returns only `.map` and throws away declared/walked/truncated -- so a broken or capped walk yielded
    fewer protos than uids and the caller could not tell "this uid is not in the bag" (released, traded)
    apart from "the walk fell over". Its consumers are TAG WRITE paths (tag_ops.py, prune_server_tag.py,
    apply_tagsets.py), where that distinction decides whether a mon gets tagged at all. The checked twin
    already existed and had zero callers.

    Genuinely-absent uids are still tolerated -- they are simply missing from the returned map. What is
    no longer tolerated is a walk that did not finish."""
    import time as _time
    uids = list(uid_str_list)          # materialize once: the caller may pass a generator
    script = get_script_with_helpers(sess)
    try:
        last = {}
        for attempt in range(retries):
            r = script.exports_sync.bag_find_for_uids_checked(bag_addr_str, uids)
            last = r
            declared, walked, trunc = r.get('declared', -1), r.get('walked', 0), bool(r.get('truncated'))
            if (not trunc) and declared >= min_count and walked >= declared:
                return r['map']
            _time.sleep(0.4)
        raise RuntimeError(
            'filtered bag walk INCOMPLETE after %d tries: walked %s of declared %s (truncated=%s, '
            'min=%d) -- refusing to return a partial proto map for %d requested uid(s)%s' % (
                retries, last.get('walked'), last.get('declared'), last.get('truncated'), min_count,
                len(uids), ('  [%s]' % last['err']) if last.get('err') else ''))
    finally:
        script.unload()

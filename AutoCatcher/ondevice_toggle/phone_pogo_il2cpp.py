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

function liveness_find_instances(klass) {
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
    try:
        out = subprocess.check_output(['adb', 'devices'], stderr=subprocess.DEVNULL).decode()
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) == 2 and parts[1] == 'device' and parts[0] != ADB_TARGET:
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


def restart_pogo_and_wait(launch_timeout=90, settle=8):
    """RETIRED 2026-09-29. Tools never force-stop, restart or launch PoGo (the user: "never restart the game.
    ever."; Pokemod must be the one that launches it, and the on-phone catcher runs on it). Kept as a stub so an
    old caller fails loudly instead of killing the game. If PoGo is down, ask the user to reopen it."""
    raise RuntimeError('restart_pogo_and_wait is retired: tools never force-stop or relaunch PoGo. '
                       'Ask the user to reopen the game.')


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
        raise RuntimeError(f'frida attach timed out via {devser} — frida-server is down/unreachable '
                           '(restart frida-server on the phone or reconnect Tailscale).')
    if 'sess' in res:
        return res['sess'], res['pid']
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


def pick_singleton(sess, namespace, class_name):
    """Resolve the live singleton of namespace.class_name -- from the per-pid CACHE when the address still
    validates (a klass-pointer read, no world stop), else via the liveness scan (which stops the GC world),
    followed by a freeze probe. 2026-09-09: the liveness scan is the last world-stopping call in the tool
    chain, so it now runs ONCE per game process instead of 2-3 times per pass."""
    key = namespace + '.' + class_name
    pid = None
    try:
        devser = _resolve_device()
        pid = _adb_pidof(devser) if devser else None
    except Exception:
        pid = None
    if pid:
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

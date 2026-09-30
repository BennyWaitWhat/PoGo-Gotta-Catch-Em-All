/* ============================================================================
 * catch.js  —  SELF-CONTAINED on-device PoGo auto-catcher for Frida GADGET
 *              SCRIPT MODE (ZygiskFrida in-process gadget).
 *
 * NO Python, NO rpc host, NO ADB, NO desktop. The gadget auto-runs this file
 * on every PoGo launch. Everything below is self-finding and self-driving.
 *
 * Ported 1:1 from:
 *   - system/scripts/game_write/catch_loop_fast.py   (the catcher JS + driver)
 *   - pogo_il2cpp.py  JS_PREAMBLE                     (Unity liveness finder)
 *
 * ARCHITECTURE (why there is no setInterval):
 *   Frida gadget *script mode* has a known bug where setTimeout/setInterval can
 *   hang and never fire (frida issue #2848). So we drive EVERYTHING off the
 *   per-frame Interceptor hook on CameraFollowingGround.LateUpdate -> tick().
 *   That callback runs on PoGo's own render thread (engine native-callback path,
 *   independent of the JS timer subsystem), so it is immune to #2848.
 *
 *   The Python side used to: (a) find singletons & push their pointers in,
 *   (b) loop every ~0.6s doing ball-floor checks / refill / reset-seen.
 *   We fold ALL of that into:
 *     - install()         : hooks (pump + prob/catch result), runs ONCE at load.
 *     - manage()          : called from tick() on a wall-clock gate (~1.0s).
 *                           Lazily finds singletons (PoGo isn't ready at load),
 *                           reads ball counts, sets availability, refills the
 *                           queue, honors the ON/OFF toggle file, re-arms on idle.
 *
 * TOGGLE:
 *   A marker FILE controls ON/OFF. Existence of TOGGLE_FILE == catching ON.
 *   The home-screen button just creates/removes that file (via su). We POLL it
 *   here (in manage()), so the toggle needs NO gadget reload and NO re-hook.
 *     ON  : `su -c 'touch  /data/local/tmp/re.zyg.fri/catch.on'`
 *     OFF : `su -c 'rm -f  /data/local/tmp/re.zyg.fri/catch.on'`
 *
 * CONFIG is hard-coded below (mirrors catch_loop_fast.py constants exactly).
 * ==========================================================================*/

'use strict';

/* ----------------------------- HARD-CODED CONFIG ------------------------- */
var CFG = {
  TOGGLE_FILE:   '/data/local/tmp/re.zyg.fri/catch.on', // exists => ON
  LOG_FILE:      '/data/local/tmp/re.zyg.fri/catch.log', // optional debug log
  HEARTBEAT_FILE:'/data/local/tmp/re.zyg.fri/catch.hb',  // epoch|RUN|OPENED|caught, written ~1/s (watchdog liveness)
  RATE_PER_MIN:  35,        // opens/min target (framerate-independent)
  MAX_RANGE_M:   80.0,      // GPS cutoff: between catchable(~64-69m) and flee(~85m)
  POKE_FLOOR:    5,         // stop using a ball type at/below this many left
  GREAT_FLOOR:   5,
  ULTRA_FLOOR:   5,
  CATCH_THRESHOLD: 0.5,     // cheapest ball whose BASE catch prob >= this, else step up
  LAG_MS:        3500,      // open -> throw latency hide (pipeline depth)
  RETHROW_DELAY: 2000,      // ms before re-throw on break-out/miss
  MAXTHROW:      4,         // max throws per encounter (1 + 3 re-throws)
  USE_PINAP:     false,     // OFF (saving Pinap); flip true + raise floor to enable
  PINAP_FLOOR:   20,
  PINAP_ID:      705,
  BERRY_LAG:     1800,      // ms after open before feeding a berry
  QUEUE_LOW:     20,        // refill the spawn queue when below this
  MANAGE_MS:     1000,      // wall-clock gate for the management block in tick()
  IDLE_REARM:    8,         // consecutive fully-idle manage() passes -> reset seen
  // Legendaries/mythicals/UBs (national dex #s) — NEVER auto-catch; skip in filter.
  LEGENDARY_DEX: [144,145,146,150,151,243,244,245,249,250,251,377,378,379,380,381,382,383,384,385,386,480,481,482,483,484,485,486,487,488,489,490,491,492,493,494,638,639,640,641,642,643,644,645,646,647,648,649,716,717,718,719,720,721,772,773,785,786,787,788,789,790,791,792,793,794,795,796,797,798,799,800,801,802,803,804,805,806,807,808,809,888,889,890,891,892,893,894,895,896,897,898,905,1001,1002,1003,1004,1007,1008,1014,1015,1016,1017,1024,1025]
};

/* ------------------------------- LOGGER ---------------------------------- */
/* In gadget SCRIPT mode there is NO connected host, so plain console.log is
 * DROPPED (and qjs' console.log carries no useful logcat tag). So we route to
 * Android logcat ourselves via __android_log_write under a fixed tag.
 *   View on-device / from PC:   logcat -s frida-catch
 * We ALSO best-effort mirror to a file (catch.log) for `tail -f`, but note the
 * PoGo process runs as an app uid and may be DENIED writing into the shell-owned
 * /data/local/tmp by SELinux — so the file is a bonus, logcat is the source of
 * truth. (Refs: frida gadget docs + issue #382 — console.log needs a host;
 * use __android_log_write for autonomous logging.) */
var _alw = (function () {
  try {
    var liblog = Process.findModuleByName('liblog.so');
    var p = liblog ? liblog.findExportByName('__android_log_write') : null;
    if (!p) return null;
    var fn = new NativeFunction(p, 'int', ['int', 'pointer', 'pointer']);
    var tag = Memory.allocUtf8String('frida-catch');
    return function (s) { try { fn(3 /*DEBUG*/, tag, Memory.allocUtf8String(s)); } catch (e) {} };
  } catch (e) { return null; }
})();
function log(s) {
  var line = '[catch] ' + s;
  if (_alw) { _alw(line); } else { try { console.log(line); } catch (e) {} }
  try {
    var fd = new File(CFG.LOG_FILE, 'a');
    fd.write(_ts() + ' ' + line + '\n');
    fd.flush(); fd.close();
  } catch (e) {}
}
function _ts() {
  var d = new Date();
  function p(n){ return (n<10?'0':'')+n; }
  return p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());
}

/* ===========================================================================
 * SECTION A — IL2CPP handle table  (from catch_loop_fast.py JS, verbatim
 *             offsets) PLUS the liveness exports (from pogo_il2cpp.py).
 * ==========================================================================*/
var H = null;
function H_() {
  if (H) return H;
  var il = Process.findModuleByName('libil2cpp.so');
  if (!il) return null;                       // not mapped yet -> caller retries
  var e = {};
  il.enumerateExports().forEach(function (x) {
    if (x.name.indexOf('il2cpp_') === 0) e[x.name] = x.address;
  });
  function b(n, r, a) { return e[n] ? new NativeFunction(e[n], r, a) : null; }
  H = {
    // --- core (catch_loop_fast.py) ---
    dG:  b('il2cpp_domain_get', 'pointer', []),
    dGA: b('il2cpp_domain_get_assemblies', 'pointer', ['pointer', 'pointer']),
    aGI: b('il2cpp_assembly_get_image', 'pointer', ['pointer']),
    iGN: b('il2cpp_image_get_name', 'pointer', ['pointer']),
    iGCC:b('il2cpp_image_get_class_count', 'uint32', ['pointer']),
    iGC: b('il2cpp_image_get_class', 'pointer', ['pointer', 'uint32']),
    CGN: b('il2cpp_class_get_name', 'pointer', ['pointer']),
    CGNS:b('il2cpp_class_get_namespace', 'pointer', ['pointer']),
    OGC: b('il2cpp_object_get_class', 'pointer', ['pointer']),
    cMN: b('il2cpp_class_get_method_from_name', 'pointer', ['pointer', 'pointer', 'int']),
    rI:  b('il2cpp_runtime_invoke', 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']),
    oN:  b('il2cpp_object_new', 'pointer', ['pointer']),
    isVT:b('il2cpp_class_is_valuetype', 'int', ['pointer']),
    cGM: b('il2cpp_class_get_methods', 'pointer', ['pointer', 'pointer']),
    mGN: b('il2cpp_method_get_name', 'pointer', ['pointer']),
    mGPC:b('il2cpp_method_get_param_count', 'uint32', ['pointer']),
    tA:  b('il2cpp_thread_attach', 'pointer', ['pointer']),
    // --- liveness / GC (pogo_il2cpp.py) for self-finding singletons ---
    cFN: b('il2cpp_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']),
    rcInit: b('il2cpp_runtime_class_init', 'void', ['pointer']),
    alloc:  b('il2cpp_alloc', 'pointer', ['size_t']),
    free:   b('il2cpp_free', 'void', ['pointer']),
    livenessAlloc:       b('il2cpp_unity_liveness_allocate_struct', 'pointer', ['pointer', 'int', 'pointer', 'pointer', 'pointer']),
    livenessFromStatics: b('il2cpp_unity_liveness_calculation_from_statics', 'void', ['pointer']),
    livenessFinalize:    b('il2cpp_unity_liveness_finalize', 'void', ['pointer']),
    livenessFreeStruct:  b('il2cpp_unity_liveness_free_struct', 'void', ['pointer']),
    stopWorld:  b('il2cpp_stop_gc_world', 'void', []),
    startWorld: b('il2cpp_start_gc_world', 'void', [])
  };
  H.tA(H.dG());
  return H;
}

function img(name) {
  var h = H_(); if (!h) return null;
  var sp = Memory.alloc(4);
  var a = h.dGA(h.dG(), sp);
  var n = sp.readS32();
  for (var i = 0; i < n; i++) {
    var im = h.aGI(a.add(i * Process.pointerSize).readPointer());
    if (h.iGN(im).readCString() === name) return im;
  }
  return null;
}
function findClass(image, cls) {
  var h = H_(); if (!h) return null;
  var im = img(image); if (!im) return null;
  var cnt = h.iGCC(im);
  for (var i = 0; i < cnt; i++) {
    var k = h.iGC(im, i);
    if (k.isNull()) continue;
    try { if (h.CGN(k).readCString() === cls) return k; } catch (e) {}
  }
  return null;
}
function mOf(k, nm, argc) {
  var h = H_(); if (!h || !k) return null;
  var m = h.cMN(k, Memory.allocUtf8String(nm), argc);
  return (m && !m.isNull()) ? m : null;
}
function inv(m, obj, params) {
  var h = H_(); if (!h || !m) return null;
  var n = params ? params.length : 0;
  var args = ptr(0);
  if (n) {
    args = Memory.alloc(Process.pointerSize * n);
    for (var i = 0; i < n; i++) args.add(i * Process.pointerSize).writePointer(params[i]);
  }
  var exc = Memory.alloc(Process.pointerSize);
  exc.writePointer(ptr(0));
  var r = h.rI(m, obj, args, exc);
  if (!exc.readPointer().isNull()) return null;
  return r;
}

/* ===========================================================================
 * SECTION B — Unity liveness object finder (ported from pogo_il2cpp.py
 *             liveness_find_instances). Enumerates LIVE instances of a class.
 *             Returns array of NativePointer (the live objects).
 * ==========================================================================*/
function classFromName(image, ns, cls) {
  var h = H_(); if (!h) return null;
  var im = img(image); if (!im) return null;
  if (!h.cFN) return findClass(image, cls); // fallback if export missing
  var k = h.cFN(im, Memory.allocUtf8String(ns), Memory.allocUtf8String(cls));
  return (k && !k.isNull()) ? k : null;
}

function livenessFind(klass) {
  var h = H_();
  if (!h || !h.livenessAlloc || !h.livenessFromStatics) return [];
  if (h.rcInit) { try { h.rcInit(klass); } catch (e) {} }
  var hits = [];
  // NativeCallbacks must be kept referenced for the duration of the call.
  var onObjects = new NativeCallback(function (objects, count, userData) {
    for (var i = 0; i < count; i++) {
      hits.push(objects.add(i * Process.pointerSize).readPointer());
    }
  }, 'void', ['pointer', 'int', 'pointer']);
  var realloc = new NativeCallback(function (handle, size, userData) {
    if (!handle.isNull() && size.compare(0) === 0) { h.free(handle); return ptr(0); }
    return h.alloc(size);
  }, 'pointer', ['pointer', 'size_t', 'pointer']);
  try {
    if (h.stopWorld) h.stopWorld();
    var state = h.livenessAlloc(klass, 0, onObjects, ptr(0), realloc);
    h.livenessFromStatics(state);
    if (h.livenessFinalize) h.livenessFinalize(state);
    if (h.startWorld) h.startWorld();
    if (h.livenessFreeStruct) h.livenessFreeStruct(state);
  } catch (e) {
    if (h.startWorld) { try { h.startWorld(); } catch (e2) {} }
    return [];
  }
  return hits;
}

/* class_name(instance) — used to discriminate liveness hits, like Python's
 * sc.exports_sync.cls_name(h). */
function clsNameOf(inst) {
  try { return H_().CGN(H_().OGC(inst)).readCString(); } catch (e) { return null; }
}
/* call a 0-arg int getter on instance (mirrors Python call0i) */
function call0i(inst, name) {
  var m = mOf(H_().OGC(inst), name, 0);
  if (!m) return -999;
  var r = inv(m, inst, []);
  try { return r ? r.add(0x10).readS32() : -998; } catch (e) { return -997; }
}
/* namespace lookup for a class living in holo-game.dll (mirrors Python ns_of) */
function nsOfGame(cls) {
  var h = H_(); if (!h) return null;
  var im = img('holo-game.dll'); if (!im) return null;
  var cnt = h.iGCC(im);
  for (var i = 0; i < cnt; i++) {
    var k = h.iGC(im, i);
    if (k.isNull()) continue;
    try { if (h.CGN(k).readCString() === cls) return h.CGNS(k).readCString(); } catch (e) {}
  }
  return null;
}

/* ===========================================================================
 * SECTION C — Catcher state + ItemBag count (from catch_loop_fast.py).
 * ==========================================================================*/
var PBT = null, PBT_VT = false, BALL = 2, FRAME = 0, lastOpenMs = 0;
var INTERVAL_MS = 1714, LAG_MS = 3500, FIRED = 0, OPENED = 0, RUN = false;
var AVAIL = { 1: true, 2: true, 3: true }, THRESH = 0.5;
var Q = [], INFLIGHT = [];
var THROWN = [], RETHROW = [], MAXTHROW = 4, RETHROW_DELAY = 2000, REFIRED = 0;
var CR = { s: 0, e: 0, f: 0, m: 0, err: 0 };
var IB = ptr(0), BERRY_PINAP = false, PINAP_ID = 705, BERRY_LAG = 1800, NBERRY = 0;
var ATTEMPTED = {};
var SEEN = {}, MAPSVC = ptr(0), VISONLY = true, MAPAVATAR = ptr(0), MAXR = 90.0, LEGENDARY = {};
var IAP = ptr(0);
var PROBCACHE = {}, PCN = 0;
var LASTSEEN = 0, LASTINR = 0;

/* ItemBag.GetItemCount(item) -> int  (returns -1.. on failure, like Python) */
function itemCount(item) {
  var h = H_(); if (!h || IB.isNull()) return -1;
  var m = h.cMN(h.OGC(IB), Memory.allocUtf8String('GetItemCount'), 1);
  if (!m || m.isNull()) return -1;
  var arg = Memory.alloc(4); arg.writeS32(item);
  var args = Memory.alloc(Process.pointerSize); args.writePointer(arg);
  var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
  var ret = h.rI(m, IB, args, exc);
  if (!exc.readPointer().isNull()) return -2;
  if (ret.isNull()) return -3;
  try { return ret.add(0x10).readS32(); } catch (e) { return -4; }
}

/* find the ItemBag class (the one exposing GetItemCount), like Python findItemBag */
function findItemBagClass() {
  var h = H_(); if (!h) return null;
  var imgs = ['holo-game.dll', 'holo-protos.dll'];
  for (var ii = 0; ii < imgs.length; ii++) {
    var im = img(imgs[ii]); if (!im) continue;
    var cnt = h.iGCC(im);
    for (var i = 0; i < cnt; i++) {
      var k = h.iGC(im, i); if (k.isNull()) continue;
      try {
        var nm = h.CGN(k).readCString();
        if (/^I[A-Z]/.test(nm)) continue;               // skip interfaces
        var m = h.cMN(k, Memory.allocUtf8String('GetItemCount'), 1);
        if (m && !m.isNull()) return { ns: h.CGNS(k).readCString(), cls: nm, klass: k, image: imgs[ii] };
      } catch (e) {}
    }
  }
  return null;
}

/* ===========================================================================
 * SECTION D — Spawn refill (verbatim from catch_loop_fast.py refillService),
 *             converted from rpc export to a plain function using globals.
 * ==========================================================================*/
function refillService() {
  var h = H_(); if (!h || MAPSVC.isNull()) return -9;
  var gm = mOf(h.OGC(MAPSVC), 'get_AllPokemon', 0); if (!gm) return -1;
  var e = inv(gm, MAPSVC, []); if (!e || e.isNull()) return 0;
  var gem = mOf(h.OGC(e), 'GetEnumerator', 0); if (!gem) return -2;
  var enr = inv(gem, e, []); if (!enr || enr.isNull()) return 0;
  var enrC = h.OGC(enr); var self = h.isVT(enrC) ? enr.add(0x10) : enr;
  var mn = mOf(enrC, 'MoveNext', 0), gc = mOf(enrC, 'get_Current', 0); if (!mn || !gc) return -3;
  var plat = null, plng = null;
  if (!MAPAVATAR.isNull()) {
    var lm = mOf(h.OGC(MAPAVATAR), 'get_Location', 0);
    if (lm) { var lr = inv(lm, MAPAVATAR, []); if (lr) { plat = lr.add(0x10).readDouble(); plng = lr.add(0x18).readDouble(); } }
  }
  function distM(a, o) {
    var R = 6371000, p1 = plat * Math.PI / 180, p2 = a * Math.PI / 180,
        dp = (a - plat) * Math.PI / 180, dl = (o - plng) * Math.PI / 180;
    var x = Math.sin(dp / 2) * Math.sin(dp / 2) + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) * Math.sin(dl / 2);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(x)));
  }
  var added = 0, guard = 0, seenct = 0, inr = 0;
  while (guard++ < 3000) {
    var r = inv(mn, self, []); if (!r || r.add(0x10).readU8() === 0) break;
    var cur = inv(gc, self, []); if (!cur || cur.isNull()) continue;
    try {
      var em = mOf(h.OGC(cur), 'get_EncounterId', 0); if (!em) continue;
      var er = inv(em, cur, []); if (!er) continue;
      var enc = er.add(0x10).readU64(); if (enc.compare(uint64(0)) === 0) continue;
      var key = enc.toString(); if (SEEN[key] || ATTEMPTED[key]) continue;
      var pm = mOf(h.OGC(cur), 'get_PokemonId', 0);
      if (pm) { var pr = inv(pm, cur, []); if (pr && LEGENDARY[pr.add(0x10).readS32()]) continue; }
      if (VISONLY) {
        var vm = mOf(h.OGC(cur), 'get_VisibleOnMap', 0);
        if (vm) { var vr = inv(vm, cur, []); if (!vr || vr.add(0x10).readU8() === 0) continue; }
      }
      seenct++;
      if (plat !== null) {
        var lm2 = mOf(h.OGC(cur), 'get_Location', 0);
        if (lm2) { var lr2 = inv(lm2, cur, []); if (lr2) { if (distM(lr2.add(0x10).readDouble(), lr2.add(0x18).readDouble()) > MAXR) continue; } }
      }
      inr++;
      SEEN[key] = 1; Q.push(cur); added++;
    } catch (e2) {}
  }
  LASTSEEN = seenct; LASTINR = inr;
  return added;
}

/* ===========================================================================
 * SECTION E — install(): build PokeballThrow, hook the per-frame pump, the
 *             EncounterOutProto prob-cache, and CatchPokemonOutProto results.
 *             VERBATIM from catch_loop_fast.py JS install().
 * ==========================================================================*/
function readCP(cp) {
  try {
    if (!cp || cp.isNull()) return null;
    var bRF = cp.add(0x10).readPointer(), pRF = cp.add(0x18).readPointer();
    if (bRF.isNull() || pRF.isNull()) return null;
    var bA = bRF.add(0x10).readPointer(), bC = bRF.add(0x18).readS32(),
        pA = pRF.add(0x10).readPointer(), pC = pRF.add(0x18).readS32();
    var n = Math.min(bC, pC); if (n <= 0 || n > 8) return null;
    var m = {};
    for (var i = 0; i < n; i++) { m[bA.add(0x20 + i * 4).readS32()] = pA.add(0x20 + i * 4).readFloat(); }
    return m;
  } catch (e) { return null; }
}
function readProbs(t) {
  try {
    var em = mOf(H_().OGC(t), 'get_EncounterId', 0); if (!em) return null;
    var er = inv(em, t, []); if (!er) return null;
    return PROBCACHE[er.add(0x10).readU64().toString()] || null;
  } catch (e) { return null; }
}
function pickBall(pr) {
  var ord = [1, 2, 3];
  if (pr) {
    for (var i = 0; i < 3; i++) { var b = ord[i]; if (AVAIL[b] && pr[b] !== undefined && pr[b] >= THRESH) return b; }
    var best = 0, bp = -1;
    for (var i = 0; i < 3; i++) { var b = ord[i]; if (AVAIL[b] && pr[b] !== undefined && pr[b] > bp) { bp = pr[b]; best = b; } }
    if (best > 0) return best;
  }
  for (var i = 0; i < 3; i++) { if (AVAIL[ord[i]]) return ord[i]; }
  return BALL;
}
function useBerry(t, itemId) {
  try {
    if (IB.isNull()) return;
    var bm = mOf(H_().OGC(IB), 'UseItemForEncounter', 2); if (!bm) return;
    var ip = Memory.alloc(4); ip.writeS32(itemId);
    inv(bm, IB, [ip, t]); NBERRY++;
  } catch (e) {}
}
function fireOpen(t) {
  try { var sm = mOf(H_().OGC(t), 'SendEncounterRequest', 0); if (sm) inv(sm, t, []); } catch (e) {}
}
function fireCatch(t, attempts) {
  try {
    var ball = pickBall(readProbs(t));
    var tm = mOf(H_().OGC(t), 'TryCapture', 2); if (!tm) return;
    var obj = H_().oN(PBT);
    obj.add(0x10).writeS32(ball);                       // ball id
    obj.add(0x14).writeFloat(0.02 + Math.random() * 0.10); // reticle 0.02..0.12 = Excellent
    obj.add(0x18).writeU8(1);                           // spin/curve = 1
    obj.add(0x19).writeU8(1);                           // bullseye   = 1
    obj.add(0x1a).writeU8(0);
    var p = PBT_VT ? obj.add(0x10) : obj;
    inv(tm, t, [p, ptr(0)]);
    THROWN.push({ t: t, a: attempts || 1, ts: Date.now() });
    try {
      var _em = mOf(H_().OGC(t), 'get_EncounterId', 0);
      if (_em) { var _er = inv(_em, t, []); if (_er) { var _enc = _er.add(0x10).readU64().toString(); ATTEMPTED[_enc] = 1; } }
    } catch (e) {}
  } catch (e) {}
}
function onCatchResult(status, thr) {
  try {
    var it = THROWN.shift(); if (!it) return;
    if (status === 1) { CR.s++; return; }               // 1 = success
    if (status === 3) { CR.f++; return; }               // 3 = flee
    if (status === 2 || status === 4) {                 // 2 = escape, 4 = miss
      if (status === 2) CR.e++; else CR.m++;
      if (it.a < MAXTHROW && thr > 0) { it.due = Date.now() + RETHROW_DELAY; RETHROW.push(it); }
      return;
    }
    CR.err++;
  } catch (e) {}
}

/* engine-readiness gate (Edit 1): don't attach the LateUpdate pump until the
 * game DLL + a known method resolve AND the assemblies walk is non-empty. This
 * proves IL2CPP metadata is fully live (not half-mapped at process launch),
 * closing the early-hook SIGSEGV window (Liveness.cpp / pre-menu native crash
 * class). tryInstall() already retries every frame while install() returns
 * {err}, so a not-ready return just means "try again next frame". */
function engineReady() {
  try {
    var h = H_(); if (!h) return false;
    var cam = findClass('holo-game.dll', 'CameraFollowingGround');
    if (!cam) return false;
    if (!mOf(cam, 'LateUpdate', 0)) return false;
    var sp = Memory.alloc(4);
    h.dGA(h.dG(), sp);
    return sp.readS32() > 0;          // assemblies present == metadata live
  } catch (e) { return false; }
}

function install() {
  var h = H_(); if (!h) return { err: 'libil2cpp not mapped' };
  if (!engineReady()) return { err: 'engine not ready (pre-menu)' };
  var st = {};
  PBT = findClass('holo-game.dll', 'PokeballThrow');
  if (PBT) PBT_VT = !!h.isVT(PBT);
  st.pbt = !!PBT;

  // per-frame pump: CameraFollowingGround.LateUpdate -> tick()
  var camC = findClass('holo-game.dll', 'CameraFollowingGround');
  var mLU = mOf(camC, 'LateUpdate', 0);
  if (mLU) {
    var ad = mLU.readPointer();
    if (!ad.isNull()) { Interceptor.attach(ad, { onEnter: function (a) { tick(); } }); st.pump = true; }
  }

  // EncounterOutProto.MergeFrom -> cache per-ball capture probabilities
  var eop = findClass('holo-protos.dll', 'EncounterOutProto');
  if (eop) {
    var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
    var m, hooked = 0;
    while ((m = h.cGM(eop, it)) && !m.isNull()) {
      try {
        if (h.mGN(m).readCString() !== 'MergeFrom') continue;
        if (h.mGPC(m) !== 1) continue;
        var code = m.readPointer(); if (!code || code.isNull()) continue;
        Interceptor.attach(code, {
          onEnter: function (a) { this.self = a[0]; },
          onLeave: function (r) {
            try {
              var s = this.self; if (!s || s.isNull()) return;
              var pk = s.add(0x10).readPointer(); if (pk.isNull()) return;
              var enc = pk.add(0x10).readU64().toString(); if (enc === '0') return;
              var pr = readCP(s.add(0x20).readPointer());
              if (pr) { if (PCN++ > 400) { PROBCACHE = {}; PCN = 0; } PROBCACHE[enc] = pr; }
            } catch (e) {}
          }
        });
        hooked++;
      } catch (e) {}
    }
    st.probhook = hooked;
  }

  // CatchPokemonOutProto.MergeFrom -> result status (success/escape/flee/miss)
  var cpo = findClass('holo-protos.dll', 'CatchPokemonOutProto');
  if (cpo) {
    var it2 = Memory.alloc(Process.pointerSize); it2.writePointer(ptr(0));
    var m2, ch = 0;
    while ((m2 = h.cGM(cpo, it2)) && !m2.isNull()) {
      try {
        if (h.mGN(m2).readCString() !== 'MergeFrom') continue;
        if (h.mGPC(m2) !== 1) continue;
        var c2 = m2.readPointer(); if (!c2 || c2.isNull()) continue;
        Interceptor.attach(c2, {
          onEnter: function (a) { this.self = a[0]; },
          onLeave: function (r) {
            try { var s = this.self; if (!s || s.isNull()) return; onCatchResult(s.add(0x10).readS32(), s.add(0x38).readS32()); } catch (e) {}
          }
        });
        ch++;
      } catch (e) {}
    }
    st.catchhook = ch;
  }
  return st;
}

/* ===========================================================================
 * SECTION F — tick(): the per-frame pump (VERBATIM from catch_loop_fast.py)
 *             PLUS a wall-clock-gated manage() call that replaces the Python
 *             driver loop. tick() is invoked from the LateUpdate hook.
 * ==========================================================================*/
function tick() {
  // management block (singleton find / ball floors / refill / toggle) — gated
  try {
    var nowm = Date.now();
    if (nowm - lastManageMs >= CFG.MANAGE_MS) { lastManageMs = nowm; manage(); }
  } catch (em) {}

  if (!RUN) return;
  FRAME++;
  try {
    var now = Date.now();
    while (THROWN.length > 0 && (now - THROWN[0].ts) > 9000) THROWN.shift(); // drop never-heard responses
    for (var i = 0; i < RETHROW.length; i++) {
      if (now >= RETHROW[i].due) { var ri = RETHROW.splice(i, 1)[0]; i--; fireCatch(ri.t, ri.a + 1); REFIRED++; }
    }
    if (now - lastOpenMs >= INTERVAL_MS && Q.length > 0) { var t = Q.shift(); fireOpen(t); INFLIGHT.push([t, now, 0]); lastOpenMs = now; OPENED++; }
    if (BERRY_PINAP && !IB.isNull()) {
      for (var bi = 0; bi < INFLIGHT.length; bi++) { var ie = INFLIGHT[bi]; if (!ie[2] && (now - ie[1]) >= BERRY_LAG) { useBerry(ie[0], PINAP_ID); ie[2] = 1; } }
    }
    while (INFLIGHT.length > 0 && (now - INFLIGHT[0][1]) >= LAG_MS) { var e = INFLIGHT.shift(); fireCatch(e[0], 1); FIRED++; }
  } catch (err) {}
}

/* ===========================================================================
 * SECTION G — manage(): replaces the entire Python while-loop. Runs ~1/sec
 *             from tick(). Lazily resolves singletons (PoGo not ready at load),
 *             reads ball counts, enforces floors, refills, honors toggle file,
 *             re-arms on idle. NO setInterval (frida #2848 safe).
 * ==========================================================================*/
var lastManageMs = 0;
var READY = false;          // singletons resolved at least once
var lastToggle = null;      // last observed toggle-file state
var idleN = 0;
var manageBusy = false;
var lastReportMs = 0;
var setupTries = 0;

function toggleOn() {
  try { var f = new File(CFG.TOGGLE_FILE, 'r'); f.close(); return true; } catch (e) { return false; }
}

/* Resolve a singleton by (ns, cls) using liveness, filtered like the Python
 * find1(): keep the live hit whose class name matches and whose getter int is
 * the largest non-negative (identifies the real, server-backed instance). */
function findSingletonBest(image, ns, cls, getter) {
  var klass = classFromName(image, ns, cls); if (!klass) return ptr(0);
  var hits = livenessFind(klass);
  var best = ptr(0), bestv = null;
  for (var i = 0; i < hits.length; i++) {
    var hptr = hits[i];
    if (clsNameOf(hptr) !== cls) continue;
    if (getter) {
      var v = call0i(hptr, getter);
      if (v !== null && v >= 0 && (bestv === null || v > bestv)) { best = hptr; bestv = v; }
    } else {
      // first matching hit (used for MapPlaceDirectoryService / MapAvatar)
      best = hptr; break;
    }
  }
  return best;
}

/* one-time-ish heavy setup: find PBT pump already installed; resolve the 4
 * singletons. Retries every manage() pass until everything is found, because
 * at process launch IL2CPP / the GC world / inventory aren't ready yet. */
function ensureSetup() {
  var h = H_(); if (!h) return false;               // libil2cpp not mapped yet
  if (!PBT) return false;                            // install() hasn't bound PBT yet

  // MapPlaceDirectoryService (spawn source)
  if (MAPSVC.isNull()) {
    var ns = nsOfGame('MapPlaceDirectoryService');
    if (ns) { var m = findSingletonBest('holo-game.dll', ns, 'MapPlaceDirectoryService', null); if (!m.isNull()) { MAPSVC = m; SEEN = {}; } }
  }
  // MapAvatar (player GPS)
  if (MAPAVATAR.isNull()) {
    var nsa = nsOfGame('MapAvatar');
    if (nsa) { var a = findSingletonBest('holo-game.dll', nsa, 'MapAvatar', null); if (!a.isNull()) MAPAVATAR = a; }
  }
  // ItemBag (ball counts + berries) — discriminate by a successful GetItemCount
  if (IB.isNull()) {
    var ibc = findItemBagClass();
    if (ibc) {
      var hits = livenessFind(ibc.klass);
      for (var i = 0; i < hits.length; i++) {
        IB = hits[i];                                 // tentatively set so itemCount() can probe
        if (itemCount(1) >= 0) break;                 // GetItemCount(Poke) works -> real bag
        IB = ptr(0);
      }
    }
  }
  // IapService (stardust readout only; optional) — pick the server-backed one
  if (IAP.isNull()) {
    var nsi = nsOfGame('IapService');
    if (nsi) {
      var klass = classFromName('holo-game.dll', nsi, 'IapService');
      if (klass) {
        var ih = livenessFind(klass), best = ptr(0), bk = null;
        for (var j = 0; j < ih.length; j++) {
          if (clsNameOf(ih[j]) !== 'IapService') continue;
          var coins = call0i(ih[j], 'get_Coins');
          var dv = call0i(ih[j], 'get_Stardusts');
          if (coins === null || coins < 0) continue;
          var key = coins * 1e9 + (dv >= 0 ? dv : 0);   // coins-major, dust tie-break
          if (bk === null || key > bk) { best = ih[j]; bk = key; }
        }
        if (!best.isNull()) IAP = best;
      }
    }
  }

  // Push static config into the catcher once core singletons exist.
  MAXR = CFG.MAX_RANGE_M;
  THRESH = CFG.CATCH_THRESHOLD;
  LEGENDARY = {};
  for (var k = 0; k < CFG.LEGENDARY_DEX.length; k++) LEGENDARY[CFG.LEGENDARY_DEX[k]] = 1;
  INTERVAL_MS = Math.max(400, Math.round(60000 / CFG.RATE_PER_MIN));
  LAG_MS = CFG.LAG_MS;
  RETHROW_DELAY = CFG.RETHROW_DELAY;
  MAXTHROW = CFG.MAXTHROW;
  BERRY_LAG = CFG.BERRY_LAG;
  PINAP_ID = CFG.PINAP_ID;

  // "ready enough" to catch: need the spawn source + a working item bag.
  return (!MAPSVC.isNull() && !IB.isNull());
}

function manage() {
  if (manageBusy) return;          // liveness stops the GC world; never re-enter
  manageBusy = true;
  try {
    if (!READY) {
      setupTries++;
      if (ensureSetup()) {
        READY = true;
        log('READY — msvc=' + (!MAPSVC.isNull() ? 'ok' : 'NO') +
            ' avatar=' + (!MAPAVATAR.isNull() ? 'ok' : 'NO') +
            ' itembag=' + (!IB.isNull() ? 'ok' : 'NO') +
            ' iap=' + (!IAP.isNull() ? 'ok' : 'NO') +
            ' | Poke=' + itemCount(1) + ' Great=' + itemCount(2) + ' Ultra=' + itemCount(3) +
            ' Stardust=' + (IAP.isNull() ? -1 : call0i(IAP, 'get_Stardusts')));
      } else {
        if (setupTries === 1 || setupTries % 15 === 0)
          log('waiting for PoGo to load (try ' + setupTries + ') ...');
        return;
      }
    }

    // ---- toggle: existence of TOGGLE_FILE == catching ON ----
    var on = toggleOn();
    if (on !== lastToggle) {
      lastToggle = on;
      RUN = !!on;
      log(on ? '>>> TOGGLE ON  — catching' : '<<< TOGGLE OFF — idle');
      if (on) { SEEN = {}; refillService(); }     // fresh scan when turned on
    }
    if (!RUN) return;                             // toggled off: do nothing else

    // ---- ball-floor management (Python's set_avail + auto-stop) ----
    var p = itemCount(1), g = itemCount(2), u = itemCount(3);
    AVAIL = { 1: p > CFG.POKE_FLOOR, 2: g > CFG.GREAT_FLOOR, 3: u > CFG.ULTRA_FLOOR };
    if (0 <= p && p <= CFG.POKE_FLOOR && 0 <= g && g <= CFG.GREAT_FLOOR && 0 <= u && u <= CFG.ULTRA_FLOOR) {
      RUN = false;
      log('===== auto-stopped (all balls at floor) — flip OFF/ON to resume after restock =====');
      return;
    }

    // ---- berry feeding gate (OFF by default) ----
    BERRY_PINAP = CFG.USE_PINAP && (itemCount(CFG.PINAP_ID) > CFG.PINAP_FLOOR);

    // ---- refill the spawn queue when low ----
    if (Q.length < CFG.QUEUE_LOW) refillService();

    // ---- stall recovery: fully idle -> re-arm seen-set and rescan ----
    if (Q.length === 0 && INFLIGHT.length === 0 && THROWN.length === 0 && RETHROW.length === 0) {
      idleN++;
      if (idleN >= CFG.IDLE_REARM) { SEEN = {}; refillService(); idleN = 0; }
    } else { idleN = 0; }

    // ---- periodic stats line (~every 10s) ----
    var nowr = Date.now();
    if (nowr - lastReportMs >= 10000) {
      lastReportMs = nowr;
      var dust = IAP.isNull() ? -1 : call0i(IAP, 'get_Stardusts');
      log('run | dust=' + dust + ' | fired=' + FIRED + ' refired=' + REFIRED +
          ' | caught=' + CR.s + ' esc=' + CR.e + ' flee=' + CR.f + ' miss=' + CR.m +
          ' | q=' + Q.length + ' vis=' + LASTSEEN + ' inr=' + LASTINR +
          ' | P=' + p + ' G=' + g + ' U=' + u + ' pc=' + Object.keys(PROBCACHE).length);
    }

    // ---- heartbeat (Edit 2): written ~1/s whenever manage() runs, so a stale
    //      catch.hb file == wedged script. The external watchdog reads this to
    //      decide whether to force-stop+relaunch PoGo with no human in the loop.
    //      Best-effort only: the PoGo app-uid may be SELinux-denied from writing
    //      /data/local/tmp, in which case the file simply won't update and the
    //      catcher itself is UNAFFECTED (logcat 'frida-catch' is the truth). ----
    writeHeartbeat();
  } catch (e) {
    log('manage err: ' + e);
  } finally {
    manageBusy = false;
  }
}

/* heartbeat line: epoch_seconds | RUN | OPENED | caught  (matches §1F watchdog) */
function writeHeartbeat() {
  try {
    var hb = new File(CFG.HEARTBEAT_FILE, 'w');
    hb.write(Math.floor(Date.now() / 1000) + '|' + (RUN ? 1 : 0) + '|' + OPENED + '|' + CR.s + '\n');
    hb.flush(); hb.close();
  } catch (e) {}
}

/* ===========================================================================
 * SECTION H — entrypoint. In gadget script mode, rpc.exports.init() runs once
 *             at load (stage 'early' or 'late'). We install hooks here. The
 *             LateUpdate hook then self-drives tick()/manage() forever; no
 *             setInterval (immune to frida #2848). install() may run before
 *             libil2cpp is mapped — if so, we retry install from manage().
 * ==========================================================================*/
var INSTALLED = false;
function tryInstall(where) {
  if (INSTALLED) return;
  var st = install();
  if (st && st.pump && st.pbt) {
    INSTALLED = true;
    log('installed (' + where + '): ' + JSON.stringify(st));
  } else {
    // libil2cpp not ready yet; manage() will keep retrying (but manage()
    // only runs once the pump exists, so retry install on a bare timer-free
    // path: piggyback on the FIRST few LateUpdate frames is impossible w/o the
    // hook, so we re-attempt install from a lightweight poll hook below).
    log('install deferred (' + where + '): ' + JSON.stringify(st));
  }
}

/* Bootstrap install retry WITHOUT setInterval:
 * Hook a very-frequently-called libc symbol as a temporary heartbeat ONLY to
 * retry install() until the il2cpp pump hook lands; then detach it. This dodges
 * the script-mode timer bug entirely. We use 'clock_gettime' (called every
 * frame by the engine). Once INSTALLED, the listener is removed and all driving
 * happens via the il2cpp LateUpdate hook. */
function armBootstrap() {
  if (INSTALLED) return;
  // Frida 17 REMOVED the static Module.findExportByName/getExportByName. Resolve
  // via the Module INSTANCE (F17-safe), with a global fallback. (Refs: frida 17
  // release notes — "static Module.* methods are gone"; instance methods kept.)
  var sym = null;
  try {
    var libc = Process.findModuleByName('libc.so');
    if (libc) { sym = libc.findExportByName('clock_gettime'); }
  } catch (e) {}
  if (!sym) {
    try { sym = Module.getGlobalExportByName('clock_gettime'); } catch (e2) {}
  }
  if (!sym) { tryInstall('no-bootstrap'); return; }
  var listener = Interceptor.attach(sym, {
    onEnter: function () {
      if (INSTALLED) { try { listener.detach(); } catch (e) {} return; }
      // throttle: only attempt every ~64th call to keep overhead negligible
      if (((bootN++) & 0x3f) !== 0) return;
      tryInstall('bootstrap');
      if (INSTALLED) { try { listener.detach(); } catch (e) {} }
    }
  });
}
var bootN = 0;

rpc.exports = {
  init: function (stage, parameters) {
    log('init stage=' + stage + ' — self-contained on-device catcher loading');
    // Optional: allow a couple of CFG overrides via gadget config "parameters".
    try {
      if (parameters) {
        if (typeof parameters.rate === 'number')  CFG.RATE_PER_MIN = parameters.rate;
        if (typeof parameters.range === 'number') CFG.MAX_RANGE_M = parameters.range;
        if (typeof parameters.toggle === 'string') CFG.TOGGLE_FILE = parameters.toggle;
      }
    } catch (e) {}
    // Try immediate install; if il2cpp isn't mapped yet, arm a timer-free retry.
    tryInstall('init');
    if (!INSTALLED) armBootstrap();
    // NOTE: we intentionally return undefined (sync) so the gadget resumes the
    // app immediately. All catching is driven by the LateUpdate hook thereafter.
  },
  // dispose() runs when the gadget unloads OR (with on_change:"reload") just
  // BEFORE a new copy of this script loads. We MUST detach our Interceptor hooks
  // here, else a hot-edit reload double-attaches the LateUpdate pump (two ticks
  // per frame). detachAll() reverts every Interceptor.attach this script made.
  dispose: function () {
    try { Interceptor.detachAll(); } catch (e) {}
    RUN = false; INSTALLED = false;
    log('dispose — detached hooks, script unloading');
  }
};

/* Native-fault visibility: in script mode there is no host to surface a crash,
 * so a bad pointer deref silently takes PoGo down. Log the fault (file + logcat)
 * so a post-mortem can tell "script native fault" from "unrelated PoGo crash".
 * Return false = let the OS handle it (clean crash); we do NOT swallow faults
 * (swallowing can corrupt state worse than crashing). Ref: frida #2039 — native
 * il2cpp faults are only visible once setExceptionHandler is installed. */
try {
  Process.setExceptionHandler(function (d) {
    try { log('NATIVE FAULT ' + d.type + ' @' + d.address + ' pc=' + (d.context && d.context.pc)); } catch (e) {}
    return false;
  });
} catch (e) {}

/* If this file is loaded by a non-gadget runner (e.g. `frida -l catch.js`)
 * where init() isn't auto-called, still bootstrap. Harmless under the gadget
 * because INSTALLED guards re-entry. */
try { tryInstall('toplevel'); if (!INSTALLED) armBootstrap(); } catch (e) {}

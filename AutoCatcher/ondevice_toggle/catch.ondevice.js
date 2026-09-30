/* ============================================================================
 * catch.ondevice.js — SELF-CONTAINED on-device PoGo auto-catcher for Frida
 *   GADGET SCRIPT MODE (ZygiskFrida in-process gadget, QuickJS runtime).
 *
 * This is the HOOK-BASED catcher. It supersedes catch.fixed.js (whose ONLY
 * defect was livenessFind() — a Unity stop-the-world GC liveness walk that
 * native-faulted the game when run from the render thread). Rename this to
 * catch.js on deploy, or point config.script.so's interaction.path at this file.
 *
 * NO Python, NO rpc host, NO ADB, NO desktop. The gadget auto-runs this file
 * on PoGo launch. Everything below is self-finding and self-driving.
 * View logs on-device / from PC:   logcat -s frida-catch
 *
 * Ported 1:1 (catch quality byte-identical) from:
 *   - system/scripts/game_write/catch_loop_fast.py   (the catcher JS + driver)
 *   - system/ondevice_toggle/catch.fixed.js          (bootstrap/gate/kill-switch)
 *
 * ----------------------------------------------------------------------------
 * WHAT CHANGED vs catch.fixed.js  (the ONE defect we are killing)
 * ----------------------------------------------------------------------------
 * catch.fixed.js was correct in every respect EXCEPT object discovery: it found
 * its 4 singletons (MapPlaceDirectoryService, MapAvatar, ItemBag, IapService)
 * with a Unity stop-the-world liveness walk
 * (il2cpp_stop_gc_world -> il2cpp_unity_liveness_* -> il2cpp_start_gc_world).
 * That path is CONFIRMED to native-fault PoGo even once when run from the render
 * thread (it suspends the GC world from inside a managed render frame). There is
 * NO safe way to run it in-process.
 *
 * This file removes the GC walk ENTIRELY. A grep of this file for
 * il2cpp_stop_gc_world / il2cpp_start_gc_world / livenessAlloc /
 * livenessFromStatics / livenessFinalize / livenessFreeStruct returns ZERO.
 * ALL object discovery is now HOOK-BASED — we capture `this` pointers from
 * methods the game ITSELF calls on the render thread, so no metadata walk and no
 * world-stop ever happen:
 *
 *   - SPAWNS (wild Pokemon, replaces MapPlaceDirectoryService.get_AllPokemon):
 *       The recon proved the GAME never calls get_AllPokemon (0 calls/45s), so
 *       it can't be hooked and the old MAPSVC enumeration could never see a
 *       spawn. Instead we hook a MapPokemon spawn-lifecycle method (Setup /
 *       OnEnable / InitBase / PlaySpawnFx — whichever resolves) and, on fire,
 *       read get_EncounterId off the captured `this` and store `this` in a live
 *       SPAWNS map keyed by encounterId. We ALSO hook a teardown method
 *       (OnDestroy / Destroy / HandleDestroy / OnDisable) to delete from SPAWNS
 *       so targets never go stale. The pipeline iterates SPAWNS (range-filtered,
 *       legendary-skipped) instead of get_AllPokemon. Spawns already on screen
 *       before load are caught once they refresh — fine for a walking user.
 *
 *   - MAPAVATAR (player GPS, range filter): hook MapAvatar.get_Location (0-arg),
 *       capture `this` on first call (recon: game calls it ~23000x/45s — instant
 *       and reliable). Cached for the haversine range filter exactly like the
 *       desktop (avatar Location +0x10 lat / +0x18 lng doubles).
 *
 *   - IB (ItemBag, ball counts): find the ItemBag class the same way the desktop
 *       does (the non-interface class exposing GetItemCount(1-arg)) and hook its
 *       GetItemCount, capturing `this` on first call (recon: ~8x/45s — works,
 *       just slower). Cached for ball floors. Until captured we throw the default
 *       BALL and assume all balls available.
 *
 *   - IapService / stardust: REMOVED entirely (recon: game never calls
 *       get_Stardusts on the map; pure telemetry, not needed to catch).
 *
 *   - PokeballThrow / EncounterOutProto / CatchPokemonOutProto: KEPT unchanged
 *       (findClass-by-name + hooks; proven to install cleanly in script mode).
 *
 * Everything else (clock_gettime readiness bootstrap, engine/foreground
 * readiness gate, first-fault kill-switch, the CameraFollowingGround.LateUpdate
 * frame pump, the EncounterOutProto + CatchPokemonOutProto hooks, and the FULL
 * catch logic — data-driven ball pick, Excellent reticle 0.02-0.12, curve +
 * bullseye, re-throw on catch status 2/4, haversine range filter, legendary
 * skip-list, marker-file toggle) is BYTE-FAITHFUL to catch.fixed.js.
 *
 * Because discovery is now hook-based, there is no "stop-the-world discovery
 * pass" to frame-gate. The READY_FRAMES warmup is REPURPOSED: it now gates only
 * the installation of the (cheap, non-stop-world) discovery hooks behind a
 * proven-foregrounded engine, so we never attach to half-mapped metadata. The
 * MapAvatar/ItemBag/spawn capture itself is passive thereafter.
 *
 * Timer note: NO setInterval/setTimeout (broken in gadget script mode, frida
 * issue #2848). The clock is the LateUpdate hook itself (the proven design); a
 * temporary clock_gettime Interceptor only retries install() until the pump
 * lands, then detaches.
 *
 * TOGGLE: existence of CFG.TOGGLE_FILE == catching ON. The home button creates/
 * removes it (via su). We POLL it in manage() (no gadget reload, no re-hook).
 *     ON  : su -c 'touch  /data/local/tmp/re.zyg.fri/catch.on'
 *     OFF : su -c 'rm -f  /data/local/tmp/re.zyg.fri/catch.on'
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
  // FOREGROUND / engine-readiness gate. In catch.fixed.js this gated the
  // world-stopping discovery pass. Here there is NO world-stop; it gates only
  // the installation of the (cheap, hook-based) discovery hooks behind a proven
  // foregrounded engine, so we never attach to half-mapped metadata. A
  // backgrounded Unity game does not pump LateUpdate, so this stalls and hook
  // installation correctly waits (no crash, just inert).
  READY_FRAMES:  90,        // require this many real LateUpdate frames (~3s @30fps)
  // Legendaries/mythicals/UBs (national dex #s) — NEVER auto-catch; skip in filter.
  LEGENDARY_DEX: [144,145,146,150,151,243,244,245,249,250,251,377,378,379,380,381,382,383,384,385,386,480,481,482,483,484,485,486,487,488,489,490,491,492,493,494,638,639,640,641,642,643,644,645,646,647,648,649,716,717,718,719,720,721,772,773,785,786,787,788,789,790,791,792,793,794,795,796,797,798,799,800,801,802,803,804,805,806,807,808,809,888,889,890,891,892,893,894,895,896,897,898,905,1001,1002,1003,1004,1007,1008,1014,1015,1016,1017,1024,1025]
};

/* ------------------------------- LOGGER ---------------------------------- */
/* In gadget SCRIPT mode there is NO connected host, so plain console.log is
 * DROPPED. Route to Android logcat ourselves via __android_log_write under a
 * fixed tag.   View:  logcat -s frida-catch
 * We ALSO best-effort mirror to a file (catch.log); the PoGo app uid may be
 * SELinux-denied from /data/local/tmp, so the file is a bonus, logcat is truth. */
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

/* Global kill-switch: set true on the FIRST native fault so nothing re-enters
 * the broken native path. Turns a per-frame fault storm into a single fault. */
var CRASHED = false;

/* ===========================================================================
 * SECTION A — IL2CPP handle table  (verbatim offsets from catch_loop_fast.py)
 *
 * CRITICAL CHANGE vs the ORIGINAL desktop preamble: H_() does NOT attach the
 * thread or touch the domain/GC at build time. It is pure export resolution. The
 * desktop did `H.tA(H.dG())` here, which on an early/bootstrap thread (pre-
 * il2cpp_init) dereferenced a garbage domain. Attaching is now done ONLY by
 * attachSelf(), ONLY behind a non-null domain, and ONLY from the render thread.
 *
 * NOTE vs catch.fixed.js: the liveness / GC export quartet
 * (il2cpp_stop_gc_world, il2cpp_start_gc_world, il2cpp_unity_liveness_*) has
 * been DELETED from this table — we no longer bind or call any of them. Object
 * discovery is hook-based (Sections C/E), so the stop-the-world machinery is
 * gone entirely.
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
    tA:  b('il2cpp_thread_attach', 'pointer', ['pointer'])
  };
  return H;                                   // NOTE: no H.tA(H.dG()) here (was the early-deref bug)
}

/* Attach the CURRENT (render) thread to il2cpp. Idempotent + cheap (returns the
 * existing Il2CppThread if already attached). Guarded so a null/early domain
 * never gets passed in. Called from engineReady()/tick() so every managed call
 * from the render thread runs on a valid attached GC context. */
function attachSelf() {
  var h = H_(); if (!h || !h.tA || !h.dG) return false;
  try {
    var dom = h.dG();
    if (!dom || dom.isNull()) return false;   // il2cpp_init not done yet
    h.tA(dom);
    return true;
  } catch (e) { return false; }
}

function img(name) {
  var h = H_(); if (!h) return null;
  var sp = Memory.alloc(4);
  var a = h.dGA(h.dG(), sp);
  if (!a || a.isNull()) return null;
  var n = sp.readS32();
  for (var i = 0; i < n; i++) {
    var ap = a.add(i * Process.pointerSize).readPointer();
    if (ap.isNull()) continue;
    var im = h.aGI(ap);
    if (im.isNull()) continue;
    var nm = h.iGN(im);
    if (!nm.isNull() && nm.readCString() === name) return im;
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

/* class_name(instance) — used to discriminate captured `this` pointers (the
 * spawn-hook may also fire on subclasses), like Python's cls_name(h). */
function clsNameOf(inst) {
  try { return H_().CGN(H_().OGC(inst)).readCString(); } catch (e) { return null; }
}
/* call a 0-arg int getter on instance (mirrors Python call0i). Kept for any
 * future use; not required by the hook-based path. */
function call0i(inst, name) {
  var m = mOf(H_().OGC(inst), name, 0);
  if (!m) return -999;
  var r = inv(m, inst, []);
  try { return r ? r.add(0x10).readS32() : -998; } catch (e) { return -997; }
}

/* ===========================================================================
 * SECTION C — Catcher state + ItemBag count (from catch_loop_fast.py).
 *
 * vs catch.fixed.js: the IAP/IapService state is GONE (stardust readout removed
 * — recon proved the game never calls get_Stardusts on the map; it is pure
 * telemetry not needed to catch). MAPSVC is GONE (get_AllPokemon is never
 * called by the game). They are replaced by the hook-fed SPAWNS map (Section D)
 * and the hook-captured MAPAVATAR / IB pointers (Section E).
 * ==========================================================================*/
var PBT = null, PBT_VT = false, BALL = 2, FRAME = 0, lastOpenMs = 0;
var INTERVAL_MS = 1714, LAG_MS = 3500, FIRED = 0, OPENED = 0, RUN = false;
var AVAIL = { 1: true, 2: true, 3: true }, THRESH = 0.5;
var Q = [], INFLIGHT = [];
var THROWN = [], RETHROW = [], MAXTHROW = 4, RETHROW_DELAY = 2000, REFIRED = 0;
var CR = { s: 0, e: 0, f: 0, m: 0, err: 0 };
var IB = ptr(0), BERRY_PINAP = false, PINAP_ID = 705, BERRY_LAG = 1800, NBERRY = 0;
var ATTEMPTED = {};
var SEEN = {}, VISONLY = true, MAPAVATAR = ptr(0), MAXR = 90.0, LEGENDARY = {};
var PROBCACHE = {}, PCN = 0;
var LASTSEEN = 0, LASTINR = 0;

/* SPAWNS: the live wild-spawn table, keyed by encounterId string -> MapPokemon
 * `this` pointer. Fed by the MapPokemon spawn-hook (onSpawn) and emptied by the
 * teardown-hook (onDespawn) AND by the lazy reap in refillService(). This
 * REPLACES MapPlaceDirectoryService + get_AllPokemon enumeration. SPAWN_N tracks
 * live size for stats/logging. */
var SPAWNS = {};
var SPAWN_N = 0;

/* REG_PTR: throttle map, MapPokemon `this`-pointer string -> 1, meaning "this
 * exact pointer is currently registered in SPAWNS". The PRIMARY spawn capture is
 * a getter hook (MapPokemon.get_VisibleOnMap / get_Location) that the map
 * renderer calls every frame for every visible spawn — hundreds of times/sec. We
 * do NOT want to runtime_invoke get_EncounterId on every one of those fires, so
 * once a pointer is registered we early-out on REG_PTR and never re-invoke for
 * it. REG_PTR is cleared in lock-step with SPAWNS (onDespawn + the refill reap),
 * so a recycled/pooled MapPokemon address that gets reused for a DIFFERENT
 * encounter is re-read on its next fire (the refill re-validation reaps the stale
 * mapping and clears REG_PTR, then the getter re-registers the new encounter).
 * IN_SPAWN_CB is a belt-and-suspenders re-entrancy guard around the handler. */
var REG_PTR = {};
var IN_SPAWN_CB = false;

/* reapSpawn(key): drop a dead/stale spawn from BOTH tables in one place so they
 * never drift. Called by onDespawn and by the refillService lazy reap. */
function reapSpawn(key) {
  try {
    var p = SPAWNS[key];
    if (p !== undefined) { delete SPAWNS[key]; if (SPAWN_N > 0) SPAWN_N--; }
    if (p && typeof p.toString === 'function') delete REG_PTR[p.toString()];
  } catch (e) {}
}

/* FRAME_SEEN: incremented by EVERY LateUpdate tick (even before RUN). Hook
 * installation gates on this to prove the engine is live AND foregrounded+
 * rendering before attaching the discovery hooks. A backgrounded Unity game does
 * not run LateUpdate, so this stalls and hook installation correctly waits (no
 * crash). */
var FRAME_SEEN = 0;

/* ItemBag.GetItemCount(item) on a GIVEN bag pointer (takes the candidate as a
 * parameter, like the desktop count(ibStr,item)). Returns int or <0. Used to
 * read the captured global bag. */
function itemCountOn(ib, item) {
  var h = H_(); if (!h || !ib || ib.isNull()) return -1;
  var m = h.cMN(h.OGC(ib), Memory.allocUtf8String('GetItemCount'), 1);
  if (!m || m.isNull()) return -1;
  var arg = Memory.alloc(4); arg.writeS32(item);
  var args = Memory.alloc(Process.pointerSize); args.writePointer(arg);
  var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
  var ret = h.rI(m, ib, args, exc);
  if (!exc.readPointer().isNull()) return -2;
  if (ret.isNull()) return -3;
  try { return ret.add(0x10).readS32(); } catch (e) { return -4; }
}
function itemCount(item) { return itemCountOn(IB, item); }   // committed global bag

/* find the ItemBag class (the one exposing GetItemCount(1-arg), non-interface),
 * like Python findItemBag. Used only to locate the class whose GetItemCount we
 * HOOK (Section E); the instance is captured passively from the hook, not via
 * any liveness walk. */
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
 * SECTION D — Spawn refill (range/legendary filter from catch_loop_fast.py
 *   refillService, but the SOURCE is the hook-fed SPAWNS map instead of
 *   MapPlaceDirectoryService.get_AllPokemon — the game never calls that). Pure
 *   managed reads on cached `this` pointers; does NOT stop the world. Safe to
 *   call from tick()/manage() after READY.
 *
 *   For each live spawn we read EXACTLY the same fields, at EXACTLY the same
 *   offsets, with EXACTLY the same filters as the desktop's get_AllPokemon walk:
 *     get_EncounterId -> +0x10 readU64   (skip if 0 / SEEN / ATTEMPTED)
 *     get_PokemonId   -> +0x10 readS32   (skip if LEGENDARY)
 *     get_VisibleOnMap-> +0x10 readU8    (skip if not visible, when VISONLY)
 *     get_Location     -> +0x10 lat / +0x18 lng doubles -> haversine vs MAXR
 *   then SEEN[key]=1; Q.push(cur). The player GPS comes from the hook-captured
 *   MAPAVATAR (get_Location +0x10 lat / +0x18 lng), identical to the desktop.
 * ==========================================================================*/
function refillService() {
  if (CRASHED) return -99;
  var h = H_(); if (!h) return -9;
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
  var added = 0, seenct = 0, inr = 0;
  // Iterate the hook-fed live spawn table. Snapshot keys first so onDespawn
  // mutating SPAWNS mid-walk (it can fire on the render thread) is harmless;
  // deleting from the live SPAWNS object while iterating this snapshot is safe.
  //
  // LAZY REAP: the teardown hook is best-effort (its method may not resolve on
  // this build), so this walk — which already touches every key — is the
  // AUTHORITATIVE staleness mechanism. Any entry whose live encounterId no longer
  // matches its key (recycled/pooled pointer), whose object is dead, or that
  // faults on read is reaped here (removed from SPAWNS + REG_PTR). That keeps the
  // table from growing unbounded even if NO teardown hook ever fires, and lets a
  // pooled address re-register for its new encounter on the getter hook's next
  // fire. Entries already in SEEN/ATTEMPTED are live+handled, so they are skipped
  // (not reaped) — onDespawn or a later re-validation removes them.
  var keys = Object.keys(SPAWNS);
  for (var ki = 0; ki < keys.length; ki++) {
    var key = keys[ki];
    var cur = SPAWNS[key];
    if (!cur || cur.isNull()) { reapSpawn(key); continue; }   // dead pointer
    if (SEEN[key] || ATTEMPTED[key]) continue;                // live + handled: skip, don't reap
    try {
      // re-read the live encounter id off the object and confirm it still matches
      // the table key (defends against a recycled/torn-down MapPokemon pointer).
      var em = mOf(h.OGC(cur), 'get_EncounterId', 0); if (!em) { reapSpawn(key); continue; }
      var er = inv(em, cur, []); if (!er) { reapSpawn(key); continue; }
      var enc = er.add(0x10).readU64(); if (enc.compare(uint64(0)) === 0) { reapSpawn(key); continue; }
      if (enc.toString() !== key) { reapSpawn(key); continue; } // pointer recycled to a new encounter
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
    } catch (e2) { reapSpawn(key); }                          // faulted on read: reap the bad entry
  }
  LASTSEEN = seenct; LASTINR = inr;
  return added;
}

/* ===========================================================================
 * SECTION E — install(): build PokeballThrow, hook the per-frame pump, the
 *             EncounterOutProto prob-cache, the CatchPokemonOutProto results,
 *             AND the new hook-based discovery (MapPokemon spawn/teardown,
 *             MapAvatar.get_Location, ItemBag.GetItemCount). VERBATIM throw
 *             mechanics from catch_loop_fast.py.
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

/* ---- hook-based discovery handlers (replace the liveness singleton finds) ---- */

/* onSpawn: the UNIFIED spawn-capture handler, fed by BOTH the per-frame getter
 * hooks (MapPokemon.get_VisibleOnMap / get_Location — the PRIMARY, reliable
 * source: the map renderer calls them for every visible spawn) AND the
 * opportunistic lifecycle hooks (Setup / OnEnable / ...). It registers the
 * captured `this` in the live SPAWNS table keyed by encounterId.
 *
 * THROTTLE: the getter hooks fire hundreds of times/sec across all visible
 * spawns. To avoid a runtime_invoke of get_EncounterId on every fire, we early-
 * out on REG_PTR: once a pointer is registered we do NOTHING (the cheap common
 * case). The (more expensive) class-name check + encounterId read run only for a
 * pointer we have not registered yet — i.e. once per fresh spawn, or once after a
 * pooled pointer was reaped. IN_SPAWN_CB guards against any re-entrancy.
 * Class-name checked so a fired subclass/look-alike never pollutes the table.
 * All reads use the SAME offsets as the desktop (get_EncounterId +0x10 readU64). */
function onSpawn(self) {
  if (CRASHED || IN_SPAWN_CB || !self || self.isNull()) return;
  var ps;
  try { ps = self.toString(); } catch (e) { return; }
  if (REG_PTR[ps]) return;                              // already registered: cheap no-op
  IN_SPAWN_CB = true;
  try {
    var h = H_(); if (!h) return;
    if (clsNameOf(self) !== 'MapPokemon') return;       // only real wild spawns
    var em = mOf(h.OGC(self), 'get_EncounterId', 0); if (!em) return;
    var er = inv(em, self, []); if (!er) return;
    var enc = er.add(0x10).readU64(); if (enc.compare(uint64(0)) === 0) return; // not assigned yet
    var key = enc.toString();
    if (SPAWNS[key] === undefined) SPAWN_N++;
    SPAWNS[key] = self;
    REG_PTR[ps] = 1;                                    // throttle: skip future fires for this pointer
  } catch (e) {} finally { IN_SPAWN_CB = false; }
}
/* onDespawn: a MapPokemon teardown method fired -> drop it from SPAWNS (and
 * REG_PTR) so the pipeline never iterates a stale/torn-down target. This is
 * BEST-EFFORT only (its method may not resolve on this build); the refillService
 * lazy reap is the authoritative staleness mechanism. We clear the SEEN mark so a
 * genuine re-spawn of the same encounter id can be re-queued — but ONLY when the
 * spawn was NOT already thrown at (ATTEMPTED): a caught-then-despawned encounter
 * must stay suppressed so the catch/despawn animation can't re-queue and re-open
 * it (ATTEMPTED is the durable guard). */
function onDespawn(self) {
  try {
    if (!self || self.isNull()) return;
    var h = H_(); if (!h) return;
    if (clsNameOf(self) !== 'MapPokemon') return;
    var em = mOf(h.OGC(self), 'get_EncounterId', 0); if (!em) return;
    var er = inv(em, self, []); if (!er) return;
    var enc = er.add(0x10).readU64(); if (enc.compare(uint64(0)) === 0) return;
    var key = enc.toString();
    reapSpawn(key);                                     // drop from SPAWNS + REG_PTR together
    if (!ATTEMPTED[key]) delete SEEN[key];              // re-queueable only if never thrown at
  } catch (e) {}
}

/* Attach an Interceptor to method `name`/`argc` on class `klass`, routing the
 * captured first-arg (`this` for an instance method) to handler(self). Returns
 * true if the hook landed. Used for the MapPokemon spawn/teardown hooks. */
function hookThisMethod(klass, name, argc, handler) {
  try {
    var m = mOf(klass, name, argc); if (!m) return false;
    var ad = m.readPointer(); if (!ad || ad.isNull()) return false;
    Interceptor.attach(ad, { onEnter: function (a) { handler(a[0]); } });
    return true;
  } catch (e) { return false; }
}

/* Discovery-hook installer state. These flip true once the relevant hook lands,
 * so install() (which may be retried) never double-attaches. */
var SPAWN_GETTER_HOOKS = 0; // PRIMARY: MapPokemon.get_VisibleOnMap/get_Location capture hooks
var SPAWN_HOOKS = 0;        // OPPORTUNISTIC: MapPokemon lifecycle (Setup/OnEnable/...) hooks
var TEARDOWN_HOOKS = 0;     // count of MapPokemon teardown-hooks installed
var AVATAR_HOOKED = false;  // MapAvatar.get_Location hook installed
var IB_HOOKED = false;      // ItemBag.GetItemCount hook installed
var DISCOVERY_HOOKED = false; // all discovery hooks attempted once (one-shot)
/* the catcher can enumerate targets if ANY spawn-capture hook landed (a getter
 * hook OR a lifecycle hook — both feed onSpawn). The getter hooks are the
 * reliable ones; lifecycle hooks are a bonus. */
function spawnCaptureReady() { return (SPAWN_GETTER_HOOKS + SPAWN_HOOKS) > 0; }

/* listMethodNames(klass): return a comma-list of "name/argc" for every method on
 * a class. Used ONLY for the one-shot diagnostic when no spawn-capture hook lands,
 * so the single on-device test reveals exactly which MapPokemon methods exist on
 * this build. Pure reads (class_get_methods / method_get_name) — no world-stop. */
function listMethodNames(klass) {
  var h = H_(); if (!h || !klass) return '';
  var out = [];
  try {
    var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
    var m;
    while ((m = h.cGM(klass, it)) && !m.isNull()) {
      try { out.push(h.mGN(m).readCString() + '/' + h.mGPC(m)); } catch (e) {}
      if (out.length >= 200) break;
    }
  } catch (e) {}
  return out.join(',');
}

/* installDiscoveryHooks(): attach the hook-based object-discovery interceptors.
 * Called ONCE from manage() after the foreground warmup (READY_FRAMES). NONE of
 * these stop the GC world — they only attach to methods the game itself calls.
 *
 *  - MapPokemon spawn capture — PRIMARY: hook the per-frame getters
 *    get_VisibleOnMap (0-arg) and get_Location (0-arg). These are non-virtual
 *    instance getters DECLARED on MapPokemon, so class_get_method_from_name
 *    resolves a real MapPokemon-specific code pointer, and the map renderer calls
 *    them CONTINUOUSLY for every on-screen wild spawn — so registration is
 *    guaranteed + immediate, and (unlike lifecycle hooks) it also captures spawns
 *    that were already on screen at load. This is the exact pattern already
 *    trusted for MapAvatar.get_Location. onSpawn throttles via REG_PTR so the
 *    high call rate costs almost nothing after first registration.
 *  - MapPokemon spawn capture — OPPORTUNISTIC: also try Setup / OnEnable /
 *    InitBase / PlaySpawnFx (they don't hurt; onSpawn is idempotent per pointer).
 *  - MapPokemon teardown — BEST EFFORT: try OnDestroy / Destroy / HandleDestroy /
 *    OnDisable; attach every one that resolves. NOT depended on — the refill lazy
 *    reap is the authoritative staleness mechanism.
 *  - MapAvatar.get_Location: capture `this` on first call (range filter source).
 *  - ItemBag.GetItemCount: capture `this` on first call (ball-count source).
 *
 * Returns true if at least one spawn-capture hook landed (getter OR lifecycle) —
 * the minimum to ever enumerate targets; avatar/itembag are best-effort and fill
 * in passively as the game calls them. */
function installDiscoveryHooks() {
  if (DISCOVERY_HOOKED) return spawnCaptureReady();
  if (CRASHED) return false;
  var h = H_(); if (!h) return false;
  attachSelf();

  // --- MapPokemon spawn + teardown hooks (replaces get_AllPokemon) ---
  var mpk = findClass('holo-game.dll', 'MapPokemon');
  if (mpk) {
    // PRIMARY: per-frame getters the map renderer calls for every visible spawn.
    // These are the reliable capture; onSpawn's REG_PTR throttle makes the high
    // fire rate cheap.
    var getterNames = ['get_VisibleOnMap', 'get_Location'];
    for (var gi = 0; gi < getterNames.length; gi++) {
      if (hookThisMethod(mpk, getterNames[gi], 0, onSpawn)) SPAWN_GETTER_HOOKS++;
    }
    // OPPORTUNISTIC: lifecycle methods (build-dependent; bonus, not relied upon).
    var spawnNames = ['Setup', 'OnEnable', 'InitBase', 'PlaySpawnFx'];
    for (var si = 0; si < spawnNames.length; si++) {
      // probe likely arg counts (0 then 1) — Setup may take an arg in some builds.
      if (hookThisMethod(mpk, spawnNames[si], 0, onSpawn)) SPAWN_HOOKS++;
      else if (hookThisMethod(mpk, spawnNames[si], 1, onSpawn)) SPAWN_HOOKS++;
    }
    // BEST-EFFORT teardown (refill lazy reap is authoritative; this is a bonus).
    var teardownNames = ['OnDestroy', 'Destroy', 'HandleDestroy', 'OnDisable'];
    for (var ti = 0; ti < teardownNames.length; ti++) {
      if (hookThisMethod(mpk, teardownNames[ti], 0, onDespawn)) TEARDOWN_HOOKS++;
      else if (hookThisMethod(mpk, teardownNames[ti], 1, onDespawn)) TEARDOWN_HOOKS++;
    }
    // Defect-4 diagnostic: if NOTHING resolved, dump the real method list ONCE so
    // the on-device test immediately reveals the correct spawn/teardown names.
    if (!spawnCaptureReady()) {
      log('NO MapPokemon spawn-capture method resolved — MapPokemon methods: ' + listMethodNames(mpk));
    }
  } else {
    log('MapPokemon class not found in holo-game.dll — cannot install spawn capture.');
  }

  // --- MapAvatar.get_Location hook (player GPS, range filter) ---
  if (!AVATAR_HOOKED) {
    var mav = findClass('holo-game.dll', 'MapAvatar');
    if (mav) {
      var glm = mOf(mav, 'get_Location', 0);
      if (glm) {
        var gad = glm.readPointer();
        if (gad && !gad.isNull()) {
          Interceptor.attach(gad, {
            onEnter: function (a) {
              try { if (MAPAVATAR.isNull() && a[0] && !a[0].isNull()) MAPAVATAR = a[0]; } catch (e) {}
            }
          });
          AVATAR_HOOKED = true;
        }
      }
    }
  }

  // --- ItemBag.GetItemCount hook (ball counts) ---
  if (!IB_HOOKED) {
    var ibc = findItemBagClass();
    if (ibc) {
      var gim = mOf(ibc.klass, 'GetItemCount', 1);
      if (gim) {
        var iad = gim.readPointer();
        if (iad && !iad.isNull()) {
          var ibcls = ibc.cls;
          Interceptor.attach(iad, {
            onEnter: function (a) {
              try { if (IB.isNull() && a[0] && !a[0].isNull() && clsNameOf(a[0]) === ibcls) IB = a[0]; } catch (e) {}
            }
          });
          IB_HOOKED = true;
        }
      }
    }
  }

  DISCOVERY_HOOKED = true;     // one-shot: do not re-attempt installs (no double-hook)
  return spawnCaptureReady();
}

/* engine-readiness gate: don't install hooks until the game DLL + LateUpdate
 * resolve AND the assemblies walk is non-empty AND the domain is non-null. This
 * proves IL2CPP metadata is fully live (not half-mapped at process launch),
 * closing the early-hook SIGSEGV window. ALL reads here are non-stop-world,
 * so the probe itself is safe even if called from the bootstrap. Attaches the
 * calling (render) thread first, behind a non-null domain. */
function engineReady() {
  try {
    var h = H_(); if (!h) return false;
    if (!h.dG || !h.dGA) return false;
    var dom = h.dG();
    if (!dom || dom.isNull()) return false;            // il2cpp_init not done yet
    try { h.tA(dom); } catch (e) { return false; }     // attach this thread (safe: dom non-null)
    var sp = Memory.alloc(4);
    var a = h.dGA(dom, sp);
    if (!a || a.isNull() || sp.readS32() <= 0) return false; // assemblies present == metadata live
    var cam = findClass('holo-game.dll', 'CameraFollowingGround');
    if (!cam) return false;
    if (!mOf(cam, 'LateUpdate', 0)) return false;
    return true;
  } catch (e) { return false; }
}

var INSTALLED = false;
function install() {
  if (INSTALLED) return { already: true };
  if (CRASHED) return { err: 'crashed' };
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
  if (st.pump && st.pbt) INSTALLED = true;   // only flip once the pump + PBT are real
  return st;
}

/* ===========================================================================
 * SECTION F — tick(): the per-frame pump (VERBATIM from catch_loop_fast.py)
 *             PLUS a wall-clock-gated manage() call that replaces the Python
 *             driver loop. tick() is invoked from the LateUpdate hook (render
 *             thread). After READY it is PURE queue-shuffling + cached reads; it
 *             NEVER stops the GC world.
 * ==========================================================================*/
var lastManageMs = 0;
function tick() {
  if (CRASHED) return;
  FRAME_SEEN++;                          // foreground gate for hook install (every frame)
  if (!attachSelf()) return;             // ensure THIS render thread is attached (behind non-null domain)

  // management block (hook install / ball floors / refill / toggle) — gated
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
 * SECTION G — discovery-hook gate (frame-gated, NO world-stop) + manage()
 *             (hot path, NO world-stop). manage() runs ~1/s from tick().
 *
 *   vs catch.fixed.js: runDiscovery() (the ONE place that stopped the GC world)
 *   is GONE. In its place, manage() installs the hook-based discovery
 *   interceptors ONCE after the foreground warmup; the singletons (MAPAVATAR /
 *   IB) and the spawn table fill in PASSIVELY thereafter as the game calls the
 *   hooked methods. No liveness, no stop_gc_world, anywhere.
 * ==========================================================================*/
var READY = false;          // discovery hooks installed + config pushed at least once
var lastToggle = null;      // last observed toggle-file state
var idleN = 0;
var lastReportMs = 0;
var setupTries = 0;
var configPushed = false;

function toggleOn() {
  try { var f = new File(CFG.TOGGLE_FILE, 'r'); f.close(); return true; } catch (e) { return false; }
}

/* Push static config into the catcher once (idempotent). */
function pushConfig() {
  if (configPushed) return;
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
  configPushed = true;
}

function manage() {
  if (CRASHED) return;
  try {
    if (!READY) {
      // FOREGROUND GATE: only install the discovery hooks after the engine has
      // rendered READY_FRAMES real frames. Backgrounded => wait, never crash.
      if (FRAME_SEEN < CFG.READY_FRAMES) {
        if (setupTries === 0) log('warming up (frames ' + FRAME_SEEN + '/' + CFG.READY_FRAMES + ') before installing discovery hooks ...');
        return;
      }
      setupTries++;
      if (installDiscoveryHooks()) {
        pushConfig();
        READY = true;
        log('READY (hook-based) — getterHooks=' + SPAWN_GETTER_HOOKS + ' lifecycleHooks=' + SPAWN_HOOKS +
            ' teardownHooks=' + TEARDOWN_HOOKS +
            ' avatarHook=' + (AVATAR_HOOKED ? 'ok' : 'NO') +
            ' itembagHook=' + (IB_HOOKED ? 'ok' : 'NO') +
            ' | avatar/itembag/spawns fill in as the game calls them');
      } else {
        // No spawn-capture hook landed: neither the getters (get_VisibleOnMap/
        // get_Location) nor any lifecycle method resolved on this build (the
        // installer already logged the real MapPokemon method list once).
        // Discovery is one-shot, so we do NOT retry.
        if (DISCOVERY_HOOKED && !spawnCaptureReady()) {
          if (setupTries === 1 || setupTries % 20 === 0)
            log('discovery hooks incomplete (no MapPokemon spawn-capture method resolved) — ' +
                'see the logged MapPokemon method list to pick the right getter/lifecycle name.');
        }
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
    if (!RUN) { writeHeartbeat(); return; }       // toggled off: heartbeat only

    // ---- ball-floor management (Python's set_avail + auto-stop) ----
    // If the ItemBag hook has not captured a bag yet (IB still null), itemCount
    // returns <0; treat that as "unknown -> assume available" so we still throw
    // the default BALL while the bag fills in (exactly the stated fallback).
    var p = itemCount(1), g = itemCount(2), u = itemCount(3);
    if (IB.isNull()) {
      AVAIL = { 1: true, 2: true, 3: true };      // bag not captured yet: assume all balls
    } else {
      AVAIL = { 1: p > CFG.POKE_FLOOR, 2: g > CFG.GREAT_FLOOR, 3: u > CFG.ULTRA_FLOOR };
      if (0 <= p && p <= CFG.POKE_FLOOR && 0 <= g && g <= CFG.GREAT_FLOOR && 0 <= u && u <= CFG.ULTRA_FLOOR) {
        RUN = false;
        log('===== auto-stopped (all balls at floor) — flip OFF/ON to resume after restock =====');
        writeHeartbeat();
        return;
      }
    }

    // ---- berry feeding gate (OFF by default) ----
    BERRY_PINAP = CFG.USE_PINAP && !IB.isNull() && (itemCount(CFG.PINAP_ID) > CFG.PINAP_FLOOR);

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
      log('run | spawns=' + SPAWN_N + ' | fired=' + FIRED + ' refired=' + REFIRED +
          ' | caught=' + CR.s + ' esc=' + CR.e + ' flee=' + CR.f + ' miss=' + CR.m +
          ' | q=' + Q.length + ' vis=' + LASTSEEN + ' inr=' + LASTINR +
          ' | P=' + p + ' G=' + g + ' U=' + u + ' pc=' + Object.keys(PROBCACHE).length +
          ' | avatar=' + (MAPAVATAR.isNull() ? 'NO' : 'ok') + ' bag=' + (IB.isNull() ? 'NO' : 'ok'));
    }

    // ---- heartbeat: written ~1/s whenever manage() runs (watchdog liveness).
    //      Best-effort only (PoGo app-uid may be SELinux-denied from
    //      /data/local/tmp); logcat 'frida-catch' is the source of truth. ----
    writeHeartbeat();
  } catch (e) {
    log('manage err: ' + e);
  }
}

/* heartbeat line: epoch_seconds | RUN | OPENED | caught  (matches the watchdog) */
function writeHeartbeat() {
  try {
    var hb = new File(CFG.HEARTBEAT_FILE, 'w');
    hb.write(Math.floor(Date.now() / 1000) + '|' + (RUN ? 1 : 0) + '|' + OPENED + '|' + CR.s + '\n');
    hb.flush(); hb.close();
  } catch (e) {}
}

/* ===========================================================================
 * SECTION H — entrypoint + timer-free bootstrap.
 *   In gadget script mode, rpc.exports.init() runs once at load (stage 'early'
 *   or 'late'), possibly BEFORE libil2cpp is mapped / il2cpp_init has run. We
 *   try install() immediately; if not ready, we arm a temporary clock_gettime
 *   Interceptor (called every frame by the engine) that retries install() until
 *   the LateUpdate pump lands, then detaches. NO setInterval (immune to frida
 *   #2848). install()/engineReady() do NOT stop the GC world and are fully
 *   guarded against a null/early domain, so this bootstrap cannot fault: the
 *   worst case before il2cpp_init is engineReady() == false. The hook-based
 *   discovery is installed LATER, on the render thread, only after READY_FRAMES
 *   (foreground) — NOT here.
 * ==========================================================================*/
function tryInstall(where) {
  if (INSTALLED || CRASHED) return;
  var st = install();
  if (st && st.pump && st.pbt) {
    log('installed (' + where + '): ' + JSON.stringify(st));
  } else if (st && !st.already && !st.err) {
    log('install deferred (' + where + '): ' + JSON.stringify(st));
  }
  // else: not ready yet (err set) — bootstrap keeps retrying; stay quiet.
}

/* Bootstrap install retry WITHOUT setInterval: hook a very-frequently-called libc
 * symbol (clock_gettime, called every frame by the engine) as a temporary
 * heartbeat ONLY to retry install() until the il2cpp pump hook lands; then detach
 * it. Frida 17 REMOVED the static Module.findExportByName — resolve via the Module
 * INSTANCE (F17-safe), with a global fallback. */
var bootListener = null;
var bootN = 0;
function armBootstrap() {
  if (INSTALLED || CRASHED) return;
  var sym = null;
  try {
    var libc = Process.findModuleByName('libc.so');
    if (libc) { sym = libc.findExportByName('clock_gettime'); }
  } catch (e) {}
  if (!sym) {
    try { sym = Module.getGlobalExportByName('clock_gettime'); } catch (e2) {}
  }
  if (!sym) { tryInstall('no-bootstrap'); return; }
  try {
    bootListener = Interceptor.attach(sym, {
      onEnter: function () {
        if (INSTALLED || CRASHED) { try { bootListener.detach(); } catch (e) {} return; }
        // throttle: only attempt every ~64th call to keep overhead negligible
        if (((bootN++) & 0x3f) !== 0) return;
        tryInstall('bootstrap');
        if (INSTALLED) { try { bootListener.detach(); } catch (e) {} }
      }
    });
  } catch (e) { tryInstall('bootstrap-failed'); }
}

rpc.exports = {
  init: function (stage, parameters) {
    log('init stage=' + stage + ' — hook-based on-device catcher (single-thread, NO GC-walk; hook-fed discovery)');
    // Optional: allow a couple of CFG overrides via gadget config "parameters".
    try {
      if (parameters) {
        if (typeof parameters.rate === 'number')  CFG.RATE_PER_MIN = parameters.rate;
        if (typeof parameters.range === 'number') CFG.MAX_RANGE_M = parameters.range;
        if (typeof parameters.toggle === 'string') CFG.TOGGLE_FILE = parameters.toggle;
      }
    } catch (e) {}
    CRASHED = false;
    // Do NOT touch il2cpp/domain/GC here (may be pre-init). Just try install +
    // arm the timer-free bootstrap; the LateUpdate hook self-drives thereafter.
    tryInstall('init');
    if (!INSTALLED) armBootstrap();
    // Return undefined (sync) so the gadget resumes the app immediately.
  },
  // dispose() runs when the gadget unloads OR (with on_change:"reload") just
  // BEFORE a new copy of this script loads. We MUST detach our Interceptor hooks
  // here, else a hot-edit reload double-attaches the LateUpdate pump (two ticks
  // per frame). We also set CRASHED so any in-flight tick()/manage() bails.
  dispose: function () {
    CRASHED = true;                  // makes tick()/manage() bail immediately
    try { Interceptor.detachAll(); } catch (e) {}
    RUN = false; INSTALLED = false; READY = false;
    log('dispose — detached hooks, script unloading');
  }
};

/* Native-fault visibility AND kill-switch: in script mode there is no host to
 * surface a crash. On the FIRST fault, flip CRASHED so tick()/manage() no-op
 * forever (one fault can NEVER become a per-frame storm). We do NOT swallow
 * (return false) — let the OS handle the actual fault; we only stop our own code
 * from re-triggering it. */
try {
  Process.setExceptionHandler(function (d) {
    try {
      if (!CRASHED) {
        CRASHED = true;
        log('NATIVE FAULT ' + d.type + ' @' + d.address + ' pc=' + (d.context && d.context.pc) +
            ' — KILL-SWITCH set, catcher disabled (no storm)');
      }
    } catch (e) {}
    return false;
  });
} catch (e) {}

/* If this file is loaded by a non-gadget runner (e.g. `frida -l catch.ondevice.js`)
 * where init() isn't auto-called, still bootstrap. Harmless under the gadget
 * because INSTALLED/CRASHED guard re-entry. */
try { tryInstall('toplevel'); if (!INSTALLED) armBootstrap(); } catch (e) {}

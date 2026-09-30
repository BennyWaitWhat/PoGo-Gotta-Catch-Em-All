"""PoGo auto-catcher + auto-spinner, rebuilt 2026-09-24 (the old 1,776-line file is catch_loop_fast.py.bak.v1).

Runs on the phone (Termux) via catch_phone.py -> run_catch.sh -> catcher_ctl.sh, attached to PoGo's loopback
Frida gadget. Toggles are the flag files the AutoCatcher app writes; they are polled live.

Why it is built this way (each rule is a crash we had):
  1. Every managed call into the game runs on UnityMain, inside the CameraFollowingGround.LateUpdate pump. A few lines
     of C (CModule) gate that hook: it fires every frame, but only enters JS every 6th frame (~9x/s) -- Frida's JS lock
     is shared by every script in the gadget, so a per-frame JS hook stalled the game whenever a cull held the lock.
     The object lookup (Unity's liveness walk) also runs in C, world stopped, no JS inside -- see C_SRC.
  2. NativeFunctions use exceptions:'propagate'. Frida's default ('steal') swallowed faults ART raises on purpose
     (CMC GC compaction pages, implicit suspend checks) -- the old log shows "access violation accessing
     0x22e7000", an ART heap page -- and the next MarkCompact stack walk SIGSEGV'd (7 tombstones).
  3. No raw game pointer outlives the tick that read it: Pokemon are tracked by encounter id, and every action
     uses the pointer from a walk of the live list made in that same tick.
"""
import os
import re
import signal
import socket
import subprocess
import sys
import time
from collections import deque

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402  (get_session only; catch_phone.py points it at the local gadget)

AN = os.path.join(ROOT, "system", "analysis", "pokemod")
LOG = os.path.join(AN, "catch_loop.log")
STATE_FILE = "/data/local/tmp/pogo_state.txt"      # read by the AutoCatcher app
FLAGS = {k: f"/data/local/tmp/pogo_{k}.on" for k in ("catch", "spin", "tap", "perfect", "apples")}
COLD_AGE_S = 12      # attach once PoGo is this old; install() then retries every 3 s until the map has loaded.
                     # (30 s was for the old catcher's heavy RPC-thread setup; this one does metadata + one lookup.)
# PAUSE HANDSHAKE: another tool that needs the game to itself (a cull, the reward catcher) writes an epoch-seconds
# deadline here; we detach within ~1 s and stay off until it writes 0 or the deadline passes (dead-man switch).
# Root-created, mode 666 -- Termux cannot create files in /data/local/tmp. Two Frida clients at once killed PoGo.
PAUSE_FILE = "/data/local/tmp/pogo_pause"
# Apple-revealed Pokemon ids (hidden on the map until caught). Kept 30 min in a file: a restart used to forget them and
# they sat on the map uncaught ("Wild 44/0 hidden=41", 2026-09-29 20:11).
REVEALED_FILE = os.path.join(AN, "apple_revealed.json")
# CRASH-LOOP BREAKER: PoGo dying within QUICK_S of our attach, twice in a row, means attaching is what kills it.
# Stop attaching for HOLD_S instead of repeating it (21:06 / 21:07 on 2026-09-24). Toggling catching off/on restarts
# this process and clears the hold.
QUICK_S, HOLD_S = 20, 1800

CFG = {
    "openMs": 300,          # min ms between encounter opens (200/min). 667 was the old cap, set when faster opens
                            # seemed to crash PoGo -- that was the stolen-ART-fault bug, fixed by exceptions:'propagate'
    "maxOpen": 12,          # encounters awaiting a server answer at once
    "thresh": 0.28,         # cheapest ball whose BASE catch prob >= this (throws are Excellent+curve, ~3.4x)
    "floors": {"1": 5, "2": 5, "3": 5},   # keep a few Poke/Great/Ultra
    "pinap": True, "pinapFloor": 5,       # Pinap on every throw that does not need a Razz; keep 5 (user, 2026-09-24)
    "razz": True, "razzFloor": 5, "razzThresh": 0.45,   # Razz (701) only when the throw is hard
    # 706 Golden Razz / 708 Silver Pinap: never touched (standing instruction) -- not even in the item list.
    "legendary": [150, 151, 243, 244, 245, 249, 250, 251, 377, 378, 379, 380, 381, 382, 383, 384, 385, 386,
                  480, 481, 482, 483, 484, 485, 486, 487, 488, 489, 490, 491, 492, 493, 494, 638, 639, 640,
                  641, 642, 643, 644, 645, 646, 647, 648, 649, 716, 717, 718, 719, 720, 721, 772, 773, 785,
                  786, 787, 788, 789, 790, 791, 792, 793, 794, 795, 796, 797, 798, 799, 800, 801, 802, 803,
                  804, 805, 806, 807, 808, 809, 888, 889, 890, 891, 892, 893, 894, 895, 896, 897, 898, 905,
                  1001, 1002, 1003, 1004, 1007, 1008, 1014, 1015, 1016, 1017, 1024, 1025],   # you catch these
    "priority": [999, 1000, 144, 145, 146],   # Gimmighoul/Gholdengo, Galarian birds: open first, best ball
    # Harvest Festival 2026 apple encounters (Applin, flower-crown Cottonee, Skiddo, Lechonk, Smoliv): a HIDDEN Pokemon of
    # these species near you is an apple reveal waiting to be caught. Event ends 2026-10-05 20:00.
    "appleSpecies": [840, 546, 672, 915, 928],
}

JS = r"""
var PS = Process.pointerSize, PROP = {exceptions: 'propagate'};   /* NULL is Frida's own global (ptr 0) */
/* C, compiled in-process by Frida (TinyCC). NO static variables: in this gadget they land on a read-only page (writing
   one SIGSEGV'd PoGo, 23:02) -- all state lives in JS-allocated buffers passed in as `gate` / `hits`. */
var C_SRC = [
  '#include <gum/guminterceptor.h>',
  'typedef struct { void **out; int max; int n; } Hits;',
  'extern long gate[];                 /* [0] frames  [1] enter JS every N frames  [2] last `this`  [3] every frame (tap) */',
  'extern void js_tick(void);',
  'extern void *il2cpp_unity_liveness_allocate_struct(void *filter, int max, void *cb, void *ud, void *re);',
  'extern void il2cpp_unity_liveness_calculation_from_statics(void *st);',
  'extern void il2cpp_unity_liveness_finalize(void *st);',
  'extern void il2cpp_unity_liveness_free_struct(void *st);',
  'extern void il2cpp_stop_gc_world(void);',
  'extern void il2cpp_start_gc_world(void);',
  'extern void *il2cpp_alloc(unsigned long n);',
  'extern void il2cpp_free(void *p);',
  'void onEnter(GumInvocationContext *ic) {',
  '  long f = ++gate[0];',
  '  gate[2] = (long) gum_invocation_context_get_nth_argument(ic, 0);',
  '  if (gate[3] || f % gate[1] == 0) js_tick();',
  '}',
  'static void on_objs(void **objs, int count, void *ud) { Hits *h = (Hits *)ud; int i; for (i = 0; i < count && h->n < h->max; i++) h->out[h->n++] = objs[i]; }',
  'static void *on_re(void *p, unsigned long size, void *ud) { if (p != 0 && size == 0) { il2cpp_free(p); return 0; } return il2cpp_alloc(size); }',
  '/* Unity marks visited objects via the low bit of obj->klass, so the world MUST be stopped -- and nothing in here',
  '   may need Frida\'s JS lock, which a suspended thread can hold. Hence C. */',
  'int find_instances(void *klass, void *hits) {',
  '  void *st; ((Hits *)hits)->n = 0;',
  '  il2cpp_stop_gc_world();',
  '  st = il2cpp_unity_liveness_allocate_struct(klass, 0, (void *)on_objs, hits, (void *)on_re);',
  '  if (st != 0) { il2cpp_unity_liveness_calculation_from_statics(st); il2cpp_unity_liveness_finalize(st); }',
  '  il2cpp_start_gc_world();',
  '  if (st != 0) il2cpp_unity_liveness_free_struct(st);',
  '  return ((Hits *)hits)->n;',
  '}'].join('\n');
var CM = null, GATE = null, TICK = null, FIND = null;
function cInit() {
  var ex = {}, syms = {};
  Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function (x) { ex[x.name] = x.address; });
  ['il2cpp_unity_liveness_allocate_struct', 'il2cpp_unity_liveness_calculation_from_statics', 'il2cpp_unity_liveness_finalize',
   'il2cpp_unity_liveness_free_struct', 'il2cpp_stop_gc_world', 'il2cpp_start_gc_world', 'il2cpp_alloc', 'il2cpp_free'].forEach(function (n) {
    if (!ex[n]) throw new Error('missing ' + n); syms[n] = ex[n]; });
  GATE = Memory.alloc(32); GATE.add(8).writeS64(6);
  TICK = new NativeCallback(function () { try { pump(GATE.add(16).readPointer()); } catch (e) { ST.errs++; } }, 'void', []);
  syms.gate = GATE; syms.js_tick = TICK;
  CM = new CModule(C_SRC, syms);
  FIND = new NativeFunction(CM.find_instances, 'int', ['pointer', 'pointer'], PROP);
}
var IL = null;
function il() {
  if (IL) return IL;
  var mod = Process.findModuleByName('libil2cpp.so'); if (!mod) return null;
  var ex = {}; mod.enumerateExports().forEach(function (x) { if (x.name.indexOf('il2cpp_') === 0) ex[x.name] = x.address; });
  function f(n, r, a) { return ex[n] ? new NativeFunction(ex[n], r, a, PROP) : null; }
  IL = {
    domain: f('il2cpp_domain_get', 'pointer', []), asms: f('il2cpp_domain_get_assemblies', 'pointer', ['pointer', 'pointer']),
    asmImage: f('il2cpp_assembly_get_image', 'pointer', ['pointer']), imageName: f('il2cpp_image_get_name', 'pointer', ['pointer']),
    classCount: f('il2cpp_image_get_class_count', 'uint32', ['pointer']), classAt: f('il2cpp_image_get_class', 'pointer', ['pointer', 'uint32']),
    className: f('il2cpp_class_get_name', 'pointer', ['pointer']), objClass: f('il2cpp_object_get_class', 'pointer', ['pointer']),
    methodByName: f('il2cpp_class_get_method_from_name', 'pointer', ['pointer', 'pointer', 'int']),
    methods: f('il2cpp_class_get_methods', 'pointer', ['pointer', 'pointer']), methodName: f('il2cpp_method_get_name', 'pointer', ['pointer']),
    paramCount: f('il2cpp_method_get_param_count', 'uint32', ['pointer']), retType: f('il2cpp_method_get_return_type', 'pointer', ['pointer']),
    typeName: f('il2cpp_type_get_name', 'pointer', ['pointer']),
    fields: f('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']), fieldName: f('il2cpp_field_get_name', 'pointer', ['pointer']),
    fieldOffset: f('il2cpp_field_get_offset', 'uint32', ['pointer']), isValueType: f('il2cpp_class_is_valuetype', 'int', ['pointer']),
    invoke: f('il2cpp_runtime_invoke', 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']),
    newObject: f('il2cpp_object_new', 'pointer', ['pointer']),
    classFromName: f('il2cpp_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']), fieldType: f('il2cpp_field_get_type', 'pointer', ['pointer']),
    fieldFlags: f('il2cpp_field_get_flags', 'int', ['pointer']), param: f('il2cpp_method_get_param', 'pointer', ['pointer', 'uint32']),
    fieldFromName: f('il2cpp_class_get_field_from_name', 'pointer', ['pointer', 'pointer']), staticGet: f('il2cpp_field_static_get_value', 'void', ['pointer', 'pointer']),
    parent: f('il2cpp_class_get_parent', 'pointer', ['pointer'])
  };
  return IL;
}
function cstr(p) { try { return (!p || p.isNull()) ? '' : p.readCString(); } catch (e) { return ''; } }
function images() {
  var h = il(), sp = Memory.alloc(4), a = h.asms(h.domain(), sp), n = sp.readS32(), out = {};
  for (var i = 0; i < n; i++) { var im = h.asmImage(a.add(i * PS).readPointer()); out[cstr(h.imageName(im))] = im; }
  return out;
}
/* one pass per image for every wanted name (metadata reads only -- safe from the RPC thread) */
function findClasses(imageNames, names, out) {
  var h = il(), imgs = images(), want = {}, left = 0;
  names.forEach(function (n) { if (!out[n]) { want[n] = 1; left++; } });
  (imageNames || Object.keys(imgs)).forEach(function (iname) {
    var im = imgs[iname]; if (!im || !left) return;
    var c = h.classCount(im);
    for (var j = 0; j < c && left; j++) {
      var k = h.classAt(im, j); if (k.isNull()) continue;
      var nm = cstr(h.className(k)); if (want[nm] && !out[nm]) { out[nm] = k; left--; }
    }
  });
  return out;
}
var MC = {};
function methodOf(klass, name, argc) {
  if (!klass || klass.isNull()) return null;
  var key = klass + '|' + name + '|' + argc, m = MC[key];
  if (m === undefined) { m = il().methodByName(klass, Memory.allocUtf8String(name), argc); if (m.isNull()) m = null; MC[key] = m; }
  return m;
}
function method(obj, name, argc) { return methodOf(il().objClass(obj), name, argc); }
function fieldOff(klass, name) {
  var h = il(), it = Memory.alloc(PS); it.writePointer(NULL); var f;
  while ((f = h.fields(klass, it)) && !f.isNull()) { if (cstr(h.fieldName(f)) === name) return h.fieldOffset(f); }
  return -1;
}
/* il2cpp_runtime_invoke. UnityMain only. Managed exceptions come back through exc (-> null), never as a signal. */
function call(m, obj, args) {
  if (!m) return null;
  var a = NULL;
  if (args && args.length) { a = Memory.alloc(PS * args.length); for (var i = 0; i < args.length; i++) a.add(i * PS).writePointer(args[i]); }
  var exc = Memory.alloc(PS); exc.writePointer(NULL);
  var r = il().invoke(m, obj, a, exc);
  LASTOK = exc.readPointer().isNull();
  return LASTOK ? r : null;
}
var LASTOK = true;   /* did the last call() return without a managed exception */
function u8(r) { return r ? r.add(0x10).readU8() : -1; }
function s32(r) { return r ? r.add(0x10).readS32() : -1; }
function i32arg(v) { var p = Memory.alloc(4); p.writeS32(v); return p; }
function each(coll, fn) {   /* IEnumerable walk: GetEnumerator / MoveNext / get_Current */
  if (!coll || coll.isNull()) return;
  var en = call(method(coll, 'GetEnumerator', 0), coll, []); if (!en || en.isNull()) return;
  var k = il().objClass(en), self = il().isValueType(k) ? en.add(0x10) : en;
  var mn = methodOf(k, 'MoveNext', 0), cur = methodOf(k, 'get_Current', 0); if (!mn || !cur) return;
  for (var g = 0; g < 4000; g++) {
    var r = call(mn, self, []); if (!r || r.add(0x10).readU8() === 0) break;
    var o = call(cur, self, []); if (o && !o.isNull() && fn(o) === false) break;
  }
}
function encOf(o) { var r = call(method(o, 'get_EncounterId', 0), o, []); return r ? r.add(0x10).readU64().toString() : null; }

/* ---------------- state ---------------- */
var K = {}, M = {}, OFF = {}, PBT_VT = false;
var CFG = {catch: false, spin: false, tap: false, perfect: false, apples: false, appleSpecies: {}, openMs: 667, maxOpen: 6, thresh: 0.28,
           floors: {1: 5, 2: 5, 3: 5}, pinap: true, pinapFloor: 20, razz: true, razzFloor: 5, razzThresh: 0.45,
           legendary: {}, priority: {}};
var S = {ready: false, stale: 'first attach', nextLookup: 0, tries: 0, msvc: NULL, ib: NULL, avatar: NULL, ps: NULL};
/* STALE MAP (2026-09-24 22:27-22:46: 20 min of vis=0 while attached, 3 Pokemon the second it re-attached). The game
   can rebuild its map -- a new MapPlaceDirectoryService, a new map camera -- and the objects found at attach then read
   an empty, dead map forever. Two signals: a CameraFollowingGround instance we did not see right after READY, and
   python's quiet-time backstop (LASTVIS). Either one makes python re-attach, which re-runs the lookup (~1-2 s). */
var CAM = {seen: {}, until: 0}, LASTVIS = 0, QUIET = 45000;
var CAND = {msvc: [], ib: [], avatar: [], ps: []};   /* raw lookup hits: checked once on UnityMain, then discarded */
var E = {}, NE = 0, DONE = {}, DONEQ = [], PEND = [], NWQ = [], RESP = {}, REQQ = [], RES = {};
var ITEMC = {}, LASTWORK = 0, LASTWALK = 0, LASTOPEN = 0, LASTPOLL = 0, VIS = 0;
var HOLD = 0, HOLDWHY = '', FLEESTREAK = 0, LASTCATCHMS = 0;
var ST = {caught: 0, fled: 0, esc: 0, miss: 0, err: 0, manual: 0, opened: 0, thrown: 0, dust: 0, candy: 0, xp: 0,
          fedPinap: 0, fedRazz: 0, holds: 0, skip: {}, errs: 0};
var SPIN = {next: 0, total: 0, inRange: 0, cooling: 0, spins: 0, ok: 0, xp: 0, items: 0, fail: {}}, SPUN = {}, SPINNER_OFF = -1, SPINM = {};
var OUT = {log: [], done: [], tap: [], revealed: []};
var WALK_MS = 400, READY_MS = 150, BERRY_MS = 800, RETHROW_MS = 900;
var WILD = 'WildMapPokemon', DISK = 'TroyDiskMapPlacePokemon', INCENSE = 'IncenseMapPokemon';
var POLL_IDS = [1, 2, 3, 701, 705];
function log(s) { OUT.log.push(s); if (OUT.log.length > 200) OUT.log.shift(); }
function bump(o, k) { o[k] = (o[k] || 0) + 1; }

/* ---------------- game objects: found by the C lookup, on UnityMain, whenever needed ----------------
   First tick after attach, again if the map is rebuilt (a new map camera) or after a long quiet spell. Retried every
   2 s until the map is up. A lookup stops the world for ~0.2-0.5 s, so it is never run on a timer. */
function liveInstances(klass) {
  if (!klass || !FIND) return [];
  var MAX = 32, hits = Memory.alloc(16 + PS * MAX);
  hits.writePointer(hits.add(16)); hits.add(8).writeS32(MAX); hits.add(12).writeS32(0);
  var n = FIND(klass, hits), out = [];
  for (var i = 0; i < n; i++) out.push(hits.add(16 + PS * i).readPointer());
  return out;
}
function avatarPos(o) {
  var r = call(M.avatarLoc, o, []); if (!r) return null;
  var lat = r.add(0x10).readDouble(), lng = r.add(0x18).readDouble();
  return (isFinite(lat) && isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 && (lat !== 0 || lng !== 0)) ? {lat: lat, lng: lng} : null;
}
/* UnityMain, first pump tick: keep the instance that behaves. Several MapAvatars exist; the live one stands somewhere
   real (after a crash-restart the first hit sat at 0,0). Anything left over is discarded -- raw hits are never reused. */
function mapCount(o) { var c = call(M.allPokemon, o, []); if (!c || c.isNull()) return -1; var n = 0; each(c, function () { n++; return n < 50; }); return n; }
function bagBalls(o) { var t = 0, ok = false; for (var b = 1; b <= 3; b++) { var v = s32(call(M.itemCount, o, [i32arg(b)])); if (v >= 0) { ok = true; t += v; } } return ok ? t : -1; }
function lookup(now, why) {
  S.nextLookup = now + 2000;
  var t = Date.now();
  CAND.msvc = liveInstances(K.MapPlaceDirectoryService);
  CAND.ib = liveInstances(K.ItemBag);
  CAND.avatar = (K.MapAvatar && M.avatarLoc) ? liveInstances(K.MapAvatar) : [];
  CAND.ps = K.PlayerService ? liveInstances(K.PlayerService) : [];
  var ms = Date.now() - t;
  S.msvc = NULL; S.ib = NULL; S.avatar = NULL;
  resolveSingletons();
  if (S.ready) { S.stale = ''; CAM.seen = {}; CAM.until = Date.now() + 3000; LASTVIS = Date.now(); log('READY (' + why + '; lookup ' + ms + ' ms, found ' + [CAND0.m, CAND0.b, CAND0.a] + ')'); }
  else if (S.tries++ % 10 === 0) log('map not up yet (' + why + '; found ' + [CAND0.m, CAND0.b, CAND0.a] + '), retrying every 2 s');
}
var CAND0 = {m: 0, b: 0, a: 0};
function resolveSingletons() {
  var t = Date.now(), i, v, bestN = -1;
  CAND0 = {m: CAND.msvc.length, b: CAND.ib.length, a: CAND.avatar.length};
  /* a stale copy would still answer, so rank: the map service that holds Pokemon, the bag that holds balls */
  for (i = 0; i < CAND.msvc.length; i++) { v = mapCount(CAND.msvc[i]); if (v > bestN) { bestN = v; S.msvc = CAND.msvc[i]; } }
  /* STALE GRAPH (Pokemon Inventory session, 2026-09-29 ~05:00): the game can rebuild its services in-process; the OLD
     ItemBag keeps its pre-rebuild counts (more balls once any are thrown) and used to win 'most balls'. The live copy is
     the one whose InventoryCache.latestTimestamp is newest. Undecided (tie / unreadable) -> the old ranking, LOGGED. */
  var pl = pickLive(CAND.ib);
  if (!pl.pick.isNull()) { S.ib = pl.pick; if (CAND.ib.length > 1) log('GRAPH ItemBag: ' + pl.why); }
  else { bestN = -1; for (i = 0; i < CAND.ib.length; i++) { v = bagBalls(CAND.ib[i]); if (v > bestN) { bestN = v; S.ib = CAND.ib[i]; } }
         if (CAND.ib.length > 1) log('GRAPH ItemBag ' + pl.why + ' -- fallback: the bag with the most balls'); }
  var pp = pickLive(CAND.ps || []); S.ps = pp.pick; if ((CAND.ps || []).length > 1) log('GRAPH PlayerService: ' + pp.why);
  if (M.avatarLoc) for (i = 0; i < CAND.avatar.length && S.avatar.isNull(); i++) if (avatarPos(CAND.avatar[i])) S.avatar = CAND.avatar[i];
  CAND = {msvc: [], ib: [], avatar: [], ps: []};
  S.ready = !S.msvc.isNull() && !S.ib.isNull();
}

/* ---------------- live service graph (after an in-process rebuild the old objects answer with frozen data) ---------------- */
var GRAPHOFF = {};
function fieldOffWhere(klass, key, test) {   /* first instance field (class, then parents) passing test(name, typeName) */
  var ck = klass.toString() + '|' + key; if (GRAPHOFF[ck] !== undefined) return GRAPHOFF[ck];
  var h = il(), k = klass, d = 0, found = -1;
  while (found < 0 && k && !k.isNull() && d++ < 6) {
    var it = Memory.alloc(PS); it.writePointer(NULL); var f;
    while ((f = h.fields(k, it)) && !f.isNull()) {
      if (h.fieldFlags(f) & 0x10) continue;
      if (test(cstr(h.fieldName(f)), cstr(h.typeName(h.fieldType(f))))) { found = h.fieldOffset(f); break; }
    }
    k = h.parent(k);
  }
  GRAPHOFF[ck] = found; return found;
}
function invTsOf(o) {   /* newest server inventory update this object's graph has seen (ms), or -1 */
  try {
    var h = il(), io = fieldOffWhere(h.objClass(o), 'inv', function (n, t) { return /(^|\.)I?InventoryCache$/.test(t); });
    if (io < 0) return -1;
    var inv = o.add(io).readPointer(); if (inv.isNull()) return -1;
    var to = fieldOffWhere(h.objClass(inv), 'ts', function (n) { return n === 'latestTimestamp'; });
    return to < 0 ? -1 : inv.add(to).readS64().toNumber();
  } catch (e) { return -1; }
}
function pickLive(cands) {
  if (cands.length <= 1) return {pick: cands.length ? cands[0] : NULL, why: 'single'};
  var best = NULL, bt = -1, second = -1;
  for (var i = 0; i < cands.length; i++) { var t = invTsOf(cands[i]); if (t > bt) { second = bt; bt = t; best = cands[i]; } else if (t > second) second = t; }
  if (bt <= 0 || bt === second) return {pick: NULL, why: 'undecided (' + cands.length + ' copies, newest ts ' + bt + ' vs ' + second + ')'};
  return {pick: best, why: cands.length + ' copies, the newest inventory timestamp wins'};
}

/* ---------------- LIMITS: is the account being refused? (user 2026-09-29: "detect in game if I'm rate limited, I can't spin") ----
   Spins: the server's own FortSearch result. OutOfRange (2) at a stop you are standing at is the refusal ("Try again
   later"); 2+ in a row with no success = BLOCKED. ExceededDailyLimit (5) = the daily cap. Catches: fled on sure throws
   (FLEESTREAK). Account: GetPlayerOutProto Banned / Warn / WarnExpireMs / WasSuspended, read from every GetPlayer reply;
   the game is asked for one at READY and hourly (2026-09-29 20:39 the server said banned 0, warn 0, suspended 0). */
var LIM = {oorStreak: 0, oorSince: 0, lastOk: 0, lastSpin: 0, lastRes: -1, daily: 0, acct: null, acctT: 0, nextAcct: 0, sig: '', sigT: 0};
function spinBlocked(now) { return LIM.oorStreak >= 2; }
function limitState(now) {
  var spin = LIM.lastSpin === 0 ? 'unknown' : (LIM.daily && now - LIM.daily < 86400000 && LIM.lastRes === 5) ? 'daily-limit'
           : spinBlocked(now) ? 'BLOCKED' : 'ok';
  return {spin: spin, oorStreak: LIM.oorStreak, oorSince: LIM.oorSince, lastOk: LIM.lastOk, lastRes: LIM.lastRes,
          flee: FLEESTREAK, hold: HOLD > now ? HOLDWHY : '', acct: LIM.acct, acctT: LIM.acctT};
}
var GPOFF = null;
function onGetPlayerOut(s) {   /* any thread: memory reads only */
  if (!GPOFF) return;
  var ok = s.add(GPOFF.Success).readU8(), pl = s.add(GPOFF.Player).readPointer(); if (!ok && pl.isNull()) return;
  LIM.acct = {banned: s.add(GPOFF.Banned).readU8(), warn: s.add(GPOFF.Warn).readU8(), suspended: s.add(GPOFF.WasSuspended).readU8(),
              warnExpireMs: GPOFF.WarnExpireMs >= 0 ? s.add(GPOFF.WarnExpireMs).readS64().toNumber() : 0};
  LIM.acctT = Date.now();
}

/* ---------------- items ---------------- */
function pollCounts() {
  var ids = CFG.apples ? POLL_IDS.concat(APPLE_IDS) : POLL_IDS;
  for (var i = 0; i < ids.length; i++) { var v = s32(call(M.itemCount, S.ib, [i32arg(ids[i])])); if (v >= 0) ITEMC[ids[i]] = v; }
}
function have(item, floor) { var c = ITEMC[item]; return c !== undefined && c > floor; }
function ballOk(b) { var c = ITEMC[b]; if (c === undefined) return b === 1; return c > (CFG.floors[b] || 0); }
function pickBall(pr, prio) {
  var b;
  if (prio) { for (b = 3; b >= 1; b--) if (ballOk(b)) return b; return 0; }
  if (pr) {
    for (b = 1; b <= 3; b++) if (ballOk(b) && pr[b] !== undefined && pr[b] >= CFG.thresh) return b;
    var best = 0, bp = -1; for (b = 1; b <= 3; b++) if (ballOk(b) && pr[b] !== undefined && pr[b] > bp) { bp = pr[b]; best = b; }
    if (best) return best;
  }
  for (b = 1; b <= 3; b++) if (ballOk(b)) return b;
  return 0;
}
function berryFor(e) {
  var b = pickBall(e.probs, e.prio), p = (e.probs && b && e.probs[b] !== undefined) ? e.probs[b] : -1;
  if (CFG.razz && p >= 0 && p < CFG.razzThresh && have(701, CFG.razzFloor)) return 701;
  if (CFG.pinap && have(705, CFG.pinapFloor)) return 705;
  return 0;
}

/* ---------------- catching ---------------- */
var COOL = {};   /* enc -> time before which a not-final encounter is left alone */
var FINAL = {caught: 1, fled: 1, legendary: 1, maxthrows: 1, catcherr: 1};
function finish(enc, why) {
  if (E[enc]) { delete E[enc]; NE--; }
  if (why && why !== 'caught') bump(ST.skip, why);
  if (!FINAL[why] && why.indexOf('enc') !== 0) { COOL[enc] = Date.now() + 20000; return; }   /* gone / stale / noresp / noresult: retry later */
  if (!DONE[enc]) { DONE[enc] = 1; DONEQ.push(enc); OUT.done.push(enc); if (DONEQ.length > 6000) delete DONE[DONEQ.shift()]; }
}
var LIVE = {};   /* enc -> MapPokemon pointer. Valid ONLY in the tick that built it: every action reads it there. */
/* CENSUS: per class, from the last walk -- [on map, tracked, no encounter id, hidden flag, skipped type/legendary,
   already handled (caught/fled, or cooling down before a retry)].
   "Not catching X" becomes one look at the status line instead of a guess. */
var CENSUS = {}, NEVER = {RaidMapPokemon: 1, QuestMapPokemon: 1};   /* raid bosses / quest rewards: not map catches */
function nearMe(o, maxM) {   /* the Pokemon's own position vs the avatar (UnityMain); records the distance it saw */
  if (S.avatar.isNull()) return false;
  var me = avatarPos(S.avatar); if (!me) return false;
  var r = call(method(o, 'get_Location', 0), o, []); if (!r) { HIDNEAR.bad++; return false; }
  var lat = r.add(0x10).readDouble(), lng = r.add(0x18).readDouble();
  if (!isFinite(lat) || !isFinite(lng) || (lat === 0 && lng === 0) || Math.abs(lat) > 90) { HIDNEAR.bad++; return false; }
  var d = meters(me.lat, me.lng, lat, lng); if (d < HIDNEAR.min) HIDNEAR.min = d;
  return d <= maxM;
}
var HIDSP = {}, HIDLAST = {}, HIDNEAR = {min: 1e9, bad: 0}, HIDNEARLAST = null;   /* hidden Pokemon by species, last walk (diagnostic: are they apple Pokemon?) */
function walk(now) {
  LIVE = {}; HIDSP = {}; HIDNEAR = {min: 1e9, bad: 0};
  var coll = call(M.allPokemon, S.msvc, []); if (!coll) return;
  var h = il(), vis = 0, cen = {};
  each(coll, function (o) {
    var cls = cstr(h.className(h.objClass(o))), c = cen[cls] || (cen[cls] = [0, 0, 0, 0, 0, 0]);
    c[0]++;
    if (NEVER[cls]) { c[4]++; return; }
    var enc = encOf(o); if (!enc) { c[2]++; return; }
    if (DONE[enc] || (COOL[enc] && now < COOL[enc])) { c[5]++; return; }
    var e = E[enc]; if (e) { LIVE[enc] = o; e.seen = now; vis++; c[1]++; return; }
    /* Only a class that HAS the flag can say "not on the map". Incense and lure Pokemon have no get_VisibleOnMap;
       treating "no flag" as hidden skipped every one of them (945 wild, 0 incense, 0 lure caught since 19:30). */
    var vm = method(o, 'get_VisibleOnMap', 0);
    /* FRESH ONLY (2026-09-29 20:42): old reveals stay on the map hidden but are no longer catchable -- 70 of them queued at
       once gave 51 duds, a flee-hold and 0 catches in 50 s. Eligible: revealed < 3 min ago, or its encounter tappable is
       still live on the map (that refreshes the time every look). */
    var appleMon = !!AP.revealed[enc] && now - AP.revealed[enc] < 180000 && !AP.gaveUp[enc];
    if (vm && !appleMon && u8(call(vm, o, [])) !== 1) {
      /* HIDDEN APPLE POKEMON: the hidden ones were ALL apple species (Applin x25, Smoliv x8, Skiddo x4, Cottonee x3, Lechonk x1,
         20:13) -- reveals whose ids a restart had forgotten. A hidden Pokemon of an apple species within reach is one. */
      var hp = s32(call(method(o, 'get_PokemonId', 0), o, []));
      if (CFG.appleSpecies[hp]) nearMe(o, 80);   /* distance diagnostic only -- the species rule caught stale reveals */
      c[3]++; HIDSP[hp] = (HIDSP[hp] || 0) + 1; return;
    }
    var pid = s32(call(method(o, 'get_PokemonId', 0), o, []));
    if (CFG.legendary[pid]) { c[4]++; finish(enc, 'legendary'); return; }
    LIVE[enc] = o; vis++; c[1]++;
    e = E[enc] = {pid: pid, cls: cls, prio: !!CFG.priority[pid], st: 'new', seen: now, att: 0, opens: 0, berry: 0, apple: appleMon};
    if (appleMon) { ST.appleMon = (ST.appleMon || 0) + 1; log('APPLEMON tracking hidden #' + pid + ' enc=' + enc); }
    NE++;
    if (e.prio) PEND.unshift(enc); else PEND.push(enc);
  });
  VIS = vis; CENSUS = cen; HIDLAST = HIDSP; HIDNEARLAST = {m: HIDNEAR.min < 1e9 ? Math.round(HIDNEAR.min) : null, bad: HIDNEAR.bad}; if (vis > 0) LASTVIS = now;
  for (var k in E) { var x = E[k]; if (!LIVE[k] && now - x.seen > 6000 && x.st !== 'thrown') finish(k, 'gone'); }
}
function due(now) {   /* anything that needs a fresh pointer this tick? (cheap: JS only) */
  if (now < HOLD) return false;
  if (PEND.length && now - LASTOPEN >= CFG.openMs) return true;
  for (var k in E) { var e = E[k]; if ((e.st === 'ready' || e.st === 'fed') && now >= e.due) return true; }
  return false;
}
var OPENING = false, GAMEOPEN = {};   /* GAMEOPEN: MapPokemon pointer -> when the GAME itself sent its encounter request */
function openOne(enc, e, o, now) {
  OPENING = true;
  try { call(method(o, 'SendEncounterRequest', 0), o, []); } finally { OPENING = false; }
  LASTOPEN = now;
  if (!LASTOK) { log('OPENFAIL ' + e.cls + ' #' + e.pid + ' (retry in 20 s)'); finish(enc, 'openfail'); return; }
  e.st = 'open'; e.tOpen = now; e.opens++; ST.opened++;
  if (e.cls !== WILD) NWQ.push({enc: enc, t: now});
}
function feed(e, o, item) {
  call(M.useItem, S.ib, [i32arg(item), o]);
  e.berry = item; if (ITEMC[item] > 0) ITEMC[item]--;
  if (item === 705) ST.fedPinap++; else ST.fedRazz++;
}
function throwAt(e, enc, o, now) {
  var ball = pickBall(e.probs, e.prio);
  if (!ball) { e.st = 'ready'; e.due = now + 5000; bump(ST.skip, 'noballs'); return; }
  var pb = il().newObject(K.PokeballThrow);
  pb.add(0x10).writeS32(ball); pb.add(0x14).writeFloat(0.02 + Math.random() * 0.10);   /* reticle: Excellent */
  pb.add(0x18).writeU8(1); pb.add(0x19).writeU8(1); pb.add(0x1a).writeU8(0);           /* curveball, hit */
  call(method(o, 'TryCapture', 2), o, [PBT_VT ? pb.add(0x10) : pb, NULL]);
  if (!LASTOK) { log('THROWFAIL ' + e.cls + ' #' + e.pid + ' ball=' + ball + ' (retry in 20 s)'); finish(enc, 'throwfail'); return; }
  /* results come back in send order; record OUR throw now (the request hook does not see background throws) */
  var last = REQQ[REQQ.length - 1];
  if (!(last && last.enc === enc && now - last.t < 1000)) { REQQ.push({enc: enc, t: now}); if (REQQ.length > 50) REQQ.shift(); }
  e.st = 'thrown'; e.tThrow = now; e.att++; e.ball = ball; e.fedWith = e.berry; e.berry = 0; ST.thrown++;
  if (ITEMC[ball] > 0) ITEMC[ball]--;
}
function outcome(e, enc, r, now) {
  var p = (e.probs && e.probs[e.ball] !== undefined) ? e.probs[e.ball] : -1;
  var line = e.cls.replace('MapPokemon', '').replace('MapPlacePokemon', '') + ' #' + e.pid + ' ball=' + e.ball + ' p=' + (p < 0 ? '?' : p.toFixed(2)) +
             ' att=' + e.att + ' berry=' + (e.fedWith || 0) + ' ' + ((now - e.tOpen) / 1000).toFixed(1) + 's' + (e.apple ? ' [apple]' : '');
  if (r.st === 1) {
    ST.caught++; FLEESTREAK = 0; LASTCATCHMS = now - e.tOpen;
    ST.dust += r.dust; ST.candy += r.candy; ST.xp += r.xp;
    log('CATCH ' + line + ' dust=' + r.dust + ' candy=' + r.candy);
    finish(enc, 'caught');
  } else if (r.st === 3) {
    ST.fled++;
    if (!e.apple && (p >= 0.4 || p < 0)) FLEESTREAK++;   /* a stale apple reveal 'flees' as a server reject: not a soft-ban sign */
    log('FLED ' + line);
    if (FLEESTREAK >= 5) { HOLD = now + 45000; HOLDWHY = 'every throw is fleeing (soft ban?)'; FLEESTREAK = 4; ST.holds++; log('HOLD 45s: ' + HOLDWHY); }
    finish(enc, 'fled');
  } else if (r.st === 2 || r.st === 4) {
    if (r.st === 2) ST.esc++; else ST.miss++;
    if (e.att < (e.prio ? 60 : 12)) { e.st = 'ready'; e.due = now + RETHROW_MS; } else finish(enc, 'maxthrows');
  } else { ST.err++; log('CATCHERR ' + r.st + ' ' + line); finish(enc, 'catcherr'); }
}
function notInRange(e, st) { return (e.cls === WILD && st === 5) || (e.cls === DISK && st === 3); }
function bagFull(e, st) { return (e.cls === WILD && st === 7) || (e.cls === DISK && st === 5) || (e.cls === INCENSE && st === 3); }
function catchTick(now) {
  var fresh = false;
  if (now - LASTWALK >= WALK_MS || due(now)) { LASTWALK = now; walk(now); fresh = true; }
  var holding = now < HOLD || !fresh, enc, e, o, n = 0;
  for (enc in E) if (E[enc].st === 'open') n++;
  /* APPLE EXCLUSIVITY: some throws at an apple Pokemon send no request (a dud); with other throws in flight the FIFO then
     hands the next real result to the dud (FLED p=1.00, NORESULT on others). So an apple throw goes alone, and nothing
     else is thrown while it is in the air -- the next result is then unambiguous. */
  var inflight = 0, appleInflight = false;
  for (enc in E) if (E[enc].st === 'thrown') { inflight++; if (E[enc].apple) appleInflight = true; }
  var anyBall = ballOk(1) || ballOk(2) || ballOk(3);
  if (!anyBall && fresh && now >= HOLD && PEND.length) { HOLD = now + 30000; HOLDWHY = 'out of balls (at the floors)'; ST.holds++; log('HOLD 30s: ' + HOLDWHY); holding = true; }
  for (var tries = PEND.length; tries > 0 && !holding && now - LASTOPEN >= CFG.openMs && n < CFG.maxOpen; tries--) {
    enc = PEND.shift(); e = E[enc]; if (!e || e.st !== 'new') continue;
    o = LIVE[enc];
    if ((e.retryAt && now < e.retryAt) || !o) { PEND.push(enc); continue; }
    if (e.apple) {
      /* APPLE POKEMON (2026-09-29): the game opens a revealed Pokemon's encounter by itself ~3 s after the reveal. A throw
         before that is a dud (49 in 7 min). Wait for the game's own SendEncounterRequest on this object, then throw;
         if the game has not opened it within 8 s of our first sighting, open it ourselves (the old path). */
      if (!e.firstSeen) e.firstSeen = now;
      var go = GAMEOPEN[o.toString()];
      if (go) { e.st = 'ready'; e.tOpen = now; e.due = Math.max(now, go + 300); e.probs = AP.probs[enc] || null; e.gameOpened = 1; ST.appleGameOpen = (ST.appleGameOpen || 0) + 1; continue; }
      if (now - e.firstSeen < 8000) { PEND.push(enc); continue; }
      /* never opened by the game in 8 s = a stale reveal: 27 duds + 4 flees in 4 min came only from these, 0 from fresh ones */
      AP.gaveUp[enc] = 1; delete AP.revealed[enc]; ST.appleStale = (ST.appleStale || 0) + 1; finish(enc, 'applestale'); continue;
    }
    openOne(enc, e, o, now); n++;
  }
  for (enc in E) {
    e = E[enc];
    if (e.st === 'open') {
      var r = RESP[enc];
      if (r && r.t < e.tOpen - 100) { delete RESP[enc]; r = null; }   /* an older answer: your own manual encounter */
      if (r) {
        delete RESP[enc];
        if (r.st === 1) { e.probs = r.p; e.st = 'ready'; e.due = now + READY_MS; }
        else if (notInRange(e, r.st) && e.opens < 3) { e.st = 'new'; e.retryAt = now + 4000; PEND.push(enc); }
        else if (bagFull(e, r.st)) { HOLD = now + 60000; HOLDWHY = 'Pokemon storage is full'; ST.holds++; log('HOLD 60s: ' + HOLDWHY); e.st = 'new'; e.retryAt = now + 60000; PEND.push(enc); }
        else if (notInRange(e, r.st) || r.st === 0) { log('ENCRETRY ' + e.cls + ' #' + e.pid + ' status=' + r.st + ' (retry in 20 s)'); finish(enc, r.st ? 'notinrange' : 'srverror'); }
        else { log('ENCFAIL ' + e.cls + ' #' + e.pid + ' status=' + r.st); finish(enc, 'enc' + r.st); }
      } else if (e.apple && now - e.tOpen >= 1500) {   /* 700 ms was too early: throws went out before the encounter existed */
        /* APPLE POKEMON: the game answers its encounter from the tappable reply it already holds -- SendEncounterRequest
           sends nothing (traced 2026-09-29: bfni -> SendEncounterRequest, no EncounterProto), so no reply will come.
           Throw with the reveal's catch probabilities. (Waiting gave 26 NORESP in 3 min.) */
        e.probs = AP.probs[enc] || null; e.st = 'ready'; e.due = now + READY_MS;
      } else if (now - e.tOpen > 8000) {
        if (e.opens < 2) { e.st = 'new'; PEND.push(enc); } else { log('NORESP ' + e.cls + ' #' + e.pid + ' (retry in 20 s)'); finish(enc, 'noresp'); }
      }
    } else if (e.st === 'thrown') {
      var res = RES[enc];
      if (res) { delete RES[enc]; outcome(e, enc, res, now); }
      else if (e.apple && now - e.tThrow > 3000) {   /* a dud: nothing was sent. Drop its queue entry, try again in 0.8 s */
        for (var qd = REQQ.length - 1; qd >= 0; qd--) if (REQQ[qd].enc === enc) REQQ.splice(qd, 1);
        e.duds = (e.duds || 0) + 1; ST.appleDuds = (ST.appleDuds || 0) + 1; if (ITEMC[e.ball] >= 0) ITEMC[e.ball]++;
        if (e.duds >= 5) { log('APPLEGONE ' + e.cls + ' #' + e.pid + ' [apple] 5 duds -- no longer catchable, dropped'); AP.gaveUp[enc] = 1; delete AP.revealed[enc]; finish(enc, 'appledud'); }
        else { e.st = 'ready'; e.due = now + 800; }
      }
      else if (now - e.tThrow > 10000) { log('NORESULT ' + e.cls + ' #' + e.pid + ' ball=' + e.ball + (e.apple ? ' [apple]' : '') + ' (retry in 20 s)');
        for (var qi = REQQ.length - 1; qi >= 0; qi--) if (REQQ[qi].enc === enc) REQQ.splice(qi, 1);
        finish(enc, 'noresult'); }
    } else if (!holding && (e.st === 'ready' || e.st === 'fed') && now >= e.due) {
      if (appleInflight || (e.apple && inflight > 0)) continue;   /* see APPLE EXCLUSIVITY */
      o = LIVE[enc]; if (!o) continue;   /* not in this tick's list: try again next tick (walk() retires it after 6s) */
      if (e.st === 'ready') { var b = berryFor(e); if (b) { feed(e, o, b); e.st = 'fed'; e.due = now + BERRY_MS; continue; } }
      throwAt(e, enc, o, now);
    }
  }
  for (var k in RESP) if (now - RESP[k].t > 20000) delete RESP[k];
}

/* ---------------- response hooks (other threads: memory reads only, never a game call) ---------------- */
function readProbs(cp) {
  try {
    if (!cp || cp.isNull()) return null;
    var bR = cp.add(0x10).readPointer(), pR = cp.add(0x18).readPointer(); if (bR.isNull() || pR.isNull()) return null;
    var bA = bR.add(0x10).readPointer(), bC = bR.add(0x18).readS32(), pA = pR.add(0x10).readPointer(), pC = pR.add(0x18).readS32();
    if (bC !== pC || bC <= 0 || bC > 8) return null;
    var m = {};
    for (var i = 0; i < bC; i++) { var b = bA.add(0x20 + i * 4).readS32(), p = pA.add(0x20 + i * 4).readFloat(); if (b < 1 || b > 10 || !(p >= 0 && p <= 1)) return null; m[b] = p; }
    return m;
  } catch (e) { return null; }
}
function repInts(rf) {   /* RepeatedField<int>: array @0x10, count @0x18, data @+0x20 */
  try { if (!rf || rf.isNull()) return 0; var a = rf.add(0x10).readPointer(), c = rf.add(0x18).readS32(), t = 0;
        if (a.isNull() || c < 0 || c > 64) return 0; for (var i = 0; i < c; i++) t += a.add(0x20 + i * 4).readS32(); return t; } catch (e) { return 0; }
}
function lootTotal(lp) {
  try { if (!lp || lp.isNull()) return 0; var rf = lp.add(0x10).readPointer(); if (!rf || rf.isNull()) return 0;
        var cnt = rf.add(0x18).readS32(), arr = rf.add(0x10).readPointer(); if (cnt < 0 || cnt > 300 || arr.isNull()) return 0;
        var t = 0; for (var i = 0; i < cnt; i++) { var it = arr.add(0x20 + i * 8).readPointer(); if (!it.isNull()) { var c = it.add(0x10).readS32(); if (c > 0 && c < 10000) t += c; } } return t; } catch (e) { return 0; }
}
var LASTNW = {t: 0, sig: ''}, LASTREQ = {enc: '', t: 0}, LASTRES = {sig: '', t: 0};
function onEncounterOut(s) {   /* EncounterOutProto: status @0x1c, WildPokemon @0x10 -> encounterId @0x10, probs @0x20 */
  var pk = s.add(0x10).readPointer(); if (pk.isNull()) return;
  var ev = pk.add(0x10).readU64(); if (ev.compare(uint64(0)) === 0) return;
  RESP[ev.toString()] = {st: s.add(0x1c).readS32(), p: readProbs(s.add(0x20).readPointer()), t: Date.now()};
  /* (a non-wild class answered through the standard proto: its queued entry is dropped at the next non-wild reply) */
}
/* Non-wild replies (incense, lure, DayNight / PowerUp / NaturalArt POIs, PokeStop incidents, daily, station...) carry no
   encounter id. Match by SPECIES to the oldest pending open, then by age. One unanswered type used to sit at the head
   of a single FIFO and shift every later reply onto the wrong Pokemon. Offsets come from each proto's own field names. */
var NWOFF = {};   /* proto class name -> {res, pk, cp} */
function onOtherEncounterOut(s, pn) {
  var o = NWOFF[pn] || {res: 0x10, pk: -1, cp: 0x20}, now = Date.now();
  var st = s.add(o.res).readS32(), p = readProbs(s.add(o.cp).readPointer()), sp = -1;
  if (o.pk >= 0 && OFF.pkId >= 0) { try { var pk = s.add(o.pk).readPointer(); if (!pk.isNull()) sp = pk.add(OFF.pkId).readS32(); } catch (e) {} }
  var sig = pn + '|' + st + '|' + sp + '|' + JSON.stringify(p);
  if (sig === LASTNW.sig && now - LASTNW.t < 300) return;   /* same reply through a second MergeFrom overload */
  LASTNW = {sig: sig, t: now};
  var i, best = -1;
  for (i = NWQ.length - 1; i >= 0; i--) { var q = NWQ[i], e = E[q.enc]; if (now - q.t > 10000 || !e || e.st !== 'open' || RESP[q.enc]) NWQ.splice(i, 1); }
  for (i = 0; i < NWQ.length && best < 0; i++) if (sp > 0 && E[NWQ[i].enc].pid === sp) best = i;
  if (best < 0 && NWQ.length) best = 0;
  if (best >= 0) { RESP[NWQ[best].enc] = {st: st, p: p, t: now}; NWQ.splice(best, 1); }
}
function onCatchReq(s) {   /* CatchPokemonProto: encounterId @0x10 (ours and manual throws, in send order) */
  var enc = s.add(0x10).readU64().toString(), now = Date.now();
  if (enc === LASTREQ.enc && now - LASTREQ.t < 500) return;   /* WriteTo + _InternalSerialize of the same request */
  LASTREQ = {enc: enc, t: now};
  var mine = E[enc] && (E[enc].st === 'thrown' || E[enc].st === 'fed' || E[enc].st === 'ready');
  if (!mine) { REQQ.push({enc: enc, t: now}); if (REQQ.length > 50) REQQ.shift(); }   /* a manual throw */
  if (CFG.perfect) {   /* Perfect Throw for MANUAL throws: the server scores the throw from these fields */
    s.add(0x20).writeDouble(1.90 + Math.random() * 0.08);   /* normalized_reticle_size -> Excellent */
    s.add(0x30).writeU8(1);                                  /* hit_pokemon */
    s.add(0x38).writeDouble(1.0);                            /* spin_modifier -> curveball */
    s.add(0x40).writeDouble(1.0);                            /* normalized_hit_position */
  }
}
function onCatchOut(s) {
  var st = s.add(OFF.cStatus).readS32(), cid = s.add(OFF.cCaptured).readU64().toString(), now = Date.now();
  var aw = OFF.cAward >= 0 ? s.add(OFF.cAward).readPointer() : NULL;
  var r = {st: st, dust: 0, candy: 0, xp: 0};
  if (!aw.isNull()) {
    if (OFF.aDust >= 0) r.dust = repInts(aw.add(OFF.aDust).readPointer());
    if (OFF.aCandy >= 0) r.candy = repInts(aw.add(OFF.aCandy).readPointer());
    if (OFF.aXp >= 0) r.xp = repInts(aw.add(OFF.aXp).readPointer());
  }
  var sig = st + '|' + cid + '|' + r.dust + '|' + r.xp;
  if (st === 0 && cid === '0' && r.xp === 0) return;            /* empty object (second MergeFrom pass) */
  if (sig === LASTRES.sig && now - LASTRES.t < 300) return;
  LASTRES = {sig: sig, t: now};
  while (REQQ.length && now - REQQ[0].t > 15000) REQQ.shift();
  /* skip our own entries that are already finished: a throw that sent no request (an apple Pokemon thrown too early) left
     its entry at the head, stole the NEXT result, and that throw went NORESULT (1 in 77 min -> 8 in 3 min, 2026-09-29) */
  while (REQQ.length && E[REQQ[0].enc] === undefined && DONE[REQQ[0].enc]) REQQ.shift();
  while (REQQ.length && E[REQQ[0].enc] && E[REQQ[0].enc].st !== 'thrown') REQQ.shift();
  var q = REQQ.shift(); if (!q) return;
  if (E[q.enc] && E[q.enc].st === 'thrown') RES[q.enc] = r;
  else { ST.manual++; if (st === 1) { ST.dust += r.dust; ST.candy += r.candy; ST.xp += r.xp; } }
}
function onSpinOut(s) {
  var res = s.add(0x10).readS32(), xp = s.add(0x30).readS32(), now = Date.now();
  var sig = res + '|' + s.add(0x70).readPointer();
  if (res !== 1 && !(sig === LIM.sig && now - LIM.sigT < 400)) {   /* a refusal: count it once (two parse passes) */
    LIM.sig = sig; LIM.sigT = now; LIM.lastSpin = now; LIM.lastRes = res;
    if (res === 2) { if (!LIM.oorStreak) LIM.oorSince = now; LIM.oorStreak++; if (LIM.oorStreak === 2) log('LIMIT spins BLOCKED: the server answered OutOfRange twice in a row at stops in range'); }
    if (res === 5) { LIM.daily = now; log('LIMIT spins: daily limit reached (ExceededDailyLimit)'); }
  }
  var items = lootTotal(s.add(0x50).readPointer()) + lootTotal(s.add(0x58).readPointer());
  if (res === 1 && xp <= 0 && items <= 0) return;   /* empty second pass */
  if (res === 1) { SPIN.ok++; if (xp > 0 && xp < 100000) SPIN.xp += xp; SPIN.items += items;
    if (LIM.oorStreak >= 2) log('LIMIT spins OK again after ' + LIM.oorStreak + ' refusals'); LIM.oorStreak = 0; LIM.lastOk = now; LIM.lastSpin = now; LIM.lastRes = 1; }
  else bump(SPIN.fail, 'res' + res);
}
function hookAll(klass, names, argc, onEnter, onLeave) {
  var h = il(), it = Memory.alloc(PS); it.writePointer(NULL); var m, n = 0;
  while ((m = h.methods(klass, it)) && !m.isNull()) {
    if (names.indexOf(cstr(h.methodName(m))) < 0) continue;
    if (argc >= 0 && h.paramCount(m) !== argc) continue;
    var code = m.readPointer(); if (code.isNull()) continue;
    Interceptor.attach(code, onLeave ? {
      onEnter: function (a) { this.s = a[0]; },
      onLeave: function () { try { if (this.s && !this.s.isNull()) onLeave(this.s); } catch (e) { ST.errs++; } }
    } : {onEnter: function (a) { try { if (!a[0].isNull()) onEnter(a[0]); } catch (e) { ST.errs++; } }});
    n++;
  }
  return n;
}

/* ---------------- spinning ---------------- */
function fortId(ps) {
  var fd = call(method(ps, 'get_FortData', 0), ps, []); if (!fd || fd.isNull()) return null;
  var idp = fd.add(0x10).readPointer(); if (idp.isNull()) return null;
  var len = idp.add(0x10).readS32(); return (len > 0 && len < 200) ? idp.add(0x14).readUtf16String(len) : null;
}
function spinMethodOf(spinner) {   /* resolved by SIGNATURE: obfuscated names change every app update */
  var h = il(), k = h.objClass(spinner), key = k.toString(); if (SPINM[key] !== undefined) return SPINM[key];
  var found = null, it = Memory.alloc(PS); it.writePointer(NULL); var m;
  while ((m = h.methods(k, it)) && !m.isNull()) { if (h.paramCount(m) !== 0) continue; if (cstr(h.typeName(h.retType(m))).indexOf('FortSearchOutProto') >= 0) { found = m; break; } }
  SPINM[key] = found; return found;
}
function spinOne(ps) {
  var inter = call(method(ps, 'StartInteractiveMode', 0), ps, []); if (!inter || inter.isNull()) return 'noInter';
  var done = function (r) { call(method(ps, 'CompleteInteractiveMode', 0), ps, []); return r; };
  if (SPINNER_OFF < 0) { SPINNER_OFF = fieldOff(il().objClass(inter), 'ItemSpinner'); if (SPINNER_OFF < 0) return done('noField'); }
  var spinner = inter.add(SPINNER_OFF).readPointer(); if (spinner.isNull()) return done('noSpinner');
  var sm = spinMethodOf(spinner); if (!sm) return done('noSpinMethod');
  call(sm, spinner, []); SPIN.spins++;
  return done('spun');
}
function spinTick(now) {
  if (spinBlocked(now) && now - LIM.lastSpin < 600000) { SPIN.next = now + 60000; return; }   /* blocked: probe once per 10 min */
  var coll = call(M.activeStops, S.msvc, []);
  var total = 0, inr = 0, cool = 0, did = false;
  each(coll, function (ps) {
    total++;
    if (u8(call(method(ps, 'get_IsPlayerInRange', 0), ps, [])) !== 1) return;
    inr++;
    if (u8(call(method(ps, 'get_IsCoolingDown', 0), ps, [])) === 1) { cool++; return; }
    if (did || u8(call(method(ps, 'get_IsClosed', 0), ps, [])) === 1) return;
    var fid = fortId(ps); if (fid && SPUN[fid] && now - SPUN[fid] < 330000) return;
    var r = spinOne(ps); if (fid) SPUN[fid] = now; did = true;
    if (r !== 'spun') bump(SPIN.fail, r);
  });
  SPIN.total = total; SPIN.inRange = inr; SPIN.cooling = cool;
  SPIN.next = now + (inr > cool ? 2500 : 6000);
}

/* ---------------- double-tap to move (GPS Joystick does the move; python sends the intent) ---------------- */
var TAP = {t: 0, x: 0, y: 0, cool: 0}, MBD = null, MPOS = null, CAMMAIN = null;
function screenToLatLng(x, y) {
  if (S.avatar.isNull() || !K.Camera) return null;
  if (!CAMMAIN) CAMMAIN = methodOf(K.Camera, 'get_main', 0);
  var cam = call(CAMMAIN, NULL, []); if (!cam || cam.isNull()) return null;
  var v = Memory.alloc(12); v.writeFloat(x); v.add(4).writeFloat(y); v.add(8).writeFloat(0);
  var ray = call(method(cam, 'ScreenPointToRay', 1), cam, [v]); if (!ray) return null;
  var oy = ray.add(0x14).readFloat(), dy = ray.add(0x20).readFloat();
  if (!isFinite(dy) || Math.abs(dy) < 1e-6) return null;
  var t = -oy / dy; if (!isFinite(t) || t < 0 || t > 100000) return null;
  var w = Memory.alloc(12); w.writeFloat(ray.add(0x10).readFloat() + ray.add(0x1c).readFloat() * t); w.add(4).writeFloat(0); w.add(8).writeFloat(ray.add(0x18).readFloat() + ray.add(0x24).readFloat() * t);
  var rnd = S.avatar.add(0x130).readPointer(); if (rnd.isNull()) return null;
  var r = call(method(rnd, 'GetWorldLocation', 1), rnd, [w]); if (!r) return null;
  var lat = r.add(0x10).readDouble(), lng = r.add(0x18).readDouble();
  return (isFinite(lat) && isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180) ? {lat: lat, lng: lng} : null;
}
function tapTick() {
  if (!K.Input) return;
  if (!MBD) { MBD = methodOf(K.Input, 'GetMouseButtonDown', 1); MPOS = methodOf(K.Input, 'get_mousePosition', 0); if (!MBD || !MPOS) return; }
  var now = Date.now(); if (now < TAP.cool) return;
  if (u8(call(MBD, NULL, [i32arg(0)])) !== 1) return;
  var mp = call(MPOS, NULL, []); if (!mp) return;
  var x = mp.add(0x10).readFloat(), y = mp.add(0x14).readFloat();
  if (now - TAP.t <= 450 && Math.abs(x - TAP.x) <= 90 && Math.abs(y - TAP.y) <= 90) {
    var ll = screenToLatLng(x, y);
    OUT.tap.push(ll ? 'MOVED ' + ll.lat.toFixed(6) + ' ' + ll.lng.toFixed(6) : 'tap did not convert to a location');
    TAP.cool = now + 800; TAP.t = 0;
  } else { TAP.t = now; TAP.x = x; TAP.y = y; }
}

/* ---------------- apples: event map tappables (TAPPABLE_TYPE_MAPLE around Mossy-lured stops, 2026-09-29) ----------
   Tapped the way a finger does: the controller's own TapGesture handler -- void ?(System.Object, System.EventArgs),
   found by SIGNATURE (its name is obfuscated) -- called on UnityMain with (controller.tapGesture, EventArgs.Empty).
   Tapped() is only a bool query: 5 calls sent 0 requests. The game keeps EXPIRED controllers pooled, so DespawnTimeMs
   is checked on every look. Controllers are learned as the game touches them (Initialize / Refresh / getters), i.e. a
   pointer from ANOTHER tick: each one is re-validated -- klass, despawn, type, distance -- in the tick that taps it.
   A tap gives an apple item or reveals a Pokemon; revealed Pokemon become wild/lure spawns that catchTick() catches.
   Encounter tappables (IsEncounter) are never tapped here. The reply arrives mostly through an obfuscated parse method
   (36 of 38 on 2026-09-29, 'puj'), so every 1-argument parse method is hooked, not just MergeFrom. */
var AP = {ctl: NULL, f: null, gos: [], handler: null, evF: NULL, ev: NULL, int32: NULL, cand: {}, dead: {}, tapped: {}, seen: {},
          last: 0, lastTap: 0, types: {TAPPABLE_TYPE_MAPLE: 1}, names: {}, inst: null,
          /* SPEED + RANGE (user 2026-09-29: "not picking up the apples as fast as the pokemon"; 697 sightings were skipped as
             >60 m): nearest first, a tap every 0.5 s, and a range LEARNED from the server -- start 80 m, +10 m after a success
             near the edge (cap 150 m = the game's visibleRadiusMeters), shrink below any ERROR_NOT_IN_RANGE (status 4). */
          maxDist: 80, gap: 500, q: [], retry: {}, okD: 0, failD: 9999,
          /* APPLE POKEMON (user: "sometimes an apple is a pokemon you gotta catch"): a reveal leaves the Pokemon on the map as a
             HIDDEN wild (VisibleOnMap 0) that walk() used to skip -- census 'Wild 8/0 hidden=8'. Every revealed encounter id
             (reply to our tap, or an IsEncounter tappable seen on the map) goes here and walk() catches it. */
          revealed: {}, probs: {}, capOff: -1, gaveUp: {},   /* probs: enc -> catch probabilities from the reveal (TappableEncounterProto) */
          rf: {}, loot: -1, liCount: -1, liObj: -1, encPk: -1, pkCp: -1, lastSig: '', lastT: 0,
          st: {taps: 0, replies: 0, items: {}, mons: 0, fails: {}, live: 0, expired: 0}};
var APPLE_IDS = [1151, 1152, 1155];   /* Sweet / Tart / Syrupy Apple (MAPLE_A/B/C); re-read from the live Item enum */
function clsByName(ns, name) {
  var h = il(), imgs = images(), a = Memory.allocUtf8String(ns), b = Memory.allocUtf8String(name);
  for (var k in imgs) { var c = h.classFromName(imgs[k], a, b); if (!c.isNull()) return c; }
  return NULL;
}
function fieldsAll(klass) {   /* own instance fields: name -> {off, tn} */
  var h = il(), it = Memory.alloc(PS), f, out = {}; it.writePointer(NULL);
  while ((f = h.fields(klass, it)) && !f.isNull()) {
    if (h.fieldFlags(f) & 0x10) continue;
    out[cstr(h.fieldName(f))] = {off: h.fieldOffset(f), tn: cstr(h.typeName(h.fieldType(f)))};
  }
  return out;
}
function apNote(p) {   /* hook callback (UnityMain): remember a controller the game just touched */
  var k = p.toString();
  if (AP.dead[k]) { try { if (p.add(AP.f.enc).readU64().toString() === AP.dead[k]) return; } catch (e) { return; } delete AP.dead[k]; }   /* the pool reused it */
  if (!AP.cand[k]) AP.cand[k] = 1;
}
function apRead(o) {   /* same-tick snapshot, or null when it is no longer a DynamicTappableController */
  if (o.readPointer().toString() !== AP.ctl.toString()) return null;
  var tp = o.add(AP.f.type).readPointer(), type = null;
  if (!tp.isNull()) { var n = tp.add(0x10).readS32(); if (n > 0 && n < 64) type = tp.add(0x14).readUtf16String(n); }
  var r = {enc: o.add(AP.f.enc).readU64().toString(), type: type, isEnc: o.add(AP.f.isEnc).readU8() !== 0,
           despawn: o.add(AP.f.despawn).readS64().toNumber(), lat: o.add(AP.f.loc).readDouble(), lng: o.add(AP.f.loc + 8).readDouble(), ready: true};
  for (var i = 0; i < AP.gos.length; i++) if (o.add(AP.gos[i]).readPointer().isNull()) { r.ready = false; break; }
  return r;
}
function meters(a1, o1, a2, o2) {
  var R = 6371008.8, p1 = a1 * Math.PI / 180, p2 = a2 * Math.PI / 180, dl = (o2 - o1) * Math.PI / 180;
  return 2 * R * Math.asin(Math.sqrt(Math.pow(Math.sin((p2 - p1) / 2), 2) + Math.cos(p1) * Math.cos(p2) * Math.pow(Math.sin(dl / 2), 2)));
}
function appleTick(now) {   /* UnityMain, from pump() */
  var me = S.avatar.isNull() ? null : avatarPos(S.avatar), keys = Object.keys(AP.cand), best = null;
  for (var i = 0; i < keys.length; i++) {
    var k = keys[i], o = ptr(k), s = null;
    try { s = apRead(o); } catch (e) { s = null; }
    if (!s) { delete AP.cand[k]; continue; }
    if (s.despawn && s.despawn < now) { delete AP.cand[k]; AP.dead[k] = s.enc; AP.st.expired++; continue; }
    var key = s.enc + ':' + s.isEnc;
    if (s.isEnc && !AP.gaveUp[s.enc]) { if (!AP.revealed[s.enc]) OUT.revealed.push(s.enc); AP.revealed[s.enc] = now; }   /* live encounter tappable: keep it fresh */
    if (AP.types[s.type] && !s.isEnc && !AP.seen[key]) { AP.seen[key] = 1; AP.st.live++; }
    if (AP.tapped[key] || s.isEnc || !AP.types[s.type] || !s.ready || !me) continue;
    if (AP.retry[key] && now < AP.retry[key]) continue;
    var d = meters(me.lat, me.lng, s.lat, s.lng);
    if (!(d <= AP.maxDist)) continue;
    if (!best || d < best.d) best = {o: o, key: key, d: d, enc: s.enc};
  }
  if (best && now - AP.lastTap >= AP.gap) {   /* the nearest apple first */
    if (AP.ev.isNull() && !AP.evF.isNull()) { var box = Memory.alloc(PS); box.writePointer(NULL); il().staticGet(AP.evF, box); AP.ev = box.readPointer(); }
    AP.lastTap = now; AP.tapped[best.key] = now; delete AP.retry[best.key];
    call(AP.handler, best.o, [best.o.add(AP.f.gesture).readPointer(), AP.ev]);
    AP.st.taps++;
    if (!LASTOK) bump(AP.st.fails, 'tapexc');
    else { AP.q.push({key: best.key, t: now, d: Math.round(best.d), enc: best.enc}); if (AP.q.length > 30) AP.q.shift(); }
  }
  if (Object.keys(AP.tapped).length > 3000) AP.tapped = {};
  if (Object.keys(AP.dead).length > 3000) AP.dead = {};
  if (Object.keys(AP.seen).length > 3000) AP.seen = {};
  if (Object.keys(AP.retry).length > 3000) AP.retry = {};
  for (var gk in GAMEOPEN) if (now - GAMEOPEN[gk] > 60000) delete GAMEOPEN[gk];
  for (var rk in AP.revealed) if (now - AP.revealed[rk] > 600000) { delete AP.revealed[rk]; delete AP.probs[rk]; }
  if (Object.keys(AP.gaveUp).length > 3000) AP.gaveUp = {};
}
function onTappableOut(s) {   /* ProcessTappableOutProto, any thread: memory reads only */
  var st = s.add(AP.rf.Status).readS32(), now = Date.now(), items = [], sp = -1, cp = -1;
  var rw = s.add(AP.rf.Reward).readPointer();
  if (!rw.isNull() && AP.loot >= 0) {
    var arr = rw.add(0x10).readPointer(), n = rw.add(0x18).readS32();
    for (var i = 0; i < n && i < 10 && !arr.isNull(); i++) {
      var lp = arr.add(0x20 + i * PS).readPointer(); if (lp.isNull()) continue;
      var li = lp.add(AP.loot).readPointer(); if (li.isNull()) continue;
      var la = li.add(0x10).readPointer(), ln = li.add(0x18).readS32();
      for (var j = 0; j < ln && j < 10 && !la.isNull(); j++) {
        var it = la.add(0x20 + j * PS).readPointer(); if (it.isNull()) continue;
        var cnt = AP.liCount >= 0 ? it.add(AP.liCount).readS32() : 1, ob = AP.liObj >= 0 ? it.add(AP.liObj).readPointer() : NULL, id = -1;
        if (!ob.isNull() && !AP.int32.isNull() && ob.readPointer().toString() === AP.int32.toString()) id = ob.add(0x10).readS32();
        items.push([id, cnt]);
      }
    }
  }
  var en = s.add(AP.rf.Encounter).readPointer();
  if (!en.isNull() && AP.encPk >= 0) {
    var pk = en.add(AP.encPk).readPointer();
    if (!pk.isNull()) { if (OFF.pkId >= 0) sp = pk.add(OFF.pkId).readS32(); if (AP.pkCp >= 0) cp = pk.add(AP.pkCp).readS32(); }
    if (AP.capOff >= 0) var probs = readProbs(en.add(AP.capOff).readPointer());
  }
  if (st === 0 && !items.length && sp < 0) return;   /* an empty pass (the same reply goes through two parse methods) */
  var sig = st + '|' + JSON.stringify(items) + '|' + sp + '|' + cp;
  if (sig === AP.lastSig && now - AP.lastT < 400) return;
  AP.lastSig = sig; AP.lastT = now; AP.st.replies++;
  while (AP.q.length && now - AP.q[0].t > 8000) AP.q.shift();
  var q = AP.q.shift();   /* replies come back in send order */
  if (q && st === 1 && q.d > AP.okD) AP.okD = q.d;
  if (q && st === 1 && q.d >= AP.maxDist - 10 && AP.maxDist < Math.min(150, AP.failD - 5)) AP.maxDist = Math.min(150, AP.failD - 5, AP.maxDist + 10);
  if (q && st === 4) { AP.failD = Math.min(AP.failD, q.d); AP.maxDist = Math.max(30, Math.min(AP.maxDist, q.d - 5)); delete AP.tapped[q.key]; AP.retry[q.key] = now + 3000; }
  if (st !== 1) { bump(AP.st.fails, 'status' + st); log('APPLEFAIL status=' + st + (st === 4 ? ' (not in range at ' + (q ? q.d : '?') + ' m -> range ' + AP.maxDist + ' m, retry when closer)' : st === 2 ? ' (not found)' : '')); return; }
  items.forEach(function (x) { var nm = AP.names[x[0]] || ('item ' + x[0]); AP.st.items[nm] = (AP.st.items[nm] || 0) + x[1]; log('APPLE +' + x[1] + ' ' + nm); });
  if (sp >= 0 && q) { AP.revealed[q.enc] = now; OUT.revealed.push(q.enc); if (probs) AP.probs[q.enc] = probs; }
  if (sp >= 0) { AP.st.mons++; log('APPLE revealed #' + sp + (cp >= 0 ? ' CP' + cp : '') + (q ? ' enc=' + q.enc : '') + ' -- catching it'); }
}
function appleInstall() {   /* RPC thread: metadata + hooks only */
  var h = il();
  AP.ctl = clsByName('', 'DynamicTappableController'); if (AP.ctl.isNull()) return 'no DynamicTappableController';
  var F = fieldsAll(AP.ctl), need = {enc: '<EncounterId>k__BackingField', type: '<TypeKey>k__BackingField', isEnc: '<IsEncounter>k__BackingField',
    despawn: '<DespawnTimeMs>k__BackingField', loc: '<Location>k__BackingField', gesture: 'tapGesture'};
  AP.f = {};
  for (var k in need) { if (!F[need[k]]) return 'no field ' + need[k]; AP.f[k] = F[need[k]].off; }
  if (F[need.loc].tn !== 'Niantic.LatLng') return 'Location is ' + F[need.loc].tn;
  AP.gos = Object.keys(F).filter(function (n) { return F[n].tn === 'UnityEngine.GameObject'; }).map(function (n) { return F[n].off; });
  var it = Memory.alloc(PS), m; it.writePointer(NULL);
  while ((m = h.methods(AP.ctl, it)) && !m.isNull()) {
    if (h.paramCount(m) !== 2) continue;
    if (cstr(h.typeName(h.param(m, 0))) === 'System.Object' && cstr(h.typeName(h.param(m, 1))) === 'System.EventArgs' &&
        cstr(h.typeName(h.retType(m))) === 'System.Void') { AP.handler = m; break; }
  }
  if (!AP.handler) return 'no tap handler';
  var ea = clsByName('System', 'EventArgs'); if (!ea.isNull()) AP.evF = h.fieldFromName(ea, Memory.allocUtf8String('Empty'));
  AP.int32 = clsByName('System', 'Int32');
  var ie = clsByName('Holoholo.Rpc', 'Item'), nice = {A: 'Sweet Apple', B: 'Tart Apple', C: 'Syrupy Apple'}, ids = [], fe;
  if (!ie.isNull()) {
    it.writePointer(NULL);
    while ((fe = h.fields(ie, it)) && !fe.isNull()) {
      var mm = /EvolutionStoneMaple([ABC])$/.exec(cstr(h.fieldName(fe))); if (!mm || !(h.fieldFlags(fe) & 0x10)) continue;
      var vb = Memory.alloc(8); vb.writeS64(0); h.staticGet(fe, vb); AP.names[vb.readS32()] = nice[mm[1]]; ids.push(vb.readS32());
    }
  }
  if (ids.length) APPLE_IDS = ids; else AP.names = {1151: 'Sweet Apple', 1152: 'Tart Apple', 1155: 'Syrupy Apple'};
  var reg = hookAll(AP.ctl, ['Initialize', 'Refresh', 'get_Id', 'get_Position', 'get_VisibleOnMap', 'get_TypeKey', 'get_IsEncounter', 'get_DespawnTimeMs'], -1, apNote, null);
  var rsp = clsByName('Holoholo.Rpc', 'ProcessTappableOutProto'), nr = 0;
  if (!rsp.isNull()) {
    var RF = fieldsAll(rsp);
    AP.rf = {Status: RF.Status ? RF.Status.off : 0x10, Reward: RF.Reward ? RF.Reward.off : 0x18, Encounter: RF.Encounter ? RF.Encounter.off : 0x20};
    var lpk = clsByName('Holoholo.Rpc', 'LootProto'); if (!lpk.isNull()) { var LF = fieldsAll(lpk); AP.loot = LF.LootItem ? LF.LootItem.off : 0x10; }
    var lik = clsByName('Holoholo.Rpc', 'LootItemProto');
    if (!lik.isNull()) { var IF = fieldsAll(lik); AP.liCount = IF.Count ? IF.Count.off : -1;
      Object.keys(IF).forEach(function (n) { if (IF[n].tn === 'System.Object') AP.liObj = IF[n].off; }); }
    var tek = clsByName('Holoholo.Rpc', 'TappableEncounterProto');
    if (!tek.isNull()) { var TF = fieldsAll(tek); AP.encPk = TF.Pokemon ? TF.Pokemon.off : -1; AP.capOff = TF.CaptureProbability ? TF.CaptureProbability.off : -1; }
    var pkk = clsByName('Holoholo.Rpc', 'PokemonProto'); if (!pkk.isNull()) { var PF = fieldsAll(pkk); AP.pkCp = PF.cp_ ? PF.cp_.off : (PF.Cp ? PF.Cp.off : -1); }
    /* every 1-argument parse method: the reply mostly comes through an obfuscated one, not MergeFrom */
    it.writePointer(NULL);
    while ((m = h.methods(rsp, it)) && !m.isNull()) {
      if (h.paramCount(m) !== 1) continue;
      var nm = cstr(h.methodName(m)); if (['WriteTo', 'Equals', '.ctor', 'CalculateSize'].indexOf(nm) >= 0) continue;
      var code = m.readPointer(); if (code.isNull()) continue;
      Interceptor.attach(code, {onEnter: function (a) { this.s = a[0]; },
        onLeave: function () { try { if (this.s && !this.s.isNull()) onTappableOut(this.s); } catch (e) { ST.errs++; } }});
      nr++;
    }
  }
  AP.inst = {reg: reg, reply: nr, gos: AP.gos.length, handler: cstr(h.methodName(AP.handler)), items: APPLE_IDS};
  return AP.inst;
}

/* ---------------- the pump: UnityMain, entered from the C gate ~9x/s (every frame while tap-to-move is on) ---- */
function pump(self) {
  try { if (CFG.tap && S.ready) tapTick(); } catch (e) { ST.errs++; }
  var now = Date.now(); if (now - LASTWORK < 100) return; LASTWORK = now;
  try {
    if (S.stale) { if (now >= S.nextLookup) lookup(now, S.stale); if (!S.ready || S.stale) return; }
    if (self && !self.isNull()) {   /* a map camera we did not see right after the lookup = the map was rebuilt */
      var ks = self.toString();
      if (now < CAM.until) CAM.seen[ks] = 1;
      else if (!CAM.seen[ks]) { S.stale = 'the map was rebuilt'; S.nextLookup = 0; log('REFRESH: ' + S.stale); return; }
    }
    if (!CFG.catch || VIS > 0) { QUIET = 45000; if (!CFG.catch) LASTVIS = now; }
    else if (now - LASTVIS >= QUIET) {   /* backstop: nothing seen for a long time -- re-find, then back off */
      S.stale = 'no Pokemon seen for ' + Math.round((now - LASTVIS) / 1000) + ' s'; S.nextLookup = 0;
      QUIET = Math.min(QUIET * 2, 600000); log('REFRESH: ' + S.stale); return;
    }
    if (now - LASTPOLL >= 3000) { LASTPOLL = now; pollCounts(); }
    if (CFG.catch) catchTick(now);
    if (CFG.spin && now >= SPIN.next) spinTick(now);
    if (CFG.apples && AP.handler && now - AP.last >= 200) { AP.last = now; appleTick(now); }
    if (M.reqPlayer && !S.ps.isNull() && now >= LIM.nextAcct) { LIM.nextAcct = now + 3600000; call(M.reqPlayer, S.ps, []); }
  } catch (e) { ST.errs++; log('ERR ' + String(e).slice(0, 120)); }
}

function applyCfg(c) {
  if (!c) return;
  ['catch', 'spin', 'tap', 'perfect', 'apples', 'openMs', 'maxOpen', 'thresh', 'pinap', 'pinapFloor', 'razz', 'razzFloor', 'razzThresh'].forEach(function (k) { if (c[k] !== undefined) CFG[k] = c[k]; });
  if (c.floors) CFG.floors = {1: c.floors['1'], 2: c.floors['2'], 3: c.floors['3']};
  if (c.legendary) { CFG.legendary = {}; c.legendary.forEach(function (d) { CFG.legendary[d] = 1; }); }
  if (c.priority) { CFG.priority = {}; c.priority.forEach(function (d) { CFG.priority[d] = 1; }); }
  if (c.appleSpecies) { CFG.appleSpecies = {}; c.appleSpecies.forEach(function (d) { CFG.appleSpecies[d] = 1; }); }
  if (GATE) GATE.add(24).writeS64(CFG.tap ? 1 : 0);   /* tap-to-move polls input every frame */
}

rpc.exports = {
  /* RPC thread: metadata lookups + hooks only. No runtime_invoke, no thread attach. */
  install: function (cfg, done, revealed) {
    applyCfg(cfg);
    (done || []).forEach(function (enc) { DONE[enc] = 1; DONEQ.push(enc); });
    (revealed || []).forEach(function (enc) { AP.revealed[enc] = Date.now(); });
    var st = {};
    findClasses(['holo-game.dll'], ['CameraFollowingGround', 'PokeballThrow', 'MapPlaceDirectoryService', 'MapAvatar', 'WildMapPokemon'], K);
    findClasses(['holo-protos.dll', 'holo-game.dll'], ['EncounterOutProto', 'CatchPokemonOutProto', 'CatchPokemonProto', 'FortSearchOutProto',
      'CaptureAwardProto', 'CaptureScoreProto', 'IncenseEncounterOutProto', 'DiskEncounterOutProto', 'DailyEncounterOutProto', 'AttractedPokemonEncounterOutProto',
      'DailyBonusSpawnEncounterOutProto', 'StationPokemonEncounterOutProto'], K);
    findClasses(['UnityEngine.InputLegacyModule.dll', 'UnityEngine.CoreModule.dll'], ['Input', 'Camera'], K);
    /* the item bag: the concrete class with GetItemCount(int) */
    var h = il(), imgs = images(), gi = imgs['holo-game.dll'];
    [/ItemBag/, /Bag|Item|Invent/, /./].forEach(function (re) {   /* by name first; any concrete class if names are obfuscated */
      if (K.ItemBag || !gi) return;
      var cc = h.classCount(gi), gic = Memory.allocUtf8String('GetItemCount'), uie = Memory.allocUtf8String('UseItemForEncounter');
      for (var j = 0; j < cc && !K.ItemBag; j++) {
        var k = h.classAt(gi, j); if (k.isNull()) continue; var nm = cstr(h.className(k));
        if (!re.test(nm) || /^I[A-Z]/.test(nm)) continue;
        if (!h.methodByName(k, gic, 1).isNull() && !h.methodByName(k, uie, 2).isNull()) { K.ItemBag = k; st.bag = nm; }
      }
    });
    var need = ['CameraFollowingGround', 'PokeballThrow', 'MapPlaceDirectoryService', 'ItemBag', 'EncounterOutProto', 'CatchPokemonOutProto', 'CatchPokemonProto'];
    st.missing = need.filter(function (n) { return !K[n]; });
    if (st.missing.length) return st;
    PBT_VT = !!h.isValueType(K.PokeballThrow);
    M.allPokemon = methodOf(K.MapPlaceDirectoryService, 'get_AllPokemon', 0);
    M.activeStops = methodOf(K.MapPlaceDirectoryService, 'get_ActivePokestops', 0);
    M.itemCount = methodOf(K.ItemBag, 'GetItemCount', 1);
    M.useItem = methodOf(K.ItemBag, 'UseItemForEncounter', 2);
    M.avatarLoc = K.MapAvatar ? methodOf(K.MapAvatar, 'get_Location', 0) : null;
    st.missing = ['allPokemon', 'itemCount', 'useItem'].filter(function (n) { return !M[n]; });
    if (st.missing.length) return st;
    var off1 = function (k, names) { for (var i = 0; i < names.length; i++) { var o = fieldOff(k, names[i]); if (o >= 0) return o; } return -1; };
    OFF.cStatus = off1(K.CatchPokemonOutProto, ['Status', 'status_']); if (OFF.cStatus < 0) OFF.cStatus = 0x10;
    OFF.cCaptured = off1(K.CatchPokemonOutProto, ['CapturedPokemonId', 'capturedPokemonId_']); if (OFF.cCaptured < 0) OFF.cCaptured = 0x20;
    OFF.cAward = off1(K.CatchPokemonOutProto, ['Scores', 'CaptureAward', 'captureAward_']);
    var AW = K.CaptureScoreProto || K.CaptureAwardProto;
    OFF.aDust = AW ? off1(AW, ['Stardust', 'stardust_']) : -1;
    OFF.aCandy = AW ? off1(AW, ['Candy', 'candy_']) : -1;
    OFF.aXp = AW ? off1(AW, ['Exp', 'Xp', 'xp_']) : -1;
    var lu = methodOf(K.CameraFollowingGround, 'LateUpdate', 0);
    if (!lu || lu.readPointer().isNull()) { st.missing = ['CameraFollowingGround.LateUpdate']; return st; }
    try { cInit(); } catch (e) { st.missing = ['C module: ' + String(e).slice(0, 120)]; return st; }
    applyCfg(cfg);
    Interceptor.attach(lu.readPointer(), CM);   /* the C gate; it enters pump() ~9x/s */
    st.pump = true;
    st.hooks = {
      enc: hookAll(K.EncounterOutProto, ['MergeFrom'], 1, null, onEncounterOut),
      other: 0,
      req: hookAll(K.CatchPokemonProto, ['WriteTo', '_InternalSerialize'], -1, onCatchReq, null),
      res: hookAll(K.CatchPokemonOutProto, ['MergeFrom'], 1, null, onCatchOut),
      spin: K.FortSearchOutProto ? hookAll(K.FortSearchOutProto, ['MergeFrom'], 1, null, onSpinOut) : 0
    };
    /* not map encounters: the wild proto (hooked above), berries, quests, PvP/Rocket rewards, battle flee, debug, queries */
    var skipOut = /^(EncounterOutProto|UseItemEncounterOutProto|QuestEncounterOutProto|LoadedQuestEncounterOutProto|VsSeekerRewardEncounterOutProto|InvasionEncounterOutProto|FleeBattleEncounterOutProto|DebugPokemonEncounterOutProto|Get.*)$/;
    var outs = [], seenOut = {}, allImg = images();
    ['holo-protos.dll', 'holo-game.dll'].forEach(function (iname) {   /* StationPokemonEncounterOutProto lives in holo-game */
      var im = allImg[iname]; if (!im) return; var pc = h.classCount(im);
      for (var q = 0; q < pc; q++) { var kq = h.classAt(im, q); if (kq.isNull()) continue; var nq = cstr(h.className(kq));
        if (/EncounterOutProto$/.test(nq) && !skipOut.test(nq) && !seenOut[nq]) { seenOut[nq] = 1; outs.push([nq, kq]); } }
    });
    var PKP = findClasses(['holo-protos.dll'], ['PokemonProto'], {}).PokemonProto;
    OFF.pkId = PKP ? off1(PKP, ['PokemonId', 'pokemonId_']) : -1;
    st.otherTypes = [];
    outs.forEach(function (x) {
      var nm = x[0], kl = x[1];
      NWOFF[nm] = {res: off1(kl, ['Result', 'Status', 'result_', 'status_']), pk: off1(kl, ['Pokemon', 'PokemonData', 'pokemon_', 'pokemonData_']),
                   cp: off1(kl, ['CaptureProbability', 'captureProbability_'])};
      if (NWOFF[nm].res < 0) NWOFF[nm].res = 0x10;
      if (NWOFF[nm].cp < 0) NWOFF[nm].cp = 0x20;
      var n = hookAll(kl, ['MergeFrom'], 1, null, function (sp) { onOtherEncounterOut(sp, nm); });
      st.hooks.other += n; st.otherTypes.push(nm.replace('EncounterOutProto', '') + (NWOFF[nm].pk < 0 ? '(no pokemon field)' : ''));
    });
    st.award = OFF.cAward >= 0 && OFF.aDust >= 0;
    if (!st.award) {   /* show the real field names so the offsets can be fixed */
      var names = function (k) { var o = [], it = Memory.alloc(PS); it.writePointer(NULL); var f; while ((f = h.fields(k, it)) && !f.isNull()) o.push(cstr(h.fieldName(f)) + '@' + h.fieldOffset(f)); return o.join(','); };
      st.catchOutFields = names(K.CatchPokemonOutProto); st.awardFields = (K.CaptureScoreProto || K.CaptureAwardProto) ? names(K.CaptureScoreProto || K.CaptureAwardProto) : 'no CaptureScoreProto/CaptureAwardProto';
    }
    st.avatar = !!M.avatarLoc; st.tap = !!(K.Input && K.Camera);
    try { st.apples = appleInstall(); } catch (e) { st.apples = 'err ' + String(e).slice(0, 100); }
    try {   /* the GAME opening an encounter itself (apple reveals: ~3 s after the tap reply) */
      var ser = K.WildMapPokemon ? methodOf(K.WildMapPokemon, 'SendEncounterRequest', 0) : null;
      if (ser && !ser.readPointer().isNull()) {
        Interceptor.attach(ser.readPointer(), {onEnter: function (a) { if (!OPENING && !a[0].isNull()) GAMEOPEN[a[0].toString()] = Date.now(); }});
        st.gameOpen = true;
      }
    } catch (e) { st.gameOpen = 'err ' + String(e).slice(0, 60); }
    try {   /* limits: the player service (for GetPlayer) and the server's GetPlayer reply */
      var psk = clsByName('Niantic.Holoholo', 'PlayerService'); K.PlayerService = psk.isNull() ? null : psk;
      M.reqPlayer = K.PlayerService ? methodOf(K.PlayerService, 'RequestPlayerFromServer', 0) : null;
      var gpk = clsByName('Holoholo.Rpc', 'GetPlayerOutProto');
      if (!gpk.isNull()) {
        GPOFF = {}; ['Success', 'Player', 'Banned', 'Warn', 'WasSuspended', 'WarnExpireMs'].forEach(function (n) { GPOFF[n] = fieldOff(gpk, n); });
        var gi2 = Memory.alloc(PS), gm; gi2.writePointer(NULL); st.limits = 0;
        while ((gm = h.methods(gpk, gi2)) && !gm.isNull()) { if (h.paramCount(gm) !== 1) continue; var gn = cstr(h.methodName(gm));
          if (['WriteTo', 'Equals', '.ctor', 'CalculateSize'].indexOf(gn) >= 0) continue; var gc = gm.readPointer(); if (gc.isNull()) continue;
          Interceptor.attach(gc, {onEnter: function (a) { this.s = a[0]; }, onLeave: function () { try { if (this.s && !this.s.isNull()) onGetPlayerOut(this.s); } catch (e) { ST.errs++; } }}); st.limits++; }
      }
    } catch (e) { st.limits = 'err ' + String(e).slice(0, 80); }
    return st;
  },
  cfg: function (c) { applyCfg(c); },
  stats: function () {
    return {frame: GATE ? GATE.readS64().toNumber() : 0, ready: S.ready, stale: S.stale, st: ST, census: CENSUS, hidden: HIDLAST, hidNear: HIDNEARLAST, items: ITEMC, vis: VIS, tracked: NE, pend: PEND.length,
            hold: Math.max(0, Math.round((HOLD - Date.now()) / 1000)), holdWhy: HOLDWHY, lastCatchMs: LASTCATCHMS,
            spin: {total: SPIN.total, inRange: SPIN.inRange, cooling: SPIN.cooling, spins: SPIN.spins, ok: SPIN.ok, xp: SPIN.xp, items: SPIN.items, fail: SPIN.fail},
            limit: limitState(Date.now()),
            apples: AP.inst ? {on: !!CFG.apples, st: AP.st, cand: Object.keys(AP.cand).length, ids: APPLE_IDS, range: AP.maxDist, okD: AP.okD, failD: AP.failD < 9999 ? AP.failD : null} : null};
  },
  drain: function () { var o = OUT; OUT = {log: [], done: [], tap: [], revealed: []}; return o; }
};
"""


def revealed_load():
    try:
        import json
        with open(REVEALED_FILE) as fh:
            m = json.load(fh)
        return [k for k, t in m.items() if time.time() - t < 180]   # older reveals are no longer catchable
    except (OSError, ValueError):
        return []


def revealed_add(ids):
    try:
        import json
        try:
            with open(REVEALED_FILE) as fh:
                m = json.load(fh)
        except (OSError, ValueError):
            m = {}
        now = time.time()
        for k in ids:
            m[k] = now
        m = {k: t for k, t in m.items() if now - t < 1800}
        with open(REVEALED_FILE, "w") as fh:
            json.dump(m, fh)
    except OSError:
        pass


def now_s():
    return time.strftime("%H:%M:%S")


class Log:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:   # keep the log from growing without bound (it once hit 19 MB)
            if os.path.getsize(path) > 8 * 1024 * 1024:
                os.replace(path, path + ".1")
        except OSError:
            pass
        self.f = open(path, "a", encoding="utf-8")

    def __call__(self, s):
        line = f"{now_s()} {s}"
        self.f.write(line + "\n")
        self.f.flush()
        print(line, flush=True)


def flag(name):
    try:
        with open(FLAGS[name]) as fh:
            return fh.read().strip() == "1"
    except OSError:
        return False


def paused_until():
    try:
        with open(PAUSE_FILE) as fh:
            t = int(fh.read().strip() or 0)
        return t if t > time.time() else 0
    except (OSError, ValueError):
        return 0


def wait_while_paused(w):
    t = paused_until()
    if not t:
        return
    w(f"paused for another tool until {time.strftime('%H:%M:%S', time.localtime(t))} -- detached")
    last = time.time()
    while paused_until():
        time.sleep(1)
        if time.time() - last >= 30:   # heartbeat: run_catch.sh restarts a catcher whose log goes silent
            last = time.time()
            w(f"still paused ({int(paused_until() - time.time())}s left)")
    w("pause cleared -- re-attaching")


def gadget_up():
    sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sk.settimeout(2.0)
    try:
        sk.connect(("127.0.0.1", 27047))
        return True
    except OSError:
        return False
    finally:
        sk.close()


def su(cmd, timeout=10):
    try:
        return subprocess.run(["su", "-c", cmd], capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def game_pid_age():
    """(pid, seconds since PoGo started) via su -- Termux itself cannot see other apps' /proc."""
    out = su("p=$(pidof -s com.nianticlabs.pokemongo) && echo $p && cut -d' ' -f22 /proc/$p/stat && cut -d' ' -f1 /proc/uptime")
    try:
        pid, start, up = out.split()[:3]
        return int(pid), float(up) - int(start) / os.sysconf("SC_CLK_TCK")
    except ValueError:
        return None, None


def teleport(lat, lng, w):
    """Double-tap-to-move: GPS Joystick owns the mock location, so it does the move (headless service)."""
    before = cur_pos()
    su(f"am start-foreground-service -a theappninjas.gpsjoystick.TELEPORT --ef lat {lat} --ef lng {lng}")
    time.sleep(1.2)
    after = cur_pos()
    w(f"TAP teleported -> {after}" if after and after != before else f"TAP teleport did NOT apply (still {after}, target {lat},{lng})")


def cur_pos():
    m = re.search(r"last location=Location\[gps ([0-9.\-]+),([0-9.\-]+)", su("dumpsys location"))
    return f"{m.group(1)},{m.group(2)}" if m else None


def cfg_now():
    c = dict(CFG)
    for k in FLAGS:
        c[k] = flag(k)
    return c


SESS = {"s": None}


def release(sess):
    """Detach AND drop the device connection. A detached session alone left the TCP link to the gadget open, so a
    paused catcher still showed 2 lines in `ss -tn | grep -c :27047` and the cull's wait-for-0 timed out (21:33)."""
    try:
        sess.detach()
    except Exception:
        pass
    try:
        import frida
        frida.get_device_manager().remove_remote_device(pg.FRIDA_REMOTE)
    except Exception:
        pass


def graceful(signum, frame):
    """Detach before dying: a kill -9 while attached left a dead socket on the single-client gadget."""
    try:
        if SESS["s"]:
            SESS["s"].detach()
    except Exception:
        pass
    raise SystemExit(0)


def limit_part(stt, base, w):
    """ | LIMIT spins=BLOCKED since HH:MM (xN OutOfRange; last ok HH:MM) acct=clean|WARNED until ... -- the server's own answers."""
    L = stt.get("limit")
    if not L:
        return ""
    hm = lambda ms: time.strftime("%H:%M", time.localtime(ms / 1000)) if ms else "-"
    spin = L["spin"]
    if spin == "BLOCKED":
        spin = f"BLOCKED since {hm(L['oorSince'])} (OutOfRange x{L['oorStreak']}, last ok {hm(L['lastOk'])})"
    a = L.get("acct")
    if not a:
        acct = "unread"
    elif a.get("banned"):
        acct = "BANNED"
    elif a.get("suspended"):
        acct = "SUSPENDED"
    elif a.get("warn"):
        acct = "WARNED until " + time.strftime("%m-%d %H:%M", time.localtime(a["warnExpireMs"] / 1000))
    else:
        acct = "clean"
    txt = f"spins={spin} acct={acct}"
    if L.get("flee", 0) >= 3:
        txt += f" catches=fled {L['flee']} in a row"
    if L.get("hold"):
        txt += f" hold={L['hold']}"
    key = (L["spin"], acct, L.get("flee", 0) >= 3)
    if key != base.get("limitkey"):
        base["limitkey"] = key
        w(f"LIMIT {txt}" + (f" (account read {hm(L['acctT'])})" if L.get("acctT") else ""))
    return f" | LIMIT {txt}"


def apple_part(stt, it):
    """ | apples taps/got/revealed/fails + the bag's Sweet/Tart/Syrupy counts (read from the game every 3 s)."""
    ap = stt.get("apples")
    if not ap or not ap.get("on"):
        return ""
    a = ap["st"]
    bag = "/".join(str(it.get(str(i), -1)) for i in ap.get("ids") or [])
    got = ",".join(f"{k.replace(' Apple', '')}+{v}" for k, v in a["items"].items()) or "0"
    duds = (stt.get("st") or {}).get("appleDuds", 0)
    gopen = (stt.get("st") or {}).get("appleGameOpen", 0)
    stale = (stt.get("st") or {}).get("appleStale", 0)
    return (f" | apples taps={a['taps']} got={got} revealed={a['mons']} seen={a['live']} duds={duds} gameopened={gopen} stale={stale}"
            + (f" fails={a['fails']}" if a["fails"] else "") + f" range={ap.get('range')}m (ok<={ap.get('okD')} fail>={ap.get('failD')})"
            + f" bag S/T/Sy={bag}")


def report(w, stt, t0, base):
    st, it, sp = stt["st"], stt["items"], stt["spin"]
    mins = max((time.time() - t0) / 60.0, 1e-6)
    c = st["caught"]
    w(f"run {int(time.time() - t0)}s | caught={c} esc={st['esc']} flee={st['fled']} manual={st['manual']} "
      f"({c / mins:.1f}/min, last {stt['lastCatchMs'] / 1000:.1f}s) | dust=+{st['dust']} candy=+{st['candy']} xp=+{st['xp']} | "
      f"P={it.get('1', -1)} G={it.get('2', -1)} U={it.get('3', -1)} Razz={it.get('701', -1)}(fed {st['fedRazz']}) "
      f"Pinap={it.get('705', -1)}(fed {st['fedPinap']}) | vis={stt['vis']} track={stt['tracked']} pend={stt['pend']} "
      f"| spins={sp['ok']} stops={sp['total']}/{sp['inRange']}/{sp['cooling']} | skip={st['skip']} errs={st['errs']}"
      + (f" | HOLD {stt['hold']}s: {stt['holdWhy']}" if stt["hold"] else "")
      + apple_part(stt, it) + limit_part(stt, base, w)
      + (f" | spinfail={sp['fail']}" if sp["fail"] else ""))
    # TYPES: every class on the map as on/tracked (+ why not: noid / hidden / skipped) -- the answer to "why not that one"
    cen = stt.get("census") or {}
    parts = []
    for cls, (n, trk, noid, hid, skp, done) in sorted(cen.items()):
        why = "".join(f" {k}={v}" for k, v in (("noid", noid), ("hidden", hid), ("skipped", skp), ("done", done)) if v)
        if cls != "WildMapPokemon" or noid or hid or skp:
            parts.append(f"{cls.replace('MapPokemon', '').replace('MapPlacePokemon', '(POI)')} {n}/{trk}{why}")
    hid = stt.get("hidden") or {}
    if hid:
        hn = stt.get("hidNear") or {}
        parts.append("hidden species " + ",".join(f"#{k}x{v}" for k, v in sorted(hid.items(), key=lambda kv: -kv[1])[:8])
                     + f" nearest apple one {hn.get('m')} m" + (f" ({hn.get('bad')} unreadable)" if hn.get("bad") else ""))
    if parts and parts != base.get("lasttypes"):
        base["lasttypes"] = parts
        w("TYPES on map/tracked: " + " | ".join(parts))
    # per-minute line for minute-by-minute rates
    minute = time.strftime("%H:%M")
    if base.get("minute") != minute:
        if base.get("minute"):
            w(f"MINUTE {base['minute']} caught={c - base.get('mc', 0)} fled={st['fled'] - base.get('mf', 0)} "
              f"dust=+{st['dust'] - base.get('md', 0)}")
        base.update(minute=minute, mc=c, mf=st["fled"], md=st["dust"])
    try:
        with open(STATE_FILE, "w") as fh:
            fh.write(f"caught={c} fled={st['fled']} spins={sp['ok']} xp={sp['xp']} items={sp['items']} "
                     f"ready={max(0, sp['inRange'] - sp['cooling'])} cooling={sp['cooling']}\n")
        os.chmod(STATE_FILE, 0o666)
    except OSError:
        pass


def session_loop(w, done_ids, base):
    """One attach. Returns when the link drops or a pause is requested; raises SystemExit when PoGo is closed."""
    wait_while_paused(w)
    if not gadget_up():
        # wait here instead of exiting: the supervisor only looked every 30 s, which made every game restart slow
        w("waiting for PoGo...")
        n = 0
        while not gadget_up():
            time.sleep(1)
            n += 1
            if n % 60 == 0:
                w(f"still waiting for PoGo ({n // 60} min)")
            if paused_until():
                return
    pid, age = game_pid_age()
    if age is None:
        w("could not read PoGo's age -- waiting 20s to be safe")
        time.sleep(20)
    elif age < COLD_AGE_S:
        w(f"PoGo started {age:.0f}s ago -- waiting {COLD_AGE_S - age:.0f}s before attaching")
        time.sleep(COLD_AGE_S - age)
    if paused_until():   # a pause may have landed during the waits above -- honour it before attaching
        return
    t_att = time.time()
    sess, _ = pg.get_session()
    SESS["s"] = sess
    dropped = {"why": None}
    sess.on("detached", lambda reason, crash=None: dropped.__setitem__("why", str(reason)))
    sc = sess.create_script(JS)
    sc.on("message", lambda m, data: w(f"JS ERROR {m.get('description', m)} {str(m.get('stack', ''))[:300]}") if m.get("type") == "error" else None)
    sc.load()
    st = sc.exports_sync.install(cfg_now(), list(done_ids), revealed_load())
    if not st.get("pump"):
        w(f"install failed: {st} -- retrying in 5s")
        release(sess)
        time.sleep(5)
        return
    base["attached_at"] = time.time()
    w(f"reply types hooked: {', '.join(st.get('otherTypes') or [])}")
    w(f"attached pid={pid} age={age and int(age)}s in {time.time() - t_att:.1f}s | hooks={st.get('hooks')} "
      f"award={st.get('award')} bag={st.get('bag', 'ItemBag')} tap={st.get('tap')} apples={st.get('apples')}")
    if not st.get("award"):
        w(f"award fields: catchOut=[{st.get('catchOutFields')}] award=[{st.get('awardFields')}]")
    t0 = time.time()
    cfg = cfg_now()
    last_rep, last_frame, idle = 0, None, 0
    while dropped["why"] is None:
        c = cfg_now()
        if c != cfg:
            cfg = c
            sc.exports_sync.cfg(c)
            w("toggles: " + " ".join(f"{k}={'on' if c[k] else 'off'}" for k in FLAGS))
        d = sc.exports_sync.drain()
        for line in d["log"]:
            w(line)
        done_ids.extend(d["done"])
        if d.get("revealed"):
            revealed_add(d["revealed"])
        for t in d["tap"]:
            w(f"TAP {t}")
            if t.startswith("MOVED "):
                _, lat, lng = t.split()
                teleport(lat, lng, w)
        if time.time() - last_rep >= 10:
            last_rep = time.time()
            stt = sc.exports_sync.stats()
            if stt["ready"]:
                report(w, stt, t0, base)
            else:
                w(f"waiting for the map ({stt['stale']})")
            # frame counter frozen = game backgrounded / screen off: poll slower (battery)
            idle = idle + 1 if stt["frame"] == last_frame else 0
            last_frame = stt["frame"]
        for _ in range(5 if idle >= 3 else 1):
            time.sleep(1)
            if paused_until():
                break
        if paused_until():
            w("pause requested -- detaching")
            release(sess)
            return
    up = time.time() - base.get("attached_at", 0)
    base["quick"] = base.get("quick", 0) + 1 if up < QUICK_S else 0
    w(f"--- link drop after {up:.0f}s attached: {dropped['why']} -- re-attaching ---")
    if base["quick"] >= 2:
        w(f"!!! SAFETY HOLD: PoGo died within {QUICK_S}s of our attach {base['quick']}x in a row -- not attaching "
          f"for {HOLD_S // 60} min (toggle catching off/on to override)")
        end = time.time() + HOLD_S
        while time.time() < end:
            time.sleep(60)
            w(f"safety hold ({int(end - time.time()) // 60} min left)")
        base["quick"] = 0


def main():
    for sg in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sg, graceful)
    w = Log(LOG)
    w(f"===== catcher start (rebuilt) openMs={CFG['openMs']} =====")
    done_ids = deque(maxlen=4000)   # handled encounters survive a re-attach: never re-open or re-throw one
    base = {}
    fails = 0
    while True:
        try:
            session_loop(w, done_ids, base)
            fails = 0
        except SystemExit:
            raise
        except Exception as e:
            fails += 1
            w(f"--- error: {str(e)[:120]} -- retry in {min(15, 2 * fails)}s ---")
            try:
                if SESS["s"]:
                    SESS["s"].detach()
            except Exception:
                pass
            time.sleep(min(15, 2 * fails))


main()

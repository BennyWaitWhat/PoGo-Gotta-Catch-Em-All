"""Buddy reads and actions inside Pokemon GO (Frida), imported by tools/buddy_run.py (the hundo Eevee buddy rotation).

CAREFUL MODE (the user, 2026-10-29, after the 2026-09-26 lockout: "revisit the eevee rotation again please. Be careful."):
- READS cost the server nothing: plain memory reads of what the game already holds. peek() = the current buddy, its hearts and
  today's hearts (ClientPlayerProto, reached from the live graph's PlayerService once, then followed by pointer); the hearts of
  every past buddy come from the BuddyHistoryData objects in memory (one liveness lookup at install).
  The 2026-09-26 version polled RequestBuddyStats every 30 s (~50 server calls in 25 min); that call is gone.
- ACTIONS are the game's own calls -- SetBuddyPokemon(UInt64), Pet(), Feed(Item, 1), RequestBuddyHistory() -- one at a time,
  on the game thread from Scheduler.LateUpdate. The hook exists only while an action is queued or in flight: act() adds it,
  idle() removes it once nothing is pending (both on the RPC thread, never from inside the hook). Between actions the game
  runs with no hook of ours.
Same rules as gym_tapper: exact-name class lookups only, every call through il2cpp_runtime_invoke with an exception slot, a
PROBE-form hook, QUIET checked first (quiesce() before unload: an unload while a hook was inside a game call deadlocked the game
on 2026-09-26 03:39). Not next to gym_run.py: that runner carries its own buddy module.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import dump_game_limits as dl  # noqa: E402
import live_graph_js as lg  # noqa: E402

JS = dl.JS.split("rpc.exports = {")[0] + lg.JS + r"""
var MFN = f('il2cpp_class_get_method_from_name', 'pointer', ['pointer', 'pointer', 'int']);
var TN = f('il2cpp_type_get_name', 'pointer', ['pointer']);
var CFN = f('il2cpp_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']);
var CGF = f('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']), FGN = f('il2cpp_field_get_name', 'pointer', ['pointer']);
var SGV = f('il2cpp_field_static_get_value', 'void', ['pointer', 'pointer']);
var RINV = f('il2cpp_runtime_invoke', 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);
var FEXC = EX['il2cpp_format_exception'] ? f('il2cpp_format_exception', 'void', ['pointer', 'pointer', 'int']) : null;
var EXC = Memory.alloc(PS), EXC_TXT = Memory.alloc(512);
function klassOf(o) { return o.readPointer(); }
function nameOf(k) { return cs(k.add(0x10).readPointer()); }
function isA(o, k) { try { return !!k && !o.isNull() && o.readPointer().equals(k); } catch (e) { return false; } }
function byName(ns, name) {                   /* exact-name lookup per image -- never a walk over every class */
  var sp = Memory.alloc(PS), a = IL.asms(IL.domain(), sp), n = sp.readU32(), nsp = Memory.allocUtf8String(ns), nmp = Memory.allocUtf8String(name);
  for (var i = 0; i < n; i++) { var k = CFN(IL.asmImage(a.add(i * PS).readPointer()), nsp, nmp); if (!k.isNull()) return k; }
  return null;
}
function methodOn(k, name, argc) { var m = MFN(k, Memory.allocUtf8String(name), argc || 0); return m.isNull() ? null : m; }
function offs(k) { var o = {}; fieldsOf(k).forEach(function (x) { o[x.name] = x.off; }); return o; }
function enumLits(k) {
  var it = Memory.alloc(PS), fd, out = {}; it.writePointer(NULL);
  while ((fd = CGF(k, it)) && !fd.isNull()) { var nm = cs(FGN(fd)); if (nm === 'value__') continue; var b = Memory.alloc(8); b.writeS64(0); SGV(fd, b); out[nm] = b.readS32(); }
  return out;
}
function call(m, obj, what, args) {           /* -> return object, or null if it threw (the exception comes back as a value) */
  EXC.writePointer(NULL);
  var ap = NULL;
  if (args && args.length) { ap = Memory.alloc(PS * args.length); for (var i = 0; i < args.length; i++) ap.add(PS * i).writePointer(args[i]); }
  var r = RINV(m, obj, ap, EXC), ex = EXC.readPointer();
  if (ex.isNull()) return r;
  var msg = ''; try { if (FEXC) { EXC_TXT.writeU8(0); FEXC(ex, EXC_TXT, 511); msg = EXC_TXT.readUtf8String(); } } catch (e) {}
  send({k: 'exc', what: what, msg: msg});
  return null;
}
var POFF = {};
function promiseOffs(pr) {                    /* the promise class's own offsets (Promise<T>: completeCalled / errorCalled / completedValue) */
  var k = pr.readPointer(), key = String(k); if (POFF[key] !== undefined) return POFF[key];
  var o = {k: k}; fieldsOf(klassOf(pr)).forEach(function (x) { if (x.name === 'completeCalled') o.done = x.off; if (x.name === 'errorCalled') o.err = x.off;
    if (x.name === 'completedValue') o.val = x.off; if (x.name === 'errorValue') o.errv = x.off; });
  POFF[key] = (o.done === undefined || o.val === undefined || o.err === undefined) ? null : o;
  if (!POFF[key]) send({k: 'err', e: 'not a Promise<T>: ' + nameOf(k)});
  return POFF[key];
}
function promiseRead(q) {                     /* null = still pending */
  if (!q.pr.readPointer().equals(q.o.k)) return {gone: true};
  if (q.pr.add(q.o.err).readU8()) return {err: str(q.o.errv !== undefined ? q.pr.add(q.o.errv).readPointer() : NULL) || 'error'};
  if (!q.pr.add(q.o.done).readU8()) return null;
  return {val: q.pr.add(q.o.val).readPointer()};
}

var K = {}, M = {}, ITEM = {}, IBAG = null, BUD = {rpc: null, pok: null, q: [], fly: null, lastAt: 0, ho: null};
var LU = null, HOOK = null, CPP = {path: null};
var BERRIES = ['RazzBerry', 'NanabBerry', 'PinapBerry', 'BlukBerry', 'WeparBerry', 'GoldenRazzBerry', 'GoldenNanabBerry', 'GoldenPinapBerry', 'Poffin'];
var BI1 = Memory.alloc(8), BI2 = Memory.alloc(8), BU64 = Memory.alloc(8);
function budHearts(ts) {                      /* BuddyStatsShownHearts -> {km, cats: {category: [heart types]}} */
  var out = {km: null, cats: {}}; if (ts.isNull()) return out;
  var to = offs(klassOf(ts)); out.km = ts.add(to.BuddyAffectionKmInProgress).readFloat();   /* a float (the game's own record prints 1.779297) */
  var mf = ts.add(to.BuddyShownHeartsPerCategory).readPointer(); if (mf.isNull()) return out;
  var ll = mf.add(0x18).readPointer(); if (ll.isNull()) return out;   /* MapField: +0x18 LinkedList (head@0x10, count@0x18) */
  var node = ll.add(0x10).readPointer(), n = ll.add(0x18).readS32();
  for (var i = 0; i < n && i < 20 && !node.isNull(); i++) {          /* node: next@0x18, key@0x28, value@0x30 */
    var key = node.add(0x28).readS32(), val = node.add(0x30).readPointer(), types = [];
    if (!val.isNull()) { var rf = val.add(offs(klassOf(val)).BuddyShownHeartTypes).readPointer();
      if (!rf.isNull()) { var arr = rf.add(0x10).readPointer(), c = rf.add(0x18).readS32(); for (var j = 0; j < c && j < 20; j++) types.push(arr.add(0x20 + 4 * j).readS32()); } }
    out.cats[key] = types; node = node.add(0x18).readPointer();
  }
  return out;
}
function num(o, name) {                      /* a numeric field by name, read at its own width (64-bit -> Number) */
  var fs = fieldsOf(klassOf(o));
  for (var i = 0; i < fs.length; i++) if (fs[i].name === name) { var v = prim(o.add(fs[i].off), fs[i].te === 0x11 ? 0x08 : fs[i].te);
    return typeof v === 'string' ? Number(v) : v; }
  return undefined;
}
function budObserved(od, out) {               /* BuddyObservedData -> hearts, mood, today's hearts, fullness */
  var oo = offs(klassOf(od));
  out.pts = od.add(oo.CurrentPointsEarned).readS32(); out.emotion = od.add(oo.CurrentEmotionPoints).readS32();
  out.today = budHearts(od.add(oo.TodayStatsShownHearts).readPointer());
  var fs = od.add(oo.BuddyFeedStats).readPointer();
  if (!fs.isNull()) { var fo = offs(klassOf(fs)); out.fullUntil = Number(fs.add(fo.FullnessExpirationMs).readS64()); out.full = fs.add(fo.PreMapFullnessPercentage).readFloat();
    out.mapUntil = Number(fs.add(fo.MapExpirationMs).readS64()); }
}
function budRead(v, out) {                    /* any buddy reply -> plain data */
  var o = offs(klassOf(v));
  if (o.Result !== undefined) out.res = v.add(o.Result).readS32();
  if (o.ShownHearts !== undefined) out.shown = v.add(o.ShownHearts).readS32();
  if (o.KmRemaining !== undefined) out.kmLeft = v.add(o.KmRemaining).readDouble();
  if (o.UpdatedBuddy !== undefined) { var ub = v.add(o.UpdatedBuddy).readPointer();
    if (!ub.isNull()) out.buddyId = ub.add(offs(klassOf(ub)).BuddyPokemonId).readU64().toString(); }
  if (o.ObservedData !== undefined) { var od = v.add(o.ObservedData).readPointer(); if (!od.isNull()) budObserved(od, out); }
  for (var nm in o) {                         /* GetBuddyHistoryOutProto: its RepeatedField<BuddyHistoryData> */
    if (out.hist) break;
    if (nm === 'Parser' || nm === 'Result') continue;
    var rf = v.add(o[nm]).readPointer(); if (rf.isNull()) continue;
    var rn = ''; try { rn = nameOf(klassOf(rf)); } catch (e) { continue; }
    if (rn.indexOf('RepeatedField') !== 0) continue;
    var arr = rf.add(0x10).readPointer(), c = rf.add(0x18).readS32(); out.hist = [];
    for (var i = 0; i < c && i < 1000 && !arr.isNull(); i++) { var h = arr.add(0x20 + PS * i).readPointer(); if (h.isNull()) continue;
      var ho = BUD.ho || (BUD.ho = offs(klassOf(h)));
      out.hist.push([h.add(ho.PokemonId).readU64().toString(), h.add(ho.PokedexId).readS32(), h.add(ho.CurrentPointsEarned).readS32(),
                     Number(h.add(ho.LastSetTimestampMs).readS64()), Number(h.add(ho.LastUnsetTimestampMs).readS64())]); }
  }
}
/* ---- passive reads: what the game already holds, no server call ---- */
function cppRead(o) {                         /* ClientPlayerProto -> trainer, current buddy, today's swaps, hearts */
  var co = offs(K.cpp), out = {name: str(o.add(co.Name).readPointer())};
  var bp = o.add(co.BuddyPokemonProto).readPointer();
  if (!bp.isNull()) { var bo = offs(klassOf(bp)); out.buddyId = bp.add(bo.BuddyPokemonId).readU64().toString(); out.setMs = num(bp, 'LastSetTimestampMs');
    var ds = bo.DailyBuddySwaps !== undefined ? bp.add(bo.DailyBuddySwaps).readPointer() : NULL;
    if (!ds.isNull()) { out.swapsWindow = num(ds, 'Window'); out.swapsCount = num(ds, 'Count'); } }
  var od = o.add(co.BuddyObservedData).readPointer(); if (!od.isNull()) budObserved(od, out);
  return out;
}
function findCpp(root, depth) {               /* the field path (offsets) from the live PlayerService to its ClientPlayerProto */
  var q = [[root, []]], seen = {}, n = 0;
  while (q.length && n++ < 800) {
    var it = q.shift(), o = it[0], path = it[1], k;
    try { k = klassOf(o); } catch (e) { continue; }
    if (k.equals(K.cpp)) return path;
    if (path.length >= depth || seen[o.toString()]) continue; seen[o.toString()] = 1;
    fieldsOf(k).forEach(function (x) {
      if (!(x.te === 0x12 || x.te === 0x1c || (x.te === 0x15 && !IL.isValueType(IL.classFromType(x.t))))) return;   /* references only */
      try { var p = o.add(x.off).readPointer(); if (!p.isNull()) q.push([p, path.concat([x.off])]); } catch (e) {} });
  }
  return null;
}
function follow(path) {                       /* re-walked on every peek: the game replaces the proto object, never the path */
  var o = ptr(GRAPH.player);
  for (var i = 0; i < path.length; i++) { o = o.add(path[i]).readPointer(); if (o.isNull()) return null; }
  return isA(o, K.cpp) ? o : null;
}
function histRead() {                         /* every BuddyHistoryData in memory -> {pokemonId: [hearts, dex, lastSetMs]}; the highest
                                                 hearts per id wins (stale copies of older fetches stay allocated; hearts only grow) */
  var out = {}; if (!K.hist) return out;
  var ho = offs(K.hist);
  instances(K.hist, 2000).forEach(function (h) { try {
    var id = h.add(ho.PokemonId).readU64().toString(), p = h.add(ho.CurrentPointsEarned).readS32();
    if (!out[id] || p > out[id][0]) out[id] = [p, h.add(ho.PokedexId).readS32(), num(h, 'LastSetTimestampMs')];
  } catch (e) {} });
  return out;
}
function hookOn() { if (!HOOK && LU) HOOK = Interceptor.attach(LU, function () { if (QUIET) return; frameTick(); }); }   /* PROBE form */
function hookOff() { if (HOOK && !BUSY) { HOOK.detach(); HOOK = null; } return HOOK === null; }

var QUIET = false, BUSY = false, FT_AT = 0;
function frameTick() {                        /* the game thread; one buddy call at a time */
  if (BUSY || QUIET) return;
  var now = Date.now(); if (now - FT_AT < 100) return; FT_AT = now;
  BUSY = true;
  try {
    if (BUD.fly) {
      var r = promiseRead(BUD.fly);
      if (r !== null || now - BUD.fly.at > 20000) {
        var out = {k: 'buddy', what: BUD.fly.what, arg: BUD.fly.arg}; BUD.fly = null;
        if (!r || r.gone || r.err) out.err = r ? (r.err || 'gone') : 'no reply';
        else { try { budRead(r.val, out); } catch (e) { out.err = 'read ' + e; } }
        send(out);
      }
    } else if (BUD.q.length && now - BUD.lastAt >= 1500) {
      var c = BUD.q.shift(), pr = null; BUD.lastAt = now;
      if (c.what === 'count') {                 /* the bag's treat counts (GetItemCount -> boxed Int32), answered at once */
        var cnt = {}; BERRIES.forEach(function (nm) { if (ITEM[nm] === undefined || !isA(IBAG, K.bag) || !M.itemCount) return;
          BI1.writeS32(ITEM[nm]); var r2 = call(M.itemCount, IBAG, 'GetItemCount', [BI1]); cnt[nm] = r2 && !r2.isNull() ? r2.add(16).readS32() : null; });
        send({k: 'buddy', what: 'count', counts: cnt}); BUSY = false; return; }
      if (c.what === 'hist' && M.bHist && isA(BUD.rpc, K.rpc)) pr = call(M.bHist, BUD.rpc, 'RequestBuddyHistory');
      else if (c.what === 'pet' && M.bPet && isA(BUD.rpc, K.rpc)) pr = call(M.bPet, BUD.rpc, 'Pet');
      else if (c.what === 'feed' && M.bFeed && isA(BUD.rpc, K.rpc) && ITEM[c.arg] !== undefined) {
        BI1.writeS32(ITEM[c.arg]); BI2.writeS32(1); pr = call(M.bFeed, BUD.rpc, 'Feed', [BI1, BI2]); }
      else if (c.what === 'set' && M.bSet && isA(BUD.pok, K.pok)) { BU64.writeU64(new UInt64(String(c.arg))); pr = call(M.bSet, BUD.pok, 'SetBuddyPokemon', [BU64]); }
      var po = (pr !== null && !pr.isNull()) ? promiseOffs(pr) : null;
      if (po) BUD.fly = {pr: pr, o: po, at: now, what: c.what, arg: c.arg};
      else send({k: 'buddy', what: c.what, arg: c.arg, err: 'call not made (service/method/item missing, or it threw)'});
    }
  } catch (e) { send({k: 'err', e: 'frame ' + e}); }
  BUSY = false;
}

rpc.exports = {
  install: function () {                      /* lookups + one liveness pass; NO hook (act() adds one only while an action runs) */
    hookOff(); QUIET = false; GRAPH = null; GRAPH_NOTES = []; CPP.path = null; BUD.q.length = 0; BUD.fly = null;
    var ks = byName('Niantic.Zeppelin.Scheduler', 'Scheduler'), kr = byName('Niantic.Holoholo.Buddy', 'BuddyRpcService'),
        kp = byName('Niantic.Holoholo.Buddy', 'BuddyPokemonService'), ki = byName('Holoholo.Rpc', 'Item'),
        kc = byName('Holoholo.Rpc', 'ClientPlayerProto');
    if (!ks || !kr || !kp || !ki || !kc) return {ok: false, why: 'class missing', ks: !!ks, kr: !!kr, kp: !!kp, ki: !!ki, kc: !!kc};
    K.rpc = kr; K.pok = kp; K.cpp = kc; K.hist = byName('Holoholo.Rpc', 'BuddyHistoryData'); ITEM = enumLits(ki);
    M.bFeed = methodOn(kr, 'Feed', 2); M.bPet = methodOn(kr, 'Pet', 0);
    M.bHist = methodOn(kr, 'RequestBuddyHistory', 0); M.bSet = methodOn(kp, 'SetBuddyPokemon', 1);
    var hr = -1, hp = -1;
    fieldsOf(kr).forEach(function (x) { if (cs(TN(x.t)) === 'Niantic.Holoholo.Rpc.IRpcHandler') hr = x.off; });
    fieldsOf(kp).forEach(function (x) { if (cs(TN(x.t)) === 'Niantic.Holoholo.Rpc.IRpcHandler') hp = x.off; });
    var kb = byName('Niantic.Holoholo.Internal', 'ItemBagImpl'), kpb = byName('Niantic.Holoholo.Internal', 'PokemonBagImpl');
    if (kb && kpb) { K.bag = kb; M.itemCount = methodOn(kb, 'GetItemCount', 1);   /* the bag FIRST: it names the live service graph */
      var bo = -1, ibs = []; fieldsOf(kb).forEach(function (x) { if (cs(TN(x.t)) === 'Niantic.Holoholo.IPokemonBag') bo = x.off; });
      instances(kb, 8).forEach(function (b) { try { var pb = b.add(bo).readPointer(); if (bo >= 0 && !pb.isNull() && klassOf(pb).equals(kpb)) ibs.push(b); } catch (e) {} });
      IBAG = pickGraph(ibs); }
    if (!GRAPH || !GRAPH.player) return {ok: false, why: 'no live service graph', graphNotes: GRAPH_NOTES};
    var cr = [], cq = [];
    instances(kr, 4).forEach(function (o) { try { if (hr >= 0 && !o.add(hr).readPointer().isNull()) cr.push(o); } catch (e) {} });
    instances(kp, 4).forEach(function (o) { try { if (hp >= 0 && !o.add(hp).readPointer().isNull()) cq.push(o); } catch (e) {} });
    BUD.rpc = graphPick(cr, 'BuddyRpcService'); BUD.pok = graphPick(cq, 'BuddyPokemonService');   /* the live graph's -- never the first hit */
    if (!BUD.rpc || !BUD.pok) return {ok: false, why: 'service instance not found in the live graph', rpc: !!BUD.rpc, pok: !!BUD.pok, graphNotes: GRAPH_NOTES};
    var lu = methodOn(ks, 'LateUpdate'); if (!lu) return {ok: false, why: 'no LateUpdate'};
    LU = lu.readPointer();
    CPP.path = findCpp(ptr(GRAPH.player), 3);
    return {ok: true, methods: {feed: !!M.bFeed, pet: !!M.bPet, hist: !!M.bHist, set: !!M.bSet}, cppPath: CPP.path,
            bag: !!IBAG, berries: BERRIES.filter(function (n) { return ITEM[n] !== undefined; }), graph: GRAPH, graphNotes: GRAPH_NOTES,
            hist: histRead()};
  },
  peek: function () {                         /* pure reads: no game call, no hook, no server traffic */
    try {
      var o = CPP.path ? follow(CPP.path) : null;
      if (!o) { CPP.path = findCpp(ptr(GRAPH.player), 3); o = CPP.path ? follow(CPP.path) : null; }
      if (!o) return {err: 'no ClientPlayerProto reachable from the live PlayerService'};
      var out = cppRead(o); out.via = 'path'; return out;
    } catch (e) { return {err: 'peek ' + e}; }
  },
  peekScan: function () {                     /* fallback when no path exists: a liveness lookup; the freshest copy wins (newest buddy
                                                 set time, then most hearts -- a frozen copy never moves forward) */
    try {
      var best = null;
      instances(K.cpp, 8).forEach(function (o) { try { var r = cppRead(o); if (!r.buddyId) return;
        if (!best || (r.setMs || 0) > (best.setMs || 0) || ((r.setMs || 0) === (best.setMs || 0) && (r.pts || 0) > (best.pts || 0))) best = r; } catch (e) {} });
      if (!best) return {err: 'no ClientPlayerProto in memory'};
      best.via = 'scan'; return best;
    } catch (e) { return {err: 'peekScan ' + e}; }
  },
  act: function (what, arg) { if (QUIET) return -1; BUD.q.push({what: what, arg: arg}); hookOn(); return BUD.q.length; },
  idle: function () { return (BUD.q.length || BUD.fly) ? false : hookOff(); },   /* true = no hook of ours in the game */
  cancel: function () { BUD.q.length = 0; return !BUD.fly; },
  quiesce: function () { QUIET = true; BUD.q.length = 0; return hookOff(); }
};
"""

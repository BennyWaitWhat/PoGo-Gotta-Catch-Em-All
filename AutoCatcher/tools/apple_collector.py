"""Collect event apples (map tappables: TAPPABLE_TYPE_MAPLE -> ITEM_OTHER_EVOLUTION_STONE_MAPLE_A/B/C =
Sweet/Tart/Syrupy Apple) the way a finger does: call the tappable's own DynamicTappableController.Tapped() on the
game's main thread, so the game sends its normal ProcessTappable request itself.

  python tools/apple_collector.py MINUTES|HH:MM [--live] [--types MAPLE,POKEBALL] [--maxdist 60]

Default is DRY: logs every apple it WOULD tap (id, type, distance, despawn) and calls nothing.
--live taps, at most one tap per 1.5 s, never an encounter tappable (IsEncounter: a Pokemon hides inside).
Proof = the server's reply: ProcessTappableOutProto (Status, Reward) is hooked and logged per tap.
Controllers are found as the game touches them (Initialize/Refresh + per-frame getters), validated by klass,
TypeKey and despawn time in the SAME tick they are tapped -- no pointer is trusted across ticks.
"""
import json
import math
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import pogo_il2cpp as pg  # noqa: E402

DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")   # cloud: the Tailscale bridge exports ADB_TARGET
LIVE = "--live" in sys.argv
TYPES = ["TAPPABLE_TYPE_" + t.strip().upper() for t in (sys.argv[sys.argv.index("--types") + 1] if "--types" in sys.argv else "MAPLE").split(",")]
MAXDIST = float(sys.argv[sys.argv.index("--maxdist") + 1]) if "--maxdist" in sys.argv else 60.0
ENCOUNTERS = "--encounters" in sys.argv   # experiment: tap the revealed-Pokemon tappables too (1 per 10 s)

JS = r"""
var PS = Process.pointerSize, PROP = {exceptions: 'propagate'}, EX = {};
Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function (e) { if (e.name.indexOf('il2cpp_') === 0) EX[e.name] = e.address; });
function nf(n, r, a) { return new NativeFunction(EX[n], r, a, PROP); }
var IL = {
  domain: nf('il2cpp_domain_get', 'pointer', []), asms: nf('il2cpp_domain_get_assemblies', 'pointer', ['pointer', 'pointer']),
  asmImage: nf('il2cpp_assembly_get_image', 'pointer', ['pointer']), fromName: nf('il2cpp_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']),
  methods: nf('il2cpp_class_get_methods', 'pointer', ['pointer', 'pointer']), mName: nf('il2cpp_method_get_name', 'pointer', ['pointer']),
  mArgs: nf('il2cpp_method_get_param_count', 'uint32', ['pointer']), mFrom: nf('il2cpp_class_get_method_from_name', 'pointer', ['pointer', 'pointer', 'int']),
  fields: nf('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']), fName: nf('il2cpp_field_get_name', 'pointer', ['pointer']),
  fOff: nf('il2cpp_field_get_offset', 'uint32', ['pointer']), fType: nf('il2cpp_field_get_type', 'pointer', ['pointer']),
  tType: nf('il2cpp_type_get_type', 'int', ['pointer']), tName: nf('il2cpp_type_get_name', 'pointer', ['pointer']),
  fFlags: nf('il2cpp_field_get_flags', 'int', ['pointer']), cName: nf('il2cpp_class_get_name', 'pointer', ['pointer']),
  parent: nf('il2cpp_class_get_parent', 'pointer', ['pointer']),
  invoke: nf('il2cpp_runtime_invoke', 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']),
  mParam: nf('il2cpp_method_get_param', 'pointer', ['pointer', 'uint32']), mRet: nf('il2cpp_method_get_return_type', 'pointer', ['pointer']),
  fFrom: nf('il2cpp_class_get_field_from_name', 'pointer', ['pointer', 'pointer']), fStatic: nf('il2cpp_field_static_get_value', 'void', ['pointer', 'pointer'])
};
function cs(p) { try { return p.isNull() ? '' : p.readCString(); } catch (e) { return '?'; } }
function cls(ns, name) { var a = Memory.allocUtf8String(ns), b = Memory.allocUtf8String(name), sp = Memory.alloc(8), as = IL.asms(IL.domain(), sp), n = sp.readS32();
  for (var i = 0; i < n; i++) { var k = IL.fromName(IL.asmImage(as.add(i * PS).readPointer()), a, b); if (!k.isNull()) return k; } return null; }
function fieldsOf(k) { var out = [];
  for (var c = k; c && !c.isNull(); c = IL.parent(c)) { var it = Memory.alloc(PS); it.writePointer(NULL); var f;
    while ((f = IL.fields(c, it)) && !f.isNull()) { if (IL.fFlags(f) & 0x10) continue;
      out.push({name: cs(IL.fName(f)), off: IL.fOff(f), te: IL.tType(IL.fType(f)), tn: cs(IL.tName(IL.fType(f)))}); } }
  return out; }
function str(p) { try { if (p.isNull()) return null; var n = p.add(0x10).readS32(); return (n >= 0 && n < 400) ? p.add(0x14).readUtf16String(n) : null; } catch (e) { return null; } }
function klassName(o) { try { return o.isNull() ? null : cs(IL.cName(o.readPointer())); } catch (e) { return '?'; } }

var CTL = null, F = {}, GOS = [], M_TAPPED = null, M_HANDLER = null, EVARGS = null, EVARGS_F = null, EV = [], CAND = {}, TAPPED = {}, TYPES = [], LIVE = false, MAXDIST = 60;
var ENCTAP = false, lastEncTap = 0, PLAT = 0, PLNG = 0, FRAME = 0, lastTap = 0, OURS = false, DEAD = {}, LOGGED = {}, STATS = {seen: 0, live: 0, dead: 0, eligible: 0, taps: 0, replies: 0, skipped: {}};
function skip(why) { STATS.skipped[why] = (STATS.skipped[why] || 0) + 1; }
function meters(a1, o1, a2, o2) { var r = 6371008.8, p1 = a1 * Math.PI / 180, p2 = a2 * Math.PI / 180, dl = (o2 - o1) * Math.PI / 180;
  return 2 * r * Math.asin(Math.sqrt(Math.pow(Math.sin((p2 - p1) / 2), 2) + Math.cos(p1) * Math.cos(p2) * Math.pow(Math.sin(dl / 2), 2))); }
function note(p) { var k = p.toString();
  if (DEAD[k]) { try { if (p.add(F.enc).readU64().toString() + ':' + (p.add(F.isEnc).readU8() !== 0) === DEAD[k]) return; } catch (e) { return; } delete DEAD[k]; }   /* reused by the pool for a new apple */
  if (!CAND[k]) { CAND[k] = Date.now(); STATS.seen++; } }   /* DEAD: expired ones the game keeps pooled */
function read(o) {   /* same-tick snapshot of a controller; null if it is no longer a DynamicTappableController */
  if (o.readPointer().toString() !== CTL.toString()) return null;
  var r = {id: o.add(F.id).readS32(), enc: o.add(F.enc).readU64().toString(), type: str(o.add(F.type).readPointer()),
           isEnc: o.add(F.isEnc).readU8() !== 0, despawn: o.add(F.despawn).readS64().toNumber(),
           lat: o.add(F.loc).readDouble(), lng: o.add(F.loc + 8).readDouble(), ready: true};
  for (var i = 0; i < GOS.length; i++) if (o.add(GOS[i]).readPointer().isNull()) { r.ready = false; break; }
  var tl = o.add(F.tloc).readPointer(); r.fort = tl.isNull() ? null : str(tl.add(0x10).readPointer());
  return r;
}
function readApples() {   /* game record: ItemBagImpl.GetItemCount(item) for Sweet/Tart/Syrupy, on UnityMain */
  if (!BAGP || !M_GIC || APPLE_IDS.length === 0) return;
  try { if (BAGP.readPointer().toString() !== IB.toString()) { BAGP = null; return; }
    APPLE_IDS.forEach(function (id) { var arg = Memory.alloc(8); arg.writeS32(id); var argv = Memory.alloc(PS); argv.writePointer(arg);
      var exc = Memory.alloc(PS); exc.writePointer(NULL); var r = IL.invoke(M_GIC, BAGP, argv, exc);
      if (exc.readPointer().isNull() && !r.isNull()) APPLES[ITEMNAMES[id]] = r.add(0x10).readS32(); }); } catch (e) { EV.push({t: Date.now(), k: 'err', e: 'apples:' + e}); } }
function tick() {
  if (FRAME % 600 === 0) readApples();
  if (++FRAME % 20) return;   /* ~3x/s */
  var now = Date.now();
  Object.keys(CAND).forEach(function (k) {
    var o = ptr(k), s; try { s = read(o); } catch (e) { s = null; }
    if (!s) { delete CAND[k]; return; }                                   /* pooled / freed: forget it */
    var key = s.enc + ':' + s.isEnc;
    if (s.despawn && s.despawn < now) { delete CAND[k]; DEAD[k] = key; if (!LOGGED['d' + key]) { LOGGED['d' + key] = 1; STATS.dead++;
        EV.push({t: now, k: 'EXPIRED', s: s}); } return; }   /* the game keeps expired tappables pooled: log once, never tap */
    if (!LOGGED['l' + key]) { LOGGED['l' + key] = 1; STATS.live++; EV.push({t: now, k: 'LIVE_APPLE', s: s}); }
    if (TAPPED[key]) return;
    if (TYPES.indexOf(s.type) < 0) { if (!TAPPED['t' + key]) { TAPPED['t' + key] = 1; EV.push({t: now, k: 'OTHER', s: s}); } return; }
    if (s.isEnc && !ENCTAP) { if (!TAPPED['e' + key]) { TAPPED['e' + key] = 1; EV.push({t: now, k: 'ENCOUNTER_TAPPABLE', s: s}); } return; }
    if (s.isEnc && now - lastEncTap < 10000) return;
    if (ENCTAP && !s.isEnc) return;   /* experiment mode: the on-phone catcher taps the plain apples */
    var d = (PLAT && s.lat) ? meters(PLAT, PLNG, s.lat, s.lng) : -1; s.dist = Math.round(d);
    if (!s.ready) { skip('not_ready'); return; }
    if (d < 0 || d > MAXDIST) { skip('far'); return; }
    STATS.eligible++;
    if (now - lastTap < 1500) return;                                     /* one tap per 1.5 s */
    lastTap = now; TAPPED[key] = now; if (s.isEnc) lastEncTap = now;
    if (!LIVE) { EV.push({t: now, k: 'WOULD_TAP', s: s}); return; }
    try { if (!EVARGS && EVARGS_F && !EVARGS_F.isNull()) { var box = Memory.alloc(PS); box.writePointer(NULL); IL.fStatic(EVARGS_F, box); EVARGS = box.readPointer(); }   /* main thread */
      var argv = Memory.alloc(PS * 2); argv.writePointer(o.add(F.gesture).readPointer()); argv.add(PS).writePointer(EVARGS || NULL);
      OURS = true; var exc = Memory.alloc(PS); exc.writePointer(NULL); IL.invoke(M_HANDLER, o, argv, exc); OURS = false;
      STATS.taps++; EV.push({t: now, k: 'TAP', s: s, exc: !exc.readPointer().isNull()}); }
    catch (e) { OURS = false; EV.push({t: now, k: 'tap_err', e: String(e), s: s}); }
  });
}
function hookEach(k, pick, cb) { var n = 0, it = Memory.alloc(PS); it.writePointer(NULL); var m;
  while ((m = IL.methods(k, it)) && !m.isNull()) { var nm = cs(IL.mName(m)), argc = IL.mArgs(m); if (!pick(nm, argc)) continue;
    var fp = m.readPointer(); if (fp.isNull()) continue; (function (nm, argc) { Interceptor.attach(fp, cb(nm, argc)); })(nm, argc); n++; }
  return n; }
function val(p, te) {
  switch (te) { case 0x02: return p.readU8() !== 0; case 0x08: case 0x11: return p.readS32(); case 0x09: return p.readU32(); case 0x0a: return p.readS64().toString();
    case 0x0b: return p.readU64().toString(); case 0x0c: return p.readFloat(); case 0x0d: return p.readDouble(); case 0x0e: return str(p.readPointer());
    case 0x12: case 0x15: case 0x1d: case 0x1c: var o = p.readPointer(); if (o.isNull()) return null; var kn = klassName(o); return kn === 'String' ? str(o) : '<' + kn + '>'; }
  return '<te ' + te + '>'; }
function deep(o, depth) {   /* every instance field; follows objects and RepeatedField`1 (arr@0x10, count@0x18) */
  if (!o || o.isNull()) return null; var out = {_c: klassName(o)};
  if (out._c && out._c.indexOf('RepeatedField') === 0) { var arr = o.add(0x10).readPointer(), n = o.add(0x18).readS32(), items = [];
    for (var i = 0; i < n && i < 12; i++) { var el = arr.add(0x20 + i * PS).readPointer(); items.push(depth > 0 ? deep(el, depth - 1) : String(el)); }
    return {_c: out._c, n: n, items: items}; }
  fieldsOf(o.readPointer()).forEach(function (f) { try { var v = val(o.add(f.off), f.te); out[f.name] = v;
    if (depth > 0 && typeof v === 'string' && v.charAt(0) === '<' && v !== '<String>') out[f.name] = deep(o.add(f.off).readPointer(), depth - 1); } catch (e) { out[f.name] = '<err>'; } });
  return out; }
function dumpReply(o) {   /* ProcessTappableOutProto: Status + Reward (repeated LootProto -> LootItem) + Encounter */
  var out = {status: o.add(RF.Status).readS32()}, rw = o.add(RF.Reward).readPointer();
  try { if (!rw.isNull()) { var arr = rw.add(0x10).readPointer(), n = rw.add(0x18).readS32(); out.rewards = [];
      for (var i = 0; i < n && i < 10; i++) { var lp = arr.add(0x20 + i * PS).readPointer(); if (lp.isNull()) continue;
        out.rewards.push(lootItems(lp)); } } } catch (e) { out.rewardErr = String(e); }
  var en = o.add(RF.Encounter).readPointer(); out.encounter = !en.isNull();
  if (out.encounter) { try { var d = deep(en, 1); var pk = d.Pokemon || {}; out.pokemon = {species: pk.pokemonId_, cp: pk.cp_, iv: [pk.individualAttack_, pk.individualDefense_, pk.individualStamina_],
      costume: (pk.pokemonDisplay_ || {}).Costume, form: (pk.pokemonDisplay_ || {}).Form, shiny: (pk.pokemonDisplay_ || {}).Shiny}; out.encResult = d.Result; } catch (e) {} }
  return out; }
var RF = {}, LOOTF = null, ITEMF = null, SEENREP = {}, ITEMNAMES = {}, IB = null, BAGP = null, M_GIC = null, APPLES = {}, APPLE_IDS = [];
function lootItems(lp) {   /* LootProto.LootItem (repeated LootItemProto): item id + count, read by field names */
  if (!LOOTF) { LOOTF = {}; fieldsOf(lp.readPointer()).forEach(function (f) { LOOTF[f.name] = f.off; }); }
  var li = lp.add(LOOTF.LootItem || 0x10).readPointer(), res = [];
  if (li.isNull()) return res; var arr = li.add(0x10).readPointer(), n = li.add(0x18).readS32();
  for (var i = 0; i < n && i < 10; i++) { var it = arr.add(0x20 + i * PS).readPointer(); if (it.isNull()) continue;
    if (!ITEMF) { ITEMF = {}; fieldsOf(it.readPointer()).forEach(function (f) { ITEMF[f.name] = f; }); }
    var r = {}; Object.keys(ITEMF).forEach(function (nm) { var f = ITEMF[nm]; try {
      if (f.te === 0x08 || f.te === 0x11) r[nm] = it.add(f.off).readS32(); else if (f.te === 0x02) r[nm] = it.add(f.off).readU8();
      else if (f.te === 0x1c || f.te === 0x12) { var bx = it.add(f.off).readPointer(); if (!bx.isNull() && klassName(bx) === 'Int32') { r.item = bx.add(0x10).readS32(); r.itemName = ITEMNAMES[r.item] || null; } } } catch (e) {} });
    res.push(r); }
  return res; }
rpc.exports = {
  install: function (types, live, maxdist, enctap) {
    TYPES = types; LIVE = live; MAXDIST = maxdist; ENCTAP = !!enctap; var st = {};
    CTL = cls('', 'DynamicTappableController'); if (!CTL) return {err: 'no DynamicTappableController'};
    var fl = fieldsOf(CTL), by = {}; fl.forEach(function (f) { by[f.name] = f; });
    F = {id: by['<Id>k__BackingField'].off, enc: by['<EncounterId>k__BackingField'].off, type: by['<TypeKey>k__BackingField'].off,
         isEnc: by['<IsEncounter>k__BackingField'].off, despawn: by['<DespawnTimeMs>k__BackingField'].off,
         loc: by['<Location>k__BackingField'].off, tloc: by['<TappableLocation>k__BackingField'].off};
    GOS = fl.filter(function (f) { return f.tn === 'UnityEngine.GameObject'; }).map(function (f) { return f.off; });
    st.offsets = F; st.gameObjects = GOS.length; st.locType = by['<Location>k__BackingField'].tn;
    M_TAPPED = IL.mFrom(CTL, Memory.allocUtf8String('Tapped'), 0); st.tapped = !M_TAPPED.isNull();
    /* THE FINGER PATH: TapGesture.tappedInvoker -> controller handler void ?(System.Object, System.EventArgs) (obfuscated name,
       found by signature). Tapped() is only a bool query -- calling it collected nothing (5 taps, 0 replies, 2026-09-29). */
    var it2 = Memory.alloc(PS); it2.writePointer(NULL); var mm;
    while ((mm = IL.methods(CTL, it2)) && !mm.isNull()) { if (IL.mArgs(mm) !== 2) continue;
      if (cs(IL.tName(IL.mParam(mm, 0))) === 'System.Object' && cs(IL.tName(IL.mParam(mm, 1))) === 'System.EventArgs' && cs(IL.tName(IL.mRet(mm))) === 'System.Void') { M_HANDLER = mm; st.handler = cs(IL.mName(mm)); } }
    F.gesture = by['tapGesture'].off;
    var ea = cls('System', 'EventArgs'); if (ea) EVARGS_F = IL.fFrom(ea, Memory.allocUtf8String('Empty'));
    st.reg = hookEach(CTL, function (nm, argc) { return ['Initialize', 'Refresh', 'get_Id', 'get_Position', 'get_VisibleOnMap', 'get_TypeKey', 'get_IsEncounter', 'get_DespawnTimeMs'].indexOf(nm) >= 0; },
      function (nm) { return {onEnter: function (a) { note(a[0]); }}; });
    st.userTap = hookEach(CTL, function (nm, argc) { return nm === 'Tapped' && argc === 0; },
      function () { return {onEnter: function (a) { if (!OURS) EV.push({t: Date.now(), k: 'USER_TAP', self: a[0].toString()}); }}; });
    /* TRACE the tap chain (who runs after Tapped(), for OUR taps and the user's): service / session / behaviour / map
       handler methods + the request's WriteTo. The session's three per-frame methods are skipped (they spam). */
    var SPAM = {}, TR = function (label) { return function (nm, argc) { return {onEnter: function (a) {
        var ck = label + '.' + nm; SPAM[ck] = (SPAM[ck] || 0) + 1; if (SPAM[ck] > 40) return;
        EV.push({t: Date.now(), k: 'TRACE', m: ck, ours: OURS, a0: a[0].toString(), a1: argc > 0 ? a[1].toString() : null}); }}; }; };
    var notHot = function (nm) { return nm.indexOf('get_') !== 0 && nm.indexOf('set_') !== 0 && ['.ctor', 'Update', 'LateUpdate', 'bfop', 'bfoq', 'bfos'].indexOf(nm) < 0; };
    st.trace = 0;
    [['Niantic.Holoholo.Services.DynamicTappables', 'DynamicTappablesService', 'SVC'], ['Niantic.Holoholo.Services.DynamicTappables', 'DynamicTappablesSession', 'SES'],
     ['Niantic.Holoholo.Services.DynamicTappables', 'DynamicTappableBehaviorService', 'BEH']].forEach(function (x) {
      var k = cls(x[0], x[1]); if (k) st.trace += hookEach(k, notHot, TR(x[2])); });
    var ctlTrace = hookEach(CTL, function (nm) { return notHot(nm) && ['Tapped', 'Initialize', 'Refresh'].indexOf(nm) < 0; }, TR('CTL')); st.trace += ctlTrace;
    var wmp = cls('Niantic.Holoholo.Map', 'WildMapPokemon') || cls('', 'WildMapPokemon');
    if (wmp) st.trace += hookEach(wmp, function (nm) { return notHot(nm) && ['SendEncounterRequest', 'TryCapture', 'OnEncounterResponse', 'StartEncounter', 'Encounter'].some(function (w) { return nm.indexOf(w) >= 0; }); }, TR('WMP'));
    [['Holoholo.Rpc', 'EncounterOutProto', 'ENC'], ['Holoholo.Rpc', 'CatchPokemonOutProto', 'CATCH'], ['Holoholo.Rpc', 'TappableEncounterProto', 'TENC'], ['Holoholo.Rpc', 'EncounterProto', 'ENCREQ'], ['Holoholo.Rpc', 'CatchPokemonProto', 'CATCHREQ']].forEach(function (x) {
      var k = cls(x[0], x[1]); if (k) st.trace += hookEach(k, function (nm, argc) { return argc === 1 && ['Equals', '.ctor', 'CalculateSize'].indexOf(nm) < 0; }, TR(x[2])); });
    var req = cls('Holoholo.Rpc', 'ProcessTappableProto');
    if (req) st.trace += hookEach(req, function (nm, argc) { return nm === 'WriteTo' || nm === 'CalculateSize'; }, TR('REQ'));
    var itemEnum = cls('Holoholo.Rpc', 'Item'); st.items = {};
    if (itemEnum) { var it3 = Memory.alloc(PS); it3.writePointer(NULL); var fe;
      while ((fe = IL.fields(itemEnum, it3)) && !fe.isNull()) { var fn = cs(IL.fName(fe)); if (!(IL.fFlags(fe) & 0x10)) continue;
        if (fn.indexOf('Maple') >= 0 || fn.indexOf('MAPLE') >= 0) { var vb = Memory.alloc(8); vb.writeS64(0); IL.fStatic(fe, vb); st.items[fn] = vb.readS32(); ITEMNAMES[vb.readS32()] = fn; } } }
    IB = cls('Niantic.Holoholo.Internal', 'ItemBagImpl'); M_GIC = IB ? IL.mFrom(IB, Memory.allocUtf8String('GetItemCount'), 1) : NULL;
    APPLE_IDS = Object.keys(ITEMNAMES).map(Number);
    if (M_GIC && !M_GIC.isNull()) { Interceptor.attach(M_GIC.readPointer(), {onEnter: function (a) { if (!BAGP) BAGP = a[0]; }}); st.bag = true; }
    var rsp = cls('Holoholo.Rpc', 'ProcessTappableOutProto');
    fieldsOf(rsp).forEach(function (f) { RF[f.name] = f.off; });
    st.reply = hookEach(rsp, function (nm, argc) { return argc === 1 && ['WriteTo', 'Equals', '.ctor', 'CalculateSize'].indexOf(nm) < 0; },
      function (nm) { return {onEnter: function (a) { this.s = a[0]; }, onLeave: function () { try { var r = dumpReply(this.s);
        if (r.status === 0 && !r.rewards) return; STATS.replies++; var key = 'rep' + this.s; if (SEENREP[key]) return; SEENREP[key] = 1; r.full = deep(this.s, 4); EV.push({t: Date.now(), k: 'REPLY', m: nm, r: r}); } catch (e) { EV.push({t: Date.now(), k: 'err', e: String(e)}); } }}; });
    st.pump = false; var cam = cls('Niantic.Holoholo', 'CameraFollowingGround'); var lu = cam ? IL.mFrom(cam, Memory.allocUtf8String('LateUpdate'), 0) : NULL;
    if (lu && !lu.isNull()) { Interceptor.attach(lu.readPointer(), {onEnter: function () { try { tick(); } catch (e) { EV.push({t: Date.now(), k: 'err', e: 'tick:' + e}); } }}); st.pump = true; }
    return st;
  },
  setPlayer: function (lat, lng) { PLAT = lat; PLNG = lng; },   /* flag-style setter: no il2cpp */
  drain: function () { var e = EV; EV = []; return {ev: e, stats: STATS, cand: Object.keys(CAND).length, apples: APPLES}; }
};
"""


def adb(cmd):
    return subprocess.run(["adb", "-s", DEV, "shell", cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout or ""


def main():
    arg = sys.argv[1]
    if ":" in arg:
        hh, mm = (int(x) for x in arg.split(":"))
        lt = time.localtime()
        minutes = (time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, 0, 0, 0, -1)) - time.time()) / 60
    else:
        minutes = float(arg)
    out = os.path.join(os.path.dirname(HERE), "system", "analysis", "apple_collector.jsonl")
    if "Pixel" not in adb("getprop ro.product.model"):
        sys.exit("not the phone")
    sess, pid = pg.get_session()
    sc = sess.create_script(JS)
    sc.load()
    st = sc.exports_sync.install(TYPES, LIVE, MAXDIST, ENCOUNTERS)
    print(f"{time.strftime('%H:%M:%S')} {'LIVE' if LIVE else 'DRY'} pid {pid} types {TYPES} maxdist {MAXDIST} m | install {st}", flush=True)
    if not (isinstance(st, dict) and st.get("pump") and st.get("handler")):
        sc.unload(); sess.detach()
        sys.exit("install incomplete (no main-thread pump or no tap handler) -- refusing to run")
    t0, last_pos, last_stat, last_apples = time.time(), 0, 0, {}
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": int(time.time() * 1000), "k": "start", "live": LIVE, "st": st}) + "\n")
        try:
            while time.time() - t0 < minutes * 60:
                if time.time() - last_pos >= 2:
                    last_pos = time.time()
                    m = re.search(r"gps ([-0-9.]+),([-0-9.]+) ", adb("dumpsys location | grep -m1 'last mock location'"))
                    if m:
                        sc.exports_sync.set_player(float(m[1]), float(m[2]))
                d = sc.exports_sync.drain()
                for e in d["ev"]:
                    fh.write(json.dumps(e) + "\n")
                    s = e.get("s") or {}
                    if e["k"] == "TRACE":
                        print(f"{time.strftime('%H:%M:%S')} TRACE {e['m']} ours={e['ours']} a0={e['a0']} a1={e.get('a1')}", flush=True)
                        continue
                    print(f"{time.strftime('%H:%M:%S')} {e['k']} {s.get('type', '')} enc={s.get('enc', '')} dist={s.get('dist', '')}m "
                          f"fort={str(s.get('fort'))[:12]} despawn_in={round((s.get('despawn', 0) - time.time() * 1000) / 60000, 1) if s.get('despawn') else ''}min "
                          f"{json.dumps({k: v for k, v in e['r'].items() if k != 'full'}) if e.get('r') else ''}{e.get('e', '')}", flush=True)
                if d.get("apples") and d["apples"] != last_apples:   # the GAME's own item counts
                    if last_apples:
                        delta = {k: v - last_apples.get(k, 0) for k, v in d["apples"].items() if v != last_apples.get(k, 0)}
                        print(f"{time.strftime('%H:%M:%S')} APPLES in bag {d['apples']} (change {delta})", flush=True)
                    else:
                        print(f"{time.strftime('%H:%M:%S')} APPLES in bag {d['apples']}", flush=True)
                    fh.write(json.dumps({"t": int(time.time() * 1000), "k": "apples", "counts": d["apples"]}) + "\n")
                    last_apples = dict(d["apples"])
                if time.time() - last_stat >= 30:
                    last_stat = time.time()
                    print(f"{time.strftime('%H:%M:%S')} stats {d['stats']} candidates {d['cand']}", flush=True)
                fh.flush()
                time.sleep(1)
        finally:
            try:
                sc.unload()
                sess.detach()
            except Exception:
                pass


if __name__ == "__main__":
    main()

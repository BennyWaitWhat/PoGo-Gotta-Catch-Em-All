"""READ-ONLY observer for map tappables (the event "apples"): hooks only, never calls a game method.

  python tools/tappable_observer.py MINUTES [OUT.jsonl]

Logs, per event: DynamicTappableController / DynamicTappablesService / DynamicTappablesSession method calls (with
the controller's Data fields: Type, Id...), MapContentHandler wild-tappable adds/updates, and the collect RPC
(ProcessTappableProto request fields when serialized, ProcessTappableOutProto reply fields when parsed).
Field reads are raw memory reads by the metadata offsets; class lookups use il2cpp_class_from_name (no class walks).
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import pogo_il2cpp as pg  # noqa: E402

DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")   # cloud: the Tailscale bridge exports ADB_TARGET
JS = r"""
var PS = Process.pointerSize, PROP = {exceptions: 'propagate'}, EX = {};
Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function (e) { if (e.name.indexOf('il2cpp_') === 0) EX[e.name] = e.address; });
function nf(n, r, a) { return new NativeFunction(EX[n], r, a, PROP); }
var IL = {
  domain: nf('il2cpp_domain_get', 'pointer', []), asms: nf('il2cpp_domain_get_assemblies', 'pointer', ['pointer', 'pointer']),
  asmImage: nf('il2cpp_assembly_get_image', 'pointer', ['pointer']), imageName: nf('il2cpp_image_get_name', 'pointer', ['pointer']),
  fromName: nf('il2cpp_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']),
  methods: nf('il2cpp_class_get_methods', 'pointer', ['pointer', 'pointer']), mName: nf('il2cpp_method_get_name', 'pointer', ['pointer']),
  mArgs: nf('il2cpp_method_get_param_count', 'uint32', ['pointer']),
  fields: nf('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']), fName: nf('il2cpp_field_get_name', 'pointer', ['pointer']),
  fOff: nf('il2cpp_field_get_offset', 'uint32', ['pointer']), fType: nf('il2cpp_field_get_type', 'pointer', ['pointer']),
  tType: nf('il2cpp_type_get_type', 'int', ['pointer']), fFlags: nf('il2cpp_field_get_flags', 'int', ['pointer']),
  cName: nf('il2cpp_class_get_name', 'pointer', ['pointer']), parent: nf('il2cpp_class_get_parent', 'pointer', ['pointer'])
};
function cs(p) { try { return p.isNull() ? '' : p.readCString(); } catch (e) { return '?'; } }
var IMAGES = null;
function images() { if (IMAGES) return IMAGES; IMAGES = []; var sp = Memory.alloc(8), a = IL.asms(IL.domain(), sp), n = sp.readS32();
  for (var i = 0; i < n; i++) { var im = IL.asmImage(a.add(i * PS).readPointer()); IMAGES.push([cs(IL.imageName(im)), im]); } return IMAGES; }
function cls(ns, name) { var a = Memory.allocUtf8String(ns), b = Memory.allocUtf8String(name), im = images();
  for (var i = 0; i < im.length; i++) { var k = IL.fromName(im[i][1], a, b); if (!k.isNull()) return k; } return null; }
var FIELDS = {};
function fieldsOf(k) {   /* instance fields incl. parents: [{name, off, te}] */
  var key = k.toString(); if (FIELDS[key]) return FIELDS[key]; var out = [];
  for (var c = k; c && !c.isNull(); c = IL.parent(c)) { var it = Memory.alloc(PS); it.writePointer(NULL); var f;
    while ((f = IL.fields(c, it)) && !f.isNull()) { if (IL.fFlags(f) & 0x10) continue;  /* static */
      out.push({name: cs(IL.fName(f)), off: IL.fOff(f), te: IL.tType(IL.fType(f))}); } }
  return (FIELDS[key] = out);
}
function str(p) { try { if (p.isNull()) return null; var n = p.add(0x10).readS32(); return (n >= 0 && n < 400) ? p.add(0x14).readUtf16String(n) : '<len ' + n + '>'; } catch (e) { return '<bad>'; } }
function klassName(o) { try { return o.isNull() ? null : cs(IL.cName(o.readPointer())); } catch (e) { return '?'; } }
function val(p, te) {
  switch (te) { case 0x02: return p.readU8() !== 0; case 0x04: return p.readS8(); case 0x05: return p.readU8(); case 0x06: return p.readS16();
    case 0x07: return p.readU16(); case 0x08: return p.readS32(); case 0x09: return p.readU32(); case 0x0a: return p.readS64().toString();
    case 0x0b: return p.readU64().toString(); case 0x0c: return p.readFloat(); case 0x0d: return p.readDouble(); case 0x0e: return str(p.readPointer());
    case 0x11: return p.readS32();   /* valuetype: enums are int-sized in these classes; structs read as their first int */
    case 0x12: case 0x15: case 0x1d: case 0x14: case 0x1c: var o = p.readPointer(); if (o.isNull()) return null; var kn = klassName(o);
      return kn === 'String' ? str(o) : '<' + kn + ' ' + o + '>'; }
  return '<te ' + te + '>';
}
function dump(o, depth) {   /* instance fields of object o (depth 1 follows object fields one level) */
  var out = {}; if (!o || o.isNull()) return null; var k = o.readPointer(); out._class = cs(IL.cName(k));
  fieldsOf(k).forEach(function (f) { try { var v = val(o.add(f.off), f.te); out[f.name] = v;
      if (depth > 0 && f.te === 0x15 && v && typeof v === 'string' && v.indexOf('<List`1') === 0) {
        var L = o.add(f.off).readPointer(), arr = L.add(0x10).readPointer(), n = L.add(0x18).readS32(), items = [];
        for (var i = 0; i < Math.min(n, 25); i++) { var el = arr.add(0x20 + i * PS).readPointer(); items.push(el.isNull() ? null : dump(el, depth - 1)); }
        out[f.name + '[]'] = {count: n, items: items};
      }
      if (depth > 0 && f.te === 0x15 && v && typeof v === 'string' && v.indexOf('<Dictionary`2') === 0) {
        var D = o.add(f.off).readPointer(); out[f.name + '{}'] = {count: D.add(0x20).readS32()};
      }
      if (depth > 0 && (f.te === 0x12 || f.te === 0x1c) && v && typeof v === 'string' && v.indexOf('<') === 0) {
        var inner = o.add(f.off).readPointer(); var cn = klassName(inner);
        if (cn && cn.indexOf('Action') < 0 && cn.indexOf('Func') < 0 && cn.indexOf('Transform') < 0 && cn.indexOf('GameObject') < 0)
          out[f.name + '.'] = dump(inner, depth - 1); } } catch (e) { out[f.name] = '<err>'; } });
  return out;
}
var CNT = {}, EV = [], SKIP = ['Update', 'LateUpdate', 'FixedUpdate', 'OnGUI', 'OnDestroy', 'Awake', 'Start', 'OnEnable', 'OnDisable', 'Equals', 'GetHashCode', 'ToString', '.ctor', '.cctor', 'CalculateSize', 'Clone', 'Finalize'];
function listMethods(k) { var out = [], it = Memory.alloc(PS); it.writePointer(NULL); var m;
  while ((m = IL.methods(k, it)) && !m.isNull()) out.push([m, cs(IL.mName(m)), IL.mArgs(m)]); return out; }
function hookAll(k, label, pick, onLeaveDump) {
  var n = 0; listMethods(k).forEach(function (x) { var m = x[0], nm = x[1], argc = x[2];
    if (!pick(nm, argc)) return; var fp = m.readPointer(); if (fp.isNull()) return;
    try { Interceptor.attach(fp, {
      onEnter: function (a) { this.s = a[0]; this.a1 = argc > 0 ? a[1] : null; },
      onLeave: function () { try { var ck = label + '.' + nm; CNT[ck] = (CNT[ck] || 0) + 1; if (CNT[ck] > 60) return;   /* rate limit per method */
          var e = {t: Date.now(), k: label, m: nm, argc: argc, self: this.s.toString()};
          if (onLeaveDump) e.d = onLeaveDump(this.s, this.a1, nm); EV.push(e); } catch (err) { EV.push({t: Date.now(), k: 'err', e: String(err)}); } } }); n++; }
    catch (err) { EV.push({t: Date.now(), k: 'hookerr', m: label + '.' + nm, e: String(err)}); } });
  return n;
}
rpc.exports = {
  install: function () {
    var st = {};
    var ctl = cls('', 'DynamicTappableController'), dat = cls('', 'DynamicTappableData');
    var svc = cls('Niantic.Holoholo.Services.DynamicTappables', 'DynamicTappablesService');
    var ses = cls('Niantic.Holoholo.Services.DynamicTappables', 'DynamicTappablesSession');
    var beh = cls('Niantic.Holoholo.Services.DynamicTappables', 'DynamicTappableBehaviorService');
    var mch = cls('Niantic.Holoholo.Map', 'MapContentHandler');
    var req = cls('Holoholo.Rpc', 'ProcessTappableProto'), rsp = cls('Holoholo.Rpc', 'ProcessTappableOutProto');
    var tap = cls('Holoholo.Rpc', 'Tappable'), enc = cls('Holoholo.Rpc', 'TappableEncounterProto');
    st.found = {ctl: !!ctl, dat: !!dat, svc: !!svc, ses: !!ses, beh: !!beh, mch: !!mch, req: !!req, rsp: !!rsp, tap: !!tap, enc: !!enc};
    st.fields = {};
    [['DynamicTappableController', ctl], ['DynamicTappableData', dat], ['ProcessTappableProto', req], ['ProcessTappableOutProto', rsp],
     ['Tappable', tap], ['TappableEncounterProto', enc]].forEach(function (x) { if (x[1]) st.fields[x[0]] = fieldsOf(x[1]).map(function (f) { return f.name + '@' + f.off.toString(16) + ':' + f.te.toString(16); }); });
    st.methods = {};
    [['DynamicTappableController', ctl], ['DynamicTappablesService', svc], ['DynamicTappablesSession', ses], ['DynamicTappableBehaviorService', beh]].forEach(function (x) {
      if (x[1]) st.methods[x[0]] = listMethods(x[1]).map(function (m) { return m[1] + '/' + m[2]; }); });
    if (mch) st.methods.MapContentHandler_tappable = listMethods(mch).filter(function (m) { return m[1].indexOf('appable') >= 0; }).map(function (m) { return m[1] + '/' + m[2]; });
    var notHot = function (nm, argc) { return SKIP.indexOf(nm) < 0 && nm.indexOf('get_') !== 0 && nm.indexOf('set_') !== 0 && nm.indexOf('<') !== 0; };
    st.hooks = {};
    if (ctl) st.hooks.ctl = hookAll(ctl, 'CTL', notHot, function (s, a1, nm) { return (nm === 'Init' || nm === 'Refresh' || nm.indexOf('Tap') >= 0) ? dump(s, 1) : null; });
    if (ctl) { var SEEN = {}, calls = 0, GETS = [];
      listMethods(ctl).forEach(function (x) { if (['get_Id', 'get_Position', 'get_VisibleOnMap', 'get_TypeKey', 'get_AssetKey', 'get_IsEncounter', 'get_DespawnTimeMs'].indexOf(x[1]) < 0) return;
        var fp = x[0].readPointer(); if (!fp.isNull()) GETS.push([x[1], fp]); });
      /* CENSUS ROUND: attach the per-frame getters for 5 s, dump every controller seen (key = pointer + Id, pooled
         controllers get reused), detach. Repeats every 45 s so tappables that spawn later are caught too. */
      var round = function () { var LS = [], c0 = calls;
        GETS.forEach(function (g) { LS.push(Interceptor.attach(g[1], {onEnter: function (a) { calls++;
          var id = -1; try { id = a[0].add(0xcc).readS32(); } catch (e) {} var k = a[0].toString() + '#' + id; if (SEEN[k]) return; SEEN[k] = 1;
          try { EV.push({t: Date.now(), k: 'LIVE', m: g[0], self: k, d: dump(a[0], 1)}); } catch (err) { EV.push({t: Date.now(), k: 'err', e: String(err)}); } }})); });
        setTimeout(function () { LS.forEach(function (l) { l.detach(); }); EV.push({t: Date.now(), k: 'CENSUS', calls: calls - c0, unique_total: Object.keys(SEEN).length}); }, 5000); };
      round(); setInterval(round, 45000); st.hooks.census = GETS.length; }
    var ONCE = {};
    var sesDump = function (s, a1, nm) { var key = 'ses' + s; if (ONCE[key]) return null; ONCE[key] = 1; return dump(s, 2); };
    if (svc) st.hooks.svc = hookAll(svc, 'SVC', notHot, sesDump);
    if (ses) st.hooks.ses = hookAll(ses, 'SES', notHot, sesDump);
    if (beh) st.hooks.beh = hookAll(beh, 'BEH', notHot, null);
    if (mch) st.hooks.mch = hookAll(mch, 'MAP', function (nm) { return nm.indexOf('appable') >= 0 && nm.indexOf('get_') !== 0; }, null);
    if (req) st.hooks.req = hookAll(req, 'REQ', function (nm, argc) { return nm === 'WriteTo' && argc === 1; }, function (s) { return dump(s, 1); });
    if (rsp) st.hooks.rsp = hookAll(rsp, 'RSP', function (nm, argc) { return argc === 1 && ['WriteTo', 'Equals', '.ctor', 'CalculateSize'].indexOf(nm) < 0; }, function (s) { return dump(s, 1); });
    return st;
  },
  drain: function () { var e = EV; EV = []; return e; },
  counts: function () { return CNT; }
};
"""


def adb(cmd):
    return subprocess.run(["adb", "-s", DEV, "shell", cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout or ""


def main():
    arg = sys.argv[1]
    if ":" in arg:   # run until a wall-clock time today, e.g. 17:30
        hh, mm = (int(x) for x in arg.split(":"))
        lt = time.localtime()
        minutes = (time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, 0, 0, 0, -1)) - time.time()) / 60
    else:
        minutes = float(arg)
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(HERE), "system", "analysis", "tappable_observe.jsonl")
    if "Pixel" not in adb("getprop ro.product.model"):
        sys.exit("not the phone")
    sess, pid = pg.get_session()
    sc = sess.create_script(JS)
    sc.load()
    st = sc.exports_sync.install()
    print(f"attached pid {pid}; found {st['found']}; hooks {st['hooks']}", flush=True)
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": int(time.time() * 1000), "k": "install", "st": st}) + "\n")
        t0, seen, last_pos = time.time(), {}, 0
        try:
            while time.time() - t0 < minutes * 60:
                for e in sc.exports_sync.drain():
                    fh.write(json.dumps(e) + "\n")
                    key = e["k"] + "." + str(e.get("m"))
                    seen[key] = seen.get(key, 0) + 1
                    if seen[key] <= 3 or e["k"] in ("REQ", "RSP", "err", "hookerr", "LIVE", "CENSUS") or e.get("m") in ("Initialize", "Refresh", "Tapped", "AddTappable", "AddTappables", "TapTappable", "ProcessTappableTapped", "RegisterTappableRevealed"):
                        d = e.get("d") or {}
                        keep = ("_class", "Type", "<Id>k__BackingField", "Id", "Status", "Result", "TappableTypeId", "EncounterId", "Reward",
                                "<TypeKey>k__BackingField", "<AssetKey>k__BackingField", "<IsEncounter>k__BackingField",
                                "<DespawnTimeMs>k__BackingField", "<EncounterId>k__BackingField", "calls", "unique_total")
                        brief = {k.replace("k__BackingField", "").strip("<>"): v for k, v in d.items() if k in keep} if isinstance(d, dict) else d
                        if e["k"] == "CENSUS":
                            brief = {"calls": e.get("calls"), "unique_total": e.get("unique_total")}
                        print(f"{time.strftime('%H:%M:%S')} {key} {json.dumps(brief)[:300]}", flush=True)
                if time.time() - last_pos >= 10:   # player position (joystick mock fix) for tap-range / despawn context
                    last_pos = time.time()
                    m = re.search(r"gps ([-0-9.]+),([-0-9.]+) .*?vel=([0-9.]+)", adb("dumpsys location | grep -m1 'last mock location'"))
                    if m:
                        fh.write(json.dumps({"t": int(time.time() * 1000), "k": "pos", "lat": float(m[1]), "lng": float(m[2]),
                                             "kmh": round(float(m[3]) * 3.6, 1)}) + "\n")
                fh.flush()
                time.sleep(1)
        finally:
            try:
                sc.unload()
                sess.detach()
            except Exception:
                pass
    print("counts:", json.dumps(seen), flush=True)


if __name__ == "__main__":
    main()

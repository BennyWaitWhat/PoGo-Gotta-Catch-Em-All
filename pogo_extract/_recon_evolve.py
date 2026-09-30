"""RECON: locate IL2CPP classes for candy/currency/evolution-branch reading.
READ ONLY. Dumps class fields + method names so we can find the right accessors."""
import frida, sys, time, json
sys.path.insert(0, '.')
import pogo_il2cpp as pg
sys.stdout.reconfigure(line_buffering=True)

RECON_JS = r"""
function imgByName(name) {
    _ensureInit();
    var sp = Memory.alloc(4);
    var asms = IL2.dGA(IL2.dG(), sp);
    var na = sp.readS32();
    for (var a = 0; a < na; a++) {
        var img = IL2.aGI(asms.add(a * Process.pointerSize).readPointer());
        if (IL2.iGN(img).readCString() === name) return img;
    }
    return null;
}

function clsFromImg(img, ns, name) {
    return IL2.cFN(img, Memory.allocUtf8String(ns), Memory.allocUtf8String(name));
}

// bind extra introspection exports
var _cGF = null, _fGN = null, _fGO = null, _fGT = null, _tGN = null, _cGNs2 = null, _cGNm2 = null, _mGpc = null, _mGrt=null;
function _ensureIntro() {
    _ensureInit();
    if (_cGF) return;
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {};
    il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name]=e.address; });
    function b(n,r,a){ return exp[n] ? new NativeFunction(exp[n],r,a) : null; }
    _cGF = b('il2cpp_class_get_fields','pointer',['pointer','pointer']);
    _fGN = b('il2cpp_field_get_name','pointer',['pointer']);
    _fGO = b('il2cpp_field_get_offset','uint32',['pointer']);
    _fGT = b('il2cpp_field_get_type','pointer',['pointer']);
    _tGN = b('il2cpp_type_get_name','pointer',['pointer']);
    _cGNm2 = b('il2cpp_method_get_param_count','uint32',['pointer']);
    _mGrt = b('il2cpp_method_get_return_type','pointer',['pointer']);
}

function dumpFields(klass) {
    _ensureIntro();
    var out = [];
    if (!_cGF) return out;
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var f;
    while ((f = _cGF(klass, iter)) && !f.isNull()) {
        var nm = _fGN(f).readCString();
        var off = _fGO(f);
        var tn = '';
        try { var t = _fGT(f); if (t && !t.isNull()) tn = _tGN(t).readCString(); } catch(e){}
        out.push({name: nm, offset: off, type: tn});
    }
    return out;
}

function dumpMethods(klass) {
    _ensureIntro();
    var out = [];
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    while ((m = IL2.cGM(klass, iter)) && !m.isNull()) {
        var nm = IL2.mGN(m).readCString();
        var pc = _cGNm2 ? _cGNm2(m) : -1;
        var rt = '';
        try { var t = _mGrt(m); if (t && !t.isNull()) rt = _tGN(t).readCString(); } catch(e){}
        out.push({name: nm, params: pc, ret: rt});
    }
    return out;
}

rpc.exports.probeClass = function(img, ns, name) {
    _ensureInit();
    var i = imgByName(img);
    if (!i || i.isNull()) return {err: 'no image ' + img};
    var k = clsFromImg(i, ns, name);
    if (!k || k.isNull()) return {err: 'class not found: ' + ns + '.' + name + ' in ' + img};
    return {ok:true, klass: k.toString(), fields: dumpFields(k), methods: dumpMethods(k)};
};

rpc.exports.livenessClass = function(img, ns, name) {
    _ensureInit();
    var i = imgByName(img);
    if (!i || i.isNull()) return {err: 'no image ' + img};
    var k = clsFromImg(i, ns, name);
    if (!k || k.isNull()) return {err: 'class not found: ' + ns + '.' + name};
    return liveness_find_instances(k);
};
"""

def main():
    for attempt in range(8):
        try:
            sess, pid = pg.get_session()
            print(f"attached pid={pid}")
            sc = pg.get_script_with_helpers(sess, RECON_JS)
            sc.exports_sync.init()

            # Candidate classes to probe across images.
            # img, ns, class
            candidates = [
                # Inventory cache / candy
                ('holo-game.dll', 'Niantic.Holoholo.Internal', 'NianticInventoryCache'),
                ('holo-game.dll', 'Niantic.Platform.Inventory', 'NianticInventoryCache'),
                ('holo-game.dll', 'Niantic.Holoholo.Internal', 'PokemonInventoryImpl'),
                ('holo-game.dll', 'Niantic.Holoholo.Internal', 'CandyInventoryImpl'),
                ('holo-game.dll', 'Niantic.Holoholo.Internal', 'PlayerProfileImpl'),
                ('holo-game.dll', 'Niantic.Holoholo.Internal', 'PlayerCurrencyImpl'),
                ('holo-game.dll', 'Niantic.Holoholo.Internal', 'ItemInventoryImpl'),
                # Game master / templates / evolution
                ('holo-game.dll', 'Niantic.Holoholo.Internal', 'GameMasterImpl'),
                ('holo-game.dll', 'Niantic.Holoholo.Internal', 'MasterTemplateServiceImpl'),
                ('holo-game.dll', 'Niantic.Holoholo.Internal', 'TemplateServiceImpl'),
                ('holo-protos.dll', 'Holoholo.Rpc', 'PokemonSettingsProto'),
                ('holo-protos.dll', 'Holoholo.Rpc', 'EvolutionBranchProto'),
                ('holo-protos.dll', 'Holoholo.Rpc', 'PlayerCurrencyProto'),
                ('holo-protos.dll', 'Holoholo.Rpc', 'PokemonFamilyProto'),
                ('holo-protos.dll', 'Holoholo.Rpc', 'CandyProto'),
            ]
            results = {}
            for img, ns, name in candidates:
                try:
                    r = sc.exports_sync.probe_class(img, ns, name)
                    key = f"{img}|{ns}.{name}"
                    if r.get('ok'):
                        results[key] = {'klass': r['klass'],
                                        'n_fields': len(r['fields']),
                                        'n_methods': len(r['methods']),
                                        'fields': r['fields'],
                                        'methods': [m for m in r['methods']]}
                        print(f"FOUND {key}  fields={len(r['fields'])} methods={len(r['methods'])}")
                    else:
                        print(f"  miss {key}: {r.get('err')}")
                except Exception as e:
                    print(f"  err  {img}|{ns}.{name}: {e}")
            json.dump(results, open('_recon_evolve_out.json', 'w'), indent=2)
            print("\nwrote _recon_evolve_out.json")
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()

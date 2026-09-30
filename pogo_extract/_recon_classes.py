"""RECON 2: enumerate all class names in holo-game.dll (and holo-protos.dll) matching
keywords, so we can find the candy inventory, currency, and game master/template singletons.
READ ONLY."""
import frida, sys, time, json
sys.path.insert(0, '.')
import pogo_il2cpp as pg
sys.stdout.reconfigure(line_buffering=True)

RECON_JS = r"""
var _iGCC=null,_iGC=null,_cGNm=null,_cGNs=null;
function _ensureIntro() {
    _ensureInit();
    if (_iGCC) return;
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {};
    il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name]=e.address; });
    function b(n,r,a){ return exp[n] ? new NativeFunction(exp[n],r,a) : null; }
    _iGCC = b('il2cpp_image_get_class_count','uint32',['pointer']);
    _iGC  = b('il2cpp_image_get_class','pointer',['pointer','size_t']);
    _cGNm = b('il2cpp_class_get_name','pointer',['pointer']);
    _cGNs = b('il2cpp_class_get_namespace','pointer',['pointer']);
}
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

rpc.exports.enumClasses = function(imgName, keywords) {
    _ensureIntro();
    var img = imgByName(imgName);
    if (!img || img.isNull()) return {err:'no image '+imgName};
    if (!_iGCC || !_iGC) return {err:'class enum API not exported'};
    var n = _iGCC(img);
    var kws = keywords.map(function(k){ return k.toLowerCase(); });
    var out = [];
    for (var i = 0; i < n; i++) {
        var k = _iGC(img, i);
        if (k.isNull()) continue;
        var nm = _cGNm(k).readCString() || '';
        var ns = '';
        try { var nsp = _cGNs(k); if (nsp && !nsp.isNull()) ns = nsp.readCString() || ''; } catch(e){}
        var low = (ns + '.' + nm).toLowerCase();
        for (var j = 0; j < kws.length; j++) {
            if (low.indexOf(kws[j]) !== -1) { out.push({ns: ns, name: nm}); break; }
        }
    }
    return {ok:true, count: n, matches: out};
};
"""

def main():
    for attempt in range(8):
        try:
            sess, pid = pg.get_session()
            print(f"attached pid={pid}")
            sc = pg.get_script_with_helpers(sess, RECON_JS)
            sc.exports_sync.init()
            kws = ['candy', 'currency', 'stardust', 'gimmighoul', 'gamemaster', 'template',
                   'inventory', 'pokemonfamily', 'masterdata', 'evolution', 'settingsstore',
                   'pokemonsettings', 'itemtemplate', 'coin']
            out = {}
            for img in ['holo-game.dll', 'holo-protos.dll']:
                r = sc.exports_sync.enum_classes(img, kws)
                if r.get('ok'):
                    out[img] = r['matches']
                    print(f"\n=== {img} ({r['count']} classes, {len(r['matches'])} matches) ===")
                    for m in r['matches']:
                        print(f"  {m['ns']}.{m['name']}")
                else:
                    print(f"{img}: {r.get('err')}")
            json.dump(out, open('_recon_classes_out.json','w'), indent=2)
            print("\nwrote _recon_classes_out.json")
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()

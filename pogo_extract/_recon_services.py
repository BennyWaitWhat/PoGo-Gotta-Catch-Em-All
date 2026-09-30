"""RECON 3: dump methods+fields of the candidate service/enum classes.
READ ONLY. Reuses probeClass from _recon_evolve approach but for the service layer."""
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
var _cGF=null,_fGN=null,_fGO=null,_fGT=null,_tGN=null,_mGpc=null,_mGrt=null,_cGNm=null;
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
    _mGpc = b('il2cpp_method_get_param_count','uint32',['pointer']);
    _mGrt = b('il2cpp_method_get_return_type','pointer',['pointer']);
}
function dumpFields(klass) {
    _ensureIntro(); var out=[]; if(!_cGF) return out;
    var iter=Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0)); var f;
    while ((f=_cGF(klass,iter)) && !f.isNull()) {
        var nm=_fGN(f).readCString(); var off=_fGO(f); var tn='';
        try{var t=_fGT(f); if(t&&!t.isNull()) tn=_tGN(t).readCString();}catch(e){}
        out.push({name:nm, offset:off, type:tn});
    }
    return out;
}
function dumpMethods(klass) {
    _ensureIntro(); var out=[];
    var iter=Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0)); var m;
    while ((m=IL2.cGM(klass,iter)) && !m.isNull()) {
        var nm=IL2.mGN(m).readCString(); var pc=_mGpc?_mGpc(m):-1; var rt='';
        try{var t=_mGrt(m); if(t&&!t.isNull()) rt=_tGN(t).readCString();}catch(e){}
        out.push({name:nm, params:pc, ret:rt});
    }
    return out;
}
rpc.exports.probe = function(img, ns, name) {
    _ensureInit();
    var i = imgByName(img);
    if (!i || i.isNull()) return {err:'no image '+img};
    var k = IL2.cFN(i, Memory.allocUtf8String(ns), Memory.allocUtf8String(name));
    if (!k || k.isNull()) return {err:'not found: '+ns+'.'+name};
    return {ok:true, klass:k.toString(), fields:dumpFields(k), methods:dumpMethods(k)};
};
"""

TARGETS = [
    ('holo-game.dll', 'Niantic.Holoholo', 'GameMasterDataService'),
    ('holo-game.dll', 'Niantic.Holoholo', 'IGameMasterDataService'),
    ('holo-game.dll', 'Niantic.Holoholo.Services', 'PokemonFamilySettingsService'),
    ('holo-game.dll', 'Niantic.Holoholo.Services', 'IPokemonFamilySettingsService'),
    ('holo-game.dll', 'Niantic.Holoholo.Collections', 'InventoryCache'),
    ('holo-game.dll', 'Niantic.Holoholo.Collections', 'IInventoryCache'),
    ('holo-game.dll', 'Niantic.Holoholo.Storefront', 'CurrencyType'),
    ('holo-game.dll', 'Niantic.Holoholo.Util', 'EvolutionBranchProtoExt'),
    ('holo-game.dll', 'Niantic.Holoholo.Util', 'ClientEvolutionQuestTemplateProtoExt'),
    ('holo-protos.dll', 'Holoholo.Rpc', 'EvolutionQuestInfoProto'),
    ('holo-protos.dll', 'Holoholo.Rpc', 'CurrencyQuantityProto'),
    ('holo-protos.dll', 'Holoholo.Rpc', 'PlayerStatsProto'),
    ('holo-protos.dll', 'Holoholo.Rpc', 'QuestEvolutionGlobalSettingsProto'),
    ('holo-protos.dll', 'Holoholo.Rpc', 'PokemonFamilySettingsProto'),
]

def main():
    for attempt in range(8):
        try:
            sess, pid = pg.get_session()
            print(f"attached pid={pid}")
            sc = pg.get_script_with_helpers(sess, RECON_JS)
            sc.exports_sync.init()
            out = {}
            for img, ns, name in TARGETS:
                r = sc.exports_sync.probe(img, ns, name)
                key = f"{ns}.{name}"
                if r.get('ok'):
                    out[key] = {'klass': r['klass'], 'fields': r['fields'], 'methods': r['methods']}
                    print(f"\n### {key}  ({len(r['fields'])}f / {len(r['methods'])}m) klass={r['klass']}")
                    # print fields
                    for f in r['fields']:
                        print(f"   F {f['offset']:>4} {f['name']:<34} {f['type']}")
                    # print getter/interesting methods only
                    for m in r['methods']:
                        nm = m['name']
                        if (nm.startswith('get_') or nm.startswith('Get') or nm.startswith('Try')
                                or 'Candy' in nm or 'Currency' in nm or 'Stardust' in nm
                                or 'Settings' in nm or 'Family' in nm or 'Evolution' in nm
                                or 'Coin' in nm or 'Quantity' in nm or 'Quest' in nm):
                            print(f"   M {nm}({m['params']}) -> {m['ret']}")
                else:
                    print(f"  miss {key}: {r.get('err')}")
            json.dump(out, open('_recon_services_out.json','w'), indent=2)
            print("\nwrote _recon_services_out.json")
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()

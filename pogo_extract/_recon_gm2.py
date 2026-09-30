"""RECON 4: GameMaster data accessors + inventory item proto types. READ ONLY."""
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
var _cGF=null,_fGN=null,_fGO=null,_fGT=null,_tGN=null,_mGpc=null,_mGrt=null;
function _ensureIntro() {
    _ensureInit(); if(_cGF) return;
    var il2cpp=Process.findModuleByName('libil2cpp.so'); var exp={};
    il2cpp.enumerateExports().forEach(function(e){ if(e.name.indexOf('il2cpp_')===0) exp[e.name]=e.address; });
    function b(n,r,a){ return exp[n]?new NativeFunction(exp[n],r,a):null; }
    _cGF=b('il2cpp_class_get_fields','pointer',['pointer','pointer']);
    _fGN=b('il2cpp_field_get_name','pointer',['pointer']);
    _fGO=b('il2cpp_field_get_offset','uint32',['pointer']);
    _fGT=b('il2cpp_field_get_type','pointer',['pointer']);
    _tGN=b('il2cpp_type_get_name','pointer',['pointer']);
    _mGpc=b('il2cpp_method_get_param_count','uint32',['pointer']);
    _mGrt=b('il2cpp_method_get_return_type','pointer',['pointer']);
}
function dF(k){_ensureIntro();var o=[];if(!_cGF)return o;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
  while((f=_cGF(k,it))&&!f.isNull()){var n=_fGN(f).readCString();var of=_fGO(f);var t='';try{var tt=_fGT(f);if(tt&&!tt.isNull())t=_tGN(tt).readCString();}catch(e){}o.push({name:n,offset:of,type:t});}return o;}
function dM(k){_ensureIntro();var o=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
  while((m=IL2.cGM(k,it))&&!m.isNull()){var n=IL2.mGN(m).readCString();var p=_mGpc?_mGpc(m):-1;var r='';try{var tt=_mGrt(m);if(tt&&!tt.isNull())r=_tGN(tt).readCString();}catch(e){}o.push({name:n,params:p,ret:r});}return o;}
rpc.exports.probe=function(img,ns,name){_ensureInit();var i=imgByName(img);if(!i||i.isNull())return{err:'no image '+img};
  var k=IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));if(!k||k.isNull())return{err:'not found: '+ns+'.'+name};
  return{ok:true,klass:k.toString(),fields:dF(k),methods:dM(k)};};
"""

TARGETS = [
    ('holo-game.dll', '', 'PokemonSettings'),
    ('holo-game.dll', '', 'GameMasterData'),
    ('holo-game.dll', 'Niantic.Holoholo', 'IGameMasterData'),
    ('holo-game.dll', 'Niantic.Holoholo', 'GameMasterDataExt'),
    ('holo-protos.dll', 'Holoholo.Rpc', 'HoloInventoryItemProto'),
    ('holo-protos.dll', 'Holoholo.Rpc', 'HoloInventoryKeyProto'),
    ('holo-protos.dll', 'Holoholo.Rpc', 'CandyProto'),
    ('holo-protos.dll', 'Holoholo.Rpc', 'PlayerCandyProto'),
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
                key = f"{ns}.{name}".lstrip('.')
                if r.get('ok'):
                    out[key] = r
                    print(f"\n### {key} ({len(r['fields'])}f/{len(r['methods'])}m) klass={r['klass']}")
                    for f in r['fields']:
                        print(f"   F {f['offset']:>4} {f['name']:<32} {f['type']}")
                    for m in r['methods']:
                        nm=m['name']
                        if (nm.startswith('get_') or nm.startswith('Get') or nm.startswith('Try')
                                or 'Candy' in nm or 'Settings' in nm or 'Family' in nm
                                or 'Evolution' in nm or 'Pokemon' in nm or 'Stardust' in nm or 'Currency' in nm):
                            print(f"   M {nm}({m['params']}) -> {m['ret']}")
                else:
                    print(f"  miss {key}: {r.get('err')}")
            json.dump(out, open('_recon_gm2_out.json','w'), indent=2)
            print("\nwrote _recon_gm2_out.json")
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()

"""RECON 6: inventory cache internals - generic base fields, ClientInventoryItem layout,
and the runtime type of GetCurrentItems()'s return + how to enumerate it. READ ONLY."""
import frida, sys, time, json
sys.path.insert(0, '.')
import pogo_il2cpp as pg
sys.stdout.reconfigure(line_buffering=True)

JS = r"""
function imgByName(name){_ensureInit();var sp=Memory.alloc(4);var asms=IL2.dGA(IL2.dG(),sp);var na=sp.readS32();
  for(var a=0;a<na;a++){var img=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());if(IL2.iGN(img).readCString()===name)return img;}return null;}
function gmCls(ns,name){var i=imgByName('holo-game.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
var _oGC=null,_cGNm=null,_cGN2=null,_cGF=null,_fGN=null,_fGO=null,_fGT=null,_tGN=null;
function _ii(){_ensureInit();if(_oGC)return;var il=Process.findModuleByName('libil2cpp.so');var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  _oGC=b('il2cpp_object_get_class','pointer',['pointer']);
  _cGNm=b('il2cpp_class_get_name','pointer',['pointer']);
  _cGF=b('il2cpp_class_get_fields','pointer',['pointer','pointer']);
  _fGN=b('il2cpp_field_get_name','pointer',['pointer']);
  _fGO=b('il2cpp_field_get_offset','uint32',['pointer']);
  _fGT=b('il2cpp_field_get_type','pointer',['pointer']);
  _tGN=b('il2cpp_type_get_name','pointer',['pointer']);
}
function clsName(k){_ii();try{return _cGNm(k).readCString();}catch(e){return '?';}}
function objClsName(o){_ii();if(o.isNull())return 'null';try{return clsName(_oGC(o));}catch(e){return '?';}}
function dF(k){_ii();var o=[];if(!_cGF)return o;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
  while((f=_cGF(k,it))&&!f.isNull()){var n=_fGN(f).readCString();var of=_fGO(f);var t='';try{var tt=_fGT(f);if(tt&&!tt.isNull())t=_tGN(tt).readCString();}catch(e){}o.push({name:n,offset:of,type:t});}return o;}

rpc.exports.invfields = function(addr) {
    var k = gmCls('Niantic.Holoholo.Collections', 'InventoryCache');
    _ii();
    var instCls = _oGC(ptr(addr));
    var out = {instClass: clsName(instCls), fields: dF(instCls)};
    return out;
};

rpc.exports.collinfo = function(addr) {
    var k = gmCls('Niantic.Holoholo.Collections', 'InventoryCache');
    var m = cMN(k, 'GetCurrentItems', 0);
    var coll = rI(m, ptr(addr), ptr(0), null);
    if (coll.isNull()) return {err:'null'};
    _ii();
    var out = {collClass: objClsName(coll), collAddr: coll.toString()};
    // dump its fields
    out.fields = dF(_oGC(coll));
    return out;
};
"""

def main():
    for attempt in range(8):
        try:
            sess, pid = pg.get_session()
            print(f"attached pid={pid}")
            sc = pg.get_script_with_helpers(sess, JS)
            sc.exports_sync.init()
            hits = pg.find_singleton(sess, 'Niantic.Holoholo.Collections', 'InventoryCache')
            print(f"InventoryCache @ {hits}")
            fr = sc.exports_sync.invfields(hits)
            print(f"\ninstance class: {fr['instClass']}")
            for f in fr['fields']:
                print(f"  F {f['offset']:>4} {f['name']:<30} {f['type']}")
            ci = sc.exports_sync.collinfo(hits)
            print(f"\nGetCurrentItems collClass={ci.get('collClass')} addr={ci.get('collAddr')}")
            for f in ci.get('fields', []):
                print(f"  C {f['offset']:>4} {f['name']:<30} {f['type']}")
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()

"""Decode Item enum names (confirm 1150=Gimmighoul Coin) and locate stardust.
Search holo-game.dll for Player/Currency singletons exposing stardust/pokecoin getters.
READ ONLY."""
import frida, sys, time, json
sys.path.insert(0, '.')
import pogo_il2cpp as pg
sys.stdout.reconfigure(line_buffering=True)

JS = r"""
function imgByName(name){_ensureInit();var sp=Memory.alloc(4);var asms=IL2.dGA(IL2.dG(),sp);var na=sp.readS32();
  for(var a=0;a<na;a++){var img=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());if(IL2.iGN(img).readCString()===name)return img;}return null;}
function gmCls(ns,name){var i=imgByName('holo-game.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
function protoCls(ns,name){var i=imgByName('holo-protos.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
var _cGF=null,_fGN=null,_fGT=null,_tGN=null,_fGV=null,_iGCC=null,_iGC=null,_cGNm=null,_cGNs=null,_cGM=null,_mGN=null,_mGpc=null,_mGrt=null;
function _ii(){_ensureInit();if(_cGF)return;var il=Process.findModuleByName('libil2cpp.so');var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  _cGF=b('il2cpp_class_get_fields','pointer',['pointer','pointer']);_fGN=b('il2cpp_field_get_name','pointer',['pointer']);
  _fGT=b('il2cpp_field_get_type','pointer',['pointer']);_tGN=b('il2cpp_type_get_name','pointer',['pointer']);
  _fGV=b('il2cpp_field_static_get_value','void',['pointer','pointer']);
  _iGCC=b('il2cpp_image_get_class_count','uint32',['pointer']);_iGC=b('il2cpp_image_get_class','pointer',['pointer','size_t']);
  _cGNm=b('il2cpp_class_get_name','pointer',['pointer']);_cGNs=b('il2cpp_class_get_namespace','pointer',['pointer']);
  _mGpc=b('il2cpp_method_get_param_count','uint32',['pointer']);_mGrt=b('il2cpp_method_get_return_type','pointer',['pointer']);}

// Decode an enum: read each literal static field's int value.
rpc.exports.enumValues = function(img, ns, name, wantVals){
    _ii();
    var i=imgByName(img);var k=IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));
    if(!k||k.isNull())return{err:'no class'};
    var want={};for(var x=0;x<wantVals.length;x++)want[wantVals[x]]=true;
    var out={};var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
    var buf=Memory.alloc(8);
    while((f=_cGF(k,it))&&!f.isNull()){
        var nm=_fGN(f).readCString();if(nm==='value__')continue;
        try{_fGV(f,buf);var v=buf.readS32();if(want[v])out[v]=nm;}catch(e){}
    }
    return {ok:true, map:out};
};

// Enumerate holo-game.dll classes whose name matches kw and that have a get_* method
// returning Int32/Int64 with 'Stardust'/'Dust'/'Pokecoin'/'Coin'/'Currency' in name.
rpc.exports.findCurrencyGetters = function(kws){
    _ii();
    var img=imgByName('holo-game.dll');var n=_iGCC(img);
    var lk=kws.map(function(s){return s.toLowerCase();});
    var hits=[];
    for(var i=0;i<n;i++){var k=_iGC(img,i);if(k.isNull())continue;
        var cn=_cGNm(k).readCString()||'';var ns='';try{var nsp=_cGNs(k);if(nsp&&!nsp.isNull())ns=nsp.readCString()||'';}catch(e){}
        var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
        while((m=IL2.cGM(k,it))&&!m.isNull()){
            var mn=IL2.mGN(m).readCString()||'';var lm=mn.toLowerCase();
            for(var j=0;j<lk.length;j++){
                if(lm.indexOf(lk[j])!==-1 && (mn.indexOf('get_')===0||mn.indexOf('Get')===0)){
                    var rt='';try{var t=_mGrt(m);if(t&&!t.isNull())rt=_tGN(t).readCString();}catch(e){}
                    hits.push({cls:(ns?ns+'.':'')+cn, method:mn, params:_mGpc?_mGpc(m):-1, ret:rt});
                    break;
                }
            }
        }
    }
    return {ok:true, hits:hits};
};
"""

def main():
    for attempt in range(8):
        try:
            sess, pid = pg.get_session()
            print(f"attached pid={pid}")
            sc = pg.get_script_with_helpers(sess, JS)
            sc.exports_sync.init()
            # Decode Item enum 1150-1155
            ev = sc.exports_sync.enum_values('holo-protos.dll', 'Holoholo.Rpc', 'Item',
                                             [1150,1151,1152,1153,1154,1155,1,2,3])
            print("=== Item enum names ===")
            print(json.dumps(ev, indent=2))
            # Find currency/stardust getters
            cg = sc.exports_sync.find_currency_getters(['stardust','pokecoin','currency'])
            print("\n=== Currency getters in holo-game.dll ===")
            for h in cg.get('hits', []):
                # only show plausible value-returning getters
                if h['ret'] in ('System.Int32','System.Int64') or 'Currenc' in h['ret'] or 'Long' in h['ret']:
                    print(f"  {h['cls']}::{h['method']}({h['params']}) -> {h['ret']}")
            json.dump({'items':ev,'currencyGetters':cg}, open('_items_stardust_out.json','w'), indent=2)
            print("\n(full list in _items_stardust_out.json)")
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()

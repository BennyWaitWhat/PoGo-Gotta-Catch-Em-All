"""Confirm Item 1150 localized name via live i18n + read stardust via IapService.
READ ONLY."""
import frida, sys, time, json
sys.path.insert(0, '.')
import pogo_il2cpp as pg
sys.stdout.reconfigure(line_buffering=True)

JS = r"""
function imgByName(name){_ensureInit();var sp=Memory.alloc(4);var asms=IL2.dGA(IL2.dG(),sp);var na=sp.readS32();
  for(var a=0;a<na;a++){var img=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());if(IL2.iGN(img).readCString()===name)return img;}return null;}
function gmCls(ns,name){var i=imgByName('holo-game.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
var _oGC=null,_cGNm=null,_mGpc=null;
function _ii(){_ensureInit();if(_oGC)return;var il=Process.findModuleByName('libil2cpp.so');var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  _oGC=b('il2cpp_object_get_class','pointer',['pointer']);_cGNm=b('il2cpp_class_get_name','pointer',['pointer']);
  _mGpc=b('il2cpp_method_get_param_count','uint32',['pointer']);}
function objCls(o){_ii();if(o.isNull())return 'null';try{return _cGNm(_oGC(o)).readCString();}catch(e){return '?';}}
function readStr(p){if(p.isNull())return null;var len=p.add(0x10).readS32();if(len<0||len>1000)return null;var s='';for(var i=0;i<len;i++)s+=String.fromCharCode(p.add(0x14+i*2).readU16());return s;}

// liveness for game class
rpc.exports.live = function(ns,name){var k=gmCls(ns,name);if(k.isNull())return{err:'no class '+ns+'.'+name};return liveness_find_instances(k);};

// Call IapService.get_Stardusts() on a candidate (unbox int)
rpc.exports.stardust = function(addr){
    var k=gmCls('Niantic.Holoholo.Storefront','IapService');
    var m=cMN(k,'get_Stardusts',0);
    try{var r=rI(m,ptr(addr),ptr(0),null);if(r.isNull())return{err:'null'};return{ok:true, stardust:r.add(0x10).readS32()};}
    catch(e){return{err:'threw '+e};}
};
rpc.exports.pokecoins = function(addr){
    var k=gmCls('Niantic.Holoholo.Storefront','IapService');
    // try get_Pokecoins / get_NumPokecoin variants
    var names=['get_Pokecoins','get_PokeCoins','get_NumPokecoin','get_Coins','get_PokecoinBalance'];
    var out={};
    for(var i=0;i<names.length;i++){var m=cMN(k,names[i],0);if(!m)continue;
        try{var r=rI(m,ptr(addr),ptr(0),null);if(!r.isNull())out[names[i]]=r.add(0x10).readS32();}catch(e){}}
    return out;
};

// i18n: find II18nService, call a localized-string getter for an item.
// Try GameMasterData / II18nService translate of 'item_other_evolution_stone_a' and similar.
rpc.exports.i18nProbe = function(i18nAddr, keys){
    var k=gmCls('Niantic.Holoholo.Internationalization','I18nService');
    var out={};
    // find a method taking 1 string -> string (Translate/GetText/Localize)
    var cand=[];
    var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
    while((m=IL2.cGM(k,it))&&!m.isNull()){var mn=IL2.mGN(m).readCString()||'';_ii();
        if((_mGpc?_mGpc(m):0)===1 && /translate|gettext|localize|getstring|text/i.test(mn)) cand.push([mn,m]);}
    out._candidates=cand.map(function(c){return c[0];});
    for(var ki=0;ki<keys.length;ki++){
        var kbuf=Memory.allocUtf8String(keys[ki]);
        // build managed string
        for(var ci=0;ci<cand.length;ci++){
            try{
                var sarg=IL2.alloc?null:null;
            }catch(e){}
        }
    }
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
            # IapService
            r = sc.exports_sync.live('Niantic.Holoholo.Storefront', 'IapService')
            print(f"IapService: {r if 'err' in r else r.get('hits')}")
            if not r.get('err') and r.get('hits'):
                for h in r['hits'][:5]:
                    sd = sc.exports_sync.stardust(h)
                    pc = sc.exports_sync.pokecoins(h)
                    print(f"  {h}: stardust={sd} pokecoins={pc}")
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()

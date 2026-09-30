"""Dump ClientInventoryItem layout + the PlayerStats / PlayerCurrency items to locate
stardust + currencies. READ ONLY."""
import frida, sys, time, json
sys.path.insert(0, '.')
import pogo_il2cpp as pg
sys.stdout.reconfigure(line_buffering=True)

JS = r"""
function imgByName(name){_ensureInit();var sp=Memory.alloc(4);var asms=IL2.dGA(IL2.dG(),sp);var na=sp.readS32();
  for(var a=0;a<na;a++){var img=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());if(IL2.iGN(img).readCString()===name)return img;}return null;}
function gmCls(ns,name){var i=imgByName('holo-game.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
function protoCls(ns,name){var i=imgByName('holo-protos.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
var _oGC=null,_cGNm=null,_cGF=null,_fGN=null,_fGO=null,_fGT=null,_tGN=null;
function _ii(){_ensureInit();if(_oGC)return;var il=Process.findModuleByName('libil2cpp.so');var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  _oGC=b('il2cpp_object_get_class','pointer',['pointer']);_cGNm=b('il2cpp_class_get_name','pointer',['pointer']);
  _cGF=b('il2cpp_class_get_fields','pointer',['pointer','pointer']);_fGN=b('il2cpp_field_get_name','pointer',['pointer']);
  _fGO=b('il2cpp_field_get_offset','uint32',['pointer']);_fGT=b('il2cpp_field_get_type','pointer',['pointer']);
  _tGN=b('il2cpp_type_get_name','pointer',['pointer']);}
function objCls(o){_ii();if(o.isNull())return 'null';try{return _cGNm(_oGC(o)).readCString();}catch(e){return '?';}}
function dFobj(o){_ii();if(o.isNull())return [];var k=_oGC(o);var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
  while((f=_cGF(k,it))&&!f.isNull()){var n=_fGN(f).readCString();var of=_fGO(f);var t='';try{var tt=_fGT(f);if(tt&&!tt.isNull())t=_tGN(tt).readCString();}catch(e){}out.push({name:n,offset:of,type:t});}return out;}
function readStr(p){if(p.isNull())return '';var len=p.add(0x10).readS32();if(len<=0||len>400)return '';var s='';for(var i=0;i<len;i++)s+=String.fromCharCode(p.add(0x14+i*2).readU16());return s;}

function getDict(invAddr){var k=gmCls('Niantic.Holoholo.Collections','InventoryCache');var m=cMN(k,'GetCurrentItems',0);
  var coll=rI(m,ptr(invAddr),ptr(0),null);if(coll.isNull())return null;return coll.add(0x10).readPointer();}
function walk(dict,cb){var en=dict.add(0x18).readPointer();if(en.isNull())return 0;var c=en.add(0x18).readS32();
  var base=en.add(0x20);var n=0;for(var i=0;i<c;i++){var e=base.add(i*0x18);if(e.readS32()<0)continue;
    var key=e.add(8).readPointer();var val=e.add(0x10).readPointer();if(key.isNull())continue;if(cb(key,val,i)===false)return n;n++;}return n;}

rpc.exports.clientItemLayout = function(invAddr, targetCase) {
    var dict = getDict(invAddr);
    var res = null;
    walk(dict, function(key, val){
        if (key.add(24).readS32() !== targetCase) return true;
        var info = {cls: objCls(val), fields: dFobj(val)};
        // dump pointer words 0x10..0x40
        var words=[];
        for (var o=0x10;o<0x48;o+=8){var p=val.add(o).readPointer();words.push(o.toString(16)+'='+p.toString()+'('+objCls(p)+')');}
        info.words = words;
        res = info; return false;
    });
    return res || {none:true};
};

// Read PlayerStats item fully: find the HoloInventoryItemProto, call get_PlayerStats.
rpc.exports.readPlayerStats = function(invAddr) {
    var dict = getDict(invAddr);
    var itemCls = protoCls('Holoholo.Rpc','HoloInventoryItemProto');
    var statsM = cMN(itemCls,'get_PlayerStats',0);
    var res=null;
    walk(dict, function(key,val){
        if (key.add(24).readS32() !== 4) return true; // PlayerStats
        // find inv item proto pointer in client item
        var item=ptr(0);
        for(var o=0x10;o<=0x40;o+=8){var p=val.add(o).readPointer();if(!p.isNull()&&objCls(p)==='HoloInventoryItemProto'){item=p;break;}}
        if(item.isNull()){res={err:'no item proto in client wrapper', clientCls:objCls(val)};return false;}
        var stats;
        try{ stats=rI(statsM,item,ptr(0),null);}catch(e){res={err:'get_PlayerStats threw '+e};return false;}
        if(stats.isNull()){res={err:'null stats'};return false;}
        // dump every int field offset 16..432 looking for plausible stardust (large number)
        var allWords=[];
        for(var o=16;o<=432;o+=4) allWords.push(o+'='+stats.add(o).readS32());
        res={ok:true, statsCls:objCls(stats), level:stats.add(16).readS32(), words:allWords};
        return false;
    });
    return res||{none:true};
};
"""

def main():
    for attempt in range(8):
        try:
            sess, pid = pg.get_session()
            print(f"attached pid={pid}")
            sc = pg.get_script_with_helpers(sess, JS)
            sc.exports_sync.init()
            inv = pg.find_singleton(sess, 'Niantic.Holoholo.Collections', 'InventoryCache')
            for tc, nm in [(4,'PlayerStats'),(5,'PlayerCurrency')]:
                info = sc.exports_sync.client_item_layout(inv, tc)
                print(f"\n=== case {tc} ({nm}) ClientInventoryItem layout ===")
                print(json.dumps(info, indent=2))
            ps = sc.exports_sync.read_player_stats(inv)
            print(f"\n=== PlayerStats values ===")
            print(json.dumps(ps, indent=2))
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()

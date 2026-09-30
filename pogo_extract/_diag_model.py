"""Dump ClientItemModel layout -> locate HoloInventoryItemProto. Then read candy
for the 3 families end-to-end. READ ONLY."""
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
  _fGO=b('il2cpp_field_get_offset','uint32',['pointer']);_fGT=b('il2cpp_field_get_type','pointer',['pointer']);_tGN=b('il2cpp_type_get_name','pointer',['pointer']);}
function objCls(o){_ii();if(o.isNull())return 'null';try{return _cGNm(_oGC(o)).readCString();}catch(e){return '?';}}
function dFobj(o){_ii();if(o.isNull())return [];var k=_oGC(o);var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
  while((f=_cGF(k,it))&&!f.isNull()){var n=_fGN(f).readCString();var of=_fGO(f);var t='';try{var tt=_fGT(f);if(tt&&!tt.isNull())t=_tGN(tt).readCString();}catch(e){}out.push({name:n,offset:of,type:t});}return out;}

function getDict(invAddr){var k=gmCls('Niantic.Holoholo.Collections','InventoryCache');var m=cMN(k,'GetCurrentItems',0);
  var coll=rI(m,ptr(invAddr),ptr(0),null);if(coll.isNull())return null;return coll.add(0x10).readPointer();}
function walk(dict,cb){var en=dict.add(0x18).readPointer();if(en.isNull())return 0;var c=en.add(0x18).readS32();
  var base=en.add(0x20);var n=0;for(var i=0;i<c;i++){var e=base.add(i*0x18);if(e.readS32()<0)continue;
    var key=e.add(8).readPointer();var val=e.add(0x10).readPointer();if(key.isNull())continue;if(cb(key,val,i)===false)return n;n++;}return n;}

// resolve the HoloInventoryItemProto from a ClientInventoryItem via serverState/clientPrediction ClientItemModel
function resolveItem(clientItem) {
    for (var base=0x10; base<=0x18; base+=0x8) {  // serverState then clientPrediction
        var model = clientItem.add(base).readPointer();
        if (model.isNull()) continue;
        // scan model fields for a HoloInventoryItemProto pointer
        for (var o=0x10;o<=0x40;o+=8){
            try{var p=model.add(o).readPointer();if(!p.isNull()&&objCls(p)==='HoloInventoryItemProto')return p;}catch(e){}
        }
    }
    return ptr(0);
}

rpc.exports.modelLayout = function(invAddr, targetCase) {
    var dict=getDict(invAddr);var res=null;
    walk(dict,function(key,val){
        if(key.add(24).readS32()!==targetCase)return true;
        var model=val.add(0x10).readPointer();
        var info={clientCls:objCls(val), modelCls:objCls(model), modelFields:dFobj(model)};
        var words=[];for(var o=0x10;o<0x48;o+=8){var p=model.add(o).readPointer();words.push(o.toString(16)+'='+p.toString()+'('+objCls(p)+')');}
        info.modelWords=words;
        res=info;return false;
    });
    return res||{none:true};
};

rpc.exports.candy = function(invAddr, wantFamilies){
    var dict=getDict(invAddr);if(!dict||dict.isNull())return{err:'no dict'};
    var itemCls=protoCls('Holoholo.Rpc','HoloInventoryItemProto');
    var famM=cMN(itemCls,'get_PokemonFamily',0);
    var want={};for(var i=0;i<wantFamilies.length;i++)want[wantFamilies[i]]=true;
    var found={};var seen=0;var matched=0;
    walk(dict,function(key,val){
        seen++;
        if(key.add(24).readS32()!==10)return true; // PokemonFamilyId
        // family id: key oneof object @ +16 is a boxed HoloPokemonFamilyId (int) OR direct int.
        // get_PokemonFamilyId (boxed) unbox @+0x10
        var famKeyId=null;
        var kHasM=cMN(protoCls('Holoholo.Rpc','HoloInventoryKeyProto'),'get_PokemonFamilyId',0);
        try{var r=rI(kHasM,key,ptr(0),null);if(!r.isNull())famKeyId=r.add(0x10).readS32();}catch(e){}
        if(famKeyId===null||!want[famKeyId])return true;
        matched++;
        var item=resolveItem(val);
        if(item.isNull()){found[famKeyId]={err:'no item'};return true;}
        var fam;try{fam=rI(famM,item,ptr(0),null);}catch(e){found[famKeyId]={err:'famthrew'};return true;}
        if(fam.isNull()){found[famKeyId]={err:'null fam'};return true;}
        found[famKeyId]={familyId:fam.add(16).readS32(), candy:fam.add(20).readS32(), xlCandy:fam.add(32).readS32()};
        return true;
    });
    return {ok:true, seen:seen, candyKeysMatched:matched, families:found};
};
"""

WANT = [824, 624, 999]

def main():
    for attempt in range(8):
        try:
            sess, pid = pg.get_session()
            print(f"attached pid={pid}")
            sc = pg.get_script_with_helpers(sess, JS)
            sc.exports_sync.init()
            inv = pg.find_singleton(sess, 'Niantic.Holoholo.Collections', 'InventoryCache')
            ml = sc.exports_sync.model_layout(inv, 10)  # a candy entry
            print("=== ClientItemModel layout (candy entry) ===")
            print(json.dumps(ml, indent=2))
            cr = sc.exports_sync.candy(inv, WANT)
            print("\n=== CANDY ===")
            print(json.dumps(cr, indent=2))
            json.dump(cr, open('_candy_out.json','w'), indent=2)
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()

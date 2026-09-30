"""Decode HoloInventoryKeyProto.TypeOneofCase enum values -> names, and inspect
the rare-case inventory items to find stardust + gimmighoul coin storage. READ ONLY."""
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
function dF(k){_ii();var o=[];if(!_cGF)return o;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
  while((f=_cGF(k,it))&&!f.isNull()){var n=_fGN(f).readCString();var of=_fGO(f);var t='';try{var tt=_fGT(f);if(tt&&!tt.isNull())t=_tGN(tt).readCString();}catch(e){}o.push({name:n,offset:of,type:t});}return o;}

// Decode the TypeOneofCase nested enum: enumerate its static literal fields.
rpc.exports.oneofEnum = function() {
    var k = protoCls('Holoholo.Rpc', 'HoloInventoryKeyProto/TypeOneofCase');
    if (!k || k.isNull()) k = protoCls('Holoholo.Rpc', 'HoloInventoryKeyProto.TypeOneofCase');
    if (!k || k.isNull()) return {err:'no TypeOneofCase class'};
    var flds = dF(k);
    // enum literals are static; value lives in the field's default - we can't read const easily,
    // but field name + the int we already match by position. Instead, list names.
    return {ok:true, fields: flds.map(function(f){return f.name;})};
};

function getDict(invAddr){var k=gmCls('Niantic.Holoholo.Collections','InventoryCache');var m=cMN(k,'GetCurrentItems',0);
  var coll=rI(m,ptr(invAddr),ptr(0),null);if(coll.isNull())return null;return coll.add(0x10).readPointer();}
function walk(dict,cb){var en=dict.add(0x18).readPointer();if(en.isNull())return 0;var c=en.add(0x18).readS32();
  var base=en.add(0x20);var n=0;for(var i=0;i<c;i++){var e=base.add(i*0x18);if(e.readS32()<0)continue;
    var key=e.add(8).readPointer();var val=e.add(0x10).readPointer();if(key.isNull())continue;if(cb(key,val,i)===false)return n;n++;}return n;}
function findInvItem(ci){if(ci.isNull())return ptr(0);for(var o=0x10;o<=0x30;o+=8){try{var p=ci.add(o).readPointer();if(!p.isNull()&&objCls(p)==='HoloInventoryItemProto')return p;}catch(e){}}return ptr(0);}

// For a given target oneof case, dump 1 example: the inventory item value class + which getter is populated.
rpc.exports.inspectCase = function(invAddr, targetCase) {
    var dict = getDict(invAddr);
    var itemCls = protoCls('Holoholo.Rpc', 'HoloInventoryItemProto');
    var result = null;
    walk(dict, function(key, val, idx){
        var fc = key.add(24).readS32();
        if (fc !== targetCase) return true;
        var item = findInvItem(val);
        var info = {oneofCase: fc, clientItemCls: objCls(val), invItemCls: objCls(item)};
        if (!item.isNull()) {
            // item value oneof: cozu(object)@16, cozv(TypeOneofCase)@24
            info.itemTypeCase = item.add(24).readS32();
            info.itemOneofObjCls = objCls(item.add(16).readPointer());
            // dump first 0x40 bytes of the item-oneof object as candidate ints
            var inner = item.add(16).readPointer();
            if (!inner.isNull()) {
                var words = [];
                for (var o=0x10;o<0x40;o+=4) words.push(o.toString(16)+'='+inner.add(o).readS32());
                info.innerWords = words;
            }
        }
        // also dump key inner object words (the oneof value, e.g. currency type string)
        var kinner = key.add(16).readPointer();
        if (!kinner.isNull()) {
            info.keyInnerCls = objCls(kinner);
        }
        result = info;
        return false; // stop after first
    });
    return result || {none:true, targetCase: targetCase};
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
            en = sc.exports_sync.oneof_enum()
            print(f"TypeOneofCase enum fields: {en}")
            # Inspect the rare/interesting cases: 6 (PlayerStats?), and any single-instance ones
            # From histogram: cases 4,7,8,9,11,13,14,15,19,24,25,28,29,30,33,34,35,38,39,40,41 are rare.
            for tc in [6, 7, 8, 9, 11, 13, 14, 15, 19, 24, 28, 29, 30, 38, 39, 40, 41]:
                info = sc.exports_sync.inspect_case(inv, tc)
                print(f"\ncase {tc}: {json.dumps(info)}")
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()

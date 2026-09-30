"""Diagnose HoloInventoryKeyProto reading: TypeOneofCase via field@+24 vs method (boxed).
Find which entries are PokemonFamily keys and read candy. READ ONLY."""
import frida, sys, time, json
sys.path.insert(0, '.')
import pogo_il2cpp as pg
sys.stdout.reconfigure(line_buffering=True)

JS = r"""
function imgByName(name){_ensureInit();var sp=Memory.alloc(4);var asms=IL2.dGA(IL2.dG(),sp);var na=sp.readS32();
  for(var a=0;a<na;a++){var img=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());if(IL2.iGN(img).readCString()===name)return img;}return null;}
function gmCls(ns,name){var i=imgByName('holo-game.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
function protoCls(ns,name){var i=imgByName('holo-protos.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
var _oGC=null,_cGNm=null;
function _ii(){_ensureInit();if(_oGC)return;var il=Process.findModuleByName('libil2cpp.so');var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  _oGC=b('il2cpp_object_get_class','pointer',['pointer']);
  _cGNm=b('il2cpp_class_get_name','pointer',['pointer']);}
function objCls(o){_ii();if(o.isNull())return 'null';try{return _cGNm(_oGC(o)).readCString();}catch(e){return '?';}}

function getDict(invAddr){var k=gmCls('Niantic.Holoholo.Collections','InventoryCache');var m=cMN(k,'GetCurrentItems',0);
  var coll=rI(m,ptr(invAddr),ptr(0),null);if(coll.isNull())return null;return coll.add(0x10).readPointer();}
function walk(dict,cb){var en=dict.add(0x18).readPointer();if(en.isNull())return 0;var c=en.add(0x18).readS32();
  var base=en.add(0x20);var n=0;for(var i=0;i<c;i++){var e=base.add(i*0x18);if(e.readS32()<0)continue;
    var key=e.add(8).readPointer();var val=e.add(0x10).readPointer();if(key.isNull())continue;cb(key,val);n++;}return n;}

// Method-based unboxed read: runtime_invoke returns boxed value -> read int @ +0x10
function callIntUnbox(klass, key, mname) {
    var m = cMN(klass, mname, 0);
    try { var r = rI(m, key, ptr(0), null); if (r.isNull()) return null; return r.add(0x10).readS32(); }
    catch(e){ return null; }
}
function callBoolUnbox(klass, key, mname) {
    var m = cMN(klass, mname, 0);
    try { var r = rI(m, key, ptr(0), null); if (r.isNull()) return null; return r.add(0x10).readU8(); }
    catch(e){ return null; }
}

rpc.exports.sample = function(invAddr) {
    var dict = getDict(invAddr);
    var keyCls = protoCls('Holoholo.Rpc', 'HoloInventoryKeyProto');
    var rows = [];
    var count = 0;
    var seenOneof = {};
    walk(dict, function(key, val){
        count++;
        // field read: TypeOneofCase @ +24, oneof object @ +16
        var fieldCase = key.add(24).readS32();
        seenOneof[fieldCase] = (seenOneof[fieldCase]||0)+1;
        if (count <= 12) {
            rows.push({
                fieldCase: fieldCase,
                methodCase: callIntUnbox(keyCls, key, 'get_TypeCase'),
                hasFamily_method: callBoolUnbox(keyCls, key, 'get_HasPokemonFamilyId'),
                familyId_method: callIntUnbox(keyCls, key, 'get_PokemonFamilyId'),
            });
        }
    });
    return {count: count, sampleRows: rows, oneofHistogram: seenOneof};
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
            r = sc.exports_sync.sample(inv)
            print(f"count={r['count']}")
            print(f"oneof histogram (fieldCase @ +24): {json.dumps(r['oneofHistogram'], indent=2)}")
            print("sample rows:")
            for row in r['sampleRows']:
                print(f"  {row}")
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()

"""Diagnose the inventory Dictionary entry layout: dump raw entries and the
runtime classes of key/value objects so we can fix offsets. READ ONLY."""
import frida, sys, time, json
sys.path.insert(0, '.')
import pogo_il2cpp as pg
sys.stdout.reconfigure(line_buffering=True)

JS = r"""
function imgByName(name){_ensureInit();var sp=Memory.alloc(4);var asms=IL2.dGA(IL2.dG(),sp);var na=sp.readS32();
  for(var a=0;a<na;a++){var img=IL2.aGI(asms.add(a*Process.pointerSize).readPointer());if(IL2.iGN(img).readCString()===name)return img;}return null;}
function gmCls(ns,name){var i=imgByName('holo-game.dll');return IL2.cFN(i,Memory.allocUtf8String(ns),Memory.allocUtf8String(name));}
var _oGC=null,_cGNm=null,_cGNs=null;
function _ii(){_ensureInit();if(_oGC)return;var il=Process.findModuleByName('libil2cpp.so');var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  _oGC=b('il2cpp_object_get_class','pointer',['pointer']);
  _cGNm=b('il2cpp_class_get_name','pointer',['pointer']);
  _cGNs=b('il2cpp_class_get_namespace','pointer',['pointer']);}
function objCls(o){_ii();if(o.isNull())return 'null';try{return _cGNm(_oGC(o)).readCString();}catch(e){return '?:'+e;}}

rpc.exports.dump = function(invAddr) {
    var k = gmCls('Niantic.Holoholo.Collections', 'InventoryCache');
    var m = cMN(k, 'GetCurrentItems', 0);
    var coll = rI(m, ptr(invAddr), ptr(0), null);
    var collClass = objCls(coll);
    var dict = coll.add(0x10).readPointer();
    var dictClass = objCls(dict);
    // Dump dict header words 0..0x40
    var hdr = [];
    for (var o=0;o<0x48;o+=8) hdr.push(o.toString(16)+'='+dict.add(o).readPointer().toString());
    // entries candidate at 0x18
    var entries = dict.add(0x18).readPointer();
    var entriesClass = objCls(entries);
    // managed array: length @ +0x18 (count) ; data @ +0x20
    var arrLen = entries.isNull()? -1 : entries.add(0x18).readS32();
    // Try strides 0x18, 0x20, 0x28; dump first 6 entries' key/value classes
    var probes = {};
    [0x18,0x20,0x28].forEach(function(stride){
        var rows=[];
        var base = entries.add(0x20);
        for (var i=0;i<8;i++){
            var e=base.add(i*stride);
            var hash=e.readS32(); var next=e.add(4).readS32();
            var key=e.add(0x8).readPointer(); var val=e.add(0x10).readPointer();
            rows.push({i:i, hash:hash, next:next,
                       keyCls: (key.isNull()?'null':objCls(key)),
                       valCls: (val.isNull()?'null':objCls(val))});
        }
        probes['stride_0x'+stride.toString(16)] = rows;
    });
    return {collClass:collClass, dictClass:dictClass, dictHdr:hdr, entriesClass:entriesClass, arrLen:arrLen, probes:probes};
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
            r = sc.exports_sync.dump(inv)
            print(json.dumps(r, indent=2))
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()

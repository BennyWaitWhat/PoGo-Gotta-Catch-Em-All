"""GROUND-TRUTH pass 4 (decisive). READ-ONLY.
- Re-read live IapService stardust (the non-zero instance).
- Scan EVERY InventoryCache entry holder for any int32 in [stardust*0.5 .. stardust*3] and
  also any LARGE int (>100000) -- to locate the server-synced currency field and check whether
  a ~700k value still lives anywhere in the synced bag (would mean server still has it).
One attach.
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function mInv(m,obj){var h=H_();var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,ptr(0),exc);if(!exc.readPointer().isNull())return null;return r;}
function cname(o){try{return H_().CGN(H_().OGC(ptr(o))).readCString();}catch(e){return null;}}

rpc.exports.clsName=function(inst){return cname(inst);};
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.readI=function(inst,name){var h=H_();var m=h.cMN(h.OGC(ptr(inst)),Memory.allocUtf8String(name),0);if(!m||m.isNull())return null;var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,ptr(inst),ptr(0),exc);if(!exc.readPointer().isNull())return null;try{return r?r.add(0x10).readS32():null;}catch(e){return null;}};

// Scan inventory holders for int32 in [lo,hi] OR > big. For each match, record holder class,
// key-case, offset, value. This locates the currency field by VALUE without knowing the proto layout.
rpc.exports.scanInts=function(invAddr,lo,hi,big){var h=H_();var inv=ptr(invAddr);
 var icls=h.cFN(img("holo-game.dll"),Memory.allocUtf8String("Niantic.Holoholo.Collections"),Memory.allocUtf8String("InventoryCache"));
 var m=h.cMN(icls,Memory.allocUtf8String("GetCurrentItems"),0);if(!m||m.isNull())return {err:"no GetCurrentItems"};
 var coll=mInv(m,inv);if(!coll||coll.isNull())return {err:"null coll"};
 var dict=coll.add(0x10).readPointer();if(dict.isNull())return {err:"null dict"};
 var entries=dict.add(0x18).readPointer();if(entries.isNull())return {err:"null entries"};
 var count=entries.add(0x18).readS32();var rng=[];var bigs=[];
 for(var i=0;i<count;i++){var e=entries.add(0x20).add(i*0x18);var hash=e.add(0x0).readS32();if(hash<0)continue;
  var key=e.add(0x8).readPointer();var val=e.add(0x10).readPointer();if(key.isNull()||val.isNull())continue;
  var kcase=-1;try{kcase=key.add(0x18).readS32();}catch(e){}
  var cn=cname(val);
  // scan first 0x60 bytes of the holder value object as int32s
  for(var o=0x10;o<=0x5c;o+=4){var v;try{v=val.add(o).readS32();}catch(e){break;}
    if(v>=lo&&v<=hi){rng.push({case:kcase,cls:cn,off:o,val:v});}
    if(v>=big){bigs.push({case:kcase,cls:cn,off:o,val:v});}}
 }
 return {count:count, inRange:rng.slice(0,40), bigVals:bigs.slice(0,40)};};
"""


def main():
    sess, pid = pg.get_session()
    print("attached pid", pid)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        r = finder.exports_sync.find_singleton("Niantic.Holoholo.Storefront", "IapService")
        live = None
        for h in (r.get("hits", []) if isinstance(r, dict) else []):
            if sc.exports_sync.cls_name(h) != "IapService":
                continue
            v = sc.exports_sync.read_i(h, "get_Stardusts")
            if v and v > 0:
                live = (h, v)
        print(f"live IapService stardust: {live}")
        cur = live[1] if live else 47000
        lo, hi = int(cur * 0.5), int(cur * 3)
        big = 200000
        print(f"scanning InventoryCache holders for int in [{lo}..{hi}] and any > {big} ...")

        ic_r = finder.exports_sync.find_singleton("Niantic.Holoholo.Collections", "InventoryCache")
        for h in (ic_r.get("hits", []) if isinstance(ic_r, dict) else []):
            res = sc.exports_sync.scan_ints(h, lo, hi, big)
            if isinstance(res, dict) and res.get("err"):
                print(f"   {h}: ERR {res['err']}"); continue
            print(f"   {h}: entries={res.get('count')}")
            print(f"   --- ints in [{lo}..{hi}] (currency-magnitude candidates) ---")
            for x in res.get("inRange", []):
                print(f"      case{x['case']:>3} {x['cls']} @{hex(x['off'])} = {x['val']}")
            print(f"   --- LARGE ints > {big} (would a ~700k value survive here?) ---")
            for x in res.get("bigVals", []):
                print(f"      case{x['case']:>3} {x['cls']} @{hex(x['off'])} = {x['val']}")
            if not res.get("bigVals"):
                print("      (none — NO large ~700k value present anywhere in the synced bag)")
    finally:
        try:
            sc.unload(); finder.unload()
        except Exception:
            pass
        try:
            sess.detach()
        except Exception:
            pass


main()

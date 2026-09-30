"""Print current stardust (max-value IapService instance) + box count. READ-ONLY. For A/B dust measurement."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.readI=function(inst,name){var h=H_();var m=h.cMN(h.OGC(ptr(inst)),Memory.allocUtf8String(name),0);if(!m||m.isNull())return null;var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,ptr(inst),ptr(0),exc);if(!exc.readPointer().isNull())return null;try{return r?r.add(0x10).readS32():null;}catch(e){return null;}};
"""


def find_max(sc, finder, cls, getter):
    ns = sc.exports_sync.ns_of(cls)
    if not ns:
        return None
    r = finder.exports_sync.find_singleton(ns, cls)
    best = None; bestv = None
    for h in (r.get("hits", []) if isinstance(r, dict) else []):
        if sc.exports_sync.cls_name(h) != cls:
            continue
        v = sc.exports_sync.read_i(h, getter)
        if v is not None and (bestv is None or v > bestv):
            best = h; bestv = v
    return best


def main():
    sess, pid = pg.get_session()
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    iap = find_max(sc, finder, "IapService", "get_Stardusts")
    pb = find_max(sc, finder, "PokemonBagImpl", "get_PokemonOnlyCount")
    d = sc.exports_sync.read_i(iap, "get_Stardusts") if iap else None
    b = sc.exports_sync.read_i(pb, "get_PokemonOnlyCount") if pb else None
    print(f"STARDUST={d} BOX={b}")
    sess.detach()


main()

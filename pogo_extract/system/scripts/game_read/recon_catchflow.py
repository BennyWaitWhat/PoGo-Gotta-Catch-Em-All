"""RECON (READ-ONLY): read the ACTUAL catch-flow internals to find the real reason/logical gap
behind the att=1 "flees" (incl. the p=1.0 contradiction) — NOT infer "soft-ban".
Dumps full field schemas of CatchPokemonProto (request), CatchPokemonOutProto (response),
CaptureProbabilityProto (how prob is structured), and lists every Capture/Catch/Score/Reason
class + the OutProto's nested Types (Status/Reason enums). Static metadata read. Catcher STOPPED."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
rpc.exports.listClasses=function(rx,image){var h=H_();var im=img(image);if(!im)return [];var re=new RegExp(rx,"i");var cnt=h.iGCC(im);var out=[];for(var i=0;i<cnt&&out.length<120;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(re.test(nm))out.push((h.CGNS(k).readCString()||"")+"."+nm);}catch(e){}}return out;};
rpc.exports.dump=function(name,image){var h=H_();var k=findClass(image,name);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()&&out.length<160){try{var nm=h.mGN(m).readCString();var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(nm+" ("+h.mGPC(m)+") -> "+rt);}catch(e){}}return out;};
rpc.exports.fields=function(name,image){var h=H_();var k=findClass(image,name);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.cGF(k,it))&&!f.isNull()&&out.length<80){try{var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}out.push("+0x"+h.fGO(f).toString(16)+" "+h.fGN(f).readCString()+" : "+tn);}catch(e){}}return out;};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        for cls, img_ in [("CatchPokemonProto", "holo-protos.dll"),
                          ("CatchPokemonOutProto", "holo-protos.dll"),
                          ("CaptureProbabilityProto", "holo-protos.dll"),
                          ("CaptureScoreProto", "holo-protos.dll"),
                          ("PokeballThrow", "holo-game.dll")]:
            fl = sc.exports_sync.fields(cls, img_)
            print(f"\n--- {cls} [{img_}] fields ---")
            for x in (fl or ["(class not found)"]):
                print("   ", x)
        print("\n== Capture/Catch/Score/Reason classes in holo-protos.dll ==")
        for c in sorted(set((sc.exports_sync.list_classes("Capture|Catch|CatchScore|Reason", "holo-protos.dll") or []))):
            print("   ", c)
        print("\n--- CatchPokemonOutProto methods (getters reveal nested fields) ---")
        for m in (sc.exports_sync.dump("CatchPokemonOutProto", "holo-protos.dll") or []):
            if m.startswith("get_") or "Status" in m or "Reason" in m or "Score" in m or "Capture" in m or "Miss" in m or "Award" in m:
                print("   ", m)
    finally:
        try:
            sc.unload()
        except Exception:
            pass
        try:
            sess.detach()
        except Exception:
            pass


main()

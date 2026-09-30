"""RECON (READ-ONLY): map the catch-award protos so we can read per-catch stardust breakdown.
Dumps CatchPokemonOutProto + CaptureAward (and any Stardust-multiplier/boost classes). Touches nothing."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
rpc.exports.listClasses=function(rx,imageName){var h=H_();var im=img(imageName||"holo-protos.dll");if(!im)return [];var re=new RegExp(rx,"i");var cnt=h.iGCC(im);var out=[];for(var i=0;i<cnt&&out.length<300;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(re.test(nm))out.push((h.CGNS(k).readCString()||"")+"."+nm);}catch(e){}}return out;};
rpc.exports.dump=function(name,imageName){var h=H_();var im=img(imageName||"holo-protos.dll");if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var kk=h.iGC(im,i);if(kk.isNull())continue;var cn;try{cn=h.CGN(kk).readCString();}catch(e){continue;}if(cn!==name)continue;var ms=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(kk,it))&&!m.isNull()&&ms.length<150){try{var nm=h.mGN(m).readCString();var argc=h.mGPC(m);var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}ms.push(nm+" ("+argc+") -> "+rt);}catch(e){}}return {ns:h.CGNS(kk).readCString(),methods:ms};}return null;};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        for rx in ["CaptureAward", "CatchPokemonOutProto", "Stardust", "WeatherBonus", "Boosted"]:
            for image in ["holo-protos.dll", "holo-game.dll"]:
                cl = sc.exports_sync.list_classes(rx, image)
                if cl:
                    print(f"\n== {image} /{rx}/ ==")
                    for c in sorted(set(cl)):
                        print("   ", c)
        for cls in ["CatchPokemonOutProto", "CaptureAward"]:
            r = sc.exports_sync.dump(cls, "holo-protos.dll")
            print(f"\n--- {cls} [{(r or {}).get('ns')}] ---")
            for m in ((r or {}).get("methods") or []):
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

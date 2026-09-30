"""#2 RECON 3 (READ-ONLY): the PokeballThrow struct shape + how to read a spawn's encounterId
(WildMapPokemon/MapPokemon), to finish arming the Ultra auto-catcher."""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return k;}catch(e){}}return null;}
rpc.exports.fields=function(imageName,clsName){var h=H_();var k=findClass(imageName,clsName);if(!k)return {err:"no "+clsName};var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;var out=[];while((f=h.cGF(k,it))&&!f.isNull()){try{out.push(h.fGN(f).readCString()+"@0x"+h.fGO(f).toString(16)+":"+h.tGN(h.fGT(f)).readCString());}catch(e){}}return {cls:clsName, fields:out};};
rpc.exports.getters=function(imageName,clsName){var h=H_();var k=findClass(imageName,clsName);if(!k)return {err:"no "+clsName};var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;var out=[];while((m=h.cGM(k,it))&&!m.isNull()){try{var nm=h.mGN(m).readCString();if(nm.indexOf("get_")===0||nm.toLowerCase().indexOf("encounter")>=0||nm.toLowerCase().indexOf("id")>=0){var rt="";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(nm+"("+h.mGPC(m)+") -> "+rt);}}catch(e){}}return {cls:clsName, methods:out};};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        for cls in ["PokeballThrow"]:
            r = sc.exports_sync.fields("holo-game.dll", cls)
            print(f"\n== {cls} fields ==")
            print(json.dumps(r, indent=2))
        for cls in ["WildMapPokemon", "MapPokemon"]:
            r = sc.exports_sync.getters("holo-game.dll", cls)
            print(f"\n== {cls} getters/id methods ==")
            if isinstance(r, dict) and r.get("methods"):
                for m in r["methods"]:
                    print("  ", m)
            else:
                print("  ", r)
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

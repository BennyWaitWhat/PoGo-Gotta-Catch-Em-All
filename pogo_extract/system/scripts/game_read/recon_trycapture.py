"""Confirm the UI-FREE catch entry: WildMapPokemon.TryCapture(...) + list all Capture/Encounter/Try
methods on WildMapPokemon / MapPokemon with full signatures. READ-ONLY."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),mGP:b("il2cpp_method_get_param","pointer",["pointer","uint32"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function sig(m){var h=H_();var nm=h.mGN(m).readCString();var pc=h.mGPC(m);var ps=[];for(var i=0;i<pc;i++){try{ps.push(h.tGN(h.mGP(m,i)).readCString());}catch(e){ps.push("?");}}var rt="";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}return nm+"("+ps.join(", ")+") -> "+rt;}
rpc.exports.methods=function(cls,re){var h=H_();var k=findClass(cls);if(!k)return {err:"no "+cls};var rx=new RegExp(re);var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;var out=[];while((m=h.cGM(k,it))&&!m.isNull()){try{var nm=h.mGN(m).readCString();if(rx.test(nm))out.push(sig(m));}catch(e){}}return {cls:cls, methods:out};};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        for cls in ["WildMapPokemon", "MapPokemon", "IMapPokemon"]:
            r = sc.exports_sync.methods(cls, "Captur|Encounter|Try|Throw")
            print(f"\n===== {cls} =====")
            if isinstance(r, dict) and r.get("methods"):
                for m in r["methods"]:
                    print("  ", m)
            else:
                print("  ", r)
        sess.detach()
    finally:
        try: sess.detach()
        except Exception: pass


main()

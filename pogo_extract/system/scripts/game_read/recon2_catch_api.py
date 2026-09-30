"""#2 RECON 2 (READ-ONLY): exact signatures of the catch-path methods + how to enumerate nearby spawns +
the service singletons, so the Ultra auto-catcher can drive StartEncounter -> SelectPokeball -> AttemptCapture."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),mGP:b("il2cpp_method_get_param","pointer",["pointer","uint32"]),mGPN:b("il2cpp_method_get_param_name","pointer",["pointer","uint32"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return k;}catch(e){}}return null;}
function sig(m){var h=H_();var nm=h.mGN(m).readCString();var pc=h.mGPC(m);var ps=[];for(var i=0;i<pc;i++){var t="";try{t=h.tGN(h.mGP(m,i)).readCString();}catch(e){t="?";}var pn="";try{pn=h.mGPN(m,i).readCString();}catch(e){}ps.push(t+" "+pn);}var rt="";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}return nm+"("+ps.join(", ")+") -> "+rt;}
rpc.exports.sigs=function(imageName,clsName,methodName){var h=H_();var k=findClass(imageName,clsName);if(!k)return {err:"no "+clsName};var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;var out=[];while((m=h.cGM(k,it))&&!m.isNull()){try{if(h.mGN(m).readCString()===methodName)out.push(sig(m));}catch(e){}}return {cls:clsName, sigs:out};};
rpc.exports.searchMethods=function(imageName,sub){var h=H_();var im=img(imageName);if(!im)return {err:"no image"};var cnt=h.iGCC(im);var out=[];var subl=sub.toLowerCase();for(var i=0;i<cnt&&out.length<40;i++){var k=h.iGC(im,i);if(k.isNull())continue;var cn;try{cn=h.CGN(k).readCString();}catch(e){continue;}var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()){try{var nm=h.mGN(m).readCString();if(nm.toLowerCase().indexOf(subl)>=0){out.push(cn+"."+nm+"("+h.mGPC(m)+")");if(out.length>=40)break;}}catch(e){}}}return {sub:sub, hits:out};};
rpc.exports.searchClasses=function(imageName,sub){var h=H_();var im=img(imageName);if(!im)return {err:"no image"};var cnt=h.iGCC(im);var out=[];var subl=sub.toLowerCase();for(var i=0;i<cnt&&out.length<40;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(nm.toLowerCase().indexOf(subl)>=0)out.push((h.CGNS(k).readCString()||"")+"."+nm);}catch(e){}}return out;};
"""

TARGETS = [
    ("holo-game.dll", "SpawnPokemonService", "StartEncounter"),
    ("holo-game.dll", "EncounterInteractionState", "AttemptCapture"),
    ("holo-game.dll", "EncounterInteractionState", "SelectPokeball"),
    ("holo-game.dll", "EncounterState", "SetupEncounter"),
    ("holo-game.dll", "ISpawnPokemonService", "StartEncounter"),
]


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        for img, cls, meth in TARGETS:
            r = sc.exports_sync.sigs(img, cls, meth)
            print(f"\n== {cls}.{meth} ==")
            if isinstance(r, dict) and r.get("sigs"):
                for s in r["sigs"]:
                    print("  ", s)
            else:
                print("  ", r)
        print("\n== spawn/map Pokemon classes ==")
        cls = set()
        for s in ["WildMapPokemon", "MapPokemon", "SpawnPokemon", "MapPokemonMarker"]:
            cls |= set(sc.exports_sync.search_classes("holo-game.dll", s))
        for c in sorted(cls):
            print("  ", c)
        print("\n== nearby/visible enumeration methods ==")
        for sub in ["GetNearby", "VisiblePokemon", "GetMapPokemon", "GetSpawnedPokemon", "MapPokemon"]:
            r = sc.exports_sync.search_methods("holo-game.dll", sub)
            for h in (r.get("hits", []) if isinstance(r, dict) else [])[:12]:
                print(f"   [{sub}] {h}")
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

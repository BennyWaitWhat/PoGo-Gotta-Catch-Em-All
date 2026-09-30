"""#2 RECON (READ-ONLY): map the game's managed encounter+catch API so the Ultra auto-catcher can
DRIVE the game's own (signed) catch path instead of forging RPCs.
Dumps methods of the encounter/catch classes VGP3 hooks, and searches holo-game.dll for catch/encounter
service methods + how nearby wild Pokemon (with encounter ids) are enumerated."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return k;}catch(e){}}return null;}
function methodsOf(k){var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;var out=[];while((m=h.cGM(k,it))&&!m.isNull()){try{var nm=h.mGN(m).readCString();var pc=h.mGPC(m);var rt="";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(nm+"("+pc+") -> "+rt);}catch(e){}}return out;}
rpc.exports.methods=function(imageName,clsName){var k=findClass(imageName,clsName);if(!k)return {err:"no "+clsName};return {cls:clsName, methods:methodsOf(k)};};
rpc.exports.searchMethods=function(imageName,sub){var h=H_();var im=img(imageName);if(!im)return {err:"no image"};var cnt=h.iGCC(im);var out=[];var subl=sub.toLowerCase();for(var i=0;i<cnt&&out.length<50;i++){var k=h.iGC(im,i);if(k.isNull())continue;var cn;try{cn=h.CGN(k).readCString();}catch(e){continue;}var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()){try{var nm=h.mGN(m).readCString();if(nm.toLowerCase().indexOf(subl)>=0){out.push(cn+"."+nm+"("+h.mGPC(m)+")");if(out.length>=50)break;}}catch(e){}}}return {sub:sub, hits:out};};
rpc.exports.searchClasses=function(imageName,sub){var h=H_();var im=img(imageName);if(!im)return {err:"no image"};var cnt=h.iGCC(im);var out=[];var subl=sub.toLowerCase();for(var i=0;i<cnt&&out.length<60;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(nm.toLowerCase().indexOf(subl)>=0)out.push((h.CGNS(k).readCString()||"")+"."+nm);}catch(e){}}return out;};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        for cls in ["EncounterInteractionState", "EncounterState", "EncounterPokemon"]:
            r = sc.exports_sync.methods("holo-game.dll", cls)
            print(f"\n===== {cls} =====")
            if isinstance(r, dict) and r.get("methods"):
                for m in r["methods"]:
                    if any(k in m.lower() for k in ["catch", "throw", "ball", "encounter", "attempt", "capture", "start", "begin", "result"]):
                        print("  ", m)
            else:
                print("  ", r)
        for sub in ["AttemptCatch", "ThrowPokeball", "CatchPokemon", "SendCatch", "StartEncounter", "RequestEncounter"]:
            r = sc.exports_sync.search_methods("holo-game.dll", sub)
            hits = r.get("hits", []) if isinstance(r, dict) else []
            print(f"\n== methods ~ '{sub}' ({len(hits)}) ==")
            for h in hits[:20]:
                print("  ", h)
        print("\n== Encounter service classes ==")
        for c in sorted(set(sc.exports_sync.search_classes("holo-game.dll", "EncounterService") + sc.exports_sync.search_classes("holo-game.dll", "CatchService"))):
            print("  ", c)
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

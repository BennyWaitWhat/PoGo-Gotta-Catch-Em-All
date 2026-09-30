"""RECON pass 5 (READ-ONLY): (a) dump QuestsProto 0-arg getters to find the quest-list field, and
(b) dump parameter TYPES for the methods we must drive (open + catch). Touches nothing."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),mGP:b("il2cpp_method_get_param","pointer",["pointer","uint32"]),mGPN:b("il2cpp_method_get_param_name","pointer",["pointer","uint32"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
rpc.exports.getters=function(cls,image){var h=H_();var k=findClass(image,cls);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()&&out.length<160){try{if(h.mGPC(m)!==0)continue;var nm=h.mGN(m).readCString();var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(nm+" -> "+rt);}catch(e){}}return out;};
rpc.exports.paramTypes=function(cls,meth,argc,image){var h=H_();var k=findClass(image,cls);if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(meth),argc);if(!m||m.isNull())return {err:"method not found"};var out=[];var pc=h.mGPC(m);for(var i=0;i<pc;i++){var t=h.mGP(m,i);var tn="?";try{tn=h.tGN(t).readCString();}catch(e){}var pn="?";try{pn=h.mGPN(m,i).readCString();}catch(e){}out.push(pn+": "+tn);}var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}return {params:out,ret:rt};};
"""

PARAM_TARGETS = [
    ("QuestService", "GetDanglingEncounterOfType", 2, "holo-game.dll"),
    ("QuestService", "GetPokemonEncounterForQuest", 1, "holo-game.dll"),
    ("QuestStateManager", "OpenQuestEncounter", 1, "holo-game.dll"),
    ("QuestStateManager", "OpenQuestEncounter", 2, "holo-game.dll"),
    ("ResearchEncounter", "AttemptCapture", 1, "holo-game.dll"),
    ("QuestMapPokemon", "SendEncounterRequest", 0, "holo-game.dll"),
]


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        print("\n#### QuestsProto 0-arg getters ####")
        for g in (sc.exports_sync.getters("QuestsProto", "holo-protos.dll") or []):
            print("   ", g)
        print("\n#### method parameter types ####")
        for cls, meth, argc, image in PARAM_TARGETS:
            res = sc.exports_sync.param_types(cls, meth, argc, image)
            print(f"\n--- {cls}.{meth}({argc}) ---")
            if isinstance(res, dict) and "params" in res:
                for p in res["params"]:
                    print("    param", p)
                print("    ret  ", res.get("ret"))
            else:
                print("   ", res)
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

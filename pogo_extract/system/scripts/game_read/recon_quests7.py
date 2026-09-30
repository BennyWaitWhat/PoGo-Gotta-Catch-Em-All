"""RECON pass 7 (READ-ONLY): find the dangling reward objects directly in the heap.
Count live QuestDanglingEncounterData + QuestPokemonEncounterProto instances; for each dangling-data
holder, confirm get_DanglingEncounter() is non-null. Touches nothing."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function inv(m,obj,params){var h=H_();if(!m)return null;var n=params?params.length:0;var args=ptr(0);if(n){args=Memory.alloc(Process.pointerSize*n);for(var i=0;i<n;i++)args.add(i*Process.pointerSize).writePointer(params[i]);}var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,args,exc);if(!exc.readPointer().isNull())return null;return r;}
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.danglingOk=function(inst){var h=H_();var m=mOf(h.OGC(ptr(inst)),"get_DanglingEncounter",0);if(!m)return "no-method";var r=inv(m,ptr(inst),[]);return (r&&!r.isNull())?r.toString():"null";};
"""


def count(finder, sc, ns, cls):
    if not ns:
        return None
    r = finder.exports_sync.find_singleton(ns, cls)
    return [h for h in (r.get("hits", []) if isinstance(r, dict) else [])
            if sc.exports_sync.cls_name(h) == cls]


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        dde = count(finder, sc, "Niantic.Holoholo.Quests", "QuestDanglingEncounterData")
        print(f"QuestDanglingEncounterData instances: {len(dde) if dde is not None else 'n/a'}")
        if dde:
            okc = 0
            for h in dde[:120]:
                d = sc.exports_sync.dangling_ok(h)
                if d not in ("null", "no-method", None):
                    okc += 1
            print(f"  of those, get_DanglingEncounter() non-null: {okc}")
        for ns, cls in [("Holoholo.Rpc", "QuestPokemonEncounterProto"),
                        ("Niantic.Holoholo.Encounter", "ResearchEncounter"),
                        ("Niantic.Holoholo.Quests", "QuestMapPokemon"),
                        ("Niantic.Holoholo.UI.TodayView", "DanglingResearchRewardWidget")]:
            hh = count(finder, sc, ns, cls)
            print(f"{cls}: {len(hh) if hh is not None else 'n/a'} instances")
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

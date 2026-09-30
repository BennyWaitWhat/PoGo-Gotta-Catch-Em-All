"""#2 opener trace (READ-ONLY): while the user taps wild Pokemon normally, log which encounter-open
methods fire and in what order, so we learn the exact programmatic entry point to open an encounter.
Hooks (observe only): EncounterState.SetupEncounter, EncounterInteractionState.set_EncounterPokemon,
WildMapPokemon.SendEncounterRequest, SpawnPokemonService.StartEncounter."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

HOLD = 80

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function cn(p){try{return H_().CGN(H_().OGC(p)).readCString();}catch(e){return '?';}}
function hookM(cls,name,argc,label,argIdx){var h=H_();var k=findClass("holo-game.dll",cls);if(!k)return false;var m=h.cMN(k,Memory.allocUtf8String(name),argc);if(!m||m.isNull())return false;var ad=m.readPointer();if(ad.isNull())return false;Interceptor.attach(ad,{onEnter:function(a){try{var ex=(argIdx>=0)?(' arg'+argIdx+'='+cn(a[argIdx])):'';send({k:'fire',m:label,ex:ex});}catch(e){send({k:'fire',m:label,ex:''});}}});return true;}
rpc.exports.hook=function(){var st={};
 st.SetupEncounter=hookM("EncounterState","SetupEncounter",4,"EncounterState.SetupEncounter",1);
 st.set_EncounterPokemon=hookM("EncounterInteractionState","set_EncounterPokemon",1,"EIS.set_EncounterPokemon",-1);
 st.SendEncounterRequest_WMP=hookM("WildMapPokemon","SendEncounterRequest",0,"WildMapPokemon.SendEncounterRequest",-1);
 st.SendEncounterRequest_MP=hookM("MapPokemon","SendEncounterRequest",0,"MapPokemon.SendEncounterRequest",-1);
 st.StartEncounter=hookM("SpawnPokemonService","StartEncounter",1,"SpawnPokemonService.StartEncounter",-1);
 return st;
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS);
        def on_msg(m, d):
            if m.get("type") == "send" and m.get("payload", {}).get("k") == "fire":
                p = m["payload"]
                print(f"  {time.strftime('%H:%M:%S')}  {p.get('m')}{p.get('ex','')}")
        sc.on("message", on_msg); sc.load()
        print("hooks:", sc.exports_sync.hook())
        print(f"\n*** Tap & catch 1-2 wild Pokemon during the next {HOLD}s — I'll trace the open path ***")
        time.sleep(HOLD)
        sess.detach()
    finally:
        try: sess.detach()
        except Exception: pass


main()

"""RECON (READ-ONLY): map the INCENSE catch path so the auto-catcher can be extended to it.
Incense mons are IncenseMapPokemon (separate from wild MapPokemon) and use IncenseEncounterProto
(not the wild EncounterProto/SendEncounterRequest). This dumps:
  - all /incense/i classes in holo-game.dll (find the holding service + IncenseMapPokemon)
  - IncenseMapPokemon methods (does it share SendEncounterRequest/TryCapture/get_EncounterId/
    get_Location/get_VisibleOnMap/get_PokemonId — i.e. can it reuse the existing open->throw pipeline?)
  - MapPlaceDirectoryService methods touching incense / AllPokemon (the accessor)
  - IncenseEncounterOutProto fields (Status offset, like the wild one at 0x1c)
  - GetIncensePokemonOutProto fields (where the served incense mon lives)
Pure static metadata read. Run with the catcher STOPPED (single-client gadget)."""
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
rpc.exports.dump=function(name,image){var h=H_();var k=findClass(image,name);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()&&out.length<240){try{var nm=h.mGN(m).readCString();var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(nm+" ("+h.mGPC(m)+") -> "+rt);}catch(e){}}return out;};
rpc.exports.fields=function(name,image){var h=H_();var k=findClass(image,name);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.cGF(k,it))&&!f.isNull()&&out.length<80){try{var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}out.push("+0x"+h.fGO(f).toString(16)+" "+h.fGN(f).readCString()+" : "+tn);}catch(e){}}return out;};
"""

IFACE = ("Encounter", "Capture", "EncounterId", "Location", "Visible", "Pokemon", "Send", "Try", "Throw", "Disk", "Active", "Detail", "Id")


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        print("\n== /incense/i classes (holo-game.dll) ==")
        cls = sorted(set(sc.exports_sync.list_classes("incense", "holo-game.dll")))
        for c in cls:
            print("   ", c)

        print("\n--- IncenseMapPokemon : interface methods (open/capture/getters) ---")
        im = sc.exports_sync.dump("IncenseMapPokemon", "holo-game.dll") or []
        for m in im:
            if any(t in m for t in IFACE):
                print("   ", m)

        print("\n--- MapPokemon (wild) : same filter, for comparison ---")
        wm = sc.exports_sync.dump("MapPokemon", "holo-game.dll") or []
        for m in wm:
            if any(t in m for t in ("Encounter", "Capture", "Send", "Try", "Visible", "get_Location", "get_PokemonId")):
                print("   ", m)

        print("\n--- MapPlaceDirectoryService : incense / AllPokemon accessors ---")
        ms = sc.exports_sync.dump("MapPlaceDirectoryService", "holo-game.dll") or []
        for m in ms:
            if "ncense" in m or "AllPokemon" in m or "Attracted" in m:
                print("   ", m)

        # Any incense SERVICE class -> dump its pokemon accessors
        for c in cls:
            short = c.split(".")[-1]
            if "Service" in short or "Manager" in short or short == "IncenseMapPokemon":
                continue
        for c in cls:
            short = c.split(".")[-1]
            if ("Service" in short) or ("Manager" in short):
                dm = sc.exports_sync.dump(short, "holo-game.dll") or []
                hits = [m for m in dm if ("Pokemon" in m or "ncense" in m or m.startswith("get_"))]
                if hits:
                    print(f"\n--- {short} : pokemon/incense accessors ---")
                    for m in hits[:30]:
                        print("   ", m)

        print("\n--- IncenseEncounterOutProto fields (Status offset) ---")
        for f in (sc.exports_sync.fields("IncenseEncounterOutProto", "holo-protos.dll") or []):
            print("   ", f)
        print("\n--- GetIncensePokemonOutProto fields ---")
        for f in (sc.exports_sync.fields("GetIncensePokemonOutProto", "holo-protos.dll") or []):
            print("   ", f)

        print("\n--- IncenseMapPokemon FULL method list (first 90) ---")
        for m in im[:90]:
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

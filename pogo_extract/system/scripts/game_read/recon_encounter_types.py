"""RECON (READ-ONLY): map EVERY catchable map-spawn type so the auto-catcher can be unified.
For each *MapPokemon class: which capture-interface methods it has (get_EncounterId / SendEncounterRequest /
TryCapture / get_Location / get_VisibleOnMap / get_PokemonId / cmof->IEncounterState / get_SourceType).
Plus: MapPlaceDirectoryService's full set of pokemon/encounter accessors (the spawn SOURCES),
the IEncounterState/EncounterState capture method (the UNIFIED throw path), and the Result/Status
offset of every *EncounterOutProto (to extend the require-OK rule to all sources). Static read.
Run with the catcher STOPPED (single-client gadget)."""
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
rpc.exports.listClasses=function(rx,image){var h=H_();var im=img(image);if(!im)return [];var re=new RegExp(rx,"i");var cnt=h.iGCC(im);var out=[];for(var i=0;i<cnt&&out.length<200;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(re.test(nm))out.push((h.CGNS(k).readCString()||"")+"."+nm);}catch(e){}}return out;};
rpc.exports.dump=function(name,image){var h=H_();var k=findClass(image,name);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()&&out.length<240){try{var nm=h.mGN(m).readCString();var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(nm+" ("+h.mGPC(m)+") -> "+rt);}catch(e){}}return out;};
rpc.exports.fields=function(name,image){var h=H_();var k=findClass(image,name);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.cGF(k,it))&&!f.isNull()&&out.length<80){try{var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}out.push("+0x"+h.fGO(f).toString(16)+" "+h.fGN(f).readCString()+" : "+tn);}catch(e){}}return out;};
"""

KEY = ["get_EncounterId", "SendEncounterRequest", "TryCapture", "get_Location", "get_VisibleOnMap",
       "get_PokemonId", "cmof", "get_SourceType", "get_Pokemon", "get_DisappearTimeMs", "get_SpawnPointId"]


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        print("\n========== (1) *MapPokemon classes -> capture-interface coverage ==========")
        classes = sorted(set(sc.exports_sync.list_classes("MapPokemon", "holo-game.dll")))
        for c in classes:
            short = c.split(".")[-1]
            ms = sc.exports_sync.dump(short, "holo-game.dll") or []
            names = set(m.split(" ")[0] for m in ms)
            have = [k for k in KEY if k in names]
            print(f"  {short:28s} -> {have}")

        print("\n========== (2) MapPlaceDirectoryService -> spawn SOURCES (accessors) ==========")
        for m in (sc.exports_sync.dump("MapPlaceDirectoryService", "holo-game.dll") or []):
            if any(t in m for t in ("Pokemon", "ncense", "Lure", "Encounter", "Attracted", "Station", "Route", "Daily", "Disk")):
                print("   ", m)

        print("\n========== (3) Unified capture path (encounter-state classes) ==========")
        for cls in ["IEncounterState", "EncounterState", "EncounterInteractionState", "IEncounterInteractionState"]:
            ms = sc.exports_sync.dump(cls, "holo-game.dll") or []
            hits = [m for m in ms if any(t in m for t in ("Capture", "Throw", "Catch", "Ball", "Flee", "Encounter"))]
            if hits:
                print(f"  -- {cls} --")
                for m in hits:
                    print("     ", m)

        print("\n========== (4) *EncounterOutProto Result/Status offsets (for require-OK extension) ==========")
        for p in ["EncounterOutProto", "IncenseEncounterOutProto", "DiskEncounterOutProto",
                  "DailyEncounterOutProto", "AttractedPokemonEncounterOutProto",
                  "DailyBonusSpawnEncounterOutProto", "StationPokemonEncounterOutProto",
                  "GetIncensePokemonOutProto", "GetDailyEncounterOutProto"]:
            fs = sc.exports_sync.fields(p, "holo-protos.dll") or []
            res = [f for f in fs if ("Result" in f or "Status" in f)]
            extra = [f for f in fs if ("Pokemon" in f or "CaptureProb" in f or "DisappearTime" in f or "EncounterId" in f)]
            tag = res if res else "(class not found)" if not fs else "(no result field)"
            print(f"  {p:34s} {tag}")
            if extra:
                print(f"       data: {extra}")
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

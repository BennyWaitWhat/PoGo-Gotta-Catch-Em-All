"""RECON (READ-ONLY): find the per-ball capture-probability data so we can pick the optimal ball per encounter.
Dumps WildMapPokemon/MapPokemon methods, hunts CaptureProbability/EncounterOutProto classes, dumps their
fields (offsets). Also looks for level/CPM getters. Catcher keeps running; this just attaches read-only."""
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
rpc.exports.listClasses=function(rx,image){var h=H_();var im=img(image);if(!im)return [];var re=new RegExp(rx,"i");var cnt=h.iGCC(im);var out=[];for(var i=0;i<cnt&&out.length<60;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(re.test(nm))out.push((h.CGNS(k).readCString()||"")+"."+nm);}catch(e){}}return out;};
rpc.exports.dump=function(name,image){var h=H_();var k=findClass(image,name);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()&&out.length<120){try{var nm=h.mGN(m).readCString();var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(nm+" ("+h.mGPC(m)+") -> "+rt);}catch(e){}}return out;};
rpc.exports.fields=function(name,image){var h=H_();var k=findClass(image,name);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.cGF(k,it))&&!f.isNull()&&out.length<80){try{var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}out.push("+0x"+h.fGO(f).toString(16)+" "+h.fGN(f).readCString()+" : "+tn);}catch(e){}}return out;};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        for rx, image in [("EncounterState|EncounterInteraction|CaptureProbability", "holo-game.dll")]:
            cl = sc.exports_sync.list_classes(rx, image)
            if cl:
                print(f"\n== {image} /{rx}/ =="); [print("   ", c) for c in sorted(set(cl))]
        for cls, image, what in [("WildPokemonProto", "holo-protos.dll", "fields"),
                                 ("EncounterOutProto", "holo-protos.dll", "fields")]:
            res = sc.exports_sync.fields(cls, image) if what == "fields" else sc.exports_sync.dump(cls, image)
            print(f"\n--- {cls} [{what}] ---")
            for x in (res or []):
                # for methods, only show interesting ones to keep it readable
                if what == "methods" and not any(t in x for t in ("Capture", "Probab", "Encounter", "Proto", "Out", "Ball", "Reticle", "Throw", "Catch", "Pokemon", "Response")):
                    continue
                print("   ", x)
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

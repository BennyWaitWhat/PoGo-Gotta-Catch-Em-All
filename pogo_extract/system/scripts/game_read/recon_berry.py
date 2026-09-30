"""RECON (READ-ONLY): find how to use a berry (Pinap / Golden Razz) on an encounter, and the item IDs.
Scans for UseItem*/Berry methods (the RPC), dumps MapPokemon methods (does the reduced fast-catch path
expose a berry call?), and reads the Item enum to extract berry IDs. Touches nothing."""
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
 H={dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),dG:b("il2cpp_domain_get","pointer",[]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),mGP:b("il2cpp_method_get_param","pointer",["pointer","uint32"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fSGV:b("il2cpp_field_static_get_value","void",["pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
rpc.exports.dumpMethods=function(cls,image){var h=H_();var k=findClass(image,cls);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()&&out.length<200){try{var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(h.mGN(m).readCString()+" ("+h.mGPC(m)+") -> "+rt);}catch(e){}}return out;};
rpc.exports.methodScan=function(rx,image){var h=H_();var im=img(image);if(!im)return [];var re=new RegExp(rx,"i");var cnt=h.iGCC(im);var out=[];for(var i=0;i<cnt&&out.length<80;i++){var k=h.iGC(im,i);if(k.isNull())continue;var cn;try{cn=h.CGN(k).readCString();}catch(e){continue;}var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()){try{var mn=h.mGN(m).readCString();if(re.test(mn)){out.push(cn+"::"+mn+" ("+h.mGPC(m)+")");if(out.length>=80)break;}}catch(e){}}}return out;};
rpc.exports.fullMethods=function(cls,image,rx){var h=H_();var k=findClass(image,cls);if(!k)return null;var re=rx?new RegExp(rx,"i"):null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()&&out.length<60){try{var mn=h.mGN(m).readCString();if(re&&!re.test(mn))continue;var pc=h.mGPC(m);var ps=[];for(var i=0;i<pc;i++){try{ps.push(h.tGN(h.mGP(m,i)).readCString());}catch(e){ps.push("?");}}var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(mn+"("+ps.join(", ")+") -> "+rt);}catch(e){}}return out;};
rpc.exports.classScan=function(rx,image){var h=H_();var im=img(image);if(!im)return [];var re=new RegExp(rx,"i");var cnt=h.iGCC(im);var out=[];for(var i=0;i<cnt&&out.length<80;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(re.test(nm))out.push((h.CGNS(k).readCString()||"")+"."+nm);}catch(e){}}return out;};
rpc.exports.enumVals=function(cls,image){var h=H_();var k=findClass(image,cls);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;var buf=Memory.alloc(8);while((f=h.cGF(k,it))&&!f.isNull()&&out.length<800){try{var nm=h.fGN(f).readCString();if(nm==="value__")continue;buf.writeU64(uint64(0));h.fSGV(f,buf);out.push(nm+" = "+buf.readS32());}catch(e){}}return out;};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        for img in ["holo-game.dll", "holo-protos.dll"]:
            ms = sc.exports_sync.method_scan("UseItem|UseEncounterItem|UseCaptureItem|Berry|Razz|Pinap|UseItemCapture|UseItemEncounter", img)
            print(f"\n=== methods /UseItem|Berry|Razz|Pinap/ in {img} ===", flush=True)
            for m in sorted(set(ms or [])):
                print("   ", m, flush=True)
        print("\n=== classes /UseItem.*Proto|Berry/ in holo-protos.dll ===", flush=True)
        for c in sorted(set(sc.exports_sync.class_scan("UseItem.*Proto|Berry|CaptureItem", "holo-protos.dll") or [])):
            print("   ", c, flush=True)
        print("\n=== MapPokemon methods (does the fast-catch object expose a berry call?) ===", flush=True)
        for m in (sc.exports_sync.dump_methods("MapPokemon", "holo-game.dll") or []):
            print("   ", m, flush=True)
        print("\n=== ItemBagImpl UseItem*/Predict signatures (how to call the berry) ===", flush=True)
        for m in (sc.exports_sync.full_methods("ItemBagImpl", "holo-game.dll", "UseItemForEncounter|UseItemOnPokemon|PredictUseItem") or []):
            print("   ", m, flush=True)
        # Item enum -> berry IDs
        for en, image in [("Item", "holo-protos.dll"), ("ItemId", "holo-protos.dll")]:
            ev = sc.exports_sync.enum_vals(en, image)
            if ev:
                berries = [x for x in ev if any(k in x.upper() for k in ["RAZZ", "PINAP", "NANAB", "BERRY"])]
                print(f"\n=== {en} berry IDs [{image}] ===", flush=True)
                for x in berries:
                    print("   ", x, flush=True)
                break
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

"""RECON (READ-ONLY): nail the catch-result signal for re-throw-on-breakout. Dumps CatchPokemonOutProto
field layout (confirm Status @0x10) and reads the CatchStatus enum constants the GAME defines (caught vs
escape vs flee vs miss) via il2cpp_field_static_get_value. Also lists nested types. Touches nothing."""
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
 H={dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),dG:b("il2cpp_domain_get","pointer",[]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),fSGV:b("il2cpp_field_static_get_value","void",["pointer","pointer"]),cGNT:b("il2cpp_class_get_nested_types","pointer",["pointer","pointer"]),cFT:b("il2cpp_class_from_type","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function enumK(k){var h=H_();var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;var buf=Memory.alloc(8);while((f=h.cGF(k,it))&&!f.isNull()&&out.length<200){try{var nm=h.fGN(f).readCString();if(nm==="value__")continue;buf.writeU64(uint64(0));h.fSGV(f,buf);out.push(nm+" = "+buf.readS32());}catch(e){}}return out;}
rpc.exports.fields=function(cls,image){var h=H_();var k=findClass(image,cls);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.cGF(k,it))&&!f.isNull()&&out.length<120){try{var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}out.push("+0x"+h.fGO(f).toString(16)+" "+h.fGN(f).readCString()+" : "+tn);}catch(e){}}return out;};
rpc.exports.nestedEnums=function(cls,image){var h=H_();var k=findClass(image,cls);if(!k)return null;var out={};var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var nt;var guard=0;while((nt=h.cGNT(k,it))&&!nt.isNull()&&guard++<40){try{var nm=h.CGN(nt).readCString();var vals=enumK(nt);if(vals.length)out[nm]=vals;}catch(e){}}return out;};
rpc.exports.enumByName=function(cls,image){var h=H_();var k=findClass(image,cls);if(!k)return null;return enumK(k);};
rpc.exports.enumOfField=function(cls,image,fieldName){var h=H_();var k=findClass(image,cls);if(!k)return null;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.cGF(k,it))&&!f.isNull()){try{if(h.fGN(f).readCString()===fieldName){var t=h.fGT(f);var ek=h.cFT(t);if(ek&&!ek.isNull())return enumK(ek);}}catch(e){}}return null;};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        print("\n=== CatchPokemonOutProto field layout (holo-protos.dll) ===", flush=True)
        for f in (sc.exports_sync.fields("CatchPokemonOutProto", "holo-protos.dll") or []):
            print("   ", f, flush=True)
        print("\n=== CatchPokemonOutProto nested enums ===", flush=True)
        ne = sc.exports_sync.nested_enums("CatchPokemonOutProto", "holo-protos.dll") or {}
        for nm, vals in ne.items():
            print(f"   [{nm}]", flush=True)
            for v in vals:
                print("       ", v, flush=True)
        print("\n=== CatchPokemonOutProto.Types.Status enum (via field type @0x10) ===", flush=True)
        for x in (sc.exports_sync.enum_of_field("CatchPokemonOutProto", "holo-protos.dll", "Status") or ["<none>"]):
            print("   ", x, flush=True)
        print("\n=== CatchPokemonOutProto.Types.CaptureReason enum (via field type @0x30) ===", flush=True)
        for x in (sc.exports_sync.enum_of_field("CatchPokemonOutProto", "holo-protos.dll", "CaptureReason") or ["<none>"]):
            print("   ", x, flush=True)
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

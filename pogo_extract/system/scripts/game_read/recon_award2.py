"""RECON (READ-ONLY): dump CatchPokemonOutProto field layout (offsets) + nested types, so we can read the
award by raw offset despite obfuscated getters. Then dump the award/CaptureAward type's fields. Touches nothing."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cGNT:b("il2cpp_class_get_nested_types","pointer",["pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function findNested(outerK,name){var h=H_();if(!outerK)return null;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var nt;while((nt=h.cGNT(outerK,it))&&!nt.isNull()){try{if(h.CGN(nt).readCString()===name)return nt;}catch(e){}}return null;}
function fieldsOf(k){var h=H_();if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.cGF(k,it))&&!f.isNull()&&out.length<200){try{var nm=h.fGN(f).readCString();var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}out.push({n:nm,t:tn,o:h.fGO(f)});}catch(e){}}return out;}
rpc.exports.fields=function(cls,image){return fieldsOf(findClass(image,cls));};
rpc.exports.nested=function(cls,image){var h=H_();var k=findClass(image,cls);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var nt;while((nt=h.cGNT(k,it))&&!nt.isNull()){try{out.push(h.CGN(nt).readCString());}catch(e){}}return out;};
rpc.exports.nestedFields=function(outer,nestedName,image){return fieldsOf(findNested(findClass(image,outer),nestedName));};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        for cls in ["CatchPokemonProto"]:
            fs = sc.exports_sync.fields(cls, "holo-protos.dll")
            print(f"\n--- {cls} fields ---")
            for f in (fs or []):
                print(f"   +0x{f['o']:x}  {f['n']} : {f['t']}")
            nt = sc.exports_sync.nested(cls, "holo-protos.dll")
            print(f"   nested types: {nt}")
            for n in (nt or []):
                nf = sc.exports_sync.nested_fields(cls, n, "holo-protos.dll")
                print(f"\n   --- {cls}.{n} fields ---")
                for f in (nf or []):
                    print(f"      +0x{f['o']:x}  {f['n']} : {f['t']}")
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

"""Locate the ~40m Go-Plus / interaction range field by NAME (proto field names are NOT
obfuscated). Search holo-protos.dll classes for interaction/range/plus/fort/gym/radius
fields, then read live values to find the ~40 gate. READ-ONLY."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
rpc.exports.searchField=function(imageName,subs){
 var h=H_();var im=img(imageName);if(!im)return["(no image)"];var cnt=h.iGCC(im);var out=[];
 for(var i=0;i<cnt&&out.length<400;i++){var k=h.iGC(im,i);if(k.isNull())continue;
   var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
   while((f=h.cGF(k,it))&&!f.isNull()){try{var nm=h.fGN(f).readCString();var low=nm.toLowerCase();
     for(var s=0;s<subs.length;s++){if(low.indexOf(subs[s])>=0){var cn=h.CGN(k).readCString();out.push(cn+"."+nm+"@0x"+h.fGO(f).toString(16)+":"+h.tGN(h.fGT(f)).readCString());break;}}
   }catch(e){}}}
 return out;
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        for image in ["holo-protos.dll", "holo-game.dll"]:
            print(f"\n===== {image} =====")
            res = sc.exports_sync.search_field(
                image, ["interactionrange", "interaction_range", "goplus", "go_plus", "sfidarange",
                        "fortinteraction", "forteraction", "encounterrange", "interactrange",
                        "captureradius", "catchradius", "plusrange", "interactionmeter"])
            if not res:
                print("  (none)")
            for line in sorted(set(res)):
                print("  ", line)
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

"""Find the method that SAVES player/Waina preferences to the server (the RPC the Go Plus+ ball
toggle fires). Search holo-game.dll + holo-protos.dll methods whose name mentions preferences/waina.
READ-ONLY (reflection only)."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","int",["pointer"]),mGP:b("il2cpp_method_get_param","pointer",["pointer","int"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
rpc.exports.searchMethod=function(imageName,subs){
 var h=H_();var im=img(imageName);if(!im)return["(no image)"];var cnt=h.iGCC(im);var out=[];
 for(var i=0;i<cnt&&out.length<300;i++){var k=h.iGC(im,i);if(k.isNull())continue;
   var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
   while((m=h.cGM(k,it))&&!m.isNull()){try{var nm=h.mGN(m).readCString();var low=nm.toLowerCase();
     for(var s=0;s<subs.length;s++){if(low.indexOf(subs[s])>=0){var pc=h.mGPC(m);var ps=[];for(var p=0;p<pc;p++){try{ps.push(h.tGN(h.mGP(m,p)).readCString());}catch(e){ps.push("?");}}out.push(h.CGN(k).readCString()+"."+nm+"("+ps.join(", ")+")");break;}}
   }catch(e){}}}
 return out;
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        for image in ["holo-game.dll", "holo-protos.dll"]:
            print(f"\n===== {image} =====")
            res = sc.exports_sync.search_method(image, ["saveplayerpref", "savepref", "savewaina",
                                                        "setwainapref", "updatewaina", "updatepref",
                                                        "savewearable", "savesettings", "wainapref"])
            for line in sorted(set(res)):
                print("  ", line)
            if not res:
                print("  (none)")
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

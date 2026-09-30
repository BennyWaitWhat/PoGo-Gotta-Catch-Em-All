"""Map the device-kind / session-start path so we know what to capture when the REAL Go Plus + pairs.
Lists PokemonGoPlus.DeviceKind enum members, and PgpService/SoftSfida session+device+pair methods.
READ-ONLY reflection."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","int",["pointer"]),mGP:b("il2cpp_method_get_param","pointer",["pointer","int"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return k;}catch(e){}}return null;}
rpc.exports.enumFields=function(imageName,clsName){var h=H_();var k=findClass(imageName,clsName);if(!k)return["(no class)"];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;var out=[];while((f=h.cGF(k,it))&&!f.isNull()){try{out.push(h.fGN(f).readCString());}catch(e){}}return out;};
rpc.exports.methods=function(imageName,clsName,subs){var h=H_();var k=findClass(imageName,clsName);if(!k)return["(no class)"];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;var out=[];while((m=h.cGM(k,it))&&!m.isNull()){try{var nm=h.mGN(m).readCString();var low=nm.toLowerCase();var ok=subs.length===0;for(var s=0;s<subs.length;s++)if(low.indexOf(subs[s])>=0){ok=true;break;}if(ok){var pc=h.mGPC(m);var ps=[];for(var p=0;p<pc;p++){try{ps.push(h.tGN(h.mGP(m,p)).readCString());}catch(e){ps.push("?");}}out.push(nm+"("+ps.join(", ")+")");}}catch(e){}}return out;};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        print("\n=== PokemonGoPlus.DeviceKind members ===")
        for f in sc.exports_sync.enum_fields("holo-game.dll", "DeviceKind"):
            print("  ", f)
        for img2 in ["holo-game.dll"]:
            for cls in ["PgpService", "PgpDeviceService"]:
                print(f"\n=== {cls} session/device/pair methods ===")
                ms = sc.exports_sync.methods(img2, cls, ["session", "device", "kind", "pair", "connect", "start", "waina", "advertise", "handshake"])
                for m in ms[:60]:
                    print("  ", m)
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

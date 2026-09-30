"""RECON (READ-ONLY): find the throw-classification logic + HoloActivityType codes so we can confirm
'Excellent' and ground the catch-rate math. Reads enum constants via il2cpp_field_static_get_value.
Catcher keeps running; this just attaches read-only."""
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
 H={dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),dG:b("il2cpp_domain_get","pointer",[]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fSGV:b("il2cpp_field_static_get_value","void",["pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
rpc.exports.listClasses=function(rx,image){var h=H_();var im=img(image);if(!im)return [];var re=new RegExp(rx,"i");var cnt=h.iGCC(im);var out=[];for(var i=0;i<cnt&&out.length<80;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();if(re.test(nm))out.push((h.CGNS(k).readCString()||"")+"."+nm);}catch(e){}}return out;};
rpc.exports.dump=function(name,image){var h=H_();var k=findClass(image,name);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()&&out.length<120){try{var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(h.mGN(m).readCString()+" ("+h.mGPC(m)+") -> "+rt);}catch(e){}}return out;};
rpc.exports.enumVals=function(name,image){var h=H_();var k=findClass(image,name);if(!k)return null;if(!h.fSGV)return {err:"no fSGV"};var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;var buf=Memory.alloc(8);while((f=h.cGF(k,it))&&!f.isNull()&&out.length<200){try{var nm=h.fGN(f).readCString();if(nm==="value__")continue;buf.writeU64(uint64(0));h.fSGV(f,buf);out.push(nm+" = "+buf.readS32());}catch(e){}}return out;};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        for rx, image in [("Throw|Excellent|ThrowResult|ThrowScore|ThrowBonus|ReticleScore", "holo-game.dll")]:
            cl = sc.exports_sync.list_classes(rx, image)
            print(f"\n== {image} /{rx}/ =="); [print("   ", c) for c in sorted(set(cl or []))]
        for image in ["holo-protos.dll", "holo-game.dll"]:
            ev = sc.exports_sync.enum_vals("HoloActivityType", image)
            if ev:
                print(f"\n--- HoloActivityType [{image}] ---")
                for x in ev:
                    print("   ", x)
                break
        for cls in ["PokeballThrow", "ThrowResult", "ThrowBonus"]:
            for image in ["holo-game.dll", "holo-protos.dll"]:
                d = sc.exports_sync.dump(cls, image)
                if d:
                    print(f"\n--- {cls} methods [{image}] ---")
                    for m in d:
                        print("   ", m)
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

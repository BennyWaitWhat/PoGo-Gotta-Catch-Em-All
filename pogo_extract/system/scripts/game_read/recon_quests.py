"""RECON (READ-ONLY): map the Field Research / quest reward system so we can catch the stacked
'Today' reward encounters UI-free. Lists Quest/Research/Reward classes in holo-game.dll + holo-protos.dll,
then dumps methods of likely service/manager/repository classes. Touches nothing."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
rpc.exports.listClasses=function(rx,imageName){var h=H_();var im=img(imageName||"holo-game.dll");if(!im)return [];var re=new RegExp(rx,"i");var cnt=h.iGCC(im);var out=[];for(var i=0;i<cnt&&out.length<400;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{var nm=h.CGN(k).readCString();var ns=h.CGNS(k).readCString();if(re.test(nm))out.push((ns?ns+".":"")+nm);}catch(e){}}return out;};
rpc.exports.clsMethods=function(name,imageName){var h=H_();var im=img(imageName||"holo-game.dll");if(!im)return null;var cnt=h.iGCC(im);var k=null;for(var i=0;i<cnt;i++){var kk=h.iGC(im,i);if(kk.isNull())continue;try{if(h.CGN(kk).readCString()===name){k=kk;break;}}catch(e){}}if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()&&out.length<120){try{var nm=h.mGN(m).readCString();var argc=h.mGPC(m);var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(nm+" ("+argc+") -> "+rt);}catch(e){}}return out;};
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        names = set()
        for image in ["holo-game.dll", "holo-protos.dll"]:
            for rx in ["Quest", "Research", "Reward"]:
                cl = sc.exports_sync.list_classes(rx, image)
                for c in (cl or []):
                    names.add((image, c))
                print(f"\n== {image} /{rx}/ -> {len(cl or [])}")
                for c in sorted(set(cl or [])):
                    print("   ", c)
        # method dump for likely service/manager classes
        import re
        svc_re = re.compile(r"(Quest|Research).*(Manager|Service|Repository|Repo|Controller|Data|Store|Cache|Provider|Model)", re.I)
        cands = []
        for image, full in names:
            cls = full.split(".")[-1]
            if svc_re.search(cls) and cls.startswith(("Quest", "Research")) and not cls.startswith("I"):
                cands.append((image, cls))
        cands = sorted(set(cands))[:8]
        print(f"\n==== method dumps for {len(cands)} service candidates ====")
        for image, cls in cands:
            ms = sc.exports_sync.cls_methods(cls, image)
            print(f"\n--- {cls} ({image}) ---")
            for m in (ms or []):
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

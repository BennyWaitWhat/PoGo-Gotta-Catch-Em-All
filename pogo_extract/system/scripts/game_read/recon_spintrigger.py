"""RECON (READ-ONLY): find the method that TRIGGERS a PokeStop spin programmatically
(the spin equivalent of MapPokemon.TryCapture). Dumps: MapPlaceDirectoryService methods
(fort accessor?), every method whose return type mentions FortSearch, and Search/Spin
methods on Fort/Poi classes. Pure metadata read — sends nothing. Catcher paused during run."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so"); var e={};
 il.enumerateExports().forEach(function(x){ if(x.name.indexOf("il2cpp_")===0) e[x.name]=x.address; });
 function b(n,r,a){ return e[n]? new NativeFunction(e[n],r,a): null; }
 H={ dG:b("il2cpp_domain_get","pointer",[]), dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),
     aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]), iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),
     iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]), CGN:b("il2cpp_class_get_name","pointer",["pointer"]),
     CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),
     cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]), mGN:b("il2cpp_method_get_name","pointer",["pointer"]),
     mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]), mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),
     tGN:b("il2cpp_type_get_name","pointer",["pointer"]), OGC:b("il2cpp_object_get_class","pointer",["pointer"]),
     tA:b("il2cpp_thread_attach","pointer",["pointer"]) };
 H.tA(H.dG()); return H; }
function eachClass(cb){ var h=H_(); var sp=Memory.alloc(4); var a=h.dGA(h.dG(),sp); var n=sp.readS32();
 for(var i=0;i<n;i++){ var im=h.aGI(a.add(i*Process.pointerSize).readPointer()); var cnt=h.iGCC(im);
   for(var j=0;j<cnt;j++){ var k=h.iGC(im,j); if(!k.isNull()) cb(k); } } }
function findClass(name){ var h=H_(); var f=null; eachClass(function(k){ if(f)return; try{ if(h.CGN(k).readCString()===name) f=k; }catch(e){} }); return f; }
function methodsOf(k){ var h=H_(); var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m;
 while((m=h.cGM(k,it))&&!m.isNull()){ try{ var rt="?"; try{ rt=h.tGN(h.mGRT(m)).readCString(); }catch(e){} out.push({n:h.mGN(m).readCString(), pc:h.mGPC(m), rt:rt}); }catch(e){} } return out; }

rpc.exports.dumpClass=function(name){ var k=findClass(name); if(!k)return null; return methodsOf(k).map(function(m){return m.n+"("+m.pc+") -> "+m.rt;}); };
// every method (any class) whose return type name contains `sub`
rpc.exports.byReturn=function(sub){ var h=H_(); var out=[]; eachClass(function(k){ var cn; try{cn=h.CGN(k).readCString();}catch(e){return;} var ms=methodsOf(k);
   for(var i=0;i<ms.length;i++){ if(ms[i].rt.indexOf(sub)>=0 && out.length<80){ out.push(cn+"::"+ms[i].n+"("+ms[i].pc+") -> "+ms[i].rt); } } }); return out; };
// classes whose name matches `rx`, with any method whose name matches `mrx`
rpc.exports.classMethods=function(rx,mrx){ var h=H_(); var re=new RegExp(rx); var mre=new RegExp(mrx,"i"); var out=[];
 eachClass(function(k){ var cn; try{cn=h.CGN(k).readCString();}catch(e){return;} if(!re.test(cn))return; var ms=methodsOf(k);
   for(var i=0;i<ms.length;i++){ if(mre.test(ms[i].n) && out.length<120){ out.push(cn+"::"+ms[i].n+"("+ms[i].pc+") -> "+ms[i].rt); } } }); return out; };
"""


def main():
    sess, pid = pg.get_session()
    sc = sess.create_script(JS); sc.load()
    print("attached", pid, flush=True)
    try:
        for cls in ["MapPokestopInteractive", "IMapPokestopMode", "IMapPlace"]:
            print(f"\n=== {cls} methods ===")
            for x in (sc.exports_sync.dump_class(cls) or ["(class not found)"]):
                print("  ", x)
        print("\n=== who returns a PoiItemSpinner (get the spinner from) ===")
        for x in (sc.exports_sync.by_return("PoiItemSpinner") or ["(none)"]):
            print("  ", x)
        print("\n=== who returns a MapPokestopInteractive ===")
        for x in (sc.exports_sync.by_return("MapPokestopInteractive") or ["(none)"]):
            print("  ", x)
    finally:
        try:
            sc.unload(); sess.detach()
        except Exception:
            pass


main()

"""RECON (READ-ONLY): hunt the live game image for cooldown / throttle / speed /
last-action state. Searches class names, then can dump fields+methods of any class.
Pure read."""
import sys, os, time
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
     aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]), iGN:b("il2cpp_image_get_name","pointer",["pointer"]),
     iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]), iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),
     CGN:b("il2cpp_class_get_name","pointer",["pointer"]), CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),
     cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]), fGN:b("il2cpp_field_get_name","pointer",["pointer"]), fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),
     cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]), mGN:b("il2cpp_method_get_name","pointer",["pointer"]),
     tA:b("il2cpp_thread_attach","pointer",["pointer"]) };
 H.tA(H.dG()); return H; }
function eachClass(cb){ var h=H_(); var sp=Memory.alloc(4); var a=h.dGA(h.dG(),sp); var n=sp.readS32();
 for(var i=0;i<n;i++){ var im=h.aGI(a.add(i*Process.pointerSize).readPointer()); var img=h.iGN(im).readCString(); var cnt=h.iGCC(im);
   for(var j=0;j<cnt;j++){ var k=h.iGC(im,j); if(!k.isNull()) cb(k,img); } } }
function clsName(k){ try{ return H_().CGN(k).readCString(); }catch(e){ return ""; } }

rpc.exports.search=function(term){ var s=term.toLowerCase(); var out=[]; eachClass(function(k,img){ var n=clsName(k); if(n.toLowerCase().indexOf(s)>=0) out.push(img.replace('.dll','')+":"+n); }); return out; };
rpc.exports.methodsearch=function(term){ var h=H_(); var s=term.toLowerCase(); var out=[]; eachClass(function(k,img){ try{ var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m; while((m=h.cGM(k,it))&&!m.isNull()){ var nm=h.mGN(m).readCString(); if(nm.toLowerCase().indexOf(s)>=0){ out.push(clsName(k)+"."+nm); if(out.length>120)return; } } }catch(e){} }); return out.slice(0,120); };
rpc.exports.fields=function(cls){ var h=H_(); var k=null; eachClass(function(c){ if(k)return; if(clsName(c)===cls)k=c; }); if(!k)return null; var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f; while((f=h.cGF(k,it))&&!f.isNull()){ try{ out.push(h.fGN(f).readCString()+"@0x"+h.fGO(f).toString(16)); }catch(e){} } return out; };
rpc.exports.methods=function(cls){ var h=H_(); var k=null; eachClass(function(c){ if(k)return; if(clsName(c)===cls)k=c; }); if(!k)return null; var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m; while((m=h.cGM(k,it))&&!m.isNull()){ try{ out.push(h.mGN(m).readCString()); }catch(e){} } return out; };
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    sc = sess.create_script(JS)
    sc.load()
    for term in ["cooldown", "throttle", "softban", "soft_ban", "ratelimit", "rate_limit",
                 "speedlock", "antispeed", "lastaction", "speedwarn", "warn", "cheat", "minimumtime"]:
        r = sc.exports_sync.search(term)
        print(f"\n=== class names ~ '{term}' ({len(r)}) ===", flush=True)
        for x in r[:40]:
            print("  ", x, flush=True)
    print("\n=== method names ~ 'cooldown' ===", flush=True)
    for x in (sc.exports_sync.methodsearch("cooldown") or []):
        print("  ", x, flush=True)
    print("\n=== method names ~ 'lastaction' ===", flush=True)
    for x in (sc.exports_sync.methodsearch("lastaction") or []):
        print("  ", x, flush=True)
    try:
        sc.unload(); sess.detach()
    except Exception:
        pass


main()

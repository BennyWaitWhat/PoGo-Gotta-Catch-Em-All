"""RECON (READ-ONLY): dissect SpaceTimeThrottle (the speed/distance governor) and
GameAnticheatAction. Dumps fields+methods, hooks every SpaceTimeThrottle method to
catch a live instance, and reads its state (timestamps/locations/flags). Pure read."""
import sys, os, time, datetime
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
     cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]), fGN:b("il2cpp_field_get_name","pointer",["pointer"]), fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),
     cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]), mGN:b("il2cpp_method_get_name","pointer",["pointer"]), mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),
     OGC:b("il2cpp_object_get_class","pointer",["pointer"]), tA:b("il2cpp_thread_attach","pointer",["pointer"]) };
 H.tA(H.dG()); return H; }
function eachClass(cb){ var h=H_(); var sp=Memory.alloc(4); var a=h.dGA(h.dG(),sp); var n=sp.readS32();
 for(var i=0;i<n;i++){ var im=h.aGI(a.add(i*Process.pointerSize).readPointer()); var cnt=h.iGCC(im);
   for(var j=0;j<cnt;j++){ var k=h.iGC(im,j); if(!k.isNull()) cb(k); } } }
function findClass(name){ var h=H_(); var f=null; eachClass(function(k){ if(f)return; try{ if(h.CGN(k).readCString()===name) f=k; }catch(e){} }); return f; }
function fieldsOf(k){ var h=H_(); var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f; while((f=h.cGF(k,it))&&!f.isNull()){ try{ out.push({n:h.fGN(f).readCString(), o:h.fGO(f)}); }catch(e){} } return out; }

rpc.exports.dump=function(cls){ var h=H_(); var k=findClass(cls); if(!k) return null;
 var fl=fieldsOf(k).map(function(f){return f.n+"@0x"+f.o.toString(16);});
 var ms=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m; while((m=h.cGM(k,it))&&!m.isNull()){ try{ ms.push(h.mGN(m).readCString()+"/"+h.mGPC(m)); }catch(e){} }
 return {fields:fl, methods:ms}; };

var INST=null, CALLS={};
rpc.exports.install=function(){ var h=H_(); var k=findClass("SpaceTimeThrottle"); if(!k) return "no SpaceTimeThrottle";
 var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m; var hk=0;
 while((m=h.cGM(k,it))&&!m.isNull()){ try{ var nm=h.mGN(m).readCString(); var code=m.readPointer(); if(code&&!code.isNull()){
   (function(nm){ Interceptor.attach(code,{ onEnter:function(a){ try{ if(a[0]&&!a[0].isNull()){ INST=a[0]; } CALLS[nm]=(CALLS[nm]||0)+1; }catch(e){} } }); })(nm); hk++; } }catch(e){} }
 return "hooked "+hk+" methods"; };
rpc.exports.calls=function(){ return CALLS; };
rpc.exports.readinst=function(){ var h=H_(); if(!INST||INST.isNull()) return null;
 var k=h.OGC(INST); var fl=fieldsOf(k); var out={};
 for(var i=0;i<fl.length;i++){ var o=fl[i].o; try{ out[fl[i].n]={ s64:INST.add(o).readS64().toString(), dbl:INST.add(o).readDouble(), s32:INST.add(o).readS32(), u8:INST.add(o).readU8() }; }catch(e){ out[fl[i].n]="?"; } }
 return out; };
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    sc = sess.create_script(JS)
    sc.load()
    for cls in ["SpaceTimeThrottle", "GameAnticheatAction", "WarningInfo", "WarnedPlayerReason"]:
        d = sc.exports_sync.dump(cls)
        print(f"\n=== {cls} ===", flush=True)
        if d:
            print("  fields :", d["fields"], flush=True)
            print("  methods:", d["methods"], flush=True)
        else:
            print("  (not found)", flush=True)
    print("\ninstall hook:", sc.exports_sync.install(), flush=True)
    print(">>> watching SpaceTimeThrottle for 40s — SPIN A STOP / move so it evaluates <<<", flush=True)
    t0 = time.time()
    while time.time() - t0 < 40:
        time.sleep(4)
        calls = sc.exports_sync.calls() or {}
        if calls:
            print(f"  calls: {calls}", flush=True)
            inst = sc.exports_sync.readinst() or {}
            for k, v in inst.items():
                print(f"     {k}: {v}", flush=True)
            break
    else:
        print("  (SpaceTimeThrottle never called in window)", flush=True)
    try:
        sc.unload(); sess.detach()
    except Exception:
        pass


main()

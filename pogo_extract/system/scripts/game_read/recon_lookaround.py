"""RECON (READ-ONLY): live player position via runtime_invoke (boxes the
value-type GeoCoordinate so lat@0x10/lng@0x18 are valid), sampled to detect
movement vs frozen. Pure read."""
import sys, os, time, math
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
 H={ dG:b("il2cpp_domain_get","pointer",[]),
     dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),
     aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),
     iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),
     iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),
     CGN:b("il2cpp_class_get_name","pointer",["pointer"]),
     cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),
     OGC:b("il2cpp_object_get_class","pointer",["pointer"]),
     rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),
     tA:b("il2cpp_thread_attach","pointer",["pointer"]) };
 H.tA(H.dG()); return H; }
function eachClass(cb){ var h=H_(); var sp=Memory.alloc(4); var a=h.dGA(h.dG(),sp); var n=sp.readS32();
 for(var i=0;i<n;i++){ var im=h.aGI(a.add(i*Process.pointerSize).readPointer()); var cnt=h.iGCC(im);
   for(var j=0;j<cnt;j++){ var k=h.iGC(im,j); if(!k.isNull()) cb(k); } } }
function findClass(name){ var h=H_(); var f=null; eachClass(function(k){ if(f)return; try{ if(h.CGN(k).readCString()===name) f=k; }catch(e){} }); return f; }
function mInfo(k,name,argc){ var h=H_(); if(!k)return null; var m=h.cMN(k,Memory.allocUtf8String(name),argc); return (m&&!m.isNull())?m:null; }

var MAPAVATAR=null;
var EXC=Memory.alloc(Process.pointerSize);
rpc.exports.install=function(){ var h=H_();
 var k=findClass("MapAvatar"); if(!k) return "no MapAvatar class";
 var m=mInfo(k,"get_Location",0); if(!m) return "no get_Location";
 Interceptor.attach(m.readPointer(),{ onEnter:function(a){ MAPAVATAR=a[0]; } });
 return "hooked";
};
rpc.exports.readloc=function(){ var h=H_(); if(!MAPAVATAR||MAPAVATAR.isNull()) return null;
 var m=mInfo(h.OGC(MAPAVATAR),"get_Location",0); if(!m) return null;
 EXC.writePointer(ptr(0));
 var lr=h.rI(m,MAPAVATAR,ptr(0),EXC); if(!lr||lr.isNull()) return null;
 return {lat:lr.add(0x10).readDouble(), lng:lr.add(0x18).readDouble(), box:lr.toString()};
};
"""


def hav(a, b):
    R = 6371000
    p1 = math.radians(a[0]); p2 = math.radians(b[0])
    dp = math.radians(b[0]-a[0]); dl = math.radians(b[1]-a[1])
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(min(1, math.sqrt(x)))


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    sc = sess.create_script(JS)
    sc.load()
    print("install:", sc.exports_sync.install(), flush=True)
    time.sleep(1.5)
    print("\n--- AVATAR POSITION (runtime_invoke read, sampling 12s) ---", flush=True)
    samples = []
    for i in range(13):
        time.sleep(1)
        s = sc.exports_sync.readloc()
        if s and s.get("lat") is not None:
            samples.append((s["lat"], s["lng"]))
            print(f"  t={i:2d}s  lat={s['lat']:.7f}  lng={s['lng']:.7f}", flush=True)
        else:
            print(f"  t={i:2d}s  (avatar not captured yet)", flush=True)
    if len(samples) >= 2:
        moved = max(hav(samples[0], p) for p in samples)
        print(f"\n  >>> position drift over window: {moved:.1f} m", flush=True)
        print(f"  >>> first: {samples[0]}", flush=True)
        print(f"  >>> last:  {samples[-1]}", flush=True)
    try:
        sc.unload(); sess.detach()
    except Exception:
        pass


main()

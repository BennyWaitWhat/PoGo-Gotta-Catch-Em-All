"""RECON (READ-ONLY): exact spin geometry. Reads avatar position (runtime_invoke)
and hooks FortSearchProto.WriteTo to capture the player+fort coords actually sent
in the spin request, so we can compute how far the game thinks you are from the
stop. Plus the result code. Pure read."""
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
 H={ dG:b("il2cpp_domain_get","pointer",[]), dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),
     aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]), iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),
     iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]), CGN:b("il2cpp_class_get_name","pointer",["pointer"]),
     cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),
     cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]), fGN:b("il2cpp_field_get_name","pointer",["pointer"]),
     fGO:b("il2cpp_field_get_offset","uint32",["pointer"]), cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),
     mGN:b("il2cpp_method_get_name","pointer",["pointer"]), OGC:b("il2cpp_object_get_class","pointer",["pointer"]),
     rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),
     tA:b("il2cpp_thread_attach","pointer",["pointer"]) };
 H.tA(H.dG()); return H; }
function eachClass(cb){ var h=H_(); var sp=Memory.alloc(4); var a=h.dGA(h.dG(),sp); var n=sp.readS32();
 for(var i=0;i<n;i++){ var im=h.aGI(a.add(i*Process.pointerSize).readPointer()); var cnt=h.iGCC(im);
   for(var j=0;j<cnt;j++){ var k=h.iGC(im,j); if(!k.isNull()) cb(k); } } }
function findClass(name){ var h=H_(); var f=null; eachClass(function(k){ if(f)return; try{ if(h.CGN(k).readCString()===name) f=k; }catch(e){} }); return f; }
function mInfo(k,name,argc){ var h=H_(); if(!k)return null; var m=h.cMN(k,Memory.allocUtf8String(name),argc); return (m&&!m.isNull())?m:null; }
function listFields(k){ var h=H_(); var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
 while(true){ var f=h.cGF(k,it); if(!f||f.isNull())break; try{ out.push({name:h.fGN(f).readCString(),off:h.fGO(f)}); }catch(e){} } return out; }

var MAPAVATAR=null, EXC=Memory.alloc(Process.pointerSize);
var LOG=[]; function L(s){ LOG.push(s); }
rpc.exports.drain=function(){ var o=LOG; LOG=[]; return o; };
rpc.exports.readloc=function(){ var h=H_(); if(!MAPAVATAR||MAPAVATAR.isNull()) return null;
 var m=mInfo(h.OGC(MAPAVATAR),"get_Location",0); if(!m) return null; EXC.writePointer(ptr(0));
 var lr=h.rI(m,MAPAVATAR,ptr(0),EXC); if(!lr||lr.isNull()) return null;
 return {lat:lr.add(0x10).readDouble(), lng:lr.add(0x18).readDouble()}; };

rpc.exports.install=function(){ var h=H_();
 var ak=findClass("MapAvatar"); if(ak){ var am=mInfo(ak,"get_Location",0); if(am) Interceptor.attach(am.readPointer(),{onEnter:function(a){MAPAVATAR=a[0];}}); L("avatar "+(ak?"ok":"no")); }
 // FortSearchProto request: dump fields, hook WriteTo, read lat/lng-ish doubles
 var rk=findClass("FortSearchProto");
 if(rk){ var fs=listFields(rk); L("REQ fields: "+fs.map(function(f){return f.name+"@0x"+f.off.toString(16);}).join(", "));
   var pos=fs.filter(function(f){ var n=f.name.toLowerCase(); return n.indexOf("lat")>=0||n.indexOf("lng")>=0||n.indexOf("longitude")>=0; });
   var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var hk=0;
   while(true){ var m=h.cGM(rk,it); if(!m||m.isNull())break; var nm; try{nm=h.mGN(m).readCString();}catch(e){continue;}
     if(nm==="WriteTo"){ var code=m.readPointer(); if(code&&!code.isNull()){ (function(){ var P=pos; Interceptor.attach(code,{onEnter:function(a){ try{ var s=a[0]; if(!s||s.isNull())return; var parts=[]; for(var i=0;i<P.length;i++){ parts.push(P[i].name+"="+s.add(P[i].off).readDouble()); } L("REQ || "+parts.join("  ")); }catch(e){} }}); hk++; })(); } } }
   L("hooked "+hk+" WriteTo on FortSearchProto");
 } else { L("no FortSearchProto"); }
 // result
 var ok=findClass("FortSearchOutProto");
 if(ok){ var it2=Memory.alloc(Process.pointerSize); it2.writePointer(ptr(0));
   while(true){ var m2=h.cGM(ok,it2); if(!m2||m2.isNull())break; var nm2; try{nm2=h.mGN(m2).readCString();}catch(e){continue;}
     if(nm2==="MergeFrom"){ var c2=m2.readPointer(); if(c2&&!c2.isNull()) Interceptor.attach(c2,{onEnter:function(a){this.s=a[0];},onLeave:function(){try{var s=this.s;if(s&&!s.isNull())L("RESULT="+s.add(0x10).readS32());}catch(e){}}}); } } }
 return "installed"; };
"""

RESULT = {0: "NO_RESULT_SET", 1: "SUCCESS", 2: "OUT_OF_RANGE", 3: "IN_COOLDOWN_PERIOD",
          4: "INVENTORY_FULL", 5: "EXCEEDED_DAILY_LIMIT", 6: "POI_INACCESSIBLE"}


def hav(lat1, lng1, lat2, lng2):
    R = 6371000
    p1 = math.radians(lat1); p2 = math.radians(lat2)
    dp = math.radians(lat2-lat1); dl = math.radians(lng2-lng1)
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(min(1, math.sqrt(x)))


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    sc = sess.create_script(JS)
    sc.load()
    print("install:", sc.exports_sync.install(), flush=True)
    for line in (sc.exports_sync.drain() or []):
        print("  ", line, flush=True)
    print("\n>>> SPIN THE FAILING POKESTOP NOW. Watching 200s. <<<\n", flush=True)
    t0 = time.time()
    last_req = {}
    while time.time() - t0 < 200:
        time.sleep(2)
        loc = sc.exports_sync.readloc()
        for line in (sc.exports_sync.drain() or []):
            if line.startswith("REQ || "):
                kv = {}
                for p in line.split("|| ")[1].split("  "):
                    if "=" in p:
                        k, v = p.split("=", 1)
                        try:
                            kv[k] = float(v)
                        except Exception:
                            kv[k] = v
                last_req = kv
                print(f"  SPIN REQUEST coords: {kv}", flush=True)
                # try to find player/fort lat-lng pairs
                lats = {k: v for k, v in kv.items() if "lat" in k.lower()}
                lngs = {k: v for k, v in kv.items() if ("lng" in k.lower() or "longitude" in k.lower())}
                if loc:
                    print(f"  avatar now: lat={loc['lat']:.7f} lng={loc['lng']:.7f}", flush=True)
                # compute distances between any lat/lng pairs and avatar
                if loc and lats and lngs:
                    for lk, lv in lats.items():
                        for gk, gv in lngs.items():
                            d = hav(loc['lat'], loc['lng'], lv, gv)
                            print(f"    dist(avatar -> {lk}/{gk}) = {d:.1f} m", flush=True)
            elif line.startswith("RESULT="):
                v = int(line.split("=")[1])
                print(f"  >>> SPIN RESULT: {RESULT.get(v, v)}", flush=True)
            else:
                print("  ", line, flush=True)
    try:
        sc.unload(); sess.detach()
    except Exception:
        pass


main()

"""RECON (READ-ONLY) pass 2 for tap-to-move. ONE class-enumeration pass only (pass 1 was killed,
exit 137, from repeated full scans). Collects: concrete ILocationProvider implementations + their
fields (where the position is cached), and the exact GetWorldLocation signature."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};
 il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),
    aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),
    iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),
    cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),
    mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),
    mGP:b("il2cpp_method_get_param","pointer",["pointer","uint32"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),
    cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),
    fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),
    tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}

/* SINGLE pass: gather everything we need in one sweep */
rpc.exports.sweep=function(){var h=H_();var res={providers:[],getworld:[],latlng:null};
 var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();
 for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());var cnt=h.iGCC(im);
  for(var j=0;j<cnt;j++){var k=h.iGC(im,j);if(k.isNull())continue;var cn;
   try{cn=h.CGN(k).readCString();}catch(e){continue;}
   var isProv=/LocationProvider|LocationService/i.test(cn);
   var wantWorld=/MapController|WorldMapRenderer|MapViewHandler|HoloholoMapApi|LightshipMapsUtils/i.test(cn);
   if(cn==="LatLng"&&!res.latlng){ /* field layout of the coordinate struct */
     var fo=[];var it2=Memory.alloc(Process.pointerSize);it2.writePointer(ptr(0));var f2;
     while((f2=h.cGF(k,it2))&&!f2.isNull()){try{var tn="?";try{tn=h.tGN(h.fGT(f2)).readCString();}catch(e){}
       fo.push("+0x"+h.fGO(f2).toString(16)+" "+h.fGN(f2).readCString()+" : "+tn);}catch(e){}}
     if(fo.length)res.latlng={cls:cn,fields:fo};
   }
   if(!isProv&&!wantWorld)continue;
   var ms=[],it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
   while((m=h.cGM(k,it))&&!m.isNull()){try{var mn=h.mGN(m).readCString();var rt="?";
     try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}
     if(wantWorld&&mn==="GetWorldLocation"){var ptypes=[];
       for(var pi=0;pi<h.mGPC(m);pi++){try{ptypes.push(h.tGN(h.mGP(m,pi)).readCString());}catch(e){ptypes.push("?");}}
       res.getworld.push(cn+"::GetWorldLocation("+ptypes.join(", ")+") -> "+rt);}
     if(isProv&&/get_Location|Location|Update|Set/i.test(mn))ms.push(mn+"("+h.mGPC(m)+") -> "+rt);
   }catch(e){}}
   if(isProv&&ms.length){var fl=[],it3=Memory.alloc(Process.pointerSize);it3.writePointer(ptr(0));var f3;
     while((f3=h.cGF(k,it3))&&!f3.isNull()){try{var tn3="?";try{tn3=h.tGN(h.fGT(f3)).readCString();}catch(e){}
       if(/LatLng|Location|double/i.test(tn3))fl.push("+0x"+h.fGO(f3).toString(16)+" "+h.fGN(f3).readCString()+" : "+tn3);}catch(e){}}
     res.providers.push({cls:cn,methods:ms.slice(0,10),fields:fl.slice(0,10)});}
  }}
 return res;};
"""


def main():
    sess, pid = pg.get_session()
    sc = sess.create_script(JS); sc.load()
    print("attached", pid, flush=True)
    try:
        r = sc.exports_sync.sweep()
        print("\n=== GetWorldLocation SIGNATURES (screen point -> LatLng) ===")
        for x in (r.get("getworld") or ["(none)"]):
            print("   ", x)
        print("\n=== LatLng struct layout ===")
        ll = r.get("latlng")
        for x in (ll["fields"] if ll else ["(not found)"]):
            print("   ", x)
        print("\n=== CONCRETE LOCATION PROVIDERS ===")
        for p in (r.get("providers") or []):
            print(f"\n  --- {p['cls']} ---")
            for m in p["methods"]:
                print("      m:", m)
            for f in p["fields"]:
                print("      f:", f)
    finally:
        try:
            sc.unload(); sess.detach()
        except Exception:
            pass


main()

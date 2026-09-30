"""RECON (READ-ONLY) for tap-to-move: find (a) what feeds the avatar's position, and (b) any
existing screen<->world/LatLng conversion PoGo already implements, so a double-tap can be turned
into a LatLng without hand-rolling a projection. Pure metadata read, sends nothing."""
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
    aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),
    iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),
    CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),
    cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),
    mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),
    tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),
    fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),
    fGT:b("il2cpp_field_get_type","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function eachClass(cb){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();
 for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());var cnt=h.iGCC(im);
  for(var j=0;j<cnt;j++){var k=h.iGC(im,j);if(!k.isNull())cb(k,h.iGN(im).readCString());}}}
function methods(k){var h=H_();var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
 while((m=h.cGM(k,it))&&!m.isNull()){try{var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}
  out.push({n:h.mGN(m).readCString(),pc:h.mGPC(m),rt:rt});}catch(e){}}return out;}

/* methods whose NAME matches nrx (optionally restricted to classes matching crx) */
rpc.exports.findMethods=function(nrx,crx){var h=H_();var nre=new RegExp(nrx,"i");var cre=crx?new RegExp(crx,"i"):null;
 var out=[];eachClass(function(k,img){var cn;try{cn=h.CGN(k).readCString();}catch(e){return;}
  if(cre&&!cre.test(cn))return;var ms=methods(k);
  for(var i=0;i<ms.length;i++){if(nre.test(ms[i].n)&&out.length<70)out.push(cn+"::"+ms[i].n+"("+ms[i].pc+") -> "+ms[i].rt);}});
 return out;};
/* any method that RETURNS a LatLng — that is the screen/world -> coordinate converter we want */
rpc.exports.returnsLatLng=function(){var h=H_();var out=[];eachClass(function(k){var cn;try{cn=h.CGN(k).readCString();}catch(e){return;}
 var ms=methods(k);for(var i=0;i<ms.length;i++){if(/LatLng/.test(ms[i].rt)&&ms[i].pc>0&&out.length<60)
  out.push(cn+"::"+ms[i].n+"("+ms[i].pc+") -> "+ms[i].rt);}});return out;};
rpc.exports.dump=function(nm){var h=H_();var f=null;eachClass(function(k){if(f)return;try{if(h.CGN(k).readCString()===nm)f=k;}catch(e){}});
 if(!f)return null;return methods(f).map(function(m){return m.n+"("+m.pc+") -> "+m.rt;});};
rpc.exports.fields=function(nm){var h=H_();var f=null;eachClass(function(k){if(f)return;try{if(h.CGN(k).readCString()===nm)f=k;}catch(e){}});
 if(!f)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var fl;
 while((fl=h.cGF(f,it))&&!fl.isNull()){try{var tn="?";try{tn=h.tGN(h.fGT(fl)).readCString();}catch(e){}
  out.push("+0x"+h.fGO(fl).toString(16)+"  "+h.fGN(fl).readCString()+" : "+tn);}catch(e){}}return out;};
"""


def main():
    sess, pid = pg.get_session()
    sc = sess.create_script(JS); sc.load()
    print("attached", pid, flush=True)
    try:
        print("\n=== [A] METHODS RETURNING LatLng (screen/world -> coordinate) ===")
        for x in (sc.exports_sync.returns_lat_lng() or ["(none)"])[:30]:
            print("   ", x)
        print("\n=== [B] ILocationProvider (what feeds the avatar) ===")
        for x in (sc.exports_sync.dump("ILocationProvider") or ["(not found)"]):
            print("   ", x)
        print("\n=== [C] screen<->world conversion helpers ===")
        for x in (sc.exports_sync.find_methods("ScreenToWorld|WorldToScreen|ScreenPointTo|Unproject|ToLatLng|FromWorld") or ["(none)"])[:25]:
            print("   ", x)
        print("\n=== [D] location provider implementations ===")
        for x in (sc.exports_sync.find_methods("get_CurrentLocation|SetLocation|get_Location", "LocationProvider|LocationService|LocationManager") or ["(none)"])[:25]:
            print("   ", x)
    finally:
        try:
            sc.unload(); sess.detach()
        except Exception:
            pass


main()

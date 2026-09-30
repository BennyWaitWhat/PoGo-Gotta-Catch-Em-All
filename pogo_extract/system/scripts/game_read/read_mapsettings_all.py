"""READ-ONLY: dump ALL live MapSettingsProto tunable values (despawn range, nearby-hide,
refresh, ranges) so we know current state before tweaking despawn / max-show."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function kp(k){var b=[];var t=k;for(var i=0;i<8;i++){var v=t.and(0xff).toInt32();b.push((v<16?"0":"")+v.toString(16));t=t.shr(8);}return b.join(" ");}
rpc.exports.go=function(){
 var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();var img=null;
 for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()==="holo-protos.dll"){img=im;break;}}
 var k=h.cFN(img,Memory.allocUtf8String("Holoholo.Rpc"),Memory.allocUtf8String("MapSettingsProto"));
 if(k.isNull())return{err:"no class"};
 var pat=kp(k);var out=[];
 Process.enumerateRanges("rw-").forEach(function(r){if(r.file||r.size<4096||r.size>67108864)return;
   try{var hs=Memory.scanSync(r.base,r.size,pat);for(var i=0;i<hs.length&&out.length<300;i++){var p=hs[i].address;
     try{var vis=p.add(0x10).readDouble();if(isNaN(vis)||vis<0||vis>100000)continue;
       out.push({addr:p.toString(),visible:vis,pokenav:p.add(0x18).readDouble(),encounter:p.add(0x20).readDouble(),minRefresh:p.add(0x28).readFloat(),maxRefresh:p.add(0x2c).readFloat(),minDist:p.add(0x30).readFloat(),minNearbyHideSightings:p.add(0x40).readS32(),despawnRange:p.add(0x60).readDouble()});
     }catch(e){}}}catch(e){}});
 return out;
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        r = sc.exports_sync.go()
        sess.detach()
        if isinstance(r, dict) and r.get("err"):
            print("ERR", r["err"]); return
        good = [s for s in r if 20 <= s["visible"] <= 400 and 20 <= s["encounter"] <= 400]
        print(f"{len(r)} heap matches, {len(good)} plausible MapSettings instances:")
        for s in good[:6]:
            print(f"  @{s['addr']}  visible={s['visible']}  encounter={s['encounter']}  despawnRange={s['despawnRange']}  "
                  f"minNearbyHideSightings={s['minNearbyHideSightings']}  refresh={s['minRefresh']}/{s['maxRefresh']}  minDist={s['minDist']}  pokenav={s['pokenav']}")
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

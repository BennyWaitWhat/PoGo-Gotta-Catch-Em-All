"""TEST: make PoGo treat the emulated VGP3 as a GO Plus + (Waina) device so the Ultra-Ball pref is
honored. Overrides PgpService.get_IsPairedWainaDeviceKind -> true and get_IsPairedPgpDeviceKind ->
false (onLeave retval replace), and ensures WainaPreferences.Ball=ULTRA_BALL(3). Holds the hooks for
the window so the user can reconnect VGP3 + catch + watch the Ultra count. SAFE: no in-hook dumps,
just boolean retval overrides. Reverts when it detaches."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

HOLD = 80

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return k;}catch(e){}}return null;}
function kp(k){var b=[];var t=ptr(k);for(var i=0;i<8;i++){var v=t.and(0xff).toInt32();b.push((v<16?"0":"")+v.toString(16));t=t.shr(8);}return b.join(" ");}
var calls={waina:0,pgp:0};
function hookBool(cls,name,val){var h=H_();if(!cls)return name+":NOCLS";var m=h.cMN(cls,Memory.allocUtf8String(name),0);if(!m||m.isNull())return name+":NOMETHOD";var ad=m.readPointer();if(ad.isNull())return name+":NOADDR";
 Interceptor.attach(ad,{onLeave:function(r){try{if(name.indexOf("Waina")>=0)calls.waina++;else calls.pgp++;r.replace(ptr(val));}catch(e){}}});return name+":HOOKED="+val;}
rpc.exports.setup=function(){
 var h=H_();var out=[];
 var ps=findClass("holo-game.dll","PgpService");
 out.push(hookBool(ps,"get_IsPairedWainaDeviceKind",1));
 out.push(hookBool(ps,"get_IsPairedPgpDeviceKind",0));
 // also try interface IPgpService if present
 var ips=findClass("holo-game.dll","IPgpService");
 if(ips){out.push(hookBool(ips,"get_IsPairedWainaDeviceKind",1));out.push(hookBool(ips,"get_IsPairedPgpDeviceKind",0));}
 // ensure WainaPreferences.Ball = ULTRA_BALL (3)
 var wp=findClass("holo-protos.dll","WainaPreferences");var nset=0;
 if(wp){var pat=kp(wp);Process.enumerateRanges("rw-").forEach(function(r){if(r.file||r.size<256||r.size>134217728)return;try{var hs=Memory.scanSync(r.base,r.size,pat);for(var i=0;i<hs.length;i++){var p=hs[i].address;try{var v=p.add(0x10).readS32();if(v>=1&&v<=2){p.add(0x10).writeS32(3);nset++;}}catch(e){}}}catch(e){}});}
 out.push("WainaPreferences.Ball set to 3 on "+nset+" instances");
 return out;
};
rpc.exports.calls=function(){return calls;};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        st = sc.exports_sync.setup()
        print("setup:")
        for s in st:
            print("  ", s)
        print(f"\n*** SPOOF ACTIVE for {HOLD}s ***")
        print("  1) Toggle VGP3 OFF then ON (so it re-handshakes while spoofed as Waina)")
        print("  2) Let it catch a few")
        print("  3) Watch your ULTRA ball count")
        time.sleep(HOLD)
        print("\ndevice-kind checks intercepted during window:", sc.exports_sync.calls())
        print("spoof released (reverted). Report: did Ultra count drop, or Poke?")
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

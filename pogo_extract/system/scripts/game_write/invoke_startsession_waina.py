"""Force VGP3 to re-handshake as a GO Plus + (WAINA): grab PgpService.get_ConnectedDevice(), stamp its
DeviceKind=WAINA(3), ensure WainaPreferences.Ball=ULTRA(3), then invoke PgpService.StartSession(device,
true) to re-announce the session as Waina (Pokemod's own reconnect path). Hook also stamps WAINA on any
StartSession that fires. User then watches: does it still AUTO-catch, and does ULTRA drop? Reverts on
detach (reconnect VGP3 normally to restore basic kind)."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

HOLD = 70

MY_JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return k;}catch(e){}}return null;}
function kp(k){var b=[];var t=ptr(k);for(var i=0;i<8;i++){var v=t.and(0xff).toInt32();b.push((v<16?"0":"")+v.toString(16));t=t.shr(8);}return b.join(" ");}
var fired=0;
rpc.exports.go=function(psStr){
 var h=H_();var ps=ptr(psStr);var psCls=h.OGC(ps);
 var mSS=h.cMN(psCls,Memory.allocUtf8String("StartSession"),2);if(!mSS||mSS.isNull())return{err:"no StartSession"};
 var ssAd=mSS.readPointer();
 Interceptor.attach(ssAd,{onEnter:function(a){try{var dev=a[1];if(!dev.isNull())dev.add(0x1c).writeS32(3);fired++;}catch(e){}}});
 var mGCD=h.cMN(psCls,Memory.allocUtf8String("get_ConnectedDevice"),0);if(!mGCD||mGCD.isNull())return{err:"no get_ConnectedDevice"};
 var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));
 var dev=h.rI(mGCD,ps,ptr(0),exc);
 if(!dev||dev.isNull())return{err:"ConnectedDevice is null (VGP3 not connected?)"};
 var curKind=-1;try{curKind=dev.add(0x1c).readS32();}catch(e){}
 try{dev.add(0x1c).writeS32(3);}catch(e){}
 var wp=findClass("holo-protos.dll","WainaPreferences");var nb=0;
 if(wp){var pat=kp(wp);Process.enumerateRanges("rw-").forEach(function(r){if(r.file||r.size<256||r.size>134217728)return;try{var hs=Memory.scanSync(r.base,r.size,pat);for(var i=0;i<hs.length;i++){var p=hs[i].address;try{var v=p.add(0x10).readS32();if(v>=1&&v<=2){p.add(0x10).writeS32(3);nb++;}}catch(e){}}}catch(e){}});}
 var bb=Memory.alloc(1);bb.writeU8(1);
 var args=Memory.alloc(2*Process.pointerSize);args.writePointer(dev);args.add(Process.pointerSize).writePointer(bb);
 var exc2=Memory.alloc(Process.pointerSize);exc2.writePointer(ptr(0));
 var ret=h.rI(mSS,ps,args,exc2);
 var ep=exc2.readPointer();var en=null;if(!ep.isNull()){try{en=h.CGN(h.OGC(ep)).readCString();}catch(e){en="?";}}
 return {curKind:curKind,setKind:3,ballSetOn:nb,invokedStartSession:true,startSessionFired:fired,exception:en};
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        finder = pg.get_script_with_helpers(sess)
        sc = pg.get_script_with_helpers(sess, MY_JS)
        try:
            r = finder.exports_sync.find_singleton("Niantic.Holoholo.Pgp", "PgpService")
            hits = r.get("hits", []) if isinstance(r, dict) else []
            print(f"PgpService instances: {len(hits)}")
            res = None
            for ps in hits:
                res = sc.exports_sync.go(ps)
                print(f"  go({ps}): {res}")
                if isinstance(res, dict) and res.get("invokedStartSession"):
                    break
            if not (res and res.get("invokedStartSession")):
                print("could not invoke StartSession on any PgpService instance."); return
            print(f"\n*** Re-announced session as WAINA (was kind {res.get('curKind')}). Hooks held {HOLD}s. ***")
            print("  WATCH: 1) does VGP3 still AUTO-catch (no button)?  2) does ULTRA count drop?")
            time.sleep(HOLD)
            print("\nreleased (reverted). Reconnect VGP3 normally if it got stuck. Report: auto-catch? Ultra or Poke?")
            sess.detach()
        finally:
            try: sc.unload(); finder.unload()
            except Exception: pass
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

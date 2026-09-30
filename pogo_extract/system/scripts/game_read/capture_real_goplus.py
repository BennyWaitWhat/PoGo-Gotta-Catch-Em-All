"""READ-ONLY capture of the REAL Go Plus + (Waina) so we learn the exact recipe VGP3 must mimic.
Hooks (observe only, no writes/invokes):
  - PgpService.StartSession(ScannedWearableDevice,bool)  -> log the device kind it announces (expect WAINA=3)
  - PgpService.get_IsPairedWainaDeviceKind                -> count when it flips true
  - PgpActivityMonitor.xek(ActionLogEntry)                -> count catches (no dump = safe)
User: disconnect VGP3, PAIR the real Go Plus +, do a couple ULTRA catches (button). Then we compare."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

KIND = {0: "UNSET", 1: "POKEMON_GO_PLUS", 2: "POKE_BALL_PLUS", 3: "WAINA"}
HOLD = 240

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
var ss=[],wainaTrue=0,catches=0;
rpc.exports.setup=function(){
 var h=H_();var gim=img("holo-game.dll");
 var st={};
 var PS=h.cFN(gim,Memory.allocUtf8String("Niantic.Holoholo.Pgp"),Memory.allocUtf8String("PgpService"));
 var mSS=PS.isNull()?null:h.cMN(PS,Memory.allocUtf8String("StartSession"),2);
 if(mSS&&!mSS.isNull()){var ad=mSS.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){try{var dev=a[1];var k=dev.isNull()?-1:dev.add(0x1c).readS32();ss.push(k);}catch(e){}}});st.startSession=true;}}
 var mW=PS.isNull()?null:h.cMN(PS,Memory.allocUtf8String("get_IsPairedWainaDeviceKind"),0);
 if(mW&&!mW.isNull()){var ad2=mW.readPointer();if(!ad2.isNull()){Interceptor.attach(ad2,{onLeave:function(r){try{if(r.toInt32&&r.toInt32()!==0)wainaTrue++;}catch(e){}}});st.wainaGetter=true;}}
 var PAM=h.cFN(gim,Memory.allocUtf8String("Niantic.Holoholo.Pgp"),Memory.allocUtf8String("PgpActivityMonitor"));
 var mXek=PAM.isNull()?null:h.cMN(PAM,Memory.allocUtf8String("xek"),1);
 if(mXek&&!mXek.isNull()){var ad3=mXek.readPointer();if(!ad3.isNull()){Interceptor.attach(ad3,{onEnter:function(a){catches++;}});st.catchHook=true;}}
 return st;
};
rpc.exports.results=function(){return {startSessionKinds:ss,wainaGetterTrue:wainaTrue,catches:catches};};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        print("setup:", sc.exports_sync.setup())
        print(f"\n*** Capturing for {HOLD}s ***")
        print("  1) Disconnect VGP3")
        print("  2) PAIR your REAL Go Plus + (Waina)")
        print("  3) Do a couple ULTRA catches (button press)")
        time.sleep(HOLD)
        r = sc.exports_sync.results()
        kinds = [KIND.get(k, str(k)) for k in r.get("startSessionKinds", [])]
        print(f"\nStartSession fired with kinds: {kinds}")
        print(f"get_IsPairedWaina returned true: {r.get('wainaGetterTrue')} times")
        print(f"catches observed (xek): {r.get('catches')}")
        if not kinds:
            print(">>> StartSession never fired — the real device may also bypass it, or it wasn't paired in time.")
        elif 3 in r.get("startSessionKinds", []):
            print(">>> WAINA confirmed at StartSession — that's the kind VGP3 must announce.")
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

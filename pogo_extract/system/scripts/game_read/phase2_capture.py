"""PHASE 2: capture the real WAINA (Go Plus +) Ultra catch. READ-ONLY.
  - read WainaPreferences.Ball (the selected ball)
  - hook PgpActivityMonitor.xek (the catch handler) -> count, to see if WAINA catches run the same path
User button-catches a few during the window. Confirms: WAINA + Ball=Ultra -> Ultra, and the catch path."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

ITEM = {0: "UNKNOWN", 1: "POKE_BALL", 2: "GREAT_BALL", 3: "ULTRA_BALL"}
HOLD = 60

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return k;}catch(e){}}return null;}
function kp(k){var b=[];var t=ptr(k);for(var i=0;i<8;i++){var v=t.and(0xff).toInt32();b.push((v<16?"0":"")+v.toString(16));t=t.shr(8);}return b.join(" ");}
var catches=0;
rpc.exports.setup=function(){
 var h=H_();var st={catches:0,balls:[]};
 var PAM=h.cFN(img("holo-game.dll"),Memory.allocUtf8String("Niantic.Holoholo.Pgp"),Memory.allocUtf8String("PgpActivityMonitor"));
 var mXek=PAM&&!PAM.isNull()?h.cMN(PAM,Memory.allocUtf8String("xek"),1):null;
 if(mXek&&!mXek.isNull()){var ad=mXek.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){catches++;}});st.xekHooked=true;}}
 var wp=findClass("holo-protos.dll","WainaPreferences");
 if(wp){var pat=kp(wp);var seen={};Process.enumerateRanges("rw-").forEach(function(r){if(r.file||r.size<256||r.size>134217728)return;try{var hs=Memory.scanSync(r.base,r.size,pat);for(var i=0;i<hs.length;i++){var p=hs[i].address;try{var v=p.add(0x10).readS32();if(v>=0&&v<=6)seen[v]=(seen[v]||0)+1;}catch(e){}}}catch(e){}});st.balls=Object.keys(seen).map(function(k){return k+"x"+seen[k];});}
 return st;
};
rpc.exports.results=function(){return {catches:catches};};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        st = sc.exports_sync.setup()
        balls = st.get("balls", [])
        print("WainaPreferences.Ball values found:", [f"{ITEM.get(int(b.split('x')[0]), b.split('x')[0])}({b})" for b in balls])
        print(f"xek hooked: {st.get('xekHooked')}")
        print(f"\n*** Button-catch a few with your PGP+ for {HOLD}s — watch the Ultra count ***")
        time.sleep(HOLD)
        r = sc.exports_sync.results()
        sess.detach()
        print(f"\ncatches through xek (the Go-Plus action-log handler): {r.get('catches')}")
        if r.get("catches", 0) > 0:
            print(">>> WAINA catches DO run through xek — same handler as VGP3. So the difference is purely the device kind, not the catch path.")
        else:
            print(">>> WAINA catches did NOT hit xek — it uses a different path. Tell me if you actually caught any.")
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

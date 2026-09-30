"""Set WainaPreferences.Ball (Go Plus + auto-throw ball) to ULTRA_BALL (3).
Writes the live preference instance(s), verifies the read-back. Persistence to the SERVER is then
tested with a real VGP3 catch (client write may or may not be enough; if not, the save RPC / in-game
toggle is needed). READ current -> WRITE 3 -> RE-READ."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

ITEM = {0: "UNKNOWN", 1: "POKE_BALL", 2: "GREAT_BALL", 3: "ULTRA_BALL", 4: "MASTER_BALL"}
TARGET = 3  # ULTRA_BALL

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return k;}catch(e){}}return null;}
function kp(k){var b=[];var t=ptr(k);for(var i=0;i<8;i++){var v=t.and(0xff).toInt32();b.push((v<16?"0":"")+v.toString(16));t=t.shr(8);}return b.join(" ");}
rpc.exports.findInstances=function(){
 var h=H_();var k=findClass("holo-protos.dll","WainaPreferences");if(!k)return{err:"no class"};
 var pat=kp(k);var out=[];
 Process.enumerateRanges("rw-").forEach(function(r){if(r.file||r.size<256||r.size>134217728)return;try{var hs=Memory.scanSync(r.base,r.size,pat);for(var i=0;i<hs.length&&out.length<40;i++)out.push(hs[i].address.toString());}catch(e){}});
 return {hits:out};
};
rpc.exports.readBall=function(a){try{return ptr(a).add(0x10).readS32();}catch(e){return null;}};
rpc.exports.writeBall=function(a,v){try{ptr(a).add(0x10).writeS32(v);return true;}catch(e){return false;}};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        r = sc.exports_sync.find_instances()
        if isinstance(r, dict) and r.get("err"):
            print("ERR:", r["err"]); return
        hits = r.get("hits", [])
        patched = 0
        for a in hits:
            cur = sc.exports_sync.read_ball(a)
            if cur in (1, 2):  # real pref instance (Poke/Great currently)
                ok = sc.exports_sync.write_ball(a, TARGET)
                now = sc.exports_sync.read_ball(a)
                print(f"  @{a}  {ITEM.get(cur)} -> {ITEM.get(now)}  (write {'ok' if ok else 'FAIL'})")
                patched += 1
        if patched == 0:
            vals = sorted(set(v for v in (sc.exports_sync.read_ball(a) for a in hits) if v is not None))
            print(f"  no instance with Ball in (1,2) found. Ball values seen: {vals}")
        else:
            print(f"\nset {patched} instance(s) to ULTRA_BALL (client-side).")
            print("NOW TEST: trigger a VGP3 catch and watch which ball it throws / which ball count drops.")
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

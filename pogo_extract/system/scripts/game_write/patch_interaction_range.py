"""TEST PATCH (reversible): raise ClientMapObjectsInteractionRangeSettingsProto.InteractionRangeMeters
from ~80 to 140 so the VPGP Go-Plus catches as far as you can see (matching SpawnBooster's
EncounterRangeMeters=140, which the server already honors for manual catches).
Writes the live instance(s) and re-applies every 3s for the hold window, then leaves it set.
Run while WALKING to test whether VPGP now catches the far visible mons. READ value first, then write."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

NEW_VAL = 325.0
HOLD_SECS = 60

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
 var h=H_();var k=findClass("holo-protos.dll","ClientMapObjectsInteractionRangeSettingsProto");if(!k)return{err:"no class"};
 var pat=kp(k);var out=[];
 Process.enumerateRanges("rw-").forEach(function(r){if(r.file||r.size<256||r.size>134217728)return;
   try{var hs=Memory.scanSync(r.base,r.size,pat);for(var i=0;i<hs.length&&out.length<60;i++){var p=hs[i].address;
     try{var v=p.add(0x10).readDouble();if(v>10&&v<400)out.push({addr:p.toString(),cur:v});}catch(e){}}}catch(e){}});
 return {hits:out};
};
rpc.exports.readD=function(a,o){try{return ptr(a).add(o).readDouble();}catch(e){return null;}};
rpc.exports.writeD=function(a,o,v){try{ptr(a).add(o).writeDouble(v);return true;}catch(e){return false;}};
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
        targets = [h for h in hits if 60 <= h["cur"] < 320]  # anything below the 325 target
        print(f"found {len(hits)} instance(s); patching {len(targets)} (InteractionRangeMeters < 320):")
        for h in targets:
            ok = sc.exports_sync.write_d(h["addr"], 0x10, NEW_VAL)
            now = sc.exports_sync.read_d(h["addr"], 0x10)
            print(f"  @{h['addr']}  {h['cur']} -> {now}  (write {'ok' if ok else 'FAIL'})")
        if not targets:
            print(f"  nothing below 320 to patch; current value(s): {[h['cur'] for h in hits]} (already at 325?)."); return
        print(f"\nHOLDING {HOLD_SECS}s — WALK NOW and watch if VPGP catches the far visible mons. Re-applying every 3s...")
        end = time.time() + HOLD_SECS
        reverts = 0
        while time.time() < end:
            time.sleep(3)
            for h in targets:
                cur = sc.exports_sync.read_d(h["addr"], 0x10)
                if cur is not None and abs(cur - NEW_VAL) > 0.5:
                    reverts += 1
                    sc.exports_sync.write_d(h["addr"], 0x10, NEW_VAL)
        print(f"\nheld {HOLD_SECS}s ({reverts} re-applies). InteractionRangeMeters left at {NEW_VAL}.")
        print("Detaching now — the written value persists until the GameMaster re-parses; tell me what you saw.")
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

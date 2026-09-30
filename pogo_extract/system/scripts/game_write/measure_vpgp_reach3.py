"""CONFIRM the patch: (1) ensure ClientMapObjectsInteractionRangeSettingsProto.InteractionRangeMeters=200,
(2) measure Go-Plus targeting reach over a walk via WildMapPokemon.Initialize (visible) + PgpActivityMonitor.xeh (targeted).
Baseline (range=80) gave max-target ~41m = ~1/3 of visible. If the patch works, max-target should now
track max-visible (ratio -> ~1.0). READ-ONLY except the idempotent range write."""
import sys, time, math, os, statistics
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","int",["pointer"]),mGP:b("il2cpp_method_get_param","pointer",["pointer","int"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function ffield(cls,sub){var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;var ex=-1,su=-1;while((f=h.cGF(cls,it))&&!f.isNull()){try{var nm=h.fGN(f).readCString().toLowerCase();var off=h.fGO(f);if(nm===sub||nm===sub+"_"){if(ex<0)ex=off;}else if(nm.indexOf(sub)>=0){if(su<0)su=off;}}catch(e){}}return ex>=0?ex:su;}
function fparam(cls,name,sub){var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(cls,it))&&!m.isNull()){try{if(h.mGN(m).readCString()===name&&h.mGPC(m)===1){var pt=h.mGP(m,0);if(pt&&!pt.isNull()&&h.tGN(pt).readCString().indexOf(sub)>=0)return m;}}catch(e){}}return null;}
function findClass(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return k;}catch(e){}}return null;}
function kp(k){var b=[];var t=ptr(k);for(var i=0;i<8;i++){var v=t.and(0xff).toInt32();b.push((v<16?"0":"")+v.toString(16));t=t.shr(8);}return b.join(" ");}
var pos={},targets={},OFF={},rangeAddr=null;
rpc.exports.setup=function(){
 var h=H_();var pim=img("holo-protos.dll"),gim=img("holo-game.dll");
 var WP=h.cFN(pim,Memory.allocUtf8String("Holoholo.Rpc"),Memory.allocUtf8String("WildPokemonProto"));
 OFF.lat=ffield(WP,"latitude");OFF.lng=ffield(WP,"longitude");
 var WMP=h.cFN(gim,Memory.allocUtf8String("Niantic.Holoholo.Map"),Memory.allocUtf8String("WildMapPokemon"));
 var mInit=WMP.isNull()?null:fparam(WMP,"Initialize","WildPokemonProto");
 var PAM=h.cFN(gim,Memory.allocUtf8String("Niantic.Holoholo.Pgp"),Memory.allocUtf8String("PgpActivityMonitor"));
 var mXeh=PAM.isNull()?null:h.cMN(PAM,Memory.allocUtf8String("xeh"),2);
 var st={};
 if(mInit&&!mInit.isNull()){var ad=mInit.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){try{var self=a[0].toString();var p=a[1];var la=p.add(OFF.lat).readDouble(),lo=p.add(OFF.lng).readDouble();if(la!==0&&Math.abs(la)<=90)pos[self]={lat:la,lng:lo};}catch(e){}}});st.init=true;}}
 if(mXeh&&!mXeh.isNull()){var ad2=mXeh.readPointer();if(!ad2.isNull()){Interceptor.attach(ad2,{onEnter:function(a){try{var t=a[2];if(t.isNull())return;targets[t.toString()]=Date.now();}catch(e){}}});st.xeh=true;}}
 // ensure InteractionRangeMeters=200
 var k=findClass("holo-protos.dll","ClientMapObjectsInteractionRangeSettingsProto");
 if(k){var pat=kp(k);Process.enumerateRanges("rw-").forEach(function(r){if(rangeAddr||r.file||r.size<256||r.size>134217728)return;try{var hs=Memory.scanSync(r.base,r.size,pat);for(var i=0;i<hs.length;i++){var p=hs[i].address;try{var v=p.add(0x10).readDouble();if(v>50&&v<300){rangeAddr=p;break;}}catch(e){}}}catch(e){}});}
 var before=null,after=null;
 if(rangeAddr){before=ptr(rangeAddr).add(0x10).readDouble();ptr(rangeAddr).add(0x10).writeDouble(200.0);after=ptr(rangeAddr).add(0x10).readDouble();}
 st.rangeBefore=before;st.rangeAfter=after;
 return st;
};
rpc.exports.results=function(){return {pos:pos,targets:Object.keys(targets)};};
rpc.exports.readRange=function(){try{return rangeAddr?ptr(rangeAddr).add(0x10).readDouble():null;}catch(e){return null;}};
rpc.exports.reapply=function(){try{if(rangeAddr){ptr(rangeAddr).add(0x10).writeDouble(200.0);return true;}}catch(e){}return false;};
"""


def hav(a, b):
    R = 6371000.0
    dp = math.radians(b[0] - a[0]); dl = math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1, math.sqrt(x)))


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        st = sc.exports_sync.setup()
        print("setup:", st)
        secs = 70
        print(f"\ncollecting {secs}s — WALK normally and let VPGP catch...")
        end = time.time() + secs
        while time.time() < end:
            time.sleep(7)
            sc.exports_sync.reapply()
        r = sc.exports_sync.results()
        rng = sc.exports_sync.read_range()
        sess.detach()
        pos = r["pos"]; tptrs = r["targets"]
        print(f"\nInteractionRangeMeters now: {rng}")
        print(f"visible mons: {len(pos)}   unique Go-Plus targets: {len(tptrs)}")
        if len(pos) < 4:
            print("too few mons — walk more / re-run."); return
        center = (statistics.median([p["lat"] for p in pos.values()]),
                  statistics.median([p["lng"] for p in pos.values()]))
        vis = sorted(hav(center, (p["lat"], p["lng"])) for p in pos.values())
        tgt = sorted(hav(center, (pos[t]["lat"], pos[t]["lng"])) for t in tptrs if t in pos)
        matched = len(tgt)

        def rep(name, ds):
            if not ds:
                print(f"  {name}: none"); return
            print(f"  {name}: n={len(ds)}  median={ds[len(ds)//2]:.0f}m  MAX={max(ds):.0f}m")
        print("\n=== distance from player-center ===")
        rep("VISIBLE", vis)
        rep("GO-PLUS TARGETED", tgt)
        if tgt:
            print(f"     targeted dists: {[round(x) for x in tgt]}")
        if tgt and vis:
            ratio = max(tgt) / max(vis) if max(vis) else 0
            print(f"\n>>> targeted/visible ratio = {ratio:.2f}  (baseline at range=80 was ~0.34)")
            if ratio >= 0.7:
                print("    CONFIRMED: catch reach now tracks visible range — the wider sweep is LIVE.")
            elif matched < 3:
                print("    (too few matched targets for a clean verdict — walk a denser/longer route.)")
            else:
                print("    catch reach still below visible — patch may not be fully effective; re-examine.")
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

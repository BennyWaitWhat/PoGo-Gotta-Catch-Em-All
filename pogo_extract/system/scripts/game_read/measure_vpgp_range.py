"""EMPIRICAL VPGP reach test (v2). Records every wild mon's GPS (WildPokemonProto
.MergeFrom, read ON EXIT so fields are populated) keyed by encounterId, and the
encounterIds VPGP actually engages (Encounter/Catch request WriteTo). The player sits
at the center of visible spawns, so we estimate player = median(mon positions) and
compare:
  - VISIBLE spread  (max mon distance from center)   -> should be ~140 if SpawnBooster on
  - ENGAGED spread  (distance of mons VPGP catches)  -> the true VPGP catch reach
If engaged ~= visible -> catch range extends; if engaged ~40 while visible ~140 ->
visibility-only. READ-ONLY."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","int",["pointer"]),mGP:b("il2cpp_method_get_param","pointer",["pointer","int"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function gameImg(){return img("holo-game.dll");}
function findMethodByParam(cls,name,sub){var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(cls,it))&&!m.isNull()){try{if(h.mGN(m).readCString()===name&&h.mGPC(m)===1){var pt=h.mGP(m,0);if(pt&&!pt.isNull()&&h.tGN(pt).readCString().indexOf(sub)>=0)return m;}}catch(e){}}return null;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function offs(cls){var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;var o={};while((f=h.cGF(cls,it))&&!f.isNull()){try{o[h.fGN(f).readCString()]=h.fGO(f);}catch(e){}}return o;}
function fo(o,subs){for(var k in o){var lk=k.toLowerCase();for(var i=0;i<subs.length;i++)if(lk===subs[i]||lk===subs[i]+"_")return o[k];}for(var k in o){var lk=k.toLowerCase();for(var i=0;i<subs.length;i++)if(lk.indexOf(subs[i])>=0)return o[k];}return -1;}

var monPos={}, engaged=[], OFF={};
rpc.exports.setup=function(){
 var h=H_(); var pim=img("holo-protos.dll"); if(!pim)return{err:"no holo-protos"};
 function C(c){return h.cFN(pim,Memory.allocUtf8String("Holoholo.Rpc"),Memory.allocUtf8String(c));}
 var WP=C("WildPokemonProto"),EN=C("EncounterProto"),CP=C("CatchPokemonProto");
 var wo=offs(WP),eo=EN.isNull()?{}:offs(EN),co=CP.isNull()?{}:offs(CP);
 OFF.wpEnc=fo(wo,["encounterid"]);OFF.wpLat=fo(wo,["latitude"]);OFF.wpLng=fo(wo,["longitude"]);
 OFF.enEnc=fo(eo,["encounterid"]);OFF.cpEnc=fo(co,["encounterid"]);
 function hookLeave(cls,name,argc,cb){var m=h.cMN(cls,Memory.allocUtf8String(name),argc);if(!m||m.isNull())return false;var ad=m.readPointer();if(ad.isNull())return false;Interceptor.attach(ad,{onEnter:function(a){this.self=a[0];},onLeave:function(){try{cb(this.self);}catch(e){}}});return true;}
 function hookEnter(cls,name,argc,cb){var m=h.cMN(cls,Memory.allocUtf8String(name),argc);if(!m||m.isNull())return false;var ad=m.readPointer();if(ad.isNull())return false;Interceptor.attach(ad,{onEnter:function(a){try{cb(a[0]);}catch(e){}}});return true;}
 var st={};
 var WMP=h.cFN(gameImg(),Memory.allocUtf8String("Niantic.Holoholo.Map"),Memory.allocUtf8String("WildMapPokemon"));
 var mInit=(WMP&&!WMP.isNull())?findMethodByParam(WMP,"Initialize","WildPokemonProto"):null;
 st.wp=false;
 if(mInit&&!mInit.isNull()){var ad=mInit.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){try{var s=a[1];if(OFF.wpEnc<0||OFF.wpLat<0)return;var enc=s.add(OFF.wpEnc).readU64().toString();var la=s.add(OFF.wpLat).readDouble(),lo=s.add(OFF.wpLng).readDouble();if(la!==0&&Math.abs(la)<=90&&Math.abs(lo)<=180)monPos[enc]={lat:la,lng:lo};}catch(e){}}});st.wp=true;}}
 st.en = !EN.isNull() && hookEnter(EN,"WriteTo",1,function(s){if(OFF.enEnc<0)return;engaged.push({k:"encounter",enc:s.add(OFF.enEnc).readU64().toString()});});
 st.cp = !CP.isNull() && hookEnter(CP,"WriteTo",1,function(s){if(OFF.cpEnc<0)return;engaged.push({k:"catch",enc:s.add(OFF.cpEnc).readU64().toString()});});
 return {OFF:OFF, hooks:st};
};
rpc.exports.results=function(){return {monPos:monPos, engaged:engaged};};
"""


def hav(a, b):
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = math.radians(b[0] - a[0]); dl = math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1, math.sqrt(x)))


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        st = sc.exports_sync.setup()
        print("setup:", st)
        if st.get("err"):
            return
        secs = 90
        print(f"\ncollecting {secs}s — keep PoGo on the map with VPGP catching...")
        time.sleep(secs)
        res = sc.exports_sync.results()
        sess.detach()
        mons = res["monPos"]
        print(f"\nwild mons seen: {len(mons)}   engage events: {len(res['engaged'])}")
        if len(mons) < 5:
            print("Too few mons captured — GetMapObjects may not have refreshed. Move a bit / re-run.")
            return
        lats = [p["lat"] for p in mons.values()]
        lngs = [p["lng"] for p in mons.values()]
        center = (statistics.median(lats), statistics.median(lngs))
        print(f"estimated player center: {center[0]:.6f}, {center[1]:.6f}")

        def dist(enc):
            p = mons.get(enc)
            return hav(center, (p["lat"], p["lng"])) if p else None

        vis = sorted(hav(center, (p["lat"], p["lng"])) for p in mons.values())
        eng = sorted(d for d in (dist(e["enc"]) for e in res["engaged"]) if d is not None)

        def rep(name, ds):
            if not ds:
                print(f"  {name}: none"); return
            print(f"  {name}: n={len(ds)}  median={ds[len(ds)//2]:.0f}m  p90={ds[int(len(ds)*0.9)]:.0f}m  MAX={max(ds):.0f}m")
        print("\n=== distance from player-center ===")
        rep("VISIBLE mons", vis)
        rep("ENGAGED by VPGP", eng)
        print(f"     engaged distances: {[round(x) for x in eng]}")
        print("\n(player-center is estimated as the median of visible spawns; expect +/-15-30m. "
              "Default encounter range ~40m; SpawnBooster sets 140.)")
        if eng:
            vmax = max(vis); emax = max(eng)
            if emax > 70:
                print(f"\n>>> VERDICT: VPGP engages mons out to ~{emax:.0f}m — catch range DOES extend (not visibility-only).")
            elif vmax > 90 and emax < 60:
                print(f"\n>>> VERDICT: visible to ~{vmax:.0f}m but VPGP only engages within ~{emax:.0f}m — VISIBILITY-ONLY; catch range NOT extended.")
            else:
                print(f"\n>>> VERDICT: engaged max ~{emax:.0f}m (visible ~{vmax:.0f}m) — inconclusive, re-run with more catches.")
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

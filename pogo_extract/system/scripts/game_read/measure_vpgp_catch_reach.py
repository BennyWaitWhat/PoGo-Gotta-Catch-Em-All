"""EMPIRICAL (corrected): measure the REAL VPGP Go-Plus catch reach via the action log.
  - WildMapPokemon.Initialize(WildPokemonProto) -> record every on-map mon {encId:(lat,lng,pid)}
  - PgpActivityMonitor.xek(ActionLogEntry) [=HandleActionLog] -> invoke get_CatchPokemon();
    non-null => a Go-Plus CATCH; record its species (PokemonId)
Player center = median of on-map mons. For each caught species, distance to the nearest
on-map mon of that species ~= the catch distance. Compare caught distances vs ALL visible
distances: if caught maxes ~40 while visible ~140 => reach is gated below visibility.
READ-ONLY (observes; no game writes)."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","int",["pointer"]),mGP:b("il2cpp_method_get_param","pointer",["pointer","int"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function ffield(cls,sub){var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;var ex=-1,su=-1;while((f=h.cGF(cls,it))&&!f.isNull()){try{var nm=h.fGN(f).readCString().toLowerCase();var off=h.fGO(f);if(nm===sub||nm===sub+"_"){if(ex<0)ex=off;}else if(nm.indexOf(sub)>=0){if(su<0)su=off;}}catch(e){}}return ex>=0?ex:su;}
function fparam(cls,name,sub){var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(cls,it))&&!m.isNull()){try{if(h.mGN(m).readCString()===name&&h.mGPC(m)===1){var pt=h.mGP(m,0);if(pt&&!pt.isNull()&&h.tGN(pt).readCString().indexOf(sub)>=0)return m;}}catch(e){}}return null;}
var monPos={},catches=[],OFF={},pidOff2=-1,pmPidOff=-1,encOffC=-1,mGetCatch=null;
rpc.exports.setup=function(){
 var h=H_();var pim=img("holo-protos.dll"),gim=img("holo-game.dll");
 var WP=h.cFN(pim,Memory.allocUtf8String("Holoholo.Rpc"),Memory.allocUtf8String("WildPokemonProto"));
 OFF.enc=ffield(WP,"encounterid");OFF.lat=ffield(WP,"latitude");OFF.lng=ffield(WP,"longitude");OFF.pokemon=ffield(WP,"pokemon");
 var WMP=h.cFN(gim,Memory.allocUtf8String("Niantic.Holoholo.Map"),Memory.allocUtf8String("WildMapPokemon"));
 var mInit=WMP.isNull()?null:fparam(WMP,"Initialize","WildPokemonProto");
 var PAM=h.cFN(gim,Memory.allocUtf8String("Niantic.Holoholo.Pgp"),Memory.allocUtf8String("PgpActivityMonitor"));
 var mXek=PAM.isNull()?null:h.cMN(PAM,Memory.allocUtf8String("xek"),1);
 var ALE=h.cFN(pim,Memory.allocUtf8String("Holoholo.Rpc"),Memory.allocUtf8String("ActionLogEntry"));
 mGetCatch=ALE.isNull()?null:h.cMN(ALE,Memory.allocUtf8String("get_CatchPokemon"),0);
 var st={};
 if(mInit&&!mInit.isNull()){var ad=mInit.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){try{var s=a[1];var enc=s.add(OFF.enc).readU64().toString();var la=s.add(OFF.lat).readDouble(),lo=s.add(OFF.lng).readDouble();var pm=OFF.pokemon>=0?s.add(OFF.pokemon).readPointer():ptr(0);var pid=0;if(!pm.isNull()){if(pmPidOff<0)pmPidOff=ffield(H_().OGC(pm),"pokemonid");if(pmPidOff>=0)pid=pm.add(pmPidOff).readS32();}if(la!==0&&Math.abs(la)<=90)monPos[enc]={lat:la,lng:lo,pid:pid};}catch(e){}}});st.init=true;}}
 if(mXek&&!mXek.isNull()&&mGetCatch&&!mGetCatch.isNull()){var ad2=mXek.readPointer();if(!ad2.isNull()){Interceptor.attach(ad2,{onEnter:function(a){try{var entry=a[1];if(entry.isNull())return;var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var cp=H_().rI(mGetCatch,entry,ptr(0),exc);if(cp.isNull())return;var cc=H_().OGC(cp);if(pidOff2<0)pidOff2=ffield(cc,"pokemonid");if(encOffC<0)encOffC=ffield(cc,"encounterid");var pid=pidOff2>=0?cp.add(pidOff2).readS32():0;var en=encOffC>=0?cp.add(encOffC).readU64().toString():"";catches.push({pid:pid,enc:en,t:Date.now()});}catch(e){}}});st.xek=true;}}
 return {OFF:OFF,hooks:st,haveXek:!(mXek===null||(mXek&&mXek.isNull())),haveGetCatch:!(mGetCatch===null||(mGetCatch&&mGetCatch.isNull()))};
};
rpc.exports.results=function(){return {monPos:monPos,catches:catches,pidOff2:pidOff2};};
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
        secs = 75
        print(f"\ncollecting {secs}s — WALK so fresh mons appear; let VPGP catch...")
        time.sleep(secs)
        r = sc.exports_sync.results()
        sess.detach()
        mons = r["monPos"]; cats = r["catches"]
        print(f"\non-map mons seen: {len(mons)}   action-log catches: {len(cats)}   (catch PokemonId offset: {r['pidOff2']})")
        if len(mons) < 4:
            print("too few mons to estimate center — walk more / re-run."); return
        center = (statistics.median([p["lat"] for p in mons.values()]),
                  statistics.median([p["lng"] for p in mons.values()]))
        vis = sorted(hav(center, (p["lat"], p["lng"])) for p in mons.values())
        # caught distance = nearest on-map mon of the caught species
        print("  catches (enc,pid):", [(c.get("enc"), c.get("pid")) for c in cats])
        caught_d = []
        by_enc = 0
        for c in cats:
            p = mons.get(c.get("enc")) if c.get("enc") else None
            if p:
                caught_d.append(hav(center, (p["lat"], p["lng"]))); by_enc += 1
            else:
                cands = [hav(center, (q["lat"], q["lng"])) for q in mons.values() if q["pid"] == c["pid"]]
                if cands:
                    caught_d.append(min(cands))
        caught_d.sort()
        print(f"  matched: {by_enc} by encId, {len(caught_d)-by_enc} by species, {len(cats)-len(caught_d)} unmatched")

        def rep(name, ds):
            if not ds:
                print(f"  {name}: none"); return
            print(f"  {name}: n={len(ds)}  median={ds[len(ds)//2]:.0f}m  MAX={max(ds):.0f}m")
        print("\n=== distance from player-center ===")
        rep("VISIBLE mons", vis)
        rep("CAUGHT by Go Plus (action log)", caught_d)
        print(f"     caught dists: {[round(x) for x in caught_d]}")
        if caught_d and vis:
            print(f"\n>>> visible reaches ~{max(vis):.0f}m; Go-Plus CATCH reaches ~{max(caught_d):.0f}m. "
                  f"{'REACH IS GATED BELOW VISIBILITY (your observation confirmed).' if max(vis)-max(caught_d) > 35 else 'catch ~ visible.'}")
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

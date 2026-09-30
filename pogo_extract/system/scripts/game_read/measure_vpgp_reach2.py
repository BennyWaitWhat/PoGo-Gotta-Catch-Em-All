"""EMPIRICAL v2: measure VPGP Go-Plus catch reach via the TARGET handler (not the action log).
  - WildMapPokemon.Initialize(self, WildPokemonProto) -> pos[self_ptr]=(lat,lng)  [every visible mon]
  - PgpActivityMonitor.xeh(self, IMapPlace, IMapPokemon) -> targets.push(arg2_ptr)  [mons the Go-Plus engages]
Target ptr == the WildMapPokemon instance ptr, so we look up its recorded position.
max(targeted distance) = catch reach;  max(visible distance) = how far you can SEE.
If targeted maxes well below visible -> the reach gate is confirmed + quantified. READ-ONLY."""
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
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function ffield(cls,sub){var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;var ex=-1,su=-1;while((f=h.cGF(cls,it))&&!f.isNull()){try{var nm=h.fGN(f).readCString().toLowerCase();var off=h.fGO(f);if(nm===sub||nm===sub+"_"){if(ex<0)ex=off;}else if(nm.indexOf(sub)>=0){if(su<0)su=off;}}catch(e){}}return ex>=0?ex:su;}
function fparam(cls,name,sub){var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(cls,it))&&!m.isNull()){try{if(h.mGN(m).readCString()===name&&h.mGPC(m)===1){var pt=h.mGP(m,0);if(pt&&!pt.isNull()&&h.tGN(pt).readCString().indexOf(sub)>=0)return m;}}catch(e){}}return null;}
var pos={},targets=[],OFF={};
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
 if(mXeh&&!mXeh.isNull()){var ad2=mXeh.readPointer();if(!ad2.isNull()){Interceptor.attach(ad2,{onEnter:function(a){try{var t=a[2];if(t.isNull())return;targets.push({ptr:t.toString(),t:Date.now()});}catch(e){}}});st.xeh=true;}}
 return {OFF:OFF,hooks:st,haveInit:!(mInit===null||(mInit&&mInit.isNull())),haveXeh:!(mXeh===null||(mXeh&&mXeh.isNull()))};
};
rpc.exports.results=function(){return {pos:pos,targets:targets};};
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
        time.sleep(secs)
        r = sc.exports_sync.results()
        sess.detach()
        pos = r["pos"]; targets = r["targets"]
        print(f"\nvisible mons (Initialize): {len(pos)}   Go-Plus target events (xeh): {len(targets)}")
        if len(pos) < 4:
            print("too few mons — walk more / re-run."); return
        center = (statistics.median([p["lat"] for p in pos.values()]),
                  statistics.median([p["lng"] for p in pos.values()]))
        vis = sorted(hav(center, (p["lat"], p["lng"])) for p in pos.values())
        # de-dupe target ptrs, match to recorded positions
        seen, tgt_d, matched = set(), [], 0
        for t in targets:
            if t["ptr"] in seen:
                continue
            seen.add(t["ptr"])
            p = pos.get(t["ptr"])
            if p:
                tgt_d.append(hav(center, (p["lat"], p["lng"]))); matched += 1
        tgt_d.sort()
        print(f"unique targets: {len(seen)}   matched to a position: {matched}")

        def rep(name, ds):
            if not ds:
                print(f"  {name}: none"); return
            print(f"  {name}: n={len(ds)}  median={ds[len(ds)//2]:.0f}m  MAX={max(ds):.0f}m")
        print("\n=== distance from player-center ===")
        rep("VISIBLE mons", vis)
        rep("GO-PLUS TARGETED (caught reach)", tgt_d)
        if tgt_d:
            print(f"     targeted dists: {[round(x) for x in tgt_d]}")
        if tgt_d and vis:
            gate = max(tgt_d)
            print(f"\n>>> you SEE to ~{max(vis):.0f}m; Go-Plus TARGETS to ~{gate:.0f}m. "
                  f"{'GATE CONFIRMED: catch reach < visible by %.0fm.' % (max(vis)-gate) if max(vis)-gate>30 else 'catch ~ visible (reach is NOT the limiter).'}")
        else:
            print("\n(no targets matched — xeh ptr may differ from WildMapPokemon; will reflect position instead.)")
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

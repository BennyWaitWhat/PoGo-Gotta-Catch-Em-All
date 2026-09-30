"""WATCHED TEST (time-boxed + auto-revert): override PokemonVisibleRange + EncounterRangeMeters to 210
(continuously, to beat SpawnBooster's 140 re-pin), ensure InteractionRange=325, and measure whether
mons now RENDER (WildMapPokemon.Initialize) and get TARGETED (PgpActivityMonitor.xeh) beyond the old
~140 cap. Baseline (visible=140) maxed ~119-140m. Holds 45s then writes 140 back (revert).
User watches for 'out of range' / far mons that flash-but-don't-catch = server rejecting."""
import sys, time, math, os, statistics
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

NEW_VIS = 210.0
HOLD = 45

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
var pos={},targets={},OFF={},msAddrs=[],msClass=null,iv1=null,iv2=null,NV=210.0;
function scanMS(){var h=H_();if(!msClass)return;var pat=kp(msClass);var out=[];Process.enumerateRanges("rw-").forEach(function(r){if(r.file||r.size<256||r.size>134217728)return;try{var hs=Memory.scanSync(r.base,r.size,pat);for(var i=0;i<hs.length&&out.length<40;i++){var p=hs[i].address;try{var v=p.add(0x10).readDouble();if(v>40&&v<400)out.push(p);}catch(e){}}}catch(e){}});msAddrs=out;}
function applyVis(val){for(var i=0;i<msAddrs.length;i++){try{msAddrs[i].add(0x10).writeDouble(val);msAddrs[i].add(0x20).writeDouble(val);}catch(e){}}}
rpc.exports.setup=function(nv){
 NV=nv;var h=H_();var pim=img("holo-protos.dll"),gim=img("holo-game.dll");
 var WP=h.cFN(pim,Memory.allocUtf8String("Holoholo.Rpc"),Memory.allocUtf8String("WildPokemonProto"));
 OFF.lat=ffield(WP,"latitude");OFF.lng=ffield(WP,"longitude");
 var WMP=h.cFN(gim,Memory.allocUtf8String("Niantic.Holoholo.Map"),Memory.allocUtf8String("WildMapPokemon"));
 var mInit=WMP.isNull()?null:fparam(WMP,"Initialize","WildPokemonProto");
 var PAM=h.cFN(gim,Memory.allocUtf8String("Niantic.Holoholo.Pgp"),Memory.allocUtf8String("PgpActivityMonitor"));
 var mXeh=PAM.isNull()?null:h.cMN(PAM,Memory.allocUtf8String("xeh"),2);
 var st={};
 if(mInit&&!mInit.isNull()){var ad=mInit.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){try{var self=a[0].toString();var p=a[1];var la=p.add(OFF.lat).readDouble(),lo=p.add(OFF.lng).readDouble();if(la!==0&&Math.abs(la)<=90)pos[self]={lat:la,lng:lo};}catch(e){}}});st.init=true;}}
 if(mXeh&&!mXeh.isNull()){var ad2=mXeh.readPointer();if(!ad2.isNull()){Interceptor.attach(ad2,{onEnter:function(a){try{var t=a[2];if(t.isNull())return;targets[t.toString()]=Date.now();}catch(e){}}});st.xeh=true;}}
 // interaction range -> 325 (idempotent)
 var ck=findClass("holo-protos.dll","ClientMapObjectsInteractionRangeSettingsProto");
 if(ck){var cpat=kp(ck);Process.enumerateRanges("rw-").forEach(function(r){if(r.file||r.size<256||r.size>134217728)return;try{var hs=Memory.scanSync(r.base,r.size,cpat);for(var i=0;i<hs.length;i++){var p=hs[i].address;try{var v=p.add(0x10).readDouble();if(v>40&&v<400)p.add(0x10).writeDouble(325.0);}catch(e){}}}catch(e){}});}
 // MapSettings visible/encounter -> NV, held by interval
 msClass=findClass("holo-protos.dll","MapSettingsProto");
 scanMS();st.msCount=msAddrs.length;st.visBefore=msAddrs.length?msAddrs[0].add(0x10).readDouble():null;
 applyVis(NV);
 iv1=setInterval(function(){applyVis(NV);},100);
 iv2=setInterval(function(){scanMS();},2500);
 st.visAfter=msAddrs.length?msAddrs[0].add(0x10).readDouble():null;
 return st;
};
rpc.exports.results=function(){return {pos:pos,targets:Object.keys(targets),visNow:msAddrs.length?msAddrs[0].add(0x10).readDouble():null};};
rpc.exports.revert=function(){try{if(iv1)clearInterval(iv1);if(iv2)clearInterval(iv2);}catch(e){}try{applyVis(140.0);}catch(e){}return true;};
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
        st = sc.exports_sync.setup(NEW_VIS)
        print("setup:", st)
        print(f"\nVISIBLE forced to {NEW_VIS} (holding against SpawnBooster). WALK {HOLD}s. Watch for 'out of range' / far flashes that don't catch...")
        time.sleep(HOLD)
        r = sc.exports_sync.results()
        print("\nreverting (visible -> 140)...")
        sc.exports_sync.revert()
        time.sleep(0.5)
        sess.detach()
        pos = r["pos"]; tptrs = r["targets"]
        print(f"visNow held at: {r['visNow']}")
        print(f"visible mons: {len(pos)}   unique Go-Plus targets: {len(tptrs)}")
        if len(pos) < 4:
            print("too few mons (stationary/backgrounded?) — can't judge."); return
        center = (statistics.median([p["lat"] for p in pos.values()]),
                  statistics.median([p["lng"] for p in pos.values()]))
        vis = sorted(hav(center, (p["lat"], p["lng"])) for p in pos.values())
        tgt = sorted(hav(center, (pos[t]["lat"], pos[t]["lng"])) for t in tptrs if t in pos)
        print(f"\nRENDERED max={max(vis):.0f}m (baseline was ~119-140)   median={vis[len(vis)//2]:.0f}m")
        if tgt:
            print(f"GO-PLUS TARGETED max={max(tgt):.0f}m   dists={[round(x) for x in tgt]}")
        else:
            print("GO-PLUS TARGETED: none matched")
        beyond = [d for d in vis if d > 145]
        print(f"\n>>> mons rendered beyond 145m: {len(beyond)}  ({[round(x) for x in beyond]})")
        if max(vis) > 160:
            print("    visible bump TOOK EFFECT (mons now render past the old ~140 cap).")
            if tgt and max(tgt) > 145:
                print("    Go-Plus IS targeting beyond 140 — check whether those actually CAUGHT or bounced out-of-range.")
        else:
            print("    visible did NOT exceed ~140 — SpawnBooster won the tug-of-war, or no mons exist past 140 server-side.")
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

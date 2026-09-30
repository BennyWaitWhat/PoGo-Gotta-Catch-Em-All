"""EMPIRICAL: is VPGP's catch rate network-bound (server round-trips) or device-paced?
Hooks EncounterProto.WriteTo + CatchPokemonProto.WriteTo with timestamps. Computes:
  - inter-catch interval (gap between consecutive catch requests) = the throughput cadence
  - encounter->catch gap (same encounterId) ~= encounter round-trip latency
If interval ~= a couple round-trips -> network-bound (better connection helps, safely).
If interval >> round-trip -> fixed pacing (network won't help). READ-ONLY."""
import sys, time, os, statistics
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function offs(cls){var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;var o={};while((f=h.cGF(cls,it))&&!f.isNull()){try{o[h.fGN(f).readCString()]=h.fGO(f);}catch(e){}}return o;}
function fo(o,subs){for(var k in o){var lk=k.toLowerCase();for(var i=0;i<subs.length;i++)if(lk===subs[i]||lk===subs[i]+"_")return o[k];}for(var k in o){var lk=k.toLowerCase();for(var i=0;i<subs.length;i++)if(lk.indexOf(subs[i])>=0)return o[k];}return -1;}
var enc=[],cat=[],OFF={};
rpc.exports.setup=function(){
 var h=H_();var pim=img("holo-protos.dll");if(!pim)return{err:"no holo-protos"};
 function C(c){return h.cFN(pim,Memory.allocUtf8String("Holoholo.Rpc"),Memory.allocUtf8String(c));}
 var EN=C("EncounterProto"),CP=C("CatchPokemonProto");
 OFF.en=EN.isNull()?-1:fo(offs(EN),["encounterid"]);OFF.cp=CP.isNull()?-1:fo(offs(CP),["encounterid"]);
 function hookW(cls,cb){if(cls.isNull())return false;var m=h.cMN(cls,Memory.allocUtf8String("WriteTo"),1);if(!m||m.isNull())return false;var ad=m.readPointer();if(ad.isNull())return false;Interceptor.attach(ad,{onEnter:function(a){try{cb(a[0]);}catch(e){}}});return true;}
 var st={};
 st.en=hookW(EN,function(s){enc.push({enc:OFF.en>=0?s.add(OFF.en).readU64().toString():"?",t:Date.now()});});
 st.cp=hookW(CP,function(s){cat.push({enc:OFF.cp>=0?s.add(OFF.cp).readU64().toString():"?",t:Date.now()});});
 return {OFF:OFF,hooks:st};
};
rpc.exports.results=function(){return {enc:enc,cat:cat};};
"""


def med(xs):
    return statistics.median(xs) if xs else None


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        st = sc.exports_sync.setup()
        print("setup:", st)
        if st.get("err"):
            return
        secs = 60
        print(f"\ncollecting {secs}s — keep VPGP catching...")
        time.sleep(secs)
        r = sc.exports_sync.results()
        sess.detach()
        cat = sorted(r["cat"], key=lambda x: x["t"])
        enc = sorted(r["enc"], key=lambda x: x["t"])
        print(f"\nencounter reqs: {len(enc)}   catch reqs: {len(cat)}")
        series = cat if len(cat) >= 2 else enc
        label = "catch" if len(cat) >= 2 else "encounter"
        if len(series) < 2:
            print("Too few events to time. Re-run while VPGP is actively catching.")
            return
        print(f"(timing on {label} requests; Go Plus catches via the Sfida action log, not CatchPokemonProto)")
        intervals = [series[i]["t"] - series[i - 1]["t"] for i in range(1, len(series))]
        cat = series
        encmap = {}
        for e in enc:
            encmap.setdefault(e["enc"], []).append(e["t"])
        gaps = []
        for c in cat:
            ts = [t for t in encmap.get(c["enc"], []) if t <= c["t"]]
            if ts:
                gaps.append(c["t"] - max(ts))
        span = (cat[-1]["t"] - cat[0]["t"]) / 1000.0
        rate = (len(cat) - 1) / span if span > 0 else 0
        print("\n=== catch timing ===")
        print(f"  inter-catch interval: median={med(intervals):.0f}ms  min={min(intervals)}ms  max={max(intervals)}ms")
        print(f"  encounter->catch gap (~encounter RTT): median={med(gaps):.0f}ms  (n={len(gaps)})" if gaps else "  encounter->catch gap: n/a")
        print(f"  effective rate: {rate:.2f} catches/sec  (~{rate*60:.0f}/min)")
        print(f"  all intervals (ms): {[int(x) for x in intervals]}")
        mi = med(intervals)
        print("\n=== read ===")
        if mi and mi < 800:
            print(f"  ~{mi:.0f}ms/catch — dominated by server round-trips. A LOWER-LATENCY connection would speed this up (safe). Request RATE is the ban-risky lever — don't.")
        else:
            print(f"  ~{mi:.0f}ms/catch — slower than a raw round-trip, so there's built-in pacing between catches; a faster network won't help much, and forcing the rate up is the ban vector.")
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

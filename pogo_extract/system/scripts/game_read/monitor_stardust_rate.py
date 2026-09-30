"""Monitor the live STARDUST earn rate: sample IapService.get_Stardusts over a window, report
per-interval gains, overall stardust/min, and ETA to 1,000,000. READ-ONLY (runs alongside the catcher)."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

GOAL = 1_000_000
SAMPLES = 7
INTERVAL = 20

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.readI=function(inst,name){var h=H_();var m=h.cMN(h.OGC(ptr(inst)),Memory.allocUtf8String(name),0);if(!m||m.isNull())return null;var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,ptr(inst),ptr(0),exc);if(!exc.readPointer().isNull())return null;try{return r?r.add(0x10).readS32():null;}catch(e){return null;}};
"""


def main():
    sess, pid = pg.get_session()
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    ns = sc.exports_sync.ns_of("IapService")
    iap = None
    if ns:
        r = finder.exports_sync.find_singleton(ns, "IapService")
        best = None
        for h in (r.get("hits", []) if isinstance(r, dict) else []):
            if sc.exports_sync.cls_name(h) != "IapService":
                continue
            v = sc.exports_sync.read_i(h, "get_Stardusts")
            if v is not None and (best is None or v > best[1]):
                best = (h, v)
        iap = best[0] if best else None
    if not iap:
        print("no IapService"); sess.detach(); return

    def dust():
        return sc.exports_sync.read_i(iap, "get_Stardusts")

    print("sampling stardust...")
    pts = []
    for i in range(SAMPLES):
        d = dust(); t = time.time(); pts.append((t, d))
        if i > 0:
            dt = t - pts[i - 1][0]; dd = d - pts[i - 1][1]
            print(f"  {d:>8}  (+{dd} in {dt:.0f}s = {dd/dt*60:.0f}/min)")
        else:
            print(f"  {d:>8}  (start)")
        if i < SAMPLES - 1:
            time.sleep(INTERVAL)
    span = pts[-1][0] - pts[0][0]; gain = pts[-1][1] - pts[0][1]
    rate = gain / span * 60 if span > 0 else 0
    print(f"\nRATE: +{gain} over {span:.0f}s = {rate:.0f} stardust/min")
    if rate > 0:
        remain = GOAL - pts[-1][1]
        print(f"To 1,000,000: {remain:,} to go => ~{remain/rate/60:.1f} h at this rate (current {pts[-1][1]:,})")
    sess.detach()


main()

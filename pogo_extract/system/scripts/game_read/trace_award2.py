"""DEFINITIVE (read-only): over one window, SUM the per-catch award arrays (CaptureScoreProto.Stardust)
AND measure the real IapService stardust the total rises by. ratio = credited / award-sum tells us whether
the Star Piece(x1.5)/event(x2-3) multipliers are actually CREDITED or just missing from the display.
ratio ~1 => multipliers dropped (real bug). ~3-4.5 => applied (display-only). Touches nothing."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function readRF(rf){try{if(!rf||rf.isNull())return 0;var arr=rf.add(0x10).readPointer();var cnt=rf.add(0x18).readS32();if(cnt<0||cnt>64)return 0;var s=0;if(arr&&!arr.isNull()){for(var i=0;i<cnt;i++)s+=arr.add(0x20+i*4).readS32();}return s;}catch(e){return 0;}}
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.readDust=function(inst){var h=H_();var m=h.cMN(h.OGC(ptr(inst)),Memory.allocUtf8String("get_Stardusts"),0);if(!m||m.isNull())return null;var ex=Memory.alloc(Process.pointerSize);ex.writePointer(ptr(0));var r=h.rI(m,ptr(inst),ptr(0),ex);if(!ex.readPointer().isNull())return null;try{return r?r.add(0x10).readS32():null;}catch(e){return null;}};
var NCATCH=0, SUMAWARD=0;
rpc.exports.stats=function(){return {n:NCATCH,sum:SUMAWARD};};
rpc.exports.install=function(){var h=H_();var st={hooks:0};var k=findClass("holo-protos.dll","CatchPokemonOutProto");if(!k)return st;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
 while((m=h.cGM(k,it))&&!m.isNull()){try{if(h.mGN(m).readCString()!=="MergeFrom")continue;if(h.mGPC(m)!==1)continue;var code=m.readPointer();if(!code||code.isNull())continue;
  Interceptor.attach(code,{onEnter:function(a){this.self=a[0];},onLeave:function(r){try{var s=this.self;if(!s||s.isNull())return;var status=s.add(0x10).readS32();var sc=s.add(0x28).readPointer();if(!sc||sc.isNull())return;var dust=readRF(sc.add(0x28).readPointer());if(status===1&&dust>0){NCATCH++;SUMAWARD+=dust;}}catch(e){}}});
  st.hooks++;}catch(e){}}
 return st;};
"""


def main():
    sess, pid = pg.get_session()
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)

    def find_iap():
        ns = sc.exports_sync.ns_of("IapService")
        r = finder.exports_sync.find_singleton(ns, "IapService")
        best = None; bv = None
        for h in (r.get("hits", []) if isinstance(r, dict) else []):
            if sc.exports_sync.cls_name(h) != "IapService":
                continue
            v = sc.exports_sync.read_dust(h)
            if v is not None and (bv is None or v > bv):
                best = h; bv = v
        return best
    iap = find_iap()
    if not iap:
        print("no IapService"); sess.detach(); return
    d0 = sc.exports_sync.read_dust(iap)
    st = sc.exports_sync.install()
    print(f"attached {pid} | hooks={st.get('hooks')} | D0={d0}", flush=True)

    # catch window
    WINDOW = 80
    t0 = time.time()
    while time.time() - t0 < WINDOW:
        time.sleep(5)
        s = sc.exports_sync.stats()
        print(f"  +{int(time.time()-t0)}s catches={s.get('n')} award_sum={s.get('sum')} dust_now={sc.exports_sync.read_dust(iap)}", flush=True)
    s = sc.exports_sync.stats()
    n, ssum = s.get("n", 0), s.get("sum", 0)

    # settle: wait for IapService to stop rising (batchy sync), up to 120s
    print("  settling (waiting for stardust to finish syncing)...", flush=True)
    last = sc.exports_sync.read_dust(iap); stable = 0; t1 = time.time()
    while time.time() - t1 < 120 and stable < 18:
        time.sleep(3)
        cur = sc.exports_sync.read_dust(iap)
        stable = stable + 3 if cur == last else 0
        last = cur
    d1 = last
    credited = d1 - d0
    print(f"\n==== RESULT over the window ====")
    print(f"catches counted (status=success): {n}")
    print(f"award-array stardust sum (base+flat, per proto): {ssum}")
    print(f"REAL stardust credited (IapService {d0} -> {d1}): {credited}")
    if ssum > 0:
        print(f"ratio credited/award = {credited/ssum:.2f}   "
              f"(~1.0 = multipliers DROPPED; ~1.5 = StarPiece only; ~3.0 = StarPiece+2x; ~4.5 = StarPiece+3x)")
    sess.detach()


main()

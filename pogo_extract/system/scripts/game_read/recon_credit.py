"""VERIFY PER-CATCH CREDITING (read-only): hook the server's CatchPokemonOutProto on EVERY catch, read the
stardust award it grants, and watch the server-backed IapService balance climb by EXACTLY the sum of those
awards. If sum(server awards) == balance gain, every single catch was credited (none dropped). Read-only;
attaches alongside the running catcher."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function inv(m,obj,params){var h=H_();if(!m)return null;var n=params?params.length:0;var args=ptr(0);if(n){args=Memory.alloc(Process.pointerSize*n);for(var i=0;i<n;i++)args.add(i*Process.pointerSize).writePointer(params[i]);}var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,args,exc);if(!exc.readPointer().isNull())return null;return r;}
function readRF(rf){try{if(!rf||rf.isNull())return 0;var n=rf.add(0x18).readS32();var arr=rf.add(0x10).readPointer();if(arr.isNull()||n<=0||n>16)return 0;var s=0;for(var i=0;i<n;i++)s+=arr.add(0x20+i*4).readS32();return s;}catch(e){return 0;}}
var EVENTS=[];
rpc.exports.getEvents=function(){var e=EVENTS;EVENTS=[];return e;};
rpc.exports.install=function(){var h=H_();var k=findClass("holo-protos.dll","CatchPokemonOutProto");if(!k)return {err:1};var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;var hk=0;while((m=h.cGM(k,it))&&!m.isNull()){try{if(h.mGN(m).readCString()!=="MergeFrom")continue;if(h.mGPC(m)!==1)continue;var code=m.readPointer();if(!code||code.isNull())continue;Interceptor.attach(code,{onEnter:function(a){this.self=a[0];},onLeave:function(r){try{var s=this.self;if(!s||s.isNull())return;if(s.add(0x10).readS32()!==1)return;var sco=s.add(0x28).readPointer();if(!sco||sco.isNull())return;EVENTS.push(readRF(sco.add(0x28).readPointer()));}catch(e){}}});hk++;}catch(e){}}return {hooked:hk};};
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.call0i=function(inst,name){var m=mOf(H_().OGC(ptr(inst)),name,0);if(!m)return -999;var r=inv(m,ptr(inst),[]);try{return r?r.add(0x10).readS32():-998;}catch(e){return -997;}};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        print("install:", sc.exports_sync.install(), flush=True)
        ns = sc.exports_sync.ns_of("IapService")
        r = finder.exports_sync.find_singleton(ns, "IapService") if ns else {}
        best = None
        for h in (r.get("hits", []) if isinstance(r, dict) else []):
            if sc.exports_sync.cls_name(h) != "IapService":
                continue
            coins = sc.exports_sync.call0i(h, "get_Coins")
            dv = sc.exports_sync.call0i(h, "get_Stardusts")
            if coins is None or coins < 0:
                continue
            key = (coins, dv if (dv is not None and dv >= 0) else -1)
            if best is None or key > best[1]:
                best = (h, key)
        iap = best[0] if best else None

        def bal():
            return sc.exports_sync.call0i(iap, "get_Stardusts") if iap else -1

        # PHASE A — align to a balance COMMIT so the baseline carries no pre-existing backlog
        print(f"server-backed IapService={iap} (coins={best[1][0] if best else '?'})", flush=True)
        print("aligning to a sync boundary (waiting for one balance commit, discarding backlog)...", flush=True)
        sc.exports_sync.get_events()
        prevb = bal()
        ta = time.time()
        while time.time() - ta < 35:
            time.sleep(0.4)
            sc.exports_sync.get_events()  # discard awards earned before our clean baseline
            b = bal()
            if b >= 0 and prevb >= 0 and b > prevb:
                break
            if b >= 0:
                prevb = b
        sc.exports_sync.get_events()  # final discard -> counter starts clean
        b0 = bal()
        print(f"aligned. clean baseline B0={b0}\nmeasuring ~100s (each line = a server balance commit)...\n", flush=True)
        # PHASE B — count EVERY server award; watch the balance commit in batches
        award_sum = 0
        n = 0
        last = b0
        t0 = time.time()
        while time.time() - t0 < 100:
            time.sleep(0.4)
            for a in (sc.exports_sync.get_events() or []):
                award_sum += a
                n += 1
            b = bal()
            if b >= 0 and b != last:
                print(f"  commit {last}->{b} (+{b-last}) | cumulative server awards={award_sum} over n={n} catches", flush=True)
                last = b
        # PHASE C — let the final batch commit so the balance reflects every counted award
        print("\nwaiting for the final commit to settle...", flush=True)
        stable = 0
        lastb = bal()
        for _ in range(60):
            time.sleep(0.4)
            b = bal()
            if b >= 0 and b == lastb:
                stable += 1
            else:
                stable = 0
                lastb = b
            if stable >= 20:
                break
        final = bal()
        gain = final - b0 if (final >= 0 and b0 >= 0) else None
        print(f"\n===== RESULT over {n} catches (clean sync boundaries) =====", flush=True)
        print(f"  sum of SERVER awards : {award_sum}", flush=True)
        print(f"  balance gain         : {b0} -> {final} = {gain}", flush=True)
        if gain is not None:
            diff = gain - award_sum
            tol = max(300, int(award_sum * 0.03))
            if abs(diff) <= tol:
                v = "EVERY CATCH CREDITED — balance gained exactly the server awards (no loss, no inflation)"
            elif diff > tol:
                v = f"balance gained {diff} MORE than awards — inflation OR leftover backlog (re-check)"
            else:
                v = f"balance gained {-diff} LESS than awards — POSSIBLE LOST CREDIT (investigate)"
            print(f"  VERDICT: {v}  (diff={diff}, tol=+/-{tol})", flush=True)
    finally:
        try:
            sc.unload()
        except Exception:
            pass
        try:
            sess.detach()
        except Exception:
            pass


main()

"""RECON (READ-ONLY): long watch on PokeStop spin results. Logs every spin you
attempt with a wall-clock stamp and EXITS the instant one returns SUCCESS (the
cooldown lifting). Runs up to 2h. Pure read -- it never spins for you (that would
reset the cooldown); you probe by spinning a stop every ~10-15 min."""
import sys, os, time, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so"); var e={};
 il.enumerateExports().forEach(function(x){ if(x.name.indexOf("il2cpp_")===0) e[x.name]=x.address; });
 function b(n,r,a){ return e[n]? new NativeFunction(e[n],r,a): null; }
 H={ dG:b("il2cpp_domain_get","pointer",[]), dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),
     aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]), iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),
     iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]), CGN:b("il2cpp_class_get_name","pointer",["pointer"]),
     cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]), mGN:b("il2cpp_method_get_name","pointer",["pointer"]),
     tA:b("il2cpp_thread_attach","pointer",["pointer"]) };
 H.tA(H.dG()); return H; }
function eachClass(cb){ var h=H_(); var sp=Memory.alloc(4); var a=h.dGA(h.dG(),sp); var n=sp.readS32();
 for(var i=0;i<n;i++){ var im=h.aGI(a.add(i*Process.pointerSize).readPointer()); var cnt=h.iGCC(im);
   for(var j=0;j<cnt;j++){ var k=h.iGC(im,j); if(!k.isNull()) cb(k); } } }
function findClass(name){ var h=H_(); var f=null; eachClass(function(k){ if(f)return; try{ if(h.CGN(k).readCString()===name) f=k; }catch(e){} }); return f; }
var LOG=[]; function L(s){ LOG.push(s); }
rpc.exports.drain=function(){ var o=LOG; LOG=[]; return o; };
rpc.exports.install=function(){ var h=H_(); var k=findClass("FortSearchOutProto"); if(!k) return "no class";
 var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m; var hk=0;
 while((m=h.cGM(k,it))&&!m.isNull()){ try{ if(h.mGN(m).readCString()!=="MergeFrom")continue; var code=m.readPointer(); if(!code||code.isNull())continue;
   Interceptor.attach(code,{ onEnter:function(a){ this.s=a[0]; }, onLeave:function(){ try{ if(this.s&&!this.s.isNull()) L("R="+this.s.add(0x10).readS32()); }catch(e){} } }); hk++; }catch(e){} }
 return "hooked "+hk; };
"""

RESULT = {0: "NO_RESULT_SET", 1: "SUCCESS", 2: "OUT_OF_RANGE", 3: "IN_COOLDOWN_PERIOD",
          4: "INVENTORY_FULL", 5: "EXCEEDED_DAILY_LIMIT", 6: "POI_INACCESSIBLE"}


def main():
    t0 = time.time()
    spins = 0
    last_beat = 0.0
    reconnects = 0
    print(f"WATCH START {datetime.datetime.now():%H:%M:%S} — probe by spinning a stop every ~10-15 min (don't spam). Up to 2h. Self-reconnects across PoGo crashes.", flush=True)
    while time.time() - t0 < 7200:
        sc = None
        sess = None
        try:
            sess, pid = pg.get_session()
            sc = sess.create_script(JS)
            sc.load()
            r = sc.exports_sync.install()
            tag = f"reconnect #{reconnects} " if reconnects else ""
            print(f"  [{datetime.datetime.now():%H:%M:%S}] {tag}attached pid={pid} ({r})", flush=True)
            while time.time() - t0 < 7200:
                time.sleep(2)
                for line in (sc.exports_sync.drain() or []):
                    if line.startswith("R="):
                        rv = int(line[2:])
                        spins += 1
                        el = (time.time() - t0) / 60.0
                        stamp = datetime.datetime.now().strftime("%H:%M:%S")
                        print(f"  [{stamp}  +{el:5.1f}min  spin#{spins}]  {RESULT.get(rv, rv)}", flush=True)
                        if rv == 1:
                            print(f"\n=== COOLDOWN CLEARED — spin SUCCEEDED at {stamp} (+{el:.1f} min into the watch) ===", flush=True)
                            try:
                                sc.unload(); sess.detach()
                            except Exception:
                                pass
                            return
                el = time.time() - t0
                if el - last_beat >= 120:
                    last_beat = el
                    print(f"  ...watching ({el/60:.0f} min, {spins} probes, {reconnects} PoGo restarts, still OUT_OF_RANGE)", flush=True)
        except Exception as e:
            reconnects += 1
            try:
                sc.unload(); sess.detach()
            except Exception:
                pass
            print(f"  [{datetime.datetime.now():%H:%M:%S}] gadget dropped ({str(e)[:60]}) — waiting for PoGo to relaunch...", flush=True)
            time.sleep(6)
            continue
    print(f"\n=== 2h elapsed, still no successful spin (probes seen: {spins}, PoGo restarts: {reconnects}) ===", flush=True)


main()

"""RECON (READ-ONLY): why are catches FLEEING? Live-hook CatchPokemonOutProto.MergeFrom and log, per result,
Status + ThrowsRemaining + MissPercent, so we can see whether flees are despawn/range artifacts, low-throws-
remaining, or genuine misses. Also dumps EncounterPokemon/MapPokemon behaviour methods (dodge/jump/attack/flee)
to judge whether a 'no-dodge' freeze is even relevant to the bot's reduced fast-catch path. Touches nothing."""
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
 H={dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),dG:b("il2cpp_domain_get","pointer",[]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
var EVENTS=[];
rpc.exports.getEvents=function(){var e=EVENTS;EVENTS=[];return e;};
rpc.exports.install=function(){var h=H_();var k=findClass("holo-protos.dll","CatchPokemonOutProto");if(!k)return {err:"no class"};var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;var hk=0;while((m=h.cGM(k,it))&&!m.isNull()){try{if(h.mGN(m).readCString()!=="MergeFrom")continue;if(h.mGPC(m)!==1)continue;var code=m.readPointer();if(!code||code.isNull())continue;Interceptor.attach(code,{onEnter:function(a){this.self=a[0];},onLeave:function(r){try{var s=this.self;if(!s||s.isNull())return;EVENTS.push({status:s.add(0x10).readS32(),thr:s.add(0x38).readS32(),miss:s.add(0x18).readDouble()});}catch(e){}}});hk++;}catch(e){}}return {hooked:hk};};
rpc.exports.methods=function(cls,image,rx){var h=H_();var k=findClass(image,cls);if(!k)return null;var re=new RegExp(rx,"i");var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()&&out.length<60){try{var mn=h.mGN(m).readCString();if(!re.test(mn))continue;var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(mn+" ("+h.mGPC(m)+") -> "+rt);}catch(e){}}return out;};
"""

STATUS = {0: "Error", 1: "Caught", 2: "Escape", 3: "FLEE", 4: "Missed", 5: "ItemReplace"}


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        print("install:", sc.exports_sync.install(), flush=True)
        for cls in ["EncounterPokemon", "MapPokemon"]:
            for image in ["holo-game.dll"]:
                ms = sc.exports_sync.methods(cls, image, "dodge|jump|attack|flee|move|agitat|idle|behavi|animat")
                if ms:
                    print(f"\n=== {cls} behaviour methods ===", flush=True)
                    for m in ms:
                        print("   ", m, flush=True)
        print("\n=== watching catch results (status / throwsRemaining / missPercent) ===", flush=True)
        tally = {}
        t0 = time.time()
        n = 0
        while time.time() - t0 < 60 and n < 60:
            time.sleep(1.0)
            for e in (sc.exports_sync.get_events() or []):
                n += 1
                st = STATUS.get(e.get("status"), e.get("status"))
                tally[st] = tally.get(st, 0) + 1
                if st in ("FLEE", "Escape", "Missed", "Error"):
                    print(f"   {st}: throwsRemaining={e.get('thr')} missPct={e.get('miss'):.3f}", flush=True)
        print(f"\n=== tally over {n} results: {tally} ===", flush=True)
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

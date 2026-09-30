"""LIVE FEED TRACER (read-only hooks): capture a real manual gym feed end-to-end so we learn the true
cadence/caps. Hooks GymRootController.FeedPokemon(Item, ulong pokemonId, string gymId) for each feed
ATTEMPT, and GymFeedPokemonOutProto.MergeFrom for each RESULT code (Success / ErrorPokemonFull /
ErrorTooFrequent = the 30-min cap / etc.). Buffers events; python polls. WRITES NOTHING."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

ITEM = {701: 'Razz', 702: 'Bluk', 703: 'Nanab', 704: 'Wepar', 705: 'Pinap', 706: 'GoldRazz', 707: 'GoldNanab', 708: 'GoldPinap'}
RESULT = {0: 'Unset', 1: 'Success', 2: 'ErrorCannotUse', 3: 'ErrorNotInRange', 4: 'ErrorPokemonNotThere',
          5: 'ErrorPokemonFull', 6: 'ErrorNoBerriesLeft', 7: 'ErrorWrongTeam', 8: 'ErrorWrongCount',
          9: 'ErrorTooFast', 10: 'ErrorTooFrequent (30-min CAP)', 11: 'ErrorGymBusy', 12: 'ErrorRaidActive', 13: 'ErrorGymClosed'}

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),CGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),FGN:b("il2cpp_field_get_name","pointer",["pointer"]),FGO:b("il2cpp_field_get_offset","uint32",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClassGame(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function clsProto(ns,nm){var h=H_();var im=img("holo-protos.dll");if(!im)return null;return h.cFN(im,Memory.allocUtf8String(ns),Memory.allocUtf8String(nm));}
function readStr(p){try{if(!p||p.isNull())return null;var len=p.add(0x10).readS32();if(len<0||len>4096)return "?";return p.add(0x14).readUtf16String(len);}catch(e){return "?";}}
var EVENTS=[], RESULT_OFF=-1;
rpc.exports.getEvents=function(){var e=EVENTS;EVENTS=[];return e;};
rpc.exports.install=function(){var h=H_();var st={};
 var grc=findClassGame("GymRootController");
 if(grc){var fm=h.cMN(grc,Memory.allocUtf8String("FeedPokemon"),3);
  if(fm&&!fm.isNull()){var code=fm.readPointer();if(!code.isNull()){Interceptor.attach(code,{onEnter:function(a){try{EVENTS.push({k:'feed',item:a[1].toInt32(),pid:a[2].toString(),gym:readStr(a[3])});}catch(e){}}});st.feedHook=true;}}}
 var op=clsProto("Holoholo.Rpc","GymFeedPokemonOutProto");
 if(op&&!op.isNull()){
   var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
   while((f=h.CGF(op,it))&&!f.isNull()){try{if(h.FGN(f).readCString()==='Result'){RESULT_OFF=h.FGO(f);break;}}catch(e){}}
   st.resultOff=RESULT_OFF;
   var it2=Memory.alloc(Process.pointerSize);it2.writePointer(ptr(0));var m;var n=0;
   while((m=h.cGM(op,it2))&&!m.isNull()){try{if(h.mGN(m).readCString()!=="MergeFrom")continue;if(h.mGPC(m)!==1)continue;var c=m.readPointer();if(c.isNull())continue;Interceptor.attach(c,{onEnter:function(a){this.self=a[0];},onLeave:function(r){try{var s=this.self;if(!s||s.isNull()||RESULT_OFF<0)return;EVENTS.push({k:'result',res:s.add(RESULT_OFF).readS32()});}catch(e){}}});n++;}catch(e){}}
   st.resultHooks=n;
 }
 return st;
};
"""


def main():
    sess, pid = pg.get_session()
    sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
    st = sc.exports_sync.install()
    print(f"attached {pid} | install={st}", flush=True)
    if not st.get("feedHook"):
        print("WARN: FeedPokemon hook failed");
    print("===== FEED A GYM DEFENDER NOW (repeatedly, until the game stops you) — capturing =====", flush=True)
    t0 = time.time(); last = None
    while time.time() - t0 < 300:
        time.sleep(0.8)
        for e in (sc.exports_sync.get_events() or []):
            ts = time.strftime('%H:%M:%S')
            if e.get("k") == "feed":
                print(f"  {ts} FEED   item={ITEM.get(e.get('item'), e.get('item'))} pokemonId={e.get('pid')} gym={e.get('gym')}", flush=True)
            elif e.get("k") == "result":
                rc = e.get("res")
                print(f"  {ts} RESULT {rc} = {RESULT.get(rc, '?')}", flush=True)
    sc.unload(); sess.detach()


main()

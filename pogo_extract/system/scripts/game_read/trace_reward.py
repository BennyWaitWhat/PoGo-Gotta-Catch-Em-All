"""LIVE TRACER (read-only hooks): watch the user manually catch ONE Field-Research reward and record the
exact method call sequence (open + catch path) so we can replicate it. Hooks quest/encounter methods,
buffers events, python polls them. Touches nothing — Interceptor.attach onEnter only."""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

TRACE = os.path.join(ROOT, "system", "analysis", "pokemod", "reward_trace.log")
RUN_SECONDS = 300

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function readStr(p){try{if(!p||p.isNull())return null;var len=p.add(0x10).readS32();if(len<0||len>4096)return "?";return p.add(0x14).readUtf16String(len);}catch(e){return "?";}}
function clsOf(p){try{if(!p||p.isNull())return null;return H_().CGN(H_().OGC(p)).readCString();}catch(e){return null;}}

var EVENTS=[], SEQ=0;
rpc.exports.getEvents=function(){var e=EVENTS;EVENTS=[];return e;};

// [class, method, argc, {str:[argIdx], int:[argIdx], cls:[argIdx]}]
var TARGETS=[
 ["QuestStateManager","OpenQuestEncounter",1,{}],
 ["QuestStateManager","OpenQuestEncounter",2,{}],
 ["QuestStateManager","OpenQuestListPageDefault",0,{}],
 ["QuestStateManager","OpenQuestListPage",1,{}],
 ["QuestService","GetPokemonEncounterForQuest",1,{str:[1]}],
 ["QuestService","GetDanglingEncounterOfType",2,{int:[1],str:[2]}],
 ["QuestService","CompleteQuest",6,{}],
 ["ResearchEncounter","AttemptCapture",1,{cls:[0]}],
 ["MapPokemon","TryCapture",2,{cls:[0]}],
 ["QuestMapPokemon","TryCapture",2,{cls:[0]}],
 ["QuestMapPokemon","SendEncounterRequest",0,{cls:[0]}],
 ["QuestRewardInteractionService","StartRewardInteraction",4,{}],
 ["QuestRewardInteractionService","LoadRewardInteraction",4,{}],
 ["QuestRewardInteractionService","StartLoadedRewardInteraction",0,{}],
];

rpc.exports.install=function(){
 var status=[];
 TARGETS.forEach(function(t){
  var cls=t[0],meth=t[1],argc=t[2],dec=t[3]||{};
  var label=cls+"."+meth+"/"+argc;
  try{
   var k=findClass("holo-game.dll",cls); if(!k){status.push(label+" : NO CLASS");return;}
   var m=mOf(k,meth,argc); if(!m){status.push(label+" : NO METHOD");return;}
   var code=m.readPointer(); if(!code||code.isNull()){status.push(label+" : NO CODE");return;}
   Interceptor.attach(code,{onEnter:function(args){
     var info={seq:SEQ++,n:cls+"."+meth};
     try{ if(dec.str)dec.str.forEach(function(i){info["s"+i]=readStr(args[i]);});
          if(dec.int)dec.int.forEach(function(i){try{info["i"+i]=args[i].toInt32();}catch(e){}});
          if(dec.cls)dec.cls.forEach(function(i){info["c"+i]=clsOf(args[i]);}); }catch(e){}
     EVENTS.push(info);
   }});
   status.push(label+" : HOOKED");
  }catch(e){status.push(label+" : ERR "+e);}
 });
 return status;
};
"""


def main():
    os.makedirs(os.path.dirname(TRACE), exist_ok=True)
    tf = open(TRACE, "a", encoding="utf-8")

    def w(s):
        line = f"{time.strftime('%H:%M:%S')} {s}"
        tf.write(line + "\n"); tf.flush(); print(line, flush=True)

    sess, pid = pg.get_session()
    sc = pg.get_script_with_helpers(sess, JS)
    w(f"===== reward tracer attached pid={pid} =====")
    status = sc.exports_sync.install()
    hooked = sum(1 for s in status if s.endswith("HOOKED"))
    for s in status:
        w("  hook " + s)
    w(f"===== {hooked}/{len(status)} hooks live — CATCH ONE REWARD NOW =====")
    t0 = time.time()
    try:
        while time.time() - t0 < RUN_SECONDS:
            evs = sc.exports_sync.get_events()
            for e in (evs or []):
                parts = [f"{k}={v}" for k, v in e.items() if k not in ("seq", "n")]
                w(f"  EVENT #{e.get('seq')} {e.get('n')} {' '.join(parts)}")
            time.sleep(1.0)
    finally:
        w("===== tracer stopping =====")
        try:
            sc.unload()
        except Exception:
            pass
        try:
            sess.detach()
        except Exception:
            pass


main()

"""LIVE AWARD READER (read-only hook): hook CatchPokemonOutProto.MergeFrom (wire parse) and read, per catch:
Status (caught/fled) + CaptureScoreProto.Stardust[] (per-bonus breakdown) + ActivityType[] (which bonus).
Reads protobuf RepeatedField<int> by raw offset (getters are obfuscated). Touches nothing — reads in onLeave."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function readRF(rf){ // protobuf RepeatedField<int>: array@0x10, count@0x18, il2cpp array data@0x20
 try{ if(!rf||rf.isNull())return null; var arr=rf.add(0x10).readPointer(); var cnt=rf.add(0x18).readS32(); if(cnt<0||cnt>64)return {cnt:cnt,bad:1}; var v=[]; if(arr&&!arr.isNull()){for(var i=0;i<cnt;i++)v.push(arr.add(0x20+i*4).readS32());} return {cnt:cnt,v:v}; }catch(e){return {err:""+e};}
}
var EVENTS=[];
rpc.exports.getEvents=function(){var e=EVENTS;EVENTS=[];return e;};
rpc.exports.install=function(){
 var h=H_(); var st={hooks:0};
 var k=findClass("holo-protos.dll","CatchPokemonOutProto"); if(!k){st.err="no class";return st;}
 var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m;
 while((m=h.cGM(k,it))&&!m.isNull()){
  try{ if(h.mGN(m).readCString()!=="MergeFrom") continue; if(h.mGPC(m)!==1) continue;
   var code=m.readPointer(); if(!code||code.isNull()) continue;
   Interceptor.attach(code,{onEnter:function(a){this.self=a[0];},onLeave:function(r){
     try{ var s=this.self; if(!s||s.isNull())return;
      var status=s.add(0x10).readS32();
      var dex=s.add(0x34).readS32();
      var sc=s.add(0x28).readPointer();
      var sd=null, act=null;
      if(sc&&!sc.isNull()){ sd=readRF(sc.add(0x28).readPointer()); act=readRF(sc.add(0x10).readPointer()); }
      // only log entries that look like a catch result (has a score)
      EVENTS.push({status:status,dex:dex,sd:sd,act:act});
     }catch(e){}
   }});
   st.hooks++;
  }catch(e){}
 }
 return st;
};
"""


def main():
    sess, pid = pg.get_session()
    sc = pg.get_script_with_helpers(sess, JS)
    st = sc.exports_sync.install()
    print(f"attached {pid} | install={st}", flush=True)
    if not st.get("hooks"):
        print("no hooks — aborting"); sess.detach(); return
    print("watching catch awards (Status / Stardust breakdown)...", flush=True)
    t0 = time.time(); n = 0
    while time.time() - t0 < 150 and n < 25:
        time.sleep(1.0)
        for e in (sc.exports_sync.get_events() or []):
            sd = e.get("sd") or {}
            act = e.get("act") or {}
            dust = sum(sd.get("v", [])) if isinstance(sd.get("v"), list) else None
            # skip merge-noise where there's no score array
            if not sd.get("v") and dust is None:
                continue
            n += 1
            print(f"  status={e.get('status')} dex={e.get('dex')} TOTAL_DUST={dust} "
                  f"breakdown={sd.get('v')} activityTypes={act.get('v')}", flush=True)
    print(f"done ({n} catches read)", flush=True)
    sess.detach()


main()

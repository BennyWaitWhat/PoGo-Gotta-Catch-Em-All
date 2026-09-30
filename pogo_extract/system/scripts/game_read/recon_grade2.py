"""RECON (READ-ONLY hook): hook PokeballThrow.GetGrade to capture, per throw, the reticle value, the live
EncounterSettings thresholds, and the resulting Grade. Confirms which reticle = Excellent. Read-only."""
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
 H={dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),dG:b("il2cpp_domain_get","pointer",[]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
var EVENTS=[];
rpc.exports.getEvents=function(){var e=EVENTS;EVENTS=[];return e;};
rpc.exports.install=function(){var h=H_();var pbt=findClass("holo-game.dll","PokeballThrow");if(!pbt)return {err:"no pbt"};var gg=h.cMN(pbt,Memory.allocUtf8String("GetGrade"),1);if(!gg||gg.isNull())return {err:"no GetGrade"};var code=gg.readPointer();if(!code||code.isNull())return {err:"no code"};
 Interceptor.attach(code,{onEnter:function(a){try{this.self=a[0];this.s=a[1];}catch(e){}},onLeave:function(r){try{var self=this.self,s=this.s;var ev={grade:r?r.toInt32():null};
  // reticle: try struct offset +4 and +0x14
  try{ev.ret4=self.add(0x4).readFloat();}catch(e){}
  try{ev.ret14=self.add(0x14).readFloat();}catch(e){}
  if(s&&!s.isNull()){try{ev.exThr=s.add(0x14).readFloat();ev.grThr=s.add(0x18).readFloat();ev.niThr=s.add(0x1c).readFloat();ev.critThr=s.add(0x68).readFloat();ev.gdust=s.add(0x60).readFloat();}catch(e){}}
  EVENTS.push(ev);}catch(e){}}});
 return {hooked:true};};
"""

GRADE = {0: "Miss", 1: "Normal", 2: "Nice", 3: "Great", 4: "EXCELLENT"}


def main():
    sess, pid = pg.get_session()
    sc = pg.get_script_with_helpers(sess, JS)
    print("attached", pid, "install:", sc.exports_sync.install(), flush=True)
    print("watching GetGrade calls (throw from the bot or manually)...", flush=True)
    t0 = time.time(); n = 0
    while time.time() - t0 < 90 and n < 10:
        time.sleep(1.0)
        for e in (sc.exports_sync.get_events() or []):
            n += 1
            print(f"  grade={GRADE.get(e.get('grade'), e.get('grade'))} reticle(+4)={e.get('ret4')} reticle(+14)={e.get('ret14')} "
                  f"| thresholds Ex={e.get('exThr')} Gr={e.get('grThr')} Ni={e.get('niThr')} Crit={e.get('critThr')} | globalDust={e.get('gdust')}", flush=True)
    print(f"done ({n} GetGrade calls seen)", flush=True)
    sess.detach()


main()

"""#2 main-thread PUMP recon (READ-ONLY): find a per-frame, main-thread method to drive the catch
sequence from (so SendEncounterRequest/AttemptCapture run on Unity's main thread, not a Frida thread).
Hooks candidate Update/Tick/LateUpdate methods on core controllers and measures call rate over a window."""
import sys, os, time, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return k;}catch(e){}}return null;}
rpc.exports.candidates=function(){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);var out=[];var re=/Controller|Manager|View|Camera|Overworld|World|Avatar|Input|GameLoop|MapExploration|MainScreen|Hud/;for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;var cn;try{cn=h.CGN(k).readCString();}catch(e){continue;}if(!re.test(cn))continue;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()){try{var nm=h.mGN(m).readCString();if((nm==="Update"||nm==="LateUpdate"||nm==="Tick")&&h.mGPC(m)===0)out.push(cn+"|"+nm);}catch(e){}}if(out.length>=40)break;}return out;};
var ctr={};var names=[];
rpc.exports.arm=function(list){var h=H_();for(var i=0;i<list.length;i++){var parts=list[i].split("|");var k=findClass("holo-game.dll",parts[0]);if(!k)continue;var m=h.cMN(k,Memory.allocUtf8String(parts[1]),0);if(!m||m.isNull())continue;var ad=m.readPointer();if(ad.isNull())continue;(function(idx){ctr[idx]=0;names[idx]=list[i];Interceptor.attach(ad,{onEnter:function(a){ctr[idx]++;}});})(i);}return names.length;};
rpc.exports.rates=function(){var out=[];for(var k in ctr)out.push(names[k]+" = "+ctr[k]);return out;};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        cands = sc.exports_sync.candidates()
        print(f"candidate per-frame methods: {len(cands)}")
        cands = cands[:14]
        sc.exports_sync.arm(cands)
        time.sleep(3.0)
        rates = sc.exports_sync.rates()
        print("\n=== call counts over 3s (high = per-frame main-thread pump) ===")
        for r in sorted(rates, key=lambda s: -int(s.split("= ")[-1])):
            print("  ", r)
        sess.detach()
    finally:
        try: sess.detach()
        except Exception: pass


main()

"""RESEARCH (read-only): hook the OUTGOING CatchPokemonProto.WriteTo and dump what the bot's catch actually
sends (EncounterId/SpawnPointGuid/HitPokemon/throw params/ArPlus). A malformed request (empty spawn guid,
HitPokemon=false, etc.) would be the only client-side reason the server withholds Star Piece/event dust.
Touches nothing (reads in onEnter)."""
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
function readStr(p){try{if(!p||p.isNull())return null;var len=p.add(0x10).readS32();if(len<0||len>4096)return "?";return p.add(0x14).readUtf16String(len);}catch(e){return "?";}}
var EVENTS=[];
rpc.exports.getEvents=function(){var e=EVENTS;EVENTS=[];return e;};
rpc.exports.install=function(){var h=H_();var st={hooks:0};var k=findClass("holo-protos.dll","CatchPokemonProto");if(!k)return st;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
 while((m=h.cGM(k,it))&&!m.isNull()){try{var mn=h.mGN(m).readCString();if(mn!=="WriteTo"&&mn!=="kfe")continue;if(h.mGPC(m)!==1)continue;var code=m.readPointer();if(!code||code.isNull())continue;var lbl=mn;
  Interceptor.attach(code,{onEnter:function(a){try{var s=a[0];if(!s||s.isNull())return;
    EVENTS.push({via:lbl,enc:s.add(0x10).readU64().toString(),ball:s.add(0x18).readS32(),reticle:s.add(0x20).readDouble(),
      spawn:readStr(s.add(0x28).readPointer()),hit:s.add(0x30).readU8(),spin:s.add(0x38).readDouble(),
      hitpos:s.add(0x40).readDouble(),arplus:(s.add(0x48).readPointer().isNull()?"null":"set"),flee:s.add(0x50).readU8()});
  }catch(e){}}});
  st.hooks++;}catch(e){}}
 return st;};
"""


def main():
    sess, pid = pg.get_session()
    sc = pg.get_script_with_helpers(sess, JS)
    st = sc.exports_sync.install()
    print(f"attached {pid} | hooks={st.get('hooks')}", flush=True)
    if not st.get("hooks"):
        print("no hooks"); sess.detach(); return
    print("reading the bot's outgoing catch requests...", flush=True)
    t0 = time.time(); n = 0
    while time.time() - t0 < 90 and n < 12:
        time.sleep(1.0)
        for e in (sc.exports_sync.get_events() or []):
            n += 1
            print(f"  via={e.get('via')} enc={e['enc']} ball={e['ball']} spawnGUID={e['spawn']!r} HitPokemon={e['hit']} "
                  f"reticle={e['reticle']:.2f} spin={e['spin']:.2f} hitPos={e['hitpos']:.2f} arPlus={e['arplus']} flee={e['flee']}", flush=True)
    print(f"done ({n} requests read)", flush=True)
    sess.detach()


main()

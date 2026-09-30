"""Find the UI-FREE network catch path: every method that consumes CatchPokemonProto or returns
CatchPokemonOutProto (names are obfuscated, types aren't), + the encounter-open network methods.
READ-ONLY. Lets us send the catch RPC directly with no encounter UI."""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),mGP:b("il2cpp_method_get_param","pointer",["pointer","uint32"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function rtName(m){try{return H_().tGN(H_().mGRT(m)).readCString();}catch(e){return "";}}
function pName(m,i){try{return H_().tGN(H_().mGP(m,i)).readCString();}catch(e){return "";}}
rpc.exports.scanByType=function(sub){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);var out=[];for(var i=0;i<cnt&&out.length<60;i++){var k=h.iGC(im,i);if(k.isNull())continue;var cn;try{cn=h.CGN(k).readCString();}catch(e){continue;}var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()){try{var pc=h.mGPC(m);var rt=rtName(m);var hit=(rt.indexOf(sub)>=0);var ps=[];for(var j=0;j<pc;j++){var pn=pName(m,j);ps.push(pn);if(pn.indexOf(sub)>=0)hit=true;}if(hit){out.push(cn+"."+h.mGN(m).readCString()+"("+ps.join(", ")+") -> "+rt);if(out.length>=60)break;}}catch(e){}}}return out;};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        for sub in ["CatchPokemonOutProto", "CatchPokemonProto", "PokemonEncounterResponse", "EncounterOutProto"]:
            r = sc.exports_sync.scan_by_type(sub)
            print(f"\n===== methods touching '{sub}' ({len(r)}) =====")
            for x in r:
                print("  ", x)
        sess.detach()
    finally:
        try: sess.detach()
        except Exception: pass


main()

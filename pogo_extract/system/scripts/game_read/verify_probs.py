"""VERIFY (READ-ONLY): read the per-ball capture probabilities from a live EncounterState via
get_EncounterResponse -> BaseCaptureProbability, to confirm the offsets/path the optimized catcher uses.
Runs alongside the catcher (which keeps opening encounters). Touches nothing."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function inv(m,obj){var h=H_();if(!m)return null;var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,ptr(0),exc);if(!exc.readPointer().isNull())return null;return r;}
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.probs=function(esStr){var h=H_();var es=ptr(esStr);var grm=mOf(h.OGC(es),"get_EncounterResponse",0);if(!grm)return {err:"no get_EncounterResponse"};var resp=inv(grm,es);if(!resp||resp.isNull())return {err:"resp null"};var cp=resp.add(0x20).readPointer();if(!cp||cp.isNull())return {err:"cp null"};var bRF=cp.add(0x10).readPointer(),pRF=cp.add(0x18).readPointer();if(bRF.isNull()||pRF.isNull())return {err:"rf null"};var bA=bRF.add(0x10).readPointer(),bC=bRF.add(0x18).readS32(),pA=pRF.add(0x10).readPointer(),pC=pRF.add(0x18).readS32();var n=Math.min(bC,pC);if(n<=0||n>8)return {err:"bad count "+bC+"/"+pC};var m={};for(var i=0;i<n;i++){m[bA.add(0x20+i*4).readS32()]=pA.add(0x20+i*4).readFloat();}return {n:n,probs:m};};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    ns = sc.exports_sync.ns_of("EncounterState")
    print("EncounterState ns:", ns)
    got = 0
    for attempt in range(8):
        r = finder.exports_sync.find_singleton(ns, "EncounterState")
        hits = [h for h in (r.get("hits", []) if isinstance(r, dict) else []) if sc.exports_sync.cls_name(h) == "EncounterState"]
        for h in hits:
            res = sc.exports_sync.probs(h)
            if isinstance(res, dict) and res.get("probs"):
                pr = res["probs"]
                print(f"  EncounterState {h}: per-ball base catch prob -> "
                      f"Poke={pr.get('1')} Great={pr.get('2')} Ultra={pr.get('3')}  (raw {pr})")
                got += 1
            else:
                print(f"  EncounterState {h}: {res}")
        if got >= 3:
            break
        time.sleep(2)
    print(f"\nread {got} live probability sets")
    sess.detach()


main()

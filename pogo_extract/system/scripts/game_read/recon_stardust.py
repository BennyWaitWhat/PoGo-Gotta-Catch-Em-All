"""Find + read the player's Stardust counter (and box count) so we can verify whether the UI-free
catches actually credit stardust server-side. READ-ONLY."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function inv(m,obj){var h=H_();var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,ptr(0),exc);if(!exc.readPointer().isNull())return null;return r;}
rpc.exports.find=function(sub){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);var out=[];var subl=sub.toLowerCase();for(var i=0;i<cnt&&out.length<40;i++){var k=h.iGC(im,i);if(k.isNull())continue;var cn;try{cn=h.CGN(k).readCString();}catch(e){continue;}var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()){try{var nm=h.mGN(m).readCString();if(nm.toLowerCase().indexOf(subl)>=0&&h.mGPC(m)===0){var rt=h.tGN(h.mGRT(m)).readCString();if(rt.indexOf("Int")>=0)out.push(cn+"."+nm+" -> "+rt);}}catch(e){}}}return out;};
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.readNum=function(inst,name){var h=H_();var m=mOf(h.OGC(ptr(inst)),name,0);if(!m)return null;var r=inv(m,ptr(inst));if(!r)return null;try{return {i32:r.add(0x10).readS32(), i64:r.add(0x10).readS64().toString()};}catch(e){return null;}};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        finder = pg.get_script_with_helpers(sess)
        sc = pg.get_script_with_helpers(sess, JS)
        try:
            cands = sc.exports_sync.find("Stardust")
            print(f"\n== Stardust 0-arg int getters ({len(cands)}) ==")
            for c in cands:
                print("  ", c)
            # try to read each candidate's class as a singleton
            seen = set()
            for c in cands:
                cls = c.split(".")[0]; meth = c.split(".")[1].split(" ")[0]
                if cls in seen:
                    continue
                seen.add(cls)
                ns = sc.exports_sync.ns_of(cls)
                if not ns:
                    continue
                r = finder.exports_sync.find_singleton(ns, cls)
                for h in (r.get("hits", []) if isinstance(r, dict) else [])[:3]:
                    if sc.exports_sync.cls_name(h) != cls:
                        continue
                    val = sc.exports_sync.read_num(h, meth)
                    if val:
                        print(f"   {cls}.{meth} @{h} = {val}")
                        break
        finally:
            try: sc.unload(); finder.unload()
            except Exception: pass
    finally:
        try: sess.detach()
        except Exception: pass


main()

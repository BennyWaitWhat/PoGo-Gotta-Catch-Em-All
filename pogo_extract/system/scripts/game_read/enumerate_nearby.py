"""#2 Step A (READ-ONLY): enumerate nearby WildMapPokemon instances and read encounterId/pokemonId/cp/
spawn/visible via simple property getters. Verifies the auto-catcher's target enumeration works and
shows what's catchable right now. No catches, no encounters opened."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"]),dGet:b("il2cpp_domain_get","pointer",[])};
 H.tA(H.dG());return H;}
function inv0(inst,name){var h=H_();var k=h.OGC(ptr(inst));if(k.isNull())return null;var m=h.cMN(k,Memory.allocUtf8String(name),0);if(!m||m.isNull())return null;var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var ret=h.rI(m,ptr(inst),ptr(0),exc);if(!exc.readPointer().isNull())return null;return ret;}
function rstr(p){try{if(p.isNull())return null;var len=p.add(0x10).readS32();if(len<0||len>200)return null;return p.add(0x14).readUtf16String(len);}catch(e){return null;}}
rpc.exports.clsName=function(inst){var h=H_();try{return h.CGN(h.OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.wmp=function(inst){
 var out={};
 try{var r=inv0(inst,"get_EncounterId");out.encId=r?r.add(0x10).readU64().toString():null;}catch(e){}
 try{var r=inv0(inst,"get_PokemonId");out.pid=r?r.add(0x10).readS32():null;}catch(e){}
 try{var r=inv0(inst,"get_Cp");out.cp=r?r.add(0x10).readS32():null;}catch(e){}
 try{var r=inv0(inst,"get_VisibleOnMap");out.vis=r?!!r.add(0x10).readU8():null;}catch(e){}
 try{var r=inv0(inst,"get_SpawnPointId");out.spawn=rstr(r);}catch(e){}
 return out;
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        finder = pg.get_script_with_helpers(sess)
        sc = pg.get_script_with_helpers(sess, JS)
        try:
            for cls in ["WildMapPokemon", "MapPokemon"]:
                r = finder.exports_sync.find_singleton("Niantic.Holoholo.Map", cls)
                hits = r.get("hits", []) if isinstance(r, dict) else []
                print(f"\n== {cls}: {len(hits)} instance(s) ==")
                shown = 0
                seen = set()
                for h in hits:
                    if sc.exports_sync.cls_name(h) != cls:
                        continue
                    info = sc.exports_sync.wmp(h)
                    # a real spawn has a pokemon id (or cp, or is visible) — encounterId may be 0 until requested
                    if not (info.get("pid") or info.get("cp") or info.get("vis")):
                        continue
                    key = info.get("encId") or h
                    if key in seen:
                        continue
                    seen.add(key)
                    print(f"   @{h}  enc={info.get('encId')} pid={info.get('pid')} cp={info.get('cp')} vis={info.get('vis')} spawn={info.get('spawn')}")
                    shown += 1
                    if shown >= 25:
                        break
                if shown == 0:
                    print("   (no instances with a pokemonId/cp/visible — no active spawns near you right now)")
        finally:
            try: sc.unload(); finder.unload()
            except Exception: pass
    finally:
        try: sess.detach()
        except Exception: pass


main()

"""Count the game's real active-spawn list (MapPlaceDirectoryService.get_AllPokemon) vs what the
memory-scan find_singleton sees. Tells us if the low catch supply is enumeration (scan misses spawns)
or genuine spawn density. READ-ONLY."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),isVT:b("il2cpp_class_is_valuetype","int",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function inv(m,obj,params){var h=H_();if(!m)return null;var n=params?params.length:0;var args=ptr(0);if(n){args=Memory.alloc(Process.pointerSize*n);for(var i=0;i<n;i++)args.add(i*Process.pointerSize).writePointer(params[i]);}var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,args,exc);if(!exc.readPointer().isNull())return null;return r;}
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.countAll=function(svcStr){
 var h=H_();var svc=ptr(svcStr);
 var gm=mOf(h.OGC(svc),"get_AllPokemon",0); if(!gm)return {err:"no get_AllPokemon"};
 var e=inv(gm,svc,[]); if(!e||e.isNull())return {err:"null enumerable"};
 var ec=h.OGC(e); var gem=mOf(ec,"GetEnumerator",0); if(!gem)return {err:"no GetEnumerator on "+h.CGN(ec).readCString()};
 var enr=inv(gem,e,[]); if(!enr||enr.isNull())return {err:"null enumerator"};
 var enrC=h.OGC(enr); var vt=!!h.isVT(enrC); var self=vt?enr.add(0x10):enr;
 var mn=mOf(enrC,"MoveNext",0), gc=mOf(enrC,"get_Current",0);
 if(!mn||!gc)return {err:"no MoveNext/Current on "+h.CGN(enrC).readCString()};
 var total=0,vis=0,withEnc=0;var guard=0;
 while(guard++<2000){ var r=inv(mn,self,[]); if(!r||(r.add(0x10).readU8()===0))break; var cur=inv(gc,self,[]); if(!cur||cur.isNull())continue; total++;
   try{var vm=mOf(h.OGC(cur),"get_VisibleOnMap",0); if(vm){var vr=inv(vm,cur,[]); if(vr&&vr.add(0x10).readU8())vis++;}}catch(e2){}
   try{var em=mOf(h.OGC(cur),"get_EncounterId",0); if(em){var er=inv(em,cur,[]); if(er&&er.add(0x10).readU64().compare(uint64(0))!==0)withEnc++;}}catch(e3){}
 }
 return {total:total, visible:vis, withEnc:withEnc, enumClass:h.CGN(enrC).readCString(), vt:vt};
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        finder = pg.get_script_with_helpers(sess)
        sc = pg.get_script_with_helpers(sess, JS)
        try:
            ns = sc.exports_sync.ns_of("MapPlaceDirectoryService")
            svc = None
            if ns:
                r = finder.exports_sync.find_singleton(ns, "MapPlaceDirectoryService")
                svc = next((h for h in (r.get("hits", []) if isinstance(r, dict) else []) if sc.exports_sync.cls_name(h) == "MapPlaceDirectoryService"), None)
            print("MapPlaceDirectoryService:", svc, "ns:", ns)
            if svc:
                print("get_AllPokemon count:", sc.exports_sync.count_all(svc))
            rw = finder.exports_sync.find_singleton("Niantic.Holoholo.Map", "WildMapPokemon")
            hits = [h for h in (rw.get("hits", []) if isinstance(rw, dict) else []) if sc.exports_sync.cls_name(h) == "WildMapPokemon"]
            print(f"find_singleton WildMapPokemon instances: {len(hits)}")
        finally:
            try: sc.unload(); finder.unload()
            except Exception: pass
    finally:
        try: sess.detach()
        except Exception: pass


main()

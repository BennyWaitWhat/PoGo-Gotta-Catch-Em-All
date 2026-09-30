"""RECON pass 3 (READ-ONLY): verify the dangling-reward count. Find QuestService, enumerate get_Quests(),
and count quests with a pending Pokemon reward (GetPokemonEncounterForQuest != null). Touches nothing."""
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
rpc.exports.hasGetQuests=function(qsStr){var h=H_();return !!mOf(h.OGC(ptr(qsStr)),"get_Quests",0);};
rpc.exports.questCounts=function(qsStr){
 var h=H_(); var qs=ptr(qsStr); var qc=h.OGC(qs);
 var gQ=mOf(qc,"get_Quests",0); if(!gQ)return {err:"no get_Quests on this instance"};
 var e=inv(gQ,qs,[]); if(!e||e.isNull())return {total:0,dangling:0,note:"get_Quests null"};
 var gem=mOf(h.OGC(e),"GetEnumerator",0); if(!gem)return {err:"no GetEnumerator"};
 var enr=inv(gem,e,[]); if(!enr||enr.isNull())return {total:0,dangling:0};
 var enrC=h.OGC(enr); var self=h.isVT(enrC)?enr.add(0x10):enr;
 var mn=mOf(enrC,"MoveNext",0), gc=mOf(enrC,"get_Current",0); if(!mn||!gc)return {err:"no MoveNext/get_Current"};
 var gpe=mOf(qc,"GetPokemonEncounterForQuest",1);
 var total=0,dangling=0,guard=0,danglingErr=(gpe?0:1);
 while(guard++<6000){ var r=inv(mn,self,[]); if(!r||r.add(0x10).readU8()===0)break; var cur=inv(gc,self,[]); if(!cur||cur.isNull())continue; total++;
   if(gpe){ try{ var enc=inv(gpe,qs,[cur]); if(enc && !enc.isNull()) dangling++; }catch(e2){} }
 }
 return {total:total,dangling:dangling,gpeMissing:danglingErr};
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        ns = sc.exports_sync.ns_of("QuestService")
        print("QuestService ns:", ns)
        if not ns:
            print("QuestService not found"); return
        r = finder.exports_sync.find_singleton(ns, "QuestService")
        hits = [h for h in (r.get("hits", []) if isinstance(r, dict) else [])
                if sc.exports_sync.cls_name(h) == "QuestService"]
        print(f"QuestService hits: {len(hits)}")
        best = None
        for h in hits:
            if not sc.exports_sync.has_get_quests(h):
                continue
            c = sc.exports_sync.quest_counts(h)
            print("  ", h, c)
            if isinstance(c, dict) and c.get("total", 0) > 0:
                if best is None or c.get("total", 0) > best[1].get("total", 0):
                    best = (h, c)
        if best:
            print(f"\n>>> QuestService @ {best[0]}: total quests = {best[1].get('total')}, "
                  f"PENDING POKEMON REWARDS (dangling) = {best[1].get('dangling')}")
        else:
            print("\nno QuestService instance returned quests")
    finally:
        try:
            sc.unload(); finder.unload()
        except Exception:
            pass
        try:
            sess.detach()
        except Exception:
            pass


main()

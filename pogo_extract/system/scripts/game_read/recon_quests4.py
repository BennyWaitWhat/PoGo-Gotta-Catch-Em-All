"""RECON pass 4 (READ-ONLY): count dangling Pokemon rewards via get_QuestsProto() -> RepeatedField<QuestProto>
(avoids the explicit-interface enumerator). For each quest, GetPokemonEncounterForQuest != null => pending
reward. Also samples a few encounter protos. Touches nothing."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),isVT:b("il2cpp_class_is_valuetype","int",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function inv(m,obj,params){var h=H_();if(!m)return null;var n=params?params.length:0;var args=ptr(0);if(n){args=Memory.alloc(Process.pointerSize*n);for(var i=0;i<n;i++)args.add(i*Process.pointerSize).writePointer(params[i]);}var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,args,exc);if(!exc.readPointer().isNull())return null;return r;}
function getterByRet(obj,substr){var h=H_();var k=h.OGC(obj);var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;while((m=h.cGM(k,it))&&!m.isNull()){try{if(h.mGPC(m)!==0)continue;var rt=h.tGN(h.mGRT(m)).readCString();if(rt.indexOf(substr)>=0)return m;}catch(e){}}return null;}
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.questCounts2=function(qsStr){
 var h=H_(); var qs=ptr(qsStr); var qc=h.OGC(qs);
 var gqp=mOf(qc,"get_QuestsProto",0); if(!gqp)return {err:"no get_QuestsProto"};
 var qp=inv(gqp,qs,[]); if(!qp||qp.isNull())return {err:"QuestsProto null"};
 var rfm=getterByRet(qp,"RepeatedField"); if(!rfm)return {err:"no RepeatedField getter on QuestsProto"};
 var rf=inv(rfm,qp,[]); if(!rf||rf.isNull())return {err:"rf null"};
 var rfc=h.OGC(rf);
 var gCount=mOf(rfc,"get_Count",0), gItem=mOf(rfc,"get_Item",1);
 if(!gCount||!gItem)return {err:"no get_Count/get_Item on rf"};
 var cntB=inv(gCount,rf,[]); var cnt=cntB?cntB.add(0x10).readS32():-1;
 var gpe=mOf(qc,"GetPokemonEncounterForQuest",1);
 var dangling=0, samples=[];
 if(gpe){ for(var i=0;i<cnt;i++){ var idx=Memory.alloc(4); idx.writeS32(i); var q=inv(gItem,rf,[idx]); if(!q||q.isNull())continue;
   try{ var enc=inv(gpe,qs,[q]); if(enc&&!enc.isNull()){ dangling++; if(samples.length<5){ var em=mOf(h.OGC(enc),"get_EncounterId",0); var eid=null; if(em){var er=inv(em,enc,[]); if(er)eid=er.add(0x10).readU64().toString();} samples.push(eid); } } }catch(e){}
 } }
 return {total:cnt,dangling:dangling,gpe:!!gpe,samples:samples};
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        ns = sc.exports_sync.ns_of("QuestService")
        r = finder.exports_sync.find_singleton(ns, "QuestService")
        hits = [h for h in (r.get("hits", []) if isinstance(r, dict) else [])
                if sc.exports_sync.cls_name(h) == "QuestService"]
        print(f"QuestService instances: {len(hits)}")
        best = None
        for h in hits:
            c = sc.exports_sync.quest_counts2(h)
            print("  ", h, c)
            if isinstance(c, dict) and c.get("total", 0) and c.get("total", 0) > 0:
                if best is None or c["total"] > best[1]["total"]:
                    best = (h, c)
        if best:
            print(f"\n>>> total quests={best[1]['total']}  PENDING POKEMON REWARDS={best[1]['dangling']}")
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

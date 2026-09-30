"""RECON pass 6 (READ-ONLY): count dangling rewards via get_ProgressedQuests() -> HashSet<String>,
enumerated through the non-generic IEnumerator interface (virtual dispatch), then
GetPokemonEncounterForQuest(questId) != null => pending reward. Touches nothing."""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),oGVM:b("il2cpp_object_get_virtual_method","pointer",["pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function corlib(){var n=["mscorlib.dll","System.Private.CoreLib.dll","netstandard.dll"];for(var i=0;i<n.length;i++){var im=img(n[i]);if(im)return im;}return null;}
function cFN(im,ns,nm){return H_().cFN(im,Memory.allocUtf8String(ns),Memory.allocUtf8String(nm));}
function mOf(k,nm,argc){var h=H_();if(!k)return null;var m=h.cMN(k,Memory.allocUtf8String(nm),argc);return (m&&!m.isNull())?m:null;}
function inv(m,obj,params){var h=H_();if(!m)return null;var n=params?params.length:0;var args=ptr(0);if(n){args=Memory.alloc(Process.pointerSize*n);for(var i=0;i<n;i++)args.add(i*Process.pointerSize).writePointer(params[i]);}var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,args,exc);if(!exc.readPointer().isNull())return null;return r;}
function readStr(s){try{var len=s.add(0x10).readS32();if(len<0||len>8192)return null;return s.add(0x14).readUtf16String(len);}catch(e){return null;}}
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.diag=function(){var h=H_();var cl=corlib();var IEable=cl?cFN(cl,"System.Collections","IEnumerable"):null;var IEor=cl?cFN(cl,"System.Collections","IEnumerator"):null;return {corlib:cl?"ok":"NO",IEable:(IEable&&!IEable.isNull())?"ok":"NO",IEor:(IEor&&!IEor.isNull())?"ok":"NO",oGVM:H_().oGVM?"ok":"NO"};};
rpc.exports.countProgressed=function(qsStr){
 var h=H_(); var qs=ptr(qsStr); var qc=h.OGC(qs);
 var gpq=mOf(qc,"get_ProgressedQuests",0); if(!gpq)return {err:"no get_ProgressedQuests"};
 var hs=inv(gpq,qs,[]); if(!hs||hs.isNull())return {progressed:0,dangling:0,note:"progressed null"};
 var cl=corlib(); var IEable=cFN(cl,"System.Collections","IEnumerable"), IEor=cFN(cl,"System.Collections","IEnumerator");
 var mGE=mOf(IEable,"GetEnumerator",0), mMN=mOf(IEor,"MoveNext",0), mGC=mOf(IEor,"get_Current",0);
 if(!mGE||!mMN||!mGC)return {err:"no interface methods"};
 var cGE=h.oGVM(hs,mGE); if(!cGE||cGE.isNull())return {err:"oGVM GetEnumerator failed"};
 var enr=inv(cGE,hs,[]); if(!enr||enr.isNull())return {err:"enumerator null"};
 var cMNx=h.oGVM(enr,mMN), cGCx=h.oGVM(enr,mGC); if(!cMNx||!cGCx)return {err:"oGVM MoveNext/Current failed"};
 var gpe=mOf(qc,"GetPokemonEncounterForQuest",1);
 var total=0,dangling=0,samples=[],guard=0;
 while(guard++<8000){ var r=inv(cMNx,enr,[]); if(!r||r.add(0x10).readU8()===0)break; var cur=inv(cGCx,enr,[]); if(!cur||cur.isNull())continue; total++;
   if(gpe){ try{ var enc=inv(gpe,qs,[cur]); if(enc&&!enc.isNull()){ dangling++; if(samples.length<8)samples.push(readStr(cur)); } }catch(e){} }
 }
 return {progressed:total,dangling:dangling,gpe:!!gpe,samples:samples};
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        print("diag:", sc.exports_sync.diag())
        ns = sc.exports_sync.ns_of("QuestService")
        r = finder.exports_sync.find_singleton(ns, "QuestService")
        hits = [h for h in (r.get("hits", []) if isinstance(r, dict) else [])
                if sc.exports_sync.cls_name(h) == "QuestService"]
        print(f"QuestService instances: {len(hits)}")
        best = None
        for h in hits:
            c = sc.exports_sync.count_progressed(h)
            print("  ", h, c)
            if isinstance(c, dict) and c.get("progressed", 0) and c["progressed"] > 0:
                if best is None or c["progressed"] > best[1]["progressed"]:
                    best = (h, c)
        if best:
            print(f"\n>>> progressed quests={best[1]['progressed']}  PENDING POKEMON REWARDS={best[1]['dangling']}")
            print("    sample quest ids:", best[1].get("samples"))
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

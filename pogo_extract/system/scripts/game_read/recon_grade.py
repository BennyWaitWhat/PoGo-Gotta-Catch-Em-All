"""RECON (READ-ONLY): definitively find the Excellent reticle value + the throw multipliers.
Dumps EncounterSettingsProto fields (multipliers + thresholds), finds a live one, then calls the game's
PokeballThrow.GetGrade(settings) across reticle values to see which grades Excellent. Touches nothing."""
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
 H={dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),dG:b("il2cpp_domain_get","pointer",[]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cGNT:b("il2cpp_class_get_nested_types","pointer",["pointer","pointer"]),oN:b("il2cpp_object_new","pointer",["pointer"]),isVT:b("il2cpp_class_is_valuetype","int",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
var PBTC=null, GG=null;
rpc.exports.setup=function(){var h=H_();PBTC=findClass("holo-game.dll","PokeballThrow");GG=PBTC?h.cMN(PBTC,Memory.allocUtf8String("GetGrade"),1):null;return {pbt:!!PBTC,gg:!!(GG&&!GG.isNull()),vt:PBTC?!!h.isVT(PBTC):null};};
rpc.exports.nsOf=function(cls){var h=H_();for(var ii=0;ii<2;ii++){var im=img(ii?"holo-protos.dll":"holo-game.dll");if(!im)continue;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.fields=function(cls,image){var h=H_();var k=findClass(image,cls);if(!k)return null;var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.cGF(k,it))&&!f.isNull()&&out.length<120){try{var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}out.push("+0x"+h.fGO(f).toString(16)+" "+h.fGN(f).readCString()+" : "+tn);}catch(e){}}return out;};
rpc.exports.thresh=function(s){var p=ptr(s);try{return {spin:p.add(0x10).readFloat(),excellent:p.add(0x14).readFloat(),great:p.add(0x18).readFloat(),nice:p.add(0x1c).readFloat(),critRet:p.add(0x68).readFloat(),critMult:p.add(0x6c).readFloat(),globalDust:p.add(0x60).readFloat()};}catch(e){return ""+e;}};
rpc.exports.gradeOf=function(x,settingsStr){var h=H_();if(!GG||GG.isNull())return "no GG";try{var obj=h.oN(PBTC);obj.add(0x10).writeS32(1);obj.add(0x14).writeFloat(x);obj.add(0x18).writeU8(1);obj.add(0x19).writeU8(1);obj.add(0x1a).writeU8(0);var self=h.isVT(PBTC)?obj.add(0x10):obj;var args=Memory.alloc(Process.pointerSize);args.writePointer(ptr(settingsStr));var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(GG,self,args,exc);if(!exc.readPointer().isNull())return "exc";return r?r.add(0x10).readS32():"null";}catch(e){return ""+e;}};
"""

GRADE = {0: "Miss", 1: "Normal", 2: "Nice", 3: "Great", 4: "EXCELLENT"}


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        print("setup:", sc.exports_sync.setup())
        print("\n--- EncounterSettingsProto fields (multipliers + thresholds) ---")
        for f in (sc.exports_sync.fields("EncounterSettingsProto", "holo-protos.dll") or []):
            print("   ", f)
        import time
        ns = sc.exports_sync.ns_of("EncounterSettingsProto")
        settings = None
        for _ in range(15):
            r = finder.exports_sync.find_singleton(ns, "EncounterSettingsProto")
            settings = next((h for h in (r.get("hits", []) if isinstance(r, dict) else [])
                             if sc.exports_sync.cls_name(h) == "EncounterSettingsProto"), None)
            if settings:
                break
            time.sleep(2)
        print(f"\nlive EncounterSettingsProto: {settings}")
        if settings:
            print("thresholds:", sc.exports_sync.thresh(settings))
            print("\nReticleSize -> Grade:")
            for x in [0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.85, 1.0, 1.3, 1.7, 2.0]:
                g = sc.exports_sync.grade_of(x, settings)
                print(f"  reticle {x:>4} -> {GRADE.get(g, g)}")
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

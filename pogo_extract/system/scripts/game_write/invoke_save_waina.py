"""Persist the Go Plus+ Ultra-Ball preference SERVER-SIDE by invoking the real save method:
  IPlayerService.SaveWainaPreferences(WainaPreferences)   [Waina-scoped — won't touch other prefs]
Steps: locate a live WainaPreferences (set Ball=ULTRA_BALL=3), DUMP its full fields so we can see
exactly what is being saved, find the live PlayerService, then runtime_invoke the save.
The user then re-tests a catch: Ultra count should now drop instead of Poke."""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

ITEM = {0: "UNKNOWN", 1: "POKE_BALL", 2: "GREAT_BALL", 3: "ULTRA_BALL"}

MY_JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),CGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),FGN:b("il2cpp_field_get_name","pointer",["pointer"]),FGO:b("il2cpp_field_get_offset","uint32",["pointer"]),FGT:b("il2cpp_field_get_type","pointer",["pointer"]),TGN:b("il2cpp_type_get_name","pointer",["pointer"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),rcInit:b("il2cpp_runtime_class_init","void",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return k;}catch(e){}}return null;}
function kp(k){var b=[];var t=ptr(k);for(var i=0;i<8;i++){var v=t.and(0xff).toInt32();b.push((v<16?"0":"")+v.toString(16));t=t.shr(8);}return b.join(" ");}
function _cs(p){try{return p.isNull()?'':p.readCString();}catch(e){return '';}}
function _rd(inst,off,ty){try{
  if(ty==='System.Single')return inst.add(off).readFloat();
  if(ty==='System.Double')return inst.add(off).readDouble();
  if(ty.indexOf('Int64')>=0||ty.indexOf('UInt64')>=0)return inst.add(off).readS64().toString();
  if(ty.indexOf('Item')>=0)return 'Item:'+inst.add(off).readS32();
  if(ty.indexOf('Int32')>=0||ty.indexOf('UInt32')>=0)return inst.add(off).readS32();
  if(ty==='System.Boolean')return !!inst.add(off).readU8();
  return 'ptr:'+inst.add(off).readPointer();}catch(e){return '(err)';}}
function dumpObj(s){var h=H_();if(ptr(s).isNull())return{err:'null'};var k=h.OGC(ptr(s));var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.CGF(k,it))&&!f.isNull()){try{var nm=_cs(h.FGN(f));var o=h.FGO(f);var ty=_cs(h.TGN(h.FGT(f)));out.push(nm+'@0x'+o.toString(16)+':'+ty+' = '+_rd(ptr(s),o,ty));}catch(e){}}return{cls:_cs(h.CGN(k)),fields:out};}
rpc.exports.classNs=function(imageName,clsName){var h=H_();var k=findClass(imageName,clsName);if(!k)return null;return _cs(h.CGNS(k));};
rpc.exports.pickWaina=function(){
 var h=H_();var k=findClass("holo-protos.dll","WainaPreferences");if(!k)return{err:"no class"};
 var pat=kp(k);var best=null;
 Process.enumerateRanges("rw-").forEach(function(r){if(best||r.file||r.size<256||r.size>134217728)return;try{var hs=Memory.scanSync(r.base,r.size,pat);for(var i=0;i<hs.length;i++){var p=hs[i].address;try{var d=dumpObj(p.toString());if(d.cls==="WainaPreferences"){p.add(0x10).writeS32(3);best={addr:p.toString(),fields:dumpObj(p.toString()).fields};break;}}catch(e){}}}catch(e){}});
 return best||{err:"no instance"};
};
rpc.exports.invokeSave=function(psStr,wpStr){
 var h=H_();var psCls=h.OGC(ptr(psStr));var m=h.cMN(psCls,Memory.allocUtf8String("SaveWainaPreferences"),1);
 if(!m||m.isNull())return{err:"no SaveWainaPreferences on this instance"};
 try{h.rcInit(psCls);}catch(e){}
 var wpCls=h.OGC(ptr(wpStr));try{h.rcInit(wpCls);}catch(e){}
 var args=Memory.alloc(Process.pointerSize);args.writePointer(ptr(wpStr));
 var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));
 var ret=h.rI(m,ptr(psStr),args,exc);
 var ep=exc.readPointer();
 if(!ep.isNull()){var k=ep.readPointer();return{ok:false,exc:_cs(h.CGN(k))};}
 return{ok:true,ret:ret.isNull()?"void":ret.toString()};
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        finder = pg.get_script_with_helpers(sess)
        sc = pg.get_script_with_helpers(sess, MY_JS)
        try:
            # 1. the WainaPreferences we will save (Ball forced to 3), with full field dump
            wp = sc.exports_sync.pick_waina()
            if wp.get("err"):
                print("WainaPreferences:", wp["err"]); return
            print(f"\n=== WainaPreferences to SAVE @{wp['addr']} (Ball set to ULTRA_BALL) ===")
            for f in wp["fields"]:
                mark = ""
                if "Item:" in f:
                    try: mark = "   <-- " + ITEM.get(int(f.split("Item:")[1].strip()), "?")
                    except Exception: pass
                print("   ", f, mark)

            # 2. live PlayerService
            ns = sc.exports_sync.class_ns("holo-game.dll", "PlayerService")
            print(f"\nPlayerService namespace: {ns}")
            r = finder.exports_sync.find_singleton(ns, "PlayerService")
            hits = r.get("hits", []) if isinstance(r, dict) else []
            print(f"PlayerService live instances: {len(hits)}")
            if not hits:
                print("no PlayerService instance found"); return

            # 3. invoke the save on each candidate until one succeeds
            done = False
            for ps in hits:
                res = sc.exports_sync.invoke_save(ps, wp["addr"])
                print(f"  invoke on {ps}: {res}")
                if isinstance(res, dict) and res.get("ok"):
                    done = True
                    print("\n>>> SaveWainaPreferences invoked OK — Ultra-Ball pref pushed to the server.")
                    print(">>> TEST: catch a few with VGP3; Ultra count should now drop (Poke should hold).")
                    break
            if not done:
                print("\n(no candidate accepted the call — may need the populated singleton; report output.)")
        finally:
            sc.unload(); finder.unload()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

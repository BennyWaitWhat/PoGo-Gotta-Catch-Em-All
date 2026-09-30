"""LIVE probe (exclusive internal access): hook the Go-Plus catch handler
PgpActivityMonitor.xek(ActionLogEntry) and dump each catch entry + its sub-protos, hunting for the
ball/item field and its value. Shows what the SERVER actually stamps on each VGP3 catch (vs guessing
from static dumps). Run while VGP3 is catching. READ-ONLY (observes)."""
import sys, time, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),FGN:b("il2cpp_field_get_name","pointer",["pointer"]),FGO:b("il2cpp_field_get_offset","uint32",["pointer"]),FGT:b("il2cpp_field_get_type","pointer",["pointer"]),TGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function _cs(p){try{return p.isNull()?'':p.readCString();}catch(e){return '';}}
function _rd(inst,off,ty){try{
  if(ty.indexOf('Item')>=0)return 'Item:'+inst.add(off).readS32();
  if(ty==='System.Single')return inst.add(off).readFloat();
  if(ty==='System.Double')return inst.add(off).readDouble();
  if(ty.indexOf('Int64')>=0||ty.indexOf('UInt64')>=0)return inst.add(off).readS64().toString();
  if(ty.indexOf('Int32')>=0||ty.indexOf('UInt32')>=0)return inst.add(off).readS32();
  if(ty==='System.Boolean')return !!inst.add(off).readU8();
  return 'ptr:'+inst.add(off).readPointer();}catch(e){return '(err)';}}
function dumpObj(s,depth){var h=H_();if(ptr(s).isNull())return null;var k=h.OGC(ptr(s));var cls=_cs(h.CGN(k));var out={cls:cls,f:[]};var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.CGF(k,it))&&!f.isNull()){try{var nm=_cs(h.FGN(f));var o=h.FGO(f);var ty=_cs(h.TGN(h.FGT(f)));var v=_rd(ptr(s),o,ty);out.f.push(nm+'@0x'+o.toString(16)+':'+ty+'='+v);
  if(depth>0 && v.indexOf('ptr:0x')===0 && v!=='ptr:0x0' && ty.indexOf('Proto')>=0 && nm.toLowerCase().indexOf('parser')<0){try{var sub=dumpObj(ptr(s).add(o).readPointer().toString(),depth-1);if(sub)out.f.push('  >>'+nm+': '+JSON.stringify(sub));}catch(e){}}
 }catch(e){}}return out;}
var hits=[];
rpc.exports.setup=function(){
 var h=H_();var gim=img("holo-game.dll");
 var PAM=h.cFN(gim,Memory.allocUtf8String("Niantic.Holoholo.Pgp"),Memory.allocUtf8String("PgpActivityMonitor"));
 var mXek=PAM.isNull()?null:h.cMN(PAM,Memory.allocUtf8String("xek"),1);
 var st={haveXek:!(mXek===null||(mXek&&mXek.isNull()))};
 if(mXek&&!mXek.isNull()){var ad=mXek.readPointer();if(!ad.isNull()){Interceptor.attach(ad,{onEnter:function(a){try{if(hits.length<14){var d=dumpObj(a[1].toString(),2);if(d)hits.push(d);}}catch(e){}}});st.hooked=true;}}
 return st;
};
rpc.exports.results=function(){return hits;};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        st = sc.exports_sync.setup()
        print("setup:", st)
        secs = 45
        print(f"\nWatching Go-Plus catches for {secs}s — let VGP3 catch a few...")
        time.sleep(secs)
        hits = sc.exports_sync.results()
        sess.detach()
        print(f"\ncaptured {len(hits)} action-log entries\n")
        ball_seen = False
        for i, d in enumerate(hits):
            print(f"--- entry {i}: {d.get('cls')} ---")
            for f in d.get("f", []):
                low = f.lower()
                flag = ""
                if any(k in low for k in ["ball", "item", "pokeball", "capture", "catch"]):
                    flag = "   <==="
                    if "item:" in low or "ball" in low:
                        ball_seen = True
                print("   ", f[:200], flag)
        print("\n>>> ball/item field present in the catch entry:" , ball_seen)
        if not hits:
            print(">>> no catches fired — VGP3 wasn't catching during the window. Re-run while it catches.")
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

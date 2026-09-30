"""Read live WainaPreferences (Go Plus + / wearable preferences) to find the ball-selection field
and its current value (POKE_BALL=1, GREAT_BALL=2, ULTRA_BALL=3). Confirms whether VGP3's catch ball
is a settable preference. Also dumps any 'auto throw' / ball Item fields. READ-ONLY."""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

ITEM = {0: "UNKNOWN", 1: "POKE_BALL", 2: "GREAT_BALL", 3: "ULTRA_BALL", 4: "MASTER_BALL", 5: "PREMIER_BALL"}

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),CGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),FGN:b("il2cpp_field_get_name","pointer",["pointer"]),FGO:b("il2cpp_field_get_offset","uint32",["pointer"]),FGT:b("il2cpp_field_get_type","pointer",["pointer"]),TGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(imageName,clsName){var h=H_();var im=img(imageName);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===clsName)return k;}catch(e){}}return null;}
function kp(k){var b=[];var t=ptr(k);for(var i=0;i<8;i++){var v=t.and(0xff).toInt32();b.push((v<16?"0":"")+v.toString(16));t=t.shr(8);}return b.join(" ");}
function _cs(p){try{return p.isNull()?'':p.readCString();}catch(e){return '';}}
function _rd(inst,off,ty){try{
  if(ty==='System.Single')return inst.add(off).readFloat();
  if(ty==='System.Double')return inst.add(off).readDouble();
  if(ty.indexOf('Int64')>=0||ty.indexOf('UInt64')>=0)return inst.add(off).readS64().toString();
  if(ty.indexOf('Int32')>=0||ty.indexOf('UInt32')>=0)return inst.add(off).readS32();
  if(ty.indexOf('Item')>=0)return 'Item:'+inst.add(off).readS32();
  if(ty==='System.Boolean')return !!inst.add(off).readU8();
  return 'ptr:'+inst.add(off).readPointer();}catch(e){return '(err)';}}
function dumpObj(s){var h=H_();if(ptr(s).isNull())return{err:'null'};var k=h.OGC(ptr(s));var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=h.CGF(k,it))&&!f.isNull()){try{var nm=_cs(h.FGN(f));var o=h.FGO(f);var ty=_cs(h.TGN(h.FGT(f)));out.push(nm+'@0x'+o.toString(16)+':'+ty+' = '+_rd(ptr(s),o,ty));}catch(e){}}return{cls:_cs(h.CGN(k)),fields:out};}
rpc.exports.dumpObj=function(s){return dumpObj(s);};
rpc.exports.findInstances=function(imageName,clsName){
 var h=H_();var k=findClass(imageName,clsName);if(!k)return{err:"no class "+clsName};
 var pat=kp(k);var out=[];
 Process.enumerateRanges("rw-").forEach(function(r){if(r.file||r.size<256||r.size>134217728)return;try{var hs=Memory.scanSync(r.base,r.size,pat);for(var i=0;i<hs.length&&out.length<20;i++)out.push(hs[i].address.toString());}catch(e){}});
 return {hits:out};
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        for cls in ["WainaPreferences", "PlayerPreferencesProto", "GlobalSettingsProto"]:
            r = sc.exports_sync.find_instances("holo-protos.dll", cls)
            if isinstance(r, dict) and r.get("err"):
                print(f"\n== {cls}: {r['err']}")
                continue
            hits = r.get("hits", [])
            print(f"\n== {cls}: {len(hits)} candidate instance(s) ==")
            shown = 0
            seen_sig = set()
            for h in hits:
                d = sc.exports_sync.dump_obj(h)
                if d.get("cls") != cls:
                    continue
                # only show ones with ball/throw/item fields, dedupe by field signature
                fields = d.get("fields", [])
                ball_fields = [f for f in fields if any(k in f.lower() for k in ["ball", "item", "throw", "auto"])]
                if not ball_fields and cls == "WainaPreferences":
                    pass  # still show waina
                sig = tuple(f.split("=")[0] for f in fields)
                if sig in seen_sig:
                    continue
                seen_sig.add(sig)
                print(f"  @{h}:")
                for f in fields:
                    mark = ""
                    if "Item:" in f:
                        try:
                            v = int(f.split("Item:")[1].strip())
                            mark = f"   <-- {ITEM.get(v, '?')}"
                        except Exception:
                            pass
                    if any(k in f.lower() for k in ["ball", "throw", "item"]):
                        print(f"      {f}{mark}")
                shown += 1
                if shown >= 3:
                    break
            if shown == 0:
                print("  (no valid instances)")
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

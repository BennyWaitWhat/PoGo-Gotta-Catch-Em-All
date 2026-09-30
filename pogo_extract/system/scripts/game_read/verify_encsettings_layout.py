"""VERIFY (READ-ONLY): cross-check the EncounterSettingsProto field offsets against
IL2CPP metadata, then hex-dump the live instance and read EVERY field via metadata
offsets (not hard-coded). Confirms whether GlobalStardustMultiplier is truly 0 or
whether the offsets were misaligned. Re-resolves the live proto via the global
proto-bag each run. Attaches alongside the catcher; touches nothing.
"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),dG:b("il2cpp_domain_get","pointer",[]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cGParent:b("il2cpp_class_get_parent","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(image,cls){var h=H_();var im=img(image);if(!im)return null;var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}return null;}
function cname(o){try{var h=H_();return (h.CGNS(h.OGC(ptr(o))).readCString()||"")+"."+h.CGN(h.OGC(ptr(o))).readCString();}catch(e){return null;}}
rpc.exports.clsName=function(inst){return cname(inst);};
rpc.exports.readPtr=function(inst,off){try{var p=ptr(inst).add(off).readPointer();return p.isNull()?null:p.toString();}catch(e){return ""+e;}};

// Metadata field layout of a class by image+name (instance fields only, with offset+type).
rpc.exports.fieldLayout=function(cls,image){var h=H_();var k=findClass(image,cls);if(!k)return {err:"class not found"};var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
 while((f=h.cGF(k,it))&&!f.isNull()&&out.length<200){try{var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}out.push({off:h.fGO(f),name:h.fGN(f).readCString(),type:tn});}catch(e){}}
 return {fields:out};};

// Read each metadata field off a live instance, decoding by simple type name.
rpc.exports.readAllFields=function(inst,cls,image){var h=H_();var k=findClass(image,cls);if(!k)return {err:"class not found"};var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;var base=ptr(inst);
 while((f=h.cGF(k,it))&&!f.isNull()&&out.length<200){try{var off=h.fGO(f);var nm=h.fGN(f).readCString();var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}
  var rec={off:off,name:nm,type:tn};var p=base.add(off);
  try{
   if(tn==="System.Single")rec.val=p.readFloat();
   else if(tn==="System.Int32"||tn.indexOf("Enum")>=0)rec.val=p.readS32();
   else if(tn==="System.Boolean")rec.val=p.readU8();
   else if(tn==="System.Int64")rec.val=p.readS64().toString();
   else if(tn==="System.Double")rec.val=p.readDouble();
   else if(tn==="System.UInt32")rec.val=p.readU32();
   else {var pp=p.readPointer();rec.val=pp.isNull()?"null":("ptr "+pp.toString());}
  }catch(e){rec.val="ERR "+e;}
  out.push(rec);}catch(e){}}
 return {fields:out};};

// Raw hex dump first N bytes of an instance (after the il2cpp object header at +0x10).
rpc.exports.hexFloats=function(inst,nbytes){var p=ptr(inst);var out=[];for(var o=0x10;o<0x10+nbytes;o+=4){try{out.push({off:o, i32:p.add(o).readS32(), f32:p.add(o).readFloat()});}catch(e){break;}}return out;};
"""

ENC_NS = "Niantic.Holoholo.Encounter"
ENC_CLS = "EncounterState"
ENC_PROTO = "EncounterSettingsProto"


def resolve_proto(finder, sc):
    """EncounterState @0x150 -> GameMasterData; crlp dict @0xd8 -> find EncounterSettingsProto value."""
    for _ in range(8):
        r = finder.exports_sync.find_singleton(ENC_NS, ENC_CLS)
        hits = r.get("hits", []) if isinstance(r, dict) else []
        for h in hits:
            cn = sc.exports_sync.cls_name(h)
            if not (cn and cn.endswith("." + ENC_CLS)):
                continue
            gm = sc.exports_sync.read_ptr(h, 0x150)
            if not (gm and gm.startswith("0x")):
                continue
            dictp = sc.exports_sync.read_ptr(gm, 0xd8)
            if not (dictp and dictp.startswith("0x")):
                continue
            # walk the Dictionary<Type,IMessage>: entries @+0x18, array first elem @+0x20, stride 0x18, value @+0x10
            res = sc.exports_sync.walk_proto_bag(dictp)
            for ent in (res.get("entries", []) if isinstance(res, dict) else []):
                if ent.get("cls") and ent["cls"].endswith("." + ENC_PROTO):
                    return ent["ptr"], gm
        time.sleep(1.0)
    return None, None


# Add a tiny proto-bag walker (value class @ +0x10) to JS via a second export.
JS += r"""
function cname2(o){try{var h=H_();return (h.CGNS(h.OGC(ptr(o))).readCString()||"")+"."+h.CGN(h.OGC(ptr(o))).readCString();}catch(e){return null;}}
rpc.exports.walkProtoBag=function(dictAddr){var d=ptr(dictAddr);var out={entries:[]};try{
  var entries=d.add(0x18).readPointer();var count=d.add(0x20).readS32();if(entries.isNull()){out.err="null";return out;}
  var alen=entries.add(0x18).readS32();var base=entries.add(0x20);var n=Math.min(count<0?alen:count,alen,4000);
  for(var i=0;i<n;i++){var e=base.add(i*0x18);var v=null;try{v=e.add(0x10).readPointer();}catch(_){}
   if(v&&!v.isNull())out.entries.push({idx:i,cls:cname2(v),ptr:v.toString()});}
 }catch(e){out.err=""+e;}return out;};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        # 1. Authoritative metadata layout
        print(f"\n=== {ENC_PROTO} metadata field layout (holo-protos.dll) ===", flush=True)
        lay = sc.exports_sync.field_layout(ENC_PROTO, "holo-protos.dll")
        if isinstance(lay, dict) and lay.get("err"):
            print("  layout err:", lay["err"], flush=True)
        for f in (lay.get("fields", []) if isinstance(lay, dict) else []):
            print(f"   +0x{f['off']:x} {f['name']} : {f['type']}", flush=True)

        # 2. Resolve a live proto
        proto, gm = resolve_proto(finder, sc)
        print(f"\nlive {ENC_PROTO} = {proto}  (via GameMasterData {gm})", flush=True)
        if not proto:
            print("could not resolve live proto", flush=True); return
        print("class check:", sc.exports_sync.cls_name(proto), flush=True)

        # 3. Read every field by metadata offset
        print(f"\n=== ALL FIELDS read by metadata offset off {proto} ===", flush=True)
        allf = sc.exports_sync.read_all_fields(proto, ENC_PROTO, "holo-protos.dll")
        for f in (allf.get("fields", []) if isinstance(allf, dict) else []):
            print(f"   +0x{f['off']:x} {f['name']} ({f['type']}) = {f['val']}", flush=True)

        # 4. Raw float/i32 hex window for sanity
        print(f"\n=== raw [off, i32, f32] dump 0x10..0x90 ===", flush=True)
        for r in (sc.exports_sync.hex_floats(proto, 0x80) or []):
            f = r["f32"]
            note = ""
            if -1e6 < f < 1e6 and f != 0 and (abs(f) > 1e-3):
                note = "  <- plausible float"
            print(f"   +0x{r['off']:x}: i32={r['i32']:>12}  f32={f:.6g}{note}", flush=True)
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

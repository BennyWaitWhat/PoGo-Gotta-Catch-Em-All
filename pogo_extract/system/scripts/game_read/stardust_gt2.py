"""GROUND-TRUTH stardust audit pass 2. READ-ONLY.
- Broaden the InventoryCache walk: identify the oneof case that holds currency by reading
  each entry's value class name; dump the ClientInventoryItem proto fields; for the
  currency/stats entries, resolve via proto getters not raw offsets.
- Re-do IapService read on every instance (i32 + i64).
- Broaden getter hunt: list ALL 0-arg getters returning ANY numeric on Player*/Currency*/Iap* classes.
One attach.
"""
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function mInv(m,obj){var h=H_();var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,ptr(0),exc);if(!exc.readPointer().isNull())return null;return r;}
function cname(o){try{return H_().CGN(H_().OGC(ptr(o))).readCString();}catch(e){return null;}}

rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){return cname(inst);};
rpc.exports.readNum=function(inst,name){var h=H_();var m=h.cMN(h.OGC(ptr(inst)),Memory.allocUtf8String(name),0);if(!m||m.isNull())return null;var r=mInv(m,ptr(inst));if(!r)return null;try{return {i32:r.add(0x10).readS32(), i64:r.add(0x10).readS64().toString()};}catch(e){return null;}};

// dump fields of a class found in either image
rpc.exports.fields=function(ns,cls){var h=H_();var im=img("holo-protos.dll");var k=h.cFN(im,Memory.allocUtf8String(ns),Memory.allocUtf8String(cls));if(!k||k.isNull()){im=img("holo-game.dll");k=h.cFN(im,Memory.allocUtf8String(ns),Memory.allocUtf8String(cls));}if(!k||k.isNull())return {err:"cls not found"};var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;var out=[];while((f=h.cGF(k,it))&&!f.isNull()){try{out.push({name:h.fGN(f).readCString(),off:h.fGO(f),type:h.tGN(h.fGT(f)).readCString()});}catch(e){}}return {fields:out};};

// list ALL 0-arg getters returning numeric on a class (by ns/cls in holo-game.dll)
rpc.exports.numGetters=function(ns,cls){var h=H_();var im=img("holo-game.dll");var k=h.cFN(im,Memory.allocUtf8String(ns),Memory.allocUtf8String(cls));if(!k||k.isNull())return {err:"cls not found"};var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;var out=[];while((m=h.cGM(k,it))&&!m.isNull()){try{if(h.mGPC(m)!==0)continue;var nm=h.mGN(m).readCString();var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(nm+" -> "+rt);}catch(e){}}return {getters:out};};

// Walk InventoryCache, for the currency/stats cases pull the inner proto via getters.
// case5 value is a ClientInventoryItem wrapping a PlayerCurrency oneof; the holder exposes
// get_PlayerCurrency / get_PlayerStats returning the proto, which has get_* numeric getters.
rpc.exports.invDeep=function(invAddr){var h=H_();var inv=ptr(invAddr);
 var icls=h.cFN(img("holo-game.dll"),Memory.allocUtf8String("Niantic.Holoholo.Collections"),Memory.allocUtf8String("InventoryCache"));
 var m=h.cMN(icls,Memory.allocUtf8String("GetCurrentItems"),0);if(!m||m.isNull())return {err:"no GetCurrentItems"};
 var coll=mInv(m,inv);if(!coll||coll.isNull())return {err:"null coll"};
 var dict=coll.add(0x10).readPointer();if(dict.isNull())return {err:"null dict"};
 var entries=dict.add(0x18).readPointer();if(entries.isNull())return {err:"null entries"};
 var count=entries.add(0x18).readS32();var out=[];
 // collect one sample value object per case 4,5,6 and also try named getters on the holder
 var wantCases={4:1,5:1,6:1};var seen={};
 for(var i=0;i<count;i++){var e=entries.add(0x20).add(i*0x18);var hash=e.add(0x0).readS32();if(hash<0)continue;
  var key=e.add(0x8).readPointer();var val=e.add(0x10).readPointer();if(key.isNull()||val.isNull())continue;
  var kcase=key.add(0x18).readS32();if(!wantCases[kcase]||seen[kcase])continue;seen[kcase]=1;
  var rec={kcase:kcase,holderCls:cname(val),inner:{}};
  // try a bunch of holder getters that would return the inner proto
  ["get_PlayerCurrency","get_PlayerStats","get_Currency","get_Stardust","get_InventoryItemData"].forEach(function(gn){
    try{var gm=h.cMN(h.OGC(val),Memory.allocUtf8String(gn),0);if(!gm||gm.isNull())return;var pr=mInv(gm,val);if(!pr||pr.isNull())return;
      rec.inner[gn]={cls:cname(pr)};
      // dump candidate ints of inner proto
      var raw={};[0x10,0x14,0x18,0x1c,0x20,0x24,0x28,0x2c,0x30].forEach(function(o){try{raw["i32@"+o.toString(16)]=pr.add(o).readS32();}catch(e){}});rec.inner[gn].raw=raw;
    }catch(e){}});
  // also raw dump the holder itself
  var hraw={};[0x10,0x14,0x18,0x1c,0x20].forEach(function(o){try{hraw["i32@"+o.toString(16)]=val.add(o).readS32();}catch(e){}});rec.holderRaw=hraw;
  out.push(rec);}
 return {count:count, samples:out};};
"""


def main():
    sess, pid = pg.get_session()
    print("attached pid", pid)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        # IapService all instances, i32+i64
        print("\n==== IapService instances (i32+i64) ====")
        ns = sc.exports_sync.ns_of("IapService")
        r = finder.exports_sync.find_singleton(ns, "IapService") if ns else {}
        for h in (r.get("hits", []) if isinstance(r, dict) else []):
            if sc.exports_sync.cls_name(h) != "IapService":
                print(f"   {h}: not IapService ({sc.exports_sync.cls_name(h)})"); continue
            sd = sc.exports_sync.read_num(h, "get_Stardusts")
            co = sc.exports_sync.read_num(h, "get_Coins")
            print(f"   {h}: Stardusts={sd} Coins={co}")

        # IapService numeric getters list (to find any other stardust-ish getter)
        print("\n==== IapService 0-arg numeric getters ====")
        g = sc.exports_sync.num_getters(ns, "IapService")
        for x in (g.get("getters", []) if isinstance(g, dict) else []):
            print("   ", x)

        # InventoryCache deep
        print("\n==== InventoryCache deep (case 4/5/6 holders + inner proto) ====")
        ic_r = finder.exports_sync.find_singleton("Niantic.Holoholo.Collections", "InventoryCache")
        for h in (ic_r.get("hits", []) if isinstance(ic_r, dict) else []):
            res = sc.exports_sync.inv_deep(h)
            if isinstance(res, dict) and res.get("err"):
                print(f"   {h}: ERR {res['err']}"); continue
            print(f"   {h}: entries={res.get('count')}")
            for rec in res.get("samples", []):
                print(f"      case{rec['kcase']} holder={rec['holderCls']} holderRaw={rec.get('holderRaw')}")
                for gn, info in rec.get("inner", {}).items():
                    print(f"          {gn}: cls={info.get('cls')} raw={info.get('raw')}")

        # ClientInventoryItem fields (to map the currency holder)
        print("\n==== ClientInventoryItem fields ====")
        f = sc.exports_sync.fields("Niantic.Holoholo.Collections", "ClientInventoryItem")
        if isinstance(f, dict) and f.get("fields"):
            for fld in f["fields"]:
                print(f"   {fld['name']} @{hex(fld['off'])} : {fld['type']}")
        else:
            print("   ", f)
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

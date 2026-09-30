"""GROUND-TRUTH pass 3. READ-ONLY. Pin the SERVER-AUTHORITATIVE stardust.
- Dump ClientInventoryItem (holo-game.dll) getters so we find the currency accessor.
- For every InventoryCache entry, call get_* that returns a proto, find the one whose class
  name contains 'Currency' or 'PlayerCurrency', read its amount.
- Also: confirm account identity via PlayerProfile/Player level + box count.
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
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),cFN:b("il2cpp_class_from_name","pointer",["pointer","pointer","pointer"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function mInv(m,obj){var h=H_();var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r=h.rI(m,obj,ptr(0),exc);if(!exc.readPointer().isNull())return null;return r;}
function cname(o){try{return H_().CGN(H_().OGC(ptr(o))).readCString();}catch(e){return null;}}
function read32(inst,name){var h=H_();var m=h.cMN(h.OGC(ptr(inst)),Memory.allocUtf8String(name),0);if(!m||m.isNull())return null;var r=mInv(m,ptr(inst));if(!r)return null;try{return r.add(0x10).readS32();}catch(e){return null;}}

rpc.exports.clsName=function(inst){return cname(inst);};
rpc.exports.read32=function(inst,name){return read32(inst,name);};
rpc.exports.readNum=function(inst,name){var h=H_();var m=h.cMN(h.OGC(ptr(inst)),Memory.allocUtf8String(name),0);if(!m||m.isNull())return null;var r=mInv(m,ptr(inst));if(!r)return null;try{return {i32:r.add(0x10).readS32(), i64:r.add(0x10).readS64().toString()};}catch(e){return null;}};
rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};

// list 0-arg getters of the class OF a given instance (so we map ClientInventoryItem live)
rpc.exports.gettersOfInst=function(inst){var h=H_();var k=h.OGC(ptr(inst));var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;var out=[];while((m=h.cGM(k,it))&&!m.isNull()){try{if(h.mGPC(m)!==0)continue;var nm=h.mGN(m).readCString();var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push(nm+" -> "+rt);}catch(e){}}return out;};

// Walk InventoryCache. For each entry holder, call any get_* returning a ref type; if the
// returned proto's class name matches /Currency/i, read candidate ints + a get_Amount/get_Stardust.
rpc.exports.findCurrency=function(invAddr){var h=H_();var inv=ptr(invAddr);
 var icls=h.cFN(img("holo-game.dll"),Memory.allocUtf8String("Niantic.Holoholo.Collections"),Memory.allocUtf8String("InventoryCache"));
 var m=h.cMN(icls,Memory.allocUtf8String("GetCurrentItems"),0);if(!m||m.isNull())return {err:"no GetCurrentItems"};
 var coll=mInv(m,inv);if(!coll||coll.isNull())return {err:"null coll"};
 var dict=coll.add(0x10).readPointer();if(dict.isNull())return {err:"null dict"};
 var entries=dict.add(0x18).readPointer();if(entries.isNull())return {err:"null entries"};
 var count=entries.add(0x18).readS32();var found=[];
 // discover holder getters that return a proto, once
 var holderGetters=null;
 for(var i=0;i<count;i++){var e=entries.add(0x20).add(i*0x18);var hash=e.add(0x0).readS32();if(hash<0)continue;
  var key=e.add(0x8).readPointer();var val=e.add(0x10).readPointer();if(key.isNull()||val.isNull())continue;
  if(holderGetters===null){holderGetters=[];var k=h.OGC(val);var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var mm;
    while((mm=h.cGM(k,it))&&!mm.isNull()){try{if(h.mGPC(mm)!==0)continue;var nm=h.mGN(mm).readCString();if(nm.indexOf("get_")!==0)continue;var rt="?";try{rt=h.tGN(h.mGRT(mm)).readCString();}catch(e){}
      // only ref-type getters (skip primitives/strings/bools)
      if(rt.indexOf("Int")<0&&rt.indexOf("Bool")<0&&rt.indexOf("String")<0&&rt.indexOf("Single")<0&&rt.indexOf("Enum")<0){holderGetters.push(nm);}}catch(e){}}}
  // call each holder getter; if result class matches Currency, capture
  for(var gi=0;gi<holderGetters.length;gi++){var gn=holderGetters[gi];try{var gm=h.cMN(h.OGC(val),Memory.allocUtf8String(gn),0);if(!gm||gm.isNull())continue;var pr=mInv(gm,val);if(!pr||pr.isNull())continue;var cn=cname(pr);if(!cn)continue;
    if(/Currenc|Stardust|PlayerWallet|Wallet/i.test(cn)){var raw={};[0x10,0x14,0x18,0x1c,0x20,0x24].forEach(function(o){try{raw["i32@"+o.toString(16)]=pr.add(o).readS32();}catch(e){}});
      var amt=read32(pr,"get_Amount");var sd=read32(pr,"get_Stardust");var q=read32(pr,"get_Quantity");
      found.push({holder:cname(val),getter:gn,proto:cn,raw:raw,get_Amount:amt,get_Stardust:sd,get_Quantity:q});}
  }catch(e){}}
  if(found.length>=6)break;
 }
 return {count:count, holderGetters:holderGetters, found:found};};
"""


def main():
    sess, pid = pg.get_session()
    print("attached pid", pid)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        # account identity: player level + box (sanity that 47k instance is THIS account)
        print("==== Account identity ====")
        for cls, getters in [
            ("PlayerProfileWatcher", ["get_Level", "get_Experience"]),
            ("PlayerMetadataProxy", ["get_Level"]),
            ("PokemonBagImpl", ["get_PokemonOnlyCount"]),
        ]:
            ns = sc.exports_sync.ns_of(cls)
            if not ns:
                print(f"   {cls}: ns not found"); continue
            r = finder.exports_sync.find_singleton(ns, cls)
            for h in (r.get("hits", []) if isinstance(r, dict) else [])[:3]:
                if sc.exports_sync.cls_name(h) != cls:
                    continue
                vals = {g: sc.exports_sync.read32(h, g) for g in getters}
                print(f"   {cls} @{h}: {vals}")
                break

        print("\n==== InventoryCache currency hunt ====")
        ic_r = finder.exports_sync.find_singleton("Niantic.Holoholo.Collections", "InventoryCache")
        for h in (ic_r.get("hits", []) if isinstance(ic_r, dict) else []):
            res = sc.exports_sync.find_currency(h)
            if isinstance(res, dict) and res.get("err"):
                print(f"   {h}: ERR {res['err']}"); continue
            print(f"   {h}: entries={res.get('count')}")
            print(f"      holder ref-getters: {res.get('holderGetters')}")
            for fr in res.get("found", []):
                print(f"      CURRENCY via {fr['getter']} -> {fr['proto']}: Amount={fr['get_Amount']} Stardust={fr['get_Stardust']} Qty={fr['get_Quantity']} raw={fr['raw']}")
            if not res.get("found"):
                print("      (no Currency-named proto surfaced from holder ref-getters)")
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

"""GROUND-TRUTH stardust audit. READ-ONLY. Runs alongside the catcher.

1. Enumerate EVERY IapService instance + its get_Stardusts / get_Coins (not just max).
2. Read InventoryCache PlayerCurrency (oneof case 5) + PlayerStats (case 4) -- the
   server-synced authoritative bag dictionary -- and pull the stardust currency value.
3. Hunt holo-game.dll for any PlayerProfile/Player/PlayerData/Inventory/CurrencyService
   class with a 0-arg int 'stardust'/'currency'-ish getter and read it on its live instance.
Touches nothing. One attach.
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
function read32(inst,name){var h=H_();var m=h.cMN(h.OGC(ptr(inst)),Memory.allocUtf8String(name),0);if(!m||m.isNull())return null;var r=mInv(m,ptr(inst));if(!r)return null;try{return r.add(0x10).readS32();}catch(e){return null;}}

rpc.exports.nsOf=function(cls){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return h.CGNS(k).readCString();}catch(e){}}return null;};
rpc.exports.clsName=function(inst){try{return H_().CGN(H_().OGC(ptr(inst))).readCString();}catch(e){return null;}};
rpc.exports.read32=function(inst,name){return read32(inst,name);};
// read both i32 and i64 (some currency fields are long)
rpc.exports.readNum=function(inst,name){var h=H_();var m=h.cMN(h.OGC(ptr(inst)),Memory.allocUtf8String(name),0);if(!m||m.isNull())return null;var r=mInv(m,ptr(inst));if(!r)return null;try{return {i32:r.add(0x10).readS32(), i64:r.add(0x10).readS64().toString()};}catch(e){return null;}};

// Find classes in holo-game.dll whose name matches /rx/ AND that have a 0-arg int getter
// whose name contains one of the wanted substrings. Returns [{cls,ns,getters:[...]}].
rpc.exports.findGetters=function(clsRx, getterSubs){var h=H_();var im=img("holo-game.dll");var cnt=h.iGCC(im);var cre=new RegExp(clsRx,"i");var out=[];
 for(var i=0;i<cnt&&out.length<60;i++){var k=h.iGC(im,i);if(k.isNull())continue;var cn;try{cn=h.CGN(k).readCString();}catch(e){continue;} if(!cre.test(cn))continue;
  var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;var gs=[];
  while((m=h.cGM(k,it))&&!m.isNull()){try{var nm=h.mGN(m).readCString();if(h.mGPC(m)!==0)continue;var lo=nm.toLowerCase();var hit=false;for(var s=0;s<getterSubs.length;s++){if(lo.indexOf(getterSubs[s])>=0){hit=true;break;}}if(!hit)continue;var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}if(rt.indexOf("Int")>=0||rt.indexOf("Long")>=0||rt.indexOf("Single")>=0){gs.push(nm+" -> "+rt);}}catch(e){}}
  if(gs.length){out.push({cls:cn, ns:(h.CGNS(k).readCString()||""), getters:gs});}}
 return out;};

// InventoryCache currency: walk the dict, find oneof case 5 (PlayerCurrency) + case 4 (PlayerStats),
// dump candidate ints so we can read stardust the server-synced way.
rpc.exports.invCurrency=function(invAddr){var h=H_();var inv=ptr(invAddr);
 var icls=h.cFN(img("holo-game.dll"),Memory.allocUtf8String("Niantic.Holoholo.Collections"),Memory.allocUtf8String("InventoryCache"));
 var m=h.cMN(icls,Memory.allocUtf8String("GetCurrentItems"),0);if(!m||m.isNull())return {err:"no GetCurrentItems"};
 var coll=mInv(m,inv);if(!coll||coll.isNull())return {err:"null coll"};
 var dict=coll.add(0x10).readPointer();if(dict.isNull())return {err:"null dict"};
 var entries=dict.add(0x18).readPointer();if(entries.isNull())return {err:"null entries"};
 var count=entries.add(0x18).readS32();var hist={};var cur=[];var stats=[];
 for(var i=0;i<count;i++){var e=entries.add(0x20).add(i*0x18);var hash=e.add(0x0).readS32();if(hash<0)continue;
  var key=e.add(0x8).readPointer();var val=e.add(0x10).readPointer();if(key.isNull()||val.isNull())continue;
  var kcase=key.add(0x18).readS32();hist[kcase]=(hist[kcase]||0)+1;
  if(kcase===5||kcase===4){var rec={kcase:kcase,cls:null,raw:{}};try{rec.cls=h.CGN(h.OGC(val)).readCString();}catch(e){}
   [0x10,0x14,0x18,0x1c,0x20,0x24,0x28].forEach(function(o){try{rec.raw["i32@"+o.toString(16)]=val.add(o).readS32();}catch(e){}});
   try{rec.raw["i64@10"]=val.add(0x10).readS64().toString();}catch(e){}
   if(kcase===5)cur.push(rec);else stats.push(rec);}}
 return {count:count, hist:hist, currency:cur, stats:stats};};
"""


def main():
    sess, pid = pg.get_session()
    print("attached pid", pid)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        # ---- 1. EVERY IapService instance ----
        print("\n==== 1. ALL IapService instances ====")
        ns = sc.exports_sync.ns_of("IapService")
        print("IapService namespace:", ns)
        iap_hits = []
        if ns:
            r = finder.exports_sync.find_singleton(ns, "IapService")
            iap_hits = r.get("hits", []) if isinstance(r, dict) else []
        print(f"liveness hits: {len(iap_hits)} -> {iap_hits}")
        for h in iap_hits:
            cls = sc.exports_sync.cls_name(h)
            dust = sc.exports_sync.read32(h, "get_Stardusts")
            coins = sc.exports_sync.read32(h, "get_Coins")
            print(f"   {h}  cls={cls}  Stardusts={dust}  Coins={coins}")

        # ---- 2. InventoryCache server-synced currency ----
        print("\n==== 2. InventoryCache PlayerCurrency/PlayerStats (server-synced dict) ====")
        ic_r = finder.exports_sync.find_singleton("Niantic.Holoholo.Collections", "InventoryCache")
        ic_hits = ic_r.get("hits", []) if isinstance(ic_r, dict) else []
        print(f"InventoryCache hits: {ic_hits}")
        for h in ic_hits:
            res = sc.exports_sync.inv_currency(h)
            if isinstance(res, dict) and res.get("err"):
                print(f"   {h}: ERR {res['err']}")
                continue
            print(f"   {h}: entries={res.get('count')} caseHist={res.get('hist')}")
            for rec in res.get("currency", []):
                print(f"      [PlayerCurrency case5] cls={rec.get('cls')} raw={rec.get('raw')}")
            for rec in res.get("stats", []):
                print(f"      [PlayerStats case4]    cls={rec.get('cls')} raw={rec.get('raw')}")

        # ---- 3. Hunt PlayerProfile/Player/Inventory/CurrencyService getters ----
        print("\n==== 3. Authoritative stardust getter hunt (holo-game.dll) ====")
        cls_rx = r"Player|Inventory|Currency|Wallet|Account|Trainer"
        subs = ["stardust", "dust", "currency", "stardstamount", "amount"]
        found = sc.exports_sync.find_getters(cls_rx, subs)
        print(f"candidate classes with stardust/currency-ish 0-arg numeric getters: {len(found)}")
        for f in found:
            print(f"\n   CLASS {f['ns']}.{f['cls']}")
            for g in f["getters"]:
                print(f"       getter: {g}")
            # try to read each getter on the live instance(s)
            try:
                rr = finder.exports_sync.find_singleton(f["ns"], f["cls"])
                hh = rr.get("hits", []) if isinstance(rr, dict) else []
            except Exception as e:
                hh = []
                print(f"       (find_singleton err: {e})")
            for inst in hh[:4]:
                if sc.exports_sync.cls_name(inst) != f["cls"]:
                    continue
                for g in f["getters"]:
                    gname = g.split(" ")[0]
                    val = sc.exports_sync.read_num(inst, gname)
                    if val is not None:
                        print(f"       @{inst} {gname} = {val}")
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

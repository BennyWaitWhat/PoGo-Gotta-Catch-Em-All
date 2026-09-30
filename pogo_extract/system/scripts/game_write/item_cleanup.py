"""Item-bag cleanup -- emulates the inventory management lost with Pokemod's paid plan.

WHY: the item bag hit 3684 against a 3650 cap, so PokeStop spins were returning
FortSearchOutProto Result=4 (INVENTORY_FULL) and awarding nothing -- roughly 38% of spins wasted.

SAFETY MODEL
  * DRY-RUN BY DEFAULT. --commit is required to discard anything, and discarding is irreversible.
  * PROTECTED is a hard blocklist re-checked at the moment of each call, not only when the plan
    is built. Golden Razz and Silver Pinap are on it because of a standing instruction ("do not
    touch my golden razz or silver"). Note that Silver Pinap's INTERNAL enum name is
    GoldenPinapBerry -- an easy and expensive thing to confuse with PinapBerry.
  * Only ids listed in KEEP_TO are ever trimmed. The policy is an allowlist of things to trim,
    not a denylist of things to spare, so an item type added by a future update defaults to
    untouched.
  * Balls are trimmed conservatively: they are the catcher's fuel, and running dry silently
    degrades catching, which is worse than a full bag.
"""
import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

# item id -> ceiling to keep. ONLY these ids are ever trimmed.
KEEP_TO = {
    1: 1200,    # PokeBall     -- the catcher's default ball; keep a deep stock
    3: 300,     # UltraBall    -- reserved for the hardest targets
    101: 50,    # Potion
    102: 50,    # SuperPotion
    103: 100,   # HyperPotion
    104: 100,   # MaxPotion
    201: 50,    # Revive
    202: 150,   # MaxRevive
    703: 50,    # NanabBerry
    705: 120,   # PinapBerry
}

# NEVER discarded, whatever the policy says. Re-checked immediately before each call.
PROTECTED = {
    706,                                    # GoldenRazzBerry -- explicit standing instruction
    707, 708,                               # 708 IS GoldenPinapBerry == SILVER PINAP in-game.
                                            # I originally protected only 707, which is the WRONG id.
                                            # It survived purely because KEEP_TO is an allowlist and
                                            # 708 was never in it -- luck, not the guard. Both listed now.
    4,                                      # MasterBall
    301, 302,                               # LuckyEgg, MaxBoost
    401, 406,                               # Incense, Daily Adventure Incense
    501, 502, 503, 504, 505, 506,           # lure modules (TroyDisk*)
    901, 902, 903, 905,                     # incubators
    1301, 1302,                             # RareCandy, XlRareCandy
    1401, 1402, 1404, 1408, 1410, 1411,     # tickets / star piece / currency holders
    1101, 1102, 1103, 1104, 1105, 1106,     # evolution items
    1107, 1150, 1151, 1153, 1154,
    1201, 1202, 1203, 1204, 1250,           # move rerolls (Elite TMs live here)
    1501, 1502, 1503, 1504, 1505, 1506,     # Leader/Giovanni maps, Shadow Gems
    801, 804,                               # SpecialCamera, SoftSfida
    651, 709,                               # Beans, Poffin
}

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};
 il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),
    cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),
    OGC:b("il2cpp_object_get_class","pointer",["pointer"]),
    cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),
    mGN:b("il2cpp_method_get_name","pointer",["pointer"]),
    mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),
    mGPT:b("il2cpp_method_get_param","pointer",["pointer","uint32"]),
    mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),
    tGN:b("il2cpp_type_get_name","pointer",["pointer"]),
    dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),
    aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),
    iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),
    iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),
    CGN:b("il2cpp_class_get_name","pointer",["pointer"]),
    iGN:b("il2cpp_image_get_name","pointer",["pointer"]),
    oN:b("il2cpp_object_new","pointer",["pointer"]),
    cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),
    fGN:b("il2cpp_field_get_name","pointer",["pointer"]),
    fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),
    rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),
    tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
rpc.exports.count=function(ibStr,item){var h=H_();var ib=ptr(ibStr);
 var m=h.cMN(h.OGC(ib),Memory.allocUtf8String("GetItemCount"),1);if(!m||m.isNull())return -1;
 var arg=Memory.alloc(4);arg.writeS32(item);
 var args=Memory.alloc(Process.pointerSize);args.writePointer(arg);
 var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));
 var ret=h.rI(m,ib,args,exc);if(!exc.readPointer().isNull())return -2;if(ret.isNull())return -3;
 try{return ret.add(0x10).readS32();}catch(e){return -4;}};
/* List candidate recycle methods so the caller resolves by NAME+ARITY rather than trusting a
   hardcoded obfuscated symbol, which reshuffles on every game update. Also report each
   parameter's TYPE: the real method turned out to be RecycleItem/3, not /2, and guessing the
   third parameter would have meant invoking a discard with a garbage argument. */
rpc.exports.recycleMethods=function(ibStr){var h=H_();var ib=ptr(ibStr);var k=h.OGC(ib);var out=[];
 var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
 while((m=h.cGM(k,it))&&!m.isNull()){try{var nm=h.mGN(m).readCString();
  if(!/recycle|discard|remove/i.test(nm))continue;
  var pc=h.mGPC(m),ps=[];
  for(var i=0;i<pc;i++){try{ps.push(h.tGN(h.mGPT(m,i)).readCString());}catch(e){ps.push("?");}}
  var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}
  out.push(nm+"("+ps.join(", ")+") -> "+rt);
 }catch(e){}}
 return out;};
/* Find the REAL recycle entry point by RETURN TYPE across every class, the same signature-based
   trick used for the spin method. ItemBagImpl.RecycleItem takes a UI widget's ItemData object as
   its first argument, not an item id -- invoking it with an int would hand the runtime a garbage
   pointer. What we want is whatever sends the RecycleItem RPC with plain (item, count) args. */
rpc.exports.findRecycleRpc=function(){var h=H_();var out=[];
 var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();
 for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());var cnt=h.iGCC(im);
  for(var j=0;j<cnt;j++){var k=h.iGC(im,j);if(k.isNull())continue;
   var cn;try{cn=h.CGN(k).readCString();}catch(e){continue;}
   var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
   while((m=h.cGM(k,it))&&!m.isNull()){try{
     var rt=h.tGN(h.mGRT(m)).readCString();
     if(!rt||rt.indexOf("RecycleItemOutProto")<0)continue;
     var pc=h.mGPC(m),ps=[];
     for(var q=0;q<pc;q++){try{ps.push(h.tGN(h.mGPT(m,q)).readCString());}catch(e){ps.push("?");}}
     if(out.length<25)out.push(cn+"."+h.mGN(m).readCString()+"("+ps.join(", ")+")");
   }catch(e){}}}}
 return out;};
/* THE REAL RECYCLE PATH, taken from Pokemod's MagicBag.itemRecycler:
     const exp = ExpirationData.$new(); exp.ExpireTime = 0;
     const data = ItemData.$new(itemId, 0, 0, count, false, true, false, null, 0, exp);
     ItemBag.RecycleItem(data, discardCount, null)
   ItemBagImpl.RecycleItem's first parameter is a UI widget's ItemData object, NOT an item id --
   passing an int there hands the runtime a garbage pointer. So construct the object exactly as
   Pokemod does. The third argument (ISet<Item>) is simply null. */
function clsAnywhere(nm){
  var imgs=["holo-game.dll","Assembly-CSharp.dll","holo-protos.dll"];
  for(var i=0;i<imgs.length;i++){var g=findClasses(imgs[i],[nm]);if(g[nm])return g[nm];}
  return null;
}
function findClasses(image,names){var h=H_();var out={};var im=img(image);if(!im)return out;
  var want={};for(var i=0;i<names.length;i++)want[names[i]]=1;
  var cnt=h.iGCC(im),left=names.length;
  for(var j=0;j<cnt&&left>0;j++){var k=h.iGC(im,j);if(k.isNull())continue;
    try{var nm=h.CGN(k).readCString();if(want[nm]&&!out[nm]){out[nm]=k;left--;}}catch(e){}}
  return out;}
function img(n){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var c=sp.readS32();
  for(var i=0;i<c;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());
    try{if(h.iGN(im).readCString()===n)return im;}catch(e){}}return null;}
function fieldOff(k,nm){try{var h=H_();var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
  while((f=h.cGF(k,it))&&!f.isNull()){try{if(h.fGN(f).readCString()===nm)return h.fGO(f);}catch(e){}}}catch(e){}return -1;}
function ctorOf(k,argc){var h=H_();if(!k)return null;
  var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
  while((m=h.cGM(k,it))&&!m.isNull()){try{
    if(h.mGN(m).readCString()===".ctor"&&h.mGPC(m)===argc)return m;}catch(e){}}
  return null;}
rpc.exports.recycleReal=function(ibStr,itemId,have,discard){
  try{
    var h=H_();var ib=ptr(ibStr);
    var idCls=clsAnywhere("ItemData"),edCls=clsAnywhere("ExpirationData");
    if(!idCls)return "no ItemData class";
    var ed=ptr(0);
    if(edCls){
      ed=h.oN(edCls);
      var oe=fieldOff(edCls,"ExpireTime");
      if(oe>=0){try{ed.add(oe).writeS64(0);}catch(e){try{ed.add(oe).writeS32(0);}catch(e2){}}}
    }
    var ct=ctorOf(idCls,10);
    if(!ct)return "no ItemData .ctor/10";
    var obj=h.oN(idCls);
    function i32(v){var b=Memory.alloc(4);b.writeS32(v);return b;}
    function u8(v){var b=Memory.alloc(1);b.writeU8(v);return b;}
    /* (itemId, 0, 0, count, false, true, false, null, 0, expiration) */
    var args=[i32(itemId),i32(0),i32(0),i32(have),u8(0),u8(1),u8(0),ptr(0),i32(0),ed];
    var ap=Memory.alloc(Process.pointerSize*args.length);
    for(var i=0;i<args.length;i++)ap.add(i*Process.pointerSize).writePointer(args[i]);
    var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));
    h.rI(ct,obj,ap,exc);
    if(!exc.readPointer().isNull())return "ctor threw";
    var rm=h.cMN(h.OGC(ib),Memory.allocUtf8String("RecycleItem"),3);
    if(!rm||rm.isNull())return "no RecycleItem/3";
    var dp=i32(discard);
    var ra=Memory.alloc(Process.pointerSize*3);
    ra.writePointer(obj);
    ra.add(Process.pointerSize).writePointer(dp);
    ra.add(Process.pointerSize*2).writePointer(ptr(0));   /* ISet<Item> == null, as Pokemod passes */
    var exc2=Memory.alloc(Process.pointerSize);exc2.writePointer(ptr(0));
    h.rI(rm,ib,ra,exc2);
    if(!exc2.readPointer().isNull())return "RecycleItem threw";
    return "ok";
  }catch(e){return "err:"+String(e).substr(0,90);}
};
rpc.exports.recycle=function(ibStr,meth,arity,item,n){var h=H_();var ib=ptr(ibStr);
 var m=h.cMN(h.OGC(ib),Memory.allocUtf8String(meth),arity);if(!m||m.isNull())return "no-method";
 var a1=Memory.alloc(4);a1.writeS32(item);var a2=Memory.alloc(4);a2.writeS32(n);
 var args=Memory.alloc(Process.pointerSize*arity);
 args.writePointer(a1);args.add(Process.pointerSize).writePointer(a2);
 /* A 3rd parameter is passed as null. If it is a callback/Action the call still completes; if it
    turns out to be a required value this returns "threw" rather than discarding anything. */
 for(var i=2;i<arity;i++)args.add(Process.pointerSize*i).writePointer(ptr(0));
 var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));
 h.rI(m,ib,args,exc);
 if(!exc.readPointer().isNull())return "threw";
 return "ok";};
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="actually discard (IRREVERSIBLE)")
    ap.add_argument("--method", default=None, help="recycle method name resolved from the probe")
    ap.add_argument("--arity", type=int, default=3,
                    help="parameter count of the recycle method (probe reported RecycleItem/3)")
    args = ap.parse_args()

    sess, pid = pg.get_session()
    sc = pg.get_script_with_helpers(sess, JS)
    print("attached", pid)
    try:
        ib = pg.pick_singleton(sess, "Niantic.Holoholo.Internal", "ItemBagImpl")
        print("ItemBagImpl @", ib)
        print("recycle-ish methods on ItemBagImpl:")
        for x in (sc.exports_sync.recycle_methods(ib) or []):
            print("   ", x)
        print("methods returning RecycleItemOutProto (the real RPC path):")
        for x in (sc.exports_sync.find_recycle_rpc() or ["(none found)"]):
            print("   ", x)

        plan, freed = [], 0
        for item, ceiling in sorted(KEEP_TO.items()):
            if item in PROTECTED:
                continue
            have = sc.exports_sync.count(ib, item)
            if not isinstance(have, int) or have <= 0:
                continue
            if have > ceiling:
                n = have - ceiling
                plan.append((item, have, ceiling, n))
                freed += n

        print()
        print(f"{'item':>6} {'have':>6} {'keep':>6} {'discard':>8}")
        print("-" * 31)
        for item, have, ceiling, n in plan:
            print(f"{item:>6} {have:>6} {ceiling:>6} {n:>8}")
        print("-" * 31)
        print(f"would free: {freed}")

        if not args.commit:
            print()
            print("DRY RUN -- nothing discarded. Re-run with --commit --method <name> to apply.")
            return
        for item, have, ceiling, n in plan:
            if item in PROTECTED:   # re-checked at call time, not just when planning
                print(f"  SKIP protected {item}")
                continue
            r = sc.exports_sync.recycle_real(ib, item, have, n)
            after = sc.exports_sync.count(ib, item)
            print(f"  item {item}: discard {n} -> {r}; now {after}")
    finally:
        try:
            sc.unload()
            sess.detach()
        except Exception:
            pass


main()

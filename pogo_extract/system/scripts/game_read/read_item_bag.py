"""READ-ONLY item bag dump: every item id, its enum name, and how many you hold.

Built because spins started returning FortSearchOutProto Result=4 (INVENTORY_FULL) -- the item
bag is full, so ~38% of PokeStop spins award nothing. Any cleanup policy has to be based on the
real bag, not on assumptions about what is in it.

Nothing here writes: it calls GetItemCount(itemId) only. The enum names come from the live
ItemId enum (same field-enumeration trick used for the Form enum) so they cannot drift with a
game update the way a hardcoded table would.
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};
 il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dG:b("il2cpp_domain_get","pointer",[]),dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),
    aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),
    iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),
    CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),
    cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),
    fGSV:b("il2cpp_field_static_get_value","void",["pointer","pointer"]),
    cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),
    OGC:b("il2cpp_object_get_class","pointer",["pointer"]),
    rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),
    tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function eachClass(cb){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();
 for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());var cnt=h.iGCC(im);
  for(var j=0;j<cnt;j++){var k=h.iGC(im,j);if(!k.isNull())cb(k);}}}

/* the ItemId enum: name -> int, read live so a game update cannot silently rename things */
rpc.exports.itemEnum=function(){var h=H_();var out={};
 eachClass(function(k){var nm;try{nm=h.CGN(k).readCString();}catch(e){return;}
  if(nm!=="Item"&&nm!=="ItemId")return;
  var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
  while((f=h.cGF(k,it))&&!f.isNull()){try{
    var fn=h.fGN(f).readCString(); if(fn==="value__")continue;
    var buf=Memory.alloc(8);buf.writeU64(0);h.fGSV(f,buf);out[fn]=buf.readS32();
  }catch(e){}}});
 return out;};
rpc.exports.count=function(ibStr,item){var h=H_();var ib=ptr(ibStr);
 var m=h.cMN(h.OGC(ib),Memory.allocUtf8String("GetItemCount"),1);if(!m||m.isNull())return -1;
 var arg=Memory.alloc(4);arg.writeS32(item);var args=Memory.alloc(Process.pointerSize);args.writePointer(arg);
 var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));
 var ret=h.rI(m,ib,args,exc);if(!exc.readPointer().isNull())return -2;if(ret.isNull())return -3;
 try{return ret.add(0x10).readS32();}catch(e){return -4;}};
rpc.exports.findItemBag=function(){var h=H_();var hits=[];
 eachClass(function(k){try{var nm=h.CGN(k).readCString();if(/^I[A-Z]/.test(nm))return;
  var m=h.cMN(k,Memory.allocUtf8String("GetItemCount"),1);if(m&&!m.isNull())hits.push(nm);}catch(e){}});
 return hits;};
"""


def main():
    sess, pid = pg.get_session()
    sc = pg.get_script_with_helpers(sess, JS)   # already loaded by the helper
    print("attached", pid, flush=True)
    try:
        ib = pg.pick_singleton(sess, "Niantic.Holoholo.Internal", "ItemBagImpl")
        print("ItemBagImpl @", ib)
        enum = sc.exports_sync.item_enum() or {}
        print(f"ItemId enum entries: {len(enum)}")
        byval = {}
        for name, val in enum.items():
            byval.setdefault(int(val), name)
        ids = sorted(byval) if byval else list(range(0, 2500))
        rows = []
        for i in ids:
            n = sc.exports_sync.count(ib, i)
            if isinstance(n, int) and n > 0:
                rows.append((i, byval.get(i, f"item_{i}"), n))
        total = sum(r[2] for r in rows)
        print(f"\n{'id':>6}  {'name':<34} {'count':>6}")
        print("-" * 50)
        for i, nm, n in sorted(rows, key=lambda r: -r[2]):
            print(f"{i:>6}  {nm:<34} {n:>6}")
        print("-" * 50)
        print(f"{'TOTAL':>42} {total:>6}")
    finally:
        try:
            sc.unload(); sess.detach()
        except Exception:
            pass


main()

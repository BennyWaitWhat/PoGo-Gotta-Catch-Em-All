"""RECON (READ-ONLY): dump the field layout of the PokeStop spin RESPONSE so we can read
the ACTUAL items + XP the server awards (immune to Pokemod's inventory management).
Targets FortSearchOutProto and the loot/award payload classes. Pure metadata read."""
import sys, os
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
    aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),
    iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),
    CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),
    cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),
    fGT:b("il2cpp_field_get_type","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),
    tGN:b("il2cpp_type_get_name","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();
 for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}
function findClass(cls){var h=H_();var imgs=["holo-protos.dll","holo-game.dll"];
 for(var ii=0;ii<imgs.length;ii++){var im=img(imgs[ii]);if(!im)continue;var cnt=h.iGCC(im);
  for(var i=0;i<cnt;i++){var k=h.iGC(im,i);if(k.isNull())continue;try{if(h.CGN(k).readCString()===cls)return k;}catch(e){}}}return null;}
rpc.exports.fields=function(name){var h=H_();var k=findClass(name);if(!k)return null;var out=[];
 var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
 while((f=h.cGF(k,it))&&!f.isNull()&&out.length<60){try{var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}
  out.push("+0x"+h.fGO(f).toString(16)+"  "+h.fGN(f).readCString()+" : "+tn);}catch(e){}}return out;};
rpc.exports.listClasses=function(rx){var h=H_();var re=new RegExp(rx,"i");var out=[];var imgs=["holo-protos.dll"];
 for(var ii=0;ii<imgs.length;ii++){var im=img(imgs[ii]);if(!im)continue;var cnt=h.iGCC(im);
  for(var i=0;i<cnt&&out.length<60;i++){var k=h.iGC(im,i);if(k.isNull())continue;
   try{var nm=h.CGN(k).readCString();if(re.test(nm))out.push(nm);}catch(e){}}}return out;};
"""


def main():
    sess, pid = pg.get_session()
    sc = sess.create_script(JS); sc.load()
    print("attached", pid, flush=True)
    try:
        for cls in ["FortSearchOutProto", "LootProto", "LootItemProto", "ItemAward", "InventoryItemProto"]:
            print(f"\n=== {cls} fields ===")
            for x in (sc.exports_sync.fields(cls) or ["(class not found)"]):
                print("  ", x)
        print("\n=== Loot/Award classes available ===")
        for c in sorted(set(sc.exports_sync.list_classes("Loot|Award") or [])):
            print("  ", c)
    finally:
        try:
            sc.unload(); sess.detach()
        except Exception:
            pass


main()

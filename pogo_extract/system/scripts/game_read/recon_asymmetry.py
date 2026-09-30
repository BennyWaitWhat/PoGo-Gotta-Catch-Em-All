"""RECON (READ-ONLY): triple-check the catch-vs-spin asymmetry at the proto schema level,
live from libil2cpp metadata (not from any cached file). Dumps the field list of the
request+response protos for BOTH the catch path and the spin path, so we can see directly
whether a player coordinate is present (and therefore range-checkable) on each.
Pure schema read. No hooks on live data, no writes."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so"); var e={};
 il.enumerateExports().forEach(function(x){ if(x.name.indexOf("il2cpp_")===0) e[x.name]=x.address; });
 function b(n,r,a){ return e[n]? new NativeFunction(e[n],r,a): null; }
 H={ dG:b("il2cpp_domain_get","pointer",[]), dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),
     aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]), iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),
     iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]), CGN:b("il2cpp_class_get_name","pointer",["pointer"]),
     cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]), fGN:b("il2cpp_field_get_name","pointer",["pointer"]), fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),
     tA:b("il2cpp_thread_attach","pointer",["pointer"]) };
 H.tA(H.dG()); return H; }
function eachClass(cb){ var h=H_(); var sp=Memory.alloc(4); var a=h.dGA(h.dG(),sp); var n=sp.readS32();
 for(var i=0;i<n;i++){ var im=h.aGI(a.add(i*Process.pointerSize).readPointer()); var cnt=h.iGCC(im);
   for(var j=0;j<cnt;j++){ var k=h.iGC(im,j); if(!k.isNull()) cb(k); } } }
function findClass(name){ var h=H_(); var f=null; eachClass(function(k){ if(f)return; try{ if(h.CGN(k).readCString()===name) f=k; }catch(e){} }); return f; }
function fieldsList(k){ var h=H_(); var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=h.cGF(k,it))&&!f.isNull()){ try{ out.push(h.fGN(f).readCString()+" @0x"+h.fGO(f).toString(16)); }catch(e){} } return out; }
rpc.exports.fields=function(clsName){ var k=findClass(clsName); if(!k) return null; return fieldsList(k); };
"""


def main():
    sess, pid = pg.get_session()
    sc = sess.create_script(JS); sc.load()
    print(f"attached {pid}\n")
    targets = [
        ("SPIN request", "FortSearchProto"),
        ("SPIN response", "FortSearchOutProto"),
        ("CATCH request", "CatchPokemonProto"),
        ("CATCH response", "CatchPokemonOutProto"),
        ("ENCOUNTER request", "EncounterProto"),
        ("ENCOUNTER response", "EncounterOutProto"),
    ]
    coord_terms = ("lat", "lng", "longitude", "latitude")
    for label, cls in targets:
        fl = sc.exports_sync.fields(cls)
        if fl is None:
            print(f"### {label}: {cls}  -> [class not found]\n")
            continue
        coords = [f for f in fl if any(t in f.lower() for t in coord_terms)]
        print(f"### {label}: {cls}   ({len(fl)} fields)")
        for f in fl:
            mark = "  <== COORDINATE" if any(t in f.lower() for t in coord_terms) else ""
            print(f"      {f}{mark}")
        print(f"   >> player/fort COORDINATE fields: {coords if coords else 'NONE'}\n")
    sc.unload(); sess.detach()


main()

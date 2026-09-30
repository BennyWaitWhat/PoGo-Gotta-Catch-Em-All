"""RECON (READ-ONLY): read the ACTUAL enum constant names+values out of this client's
libil2cpp metadata (ground truth), instead of trusting the published POGOProtos numbering.
Resolves a proto field -> its enum type -> every literal constant (name = value).
Pure metadata read."""
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
     cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]), fGN:b("il2cpp_field_get_name","pointer",["pointer"]),
     fGT:b("il2cpp_field_get_type","pointer",["pointer"]), cFT:b("il2cpp_class_from_type","pointer",["pointer"]),
     fSGV:b("il2cpp_field_static_get_value","void",["pointer","pointer"]),
     fGFL:b("il2cpp_field_get_flags","uint32",["pointer"]), tA:b("il2cpp_thread_attach","pointer",["pointer"]) };
 H.tA(H.dG()); return H; }
function eachClass(cb){ var h=H_(); var sp=Memory.alloc(4); var a=h.dGA(h.dG(),sp); var n=sp.readS32();
 for(var i=0;i<n;i++){ var im=h.aGI(a.add(i*Process.pointerSize).readPointer()); var cnt=h.iGCC(im);
   for(var j=0;j<cnt;j++){ var k=h.iGC(im,j); if(!k.isNull()) cb(k); } } }
function findClass(name){ var h=H_(); var f=null; eachClass(function(k){ if(f)return; try{ if(h.CGN(k).readCString()===name) f=k; }catch(e){} }); return f; }

// resolve PROTO.FIELD -> enum class, then dump every literal constant (name = int value)
rpc.exports.enumvals=function(protoName, fieldName){ var h=H_(); var k=findClass(protoName); if(!k) return ["[no proto] "+protoName];
  var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f; var target=null;
  while((f=h.cGF(k,it))&&!f.isNull()){ try{ if(h.fGN(f).readCString()===fieldName){ target=f; break; } }catch(e){} }
  if(!target) return ["[no field] "+protoName+"."+fieldName];
  var ek=h.cFT(h.fGT(target));
  var out=["ENUM "+protoName+"."+fieldName+"  ("+h.CGN(ek).readCString()+"):"];
  var it2=Memory.alloc(Process.pointerSize); it2.writePointer(ptr(0)); var ef; var buf=Memory.alloc(8);
  while((ef=h.cGF(ek,it2))&&!ef.isNull()){ try{ var nm=h.fGN(ef).readCString(); var fl=h.fGFL(ef);
    if(nm==="value__" || (fl & 0x10)===0) continue;   // skip backing field + non-static
    buf.writeU64(0); var val="?";
    try{ h.fSGV(ef, buf); val=buf.readS32(); }catch(e){ val="(unreadable)"; }
    out.push("    "+val+"  =  "+nm);
  }catch(e){} }
  return out; };
"""


def main():
    sess, pid = pg.get_session()
    sc = sess.create_script(JS); sc.load()
    print(f"attached {pid}\n")
    for proto, field in [("FortSearchOutProto", "Result"),
                         ("CatchPokemonOutProto", "Status"),
                         ("EncounterOutProto", "Status")]:
        for line in sc.exports_sync.enumvals(proto, field):
            print(line)
        print()
    sc.unload(); sess.detach()


main()

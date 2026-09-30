"""RECON (READ-ONLY): what we need to auto-transfer 1-24% IV safely.
Needs: PokemonProto IV + keep-axis fields (shiny/costume/form/size/favorite/moves),
and the RELEASE/TRANSFER call. Reads metadata only; releases nothing."""
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
    CGN:b("il2cpp_class_get_name","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),
    fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),
    fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),
    mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),
    mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),
    tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function eachClass(cb){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();
 for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());var cnt=h.iGCC(im);
  for(var j=0;j<cnt;j++){var k=h.iGC(im,j);if(!k.isNull())cb(k,h.iGN(im).readCString());}}}
function findClass(nm){var h=H_();var f=null;eachClass(function(k){if(f)return;try{if(h.CGN(k).readCString()===nm)f=k;}catch(e){}});return f;}
rpc.exports.fields=function(nm){var h=H_();var k=findClass(nm);if(!k)return null;var out=[];
 var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
 while((f=h.cGF(k,it))&&!f.isNull()&&out.length<70){try{var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}
  out.push("+0x"+h.fGO(f).toString(16)+"  "+h.fGN(f).readCString()+" : "+tn);}catch(e){}}return out;};
rpc.exports.methodsLike=function(rx){var h=H_();var re=new RegExp(rx,"i");var out=[];
 eachClass(function(k){var cn;try{cn=h.CGN(k).readCString();}catch(e){return;}
  var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
  while((m=h.cGM(k,it))&&!m.isNull()){try{var mn=h.mGN(m).readCString();
   if(re.test(mn)&&out.length<45)out.push(cn+"::"+mn+"("+h.mGPC(m)+")");}catch(e){}}});return out;};
"""

def main():
    sess, pid = pg.get_session()
    sc = sess.create_script(JS); sc.load()
    print("attached", pid, flush=True)
    try:
        print("\n=== PokemonProto fields (IVs + keep axes) ===")
        for x in (sc.exports_sync.fields("PokemonProto") or ["(not found)"]):
            if any(t in x.lower() for t in ("individual","cp","move","favorite","size","weight","height",
                                            "display","form","costume","lucky","shadow","buddy","deploy",
                                            "id ","pokemonid","captured","creation")):
                print("   ", x)
        print("\n=== RELEASE / TRANSFER methods ===")
        for x in (sc.exports_sync.methods_like("ReleasePokemon|TransferPokemon|^Release$") or ["(none)"]):
            print("   ", x)
    finally:
        try: sc.unload(); sess.detach()
        except Exception: pass
main()

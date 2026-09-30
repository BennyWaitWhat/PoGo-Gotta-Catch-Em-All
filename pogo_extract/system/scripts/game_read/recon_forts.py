"""RECON (READ-ONLY): what does the SERVER actually serve at the current position?
Hooks the map RPC responses (GetMapObjects / GetMapForts) and reads how many forts
vs pokemon come back, and the fort positions/ids -- to test whether the stops you
tap even exist server-side at your spot (a spin-specific desync) vs a cooldown."""
import sys, os, time
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
     cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]), mGN:b("il2cpp_method_get_name","pointer",["pointer"]),
     tA:b("il2cpp_thread_attach","pointer",["pointer"]) };
 H.tA(H.dG()); return H; }
function eachClass(cb){ var h=H_(); var sp=Memory.alloc(4); var a=h.dGA(h.dG(),sp); var n=sp.readS32();
 for(var i=0;i<n;i++){ var im=h.aGI(a.add(i*Process.pointerSize).readPointer()); var cnt=h.iGCC(im);
   for(var j=0;j<cnt;j++){ var k=h.iGC(im,j); if(!k.isNull()) cb(k); } } }
function findClass(name){ var h=H_(); var f=null; eachClass(function(k){ if(f)return; try{ if(h.CGN(k).readCString()===name) f=k; }catch(e){} }); return f; }
function fieldsOf(k){ var h=H_(); var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f; while((f=h.cGF(k,it))&&!f.isNull()){ try{ out.push(h.fGN(f).readCString()+"@0x"+h.fGO(f).toString(16)); }catch(e){} } return out; }

var LOG=[]; function L(s){ LOG.push(s); }
rpc.exports.drain=function(){ var o=LOG; LOG=[]; return o; };
rpc.exports.dump=function(cls){ var k=findClass(cls); if(!k)return null; return fieldsOf(k); };

function repCount(self, off){ try{ var rf=self.add(off).readPointer(); if(rf.isNull())return -1; return rf.add(0x18).readS32(); }catch(e){ return -2; } }

function hookMerge(cls, label, cb){ var h=H_(); var k=findClass(cls); if(!k){ L("[no] "+cls); return; }
 var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var m; var hk=0;
 while((m=h.cGM(k,it))&&!m.isNull()){ try{ if(h.mGN(m).readCString()!=="MergeFrom")continue; var code=m.readPointer(); if(!code||code.isNull())continue;
   Interceptor.attach(code,{ onEnter:function(a){ this.s=a[0]; }, onLeave:function(){ try{ if(this.s&&!this.s.isNull()) cb(this.s); }catch(e){} } }); hk++; }catch(e){} }
 L("[hooked "+hk+"] "+cls); }

rpc.exports.install=function(){ H_();
 // GetMapForts: read Forts repeated-field count if present
 hookMerge("GetMapFortsOutProto","GMF", function(self){
   var k=H_(); var fk=findClass("GetMapFortsOutProto"); var fl=fieldsOf(fk);
   // find a field that is a repeated (object) -- try every ptr field's count
   var parts=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
   var H2=H_(); var i2=Memory.alloc(Process.pointerSize); i2.writePointer(ptr(0)); var ff;
   while((ff=H2.cGF(fk,i2))&&!ff.isNull()){ try{ var nm=H2.fGN(ff).readCString(); var o=H2.fGO(ff); var c=repCount(self,o); if(c>=0&&c<100000) parts.push(nm+"="+c); }catch(e){} }
   L("GetMapForts response repeated-counts: "+parts.join(", "));
 });
 hookMerge("GetMapObjectsOutProto","GMO", function(self){
   var fk=findClass("GetMapObjectsOutProto"); var parts=[]; var H2=H_(); var i2=Memory.alloc(Process.pointerSize); i2.writePointer(ptr(0)); var ff;
   while((ff=H2.cGF(fk,i2))&&!ff.isNull()){ try{ var nm=H2.fGN(ff).readCString(); var o=H2.fGO(ff); var c=repCount(self,o); if(c>=0&&c<100000) parts.push(nm+"="+c); }catch(e){} }
   L("GMO response repeated-counts: "+parts.join(", "));
 });
 return "installed"; };
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    sc = sess.create_script(JS)
    sc.load()
    for cls in ["GetMapFortsOutProto", "GetMapObjectsOutProto", "FortProto", "PokemonFortProto", "FortData"]:
        d = sc.exports_sync.dump(cls)
        print(f"\n=== {cls} fields ===\n  {d}", flush=True)
    print("\ninstall:", sc.exports_sync.install(), flush=True)
    print(">>> watching 60s for map responses (stay where you are; it refreshes periodically) <<<", flush=True)
    t0 = time.time()
    while time.time() - t0 < 60:
        time.sleep(3)
        for line in (sc.exports_sync.drain() or []):
            print("  ", line, flush=True)
    try:
        sc.unload(); sess.detach()
    except Exception:
        pass


main()

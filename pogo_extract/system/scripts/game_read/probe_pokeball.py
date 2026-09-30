"""READ-ONLY probe of Niantic.Holoholo.Encounter.Pokeball.

Pokemod's Headshot/PerfectedThrow rebinds `HitGround` and `HitKillZone` to a System.Action that
calls SetActive(true) -- that is the hook that recovers a ball which lands, and it is the one I have
never implemented. Before building a delegate by hand I need the real shape: are HitGround /
HitKillZone FIELDS or events, what is their declared type, what does Initialize look like, and
where is SetActive declared. Guessing these is what produced four hung encounters.
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
/* Resolve exactly the way Pokemod does: by FULL namespace + class name, via
   il2cpp_class_from_name. The preamble already exposes cFN(ns, cls) for this. Searching by bare
   class name across images was my own invention and is not how their `use(...)` works. */
var EX=null;
rpc.exports.probe=function(){
  _ensureInit();
  var h=IL2;var out={};
  var want=[["Niantic.Holoholo.Encounter","Pokeball"],
            ["Niantic.Holoholo.Encounter","Reticle"],
            ["Niantic.Holoholo.Encounter","EncounterPokemon"]];
  want.forEach(function(pair){
    var ns=pair[0],cn=pair[1];
    var k=null;try{k=cFN(ns,cn);}catch(e){}
    if(!k||k.isNull()){out[cn]={err:"class_from_name failed"};return;}
    var info={ns:ns,fields:[],methods:[]};
    /* Frida 17 has no Module.findExportByName -- the rest of this codebase resolves exports with
       Process.findModuleByName(...).enumerateExports(), so do the same. */
    if(!EX){EX={};Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(x){
      if(x.name.indexOf("il2cpp_")===0)EX[x.name]=x.address;});}
    function nf(n,r,a){return new NativeFunction(EX[n],r,a);}
    var fGet=nf("il2cpp_class_get_fields","pointer",["pointer","pointer"]);
    var fName=nf("il2cpp_field_get_name","pointer",["pointer"]);
    var fType=nf("il2cpp_field_get_type","pointer",["pointer"]);
    var fOff=nf("il2cpp_field_get_offset","uint32",["pointer"]);
    var tName=nf("il2cpp_type_get_name","pointer",["pointer"]);
    var mPC=nf("il2cpp_method_get_param_count","uint32",["pointer"]);
    var mP=nf("il2cpp_method_get_param","pointer",["pointer","uint32"]);
    var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
    while((f=fGet(k,it))&&!f.isNull()){try{
      var tn="";try{tn=tName(fType(f)).readCString();}catch(e){}
      info.fields.push(fName(f).readCString()+"@"+fOff(f)+":"+tn);
    }catch(e){}}
    var it2=Memory.alloc(Process.pointerSize);it2.writePointer(ptr(0));var m;
    while((m=h.cGM(k,it2))&&!m.isNull()){try{
      var mn=h.mGN(m).readCString();
      if(!/Initialize|SetActive|HitGround|HitKillZone|Launch|OnCollision|Invulnerable|NormalizedSize|Bullseye|CanPerform/i.test(mn))continue;
      var pc=mPC(m),ps=[];
      for(var q=0;q<pc;q++){try{ps.push(tName(mP(m,q)).readCString());}catch(e){ps.push("?");}}
      info.methods.push(mn+"("+ps.join(", ")+")");
    }catch(e){}}
    out[cn]=info;
  });
  return out;
};
"""



def main():
    sess, pid = pg.get_session()
    sc = pg.get_script_with_helpers(sess, JS)
    print("attached", pid)
    try:
        r = sc.exports_sync.probe() or {}
        for cls, info in r.items():
            print(f"\n===== {cls}  ns={info.get('ns')}  image={info.get('image')}")
            print("  -- fields --")
            for f in info.get("fields", []):
                print("    ", f)
            print("  -- methods of interest --")
            for m in info.get("methods", []):
                print("    ", m)
    finally:
        try:
            sc.unload(); sess.detach()
        except Exception:
            pass


main()

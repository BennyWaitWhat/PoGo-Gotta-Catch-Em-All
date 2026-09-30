"""RECON (READ-ONLY): reach a LIVE EncounterSettingsProto via the game master.
Route (a): find a live EncounterState (Niantic.Holoholo.Encounter), read field
'dqvp : IGameMasterData' @0x150, introspect that game-master object for a method
or field returning EncounterSettings / global settings, and read the listed
fields. Attaches alongside the running catcher; touches nothing.
"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),dG:b("il2cpp_domain_get","pointer",[]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),iGCC:b("il2cpp_image_get_class_count","uint32",["pointer"]),iGC:b("il2cpp_image_get_class","pointer",["pointer","uint32"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),cGParent:b("il2cpp_class_get_parent","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function img(name){var h=H_();var sp=Memory.alloc(4);var a=h.dGA(h.dG(),sp);var n=sp.readS32();for(var i=0;i<n;i++){var im=h.aGI(a.add(i*Process.pointerSize).readPointer());if(h.iGN(im).readCString()===name)return im;}return null;}

rpc.exports.clsName=function(inst){try{var h=H_();return (h.CGNS(h.OGC(ptr(inst))).readCString()||"")+"."+h.CGN(h.OGC(ptr(inst))).readCString();}catch(e){return null;}};

// All fields of the class of a live instance (walks inheritance chain). [{off,name,type}]
rpc.exports.instFields=function(inst){var h=H_();var out=[];var k=h.OGC(ptr(inst));var guard=0;
 while(k&&!k.isNull()&&guard<8){var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
  while((f=h.cGF(k,it))&&!f.isNull()&&out.length<200){try{var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}out.push({off:h.fGO(f),name:h.fGN(f).readCString(),type:tn});}catch(e){}}
  try{k=h.cGParent(k);}catch(e){break;} guard++;}
 return out;};

// Read a pointer field at byte offset off from instance.
rpc.exports.readPtr=function(inst,off){try{var p=ptr(inst).add(off).readPointer();return p.isNull()?null:p.toString();}catch(e){return ""+e;}};

// Dump methods of the class-of-instance (and its interfaces are not enumerable here,
// so we also accept a class name to dump directly). [{name,argc,ret}]
rpc.exports.dumpMethodsOfInst=function(inst){var h=H_();var k=h.OGC(ptr(inst));var out=[];var guard=0;
 while(k&&!k.isNull()&&guard<6){var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
  while((m=h.cGM(k,it))&&!m.isNull()&&out.length<400){try{var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push({name:h.mGN(m).readCString(),argc:h.mGPC(m),ret:rt});}catch(e){}}
  try{k=h.cGParent(k);}catch(e){break;} guard++;}
 return out;};

// Invoke a 0-arg method by name on inst; return resulting object ptr (or null) + its class.
rpc.exports.invoke0=function(inst,name){var h=H_();var k=h.OGC(ptr(inst));var m=h.cMN(k,Memory.allocUtf8String(name),0);if(!m||m.isNull())return {err:"no method "+name};
 var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var r;try{r=h.rI(m,ptr(inst),ptr(0),exc);}catch(e){return {err:"invoke threw "+e};}
 if(!exc.readPointer().isNull())return {err:"managed exc"};
 if(!r||r.isNull())return {ret:null};
 var cls=null;try{cls=(h.CGNS(h.OGC(r)).readCString()||"")+"."+h.CGN(h.OGC(r)).readCString();}catch(e){}
 return {ret:r.toString(), cls:cls};};

// Read the EncounterSettingsProto fields off a given instance pointer.
rpc.exports.readEncSettings=function(s){var p=ptr(s);try{return {
   GlobalStardustMultiplier:p.add(0x60).readFloat(),
   GlobalCandyMultiplier:p.add(0x64).readFloat(),
   SpinBonusThreshold:p.add(0x10).readFloat(),
   ExcellentThrowThreshold:p.add(0x14).readFloat(),
   GreatThrowThreshold:p.add(0x18).readFloat(),
   NiceThrowThreshold:p.add(0x1c).readFloat(),
   CriticalReticleThreshold:p.add(0x68).readFloat(),
   CriticalReticleCatchMultiplier:p.add(0x6c).readFloat()
 };}catch(e){return {err:""+e};}};
"""

ENC_NS = "Niantic.Holoholo.Encounter"
ENC_CLS = "EncounterState"


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        # 1. Find a live EncounterState
        es = None
        for _ in range(8):
            r = finder.exports_sync.find_singleton(ENC_NS, ENC_CLS)
            if isinstance(r, dict) and r.get("err"):
                print("find_singleton err:", r["err"], flush=True)
                break
            hits = r.get("hits", []) if isinstance(r, dict) else []
            for h in hits:
                cn = sc.exports_sync.cls_name(h)
                if cn and cn.endswith("." + ENC_CLS):
                    es = h
                    break
            if es:
                break
            time.sleep(1.5)
        print(f"\nlive {ENC_CLS}: {es}", flush=True)
        if not es:
            print("NO live EncounterState found.", flush=True)
            return

        # 2. Dump its fields to confirm dqvp @0x150 and find candidate settings holders
        flds = sc.exports_sync.inst_fields(es) or []
        print(f"\n--- {ENC_CLS} fields ({len(flds)}) ---", flush=True)
        for f in flds:
            print(f"   +0x{f['off']:x} {f['name']} : {f['type']}", flush=True)

        # 3. Read the IGameMasterData pointer @0x150 (and confirm what field is there)
        gm = sc.exports_sync.read_ptr(es, 0x150)
        print(f"\nfield @0x150 (expected dqvp:IGameMasterData) = {gm}", flush=True)
        if gm and gm.startswith("0x"):
            gmcls = sc.exports_sync.cls_name(gm)
            print(f"   class of @0x150 obj = {gmcls}", flush=True)
            # Dump the game-master object's methods + fields
            ms = sc.exports_sync.dump_methods_of_inst(gm) or []
            print(f"\n--- game-master obj methods ({len(ms)}) ---", flush=True)
            for m in ms:
                rl = m['ret'].lower()
                tag = "  <== ENC/SETTINGS" if ('encounter' in rl or 'setting' in rl) else ""
                print(f"   {m['name']} ({m['argc']}) -> {m['ret']}{tag}", flush=True)
            gflds = sc.exports_sync.inst_fields(gm) or []
            print(f"\n--- game-master obj fields ({len(gflds)}) ---", flush=True)
            for f in gflds:
                tl = f['type'].lower()
                tag = "  <== ENC/SETTINGS" if ('encounter' in tl or 'setting' in tl) else ""
                print(f"   +0x{f['off']:x} {f['name']} : {f['type']}{tag}", flush=True)
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

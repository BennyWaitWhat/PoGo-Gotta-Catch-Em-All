"""RECON (READ-ONLY) stage 2: from the live GameMasterData, reach EncounterSettingsProto.
- Walk crlp : Dictionary<System.Type, IMessage> @0xd8 (the global proto bag) and report
  every value's class -> locate EncounterSettingsProto and read its fields.
- Also introspect crkt : IGlobalSettings @0x28 for an encounter-settings getter.
Attaches alongside the running catcher; touches nothing.
GM_ADDR is re-resolved each run via EncounterState @0x150 (ptr drifts across processes).
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
 H={dGA:b("il2cpp_domain_get_assemblies","pointer",["pointer","pointer"]),dG:b("il2cpp_domain_get","pointer",[]),aGI:b("il2cpp_assembly_get_image","pointer",["pointer"]),iGN:b("il2cpp_image_get_name","pointer",["pointer"]),CGN:b("il2cpp_class_get_name","pointer",["pointer"]),CGNS:b("il2cpp_class_get_namespace","pointer",["pointer"]),OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cGM:b("il2cpp_class_get_methods","pointer",["pointer","pointer"]),mGN:b("il2cpp_method_get_name","pointer",["pointer"]),mGPC:b("il2cpp_method_get_param_count","uint32",["pointer"]),mGRT:b("il2cpp_method_get_return_type","pointer",["pointer"]),tGN:b("il2cpp_type_get_name","pointer",["pointer"]),cGF:b("il2cpp_class_get_fields","pointer",["pointer","pointer"]),fGN:b("il2cpp_field_get_name","pointer",["pointer"]),fGT:b("il2cpp_field_get_type","pointer",["pointer"]),fGO:b("il2cpp_field_get_offset","uint32",["pointer"]),cGParent:b("il2cpp_class_get_parent","pointer",["pointer"]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}

function cname(o){try{var h=H_();return (h.CGNS(h.OGC(ptr(o))).readCString()||"")+"."+h.CGN(h.OGC(ptr(o))).readCString();}catch(e){return null;}}
rpc.exports.clsName=function(inst){return cname(inst);};
rpc.exports.readPtr=function(inst,off){try{var p=ptr(inst).add(off).readPointer();return p.isNull()?null:p.toString();}catch(e){return ""+e;}};

// Walk a System.Collections.Generic.Dictionary<K,V> object. Standard layout:
//   +0x18 entries[]   +0x20 count(int)   entry stride 0x18: [0]=hashCode(i32) [0x8]=key(ptr) [0x10]=value(ptr) ...
// (key/value order can be [key@0x10,val@0x18] for some; we report both candidates' class.)
// Returns list of {idx, kcls, v10cls, v18cls, v10, v18}.
rpc.exports.walkDict=function(dictAddr){var h=H_();var d=ptr(dictAddr);var out={entries:[]};
 try{
  var entries=d.add(0x18).readPointer();
  var count=d.add(0x20).readS32();
  out.count=count;
  if(entries.isNull()){out.err="null entries";return out;}
  // array data starts at +0x20 (Il2Cpp Array: +0x18 length, +0x20 first element)
  var alen=entries.add(0x18).readS32();
  out.arrlen=alen;
  var base=entries.add(0x20);
  var n=Math.min(count<0?alen:count, alen, 4000);
  for(var i=0;i<n;i++){var e=base.add(i*0x18);var rec={idx:i};
    try{rec.hash=e.add(0x0).readS32();}catch(_){}
    var p8=null,p10=null,p18=null;
    try{p8=e.add(0x8).readPointer();}catch(_){}
    try{p10=e.add(0x10).readPointer();}catch(_){}
    try{p18=e.add(0x18).readPointer();}catch(_){}
    if(p8&&!p8.isNull()){rec.c8=cname(p8);rec.p8=p8.toString();}
    if(p10&&!p10.isNull()){rec.c10=cname(p10);rec.p10=p10.toString();}
    out.entries.push(rec);}
 }catch(e){out.err=""+e;}
 return out;};

// Dump methods of class-of-instance (walk parents). [{name,argc,ret}]
rpc.exports.dumpMethodsOfInst=function(inst){var h=H_();var k=h.OGC(ptr(inst));var out=[];var guard=0;
 while(k&&!k.isNull()&&guard<6){var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var m;
  while((m=h.cGM(k,it))&&!m.isNull()&&out.length<400){try{var rt="?";try{rt=h.tGN(h.mGRT(m)).readCString();}catch(e){}out.push({name:h.mGN(m).readCString(),argc:h.mGPC(m),ret:rt});}catch(e){}}
  try{k=h.cGParent(k);}catch(e){break;} guard++;}
 return out;};
rpc.exports.instFields=function(inst){var h=H_();var out=[];var k=h.OGC(ptr(inst));var guard=0;
 while(k&&!k.isNull()&&guard<8){var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
  while((f=h.cGF(k,it))&&!f.isNull()&&out.length<200){try{var tn="?";try{tn=h.tGN(h.fGT(f)).readCString();}catch(e){}out.push({off:h.fGO(f),name:h.fGN(f).readCString(),type:tn});}catch(e){}}
  try{k=h.cGParent(k);}catch(e){break;} guard++;}
 return out;};

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


def resolve_gm(finder, sc):
    """Re-find a live EncounterState and read its IGameMasterData @0x150."""
    for _ in range(8):
        r = finder.exports_sync.find_singleton(ENC_NS, ENC_CLS)
        hits = r.get("hits", []) if isinstance(r, dict) else []
        for h in hits:
            cn = sc.exports_sync.cls_name(h)
            if cn and cn.endswith("." + ENC_CLS):
                gm = sc.exports_sync.read_ptr(h, 0x150)
                if gm and gm.startswith("0x"):
                    return h, gm
        time.sleep(1.0)
    return None, None


def main():
    sess, pid = pg.get_session()
    print("attached", pid, flush=True)
    finder = pg.get_script_with_helpers(sess)
    sc = pg.get_script_with_helpers(sess, JS)
    try:
        es, gm = resolve_gm(finder, sc)
        print(f"EncounterState={es}  GameMasterData={gm} ({sc.exports_sync.cls_name(gm) if gm else None})", flush=True)
        if not gm:
            print("NO GameMasterData.", flush=True); return

        # --- A. Walk crlp : Dictionary<Type, IMessage> @0xd8 (global proto bag) ---
        dictp = sc.exports_sync.read_ptr(gm, 0xd8)
        print(f"\ncrlp Dictionary<Type,IMessage> @0xd8 = {dictp}", flush=True)
        enc_proto = None
        if dictp and dictp.startswith("0x"):
            res = sc.exports_sync.walk_dict(dictp)
            print(f"  count={res.get('count')} arrlen={res.get('arrlen')} err={res.get('err')}", flush=True)
            ents = res.get("entries", []) if isinstance(res, dict) else []
            print(f"  --- proto-bag values ({len(ents)} entries) ---", flush=True)
            for e in ents:
                c10 = e.get("c10")
                line = f"   idx{e.get('idx')} hash={e.get('hash')} key={e.get('c8')} val={c10} @ {e.get('p10')}"
                if c10 and "EncounterSettings" in c10:
                    line += "   <<<<< ENCOUNTERSETTINGS"
                    enc_proto = e.get("p10")
                print(line, flush=True)

        # --- B. Introspect crkt : IGlobalSettings @0x28 ---
        gs = sc.exports_sync.read_ptr(gm, 0x28)
        print(f"\ncrkt IGlobalSettings @0x28 = {gs} ({sc.exports_sync.cls_name(gs) if gs else None})", flush=True)
        if gs and gs.startswith("0x"):
            ms = sc.exports_sync.dump_methods_of_inst(gs) or []
            print(f"  --- IGlobalSettings impl methods returning Encounter/Settings ({len(ms)} total) ---", flush=True)
            for m in ms:
                rl = m["ret"].lower()
                if "encounter" in rl or "settings" in rl or "global" in rl:
                    print(f"     {m['name']} ({m['argc']}) -> {m['ret']}", flush=True)
            fs = sc.exports_sync.inst_fields(gs) or []
            print(f"  --- IGlobalSettings impl fields with Encounter/Settings type ---", flush=True)
            for f in fs:
                tl = f["type"].lower()
                if "encounter" in tl or "settings" in tl:
                    print(f"     +0x{f['off']:x} {f['name']} : {f['type']}", flush=True)

        # --- C. If we found the proto, READ THE FIELDS ---
        if enc_proto:
            print(f"\n=== LIVE EncounterSettingsProto @ {enc_proto} ===", flush=True)
            vals = sc.exports_sync.read_enc_settings(enc_proto)
            print("FIELDS:", vals, flush=True)
        else:
            print("\n(No EncounterSettingsProto found in proto bag — see IGlobalSettings leads above.)", flush=True)
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

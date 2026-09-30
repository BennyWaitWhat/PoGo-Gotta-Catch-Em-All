"""READ-ONLY: dump LIVE field values of PoGo's Go Plus subsystem services to find
the active path + current cadence/range values. For each target service it finds
live instances (liveness API) and reads every field by type (Single->float etc.),
so the bubbleDelay / captureDelay / delay-period / scanning / connected-device
state is shown with real numbers. WRITES NOTHING.
"""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

EXTRA_JS = r"""
var _R=null;
function _refl(){ if(_R) return _R; _ensureInit(); var il=Process.findModuleByName('libil2cpp.so'); var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  _R={CGF:b('il2cpp_class_get_fields','pointer',['pointer','pointer']),FGN:b('il2cpp_field_get_name','pointer',['pointer']),
      FGT:b('il2cpp_field_get_type','pointer',['pointer']),FGO:b('il2cpp_field_get_offset','uint32',['pointer']),
      TGN:b('il2cpp_type_get_name','pointer',['pointer'])};
  return _R;
}
function _cs(p){ try{return p.isNull()?'':p.readCString();}catch(e){return '';} }
function _rdCSStr(p){ try{ if(p.isNull())return null; var len=p.add(0x10).readS32(); if(len<0||len>256)return '(len?'+len+')'; var c=[]; for(var i=0;i<len;i++)c.push(String.fromCharCode(p.add(0x14+i*2).readU16())); return c.join(''); }catch(e){return '(err)';} }
function _rdField(inst,off,ty){
  try{
    if(ty==='System.Single') return inst.add(off).readFloat();
    if(ty==='System.Double') return inst.add(off).readDouble();
    if(ty==='System.Int32'||ty==='System.UInt32') return inst.add(off).readS32();
    if(ty==='System.Int64'||ty==='System.UInt64') return inst.add(off).readS64().toString();
    if(ty==='System.Boolean') return !!inst.add(off).readU8();
    if(ty==='System.Byte'||ty==='System.SByte') return inst.add(off).readU8();
    if(ty==='System.String') return _rdCSStr(inst.add(off).readPointer());
    var p=inst.add(off).readPointer();
    // generic RepeatedField/List count probe
    var cnt=null; try{ if(!p.isNull()){ var c=p.add(0x18).readS32(); if(c>=0&&c<100000)cnt=c; } }catch(e){}
    return 'ptr:'+p+(cnt!==null?(' (count@0x18='+cnt+')'):'');
  }catch(e){ return '(read err)'; }
}

rpc.exports.dumpInstance = function(ns, cls, instStr){
  _ensureInit(); var R=_refl(); var k=cFN(ns,cls); if(k.isNull()) return {err:'class not found'};
  var inst=ptr(instStr); var out=[];
  var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=R.CGF(k,it))&&!f.isNull()){ try{ var nm=_cs(R.FGN(f)); var off=R.FGO(f); var ty=_cs(R.TGN(R.FGT(f))); out.push({n:nm,o:'0x'+off.toString(16),t:ty,v:_rdField(inst,off,ty)}); }catch(e){} }
  return {fields:out};
};
"""

TARGETS = [
    ("Niantic.Holoholo.Services.SoftSfidaService", "SoftSfidaForegroundService"),
    ("Niantic.Holoholo.Services.SoftSfidaService", "SoftSfidaService"),
    ("Niantic.Holoholo.Pgp", "PgpService"),
    ("Niantic.Holoholo.Pgp", "PgpDeviceService"),
    ("PokemonGoPlus", "PgpState"),
    ("PokemonGoPlus", "PgpStateInternal"),
]


def main():
    sess, pid = pg.get_session()
    print("attached pid", pid)
    try:
        finder = pg.get_script_with_helpers(sess)          # has findSingleton
        sc = pg.get_script_with_helpers(sess, EXTRA_JS)     # has dumpInstance
        try:
            for ns, cls in TARGETS:
                r = finder.exports_sync.find_singleton(ns, cls)
                hits = r.get("hits", []) if isinstance(r, dict) else []
                err = r.get("err") if isinstance(r, dict) else None
                print(f"\n================ {ns}.{cls} ================")
                if err:
                    print("  find err:", err); continue
                print(f"  live instances: {len(hits)}")
                for h in hits[:2]:
                    d = sc.exports_sync.dump_instance(ns, cls, h)
                    if d.get("err"):
                        print("   dump err:", d["err"]); continue
                    for fld in d["fields"]:
                        ty = fld["t"]
                        interesting = (ty in ("System.Single", "System.Double", "System.Int32",
                                              "System.UInt32", "System.Int64", "System.Boolean")
                                       or "Settings" in ty or "Device" in ty or "List" in ty
                                       or "RepeatedField" in ty)
                        mark = " *" if interesting else ""
                        print(f"     {fld['n']}@{fld['o']}:{ty} = {fld['v']}{mark}")
        finally:
            sc.unload(); finder.unload()
    finally:
        sess.detach()


if __name__ == "__main__":
    main()

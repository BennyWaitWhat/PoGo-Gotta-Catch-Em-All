"""READ-ONLY: follow PgpService -> Waina device-read settings + connected device +
IPgpApi, and dump their live field values. This is the active virtual-Go-Plus+
auto-mode config (where any PoGo-side interval / range / cooldown knob would be).
WRITES NOTHING.
"""
import sys, os
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
function _rdCSStr(p){ try{ if(p.isNull())return null; var len=p.add(0x10).readS32(); if(len<0||len>256)return '(len?)'; var c=[]; for(var i=0;i<len;i++)c.push(String.fromCharCode(p.add(0x14+i*2).readU16())); return c.join(''); }catch(e){return '(err)';} }
function _rdField(inst,off,ty){
  try{
    if(ty==='System.Single') return inst.add(off).readFloat();
    if(ty==='System.Double') return inst.add(off).readDouble();
    if(ty==='System.Int32'||ty==='System.UInt32') return inst.add(off).readS32();
    if(ty==='System.Int64'||ty==='System.UInt64') return inst.add(off).readS64().toString();
    if(ty==='System.Boolean') return !!inst.add(off).readU8();
    if(ty==='System.Byte'||ty==='System.SByte') return inst.add(off).readU8();
    if(ty==='System.String') return _rdCSStr(inst.add(off).readPointer());
    var p=inst.add(off).readPointer(); var cnt=null; try{ if(!p.isNull()){var c=p.add(0x18).readS32(); if(c>=0&&c<100000)cnt=c;} }catch(e){}
    return 'ptr:'+p+(cnt!==null?(' (cnt@0x18='+cnt+')'):'');
  }catch(e){ return '(err)'; }
}
rpc.exports.readPtr = function(instStr, off){ try{ return ptr(instStr).add(off).readPointer().toString(); }catch(e){ return '0x0'; } };
rpc.exports.dumpAt = function(ns, cls, instStr){
  _ensureInit(); var R=_refl(); if(ptr(instStr).isNull()) return {err:'null instance'};
  var k=cFN(ns,cls); if(k.isNull()) return {err:'class not found '+ns+'.'+cls};
  var inst=ptr(instStr); var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=R.CGF(k,it))&&!f.isNull()){ try{ var nm=_cs(R.FGN(f)); var o=R.FGO(f); var ty=_cs(R.TGN(R.FGT(f))); out.push(nm+'@0x'+o.toString(16)+':'+ty+' = '+_rdField(inst,o,ty)); }catch(e){} }
  return {fields:out};
};
"""


def dump(sc, ns, cls, addr, label):
    print(f"\n================ {label}  ({ns}.{cls} @ {addr}) ================")
    if not addr or addr == "0x0":
        print("  (null)")
        return
    d = sc.exports_sync.dump_at(ns, cls, addr)
    if d.get("err"):
        print("  err:", d["err"]); return
    for line in d["fields"]:
        print("  ", line)


def main():
    sess, pid = pg.get_session()
    print("attached pid", pid)
    try:
        finder = pg.get_script_with_helpers(sess)
        sc = pg.get_script_with_helpers(sess, EXTRA_JS)
        try:
            r = finder.exports_sync.find_singleton("Niantic.Holoholo.Pgp", "PgpService")
            hits = r.get("hits", []) if isinstance(r, dict) else []
            svc = None
            for h in hits:
                dev = sc.exports_sync.read_ptr(h, 0xF0)   # cunk = connected ScannedWearableDevice
                if dev and dev != "0x0":
                    svc = h; break
            if not svc:
                svc = hits[0] if hits else None
            print("PgpService (real, device-connected):", svc)
            if not svc:
                print("no PgpService instance"); return
            waina = sc.exports_sync.read_ptr(svc, 0x118)
            dev = sc.exports_sync.read_ptr(svc, 0xF0)
            api = sc.exports_sync.read_ptr(svc, 0xE8)
            dump(sc, "PokemonGoPlus", "PgpWainaDeviceReadSettings", waina, "WAINA AUTO-MODE / READ SETTINGS")
            dump(sc, "PokemonGoPlus", "ScannedWearableDevice", dev, "CONNECTED VIRTUAL DEVICE")
            dump(sc, "PokemonGoPlus", "PgpApi", api, "PGP API")
        finally:
            sc.unload(); finder.unload()
    finally:
        sess.detach()


if __name__ == "__main__":
    main()

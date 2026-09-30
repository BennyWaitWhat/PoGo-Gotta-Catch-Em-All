"""READ-ONLY: dump live AdventureEffectService state (active effect type + applied bonus
data) and follow the applied-bonus object. Run before vs during Spacial Rend to see the
delta (which proves whether the server granted extra encounter/interaction reach)."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

EXTRA_JS = r"""
var _E=null;
function _e(){ if(_E)return _E; var il=Process.findModuleByName('libil2cpp.so'); var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  _E={OGC:b('il2cpp_object_get_class','pointer',['pointer']),CGN:b('il2cpp_class_get_name','pointer',['pointer']),
      CGF:b('il2cpp_class_get_fields','pointer',['pointer','pointer']),FGN:b('il2cpp_field_get_name','pointer',['pointer']),
      FGT:b('il2cpp_field_get_type','pointer',['pointer']),FGO:b('il2cpp_field_get_offset','uint32',['pointer']),
      TGN:b('il2cpp_type_get_name','pointer',['pointer'])};
  return _E;
}
function _cs(p){ try{return p.isNull()?'':p.readCString();}catch(e){return '';} }
function _rd(inst,off,ty){
  try{
    if(ty==='System.Single')return inst.add(off).readFloat();
    if(ty==='System.Double')return inst.add(off).readDouble();
    if(ty.indexOf('Int64')>=0||ty.indexOf('UInt64')>=0)return inst.add(off).readS64().toString();
    if(ty.indexOf('Int32')>=0||ty.indexOf('UInt32')>=0)return inst.add(off).readS32();
    if(ty.indexOf('Int16')>=0||ty.indexOf('UInt16')>=0)return inst.add(off).readS16();
    if(ty==='System.Boolean')return !!inst.add(off).readU8();
    if(ty==='System.Byte'||ty==='System.SByte')return inst.add(off).readU8();
    var p=inst.add(off).readPointer(); return 'ptr:'+p;
  }catch(e){return '(err)';}
}
function _dump(inst){
  var E=_e(); if(ptr(inst).isNull())return {err:'null'};
  var k=E.OGC(ptr(inst)); var out=[]; var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
  while((f=E.CGF(k,it))&&!f.isNull()){ try{ var nm=_cs(E.FGN(f)); var o=E.FGO(f); var ty=_cs(E.TGN(E.FGT(f))); out.push(nm+'@0x'+o.toString(16)+':'+ty+' = '+_rd(ptr(inst),o,ty)); }catch(e){} }
  return {cls:_cs(E.CGN(k)), fields:out};
}
rpc.exports.dumpObj=function(instStr){ _ensureInit(); return _dump(instStr); };
rpc.exports.readPtr=function(instStr,off){ try{return ptr(instStr).add(off).readPointer().toString();}catch(e){return '0x0';} };
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        finder = pg.get_script_with_helpers(sess)
        sc = pg.get_script_with_helpers(sess, EXTRA_JS)
        try:
            ns, cls = "Niantic.Holoholo.AdventureEffect", "AdventureEffectService"
            r = finder.exports_sync.find_singleton(ns, cls)
            hits = r.get("hits", []) if isinstance(r, dict) else []
            print(f"{ns}.{cls}: {len(hits)} instance(s)  {r.get('err','') if isinstance(r,dict) else ''}")
            for h in hits[:2]:
                d = sc.exports_sync.dump_obj(h)
                print(f"\n== instance @{h}  ({d.get('cls')}) ==")
                for line in d.get("fields", []):
                    print("  ", line)
                def _follow(addr, depth, indent):
                    sd = sc.exports_sync.dump_obj(addr)
                    print(indent + f"({sd.get('cls')})")
                    for s in sd.get("fields", []):
                        print(indent, s)
                    if depth <= 0:
                        return
                    for s in sd.get("fields", []):
                        low = s.lower()
                        if "ptr:0x" in s and "ptr:0x0" not in s and "parser@" not in low and any(k in low for k in ["effect", "bonus", "appliedadventure", "activeeffect"]):
                            try:
                                o2 = int(s.split("@0x")[1].split(":")[0], 16)
                            except Exception:
                                continue
                            sub2 = sc.exports_sync.read_ptr(addr, o2)
                            if sub2 and sub2 != "0x0" and int(sub2, 16) > 0x100000:
                                print(indent + "  -> " + s.split("@")[0].strip() + " @" + sub2)
                                _follow(sub2, depth - 1, indent + "     ")
                for line in d.get("fields", []):
                    low = line.lower()
                    if ("bonus" in low or "appliedadventure" in low or "activeadventureeffectproto" in low) and "ptr:0x" in line and "ptr:0x0" not in line:
                        off = int(line.split("@0x")[1].split(":")[0], 16)
                        sub = sc.exports_sync.read_ptr(h, off)
                        if sub and sub != "0x0":
                            print(f"   -> {line.split('@')[0].strip()} @{sub}:")
                            _follow(sub, 3, "        ")
                b = sc.exports_sync.read_ptr(h, 0xa8)
                if b and b != "0x0":
                    eff = sc.exports_sync.read_ptr(b, 0x28)
                    if eff and eff != "0x0":
                        val = sc.exports_sync.read_ptr(eff, 0x10)
                        if val and val != "0x0":
                            vd = sc.exports_sync.dump_obj(val)
                            print(f"   *** SPACIAL REND bonus value ({vd.get('cls')}): ***")
                            for s in vd.get("fields", []):
                                print("        ", s)
        finally:
            sc.unload(); finder.unload()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

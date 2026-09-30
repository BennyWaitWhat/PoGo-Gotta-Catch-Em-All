"""TIME-SENSITIVE capture of the LIVE Spacial Rend bonus state (while active) so it can be
analyzed/replicated after it expires. Grabs: the AppliedBonusProto + AppliedSpaceBonusProto
(values + raw bytes), every memory cache of the 350m allowable-range double, the active
AdventureEffect, and the PlayerBuffService. Saves all to disk. READ-ONLY."""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402
OUT = os.path.join(ROOT, "system", "analysis", "pokemod", "spacial_rend_capture.txt")

EXTRA_JS = r"""
var _E=null;
function _e(){ if(_E)return _E; var il=Process.findModuleByName('libil2cpp.so'); var e={};
  il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
  function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
  _E={OGC:b('il2cpp_object_get_class','pointer',['pointer']),CGN:b('il2cpp_class_get_name','pointer',['pointer']),
      CGF:b('il2cpp_class_get_fields','pointer',['pointer','pointer']),FGN:b('il2cpp_field_get_name','pointer',['pointer']),
      FGT:b('il2cpp_field_get_type','pointer',['pointer']),FGO:b('il2cpp_field_get_offset','uint32',['pointer']),TGN:b('il2cpp_type_get_name','pointer',['pointer'])};
  return _E;}
function _cs(p){try{return p.isNull()?'':p.readCString();}catch(e){return '';}}
function _rd(inst,off,ty){try{
  if(ty==='System.Single')return inst.add(off).readFloat();
  if(ty==='System.Double')return inst.add(off).readDouble();
  if(ty.indexOf('Int64')>=0||ty.indexOf('UInt64')>=0)return inst.add(off).readS64().toString();
  if(ty.indexOf('Int32')>=0||ty.indexOf('UInt32')>=0)return inst.add(off).readS32();
  if(ty==='System.Boolean')return !!inst.add(off).readU8();
  return 'ptr:'+inst.add(off).readPointer();}catch(e){return '(err)';}}
rpc.exports.dumpObj=function(s){var E=_e();if(ptr(s).isNull())return{err:'null'};var k=E.OGC(ptr(s));var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;while((f=E.CGF(k,it))&&!f.isNull()){try{var nm=_cs(E.FGN(f));var o=E.FGO(f);var ty=_cs(E.TGN(E.FGT(f)));out.push(nm+'@0x'+o.toString(16)+':'+ty+' = '+_rd(ptr(s),o,ty));}catch(e){}}return{cls:_cs(E.CGN(k)),fields:out};};
rpc.exports.readPtr=function(s,o){try{return ptr(s).add(o).readPointer().toString();}catch(e){return '0x0';}};
rpc.exports.readD=function(a){try{return ptr(a).readDouble();}catch(e){return null;}};
rpc.exports.hexAt=function(a,n){try{var b=Memory.readByteArray(ptr(a),n);if(!b)return'';var u=new Uint8Array(b);var h=[];for(var i=0;i<u.length;i++){var c=u[i].toString(16);h.push(c.length<2?'0'+c:c);}return h.join(' ');}catch(e){return 'err';}};
rpc.exports.scanPattern=function(pat){var out=[];Process.enumerateRanges('rw-').forEach(function(r){if(r.file||r.size<256||r.size>134217728)return;try{var hs=Memory.scanSync(r.base,r.size,pat);for(var i=0;i<hs.length&&out.length<300;i++)out.push(hs[i].address.toString());}catch(e){}});return out;};
"""

LINES = []
def L(s):
    print(s); LINES.append(str(s))

def main():
    sess, pid = pg.get_session()
    L(f"attached {pid}")
    try:
        finder = pg.get_script_with_helpers(sess)
        sc = pg.get_script_with_helpers(sess, EXTRA_JS)
        try:
            r = finder.exports_sync.find_singleton("Niantic.Holoholo.AdventureEffect", "AdventureEffectService")
            hits = r.get("hits", []) if isinstance(r, dict) else []
            active = None
            for h in hits:
                if sc.exports_sync.read_ptr(h, 0xA8) not in (None, "0x0"):
                    active = h; break
            L(f"AEService active instance: {active}")
            if active:
                dxln = sc.exports_sync.read_ptr(active, 0xA0)
                bonus = sc.exports_sync.read_ptr(active, 0xA8)
                L(f"\n== active AdventureEffect @{dxln} ==")
                L(json.dumps(sc.exports_sync.dump_obj(dxln), indent=1))
                L(f"\n== AppliedBonusProto @{bonus} ==")
                L(json.dumps(sc.exports_sync.dump_obj(bonus), indent=1))
                L(f"   raw: {sc.exports_sync.hex_at(bonus, 0x40)}")
                eff = sc.exports_sync.read_ptr(bonus, 0x28)
                spc = sc.exports_sync.read_ptr(eff, 0x10)
                L(f"\n== AppliedSpaceBonusProto @{spc} ==")
                L(json.dumps(sc.exports_sync.dump_obj(spc), indent=1))
                L(f"   raw: {sc.exports_sync.hex_at(spc, 0x40)}")
            # all caches of the 350 allowable-range double
            L("\n== memory caches of 350.0 (allowable-range double) ==")
            import struct
            pat350 = " ".join(f"{b:02x}" for b in struct.pack("<d", 350.0))
            hits350 = sc.exports_sync.scan_pattern(pat350)
            L(f"   {len(hits350)} hits")
            bonus_protos = []
            for a in hits350:
                ai = int(a, 16)
                vis = sc.exports_sync.read_d(hex(ai - 0x10))
                enc = sc.exports_sync.read_d(hex(ai - 0x8))
                tag = ""
                if isinstance(vis, (int, float)) and isinstance(enc, (int, float)) and 0 < vis < 1000 and 0 < enc < 1000:
                    tag = f"  <-- AppliedSpaceBonusProto-like (vis={vis}, enc={enc}, allow=350) base=@{hex(ai-0x20)}"
                    bonus_protos.append(hex(ai - 0x20))
                L(f"   @{a} {tag}")
            L(f"\n   => {len(bonus_protos)} look like AppliedSpaceBonusProto instances: {bonus_protos}")
            # PlayerBuffService (likely read-source)
            for cand in [("Niantic.Holoholo.Items", "PlayerBuffService"), ("Niantic.Holoholo.Items", "PlayerBuffServiceImpl")]:
                rb = finder.exports_sync.find_singleton(*cand)
                bh = rb.get("hits", []) if isinstance(rb, dict) else []
                if bh:
                    L(f"\n== {cand[0]}.{cand[1]} @{bh[0]} ==")
                    L(json.dumps(sc.exports_sync.dump_obj(bh[0]), indent=1))
                    break
            sess.detach()
        finally:
            try: sc.unload(); finder.unload()
            except Exception: pass
    finally:
        try: sess.detach()
        except Exception: pass
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES))
    print(f"\nsaved -> {OUT}")

main()

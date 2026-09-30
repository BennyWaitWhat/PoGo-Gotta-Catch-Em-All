"""Dump the connected ScannedWearableDevice on PgpService (name + kind + key fields) to identify
whether it's VGP3 (e.g. 'vPGP') or the user's real device, and what DeviceKind PoGo assigns it.
READ-ONLY."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

KIND = {0: "UNSET", 1: "POKEMON_GO_PLUS", 2: "POKE_BALL_PLUS", 3: "WAINA"}

EXTRA_JS = r"""
var _E=null;
function _e(){ if(_E)return _E; var il=Process.findModuleByName('libil2cpp.so'); var e={};
 il.enumerateExports().forEach(function(x){if(x.name.indexOf('il2cpp_')===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 _E={OGC:b('il2cpp_object_get_class','pointer',['pointer']),CGN:b('il2cpp_class_get_name','pointer',['pointer']),CGF:b('il2cpp_class_get_fields','pointer',['pointer','pointer']),FGN:b('il2cpp_field_get_name','pointer',['pointer']),FGO:b('il2cpp_field_get_offset','uint32',['pointer']),FGT:b('il2cpp_field_get_type','pointer',['pointer']),TGN:b('il2cpp_type_get_name','pointer',['pointer'])};
 return _E;}
function _cs(p){try{return p.isNull()?'':p.readCString();}catch(e){return '';}}
function _str(p){try{if(!p||p.isNull())return'';var len=p.add(0x10).readS32();if(len<=0||len>128)return'';var c=[];for(var i=0;i<len;i++)c.push(String.fromCharCode(p.add(0x14+i*2).readU16()));return c.join('');}catch(e){return'';}}
rpc.exports.readPtr=function(s,o){try{return ptr(s).add(o).readPointer().toString();}catch(e){return '0x0';}};
rpc.exports.dumpFull=function(s){var E=_e();if(ptr(s).isNull())return{err:'null'};var k=E.OGC(ptr(s));var out=[];var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
 while((f=E.CGF(k,it))&&!f.isNull()){try{var nm=_cs(E.FGN(f));var o=E.FGO(f);var ty=_cs(E.TGN(E.FGT(f)));var v;
   if(ty==='System.String')v='"'+_str(ptr(s).add(o).readPointer())+'"';
   else if(ty.indexOf('DeviceKind')>=0)v='kind='+ptr(s).add(o).readS32();
   else if(ty.indexOf('Int32')>=0||ty.indexOf('UInt32')>=0)v=ptr(s).add(o).readS32();
   else if(ty==='System.Boolean')v=!!ptr(s).add(o).readU8();
   else v='ptr:'+ptr(s).add(o).readPointer();
   out.push(nm+'@0x'+o.toString(16)+':'+ty+' = '+v);
 }catch(e){}}
 return {cls:_cs(E.CGN(k)),fields:out};
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        finder = pg.get_script_with_helpers(sess)
        sc = pg.get_script_with_helpers(sess, EXTRA_JS)
        try:
            r = finder.exports_sync.find_singleton("Niantic.Holoholo.Pgp", "PgpService")
            hits = r.get("hits", []) if isinstance(r, dict) else []
            for h in hits:
                dev = sc.exports_sync.read_ptr(h, 0xF0)  # cunk = connected ScannedWearableDevice
                if dev in (None, "0x0"):
                    continue
                d = sc.exports_sync.dump_full(dev)
                print(f"\n== connected device @{dev} ({d.get('cls')}) ==")
                for line in d.get("fields", []):
                    mark = ""
                    if "kind=" in line:
                        try:
                            v = int(line.split("kind=")[1].split()[0])
                            mark = "   <== " + KIND.get(v, str(v))
                        except Exception:
                            pass
                    print("   ", line, mark)
        finally:
            try: sc.unload(); finder.unload()
            except Exception: pass
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

"""Read the LIVE connected wearable device on PgpService and its DeviceKind — to confirm whether the
real Go Plus + currently paired shows up as WAINA(3) (vs VGP3's POKEMON_GO_PLUS). READ-ONLY."""
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
rpc.exports.dumpDevice=function(s){var E=_e();if(ptr(s).isNull())return{err:'null'};var k=E.OGC(ptr(s));var out=[];var devField=null;var it=Memory.alloc(Process.pointerSize);it.writePointer(ptr(0));var f;
 while((f=E.CGF(k,it))&&!f.isNull()){try{var nm=_cs(E.FGN(f));var o=E.FGO(f);var ty=_cs(E.TGN(E.FGT(f)));var low=(nm+ty).toLowerCase();
   var val='';
   if(ty.indexOf('ScannedWearableDevice')>=0||ty.indexOf('WearableDevice')>=0||low.indexOf('connecteddevice')>=0){var p=ptr(s).add(o).readPointer();val='ptr:'+p;if(!p.isNull()){try{val+=' kind@0x1c='+p.add(0x1c).readS32();}catch(e){}}}
   else if(ty.indexOf('DeviceKind')>=0){val='kind='+ptr(s).add(o).readS32();}
   else if(low.indexOf('paired')>=0||low.indexOf('connect')>=0||low.indexOf('device')>=0){try{val=(ty==='System.Boolean')?(''+!!ptr(s).add(o).readU8()):('ptr:'+ptr(s).add(o).readPointer());}catch(e){}}
   if(val!=='')out.push(nm+'@0x'+o.toString(16)+':'+ty+' = '+val);
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
            print(f"PgpService instances: {len(hits)}\n")
            for h in hits:
                d = sc.exports_sync.dump_device(h)
                print(f"== PgpService @{h} ({d.get('cls')}) ==")
                for line in d.get("fields", []):
                    mark = ""
                    if "kind@0x1c=" in line:
                        try:
                            v = int(line.split("kind@0x1c=")[1].split()[0])
                            mark = "   <== " + KIND.get(v, str(v))
                        except Exception:
                            pass
                    print("   ", line, mark)
                print()
        finally:
            try: sc.unload(); finder.unload()
            except Exception: pass
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

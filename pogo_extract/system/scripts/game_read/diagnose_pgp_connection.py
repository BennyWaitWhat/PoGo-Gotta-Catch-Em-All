"""Diagnose the live Go-Plus connection: invoke the PgpService state getters (HasPairedDevice,
IsConnected, IsSessionActive, DeviceState, HasPairedPbp/Waina/Pgp) to tell whether the real device is
actually CONNECTED + its session ACTIVE (catching), vs just nominally 'paired'. READ-ONLY (getters)."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

MY_JS = r"""
var H=null;
function H_(){ if(H)return H; var il=Process.findModuleByName("libil2cpp.so");var e={};il.enumerateExports().forEach(function(x){if(x.name.indexOf("il2cpp_")===0)e[x.name]=x.address;});
 function b(n,r,a){return e[n]?new NativeFunction(e[n],r,a):null;}
 H={OGC:b("il2cpp_object_get_class","pointer",["pointer"]),cMN:b("il2cpp_class_get_method_from_name","pointer",["pointer","pointer","int"]),rI:b("il2cpp_runtime_invoke","pointer",["pointer","pointer","pointer","pointer"]),dG:b("il2cpp_domain_get","pointer",[]),tA:b("il2cpp_thread_attach","pointer",["pointer"])};
 H.tA(H.dG());return H;}
function callGetter(psCls,ps,name){var h=H_();var m=h.cMN(psCls,Memory.allocUtf8String(name),0);if(!m||m.isNull())return name+": (no method)";var exc=Memory.alloc(Process.pointerSize);exc.writePointer(ptr(0));var ret=h.rI(m,ps,ptr(0),exc);if(!exc.readPointer().isNull())return name+": EXC";if(ret.isNull())return name+"=null";try{return name+"="+ret.add(0x10).readS32();}catch(e){return name+"=?";}}
rpc.exports.cumt=function(psStr){try{return ptr(psStr).add(0x40).readPointer().toString();}catch(e){return "0x0";}};
rpc.exports.diagOne=function(psStr,name,isInt){var h=H_();var ps=ptr(psStr);var psCls=h.OGC(ps);return callGetter(psCls,ps,name);};
"""

GETTERS = ["get_HasPairedDevice", "get_IsConnected", "get_IsSessionActive",
           "get_IsStableConnectState", "get_IsDisconnecting", "get_DeviceState",
           "get_HasPairedPbp", "get_HasPairedWaina", "get_HasPairedPgp"]


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        finder = pg.get_script_with_helpers(sess)
        sc = pg.get_script_with_helpers(sess, MY_JS)
        try:
            r = finder.exports_sync.find_singleton("Niantic.Holoholo.Pgp", "PgpService")
            hits = r.get("hits", []) if isinstance(r, dict) else []
            active = [h for h in hits if sc.exports_sync.cumt(h) not in (None, "0x0")]
            ps = active[0] if active else (hits[0] if hits else None)
            print(f"PgpService: {len(hits)} instances, using active {ps}\n")
            if not ps:
                print("no PgpService"); return
            for name in GETTERS:
                try:
                    print("  ", sc.exports_sync.diag_one(ps, name, False))
                except Exception as e:
                    print(f"   {name}: ABORTED ({str(e)[:60]})")
                    # an abort likely destroys the script; re-create for the next getter
                    try:
                        sc.unload()
                    except Exception:
                        pass
                    sc = pg.get_script_with_helpers(sess, MY_JS)
            print("\n(1=true/0=false for the bool getters; DeviceState is an enum value)")
        finally:
            try: sc.unload(); finder.unload()
            except Exception: pass
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

"""Diagnose libholoholo.so symbol visibility at runtime + validate the static RVA offsets.
READ-ONLY one-shot. Decides whether to hook by symbol name or by base+offset."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

JS = r"""
rpc.exports.probe=function(){
 var mod=Process.findModuleByName("libholoholo.so");
 if(!mod)return {err:"not loaded"};
 var ex=[],sy=[];
 try{ex=mod.enumerateExports();}catch(e){}
 try{sy=mod.enumerateSymbols();}catch(e){}
 function samp(arr,parts,lim){var out=[];for(var i=0;i<arr.length&&out.length<lim;i++){var n=arr[i].name;var ok=true;for(var j=0;j<parts.length;j++){if(n.indexOf(parts[j])<0){ok=false;break;}}if(ok)out.push(n+" @0x"+arr[i].address.sub(mod.base).toString(16));}return out;}
 function dis(off,cnt){var out=[];try{var ins=mod.base.add(off);for(var i=0;i<cnt;i++){var d=Instruction.parse(ins);out.push("0x"+d.address.sub(mod.base).toString(16)+": "+d.mnemonic+" "+d.opStr);ins=d.next;}}catch(e){out.push("ERR "+e);}return out;}
 return {
  size:"0x"+mod.size.toString(16), nExports:ex.length, nSymbols:sy.length,
  sample_exports: ex.slice(0,6).map(function(x){return x.name;}),
  m_scanned_sym: samp(sy,["Scanned"],6), m_sfida_sym: samp(sy,["Sfida"],6),
  m_serialize_sym: samp(sy,["Serialize"],6), m_proxy_sym: samp(sy,["Proxy"],6),
  m_scanned_ex: samp(ex,["Scanned"],6), m_sfida_ex: samp(ex,["Sfida"],6),
  dis_AddScannedSfida_8a6bfc: dis(0x8a6bfc,4),
  dis_CatchPokemon_8e10a0: dis(0x8e10a0,4),
  dis_InitBtKey_8c6064: dis(0x8c6064,3),
 };
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        r = sc.exports_sync.probe()
        import json
        print(json.dumps(r, indent=2))
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

"""Find the exact libholoholo.so EXPORT names for the envelope + catch serializers we need to hook.
READ-ONLY one-shot."""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

PATTERNS = {
    "GarProxy": ["GarProxy"],
    "ProxyRequest": ["ProxyRequest"],
    "any_InternalSerialize": ["_InternalSerialize"],
    "SfidaCapture_methods": ["SfidaCaptureRequest"],
    "SfidaUpdate_methods": ["SfidaUpdateRequest"],
    "MakeProtobufAction": ["MakeProtobufAction"],
    "RpcManager_send": ["RpcManager"],
    "EnqueueRpc": ["Enqueue"],
}

JS = r"""
rpc.exports.search=function(patsJson){
 var mod=Process.findModuleByName("libholoholo.so");
 if(!mod)return {err:"not loaded"};
 var pats=JSON.parse(patsJson);
 var ex=mod.enumerateExports();
 var out={};
 var counts={};
 for(var key in pats){out[key]=[];counts[key]=0;}
 for(var i=0;i<ex.length;i++){
  var n=ex[i].name;
  for(var key in pats){
   var parts=pats[key];var ok=true;
   for(var j=0;j<parts.length;j++){if(n.indexOf(parts[j])<0){ok=false;break;}}
   if(ok){counts[key]++;if(out[key].length<10)out[key].push(n+" @0x"+ex[i].address.sub(mod.base).toString(16));}
  }
 }
 return {counts:counts, matches:out};
};
"""


def main():
    sess, pid = pg.get_session()
    print("attached", pid)
    try:
        sc = sess.create_script(JS); sc.on("message", lambda m, d: None); sc.load()
        r = sc.exports_sync.search(json.dumps(PATTERNS))
        print(json.dumps(r, indent=2))
        sess.detach()
    finally:
        try:
            sess.detach()
        except Exception:
            pass


main()

"""Confirm IapService stardust methods + hook set_Stardusts to record the actual
add path (caller backtrace + old->new delta). Read-only observation; logs to stdout."""
import frida, json, time, sys
sys.path.insert(0, '.')
import pogo_il2cpp as pg

EXTRA = r'''
rpc.exports.iapStardustMethods = function(){
  _ensureInit();
  var k = cFN('Niantic.Holoholo.Storefront','IapService');
  if(!k || k.isNull()) return {err:'no IapService'};
  var il2=Process.findModuleByName('libil2cpp.so');
  var cgm=new NativeFunction(il2.findExportByName('il2cpp_class_get_methods'),'pointer',['pointer','pointer']);
  var mgn=new NativeFunction(il2.findExportByName('il2cpp_method_get_name'),'pointer',['pointer']);
  var mgpc=new NativeFunction(il2.findExportByName('il2cpp_method_get_param_count'),'uint32',['pointer']);
  var it=Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
  var out=[]; var m;
  while(!(m=cgm(k,it)).isNull()){
    var nm=mgn(m).readCString();
    if(/stardust|coin|currenc/i.test(nm)) out.push({name:nm, argc:mgpc(m), method:m.toString(), code:m.readPointer().toString()});
  }
  return out;
};
// hook set_Stardusts: arg0=this, arg1=new value (long). Log + backtrace.
rpc.exports.hookSetStardusts = function(){
  _ensureInit();
  var k=cFN('Niantic.Holoholo.Storefront','IapService');
  var m=cMN(k,'set_Stardusts',1);
  if(!m || m.isNull()) return {err:'no set_Stardusts'};
  var code=m.readPointer();   // MethodInfo->methodPointer @ offset 0
  Interceptor.attach(code,{
    onEnter:function(a){
      var val=a[1].toInt32();
      var bt=Thread.backtrace(this.context, Backtracer.ACCURATE).slice(0,8)
              .map(function(x){return DebugSymbol.fromAddress(x).toString();});
      send({stardust_set:val, backtrace:bt});
    }
  });
  return {ok:true, hooked:code.toString()};
};
'''

def run():
    sess, pid = pg.get_session()
    sc = pg.get_script_with_helpers(sess, EXTRA)
    msgs = []
    sc.on('message', lambda m, d: msgs.append(m.get('payload')))
    methods = sc.exports_sync.iap_stardust_methods()
    print('IapService stardust/coin/currency methods:')
    for m in (methods if isinstance(methods, list) else [methods]):
        print('  ', m)
    h = sc.exports_sync.hook_set_stardusts()
    print('hook:', h)
    print('watching set_Stardusts for 25s (play / open a gift to capture an add)...')
    time.sleep(25)
    print(f'captured {len(msgs)} set_Stardusts calls:')
    for m in msgs: print('  ', json.dumps(m)[:400])
    sess.detach()

for a in range(5):
    try: run(); break
    except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
            frida.ServerNotRunningError, RuntimeError) as e:
        print('retry', a, type(e).__name__, e); time.sleep(4)

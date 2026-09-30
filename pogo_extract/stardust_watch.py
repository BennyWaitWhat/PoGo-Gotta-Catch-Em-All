"""Record stardust additions live. Hooks IapService.set_Stardusts and appends every
balance change (ts, old, new, delta, caller backtrace) to stardust_log.jsonl.
Run while playing: catches/gifts/quests fire it. Observe-only. Ctrl-C to stop.
Usage: python stardust_watch.py [seconds]   (default: run until interrupted)"""
import frida, json, time, sys
sys.path.insert(0, '.')
import pogo_il2cpp as pg

DUR = int(sys.argv[1]) if len(sys.argv) > 1 else None
EXTRA = r'''
rpc.exports.hookStardust = function(){
  _ensureInit();
  var k = cFN('Niantic.Holoholo.Storefront','IapService');
  if(!k || k.isNull()) return {err:'no IapService'};
  var getM = cMN(k,'get_Stardusts',0);
  var rI_local = rI;
  var setM = cMN(k,'set_Stardusts',1);
  if(!setM || setM.isNull()) return {err:'no set_Stardusts'};
  Interceptor.attach(setM.readPointer(), {
    onEnter:function(a){
      var inst=a[0], nv=a[1].toInt32();
      var old=null;
      try { var r=rI_local(getM, inst, ptr(0), null); old=r.add(0x10).readS64().toString(); } catch(e){}
      var bt=Thread.backtrace(this.context, Backtracer.ACCURATE).slice(0,10)
              .map(function(x){return DebugSymbol.fromAddress(x).toString();});
      send({ts:Date.now(), old:old, new:nv, bt:bt});
    }
  });
  return {ok:true};
};
'''

def run():
    sess, pid = pg.get_session()
    sc = pg.get_script_with_helpers(sess, EXTRA)
    f = open('stardust_log.jsonl', 'a', encoding='utf-8')
    def on_msg(m, d):
        p = m.get('payload')
        if not p: return
        delta = None
        try: delta = p['new'] - int(p['old'])
        except Exception: pass
        rec = {'ts': p['ts'], 'old': p['old'], 'new': p['new'], 'delta': delta, 'bt': p['bt']}
        f.write(json.dumps(rec) + '\n'); f.flush()
        print(f"[stardust] {p['old']} -> {p['new']}  (delta {delta})")
        for b in p['bt'][:5]: print('    ', b)
    sc.on('message', on_msg)
    r = sc.exports_sync.hook_stardust()
    print('hook:', r, '| logging to stardust_log.jsonl | play to capture gains')
    if DUR: time.sleep(DUR)
    else:
        while True: time.sleep(3600)

for a in range(6):
    try:
        run(); break
    except KeyboardInterrupt:
        print('stopped'); break
    except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
            frida.ServerNotRunningError, RuntimeError) as e:
        print('retry', a, type(e).__name__, e); time.sleep(4)

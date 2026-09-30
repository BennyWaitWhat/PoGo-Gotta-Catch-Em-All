"""Inject fake sleep records directly into SleepService.dwst.SleepRecord then trigger sync.

Hypothesis: SleepRecordsProto.SleepRecord is the local cache PoGo submits to server.
If we add SleepDayRecordProto entries with different SleepDay numbers + valid durations,
then trigger ReadNewSleepLogs / a sync method, PoGo submits with auth-signed session.
"""
import frida, json, time, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}', flush=True)
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

hook_js = """
var sleepInst = null;
function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var addrs = {};
    il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
    var dG = bind('il2cpp_domain_get','pointer',[]);
    var dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    var aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
    var iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
    var cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    var cGM = bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    tA(dG());
    var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
    var gi = null;
    for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Sleep'), Memory.allocUtf8String('SleepService'));
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    while ((m = cGM(cls, iter)) && !m.isNull()) {
        try {
            var addr = m.readPointer();
            if (addr.isNull()) continue;
            Interceptor.attach(addr, {
                onEnter: function(args) { if (!sleepInst) { sleepInst = args[0].toString(); send({type:'h', msg:'sleep '+sleepInst}); } }
            });
        } catch(e) {}
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {sleep: sleepInst}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}", flush=True)
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Waiting up to 240s for SleepService hook (open Today, swipe to Sleep)...", flush=True)
sleep_inst = None
for i in range(240):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('sleep'): sleep_inst = g['sleep']; break
if not sleep_inst:
    print("No SleepService captured.", flush=True)
    sess.detach(); exit(1)
print(f"\nSleepService: {sleep_inst}", flush=True)
hs.unload()

js = """
rpc.exports = {
    inject: function(sleepAddr, days) {
        var inst = ptr(sleepAddr);
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var addrs = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
        var dG = bind('il2cpp_domain_get','pointer',[]);
        var dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
        var cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
        var cMN = bind('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']);
        var rI = bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
        var objNew = new NativeFunction(addrs['il2cpp_object_new'],'pointer',['pointer']);
        var arrNewSpec = new NativeFunction(addrs['il2cpp_array_new_specific'],'pointer',['pointer','uint32']);
        var arrClsGet = new NativeFunction(addrs['il2cpp_array_class_get'],'pointer',['pointer','uint32']);
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var hpr = null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-protos.dll'){ hpr=i; break; } }
        var dayCls = cFN(hpr, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('SleepDayRecordProto'));
        if (dayCls.isNull()) return {error:'SleepDayRecordProto class not found'};

        // dwst = SleepRecordsProto at SleepService +0x48
        var srProto = inst.add(0x48).readPointer();
        if (srProto.isNull()) return {error:'srProto null'};
        var srRf = srProto.add(0x10).readPointer();
        if (srRf.isNull()) return {error:'srRf null'};

        // Build N SleepDayRecordProto entries, days starting at currentDay+1
        var dayCtor = cMN(dayCls, Memory.allocUtf8String('.ctor'), 0);
        var records = [];
        var startDay = days[0];  // first day number
        for (var i = 0; i < days.length; i++) {
            var rec = objNew(dayCls);
            var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
            rI(dayCtor, rec, ptr(0), ex);
            // Set fields: SleepDay (UInt32 +0x10), SleepDurationSec (UInt32 +0x14), Rewarded (bool +0x18)
            rec.add(0x10).writeU32(days[i]);
            rec.add(0x14).writeU32(28800);  // 8 hours
            rec.add(0x18).writeU8(0);  // not rewarded yet
            records.push(rec);
        }

        // Build SleepDayRecordProto[] array
        var arrCls = arrClsGet(dayCls, 1);
        var arr = arrNewSpec(arrCls, records.length);
        for (var i = 0; i < records.length; i++) {
            arr.add(0x20 + i*8).writePointer(records[i]);
        }
        // Set RepeatedField fields: array at +0x10, count at +0x18
        srRf.add(0x10).writePointer(arr);
        srRf.add(0x18).writeS32(records.length);

        // Set lastUpdate to current ms
        var nowMs = Date.now();
        var nowMsHi = Math.floor(nowMs / 0x100000000);
        var nowMsLo = nowMs >>> 0;
        srProto.add(0x18).writeU64(BigInt(nowMs));

        // Read back to verify
        var verify = [];
        var arrCheck = srRf.add(0x10).readPointer();
        var countCheck = srRf.add(0x18).readS32();
        for (var i = 0; i < countCheck; i++) {
            var p = arrCheck.add(0x20 + i*8).readPointer();
            verify.push({day: p.add(0x10).readU32(), dur: p.add(0x14).readU32()});
        }

        // Now trigger ReadNewSleepLogs to make PoGo process+submit
        var gi = null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
        var ssCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Sleep'), Memory.allocUtf8String('SleepService'));
        var rnsl = cMN(ssCls, Memory.allocUtf8String('ReadNewSleepLogs'), 0);
        var ex2 = Memory.alloc(Process.pointerSize); ex2.writePointer(ptr(0));
        var ret = rI(rnsl, inst, ptr(0), ex2);
        return {
            verify: verify,
            triggerRet: ret ? ret.toString() : 'null',
            triggerExc: ex2.readPointer().toString()
        };
    },

    readState: function(addr) {
        var inst = ptr(addr);
        var srProto = inst.add(0x48).readPointer();
        if (srProto.isNull()) return {error:'null'};
        var srRf = srProto.add(0x10).readPointer();
        var count = srRf.add(0x18).readS32();
        var arr = srRf.add(0x10).readPointer();
        var records = [];
        for (var i = 0; i < count; i++) {
            var p = arr.add(0x20 + i*8).readPointer();
            records.push({day: p.add(0x10).readU32(), dur: p.add(0x14).readU32(), rewarded: p.add(0x18).readU8()});
        }
        return {count: count, records: records, lastUpdate: srProto.add(0x18).readU64().toString()};
    }
};
"""
sc = sess.create_script(js); sc.load()
print("\n=== BEFORE: ===", flush=True)
print(json.dumps(sc.exports_sync.read_state(sleep_inst), indent=2), flush=True)

# Inject 8 days starting from current_day+1 (where current_day is what server thinks)
# Server has 4 days credited; let's submit days 5-12 (numbered as days-since-2024-01-01 or similar)
# Use day-of-year style: days 130-137 (roughly May 10..17 2026 in DOY)
import datetime
start_day = (datetime.datetime.now() - datetime.datetime(2026,1,1)).days
days_to_inject = list(range(start_day - 7, start_day + 1))  # last 8 days
print(f"\n=== INJECTING days {days_to_inject} ===", flush=True)
r = sc.exports_sync.inject(sleep_inst, days_to_inject)
print(json.dumps(r, indent=2), flush=True)

print("\nWaiting 15s for any RPC submission...", flush=True)
time.sleep(15)

print("\n=== AFTER: ===", flush=True)
print(json.dumps(sc.exports_sync.read_state(sleep_inst), indent=2), flush=True)
sess.detach()

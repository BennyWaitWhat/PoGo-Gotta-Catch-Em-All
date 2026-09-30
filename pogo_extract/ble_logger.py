"""Long-running BLE traffic logger with outbound + inbound hooks.

Logs everything PoGo sends to / receives from PGP. Runs through reconnects + PoGo restarts.
Designed to capture a real sleep session when user does one.
Output: ble_log.json (live updated)
"""
import frida, json, time, subprocess, sys, datetime
sys.stdout.reconfigure(line_buffering=True)
ADB = ['adb','-s','100.98.158.56:5555']
OUT = 'ble_log.json'

INBOUND = {
    'SaveValueChanged': '_ZN3pgp7android21AndroidCharacteristic30nativeSaveValueChangedCallbackEP7_JNIEnvP8_jobjectP11_jbyteArray',
    'ValueChanged': '_ZN3pgp7android21AndroidCharacteristic26nativeValueChangedCallbackEP7_JNIEnvP8_jobjecthhi',
    'ReadComplete': '_ZN3pgp7android21AndroidCharacteristic26nativeReadCompleteCallbackEP7_JNIEnvP8_jobjecthi',
    'WriteComplete': '_ZN3pgp7android21AndroidCharacteristic27nativeWriteCompleteCallbackEP7_JNIEnvP8_jobjecthi',
    'EnableNotify': '_ZN3pgp7android21AndroidCharacteristic26nativeEnableNotifyCallbackEP7_JNIEnvP8_jobjecthi',
}

# Outbound writes (PoGo→PGP) - find PgpClient/Bluetooth driver write methods
# Common patterns: WriteValue, SendMessage

def get_pid():
    try: return int(subprocess.check_output(ADB + ['shell','pidof com.nianticlabs.pokemongo']).decode().strip())
    except: return None

def attach_and_hook():
    pid = get_pid()
    if not pid: return None, None
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Attaching PID {pid}", flush=True)
    # Retry with backoff - frida-gadget needs time to come up after PoGo restart
    for retry in range(15):
        try:
            mgr = frida.get_device_manager()
            d = mgr.add_remote_device('127.0.0.1:27047')
            sess = d.attach(pid)
            break
        except Exception as e:
            if retry == 14: print(f"  attach gave up: {e}", flush=True); return None, None
            print(f"  attach retry {retry+1}/15: {e}", flush=True)
            time.sleep(4)

    js = """
    var captures = [];
    rpc.exports = { fetch: function() { var r = captures.slice(); captures = []; return r; } };

    var mod = Process.findModuleByName('libholoholo.so');
    var addrMap = {};
    mod.enumerateExports().forEach(function(e){ addrMap[e.name] = e.address; });

    function hookSimple(name, sym, paramReader) {
        var addr = addrMap[sym];
        if (!addr) return false;
        Interceptor.attach(addr, {
            onEnter: function(args) {
                var rec = {fn: name, ts: Date.now()};
                try {
                    if (paramReader) paramReader(args, rec);
                } catch(e) { rec.err = e.toString(); }
                captures.push(rec);
            }
        });
        return true;
    }

    var cnt = 0;
    cnt += hookSimple('SaveValueChanged', '_ZN3pgp7android21AndroidCharacteristic30nativeSaveValueChangedCallbackEP7_JNIEnvP8_jobjectP11_jbyteArray',
        function(args, rec) {
            var jniEnv = args[0];
            var jbyteArr = args[2];
            var jniTbl = jniEnv.readPointer();
            var GetArrayLength = jniTbl.add(171*8).readPointer();
            var GetByteArrayElements = jniTbl.add(184*8).readPointer();
            var ReleaseByteArrayElements = jniTbl.add(192*8).readPointer();
            var lenFn = new NativeFunction(GetArrayLength, 'int', ['pointer','pointer']);
            var getFn = new NativeFunction(GetByteArrayElements, 'pointer', ['pointer','pointer','pointer']);
            var relFn = new NativeFunction(ReleaseByteArrayElements, 'void', ['pointer','pointer','pointer','int']);
            var len = lenFn(jniEnv, jbyteArr);
            rec.len = len;
            if (len > 0 && len < 4096) {
                var dataPtr = getFn(jniEnv, jbyteArr, ptr(0));
                if (!dataPtr.isNull()) {
                    var bytes = dataPtr.readByteArray(Math.min(len, 1024));
                    var u8 = new Uint8Array(bytes);
                    var hex = '';
                    for (var j = 0; j < u8.length; j++) hex += ('0'+u8[j].toString(16)).slice(-2);
                    rec.hex = hex;
                    relFn(jniEnv, jbyteArr, dataPtr, 0);
                }
            }
        });
    cnt += hookSimple('ValueChanged', '_ZN3pgp7android21AndroidCharacteristic26nativeValueChangedCallbackEP7_JNIEnvP8_jobjecthhi',
        function(args, rec) {
            rec.handle = args[2].toInt32() & 0xff;
            rec.flags = args[3].toInt32() & 0xff;
            rec.status = args[4].toInt32();
        });
    cnt += hookSimple('ReadComplete', '_ZN3pgp7android21AndroidCharacteristic26nativeReadCompleteCallbackEP7_JNIEnvP8_jobjecthi',
        function(args, rec) {
            rec.handle = args[2].toInt32() & 0xff;
            rec.flags = args[3].toInt32() & 0xff;
            rec.status = args[4].toInt32();
        });
    cnt += hookSimple('WriteComplete', '_ZN3pgp7android21AndroidCharacteristic27nativeWriteCompleteCallbackEP7_JNIEnvP8_jobjecthi',
        function(args, rec) {
            rec.handle = args[2].toInt32() & 0xff;
            rec.flags = args[3].toInt32() & 0xff;
            rec.status = args[4].toInt32();
        });

    // Hook AndroidCharacteristic::WriteValue (the OUTBOUND write from C++ to Java BLE)
    // The mangled name format varies; try the typical mangled prefix
    var writeValueAddr = null;
    for (var sym in addrMap) {
        if (sym.indexOf('AndroidCharacteristic') >= 0 && sym.indexOf('WriteValue') >= 0) {
            writeValueAddr = addrMap[sym]; break;
        }
        if (sym.indexOf('AndroidCharacteristic') >= 0 && sym.indexOf('WriteByteString') >= 0) {
            writeValueAddr = addrMap[sym]; break;
        }
    }
    if (writeValueAddr) {
        Interceptor.attach(writeValueAddr, {
            onEnter: function(args) {
                var rec = {fn: 'WriteValueOut', ts: Date.now(), this: args[0].toString()};
                // arg1 might be std::string or bytes - try to read as ByteString-like (vec of bytes)
                try {
                    var lenAt = args[1].add(8).readU64();
                    if (lenAt > 0n && lenAt < 4096n) {
                        var dataAt = args[1].add(0x10).readPointer();
                        if (!dataAt.isNull()) {
                            var bytes = dataAt.readByteArray(Math.min(Number(lenAt), 256));
                            var u8 = new Uint8Array(bytes);
                            var hex = '';
                            for (var j = 0; j < u8.length; j++) hex += ('0'+u8[j].toString(16)).slice(-2);
                            rec.hex = hex;
                        }
                    }
                } catch(e) { rec.err = e.toString(); }
                captures.push(rec);
            }
        });
        cnt++;
    }

    send({type:'h', msg: 'Hooked '+cnt+' methods, writeValueAddr='+(writeValueAddr ? writeValueAddr.toString() : 'NOT_FOUND')});
    """
    sc = sess.create_script(js)
    def on(m, data):
        p = m.get('payload', {})
        if isinstance(p, dict) and 'msg' in p: print(f"  [{datetime.datetime.now().strftime('%H:%M:%S')}] {p['msg']}", flush=True)
    sc.on('message', on)
    sc.load()
    return sess, sc

# main loop
print(f"Started: {datetime.datetime.now()}", flush=True)
all_captures = []
last_pid = None
sess = None
sc = None
start = time.time()
TIMEOUT = 4 * 3600

try:
    while time.time() - start < TIMEOUT:
        cur = get_pid()
        if cur != last_pid or sc is None:
            if sess:
                try: sess.detach()
                except: pass
            try:
                sess, sc = attach_and_hook()
            except Exception as e:
                print(f"  attach failed: {e}, will retry", flush=True)
                sess, sc = None, None
                time.sleep(5)
                continue
            last_pid = cur
        if sc:
            try:
                fresh = sc.exports_sync.fetch()
                if fresh:
                    all_captures.extend(fresh)
                    for c in fresh:
                        kind = c.get('fn','?')
                        info = ''
                        if 'hex' in c: info = f" len={c.get('len','?')} hex={c['hex'][:60]}"
                        elif 'handle' in c: info = f" handle=0x{c['handle']:02x} flags=0x{c['flags']:02x} status={c['status']}"
                        print(f"  [{datetime.datetime.now().strftime('%H:%M:%S')}] {kind}{info}", flush=True)
                    with open(OUT,'w') as f:
                        json.dump(all_captures, f, indent=2)
            except Exception as e:
                print(f"  fetch err: {e}", flush=True)
                last_pid = None
                sess = None
        time.sleep(2)
except KeyboardInterrupt:
    print(f"\nStopped. Saving {len(all_captures)} captures.", flush=True)
finally:
    with open(OUT,'w') as f: json.dump(all_captures, f, indent=2)
    print(f"\nFinal: {len(all_captures)} captures in {OUT}", flush=True)

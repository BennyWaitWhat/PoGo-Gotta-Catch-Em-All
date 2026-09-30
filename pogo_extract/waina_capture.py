"""Long-running hook on native WAINA pipeline. Captures everything to waina_capture.json.
Survives multiple PoGo restarts by re-attaching."""
import frida, json, time, subprocess, sys, datetime
sys.stdout.reconfigure(line_buffering=True)
ADB = ['adb','-s','100.98.158.56:5555']
OUT = 'waina_capture.json'

NATIVE_HOOKS = {
    'serialize': '_ZNK27WainaSubmitSleepDataRequest18_InternalSerializeEPhPN6google8protobuf2io19EpsCopyOutputStreamE',
    'postProcessLog': '_ZNK3pgp5sfida19WainaSleepLogRecord14PostProcessLogEv',
    'emplaceBack': '_ZNSt6__ndk16vectorIN3pgp5sfida24WainaSleepLogRecordEntryENS_9allocatorIS3_EEE12emplace_backIJRNS2_15WainaSleepStateERjEEERS3_DpOT_',
    'handleRpcResponse': '_ZN3pgp5sfida6Module17HandleRpcResponseENSt6__ndk112basic_stringIcNS2_11char_traitsIcEENS2_9allocatorIcEEEEN3nia3api10background10RpcManager6StatusENS2_8functionIFvvEEE',
    # Bonus: SfidaCaptureRequest serialize - might catch other PGP traffic
    'wainaResponseParse': '_ZN28WainaSubmitSleepDataResponse14_InternalParseEPKcPN6google8protobuf8internal12ParseContextE',
    # WainaSleepLogRecord state read
    'wainaPostprocLog': '_ZNK3pgp5sfida19WainaSleepLogRecord14PostProcessLogEv',
}

def get_pid():
    try: return int(subprocess.check_output(ADB + ['shell','pidof com.nianticlabs.pokemongo']).decode().strip())
    except: return None

def attach_and_hook():
    pid = get_pid()
    if not pid: return None, None
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Attaching to PoGo PID {pid}", flush=True)
    mgr = frida.get_device_manager()
    d = mgr.add_remote_device('127.0.0.1:27047')
    sess = d.attach(pid)

    js = """
    var captures = [];
    var hookedAddrs = {};
    function init(addrMap) {
        for (var name in addrMap) {
            var addr = ptr(addrMap[name]);
            if (addr.isNull()) continue;
            (function(n, a) {
                Interceptor.attach(a, {
                    onEnter: function(args) {
                        var entry = {when:'enter', name: n, ts: Date.now()};
                        try {
                            entry.this = args[0].toString();
                            // Read first 0x40 bytes of `this` for state introspection
                            var bytes = [];
                            for (var off = 0; off < 0x40; off += 8) {
                                try { bytes.push({off:off, val: args[0].add(off).readPointer().toString()}); } catch(e) {}
                            }
                            entry.thisBytes = bytes;
                            // For serialize: args[1] is output buffer, args[2] is EpsCopyOutputStream
                            if (n === 'serialize') {
                                entry.outBuf = args[1].toString();
                                entry.outStream = args[2].toString();
                            }
                            // For emplaceBack: args[1]=&state, args[2]=&uint
                            if (n === 'emplaceBack') {
                                entry.statePtr = args[1].toString();
                                try {
                                    entry.uintVal = args[2].readU32();
                                    var stateBytes = [];
                                    for (var off = 0; off < 0x40; off += 8) {
                                        try { stateBytes.push({off:off, val: args[1].add(off).readPointer().toString()}); } catch(e) {}
                                    }
                                    entry.stateBytes = stateBytes;
                                } catch(e) {}
                            }
                            // For handleRpcResponse: args[1]=string, args[2]=status, args[3]=callback
                            if (n === 'handleRpcResponse') {
                                try {
                                    // The string param - C++ std::string (basic_string)
                                    var strPtr = args[1];
                                    // SSO: bytes 0-22 are inline if small; else heap ptr at +0x10
                                    var firstByte = strPtr.readU8();
                                    if (firstByte & 1) {
                                        // long string mode
                                        var size = strPtr.add(8).readU64();
                                        var data = strPtr.add(0x10).readPointer();
                                        entry.rpcMethod = data.readUtf8String(Number(size));
                                    } else {
                                        // short string mode (SSO)
                                        var size = firstByte >> 1;
                                        var chars = [];
                                        for (var i = 0; i < size && i < 22; i++) chars.push(String.fromCharCode(strPtr.add(1+i).readU8()));
                                        entry.rpcMethod = chars.join('');
                                    }
                                } catch(e) { entry.strErr = e.toString(); }
                                entry.statusVal = args[2].toInt32();
                            }
                        } catch(e) { entry.err = e.toString(); }
                        captures.push(entry);
                        send({type:'h', msg: n+' fired'});
                    },
                    onLeave: function(retval) {
                        if (n === 'serialize') {
                            // After serialize, the bytes have been written
                            // Read first 256 bytes from outBuf to see the wire format
                            try {
                                var entry = {when:'leave', name: n, ts: Date.now()};
                                if (retval) entry.ret = retval.toString();
                                captures.push(entry);
                            } catch(e) {}
                        }
                    }
                });
                hookedAddrs[n] = a.toString();
            })(name, addr);
        }
        return hookedAddrs;
    }
    rpc.exports = {
        setup: function(addrMap) { return init(addrMap); },
        fetch: function() { var c = captures.slice(); captures = []; return c; }
    };
    """
    sc = sess.create_script(js)
    received_count = [0]
    def on(m, data):
        p = m.get('payload', {})
        if isinstance(p, dict) and 'msg' in p:
            received_count[0] += 1
            print(f"  [{datetime.datetime.now().strftime('%H:%M:%S')}] FIRE: {p['msg']} (#{received_count[0]})", flush=True)
    sc.on('message', on)
    sc.load()

    # Resolve native addresses
    addr_js = """
    rpc.exports = {
        resolve: function(symbols) {
            var mod = Process.findModuleByName('libholoholo.so');
            var exps = mod.enumerateExports();
            var map = {};
            exps.forEach(function(e){ map[e.name] = e.address.toString(); });
            var out = {};
            for (var name in symbols) {
                if (map[symbols[name]]) out[name] = map[symbols[name]];
            }
            return out;
        }
    };
    """
    rs = sess.create_script(addr_js); rs.load()
    addrs = rs.exports_sync.resolve(NATIVE_HOOKS)
    print(f"  Resolved {len(addrs)}/{len(NATIVE_HOOKS)} symbols", flush=True)
    rs.unload()

    sc.exports_sync.setup(addrs)
    return sess, sc

# --- Main loop ---
print(f"Started: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
print("Will run for up to 4 hours. Hit Ctrl+C to stop and save.", flush=True)
print("Capture written to:", OUT, flush=True)
print(flush=True)

sess = None
sc = None
all_captures = []
last_attach_pid = None
start_time = time.time()
TIMEOUT = 4 * 3600  # 4 hours

try:
    while time.time() - start_time < TIMEOUT:
        cur_pid = get_pid()
        if cur_pid != last_attach_pid:
            if sess:
                try: sess.detach()
                except: pass
                sess = None
            sess, sc = attach_and_hook()
            last_attach_pid = cur_pid
        if sc:
            try:
                fresh = sc.exports_sync.fetch()
                if fresh:
                    all_captures.extend(fresh)
                    # Save periodically
                    with open(OUT,'w') as f:
                        json.dump({'pid_lineage': last_attach_pid, 'captures': all_captures}, f, indent=2, default=str)
            except Exception as e:
                print(f"  fetch error: {e} — will reattach", flush=True)
                sess = None
                last_attach_pid = None
        time.sleep(2)
except KeyboardInterrupt:
    print("\nInterrupted. Saving final state...", flush=True)
finally:
    with open(OUT,'w') as f:
        json.dump({'pid_lineage': last_attach_pid, 'captures': all_captures}, f, indent=2, default=str)
    print(f"\nTotal captures: {len(all_captures)}", flush=True)
    print(f"Saved to {OUT}", flush=True)
    if sess:
        try: sess.detach()
        except: pass

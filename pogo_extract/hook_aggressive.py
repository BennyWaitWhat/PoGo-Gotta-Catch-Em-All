"""More aggressive hooking: scan for 'PvP Rank:' string allocations from anywhere."""
import frida, subprocess, time

adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    hookEverything: function() {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {};
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });

        // Hook every string-creating il2cpp function
        var fnNames = ['il2cpp_string_new', 'il2cpp_string_new_len', 'il2cpp_string_new_utf16', 'il2cpp_string_new_wrapper'];
        var hooked = [];
        fnNames.forEach(function(fn) {
            if (exp[fn]) {
                Interceptor.attach(exp[fn], {
                    onEnter: function(args) { this.fn = fn; this.input = args[0]; this.len = args[1] ? args[1].toInt32() : -1; },
                    onLeave: function(retval) {
                        try {
                            var s = null;
                            if (this.fn === 'il2cpp_string_new' || this.fn === 'il2cpp_string_new_wrapper') {
                                s = this.input.readCString();
                            } else if (this.fn === 'il2cpp_string_new_len') {
                                if (this.len > 0 && this.len < 500) s = this.input.readUtf8String(this.len);
                            } else if (this.fn === 'il2cpp_string_new_utf16') {
                                if (this.len > 0 && this.len < 500) {
                                    var chars = [];
                                    for (var i = 0; i < this.len; i++) chars.push(String.fromCharCode(this.input.add(i*2).readU16()));
                                    s = chars.join('');
                                }
                            }
                            if (s && /PvP|Rank|League|Pokemod/i.test(s)) {
                                send({type:'s', msg: this.fn + ': ' + s});
                            }
                        } catch(e) {}
                    }
                });
                hooked.push(fn);
            }
        });

        // Hook libc malloc - look for buffer that might be assembled before string conversion
        // Also hook raw mem allocations - skip, too noisy

        // Hook System.String constructors via mscorlib
        try {
            var dG = new NativeFunction(exp.il2cpp_domain_get,'pointer',[]);
            var dGA = new NativeFunction(exp.il2cpp_domain_get_assemblies,'pointer',['pointer','pointer']);
            var aGI = new NativeFunction(exp.il2cpp_assembly_get_image,'pointer',['pointer']);
            var iGN = new NativeFunction(exp.il2cpp_image_get_name,'pointer',['pointer']);
            var cFN = new NativeFunction(exp.il2cpp_class_from_name,'pointer',['pointer','pointer','pointer']);
            var cGM = new NativeFunction(exp.il2cpp_class_get_methods,'pointer',['pointer','pointer']);
            var mGN = new NativeFunction(exp.il2cpp_method_get_name,'pointer',['pointer']);

            var dom = dG();
            var sp = Memory.alloc(4);
            var asms = dGA(dom, sp); var na = sp.readS32();
            var mscor = null;
            for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='mscorlib.dll'){ mscor=i; break; } }
            if (mscor) {
                var stringCls = cFN(mscor, Memory.allocUtf8String('System'), Memory.allocUtf8String('String'));
                var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
                var m;
                while ((m = cGM(stringCls, iter)) && !m.isNull()) {
                    try {
                        var nm = mGN(m).readCString();
                        if (nm === 'Concat' || nm === 'Format' || nm === 'CreateString') {
                            var addr = m.readPointer();
                            if (addr.isNull()) continue;
                            Interceptor.attach(addr, {
                                onLeave: function(retval) {
                                    try {
                                        if (retval.isNull()) return;
                                        var len = retval.add(0x10).readS32();
                                        if (len <= 0 || len > 200) return;
                                        var chars = [];
                                        for (var ci = 0; ci < len; ci++) chars.push(String.fromCharCode(retval.add(0x14 + ci*2).readU16()));
                                        var s = chars.join('');
                                        if (/PvP|Rank|League|Pokemod/i.test(s)) {
                                            send({type:'sf', msg: nm + ': ' + s});
                                        }
                                    } catch(e) {}
                                }
                            });
                            hooked.push('String.' + nm);
                        }
                    } catch(e) {}
                }
            }
        } catch(e) {}

        return {hooked: hooked};
    },

    /* Re-scan for rendered PvP Rank strings now */
    rescanRendered: function() {
        var pattern = '50 76 50 20 52 61 6e 6b 3a 20'; // "PvP Rank: "
        var hits = [];
        var ranges = Process.enumerateRanges('r--');
        for (var r = 0; r < ranges.length; r++) {
            if (ranges[r].size > 100*1024*1024) continue;
            try {
                Memory.scanSync(ranges[r].base, ranges[r].size, pattern).forEach(function(m){
                    // Read 64 bytes around it to see if it's a rendered string
                    try {
                        var b = m.address.readByteArray(64);
                        var u8 = new Uint8Array(b);
                        var s = '';
                        for (var i = 0; i < u8.length; i++) {
                            if (u8[i] >= 32 && u8[i] < 127) s += String.fromCharCode(u8[i]);
                            else if (u8[i] === 0) break;
                            else s += '.';
                        }
                        hits.push({addr: m.address.toString(), str: s});
                    } catch(e) {}
                });
            } catch(e) {}
        }
        return hits;
    }
};
"""
script = sess.create_script(js)
captured = []
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p:
        captured.append(p['msg'])
        print(f"  [{p.get('type','?')}] {p['msg']}")
script.on('message', on)
script.load()

print("Hooking everything...")
print(script.exports_sync.hook_everything())

print("\n>>> NOW: open PoGo, tap a SPECIFIC pokemon to view its detail page.")
print(">>> Pokemod's 'PvP Rank: X' should appear at the bottom.")
print(">>> Capturing for 60s...")
for i in range(12):
    time.sleep(5)
    print(f"  ... {(i+1)*5}/60s, captured {len(captured)} strings so far")

print(f"\n=== Total captured: {len(captured)} ===")
for c in captured:
    print(f"  {c}")

# Also re-scan for PvP Rank strings now (after user viewed pokemon)
print("\n=== Re-scanning memory for 'PvP Rank: ' strings ===")
hits = script.exports_sync.rescan_rendered()
for h in hits[:20]:
    print(f"  {h['addr']}: {h['str']}")

sess.detach()

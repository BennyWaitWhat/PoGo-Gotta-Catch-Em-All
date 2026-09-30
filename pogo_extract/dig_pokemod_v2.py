"""Examine PvP Rank string contexts."""
import frida, subprocess

adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    examineRange: function(addr, len) {
        var p = ptr(addr);
        try {
            var bytes = p.readByteArray(len);
            var u8 = new Uint8Array(bytes);
            var ascii = '';
            for (var i = 0; i < u8.length; i++) {
                ascii += (u8[i] >= 32 && u8[i] < 127) ? String.fromCharCode(u8[i]) : '.';
            }
            return {ascii: ascii};
        } catch(e) { return {err: e.message}; }
    },
    findStrings: function(queries) {
        var hits = {};
        var ranges = Process.enumerateRanges('r--');
        for (var q = 0; q < queries.length; q++) {
            var qstr = queries[q];
            var pattern = '';
            for (var i = 0; i < qstr.length; i++) {
                pattern += ('0' + qstr.charCodeAt(i).toString(16)).slice(-2) + ' ';
            }
            var samples = [];
            for (var r = 0; r < ranges.length && samples.length < 10; r++) {
                if (ranges[r].size > 100*1024*1024) continue;
                try {
                    Memory.scanSync(ranges[r].base, ranges[r].size, pattern.trim()).forEach(function(m){
                        if (samples.length < 10) samples.push(m.address.toString());
                    });
                } catch(e) {}
            }
            hits[qstr] = samples;
        }
        return hits;
    },
    /* Hook IL2CPP string allocation, capture any strings related to Rank/PvP */
    captureStrings: function() {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {};
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        if (!exp.il2cpp_string_new) return {ok:false, err:'no il2cpp_string_new'};
        var captured = [];
        Interceptor.attach(exp.il2cpp_string_new, {
            onEnter: function(args) { this.input = args[0]; },
            onLeave: function(retval) {
                try {
                    var s = this.input.readCString();
                    if (s && s.length < 200 && /Rank|League|Pvp|PvP/i.test(s)) {
                        send({type:'s', msg: s + ' -> ' + retval.toString()});
                    }
                } catch(e) {}
            }
        });
        return {ok: true, msg: 'hooked - waiting for game to render rank strings'};
    },
    /* Hook string concat / format functions which may produce 'PvP Rank: 5' */
    captureFormatStrings: function() {
        var captured = 0;
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {};
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        // String.Concat, String.Format - find them via class lookup
        var dG = new NativeFunction(exp.il2cpp_domain_get,'pointer',[]);
        var dGA = new NativeFunction(exp.il2cpp_domain_get_assemblies,'pointer',['pointer','pointer']);
        var aGI = new NativeFunction(exp.il2cpp_assembly_get_image,'pointer',['pointer']);
        var iGN = new NativeFunction(exp.il2cpp_image_get_name,'pointer',['pointer']);
        var cFN = new NativeFunction(exp.il2cpp_class_from_name,'pointer',['pointer','pointer','pointer']);
        var cGM = new NativeFunction(exp.il2cpp_class_get_methods,'pointer',['pointer','pointer']);
        var mGN = new NativeFunction(exp.il2cpp_method_get_name,'pointer',['pointer']);
        var mGPC = new NativeFunction(exp.il2cpp_method_get_param_count,'int',['pointer']);
        var dom = dG();
        var sp = Memory.alloc(4);
        var asms = dGA(dom, sp); var na = sp.readS32();
        var mscorlib = null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='mscorlib.dll'){ mscorlib=i; break; } }
        if (!mscorlib) return {ok:false, err:'no mscorlib'};
        var stringCls = cFN(mscorlib, Memory.allocUtf8String('System'), Memory.allocUtf8String('String'));
        // Hook .ctor or all that contain a format-like signature
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, hooked = 0;
        while ((m = cGM(stringCls, iter)) && !m.isNull()) {
            try {
                var nm = mGN(m).readCString();
                if (nm === 'Concat' || nm === 'Format') {
                    var native = m.readPointer();
                    if (!native.isNull()) {
                        Interceptor.attach(native, {
                            onLeave: function(retval) {
                                try {
                                    if (retval.isNull()) return;
                                    // String length at +0x10 (.NET string layout)
                                    var len = retval.add(0x10).readS32();
                                    if (len <= 0 || len > 100) return;
                                    var chars = [];
                                    for (var ci = 0; ci < len; ci++) {
                                        chars.push(String.fromCharCode(retval.add(0x14 + ci*2).readU16()));
                                    }
                                    var s = chars.join('');
                                    if (/Rank|League/.test(s)) {
                                        send({type:'fmt', msg: s});
                                    }
                                } catch(e) {}
                            }
                        });
                        hooked++;
                    }
                }
            } catch(e) {}
        }
        return {ok:true, hooked: hooked};
    }
};
"""
script = sess.create_script(js)
captures = []
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p:
        captures.append(p['msg'])
        if len(captures) <= 30:
            print(f"  [hook] {p['msg']}")
script.on('message', on)
script.load()

# Look at all PvP Rank hits
print('=== Examining each "PvP Rank: " hit context ===')
hits = ['0x736999c738', '0x7369af9fb0', '0x736bfd7b10', '0x736d498fea']
for h in hits:
    print(f"\n--- {h} ---")
    addr = int(h, 16)
    m = script.exports_sync.examine_range(hex(addr - 16), 200)
    if 'ascii' in m:
        print(m['ascii'])

# Search broader for related strings
print('\n=== Searching for related strings ===')
queries = ['{rank}', 'RankFormat', 'PvP Rank: 1', 'PvP Rank: 2', 'PvP Rank: 100', 'PvP Rank: 50',
           'GreatLeague', 'UltraLeague', '\xa3 ', 'rank:', 'GL Rank', 'UL Rank',
           'pvpRanks', 'rankCache', 'leagueCache']
hits2 = script.exports_sync.find_strings(queries)
for q, samples in hits2.items():
    if samples:
        print(f"  {q!r:30s} {len(samples)} hits  {samples[:3]}")

# Hook string format - get user to scroll storage to capture more rank strings being rendered
print('\n=== Hooking String.Concat/Format ===')
import time
hook_res = script.exports_sync.capture_format_strings()
print(f'  hook result: {hook_res}')
print('\n>>> Open PoGo storage and scroll - I will capture format calls for 30 seconds...')
time.sleep(30)

print(f'\n=== Captured {len(captures)} rank/league format strings ===')
for c in captures[:50]:
    print(f'  {c}')
sess.detach()

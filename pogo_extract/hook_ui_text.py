"""Hook Unity UI Text setters to capture Pokemod's rank rendering.

When user opens a pokemon detail page, Pokemod injects a 'PvP Rank: X' text
into the UI. We hook ALL setters that take a string to find which one Pokemod
uses, capturing the rank value + proto pointer in same call stack.
"""
import frida, subprocess, time

adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
var captured = [];
var fns = {};

function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {};
    il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
    fns.dG = bind('il2cpp_domain_get','pointer',[]);
    fns.dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    fns.aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
    fns.iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
    fns.cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    fns.cGM = bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    fns.mGN = bind('il2cpp_method_get_name','pointer',['pointer']);
    fns.tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    fns.sN_get = bind('il2cpp_string_new','pointer',['pointer']);
}

function readDotNetString(strPtr) {
    try {
        if (strPtr.isNull()) return null;
        var len = strPtr.add(0x10).readS32();
        if (len <= 0 || len > 500) return null;
        var chars = [];
        for (var i = 0; i < len; i++) {
            chars.push(String.fromCharCode(strPtr.add(0x14 + i*2).readU16()));
        }
        return chars.join('');
    } catch(e) { return null; }
}

rpc.exports = {
    /* Hook IL2CPP string allocation - capture any string containing 'Rank' */
    hookStringAlloc: function() {
        init();
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {};
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        // Hook il2cpp_string_new (UTF-8 input) and il2cpp_string_new_utf16
        Interceptor.attach(exp.il2cpp_string_new, {
            onEnter: function(args) { this.input = args[0]; },
            onLeave: function(retval) {
                try {
                    var s = this.input.readCString();
                    if (s && /Rank|rank|League|league|Pvp|PvP/.test(s)) {
                        send({type:'sa', msg: s + ' -> ' + retval.toString()});
                    }
                } catch(e) {}
            }
        });
        if (exp.il2cpp_string_new_utf16) {
            Interceptor.attach(exp.il2cpp_string_new_utf16, {
                onEnter: function(args) { this.input = args[0]; this.len = args[1].toInt32(); },
                onLeave: function(retval) {
                    try {
                        if (this.len <= 0 || this.len > 500) return;
                        var chars = [];
                        for (var i = 0; i < this.len; i++) {
                            chars.push(String.fromCharCode(this.input.add(i*2).readU16()));
                        }
                        var s = chars.join('');
                        if (/Rank|rank|League|league/.test(s)) {
                            send({type:'sa', msg: 'utf16: ' + s + ' -> ' + retval.toString()});
                        }
                    } catch(e) {}
                }
            });
        }
        // Also hook il2cpp_string_new_len
        if (exp.il2cpp_string_new_len) {
            Interceptor.attach(exp.il2cpp_string_new_len, {
                onEnter: function(args) {
                    this.input = args[0];
                    this.len = args[1].toInt32();
                },
                onLeave: function(retval) {
                    try {
                        if (this.len <= 0 || this.len > 500) return;
                        var s = this.input.readUtf8String(this.len);
                        if (s && /Rank|rank|League|league/.test(s)) {
                            send({type:'sa', msg: 'len: ' + s + ' -> ' + retval.toString()});
                        }
                    } catch(e) {}
                }
            });
        }
        return {ok:true, msg:'hooked'};
    },

    /* Hook TMP_Text and Text setters */
    hookTmpText: function() {
        init();
        var sp = Memory.alloc(4);
        var asms = fns.dGA(fns.dG(), sp);
        var na = sp.readS32();
        var unityImg = null, tmpImg = null;
        for (var a=0;a<na;a++){
            var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
            var nm = fns.iGN(img).readCString();
            if (nm === 'UnityEngine.UI.dll') unityImg = img;
            if (nm === 'Unity.TextMeshPro.dll') tmpImg = img;
        }
        var hooked = 0;
        function hookTextSetter(img, ns, cls, propName) {
            try {
                var clsP = fns.cFN(img, Memory.allocUtf8String(ns), Memory.allocUtf8String(cls));
                if (!clsP || clsP.isNull()) return;
                var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
                var m;
                while ((m = fns.cGM(clsP, iter)) && !m.isNull()) {
                    var nm = fns.mGN(m).readCString();
                    if (nm === 'set_text' || nm === propName) {
                        var addr = m.readPointer();
                        if (addr.isNull()) continue;
                        Interceptor.attach(addr, {
                            onEnter: function(args) {
                                try {
                                    var s = readDotNetString(args[1]);
                                    if (s && /Rank|rank|League|league/.test(s)) {
                                        send({type:'ut', msg: cls + '.set_text: ' + s});
                                    }
                                } catch(e) {}
                            }
                        });
                        hooked++;
                    }
                }
            } catch(e) {}
        }
        function readDotNetString(strPtr) {
            try {
                if (strPtr.isNull()) return null;
                var len = strPtr.add(0x10).readS32();
                if (len <= 0 || len > 500) return null;
                var chars = [];
                for (var i = 0; i < len; i++) {
                    chars.push(String.fromCharCode(strPtr.add(0x14 + i*2).readU16()));
                }
                return chars.join('');
            } catch(e) { return null; }
        }
        if (unityImg) {
            hookTextSetter(unityImg, 'UnityEngine.UI', 'Text', 'set_text');
        }
        if (tmpImg) {
            hookTextSetter(tmpImg, 'TMPro', 'TMP_Text', 'set_text');
            hookTextSetter(tmpImg, 'TMPro', 'TextMeshPro', 'set_text');
            hookTextSetter(tmpImg, 'TMPro', 'TextMeshProUGUI', 'set_text');
        }
        return {ok:true, hooked: hooked};
    }
};
"""
script = sess.create_script(js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p:
        print(f"  [{p.get('type','?')}] {p['msg']}")
script.on('message', on)
script.load()

print("Hooking il2cpp string alloc...")
print(script.exports_sync.hook_string_alloc())
print("\nHooking UI text setters...")
print(script.exports_sync.hook_tmp_text())
print("\n>>> Open PoGo, tap any pokemon to see its detail page (Pokemod renders 'PvP Rank: X' at bottom)")
print(">>> Capturing for 60 seconds...")
time.sleep(60)
print("\nDone. Detaching.")
sess.detach()

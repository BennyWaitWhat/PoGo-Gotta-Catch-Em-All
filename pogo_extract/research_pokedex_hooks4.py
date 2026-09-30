"""Hook all candidate mutators and watch what fires when player catches a Pokemon.

Hooks:
- All PokedexImpl 2p/3p/4p Void methods (yoq-yov + vpv-vpz + etc).
- NianticInventoryCache.HandleInventoryDelta -> log args to identify if Pokedex deltas come through here.
- PokedexCategoryNotificationGuiController.Initialize -> log when a category unlock notification fires.

Run while player catches a fresh pokemon (e.g., spin a stop and catch a wild).
Watch which method actually fires + with what HoloPokemonId.
"""
import frida, json, subprocess, sys, time
sys.stdout.reconfigure(line_buffering=True)
subprocess.run(['adb','connect','100.98.158.56:5555'], capture_output=True)
subprocess.run(['adb','-s','100.98.158.56:5555','forward','tcp:27047','tcp:27047'], capture_output=True)
pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f"PID: {pid}")
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(pid)

# Method ptrs from prior introspection.
# PokedexImpl (Niantic.Holoholo.Internal):
# 2p Void: yoq, yor, yot, you, yov
# (also yos returns bool, not relevant)

# Resolve them dynamically rather than hardcoding ptrs.
js = r"""
var fns={};
var il2cpp=Process.findModuleByName('libil2cpp.so');
var exp={}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name]=e.address; });
function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
fns.dG=bind('il2cpp_domain_get','pointer',[]);
fns.dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
fns.aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']);
fns.iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
fns.cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
fns.cGM=bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
fns.mGN=bind('il2cpp_method_get_name','pointer',['pointer']);
fns.mGPC=bind('il2cpp_method_get_param_count','int',['pointer']);
fns.mGRT=bind('il2cpp_method_get_return_type','pointer',['pointer']);
fns.tGN=bind('il2cpp_type_get_name','pointer',['pointer']);
fns.tA=bind('il2cpp_thread_attach','pointer',['pointer']); fns.tA(fns.dG());

function getImg(name) {
    var sp=Memory.alloc(4); var asms=fns.dGA(fns.dG(),sp); var na=sp.readS32();
    for (var a=0;a<na;a++){ var i=fns.aGI(asms.add(a*Process.pointerSize).readPointer()); if (fns.iGN(i).readCString()===name) return i; }
    return null;
}
function getCls(imgName, ns, name) {
    var img=getImg(imgName);
    if (!img) return null;
    return fns.cFN(img, Memory.allocUtf8String(ns), Memory.allocUtf8String(name));
}
function listMethods(cls) {
    var out=[]; var iter=Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    while ((m=fns.cGM(cls,iter)) && !m.isNull()) {
        try {
            var n=fns.mGN(m).readCString(); var pc=fns.mGPC(m); var r=fns.mGRT(m);
            var rn=''; try{rn=fns.tGN(r).readCString();}catch(e){}
            out.push({name:n, params:pc, ret:rn, ptr:m.readPointer()});
        } catch(e){}
    }
    return out;
}

// Read C# string at ptr (System.String layout: vtable +0x10 len, +0x14 chars utf-16)
function readUtf16(p) {
    if (!p || p.isNull()) return '';
    try {
        var len = p.add(0x10).readS32();
        if (len < 0 || len > 200) return '';
        var s = '';
        for (var i=0;i<len;i++) s += String.fromCharCode(p.add(0x14 + i*2).readU16());
        return s;
    } catch(e) { return '<bad>'; }
}

var hookLog = [];
function logHook(label, args, this_obj, nargs) {
    try {
        var entry = {ts: Date.now(), label: label, this: this_obj ? this_obj.toString() : null, args:[]};
        for (var i=0;i<nargs;i++) {
            var a = args[i];
            entry.args.push(a ? a.toString() : 'null');
        }
        hookLog.push(entry);
        send({type:'hook', e: entry});
    } catch(e) { send({type:'err', msg:e.toString()}); }
}

rpc.exports = {
    hookAll: function() {
        var hookCount = 0;
        // PokedexImpl 2p Void methods
        var pdex = getCls('holo-game.dll', 'Niantic.Holoholo.Internal', 'PokedexImpl');
        if (pdex && !pdex.isNull()) {
            var methods = listMethods(pdex);
            send({type:'status', msg:'PokedexImpl methods: '+methods.length});
            for (var i=0;i<methods.length;i++) {
                var m = methods[i];
                if (m.ret !== 'System.Void') continue;
                if (m.params < 1 || m.params > 4) continue;
                if (m.name === '.ctor' || m.name === '.cctor' || m.name.indexOf('add_') === 0 || m.name.indexOf('remove_') === 0) continue;
                if (m.ptr.isNull()) continue;
                (function(label, p, np) {
                    try {
                        Interceptor.attach(p, {
                            onEnter: function(args) { logHook('PokedexImpl.'+label, args, args[0], np+1); }
                        });
                        hookCount++;
                    } catch(e) { send({type:'err', msg:'hook PokedexImpl.'+label+': '+e.toString()}); }
                })(m.name, m.ptr, m.params);
            }
        }

        // PokedexCollectionService obfuscated mutators
        var pcs = getCls('holo-game.dll', 'Niantic.Holoholo', 'PokedexCollectionService');
        if (pcs && !pcs.isNull()) {
            var methods = listMethods(pcs);
            send({type:'status', msg:'PokedexCollectionService methods: '+methods.length});
            for (var i=0;i<methods.length;i++) {
                var m = methods[i];
                if (m.ret !== 'System.Void') continue;
                if (m.params < 1 || m.params > 4) continue;
                if (m.name === '.ctor' || m.name === '.cctor') continue;
                if (m.ptr.isNull()) continue;
                (function(label, p, np) {
                    try {
                        Interceptor.attach(p, {
                            onEnter: function(args) { logHook('PokedexCollectionSvc.'+label, args, args[0], np+1); }
                        });
                        hookCount++;
                    } catch(e) {}
                })(m.name, m.ptr, m.params);
            }
        }

        // Inventory delta entry point (the platform handler)
        var nic = getCls('holo-game.dll', 'Niantic.Platform', 'NianticInventoryCache`2');
        if (nic && !nic.isNull()) {
            var methods = listMethods(nic);
            send({type:'status', msg:'NianticInventoryCache methods: '+methods.length});
            for (var i=0;i<methods.length;i++) {
                var m = methods[i];
                if (m.name === 'HandleInventoryDelta' || m.name === 'DoInventoryUpdateEvent') {
                    if (m.ptr.isNull()) continue;
                    (function(label, p, np) {
                        try {
                            Interceptor.attach(p, {
                                onEnter: function(args) { logHook('NIC.'+label, args, args[0], np+1); }
                            });
                            hookCount++;
                        } catch(e) {}
                    })(m.name, m.ptr, m.params);
                }
            }
        }

        // Cutscene IsFirstCapture
        var rtc = getCls('holo-game.dll', 'Niantic.Holoholo.Cutscenes', 'RegisterToPokedexCutscene');
        if (rtc && !rtc.isNull()) {
            var methods = listMethods(rtc);
            for (var i=0;i<methods.length;i++) {
                var m = methods[i];
                if (m.name !== 'IsFirstCapture' && m.name !== 'DiscoverPokemonIcon') continue;
                if (m.ptr.isNull()) continue;
                (function(label, p, np) {
                    try {
                        Interceptor.attach(p, {
                            onEnter: function(args) { logHook('RTPC.'+label, args, args[0], np+1); }
                        });
                        hookCount++;
                    } catch(e) {}
                })(m.name, m.ptr, m.params);
            }
        }

        // Category notification gui
        var pcn = getCls('holo-game.dll', 'Niantic.Holoholo', 'PokedexCategoryNotificationGuiController');
        if (pcn && !pcn.isNull()) {
            var methods = listMethods(pcn);
            for (var i=0;i<methods.length;i++) {
                var m = methods[i];
                if (m.name !== 'Initialize') continue;
                if (m.ptr.isNull()) continue;
                (function(label, p, np) {
                    try {
                        Interceptor.attach(p, {
                            onEnter: function(args) { logHook('PCN.'+label, args, args[0], np+1); }
                        });
                        hookCount++;
                    } catch(e) {}
                })(m.name, m.ptr, m.params);
            }
        }

        return {hooks: hookCount};
    },
    flush: function() { var c = hookLog.slice(); hookLog = []; return c; }
};
"""
sc = sess.create_script(js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict):
        t = p.get('type')
        if t == 'status': print(f"  [status] {p.get('msg')}")
        elif t == 'err':  print(f"  [ERR] {p.get('msg')}")
        elif t == 'hook':
            e = p.get('e', {})
            print(f"  [{time.strftime('%H:%M:%S')}] HOOK {e.get('label')}  this={e.get('this')}  args={e.get('args')}")
sc.on('message', on)
sc.load()
r = sc.exports_sync.hook_all()
print(f"\nHooks installed: {r}")
print("\nWaiting 60s. CATCH a pokemon NOW (preferably a brand-new species, costume, lucky, etc).")
print("CTRL+C to exit early.\n")
try:
    for i in range(60):
        time.sleep(1)
except KeyboardInterrupt:
    print("\nInterrupted")
sess.detach()

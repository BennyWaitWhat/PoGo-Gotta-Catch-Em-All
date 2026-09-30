"""Research script: enumerate PokedexImpl + related classes for hookable methods.

Findings target:
- All methods on PokedexImpl (catch the AddOrUpdate-style mutators)
- All fields on PokedexImpl (find PokedexUpdated event/delegate field, like PokemonBagUpdated)
- Find IPokedex interface
- Find any *PokedexNotifier* / *PokedexService* class
- Find RPC-handler classes that process catch/evolve responses
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

js = r"""
var fns={}, gi=null, allImgs=[];
function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
    fns.dG = bind('il2cpp_domain_get','pointer',[]);
    fns.dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    fns.aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
    fns.iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
    fns.iGCC = bind('il2cpp_image_get_class_count','int',['pointer']);
    fns.iGC = bind('il2cpp_image_get_class','pointer',['pointer','int']);
    fns.cGN = bind('il2cpp_class_get_name','pointer',['pointer']);
    fns.cGNS = bind('il2cpp_class_get_namespace','pointer',['pointer']);
    fns.cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    fns.cGM = bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    fns.mGN = bind('il2cpp_method_get_name','pointer',['pointer']);
    fns.mGPC = bind('il2cpp_method_get_param_count','int',['pointer']);
    fns.mGRT = bind('il2cpp_method_get_return_type','pointer',['pointer']);
    fns.cGF = bind('il2cpp_class_get_fields','pointer',['pointer','pointer']);
    fns.fGN = bind('il2cpp_field_get_name','pointer',['pointer']);
    fns.fGO = bind('il2cpp_field_get_offset','int',['pointer']);
    fns.fGT = bind('il2cpp_field_get_type','pointer',['pointer']);
    fns.tGN = bind('il2cpp_type_get_name','pointer',['pointer']);
    fns.tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    fns.cGI = bind('il2cpp_class_get_interfaces','pointer',['pointer','pointer']);
    fns.cGP = bind('il2cpp_class_get_parent','pointer',['pointer']);
    fns.tA(fns.dG());
    var sp = Memory.alloc(4); var asms = fns.dGA(fns.dG(), sp); var na = sp.readS32();
    for (var a=0;a<na;a++){
        var i = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
        var n = fns.iGN(i).readCString();
        allImgs.push({img: i, name: n});
    }
    return {numImages: allImgs.length};
}

function dumpMethods(cls) {
    var out = [];
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    while ((m = fns.cGM(cls, iter)) && !m.isNull()) {
        try {
            var name = fns.mGN(m).readCString();
            var pc = fns.mGPC(m);
            var rt = fns.mGRT(m);
            var rtn = '';
            try { rtn = fns.tGN(rt).readCString(); } catch(e) {}
            var ptrAddr = m.readPointer();
            out.push({name: name, params: pc, ret: rtn, ptr: ptrAddr.toString()});
        } catch(e) {}
    }
    return out;
}

function dumpFields(cls) {
    var out = [];
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var f;
    while ((f = fns.cGF(cls, iter)) && !f.isNull()) {
        try {
            var name = fns.fGN(f).readCString();
            var off = fns.fGO(f);
            var t = fns.fGT(f);
            var tn = '';
            try { tn = fns.tGN(t).readCString(); } catch(e) {}
            out.push({name: name, offset: off, type: tn});
        } catch(e) {}
    }
    return out;
}

rpc.exports = {
    init: init,
    findClasses: function(needles) {
        var hits = [];
        for (var ai = 0; ai < allImgs.length; ai++) {
            var img = allImgs[ai];
            if (img.name !== 'holo-game.dll' && img.name !== 'holo-protos.dll' && img.name !== 'Assembly-CSharp.dll') continue;
            var cc = fns.iGCC(img.img);
            for (var ci = 0; ci < cc; ci++) {
                var cls = fns.iGC(img.img, ci);
                if (!cls || cls.isNull()) continue;
                var name = fns.cGN(cls).readCString();
                var ns = '';
                try { ns = fns.cGNS(cls).readCString(); } catch(e) {}
                for (var ni = 0; ni < needles.length; ni++) {
                    if (name.toLowerCase().indexOf(needles[ni].toLowerCase()) >= 0) {
                        hits.push({img: img.name, ns: ns, name: name, cls: cls.toString()});
                        break;
                    }
                }
            }
        }
        return hits;
    },
    introspect: function(ns, name) {
        for (var ai = 0; ai < allImgs.length; ai++) {
            var img = allImgs[ai];
            var cls = fns.cFN(img.img, Memory.allocUtf8String(ns), Memory.allocUtf8String(name));
            if (!cls.isNull()) {
                var fields = dumpFields(cls);
                var methods = dumpMethods(cls);
                var parent = fns.cGP(cls);
                var parentName = '';
                if (parent && !parent.isNull()) {
                    var pn = fns.cGN(parent).readCString();
                    var pns = '';
                    try { pns = fns.cGNS(parent).readCString(); } catch(e) {}
                    parentName = pns + '.' + pn;
                }
                return {img: img.name, ns: ns, name: name, cls: cls.toString(), parent: parentName,
                        fields: fields, methods: methods};
            }
        }
        return null;
    }
};
init();
"""
sc = sess.create_script(js); sc.load()
init_r = sc.exports_sync.init()
print(f"Init: {init_r}")

print("\n=== STAGE 1: Find Pokedex* classes ===")
needles = ['Pokedex', 'IDexUpdate', 'DexUpdated', 'DexNotifier', 'DexService']
hits = sc.exports_sync.find_classes(needles)
for h in hits[:200]:
    print(f"  {h['img']:20s}  {h['ns']:50s}  {h['name']}")
print(f"\n  total: {len(hits)} classes\n")

# Save full results
with open('research_pokedex_hits.json', 'w') as f:
    json.dump(hits, f, indent=2)

print("\n=== STAGE 2: Introspect known Pokedex classes ===")
candidates = [
    ('Niantic.Holoholo.Internal', 'PokedexImpl'),
    ('Niantic.Holoholo.Internal', 'PokedexService'),
    ('Niantic.Holoholo.Services', 'PokedexService'),
    ('Niantic.Holoholo', 'PokedexService'),
    ('Niantic.Holoholo', 'IPokedex'),
    ('Niantic.Holoholo.Internal', 'IPokedex'),
    ('Niantic.Holoholo.Services', 'IPokedexService'),
]
introspected = {}
for ns, n in candidates:
    r = sc.exports_sync.introspect(ns, n)
    if r:
        print(f"\n{ns}.{n}  ({r['img']}, parent={r['parent']})")
        print(f"  Fields ({len(r['fields'])}):")
        for f in r['fields'][:80]:
            print(f"    +0x{f['offset']:04x}  {f['name']:35s}  {f['type']}")
        print(f"  Methods ({len(r['methods'])}):")
        for m in r['methods'][:100]:
            print(f"    [{m['params']}p {m['ret']}] {m['name']}")
        introspected[f"{ns}.{n}"] = r

# Also introspect anything found in stage 1 with PokedexImpl-like names
hit_classes = set()
for h in hits:
    qn = f"{h['ns']}.{h['name']}"
    if qn not in introspected and (h['name'].lower().endswith('impl') or 'pokedex' in h['name'].lower()):
        hit_classes.add((h['ns'], h['name']))

for ns, n in list(hit_classes)[:30]:
    qn = f"{ns}.{n}"
    if qn in introspected: continue
    r = sc.exports_sync.introspect(ns, n)
    if r:
        print(f"\n{ns}.{n}  ({r['img']}, parent={r['parent']})")
        print(f"  Fields ({len(r['fields'])}):")
        for f in r['fields'][:50]:
            print(f"    +0x{f['offset']:04x}  {f['name']:35s}  {f['type']}")
        print(f"  Methods ({len(r['methods'])}):")
        for m in r['methods'][:60]:
            print(f"    [{m['params']}p {m['ret']}] {m['name']}")
        introspected[qn] = r

with open('research_pokedex_introspect.json', 'w') as f:
    json.dump(introspected, f, indent=2)
print(f"\nSaved {len(introspected)} class introspections.")
sess.detach()

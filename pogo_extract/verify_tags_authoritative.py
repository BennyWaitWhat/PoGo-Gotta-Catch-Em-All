"""Authoritative tag verification: enumerate every tag via TaggingRpcService bindings.

Uses GetCachedTagToPokemonBindingForIndex(idx) for each idx in [0..NumberOfTags),
which returns server-state-backed TagToPokemonBinding -> List<PokemonProto*>.count.
"""
import frida, json, time

mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(22409)
script = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())

captured = []
def on(m, data):
    p = m.get("payload",{})
    if isinstance(p,dict):
        msg = p.get("msg","")
        if "captured this @" in msg:
            captured.append(msg.split("@")[1].strip().split(" ")[0])
script.on("message", on)
script.load()
script.exports_sync.init_status()
script.exports_sync.hook_for_real_instance(180)
print(">>> OPEN PoGo's tag manager (filter dropdown -> tap a tag) to trigger hook (180s)...")
real = None
for i in range(180):
    time.sleep(1)
    cap = script.exports_sync.get_captured()
    if cap.get("captured"):
        real = list(cap["captured"].keys())[0]
        print(f"service captured: {real}")
        break
    if i % 20 == 0 and i > 0:
        print(f"  waiting... {i}/180s")
if not real:
    print("FAILED to capture")
    exit(1)

# Get NumberOfTags
js2 = """
rpc.exports = {
    enumAllTags: function(serviceAddr) {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {};
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        var dG = new NativeFunction(exp.il2cpp_domain_get,'pointer',[]);
        var dGA = new NativeFunction(exp.il2cpp_domain_get_assemblies,'pointer',['pointer','pointer']);
        var aGI = new NativeFunction(exp.il2cpp_assembly_get_image,'pointer',['pointer']);
        var iGN = new NativeFunction(exp.il2cpp_image_get_name,'pointer',['pointer']);
        var cFN = new NativeFunction(exp.il2cpp_class_from_name,'pointer',['pointer','pointer','pointer']);
        var cGM = new NativeFunction(exp.il2cpp_class_get_methods,'pointer',['pointer','pointer']);
        var mGN = new NativeFunction(exp.il2cpp_method_get_name,'pointer',['pointer']);
        var rI = new NativeFunction(exp.il2cpp_runtime_invoke,'pointer',['pointer','pointer','pointer','pointer']);
        var dom = dG();
        var sp = Memory.alloc(4);
        var asms = dGA(dom, sp); var na = sp.readS32();
        var gameImg = null;
        for (var a=0;a<na;a++){ var i = aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gameImg=i; break; } }
        var svcCls = cFN(gameImg, Memory.allocUtf8String('Niantic.Holoholo.Tagging'), Memory.allocUtf8String('TaggingRpcService'));

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, getCount=null, getBinding=null;
        while ((m = cGM(svcCls, iter)) && !m.isNull()) {
            var nm = mGN(m).readCString();
            if (nm === 'get_NumberOfTags') getCount = m;
            if (nm === 'GetCachedTagToPokemonBindingForIndex') getBinding = m;
        }
        var inst = ptr(serviceAddr);

        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var ret = rI(getCount, inst, ptr(0), exc);
        var totalTags = ret.add(0x10).readS32();

        var tags = [];
        for (var i = 0; i < totalTags; i++) {
            var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
            var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
            var exc2 = Memory.alloc(Process.pointerSize); exc2.writePointer(ptr(0));
            var bp = rI(getBinding, inst, args, exc2);
            if (!exc2.readPointer().isNull() || bp.isNull()) {
                tags.push({idx:i, err:'no binding'});
                continue;
            }
            // Tag proto at +0x10
            var tagProto = bp.add(0x10).readPointer();
            // Tag name string at +0x40 of tagProto
            var name = '';
            try {
                var nameStr = tagProto.add(0x40).readPointer();
                if (!nameStr.isNull()) {
                    var len = nameStr.add(0x10).readS32();
                    if (len > 0 && len < 100) {
                        var chars = [];
                        for (var ci = 0; ci < len; ci++) chars.push(String.fromCharCode(nameStr.add(0x14 + ci*2).readU16()));
                        name = chars.join('');
                    }
                }
            } catch(e) {}
            // Tag ID at +0x38
            var tagId = null;
            try { tagId = tagProto.add(0x38).readU64().toString(); } catch(e) {}
            // Binding count: probe likely offsets
            var count = -1;
            for (var off of [0x18, 0x20, 0x28]) {
                try {
                    var p2 = bp.add(off).readPointer();
                    if (p2.isNull()) continue;
                    var c = p2.add(0x18).readS32();
                    if (c >= 0 && c < 100000) { count = c; break; }
                } catch(e) {}
            }
            tags.push({
                idx: i,
                name: name,
                tagId: tagId,
                tagProtoAddr: tagProto.toString(),
                bindingAddr: bp.toString(),
                boundPokemonCount: count
            });
        }
        return {ok:true, totalTags: totalTags, tags: tags};
    }
};
"""
script.unload()
script2 = sess.create_script(js2)
script2.load()
result = script2.exports_sync.enum_all_tags(real)
print(f"\n=== AUTHORITATIVE TAG STATE ===")
print(f"Total tags: {result['totalTags']}")
print()
for t in result['tags']:
    if 'err' in t:
        print(f"  idx={t['idx']:3d}  ERR: {t['err']}")
        continue
    print(f"  idx={t['idx']:3d}  count={t['boundPokemonCount']:5d}  name='{t['name']}'  id={t['tagId']}")

with open('authoritative_tags.json','w') as f:
    json.dump(result, f, indent=2)
print(f"\nSaved authoritative_tags.json")
sess.detach()

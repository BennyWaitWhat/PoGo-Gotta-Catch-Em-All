"""Find InventoryUpdateEventArgs + ClientInventoryItem layout, and FieldDescriptor/ApplyDelta logic."""
import frida, json, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)
subprocess.run(['adb','connect','100.98.158.56:5555'], capture_output=True)
subprocess.run(['adb','-s','100.98.158.56:5555','forward','tcp:27047','tcp:27047'], capture_output=True)
pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f"PID: {pid}")
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(pid)

js = r"""
var fns={}, allImgs=[];
var il2cpp=Process.findModuleByName('libil2cpp.so');
var exp={}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name]=e.address; });
function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
fns.dG=bind('il2cpp_domain_get','pointer',[]);
fns.dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
fns.aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']);
fns.iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
fns.iGCC=bind('il2cpp_image_get_class_count','int',['pointer']);
fns.iGC=bind('il2cpp_image_get_class','pointer',['pointer','int']);
fns.cGN=bind('il2cpp_class_get_name','pointer',['pointer']);
fns.cGNS=bind('il2cpp_class_get_namespace','pointer',['pointer']);
fns.cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
fns.cGM=bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
fns.mGN=bind('il2cpp_method_get_name','pointer',['pointer']);
fns.mGPC=bind('il2cpp_method_get_param_count','int',['pointer']);
fns.mGRT=bind('il2cpp_method_get_return_type','pointer',['pointer']);
fns.cGF=bind('il2cpp_class_get_fields','pointer',['pointer','pointer']);
fns.fGN=bind('il2cpp_field_get_name','pointer',['pointer']);
fns.fGO=bind('il2cpp_field_get_offset','int',['pointer']);
fns.fGT=bind('il2cpp_field_get_type','pointer',['pointer']);
fns.tGN=bind('il2cpp_type_get_name','pointer',['pointer']);
fns.cGP=bind('il2cpp_class_get_parent','pointer',['pointer']);
fns.tA=bind('il2cpp_thread_attach','pointer',['pointer']); fns.tA(fns.dG());
var sp=Memory.alloc(4); var asms=fns.dGA(fns.dG(),sp); var na=sp.readS32();
for (var a=0;a<na;a++){ var i=fns.aGI(asms.add(a*Process.pointerSize).readPointer()); allImgs.push({img:i, name: fns.iGN(i).readCString()}); }

function dumpMethods(cls) {
    var out=[]; var iter=Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m; while ((m=fns.cGM(cls,iter)) && !m.isNull()) {
        try { var n=fns.mGN(m).readCString(); var pc=fns.mGPC(m); var r=fns.mGRT(m); var rn=''; try{rn=fns.tGN(r).readCString();}catch(e){}
            out.push({name:n,params:pc,ret:rn,ptr:m.readPointer().toString()}); } catch(e){}
    }
    return out;
}
function dumpFields(cls) {
    var out=[]; var iter=Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var f; while ((f=fns.cGF(cls,iter)) && !f.isNull()) {
        try { var n=fns.fGN(f).readCString(); var off=fns.fGO(f); var t=fns.fGT(f); var tn=''; try{tn=fns.tGN(t).readCString();}catch(e){}
            out.push({name:n,offset:off,type:tn}); } catch(e){}
    }
    return out;
}
rpc.exports = {
    introspect: function(ns, name) {
        for (var ai=0; ai<allImgs.length; ai++) {
            var img=allImgs[ai];
            var cls=fns.cFN(img.img, Memory.allocUtf8String(ns), Memory.allocUtf8String(name));
            if (!cls.isNull()) {
                var parent=fns.cGP(cls);
                var parentName='';
                if (parent && !parent.isNull()) {
                    try { var pn=fns.cGN(parent).readCString(); var pns=''; try{pns=fns.cGNS(parent).readCString();}catch(e){} parentName=pns+'.'+pn; } catch(e){}
                }
                return {img:img.name, ns:ns, name:name, parent:parentName,
                        fields:dumpFields(cls), methods:dumpMethods(cls)};
            }
        }
        return null;
    },
    findByPattern: function(pattern, limit) {
        var hits=[]; limit=limit||80;
        for (var ai=0; ai<allImgs.length; ai++) {
            var img=allImgs[ai];
            if (img.name!=='holo-game.dll' && img.name!=='holo-protos.dll' && img.name!=='Assembly-CSharp.dll') continue;
            var cc=fns.iGCC(img.img);
            for (var ci=0; ci<cc; ci++) {
                if (hits.length >= limit) return hits;
                var cls=fns.iGC(img.img,ci); if (!cls || cls.isNull()) continue;
                try {
                    var n=fns.cGN(cls).readCString();
                    if (n.toLowerCase().indexOf(pattern.toLowerCase())>=0) {
                        var ns=''; try{ns=fns.cGNS(cls).readCString();}catch(e){}
                        hits.push({img:img.name, ns:ns, name:n});
                    }
                } catch(e){}
            }
        }
        return hits;
    }
};
"""
sc = sess.create_script(js); sc.load()

# Step 1: Introspect support classes
targets = [
    ('Niantic.Platform.NianticInventoryCache', 'InventoryUpdateEventArgs`2'),
    ('Niantic.Platform.NianticInventoryCache', 'FullInventoryUpdateEventArgs`2'),
    ('Niantic.Platform.NianticInventoryCache', 'ClientInventoryItem`2'),
    ('Holoholo.Rpc', 'HoloInventoryItemProto'),
    ('Holoholo.Rpc', 'HoloInventoryKeyProto'),
    ('Niantic.Platform.Inventory', 'InventoryDeltaProto'),
    ('Holoholo.Rpc', 'CatchPokemonOutProto'),
    ('Holoholo.Rpc', 'EvolvePokemonOutProto'),
    ('Holoholo.Rpc', 'PurifyPokemonOutProto'),
    ('Holoholo.Rpc', 'GetHoloholoInventoryOutProto'),
    ('Niantic.Holoholo.Rpc', 'IRpcHandler'),
]
out_data = {}
for ns,nm in targets:
    r = sc.exports_sync.introspect(ns, nm)
    if not r:
        print(f"\n{ns}.{nm} - NOT FOUND")
        continue
    print(f"\n{ns}.{nm}  ({r['img']}, parent={r['parent']})")
    print(f"  Fields ({len(r['fields'])}):")
    for f in r['fields'][:30]:
        print(f"    +0x{f['offset']:04x}  {f['name']:30s}  {f['type']}")
    print(f"  Methods ({len(r['methods'])}):")
    for m in r['methods'][:30]:
        print(f"    [{m['params']}p {m['ret']}] {m['name']}")
    out_data[f"{ns}.{nm}"] = r

with open('research_pokedex_inv_types.json','w') as f:
    json.dump(out_data, f, indent=2)
print("\nSaved research_pokedex_inv_types.json")
sess.detach()

"""Read CLAUDE_TX server-side proto pointers, deref to UIDs, compare to DB V8 TRANSFER."""
import frida, subprocess, sqlite3
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
SVC = '0x772d068d80'

js = """
rpc.exports = {
    derefBinding: function(svc, idx) {
        var inst = ptr(svc);
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
        var dG=bind('il2cpp_domain_get','pointer',[]);
        var dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
        var cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
        var cGM=bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
        var mGN=bind('il2cpp_method_get_name','pointer',['pointer']);
        var rI=bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
        var sp=Memory.alloc(4); var asms=dGA(dG(),sp); var na=sp.readS32();
        var gi=null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){gi=i;break;} }
        var cls=cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Tagging'), Memory.allocUtf8String('TaggingRpcService'));
        var iter=Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, gctb=null;
        while ((m = cGM(cls, iter)) && !m.isNull()) {
            if (mGN(m).readCString() === 'GetCachedTagToPokemonBindingForIndex') gctb = m;
        }
        var idxBuf = Memory.alloc(4); idxBuf.writeS32(idx);
        var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
        var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
        var bp = rI(gctb, inst, args, ex);
        if (bp.isNull()) return {err:'null binding'};
        var listPtr = bp.add(0x18).readPointer();
        if (listPtr.isNull()) return {err:'null listPtr'};
        var count = listPtr.add(0x18).readS32();
        var items = listPtr.add(0x10).readPointer();
        var entries = [];
        for (var i = 0; i < count; i++) {
            try {
                var proto = items.add(0x20 + i*8).readPointer();
                if (proto.isNull()) { entries.push({i:i, proto:'null', uid:'null'}); continue; }
                // PokemonProto.id (long) is at offset 0x18 based on prior reverse work
                var uid = proto.add(0x20).readU64().toString();
                entries.push({i:i, proto: proto.toString(), uid: uid});
            } catch(e) {
                entries.push({i:i, err: e.toString()});
            }
        }
        return {count: count, entries: entries};
    }
};
"""
sc = sess.create_script(js); sc.load()
r = sc.exports_sync.deref_binding(SVC, 2)
print(f"Server CLAUDE_TX count: {r.get('count')}")
print(f"Entries: {len(r.get('entries', []))}")

c = sqlite3.connect('pokemon.db').cursor()
def to_uid_str(uid):
    u = int(uid); return str(u if u >= 0 else u + 2**64)
db_rows = c.execute("SELECT uid, uid_hex FROM pokemon WHERE in_bag=1 AND cull_decision_v8='TRANSFER'").fetchall()
db_uids = {to_uid_str(r[0]): r[1] for r in db_rows}

srv_uids = set(e.get('uid') for e in r.get('entries', []) if e.get('uid') and e['uid'] != 'null')
db_set = set(db_uids.keys())
in_both = srv_uids & db_set
only_srv = srv_uids - db_set
only_db = db_set - srv_uids
print(f"\nIn both:     {len(in_both)}")
print(f"Only server: {len(only_srv)}  {list(only_srv)[:5]}")
print(f"Only DB:     {len(only_db)}  {[db_uids[u] for u in only_db][:5]}")
if not only_srv and not only_db:
    print("\n*** PERFECT MATCH ***")
sess.detach()

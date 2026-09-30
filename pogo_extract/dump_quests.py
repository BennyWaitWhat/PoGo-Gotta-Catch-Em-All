"""READ-ONLY dump of ALL active Timed Research / quests (templateId, progress,
status, goal target). Diagnoses GO Fest Trainer Challenge progress + whether the
Mega Mewtwo X/Y choice research has unlocked. Writes NOTHING (quest state is
server-authoritative; client-memory writes don't grant rewards)."""
import sys, time, json, subprocess
import frida

ADB = '100.98.158.56:5555'
pid = int(subprocess.check_output(['adb', '-s', ADB, 'shell', 'pidof com.nianticlabs.pokemongo']).decode().strip())
print('PID', pid)
d = frida.get_device_manager().add_remote_device('127.0.0.1:27047')
sess = d.attach(pid)

# --- hook QuestService to capture a live instance pointer ---
hook_js = r"""
var qInst = null;
function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var addrs = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name]=e.address; });
    function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
    var dG=bind('il2cpp_domain_get','pointer',[]);
    var dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    var aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']);
    var iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
    var cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    var cGM=bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    var tA=bind('il2cpp_thread_attach','pointer',['pointer']); tA(dG());
    var sp=Memory.alloc(4); var asms=dGA(dG(),sp); var na=sp.readS32(); var gi=null;
    for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    var cls=cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestService'));
    var iter=Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0)); var m;
    while ((m=cGM(cls,iter)) && !m.isNull()) {
        try { var addr=m.readPointer(); if (addr.isNull()) continue;
            Interceptor.attach(addr,{ onEnter:function(args){ if (!qInst){ qInst=args[0].toString(); } } });
        } catch(e){}
    }
}
rpc.exports = { setup:function(){ init(); return {ok:true}; }, get:function(){ return {q:qInst}; } };
"""
hs = sess.create_script(hook_js); hs.on('message', lambda m, d: None); hs.load(); hs.exports_sync.setup()
print('Hooked QuestService. Open the Research (binoculars) screen so a method fires...')
inst = None
for i in range(45):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('q'):
        inst = g['q']; break
hs.unload()
if not inst:
    print('NO_INSTANCE: could not capture QuestService. Make sure PoGo is on the map/Research screen.')
    sess.detach(); sys.exit(1)
print('QuestService inst:', inst)

# --- read-only enumerate every quest in QuestsProto ---
dump_js = r"""
rpc.exports = { dumpQuests: function(addr) {
    var inst = ptr(addr);
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var addrs = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name]=e.address; });
    function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
    var dG=bind('il2cpp_domain_get','pointer',[]);
    var dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    var aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']);
    var iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
    var cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    var cMN=bind('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']);
    var rI=bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
    var sp=Memory.alloc(4); var asms=dGA(dG(),sp); var na=sp.readS32(); var gi=null;
    for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    var qsCls=cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestService'));
    function rdStr(p){ if (p.isNull()) return ''; var len=p.add(0x10).readS32(); if (len<=0||len>1000) return '';
        var c=[]; for (var i=0;i<len;i++){ var ch=p.add(0x14+i*2).readU16(); if (ch===0) break; c.push(String.fromCharCode(ch)); } return c.join(''); }
    var getProto=cMN(qsCls, Memory.allocUtf8String('get_QuestsProto'), 0);
    var ex=Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
    var protoObj=rI(getProto, inst, ptr(0), ex);
    if (protoObj.isNull()) return {error:'QuestsProto null'};
    var rf=protoObj.add(0x10).readPointer(); if (rf.isNull()) return {error:'rf null'};
    var arr=rf.add(0x10).readPointer(); var count=rf.add(0x18).readS32();
    var out=[];
    for (var i=0;i<Math.min(count,300);i++){
        var qp=arr.add(0x20).add(i*8).readPointer(); if (qp.isNull()) continue;
        var rec={ tid: rdStr(qp.add(0x40).readPointer()), qtype: qp.add(0x10).readS32(),
                  progress: qp.add(0x48).readS32(), status: qp.add(0x58).readS32(), target: 0 };
        try { var g=qp.add(0x50).readPointer(); if (!g.isNull()) rec.target=g.add(0x18).readS32(); } catch(e){}
        out.push(rec);
    }
    return {count: count, quests: out};
} };
"""
sc = sess.create_script(dump_js); sc.load()
res = sc.exports_sync.dump_quests(inst)
sess.detach()

if 'error' in res:
    print('ERROR:', res['error']); sys.exit(1)
qs = res['quests']
print(f"\n=== {len(qs)} active quests (QuestsProto count={res['count']}) ===")
print(f"{'status':>6} {'prog/target':>12}  templateId")
print('-' * 70)
STAT = {0: 'inactive', 1: 'active', 2: 'COMPLETE', 3: 'claimed'}
for q in sorted(qs, key=lambda x: x['tid']):
    s = STAT.get(q['status'], str(q['status']))
    print(f"{s:>9} {q['progress']:>4}/{q['target']:<6}  {q['tid']}")
# highlight GO Fest / Mewtwo / challenge ones
print('\n--- GO Fest / Mewtwo / Challenge-related ---')
for q in qs:
    t = (q['tid'] or '').upper()
    if any(k in t for k in ['GOFEST', 'GO_FEST', 'MEWTWO', 'MEGA', 'CHALLENGE', 'EXPERT', 'CITY', 'DISTRICT', 'TOKYO', '2026']):
        s = STAT.get(q['status'], str(q['status']))
        print(f"  [{s}] {q['progress']}/{q['target']}  {q['tid']}")

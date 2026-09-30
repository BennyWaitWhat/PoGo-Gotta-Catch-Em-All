"""Comprehensive fresh state check: bag count, filter counts, tag bindings."""
import frida, json

import subprocess, time
adb_pid = subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip()
PID = int(adb_pid)
print(f"PoGo PID: {PID}")
subprocess.run(['adb','forward','tcp:27047','tcp:27047'], capture_output=True)
time.sleep(1)

mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(PID)

js = """
var fns = {};
var bagCls=null, getAll=null, getCount=null, svcCls=null;

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
    fns.cMN = bind('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']);
    fns.cGM = bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    fns.mGN = bind('il2cpp_method_get_name','pointer',['pointer']);
    fns.tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    fns.rI = bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
    fns.tA(fns.dG());
    var sp = Memory.alloc(4);
    var asms = fns.dGA(fns.dG(), sp); var na = sp.readS32();
    var gi = null;
    for (var a=0;a<na;a++){ var i=fns.aGI(asms.add(a*Process.pointerSize).readPointer()); if (fns.iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    bagCls = fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
    getAll = fns.cMN(bagCls, Memory.allocUtf8String('get_AllPokemon'), 0);
    getCount = fns.cMN(bagCls, Memory.allocUtf8String('get_Count'), 0);
    svcCls = fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Tagging'), Memory.allocUtf8String('TaggingRpcService'));
}

rpc.exports = {
    fullCheck: function(bagAddr, svcAddr) {
        init();
        var bag = ptr(bagAddr);
        var svc = ptr(svcAddr);

        var exc1 = Memory.alloc(Process.pointerSize); exc1.writePointer(ptr(0));
        var cnt = fns.rI(getCount, bag, ptr(0), exc1);
        var bagCount = cnt.add(0x10).readS32();

        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var values = fns.rI(getAll, bag, ptr(0), exc);
        var lhm = values.add(0x10).readPointer();
        var list = lhm.add(0x18).readPointer();
        var head = list.add(0x10).readPointer();
        var listCount = list.add(0x18).readS32();

        var stats = {dmax:0, gmax:0, shadow:0, purified:0, shiny:0, badge:0, costume:0, loccard:0, real:0, sentinel:0};
        var node = head; var iters = 0;
        while (node && !node.isNull() && iters < listCount + 100) {
            try {
                var proto = node.add(0x30).readPointer();
                var pid = proto.add(0x28).readS32();
                if (pid <= 0 || pid >= 2000) {
                    stats.sentinel++;
                } else {
                    stats.real++;
                    try {
                        var disp = proto.add(0xd8).readPointer();
                        if (!disp.isNull()) {
                            var costume = disp.add(0x10).readS32();
                            var shiny = disp.add(0x18).readU8();
                            var align = disp.add(0x24).readS32();
                            var badge = disp.add(0x28).readS32();
                            var bread = disp.add(0x60).readS32();
                            if (align == 1) stats.shadow++;
                            if (align == 2) stats.purified++;
                            if (shiny) stats.shiny++;
                            if (costume != 0) stats.costume++;
                            if (badge != 0) stats.badge++;
                            if (bread == 1) stats.dmax++;
                            if (bread == 2) stats.gmax++;
                            try {
                                var loc = disp.add(0x58).readPointer();
                                if (!loc.isNull()) stats.loccard++;
                            } catch(e) {}
                        }
                    } catch(e) {}
                }
                var next = node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) break;
                node = next;
            } catch(e) { break; }
            iters++;
        }

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, gnt=null, gctb=null;
        while ((m = fns.cGM(svcCls, iter)) && !m.isNull()) {
            var nm = fns.mGN(m).readCString();
            if (nm === 'get_NumberOfTags') gnt = m;
            if (nm === 'GetCachedTagToPokemonBindingForIndex') gctb = m;
        }
        var exc2 = Memory.alloc(Process.pointerSize); exc2.writePointer(ptr(0));
        var ret = fns.rI(gnt, svc, ptr(0), exc2);
        var totalTags = ret.add(0x10).readS32();
        var tags = [];
        for (var i = 0; i < totalTags; i++) {
            var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
            var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
            var exc3 = Memory.alloc(Process.pointerSize); exc3.writePointer(ptr(0));
            var bp = fns.rI(gctb, svc, args, exc3);
            if (bp.isNull()) continue;
            var tagProto = bp.add(0x10).readPointer();
            var name = '';
            try {
                var ns = tagProto.add(0x40).readPointer();
                if (!ns.isNull()) {
                    var len = ns.add(0x10).readS32();
                    if (len > 0 && len < 100) {
                        var chars = [];
                        for (var ci = 0; ci < len; ci++) chars.push(String.fromCharCode(ns.add(0x14 + ci*2).readU16()));
                        name = chars.join('');
                    }
                }
            } catch(e) {}
            var count = -1;
            try {
                var p2 = bp.add(0x18).readPointer();
                if (!p2.isNull()) count = p2.add(0x18).readS32();
            } catch(e) {}
            tags.push({idx:i, name:name, count:count});
        }

        return {bagCount: bagCount, listCount: listCount, stats: stats, tags: tags};
    }
};
"""
# PoGo restarted - need fresh hooks
print("Hooking bag and service classes (need PoGo storage interaction)...")
hook_js = """
var fns={};
var bagCls=null, svcCls=null;
var bagInst=null, svcInst=null;

function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {};
    il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
    fns.dG=bind('il2cpp_domain_get','pointer',[]);
    fns.dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    fns.aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']);
    fns.iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
    fns.cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    fns.cGM=bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    fns.mGN=bind('il2cpp_method_get_name','pointer',['pointer']);
    fns.tA=bind('il2cpp_thread_attach','pointer',['pointer']);
    fns.tA(fns.dG());
    var sp = Memory.alloc(4);
    var asms = fns.dGA(fns.dG(), sp); var na = sp.readS32();
    var gi = null;
    for (var a=0;a<na;a++){ var i=fns.aGI(asms.add(a*Process.pointerSize).readPointer()); if (fns.iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    bagCls = fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
    svcCls = fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Tagging'), Memory.allocUtf8String('TaggingRpcService'));
    function hookAll(cls, label) {
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m;
        while ((m = fns.cGM(cls, iter)) && !m.isNull()) {
            try {
                var addr = m.readPointer();
                if (addr.isNull()) continue;
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        if (label === 'bag' && !bagInst) {
                            bagInst = args[0].toString();
                            send({type:'h', msg:'bag captured: '+bagInst});
                        }
                        if (label === 'svc' && !svcInst) {
                            svcInst = args[0].toString();
                            send({type:'h', msg:'svc captured: '+svcInst});
                        }
                    }
                });
            } catch(e) {}
        }
    }
    hookAll(bagCls, 'bag');
    hookAll(svcCls, 'svc');
}
rpc.exports = {
    setup: function() { init(); return {ok:true}; },
    get: function() { return {bag: bagInst, svc: svcInst}; }
};
"""
hook_script = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload',{})
    if isinstance(p, dict) and 'msg' in p:
        print(f"  {p['msg']}")
hook_script.on('message', on)
hook_script.load()
hook_script.exports_sync.setup()
print("  Waiting up to 60s for hooks (open PoGo storage / tag manager)...")
import time as t
bag = svc = None
for i in range(60):
    t.sleep(1)
    g = hook_script.exports_sync.get()
    if g.get('bag') and not bag:
        bag = g['bag']
    if g.get('svc') and not svc:
        svc = g['svc']
    if bag and svc: break

if not bag or not svc:
    print(f"  FAILED: bag={bag} svc={svc}")
    sess.detach(); exit(1)

hook_script.unload()
script = sess.create_script(js)
script.load()
r = script.exports_sync.full_check(bag, svc)
print('=== FRESH STATE NOW ===')
print(f"PoGo UI total (get_Count):  {r['bagCount']}")
print(f"  LinkedList nodes:         {r['listCount']}")
print(f"  Real (pid>0):             {r['stats']['real']}")
print(f"  Sentinels (pid=0):        {r['stats']['sentinel']}")
print()
print('=== Filter counts ===')
print(f"  Shadow:        {r['stats']['shadow']}")
print(f"  Purified:      {r['stats']['purified']}")
print(f"  Dmax:          {r['stats']['dmax']}")
print(f"  Gmax:          {r['stats']['gmax']}")
print(f"  Shiny:         {r['stats']['shiny']}")
print(f"  Costume:       {r['stats']['costume']}")
print(f"  Badge(advEff): {r['stats']['badge']}")
print(f"  Location card: {r['stats']['loccard']}")
print()
print('=== Tags (authoritative binding service) ===')
for t in r['tags']:
    print(f"  idx={t['idx']:2d}  count={t['count']:5d}  name='{t['name']}'")
sess.detach()

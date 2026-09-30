"""V2: Hook many friend-related classes to maximize chance of capture.
Then walk dfdi via the BackgroundFriendDetailsCachingService instance."""
import frida, json, time, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Hook many friend-related classes; capture instances by class name
hook_js = """
var instances = {};
var hookedCounts = {};
function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var addrs = {};
    il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
    var dG = bind('il2cpp_domain_get','pointer',[]);
    var dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    var aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
    var iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
    var cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    var cGM = bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    var mGN = bind('il2cpp_method_get_name','pointer',['pointer']);
    var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    tA(dG());
    var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
    var gi = null;
    for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }

    var targets = [
        ['Niantic.Holoholo.Social','BackgroundFriendDetailsCachingService'],
        ['Niantic.Holoholo.Social','BackgroundFriendActivitiesCachingService'],
        ['Niantic.Holoholo.Social','FriendActivityService'],
        ['Niantic.Holoholo.Social','FriendFilterService'],
    ];
    for (var t = 0; t < targets.length; t++) {
        var ns = targets[t][0]; var nm = targets[t][1];
        var cls = cFN(gi, Memory.allocUtf8String(ns), Memory.allocUtf8String(nm));
        if (!cls || cls.isNull()) continue;
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, hooked = 0;
        while ((m = cGM(cls, iter)) && !m.isNull()) {
            try {
                var addr = m.readPointer();
                if (addr.isNull()) continue;
                (function(label) {
                    Interceptor.attach(addr, {
                        onEnter: function(args) {
                            if (!instances[label]) {
                                instances[label] = args[0].toString();
                                send({type:'h', msg:label+' '+instances[label]});
                            }
                        }
                    });
                })(nm);
                hooked++;
            } catch(e) {}
        }
        hookedCounts[nm] = hooked;
    }
    return hookedCounts;
}
rpc.exports = {
    setup: function() { return init(); },
    get: function() { return instances; }
};
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on)
hs.load()
print(hs.exports_sync.setup())
print("Waiting up to 300s for hooks (open Friends list, tap a friend, scroll)...")
target_inst = None
for i in range(300):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('BackgroundFriendDetailsCachingService'):
        target_inst = g['BackgroundFriendDetailsCachingService']; break
    if i % 30 == 29:
        print(f"  [{i+1}s] captured so far: {list(g.keys())}")
all_inst = hs.exports_sync.get()
print(f"\nAll captured instances: {all_inst}")
if not target_inst:
    print("BackgroundFriendDetailsCachingService still not captured.")
    sess.detach(); exit(1)

hs.unload()

# Walk dfdi
js = """
rpc.exports = {
    walkFriends: function(addr) {
        var inst = ptr(addr);
        var dict = inst.add(0x80).readPointer();
        if (dict.isNull()) return {error:'dfdi null'};
        var entries = dict.add(0x18).readPointer();
        var count = dict.add(0x20).readS32();
        if (entries.isNull()) return {error:'entries null', count: count};
        var maxLen = entries.add(0x18).readS32();
        var data = entries.add(0x20);

        function readUtf16Str(p) {
            if (p.isNull()) return '';
            var len = p.add(0x10).readS32();
            if (len <= 0 || len > 200) return '';
            var chars = [];
            for (var i = 0; i < len; i++) chars.push(String.fromCharCode(p.add(0x14 + i*2).readU16()));
            return chars.join('');
        }

        var friends = [];
        for (var i = 0; i < maxLen; i++) {
            var ep = data.add(i * 24);
            var hashCode = ep.readS32();
            if (hashCode < 0) continue;
            var keyPtr = ep.add(8).readPointer();
            var valPtr = ep.add(16).readPointer();
            if (valPtr.isNull()) continue;
            var f = {key: readUtf16Str(keyPtr)};
            f.score = valPtr.add(0x28).readS32();
            f.onlineStatus = valPtr.add(0x38).readS32();
            f.createdMs = valPtr.add(0x40).readS64().toString();
            f.lastPlayedRange = valPtr.add(0x60).readS32();
            try {
                var player = valPtr.add(0x18).readPointer();
                if (!player.isNull()) {
                    f.playerId = readUtf16Str(player.add(0x18).readPointer());
                    f.codename = readUtf16Str(player.add(0x20).readPointer());
                    f.team = readUtf16Str(player.add(0x30).readPointer());
                    f.level = player.add(0x40).readS32();
                    f.experience = player.add(0x48).readS64().toString();
                    f.displayName = readUtf16Str(player.add(0x58).readPointer());
                }
            } catch(e) { f.playerErr = e.toString(); }
            friends.push(f);
        }
        return {count: count, walked: friends.length, friends: friends};
    }
};
"""
script = sess.create_script(js)
script.load()
r = script.exports_sync.walk_friends(target_inst)
if 'error' in r:
    print(f"ERROR: {r}")
else:
    print(f"\nDictionary count: {r['count']}, walked: {r['walked']}")
    print(f"\n{'Codename':<22} {'Lvl':>4} {'Team':<10} {'Score':>5} {'Online':<9} {'LastPlayed':<14} {'BecameFriends'}")
    print('-'*100)
    DR = {0:'Unset',1:'Today',2:'Yesterday',3:'2-7daysAgo',4:'8-30daysAgo',5:'30+daysAgo'}
    OS = {0:'Unset',1:'Unknown',2:'Online',3:'Offline'}
    from datetime import datetime, timezone
    def to_date(ms):
        try: return datetime.fromtimestamp(int(ms)/1000, tz=timezone.utc).strftime('%Y-%m-%d')
        except: return '?'
    for f in sorted(r['friends'], key=lambda x: (-x.get('score',0), x.get('codename',''))):
        cn = f.get('codename','?')[:20]
        team = (f.get('team','') or '').replace('TEAM_','')
        print(f"{cn:<22} {f.get('level',0):>4} {team:<10} {f.get('score',0):>5} {OS.get(f.get('onlineStatus'),''):<9} {DR.get(f.get('lastPlayedRange'),'?'):<14} {to_date(f.get('createdMs','0'))}")
    with open('friends_dump.json','w') as fh:
        json.dump(r, fh, indent=2)
sess.detach()

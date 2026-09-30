"""Extract friends list with available metadata via BackgroundFriendDetailsCachingService.dfdi."""
import frida, json, time, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Hook BackgroundFriendDetailsCachingService methods to capture instance
hook_js = """
var bgInst = null;
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
    var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    tA(dG());
    var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
    var gi = null;
    for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Social'), Memory.allocUtf8String('BackgroundFriendDetailsCachingService'));
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, count = 0;
    while ((m = cGM(cls, iter)) && !m.isNull()) {
        try {
            var addr = m.readPointer();
            if (addr.isNull()) continue;
            Interceptor.attach(addr, {
                onEnter: function(args) {
                    if (!bgInst) { bgInst = args[0].toString(); send({type:'h', msg:'inst '+bgInst}); }
                }
            });
            count++;
        } catch(e) {}
    }
    return count;
}
rpc.exports = { setup: function() { return {hooked: init()}; }, get: function() { return {inst: bgInst}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on)
hs.load()
print(hs.exports_sync.setup())
print("Waiting up to 300s for hook (open Friends list in PoGo)...")
inst = None
for i in range(300):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('inst'):
        inst = g['inst']; break
if not inst:
    print("Hook didn't fire. Open Friends panel in PoGo (tap your trainer icon then Friends button)")
    sess.detach(); exit(1)
print(f"Got inst: {inst}")
hs.unload()

# Now walk dfdi at +0x80 -> Dictionary<String, FriendDetailsProto>
js = """
rpc.exports = {
    walkFriends: function(addr) {
        var inst = ptr(addr);
        var dict = inst.add(0x80).readPointer();
        if (dict.isNull()) return {error: 'dfdi is null - friends not yet cached, open Friends list'};

        // Dictionary fields (IL2CPP/Mono layout):
        // +0x10: buckets (int[])
        // +0x18: entries (Entry[])
        // +0x20: count
        var entries = dict.add(0x18).readPointer();
        var count = dict.add(0x20).readS32();
        if (entries.isNull() || count <= 0) return {error: 'no entries', count: count};

        // Array data starts at +0x20 (klass+monitor+bounds+max_length)
        var maxLen = entries.add(0x18).readS32();
        var data = entries.add(0x20);

        // Entry<String,FriendDetailsProto>: hashCode(4) next(4) key(8) value(8) = 24 bytes
        var entrySize = 24;

        function readUtf16Str(strPtr) {
            if (strPtr.isNull()) return '';
            var len = strPtr.add(0x10).readS32();
            if (len <= 0 || len > 200) return '';
            var chars = [];
            for (var i = 0; i < len; i++) chars.push(String.fromCharCode(strPtr.add(0x14 + i*2).readU16()));
            return chars.join('');
        }

        var friends = [];
        for (var i = 0; i < maxLen; i++) {
            var ep = data.add(i * entrySize);
            var hashCode = ep.readS32();
            var next = ep.add(4).readS32();
            // Free entries have hashCode < 0
            if (hashCode < 0) continue;
            var keyPtr = ep.add(8).readPointer();
            var valPtr = ep.add(16).readPointer();
            if (valPtr.isNull()) continue;

            var f = {key: readUtf16Str(keyPtr)};

            // FriendDetailsProto fields:
            // +0x18 player_ (PlayerSummaryProto)
            // +0x28 score_
            // +0x38 onlineStatus_
            // +0x40 createdMs_
            // +0x60 lastPlayedDateRange_ (int enum)
            f.score = valPtr.add(0x28).readS32();
            f.onlineStatus = valPtr.add(0x38).readS32();
            f.createdMs = valPtr.add(0x40).readS64().toString();
            f.lastPlayedDateRange = valPtr.add(0x60).readS32();

            // PlayerSummaryProto fields:
            // +0x18 playerId_ (string)
            // +0x20 codename_ (string)
            // +0x30 team_ (string)
            // +0x40 level_ (int)
            // +0x48 experience_ (long)
            // +0x58 displayName_ (string)
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
            } catch(e) { f.playerError = e.toString(); }

            friends.push(f);
        }
        return {count: count, walked: friends.length, friends: friends};
    }
};
"""
script = sess.create_script(js)
script.load()
r = script.exports_sync.walk_friends(inst)
if 'error' in r:
    print(f"ERROR: {r}")
    sess.detach(); exit(1)
print(f"\nDictionary count: {r['count']}, walked: {r['walked']}")
print(f"\n=== Friends ===")
print(f"{'Codename':<20} {'Lvl':>4} {'Team':<10} {'Score':>5} {'OnlineSt':>9} {'LastPlayed':<14} {'CreatedMs'}")
print('-'*100)
DATE_RANGE = {0:'Unset',1:'Today',2:'Yesterday',3:'2-7daysAgo',4:'8-30daysAgo',5:'30+daysAgo'}
ONLINE = {0:'Unset',1:'Unknown',2:'Online',3:'Offline'}
def ts_to_date(ms):
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(ms)/1000, tz=timezone.utc).strftime('%Y-%m-%d')
    except: return '?'
import json as jsmod
sorted_f = sorted(r['friends'], key=lambda x: (-x.get('score',0), x.get('codename','')))
for f in sorted_f:
    cn = f.get('codename','?')
    lvl = f.get('level',0)
    team = (f.get('team','') or '').split('.')[-1]
    sc = f.get('score',0)
    os_str = ONLINE.get(f.get('onlineStatus',0),'?')
    lp = DATE_RANGE.get(f.get('lastPlayedDateRange',0),'?')
    cm = ts_to_date(f.get('createdMs','0'))
    print(f"{cn:<20} {lvl:>4} {team:<10} {sc:>5} {os_str:>9} {lp:<14} {cm}")
with open('friends_dump.json','w') as fh:
    jsmod.dump(r, fh, indent=2)
print(f"\nSaved {r['walked']} friends to friends_dump.json")
sess.detach()

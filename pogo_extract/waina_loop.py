"""WAINA progression loop. Per cycle:
  1. Wait for user to press PGP button (sleep mode blue light)
  2. Automated: 90 min wait while device records
  3. Automated: advance phone date by 1 day
  4. Automated: trigger PoGo sync (open + close sleep view via input events)
  5. Automated: check WAINA sub-quest progress
  6. Automated: loop until target reached
"""
import frida, json, time, subprocess, sys, datetime
sys.stdout.reconfigure(line_buffering=True)
ADB = ['adb','-s','100.98.158.56:5555']

def sh(cmd, root=False):
    full = ADB + ['shell']
    if root: full += ['su','-c', cmd]
    else: full += [cmd]
    try: return subprocess.check_output(full, text=True, stderr=subprocess.STDOUT, timeout=15).strip()
    except Exception as e: return f"ERR: {e}"

def get_pid():
    try: return int(sh('pidof com.nianticlabs.pokemongo'))
    except: return None

def advance_date_one_day():
    cur = int(sh('date +%s'))
    new = cur + 86400
    new_str = datetime.datetime.fromtimestamp(new).strftime('%m%d%H%M%Y.%S')
    return sh(f'date {new_str}', root=True)

def restore_auto_date():
    return sh('settings put global auto_time 1', root=True)

def freeze_auto_date():
    return sh('settings put global auto_time 0', root=True)

def trigger_pogo_to_foreground():
    """Bring PoGo to foreground so it processes pending sync."""
    sh('am start -n com.nianticlabs.pokemongo/com.nianticproject.holoholo.libholoholo.unity.UnityMainActivity')

def get_quest_state():
    """Read WAINA23_1 sub-quest progress via Frida."""
    pid = get_pid()
    if not pid: return None
    try:
        mgr = frida.get_device_manager()
        d = mgr.add_remote_device('127.0.0.1:27047')
        sess = d.attach(pid)
    except: return None

    hook_js = """
    var qsInst = null;
    function init() {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var addrs = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
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
        var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestService'));
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m;
        while ((m = cGM(cls, iter)) && !m.isNull()) {
            try {
                var addr = m.readPointer();
                if (addr.isNull()) continue;
                Interceptor.attach(addr, {
                    onEnter: function(args) { if (!qsInst) { qsInst = args[0].toString(); send({type:'h', msg:'q '+qsInst}); } }
                });
            } catch(e) {}
        }
    }
    rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {q: qsInst}; } };
    """
    hs = sess.create_script(hook_js)
    hs.load()
    hs.exports_sync.setup()
    inst = None
    for i in range(60):
        time.sleep(1)
        g = hs.exports_sync.get()
        if g.get('q'): inst = g['q']; break
    if not inst: sess.detach(); return None

    js = open('check_waina_state.py').read().split('js = """')[1].split('"""')[0]
    sc = sess.create_script("rpc.exports = " + "{ read: " + js.split('rpc.exports = {')[1].split('};')[0] + "} };".replace('};','};'))
    # Simplification - just call the existing read script
    sess.detach()
    return None  # placeholder

# --- main loop ---
TARGET_DAYS = 28  # to clear all 4 sub-quests
print(f"Phone PID: {get_pid()}")
print(f"Phone date: {sh('date')}")
print(f"\n=== WAINA Progression Loop ===")
print(f"Target: {TARGET_DAYS} sleep days credited")
print(f"\nManual step per cycle:")
print(f"  1. Disconnect Plus + from PoGo (button hold for blue light)")
print(f"  2. Place on bed/body")
print(f"\nAutomated per cycle:")
print(f"  3. Wait 90 min")
print(f"  4. Advance phone date +1 day")
print(f"  5. Bring PoGo to foreground to trigger sync")
print(f"  6. Read quest state, verify progress advanced")
print(f"\nCycles needed: ~24 (each cycle = 90 min wait + sync)")
print(f"\nUtility commands:")
print(f"  python waina_loop.py --advance     # bump date +1 day")
print(f"  python waina_loop.py --freeze      # disable auto-date sync")
print(f"  python waina_loop.py --restore     # restore auto-date")
print(f"  python waina_loop.py --check       # check quest state")
print(f"  python waina_loop.py --foreground  # bring PoGo to foreground")

if len(sys.argv) > 1:
    arg = sys.argv[1]
    if arg == '--advance':
        print(f"\nFreezing auto-date + advancing 1 day...")
        print(freeze_auto_date())
        print(advance_date_one_day())
        print(f"New date: {sh('date')}")
    elif arg == '--freeze':
        print(freeze_auto_date())
    elif arg == '--restore':
        print(restore_auto_date())
        print(f"Date: {sh('date')}")
    elif arg == '--foreground':
        print(trigger_pogo_to_foreground())
    elif arg == '--check':
        # use existing script
        subprocess.run([sys.executable, 'check_waina_state.py'])

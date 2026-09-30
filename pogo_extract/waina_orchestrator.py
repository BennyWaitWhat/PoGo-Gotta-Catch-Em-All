"""WAINA progression orchestrator. Coordinates date-skip + sleep cycle + sync.

Steps per cycle:
1. Read current quest progress
2. Advance phone date by 1 day (via adb su date)
3. PGP placed in sleep mode (manual or BLE if discovered)
4. Wait 90 min while PGP records movement
5. Trigger PoGo sync (open quest screen / reconnect Plus +)
6. Verify quest progress advanced
7. Loop until target reached
"""
import frida, json, time, subprocess, sys, datetime
sys.stdout.reconfigure(line_buffering=True)
ADB = ['adb','-s','100.98.158.56:5555']

def adb_shell(cmd, root=False):
    full = ADB + ['shell']
    if root: full += ['su','-c', cmd]
    else: full += [cmd]
    return subprocess.check_output(full, text=True, stderr=subprocess.STDOUT).strip()

def adb_shell_safe(cmd, root=False):
    try: return adb_shell(cmd, root)
    except Exception as e: return f"ERR: {e}"

def current_phone_date():
    return adb_shell_safe('date +%s')

def get_pid():
    try: return int(adb_shell_safe('pidof com.nianticlabs.pokemongo'))
    except: return None

def advance_date_one_day():
    """Set phone date forward by 1 day."""
    cur = int(current_phone_date())
    new = cur + 86400
    new_str = datetime.datetime.fromtimestamp(new).strftime('%m%d%H%M%Y.%S')
    return adb_shell_safe(f'date {new_str}', root=True)

def read_quest_state():
    """Walk QuestService to get WAINA23_1 sub-quest progress."""
    pid = get_pid()
    if not pid: return None
    mgr = frida.get_device_manager()
    d = mgr.add_remote_device('127.0.0.1:27047')
    sess = d.attach(pid)
    js = """
    rpc.exports = {
        read: function() {
            var il2cpp = Process.findModuleByName('libil2cpp.so');
            var addrs = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
            function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
            // We need a QuestService instance - hook to capture
            return {todo: 'hook QuestService and walk'};
        }
    };
    """
    sc = sess.create_script(js); sc.load()
    sess.detach()

if __name__ == '__main__':
    print(f"Phone PID: {get_pid()}")
    print(f"Phone date: {adb_shell_safe('date')}")
    print(f"Phone epoch: {current_phone_date()}")
    if len(sys.argv) > 1 and sys.argv[1] == '--advance':
        print("Advancing date by 1 day (root required)...")
        print(advance_date_one_day())
        print(f"New date: {adb_shell_safe('date')}")
    else:
        print("Run with --advance to bump date by 1 day")

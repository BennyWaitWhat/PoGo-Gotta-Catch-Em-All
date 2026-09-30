"""
Full orchestrator: kill PoGO, launch Pokemod, tap Start Service,
wait for both injectors to attach, then attach Frida and run extraction.

Live logging at every step. No long blocking waits.
"""
import subprocess, time, sys, json, threading, frida

ADB = ['adb', '-s', '100.98.158.56:5555']
START_BTN = (480, 1866)  # center of START SERVICE button
FRIDA_HOST = '127.0.0.1:31337'

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def adb(args, root=False, capture=True):
    if root:
        cmd = ADB + ['shell', 'su -c "' + args + '"']
    else:
        cmd = ADB + ['shell'] + args.split() if isinstance(args, str) else ADB + args
    r = subprocess.run(cmd, capture_output=capture, text=True, timeout=10)
    return r.stdout.strip() if capture else ''

def get_pogo_pid():
    out = adb('pidof com.nianticlabs.pokemongo', root=True)
    if not out: return None
    try: return int(out.split()[0])
    except: return None

def get_injector_count():
    out = adb('ps -A', root=True)
    return out.count('pokemod-injector')

def has_pgp_process():
    out = adb('ps -A', root=True)
    return ':pgp' in out

# Step 1: Clean state
log("=== STEP 1: Clean state ===")
log("Force-stopping PoGO...")
adb('am force-stop com.nianticlabs.pokemongo', root=True)
log("Force-stopping Pokemod...")
adb('am force-stop com.pokemod.app.public', root=True)
time.sleep(2)
log(f"PoGO PID after stop: {get_pogo_pid()} (should be None)")
log(f"Injector count: {get_injector_count()}")

# Step 2: Launch Pokemod
log("=== STEP 2: Launch Pokemod ===")
adb(['shell', 'am', 'start', '-n', 'com.pokemod.app.public/com.pokemod.app.activities.MainActivity'])
log("Waiting for Pokemod UI to load...")
for i in range(15):
    time.sleep(1)
    out = adb('dumpsys window 2>/dev/null | grep mCurrentFocus', root=True)
    if 'pokemod' in out.lower():
        log(f"  Pokemod focused after {i+1}s: {out[:100]}")
        break
else:
    log("  WARNING: Pokemod may not be focused")

# Step 3: Tap Start Service button
log("=== STEP 3: Tap START SERVICE button ===")
adb(['shell', 'input', 'tap', str(START_BTN[0]), str(START_BTN[1])])
log(f"Tapped at {START_BTN}")

# Step 4: Wait for PoGO + both injectors
log("=== STEP 4: Wait for PoGO spawn + both injectors ===")
pogo_pid = None
for i in range(60):
    time.sleep(1)
    pid = get_pogo_pid()
    inj = get_injector_count()
    pgp = has_pgp_process()
    if pid != pogo_pid:
        log(f"  t={i}s: PoGO PID={pid}, injectors={inj}, :pgp={pgp}")
        pogo_pid = pid
    if pid and inj >= 2 and pgp:
        log(f"  Ready! PoGO={pid}, injectors=2, :pgp running")
        break
    elif pid and inj >= 1 and i % 3 == 0:
        log(f"  t={i}s: Waiting... PoGO={pid}, injectors={inj}, :pgp={pgp}")
else:
    log("WARNING: Did not see complete state. Proceeding anyway.")

if not pogo_pid:
    log("ERROR: PoGO never started")
    sys.exit(1)

# Step 4.5: Just attach immediately - we're already at Ready state
log("=== STEP 4.5: Attaching IMMEDIATELY (Ready state reached) ===")

# Step 5: Forward port and attach via frida
log("=== STEP 5: Frida attach ===")
adb(['forward', 'tcp:31337', 'tcp:31337'])
time.sleep(1)

mgr = frida.get_device_manager()
dev = mgr.add_remote_device(FRIDA_HOST)
log(f"Attempting attach to PID {pogo_pid}...")

session = None
for attempt in range(20):
    try:
        cur = get_pogo_pid()
        if not cur:
            log(f"  Attempt {attempt+1}: no PID yet")
            time.sleep(0.5)
            continue
        session = dev.attach(cur)
        # Verify libil2cpp.so accessible by listing modules
        log(f"  Attached on attempt {attempt+1} to PID {cur}")
        pogo_pid = cur
        break
    except Exception as e:
        if attempt % 4 == 0:
            log(f"  Attempt {attempt+1} (pid={cur}): {e}")
        time.sleep(0.5)

if not session:
    log("ERROR: Could not attach after 20 attempts")
    sys.exit(1)

# Step 6: Load extraction script
log("=== STEP 6: Load extraction script ===")
results = []
done = threading.Event()
pokemon_received = []

def on_message(msg, data):
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, dict):
            t = p.get('type', '')
            if t == 'status':
                log(f"  [JS] {p['msg']}")
            elif t == 'error':
                log(f"  [JS ERROR] {p['msg']}")
            elif t == 'progress':
                log(f"  [JS PROGRESS] {p.get('count')}/{p.get('total')}")
            elif t == 'pokemon_data':
                pokemon_received.extend(p.get('data', []))
                log(f"  [JS POKEMON] Got {len(pokemon_received)} pokemon")
                with open('pokemon_dump.json', 'w') as f:
                    json.dump(pokemon_received, f, indent=2)
                log(f"  Saved to pokemon_dump.json")
            elif t == 'done':
                log(f"  [JS DONE] {p.get('msg', '')}")
                done.set()
            else:
                content = p.get('msg', p.get('data', p))
                log(f"  [JS {t}] {str(content)[:300]}")
            results.append(p)
        else:
            log(f"  [JS msg] {p}")
    elif msg['type'] == 'error':
        log(f"  [JS ERR] {msg.get('description', '?')}")
        if 'stack' in msg:
            log(f"    {msg['stack'][:300]}")

script_path = sys.argv[1] if len(sys.argv) > 1 else 'il2cpp_extract_v3.js'
log(f"Loading script: {script_path}")
with open(script_path, 'r') as f:
    src = f.read()
script = session.create_script(src)
script.on('message', on_message)
script.load()
log("Script loaded, monitoring for completion...")

# Wait with periodic status updates
start = time.time()
last_status = 0
while not done.is_set() and time.time() - start < 90:
    time.sleep(1)
    elapsed = int(time.time() - start)
    if elapsed - last_status >= 10:
        log(f"  ...waiting {elapsed}s, results so far: {len(results)}")
        last_status = elapsed

if done.is_set():
    log("=== SUCCESS ===")
else:
    log("=== TIMEOUT (90s) ===")

log(f"Total results: {len(results)}, pokemon: {len(pokemon_received)}")

try:
    session.detach()
    log("Detached cleanly")
except:
    log("Detach failed (session likely dead)")

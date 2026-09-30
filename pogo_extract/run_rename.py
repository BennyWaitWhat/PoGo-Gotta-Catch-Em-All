"""Rename pokemon by piggybacking on Pokemod's injector (which bypasses Niantic anti-cheat).

Flow (mirrors orchestrate.py):
  1. force-stop pogo + pokemod
  2. launch pokemod, tap Start Service
  3. wait for pogo PID + 2 pokemod-injectors + :pgp
  4. attach Frida (it works because pokemod-injector neutralized anti-cheat)
  5. load rename_pokemon.js
  6. wait for user to navigate to storage so heap is populated with pokemon
  7. invoke rename rpc
"""
import frida, json, subprocess, sys, time, threading

UID_TEST = 0x31c43fb6a058ea49  # CP 500 ditto, 28.9% IV - lowest
NICK_TEST = "TEST_RENAME"

START_BTN = (480, 1866)  # Pokemod "Start Service" coords from orchestrate.py

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def adb(*args, root=False):
    cmd = ['adb', 'shell']
    if root:
        cmd += ['su', '-c', ' '.join(args)]
    else:
        cmd += list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return r.stdout.strip()

def get_pogo_pid():
    out = adb('pidof', 'com.nianticlabs.pokemongo')
    if not out: return None
    try: return int(out.split()[0])
    except: return None

def get_injector_count():
    out = adb('ps', '-A')
    return out.count('pokemod-injector')

def has_pgp():
    return ':pgp' in adb('ps', '-A')

def wait_state():
    log("Waiting for PoGo + injectors + :pgp...")
    pogo_pid = None
    for i in range(60):
        time.sleep(1)
        pid = get_pogo_pid()
        inj = get_injector_count()
        pgp = has_pgp()
        if pid != pogo_pid:
            log(f"  t={i}s: PoGO PID={pid} inj={inj} :pgp={pgp}")
            pogo_pid = pid
        if pid and inj >= 2 and pgp:
            log(f"  Ready: PID={pid}")
            return pid
    return pogo_pid

def on_msg(message, data):
    if message.get("type") == "send":
        p = message["payload"]
        log(f"  [JS {p.get('type','msg').upper()}] {p.get('msg', json.dumps(p))[:300]}")
    elif message.get("type") == "error":
        log(f"  [FRIDA-ERR] {message.get('description')}")

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"

    log("=== Step 1: Clean state ===")
    adb('am', 'force-stop', 'com.nianticlabs.pokemongo')
    adb('am', 'force-stop', 'com.pokemod.app.public')
    time.sleep(2)
    log(f"  PoGo PID: {get_pogo_pid()} (None expected)")

    log("=== Step 2: Launch Pokemod ===")
    subprocess.run(['adb','shell','am','start','-n','com.pokemod.app.public/com.pokemod.app.activities.MainActivity'],
                   capture_output=True, timeout=10)
    time.sleep(3)

    log("=== Step 3: Tap Start Service ===")
    subprocess.run(['adb','shell','input','tap', str(START_BTN[0]), str(START_BTN[1])],
                   capture_output=True, timeout=10)
    log(f"  tapped {START_BTN}")

    pogo_pid = wait_state()
    if not pogo_pid:
        log("ERROR: PoGo never started"); return

    log("=== Step 4: Frida attach ===")
    subprocess.run(['adb','forward','tcp:27042','tcp:27042'], capture_output=True, timeout=5)
    time.sleep(1)
    mgr = frida.get_device_manager()
    try:
        dev = mgr.add_remote_device("127.0.0.1:27042")
    except Exception:
        dev = frida.get_usb_device(timeout=10)

    session = None
    for attempt in range(20):
        try:
            cur = get_pogo_pid()
            if not cur:
                time.sleep(0.5); continue
            session = dev.attach(cur)
            log(f"  Attached PID={cur} (attempt {attempt+1})")
            pogo_pid = cur
            break
        except Exception as e:
            if attempt % 3 == 0:
                log(f"  attempt {attempt+1} (pid={cur}): {e}")
            time.sleep(0.5)

    if not session:
        log("ERROR: Could not attach"); return

    log("=== Step 5: Load rename script ===")
    src = open("rename_pokemon.js","r",encoding="utf-8").read()
    script = session.create_script(src)
    script.on("message", on_msg)
    script.load()

    log("=== Step 6: Wait for heap to populate ===")
    log("  USER: log into PoGo if prompted, get to map screen,")
    log("  then OPEN YOUR POKEMON STORAGE so dittos are loaded into RAM")
    n_initial = 0
    for i in range(60):
        try:
            n = script.exports_sync.count_pokemon()
            if n != n_initial:
                log(f"  PokemonProtos in heap: {n}")
                n_initial = n
            if n > 1000:
                log("  -> heap has full collection, ready")
                break
        except Exception as e:
            log(f"  not ready: {e}")
        time.sleep(5)

    if mode == "test":
        uid = UID_TEST; nick = NICK_TEST
        low = uid & 0xFFFFFFFF
        high = (uid >> 32) & 0xFFFFFFFF
        if low > 0x7FFFFFFF: low -= 0x100000000
        if high > 0x7FFFFFFF: high -= 0x100000000
        log(f"\n=== Step 7: Rename uid 0x{uid:016x} -> {nick!r} ===")
        result = script.exports_sync.rename(low, high, nick)
        log(f"RESULT: {json.dumps(result, indent=2)}")

    log("\nKeeping session 15s for promise to resolve...")
    time.sleep(15)
    try: session.detach()
    except: pass

if __name__ == "__main__":
    main()

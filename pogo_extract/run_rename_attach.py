"""Attach to currently-running PoGo (already injected by Pokemod) and rename a ditto.

Prerequisites: user manually launched Pokemod -> tapped Start Service ->
got into game -> opened Pokemon storage so heap is populated.
"""
import frida, json, subprocess, sys, time

UID_TEST = 0x31c43fb6a058ea49  # CP 500 ditto, 28.9% IV
NICK_TEST = "TEST_RENAME"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def get_pid():
    r = subprocess.run(['adb','shell','pidof','com.nianticlabs.pokemongo'],
                       capture_output=True, text=True, timeout=10)
    s = r.stdout.strip()
    return int(s.split()[0]) if s else None

def on_msg(message, data):
    if message.get("type") == "send":
        p = message["payload"]
        log(f"  [JS {p.get('type','msg').upper()}] {str(p.get('msg', json.dumps(p)))[:400]}")
    elif message.get("type") == "error":
        log(f"  [FRIDA-ERR] {message.get('description')}")

def main():
    pid = get_pid()
    if not pid:
        log("PoGo not running. Open Pokemod and tap Start Service first.")
        return
    log(f"PoGo PID: {pid}")

    subprocess.run(['adb','forward','tcp:27042','tcp:27042'], capture_output=True, timeout=5)
    time.sleep(0.5)

    mgr = frida.get_device_manager()
    try:
        dev = mgr.add_remote_device("127.0.0.1:27042")
        log("Using remote device 127.0.0.1:27042")
    except Exception:
        dev = frida.get_usb_device(timeout=10)
        log(f"Using USB device: {dev.name}")

    session = None
    for attempt in range(15):
        cur = get_pid()
        if not cur:
            time.sleep(0.5); continue
        try:
            session = dev.attach(cur)
            log(f"Attached PID={cur} (attempt {attempt+1})")
            pid = cur
            break
        except Exception as e:
            if attempt % 3 == 0:
                log(f"  attempt {attempt+1} (pid={cur}): {e}")
            time.sleep(1)
    if not session:
        log("ERROR: Could not attach"); return

    log("Loading rename_pokemon.js...")
    src = open("rename_pokemon.js","r",encoding="utf-8").read()
    script = session.create_script(src)
    script.on("message", on_msg)
    script.load()
    log("Script loaded")

    # Probe init status
    log("Probing init...")
    for i in range(20):
        st = script.exports_sync.init_status()
        log(f"  init: {st}")
        if st.get("ready"): break
        time.sleep(2)

    # Probe heap
    log("Probing heap...")
    last = -1
    for i in range(8):
        r = script.exports_sync.count_pokemon()
        n = r.get("count", 0) if isinstance(r, dict) else 0
        log(f"  PokemonProtos: {n}")
        if n > 1000 and n == last: break
        last = n
        time.sleep(3)

    uid = UID_TEST; nick = NICK_TEST
    low = uid & 0xFFFFFFFF
    high = (uid >> 32) & 0xFFFFFFFF
    if low > 0x7FFFFFFF: low -= 0x100000000
    if high > 0x7FFFFFFF: high -= 0x100000000
    log(f"\n=== Rename uid 0x{uid:016x} -> {nick!r} ===")
    result = script.exports_sync.rename(low, high, nick)
    log(f"RESULT: {json.dumps(result, indent=2)}")

    log("\nKeeping session 15s for promise to resolve...")
    time.sleep(15)
    try: session.detach()
    except: pass

if __name__ == "__main__":
    main()

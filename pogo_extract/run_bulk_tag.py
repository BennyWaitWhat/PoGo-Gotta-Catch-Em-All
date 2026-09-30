"""Bulk-tag PoGo pokemon via the working Frida recipe.

Usage:
  python run_bulk_tag.py discover         # phase 1: enumerate methods + index pokemon, no writes
  python run_bulk_tag.py tag-test          # phase 2: tag ONE pokemon as a smoke test
  python run_bulk_tag.py tag-tx            # phase 3: tag all 858 transferables with TX
  python run_bulk_tag.py tag-all           # phase 4: apply full desired_tags.csv

Recipe (executed in --recipe mode):
  force-stop PoGo
  setenforce 0
  start frida-server
  launch PoGo via am start
  wait 5s for libil2cpp.so load
  attach
"""
import argparse, csv, frida, json, os, subprocess, sys, time

DEVICE = "4A181FDAP0013G"  # Tailscale offline; using USB
PKG = "com.nianticlabs.pokemongo"
ACTIVITY = "com.nianticproject.holoholo.libholoholo.unity.UnityMainActivity"

def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def adb(*args, root=False):
    cmd = ["adb","-s",DEVICE,"shell"]
    if root:
        cmd += ["su","-c"," ".join(args)]
    else:
        cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=20)

def has_il2cpp(pid):
    """Check if libil2cpp.so is loaded in given PID"""
    r = adb(f"grep -c libil2cpp /proc/{pid}/maps 2>/dev/null", root=True)
    try: return int(r.stdout.strip()) > 0
    except: return False

def setup_recipe():
    log("force-stop PoGo")
    adb("am","force-stop",PKG)
    time.sleep(1)
    log("setenforce 0")
    adb("setenforce 0", root=True)
    log("ensure frida-server running")
    r = adb("pidof frida-server", root=True)
    if not r.stdout.strip():
        adb("nohup /data/local/tmp/frida-server >/dev/null 2>&1 &", root=True)
        time.sleep(1)
    log("launch PoGo via monkey")
    adb("monkey","-p",PKG,"-c","android.intent.category.LAUNCHER","1")

    # Wait for stable PID with libil2cpp loaded
    log("polling for libil2cpp.so + stable PID...")
    last_pid = None
    stable_count = 0
    for i in range(40):  # 40s max
        time.sleep(1)
        pid = get_pid()
        if not pid:
            stable_count = 0
            continue
        if pid != last_pid:
            log(f"  t={i}s PID changed: {last_pid} -> {pid}")
            last_pid = pid
            stable_count = 0
            continue
        # Same PID - check libil2cpp
        if has_il2cpp(pid):
            stable_count += 1
            if stable_count >= 3:  # PID stable + il2cpp loaded for 3s
                log(f"  ready: PID {pid} stable with libil2cpp.so loaded")
                return pid
            log(f"  t={i}s PID {pid} stable {stable_count}s with il2cpp")
        else:
            log(f"  t={i}s PID {pid} - waiting for libil2cpp")
    raise RuntimeError("PoGo never reached stable state with libil2cpp")

def get_pid():
    r = adb("pidof",PKG)
    s = r.stdout.strip()
    return int(s.split()[0]) if s else None

def attach(pid):
    subprocess.run(["adb","-s",DEVICE,"forward","tcp:27042","tcp:27042"], capture_output=True)
    time.sleep(0.5)
    mgr = frida.get_device_manager()
    try:
        d = mgr.add_remote_device("127.0.0.1:27042")
    except Exception:
        d = frida.get_usb_device(timeout=5)
    last_err = None
    for attempt in range(8):
        # Always re-fetch live PID; PoGo may have respawned
        cur = get_pid()
        if not cur:
            time.sleep(1)
            continue
        try:
            log(f"attach PID {cur} (attempt {attempt+1})")
            return d.attach(cur)
        except Exception as e:
            last_err = e
            if attempt % 2 == 0:
                log(f"  attempt {attempt+1} failed: {e}")
            time.sleep(1.5)
    raise last_err or RuntimeError("could not attach")

def make_msg_handler():
    methods_buf = []
    def on_msg(message, data):
        if message.get("type") == "send":
            p = message["payload"]
            t = p.get("type", "msg")
            if t == "methods":
                methods_buf.extend(p.get("data", []))
                log(f"  [JS] {len(p.get('data',[]))} methods on TaggingRpcService")
            else:
                log(f"  [JS {t}] {str(p.get('msg', json.dumps(p)))[:300]}")
        elif message.get("type") == "error":
            log(f"  [FRIDA-ERR] {message.get('description')}")
    return on_msg, methods_buf

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["discover","add-tag-test","get-tags-test","list-tags","find-instances","add-tag-verified","count-tags","hook-instance","tag-test","tag-tx","tag-all"])
    ap.add_argument("--recipe", action="store_true",
                    help="Run the force-stop + setenforce + launch recipe before attach (default)")
    ap.add_argument("--no-recipe", dest="recipe", action="store_false")
    ap.set_defaults(recipe=True)
    args = ap.parse_args()

    if args.recipe:
        pid = setup_recipe()
    else:
        pid = get_pid()
        if not pid:
            raise RuntimeError("PoGo not running and --no-recipe; start it first")
    log(f"PID {pid}")

    sess = attach(pid)
    src = open("bulk_tag.js","r",encoding="utf-8").read()
    script = sess.create_script(src)
    on_msg, methods_buf = make_msg_handler()
    script.on("message", on_msg)
    script.load()
    log("script loaded")

    # phase 1: init + discover
    log("calling init...")
    st = script.exports_sync.init_status()
    log(f"  init: {st}")
    if not st.get("ready"):
        log(f"  init failed: {st.get('err')}")
        return

    log("discovering tag service methods...")
    script.exports_sync.discover_methods()

    if args.mode not in ("find-instances","add-tag-verified"):
        log("indexing pokemon protos in heap...")
        res = script.exports_sync.index_pokemon()
        log(f"  index: {res}")

    if args.mode == "discover":
        # save methods report
        with open("tagging_service_methods.json","w") as f:
            json.dump(methods_buf, f, indent=2)
        log(f"saved {len(methods_buf)} methods to tagging_service_methods.json")

    elif args.mode == "add-tag-test":
        # Try color 1 (color 0 was NullRef - probably means "unset" enum)
        log("CALLING AddTag('TX-TEST', 1)...")
        result = script.exports_sync.add_tag_test("TX-TEST", 1)
        log(f"  result: {json.dumps(result, indent=2)}")
        log("If success, check PoGo > Pokemon storage > tags - 'TX-TEST' should appear")

    elif args.mode == "hook-instance":
        log("Hooking get_NumberOfTags...")
        result = script.exports_sync.hook_for_real_instance(60)
        log(f"  hook: {result}")
        log("INTERACT WITH POGO NOW: scroll the tag manager, tap tags, etc. for 60 seconds...")
        for i in range(60, 0, -10):
            log(f"  {i}s remaining - keep interacting")
            time.sleep(10)
        log("Collecting captured instances...")
        result = script.exports_sync.get_captured()
        log(json.dumps(result, indent=2))

    elif args.mode == "count-tags":
        log("Calling get_NumberOfTags() on each instance...")
        result = script.exports_sync.count_tags()
        log(json.dumps(result, indent=2))

    elif args.mode == "find-instances":
        log("Finding all TaggingRpcService instances and their tag counts:")
        result = script.exports_sync.find_all_instances()
        log(json.dumps(result, indent=2))

    elif args.mode == "add-tag-verified":
        log("AddTag with before/after count check on each instance...")
        result = script.exports_sync.add_tag_verified("AUTO-TX", 2)
        log(json.dumps(result, indent=2))

    elif args.mode == "list-tags":
        log("Service instance fields:")
        result = script.exports_sync.list_all_tag_definitions()
        log(f"  {json.dumps(result, indent=2)}")

    elif args.mode == "get-tags-test":
        # Use a known existing pokemon UID - first ditto
        with open("desired_tags.csv","r",encoding="utf-8",newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                if row["species_name"] == "Ditto":
                    uid = int(row["uid_signed"])
                    low = uid & 0xFFFFFFFF
                    high = (uid >> 32) & 0xFFFFFFFF
                    if low > 0x7FFFFFFF: low -= 0x100000000
                    if high > 0x7FFFFFFF: high -= 0x100000000
                    log(f"GetAllTags on Ditto uid 0x{uid&0xFFFFFFFFFFFFFFFF:016x}")
                    result = script.exports_sync.get_all_tags_test(low, high)
                    log(f"  result: {json.dumps(result, indent=2)}")
                    break

    elif args.mode == "tag-test":
        # tag one transferable ditto with TX
        with open("desired_tags.csv","r",encoding="utf-8",newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                if row["species_name"] == "Ditto" and "TX" in row["tags_pipe_separated"]:
                    uid = int(row["uid_signed"])
                    low = uid & 0xFFFFFFFF
                    high = (uid >> 32) & 0xFFFFFFFF
                    if low > 0x7FFFFFFF: low -= 0x100000000
                    if high > 0x7FFFFFFF: high -= 0x100000000
                    log(f"test-tagging Ditto uid 0x{uid&0xFFFFFFFFFFFFFFFF:016x}")
                    result = script.exports_sync.tag_one(low, high, [])
                    log(f"  result: {result}")
                    break

    log("session alive 30s for promise(s) to settle")
    time.sleep(30)
    try: sess.detach()
    except: pass

if __name__ == "__main__":
    main()

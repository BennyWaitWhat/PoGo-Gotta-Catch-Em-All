"""Run nickname_search.js against PoGo and save results."""
import frida
import json
import subprocess
import sys
import time

results = {"class_matches": [], "method_matches": [], "status": [], "img_done": [], "errors": []}
done = False


def get_pogo_pid():
    r = subprocess.run(
        ["adb", "shell", "su", "-c", "pidof com.nianticlabs.pokemongo"],
        capture_output=True, text=True
    )
    s = r.stdout.strip()
    if not s:
        return None
    return int(s.split()[0])


def unfreeze_pogo(pid):
    path = f"/sys/fs/cgroup/apps/uid_10468/pid_{pid}/cgroup.freeze"
    subprocess.run(["adb", "shell", "su", "-c", f"echo 0 > {path}"], capture_output=True)

def on_message(message, data):
    global done
    if message.get("type") == "send":
        payload = message["payload"]
        ptype = payload.get("type")
        if ptype == "status":
            print("[STATUS]", payload.get("msg"))
            results["status"].append(payload.get("msg"))
        elif ptype == "img_done":
            results["img_done"].append(payload)
            if payload.get("classMatches", 0) > 0 or payload.get("methodMatches", 0) > 0 or payload["idx"] % 10 == 0:
                print(f"[IMG {payload['idx']}/{payload['total']}] {payload['name']} cls={payload['classes']} cm={payload['classMatches']} mm={payload['methodMatches']}")
        elif ptype == "img_err":
            print(f"[IMG-ERR] {payload['name']}: {payload['err']}")
            results["errors"].append(payload)
        elif ptype == "class_matches":
            results["class_matches"] = payload.get("data", [])
            print(f"[CLASSES] {len(results['class_matches'])} matched")
        elif ptype == "method_matches":
            results["method_matches"] = payload.get("data", [])
            print(f"[METHODS] {len(results['method_matches'])} matched")
        elif ptype == "done":
            print("[DONE]", payload.get("msg"))
            done = True
        elif ptype == "error":
            print("[ERR]", payload.get("msg"))
            results["errors"].append(payload.get("msg"))
    elif message.get("type") == "error":
        print("[FRIDA-ERR]", message.get("description"))
        results["errors"].append(message.get("description"))


def main():
    # Use the remote device (forwarded via adb) to match the existing pipeline.
    mgr = frida.get_device_manager()
    try:
        d = mgr.add_remote_device("127.0.0.1:31337")
    except Exception:
        d = frida.get_usb_device(timeout=30)
    print(f"Device: {d.name}")

    pid = get_pogo_pid()
    if pid is None:
        raise RuntimeError("PoGo not running")
    print(f"PoGo PID: {pid}")
    unfreeze_pogo(pid)

    last_err = None
    for attempt in range(5):
        try:
            unfreeze_pogo(pid)
            session = d.attach(pid)
            print(f"Attached to PID {pid} (attempt {attempt+1})")
            break
        except Exception as e:
            last_err = e
            print(f"attach attempt {attempt+1} failed: {e}; retry in 3s")
            time.sleep(3)
    else:
        raise last_err

    with open("nickname_search.js", "r", encoding="utf-8") as f:
        src = f.read()

    script = session.create_script(src)
    script.on("message", on_message)
    script.load()

    timeout = 180
    waited = 0
    while not done and waited < timeout:
        time.sleep(1)
        waited += 1
        # Re-unfreeze every 2s to keep the process running
        if waited % 2 == 0:
            unfreeze_pogo(pid)

    with open("nickname_search_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Saved nickname_search_results.json: {len(results['class_matches'])} classes, {len(results['method_matches'])} methods")
    session.detach()


if __name__ == "__main__":
    main()

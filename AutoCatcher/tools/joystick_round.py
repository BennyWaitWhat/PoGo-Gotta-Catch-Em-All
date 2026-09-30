"""Load new GPS Joystick speed presets safely and restart the route (the joystick reads settings only at start).

  python tools/joystick_round.py WALK JOG RUN [SPEED_OFFSET]      e.g. 10.7 11.1 11.6 0
  python tools/joystick_round.py mode walking|jogging|running      tap a speed button on the overlay (live)

Safe order (the real GPS must never reach PoGo): record the spot -> edit presets in the joystick's Settings ->
close PoGo -> STOP intent + force-stop the joystick (kills the stale process) -> TELEPORT to the recorded spot
(starts a fresh process that loads the new presets) -> ROUTE "NY Long" -> Home -> reopen PoGo.
Every step is verified; any surprise aborts before the next step.
"""
import html
import math
import os
import re
import subprocess
import sys
import time

DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")   # cloud: the Tailscale bridge exports ADB_TARGET
PKG = "com.theappninjas.fakegpsjoystick"
ROUTE = "NY Long"


def sh(cmd):
    return subprocess.run(["adb", "-s", DEV, "shell", cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout or ""


def pos():
    m = re.search(r"Location\[gps ([-0-9.]+),([-0-9.]+) .*?vel=([0-9.]+)", sh("dumpsys location | grep -m1 'last mock location'"))
    return (float(m[1]), float(m[2]), float(m[3])) if m else None


def meters(a, b):
    r = 6371008.8
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    return 2 * r * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


def nodes(windows=False):
    s = sh(f"uiautomator dump {'--windows ' if windows else ''}/data/local/tmp/u.xml >/dev/null 2>&1; cat /data/local/tmp/u.xml")
    out = []
    for m in re.finditer(r"<node ([^>]*)>", s):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(1)))
        b = list(map(int, re.findall(r"\d+", a.get("bounds", "[0,0][0,0]"))))
        out.append(dict(t=html.unescape(a.get("text", "")), rid=a.get("resource-id", "").split("/")[-1],
                        cls=a.get("class", "").split(".")[-1], pkg=a.get("package", ""), sel=a.get("selected"), b=b))
    return out


def tap(b):
    sh(f"input tap {(b[0] + b[2]) // 2} {(b[1] + b[3]) // 2}")


def die(msg):
    print("ABORT:", msg, flush=True)
    sys.exit(1)


def to_top():
    sh("for i in 1 2 3 4 5 6; do input swipe 640 800 640 2500 120; done")   # flings are fine for reaching the top
    time.sleep(0.8)


def find(label, tries=30):
    """Slow 600 px drags (1.2 s, no fling) from wherever the list is; wrap to the top once if the end is reached."""
    wrapped, prev = False, None
    for _ in range(tries):
        d = nodes()
        hit = [n for n in d if n["t"] == label]
        if hit and 300 < hit[0]["b"][1] < 2550:
            return hit[0]
        sig = tuple(n["t"] for n in d if n["t"])
        if sig == prev:                      # the list did not move: at the bottom
            if wrapped:
                break
            to_top()
            wrapped = True
        prev = sig
        sh("input swipe 640 2000 640 1400 1200")
        time.sleep(0.4)
    die(f"setting '{label}' not found")


def wait_for(pred, secs=4.0):
    end = time.time() + secs
    while time.time() < end:
        d = nodes()
        if pred(d):
            return d
        time.sleep(0.3)
    return None


def set_value(label, val):
    row = find(label)
    tap(row["b"])
    d = wait_for(lambda d: any(n["cls"] == "EditText" for n in d))
    if not d:
        die(f"no dialog for {label}")
    tap([n for n in d if n["cls"] == "EditText"][0]["b"])
    sh(f"sleep 0.2; input keyevent KEYCODE_MOVE_END; for i in 1 2 3 4 5 6 7 8 9 10; do input keyevent KEYCODE_DEL; done; input text {val}")
    d = wait_for(lambda d: any(n["cls"] == "EditText" and n["t"] == val for n in d), 3)
    if not d:
        sh("input keyevent KEYCODE_BACK; input keyevent KEYCODE_BACK")
        die(f"{label}: could not type {val}")
    tap([n for n in d if n["t"] == "OK"][0]["b"])
    if not wait_for(lambda d: not any(n["cls"] == "EditText" for n in d), 3):
        die(f"{label}: dialog did not close")
    shown = wait_for(lambda d: any(n["t"] == label for n in d), 2)
    print(f"   {label} -> {val}", flush=True)


def read_values():
    got = {}
    for _ in range(12):
        d = sorted(nodes(), key=lambda n: n["b"][1])
        for i, n in enumerate(d):
            if n["t"] in ("Walking Speed", "Jogging Speed", "Running Speed", "Speed Offset", "Process Interval", "Update Interval"):
                later = [x["t"] for x in d[i + 1:i + 4] if re.search(r"(km/h|ms)$", x["t"])]
                if later:
                    got[n["t"]] = later[0]
        if len(got) >= 6:
            break
        sh("input swipe 640 2300 640 1300 350")
        time.sleep(0.6)
    return got


def mode(which):
    for _ in range(3):
        btn = {n["rid"]: n for n in nodes(windows=True) if PKG in n["pkg"] and n["rid"].endswith("_button")}
        if f"{which}_button" in btn:
            tap(btn[f"{which}_button"]["b"])
            time.sleep(1.0)
            sel = {n["rid"]: n["sel"] for n in nodes(windows=True) if PKG in n["pkg"] and n["rid"] in ("walking_button", "jogging_button", "running_button")}
            print("speed buttons:", sel, flush=True)
            return sel.get(f"{which}_button") == "true"
        time.sleep(1)
    die("joystick speed buttons not on screen")


def main():
    if "Pixel" not in sh("getprop ro.product.model"):
        die("not the phone")
    if sys.argv[1] == "mode":
        ok = mode(sys.argv[2])
        print("mode", sys.argv[2], "selected" if ok else "NOT selected", flush=True)
        return
    walk, jog, run = sys.argv[1:4]
    off = sys.argv[4] if len(sys.argv) > 4 else None
    t0 = time.time()
    T = lambda: f"[{time.time() - t0:5.1f}s]"
    print(T(), "1. open joystick Settings and set presets", flush=True)
    sh(f"su -c 'am start -n {PKG}/.ui.settings.SettingsActivity' >/dev/null 2>&1")
    time.sleep(1.3)
    sh("for i in 1 2 3 4 5; do input swipe 640 700 640 2600 150; done")
    time.sleep(0.6)
    for label, val in (("Walking Speed", walk), ("Jogging Speed", jog), ("Running Speed", run)):
        set_value(label, val)
    if off is not None:
        set_value("Speed Offset", off)
    sh("for i in 1 2 3 4 5; do input swipe 640 700 640 2600 150; done")
    time.sleep(0.6)
    vals = read_values()
    print(T(), "   saved:", vals, flush=True)
    want = {"Walking Speed": f"{float(walk):.1f} km/h", "Jogging Speed": f"{float(jog):.1f} km/h", "Running Speed": f"{float(run):.1f} km/h"}
    if any(vals.get(k) != v for k, v in want.items()):
        die(f"presets not saved as asked: {vals}")
    spot = pos()
    print(T(), "2. spot", spot, flush=True)
    sh("am force-stop com.nianticlabs.pokemongo")
    time.sleep(1)
    if sh("pidof com.nianticlabs.pokemongo").strip():
        die("PoGo still running")
    spot = pos() or spot
    print(T(), "3. PoGo closed; spot at close", spot, flush=True)
    sh("am start-foreground-service -a theappninjas.gpsjoystick.STOP")
    time.sleep(2)
    sh(f"am force-stop {PKG}")
    time.sleep(1)
    if sh("ps -A | grep fakegpsjoy").strip():
        die("joystick still running")
    print(T(), "4. joystick stopped", flush=True)
    sh(f"am start-foreground-service -a theappninjas.gpsjoystick.TELEPORT --ef lat {spot[0]} --ef lng {spot[1]}")
    q = None
    for _ in range(20):
        time.sleep(1)
        q = pos()
        if q and sh(f"pidof {PKG}:overlay").strip() and meters(q, spot) < 15:
            break
    else:
        die(f"fresh joystick not at the spot: {q}")
    print(T(), f"5. fresh joystick pid {sh(f'pidof {PKG}:overlay').strip()} at {meters(q, spot):.1f} m from the spot", flush=True)
    sh(f'am start-foreground-service -a theappninjas.gpsjoystick.ROUTE --es name "{ROUTE}"')
    time.sleep(4)
    q2 = pos()
    print(T(), f"6. route started: moved {meters(q, q2):.1f} m in 4 s, label {q2[2] * 3.6:.1f} km/h", flush=True)
    sh("input keyevent KEYCODE_HOME")
    time.sleep(1.5)
    sh("monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1")
    time.sleep(3)
    focus = sh("dumpsys window | grep -m1 mCurrentFocus")
    print(T(), "7. PoGo reopened:", "yes" if "pokemongo" in focus else focus.strip(), "pid", sh("pidof com.nianticlabs.pokemongo").strip(), flush=True)


if __name__ == "__main__":
    main()

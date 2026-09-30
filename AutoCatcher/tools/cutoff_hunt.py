"""Exact walking-credit cutoff, driven entirely through the GPS Joystick Pro API, judged on the game's own record.

  python tools/cutoff_hunt.py LO HI [RESOLUTION=0.05]    LO = a speed that is credited, HI = one that is not

Protocol (tamper-proof):
  * WALK a fresh dead-straight line (6 x 3 km legs along Manhattan's avenue axis) -- credited distance can be
    compared with the distance moved one to one.
  * HIDE the joystick overlay for the whole run (no accidental speed taps); SHOW it again at the end.
  * Every credit batch is caught the moment PlayerStatsProto.KmWalked is parsed (read-only hook).
  * Right after a batch: SPEED <test value>. The next batch is mixed (not judged); the one after is judged:
    credited >= 80% of the GPS distance moved = PASS, <= 20% = FAIL, in between = judge one more batch.
  * Every fix is checked: if the fix's speed label is off the test value, the window is invalid, SPEED is re-sent
    and the speed is re-tested.
  * After bisection converges, LO and HI are re-tested once each as confirmation.
"""
import math
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402
import dump_game_limits as dl  # noqa: E402

DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")   # cloud: the Tailscale bridge exports ADB_TARGET
JS = dl.JS.split("rpc.exports = {")[0] + r"""
var EV = [], KMOFF = -1, KMTE = 0, LASTV = -1;
rpc.exports = {
  install: function () {
    var ps = findClass('holo-protos.dll', 'PlayerStatsProto'); if (!ps) return 'no class';
    fieldsOf(ps).forEach(function (fd) { if (fd.name === 'KmWalked') { KMOFF = fd.off; KMTE = fd.te; } });
    var getM = new NativeFunction(EX['il2cpp_class_get_methods'], 'pointer', ['pointer', 'pointer'], PROP);
    var mName = new NativeFunction(EX['il2cpp_method_get_name'], 'pointer', ['pointer'], PROP);
    var mArgs = new NativeFunction(EX['il2cpp_method_get_param_count'], 'uint32', ['pointer'], PROP);
    var it = Memory.alloc(PS); it.writePointer(NULL); var m, n = 0;
    while ((m = getM(ps, it)) && !m.isNull()) {
      var nm = cs(mName(m));   /* the parse path is an obfuscated 1-arg method (mxx/mxy on 0.429.1): hook every 1-arg method but these */
      if (mArgs(m) !== 1 || ['WriteTo', 'Equals', '.ctor', 'CalculateSize'].indexOf(nm) >= 0) continue;
      Interceptor.attach(m.readPointer(), {onEnter: function (a) { this.s = a[0]; }, onLeave: function () {
        try { var v = KMTE === 0x0d ? this.s.add(KMOFF).readDouble() : this.s.add(KMOFF).readFloat();
              if (v > LASTV + 1e-6) { LASTV = v; EV.push({t: Date.now(), v: v}); } } catch (e) {} }});
      n++;
    }
    return {hooks: n, kmType: KMTE};
  },
  drain: function () { var e = EV; EV = []; return e; }
};
"""


def adb(cmd):
    return subprocess.run(["adb", "-s", DEV, "shell", cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout or ""


def fix():
    m = re.search(r"Location\[gps ([-0-9.]+),([-0-9.]+) .*?et=\+(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?(?:(\d+)ms)?.*?vel=([0-9.]+)",
                  adb("dumpsys location | grep -m1 'last mock location'"))
    if not m:
        return None
    # et= is uptime and gains a day field after 24 h ("+1d21h18m28s184ms"); without (\d+)d the whole match came back 0
    et = int(m[3] or 0) * 86400 + int(m[4] or 0) * 3600 + int(m[5] or 0) * 60 + int(m[6] or 0) + int(m[7] or 0) / 1000
    return (float(m[1]), float(m[2]), et, float(m[8]) * 3.6)


def meters(a, b):
    r = 6371008.8
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl_ = math.radians(b[1] - a[1])
    return 2 * r * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl_ / 2) ** 2))


def api(action, extra=""):
    adb(f"am start-foreground-service -a theappninjas.gpsjoystick.{action} {extra}")


def walk_line(speed_kmh):
    p = fix()
    a = (p[0], p[1])
    b = math.radians(29.0)
    ll = 3000.0
    bb = (a[0] + ll * math.cos(b) / 111320.0, a[1] + ll * math.sin(b) / (111320.0 * math.cos(math.radians(a[0]))))
    wp = ";".join(f"{x[0]:.6f},{x[1]:.6f}" for x in (a, bb, a, bb, a, bb))
    api("WALK", f'--es waypoints "{wp}" --ef speed {speed_kmh}')
    return a, bb


def main():
    lo, hi = float(sys.argv[1]), float(sys.argv[2])
    res = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05
    if "Pixel" not in adb("getprop ro.product.model"):
        sys.exit("not the phone")
    if not adb("pidof com.theappninjas.fakegpsjoystick:overlay").strip() or not fix():
        sys.exit("joystick not spoofing -- refusing (PoGo must never see the real GPS)")
    a, b = walk_line(lo)
    api("HIDE")
    print(f"{time.strftime('%H:%M:%S')} WALK straight line {a} -> {b} x6 legs; joystick controls HIDDEN", flush=True)
    pg.wait_ready_to_attach(timeout_s=240, min_age_s=45)
    sess, pid = pg.get_session()
    sc = sess.create_script(JS)
    sc.load()
    print(f"attached pid {pid}; hooks {sc.exports_sync.install()}; bisect {lo} (credited) .. {hi} (not), resolution {res}", flush=True)
    queue_confirm, confirmed = None, []
    MIN_WIN = 45                       # s: shortest batch-to-batch window worth judging
    cur, phase, tested = lo, "switch", []
    t_switch = w_t0 = w_km0 = None
    moved, labels, off_speed, last, last_ev, km_now, next_tick = 0.0, [], 0, fix(), None, None, time.time() + 15
    api("SPEED", f"--ef speed {cur}")

    def choose():
        nonlocal queue_confirm
        if hi - lo > res:
            return round((lo + hi) / 2 / 0.01) * 0.01
        if queue_confirm is None:
            queue_confirm = [lo, hi]
        return queue_confirm.pop(0) if queue_confirm else None

    def open_window(t, v):
        nonlocal w_t0, w_km0, moved, labels, off_speed
        w_t0, w_km0, moved, labels, off_speed = t, v, 0.0, [], 0

    try:
        while True:
            for e in sc.exports_sync.drain():
                t, v = e["t"] / 1000, e["v"]
                km_now = v
                ts = time.strftime("%H:%M:%S", time.localtime(t))
                gap = f"{t - last_ev[0]:.0f} s after the previous batch, +{(v - last_ev[1]) * 1000:.0f} m" if last_ev else "first batch seen"
                print(f"{ts} batch: KmWalked {v:.3f} ({gap})", flush=True)
                last_ev = (t, v)
                if phase == "judge" and t - w_t0 >= MIN_WIN:
                    got, dt = (v - w_km0) * 1000, t - w_t0
                    real = moved / dt * 3.6 if dt else 0
                    lab = (min(labels), max(labels)) if labels else (0, 0)
                    head = (f"{ts} JUDGE SET {cur:.2f}: credited {got:.0f} m vs moved (GPS) {moved:.0f} m over {dt:.0f} s"
                            f" | real {real:.2f} km/h, label {lab[0]:.2f}..{lab[1]:.2f}")
                    ratio = got / moved if moved > 1 else 0
                    verdict = "INVALID" if off_speed else ("PASS" if ratio >= 0.8 else ("FAIL" if ratio <= 0.2 else "UNCLEAR"))
                    print(head + f" | {ratio * 100:.0f}% -> {verdict}", flush=True)
                    if verdict in ("INVALID", "UNCLEAR"):
                        if verdict == "INVALID":
                            api("SPEED", f"--ef speed {cur}")
                        open_window(t, v)                  # judge the next batch at the same speed
                    else:
                        tested.append((cur, real, lab, ratio, verdict, queue_confirm is not None))
                        if queue_confirm is None:
                            if verdict == "PASS":
                                lo = cur
                            else:
                                hi = cur
                        else:
                            confirmed.append((cur, verdict))
                        phase = "switch"
                if phase == "switch":
                    nxt = choose()
                    if nxt is None:
                        raise StopIteration
                    cur = nxt
                    api("SPEED", f"--ef speed {cur}")
                    t_switch, phase = time.time(), "judge"
                    open_window(t, v)
                    tag = "CONFIRM" if queue_confirm is not None else f"bisect {lo:.2f}..{hi:.2f}"
                    print(f"{time.strftime('%H:%M:%S')} === SPEED {cur:.2f} km/h ({tag}); judged on the next batch >= {MIN_WIN}s away", flush=True)
            p = fix()
            if p and last and p[2] != last[2]:
                d = meters(last, p)
                if d < 200:
                    moved += d
                if phase == "judge" and t_switch and time.time() - t_switch > 5:
                    labels.append(p[3])
                    if abs(p[3] - cur) > 0.06:
                        off_speed += 1
                        if off_speed in (1, 5, 20):
                            api("SPEED", f"--ef speed {cur}")
            last = p or last
            if time.time() >= next_tick:
                next_tick += 15
                if phase == "judge" and w_t0:
                    cr = (km_now - w_km0) * 1000 if km_now is not None else 0
                    print(f"{time.strftime('%H:%M:%S')} check: SET {cur:.2f} | label {p[3] if p else 0:.2f} | since window start: moved {moved:.0f} m, credited {cr:.0f} m", flush=True)
            time.sleep(1)
    except StopIteration:
        pass
    finally:
        api("SPEED", "--ef speed 10.4")
        api("SHOW")
        sc.unload()
        sess.detach()
    print(f"RESULT: credited up to SET {lo:.2f} km/h | not credited from SET {hi:.2f} km/h", flush=True)
    for t in tested:
        print(f"   {'confirm ' if t[5] else ''}set {t[0]:.2f}  real {t[1]:.2f}  label {t[2][0]:.2f}..{t[2][1]:.2f}  credited {t[3] * 100:.0f}%  {t[4]}", flush=True)
    print("speed back to 10.4, joystick controls shown again. done", flush=True)


if __name__ == "__main__":
    main()

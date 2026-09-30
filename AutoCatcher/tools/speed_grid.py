"""Credited-distance vs speed curve, contamination-proof. Pro API + the game's own KmWalked record.

  python tools/speed_grid.py 10.4 10.6 10.8 11.0 11.2 11.5 12.0 13.0 14.0

For every speed: SPEED at a sync moment, then two windows of >= WIN seconds, each bounded by PlayerStats sync
moments (every parse of PlayerStatsProto is timestamped, changed or not):
  window 1 absorbs any credit still owed from the previous speed -- shown, NOT judged;
  window 2 is judged: credited (KmWalked delta) / moved (GPS, my measurement) over exactly the same interval.
Straight WALK line, joystick controls HIDDEN, wobble 0; a fix whose speed label is off the test value in window 2
invalidates the window (SPEED re-sent, window repeated). Every 15 s a check line is logged.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cutoff_hunt as ch  # noqa: E402  (adb, fix, meters, api, walk_line, pg)

WIN = 120
JS = ch.JS.replace("if (v > LASTV + 1e-6) { LASTV = v; EV.push({t: Date.now(), v: v}); }",
                   "var now = Date.now(); if (Math.abs(v - LASTV) > 1e-6 || now - (this.lt || 0) > 1000) { LASTV = v; EV.push({t: now, v: v}); }")


def main():
    speeds = [float(x) for x in sys.argv[1:]]
    if "Pixel" not in ch.adb("getprop ro.product.model"):
        sys.exit("not the phone")
    if not ch.adb("pidof com.theappninjas.fakegpsjoystick:overlay").strip() or not ch.fix():
        sys.exit("joystick not spoofing -- refusing (PoGo must never see the real GPS)")
    if os.environ.get("KEEP_PATH"):
        a = b = "current WALK path kept"
        ch.api("SPEED", f"--ef speed {speeds[0]}")
    else:
        a, b = ch.walk_line(speeds[0])
    ch.api("HIDE")
    print(f"{time.strftime('%H:%M:%S')} WALK straight {a} -> {b} x6 legs; controls HIDDEN; speeds {speeds}", flush=True)
    ch.pg.wait_ready_to_attach(timeout_s=240, min_age_s=45)
    sess, pid = ch.pg.get_session()
    sc = sess.create_script(JS)
    sc.load()
    print(f"attached pid {pid}; hooks {sc.exports_sync.install()}", flush=True)
    results = []
    idx, cur, stage = -1, None, "next"           # stage: next (waiting to switch) -> w1 -> w2
    w_t0 = w_km0 = t_stage = None
    moved, labels, off, last, km_now, last_sync, last_change = 0.0, [], 0, ch.fix(), None, None, None
    next_tick = time.time() + 15

    def begin(t, v, new_stage):
        nonlocal w_t0, w_km0, moved, labels, off, stage, t_stage
        w_t0, w_km0, moved, labels, off, stage, t_stage = t, v, 0.0, [], 0, new_stage, time.time()

    def close_window(t, v, why):
        """Judge/print the window that started at w_t0 and ends now (at a credit update, or a timeout)."""
        got, dt = (v - w_km0) * 1000, t - w_t0
        real = moved / dt * 3.6 if dt else 0
        ratio = got / moved if moved > 1 else 0
        lab = (min(labels), max(labels)) if labels else (0, 0)
        return got, dt, real, ratio, lab, (f"{time.strftime('%H:%M:%S', time.localtime(t))} SET {cur:.2f} {stage} [{why}]: credited {got:.0f} m"
                                            f" / moved {moved:.0f} m over {dt:.0f} s = {ratio * 100:.0f}% | real {real:.2f} km/h, label {lab[0]:.2f}..{lab[1]:.2f}")

    def advance(t, v, why):
        """End the current window at (t, v): w1 -> w2, w2 -> judged -> next speed."""
        nonlocal idx, cur
        if stage in ("w1", "w2"):
            got, dt, real, ratio, lab, line = close_window(t, v, why)
            if stage == "w1":
                print(line + " | window 1 (absorbs leftovers, not judged)", flush=True)
                begin(t, v, "w2")
                return
            if off:
                print(line + f" | INVALID ({off} fixes off speed) -> repeat window 2", flush=True)
                ch.api("SPEED", f"--ef speed {cur}")
                begin(t, v, "w2")
                return
            print(line + " | JUDGED", flush=True)
            results.append((cur, real, lab, got, moved, ratio))
        idx += 1
        if idx >= len(speeds):
            raise StopIteration
        cur = speeds[idx]
        ch.api("SPEED", f"--ef speed {cur}")
        print(f"{time.strftime('%H:%M:%S')} === SPEED {cur:.2f} km/h ({idx + 1}/{len(speeds)}) at the credit update [{why}]", flush=True)
        begin(t, v, "w2" if os.environ.get("ONE_WINDOW") else "w1")

    try:
        while True:
            for e in sc.exports_sync.drain():
                t, v = e["t"] / 1000, e["v"]
                changed = last_sync is None or abs(v - last_sync[1]) > 1e-6
                if not changed and t - last_sync[0] < 1:
                    continue
                if changed:
                    d_km = (v - last_change[1]) * 1000 if last_change else 0
                    print(f"{time.strftime('%H:%M:%S', time.localtime(t))} CREDIT UPDATE: KmWalked {v:.3f}"
                          f" ({'+%.0f m, %.0f s after the previous update' % (d_km, t - last_change[0]) if last_change else 'first'})", flush=True)
                    last_change = (t, v)
                last_sync, km_now = (t, v), v
                # windows start and end exactly at credit updates (the user's rule); w_t0 + WIN is the minimum length
                if changed and (stage == "next" or (stage in ("w1", "w2") and t - w_t0 >= WIN)):
                    advance(t, v, "credit update")
            # a speed that earns nothing never produces an update: close on a timeout with the latest synced value
            if stage in ("w1", "w2") and time.time() - t_stage >= WIN + 150 and last_sync:
                advance(time.time(), km_now, "timeout, no credit update")
            elif stage == "next" and last_sync and time.time() - (t_stage or 0) > 20:
                advance(time.time(), km_now, "no update within 20 s")
            p = ch.fix()
            if p and last and p[2] != last[2]:
                dd = ch.meters(last, p)
                if dd < 200:
                    moved += dd
                if stage == "w2":
                    labels.append(p[3])
                    if abs(p[3] - cur) > 0.06:
                        off += 1
                        if off in (1, 5, 20):
                            ch.api("SPEED", f"--ef speed {cur}")
                elif stage == "w1" and time.time() - t_stage > 5:
                    labels.append(p[3])
            last = p or last
            if time.time() >= next_tick:
                next_tick += 15
                if stage in ("w1", "w2"):
                    cr = (km_now - w_km0) * 1000 if km_now is not None else 0
                    print(f"{time.strftime('%H:%M:%S')} check: SET {cur:.2f} {stage} {time.time() - t_stage:.0f}s | label {p[3] if p else 0:.2f}"
                          f" | moved {moved:.0f} m, credited {cr:.0f} m so far", flush=True)
            time.sleep(1)
    except StopIteration:
        pass
    finally:
        ch.api("SPEED", "--ef speed 10.4")
        ch.api("SHOW")
        sc.unload()
        sess.detach()
    print("RESULTS (window 2 only, game record KmWalked vs GPS moved):", flush=True)
    for s_, real, lab, got, mv, ratio in results:
        print(f"   set {s_:5.2f} | real {real:5.2f} km/h | label {lab[0]:.2f}..{lab[1]:.2f} | credited {got:4.0f} m of {mv:4.0f} m = {ratio * 100:3.0f}%", flush=True)
    print("speed back to 10.4, controls shown. done", flush=True)


if __name__ == "__main__":
    main()

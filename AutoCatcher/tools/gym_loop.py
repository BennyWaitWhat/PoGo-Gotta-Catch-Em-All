"""Keep re-battling one gym until it is empty (or no longer the target team), then stop and say so.

Screen-state loop (stopgap until the traced in-game calls replace the taps): reads a few pixels on the phone,
taps only outside battles. The in-battle attacking is tools/gym_tapper.py (run it alongside).

  python tools/gym_loop.py GYM_ID [--team 1] [--minutes 30]
"""
import argparse
import os
import sqlite3
import subprocess
import sys
import time

DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")   # cloud: the Tailscale bridge exports ADB_TARGET (127.0.0.1:5555)
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "system", "map", "pogo_wigle.db")
ATTACK_LOG = sys.argv[sys.argv.index("--log") + 1] if "--log" in sys.argv else None
W = 1280
PTS = {"go": (640, 1180), "sky": (640, 300), "flee": (104, 480), "btn": (640, 2700), "mid": (640, 1400)}


def pixels():
    offs = " ".join(str(4 + y * W + x) for x, y in PTS.values())
    out = subprocess.run(["adb", "-s", DEV, "shell", f"screencap /data/local/tmp/g.raw && for o in {offs}; do dd if=/data/local/tmp/g.raw bs=4 skip=$o count=1 2>/dev/null | od -An -tu1; done"],
                         capture_output=True, text=True, env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout.split()
    v = [int(x) for x in out]
    return {k: tuple(v[i * 4:i * 4 + 3]) for i, k in enumerate(PTS)} if len(v) >= 4 * len(PTS) else None


def screen(p):
    go, sky, flee, btn, mid = p["go"], p["sky"], p["flee"], p["btn"], p["mid"]
    if go[1] > 220 and 170 <= go[0] <= 215 and 190 <= go[2] <= 235:
        return "prep"
    if sky[2] > 110 and sky[0] < 45 and sky[1] < 70 and flee[2] > 110 and btn[0] < 70 and 110 <= btn[1] <= 165 and 130 <= btn[2] <= 185:
        return "gym"
    if min(mid) > 240 and min(sky) > 150:
        return "white"
    return "other"


def tap(x, y):
    subprocess.run(["adb", "-s", DEV, "shell", f"input tap {x} {y}"], capture_output=True)


def team(gym):
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    r = db.execute("SELECT team, last_seen FROM forts WHERE id=?", (gym,)).fetchone()
    return r


def in_battle():
    if not ATTACK_LOG or not os.path.exists(ATTACK_LOG):
        return False
    s = open(ATTACK_LOG, encoding="utf-8", errors="replace").read()
    return s.rfind("round start") > s.rfind("battle over")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gym")
    ap.add_argument("--team", type=int, default=1)
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--log")
    a = ap.parse_args()
    t0, last_battle_tap, misses = time.time(), 0, 0
    print(time.strftime("%H:%M:%S"), "loop on", a.gym, "team", team(a.gym), flush=True)
    while time.time() - t0 < a.minutes * 60:
        if in_battle():
            time.sleep(1)
            continue
        p = pixels()
        s = screen(p) if p else "none"
        if s == "gym":
            tm = team(a.gym)
            if tm and tm[0] != a.team:
                print(time.strftime("%H:%M:%S"), f"STOP: gym is now team {tm[0]} (0 = empty, place your Pokemon) as of {tm[1]}", flush=True)
                return
            if time.time() - last_battle_tap > 4:
                tap(1120, 2436)
                last_battle_tap = time.time()
                misses += 1
                print(time.strftime("%H:%M:%S"), "gym view -> Battle", flush=True)
                if misses > 3:
                    print(time.strftime("%H:%M:%S"), "STOP: Battle did not open the team screen 3 times (gym empty? team needs healing?)", flush=True)
                    return
        elif s == "prep":
            tap(640, 1180)
            misses = 0
            print(time.strftime("%H:%M:%S"), "team screen -> GO BATTLE", flush=True)
            time.sleep(2)
        elif s == "white":
            tap(640, 1400)
            print(time.strftime("%H:%M:%S"), "results screen -> skip", flush=True)
        time.sleep(0.6)


if __name__ == "__main__":
    main()

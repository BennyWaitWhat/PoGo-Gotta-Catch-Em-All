"""Never stand still: when the avatar stops, walk a loop through the Bryant Park gyms (joystick WALK, egg-safe speed).

Watches the mock fix; if it moved < 1.5 m over 8 s, starts the loop from the nearest loop point. A walk you start
yourself is left alone while it runs.

  python tools/keep_moving.py [--speed 10.4] [--laps 8]
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import cutoff_hunt as ch  # noqa: E402

# the six Bryant Park gyms (park + library), clockwise from the 42nd St / 6th Ave corner (bank positions)
LOOP = [(40.754481, -73.983776), (40.753949, -73.982633), (40.752982, -73.981523),
        (40.752449, -73.981984), (40.753193, -73.983572), (40.753478, -73.984248)]


def loop_from(here, laps):
    i = min(range(len(LOOP)), key=lambda k: ch.meters(here, LOOP[k]))
    pts = [LOOP[(i + k) % len(LOOP)] for k in range(len(LOOP) * laps + 1)]
    return ";".join(f"{a:.6f},{b:.6f}" for a, b in pts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=10.4)
    ap.add_argument("--laps", type=int, default=8)
    a = ap.parse_args()
    hist = []
    while True:
        p = ch.fix()
        if p:
            hist = [h for h in hist if p[2] - h[2] <= 8] + [p]
            if p[2] - hist[0][2] >= 8 and ch.meters(hist[0][:2], p[:2]) < 1.5:
                ch.api("WALK", f'--es waypoints "{loop_from(p[:2], a.laps)}" --ef speed {a.speed}')
                print(time.strftime("%H:%M:%S"), f"stopped at {p[0]:.6f},{p[1]:.6f} -> looping the park gyms at {a.speed} km/h", flush=True)
                hist = []
                time.sleep(10)
        time.sleep(2)


if __name__ == "__main__":
    main()

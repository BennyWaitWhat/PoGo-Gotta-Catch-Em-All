"""Is the catcher keeping up, or is it starved by the spawn supply?

  python tools/catcher_keepup.py system/analysis/spawn_study.jsonl

Supply = wild Pokemon the server revealed (map data, species + time).  Output = the catcher's own log for the same
minutes (pulled from the phone). Each revealed wild is matched to the first 'CATCH Wild #<species>' within
[-5 s, +120 s]; latency = catch time - reveal time. Also: lure/incense/other catches, fled, and the catcher's own
status (visible / tracked / pending) -- idle while nothing is visible means supply-limited.
"""
import json
import os
import re
import statistics as st
import subprocess
import sys
import time
from collections import defaultdict

DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")   # cloud: the Tailscale bridge exports ADB_TARGET
LOG = "/data/data/com.termux/files/home/pogo/system/analysis/pokemod/catch_loop.log"


def main():
    ev = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    resps = [e for e in ev if e.get("k") == "resp"]
    if not resps:
        sys.exit("no responses")
    t0, t1 = resps[0]["t"] / 1000, resps[-1]["t"] / 1000
    reveals = {}
    for e in resps:
        for w in e.get("wild") or []:
            reveals.setdefault(w[0], (e["t"] / 1000, w[6]))
    day = time.strftime("%Y-%m-%d", time.localtime(t0))
    raw = subprocess.run(["adb", "-s", DEV, "shell", f"su -c 'cat {LOG}'"], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout.splitlines()
    # The log has NO dates and spans days: walk back from the END (today) and stop at the first line older than the
    # window -- never match by clock time alone (an earlier night's lines have the same HH:MM:SS).
    lines = []
    for ln in reversed(raw):
        m = re.match(r"(\d\d:\d\d:\d\d) (.*)", ln)
        if not m:
            continue
        ts = time.mktime(time.strptime(f"{day} {m[1]}", "%Y-%m-%d %H:%M:%S"))
        if ts < t0 - 600:
            break
        if t0 - 5 <= ts <= t1 + 120:
            lines.append((ts, m[2]))
    lines.reverse()
    catches = []
    for ts, body in lines:
        m = re.match(r"CATCH (\S+) #(\d+)", body)
        if m:
            catches.append([ts, m[1], int(m[2]), False])
        m2 = re.match(r"CATCH r=1 .*pid=(\d+) .*src=(\w+)", body)
        if m2:
            catches.append([ts, "other:" + m2[2], int(m2[1]), False])
    fled = [ts for ts, b in lines if b.startswith("FLED")]
    status = [(ts, int(m[1]), int(m[2]), int(m[3])) for ts, b in lines
              for m in [re.search(r"vis=(\d+) track=(\d+) pend=(\d+)", b)] if m]
    lat, missed = [], []
    for enc, (tr, sp) in sorted(reveals.items(), key=lambda kv: kv[1][0]):
        hit = next((c for c in catches if not c[3] and c[1] == "Wild" and c[2] == sp and tr - 5 <= c[0] <= tr + 120), None)
        if hit:
            hit[3] = True
            lat.append(hit[0] - tr)
        else:
            missed.append((tr, sp))
    mins = (t1 - t0) / 60
    wild_c = sum(1 for c in catches if c[1] == "Wild" and t0 - 5 <= c[0] <= t1 + 5)
    other_c = sum(1 for c in catches if c[1] != "Wild" and t0 - 5 <= c[0] <= t1 + 5)
    print(f"window {time.strftime('%H:%M:%S', time.localtime(t0))} - {time.strftime('%H:%M:%S', time.localtime(t1))} ({mins:.1f} min)")
    print(f"SUPPLY  wild revealed by the server: {len(reveals)} ({len(reveals) / mins:.1f}/min)")
    print(f"OUTPUT  wild caught: {wild_c} | lure/incense/POI/other caught: {other_c} | fled: {len(fled)} | total {(wild_c + other_c) / mins:.1f}/min")
    print(f"MATCH   revealed wild caught: {len(lat)}/{len(reveals)} = {len(lat) / len(reveals) * 100 if reveals else 0:.0f}%"
          f" | reveal->caught latency: median {st.median(lat) if lat else 0:.1f} s, p90 {sorted(lat)[int(len(lat) * 0.9)] if lat else 0:.1f} s, max {max(lat) if lat else 0:.1f} s")
    if missed:
        print(f"        not matched ({len(missed)}): species {[sp for _, sp in missed][:20]}")
    if status:
        idle = sum(1 for s in status if s[1] == 0 and s[3] == 0) / len(status)
        print(f"STATUS  catcher reports: visible avg {st.mean(s[1] for s in status):.2f}, tracked avg {st.mean(s[2] for s in status):.2f},"
              f" pending avg {st.mean(s[3] for s in status):.2f} | idle (nothing visible, nothing pending) {idle * 100:.0f}% of reports"
              f" | max pending {max(s[3] for s in status)}")
    per = defaultdict(lambda: [0, 0, 0])
    for enc, (tr, sp) in reveals.items():
        per[int(tr // 60)][0] += 1
    for c in catches:
        if t0 - 5 <= c[0] <= t1 + 5:
            per[int(c[0] // 60)][1 if c[1] == "Wild" else 2] += 1
    print("per minute: revealed wild | caught wild | caught other")
    for m in sorted(per):
        r, w, o = per[m]
        print(f"   {time.strftime('%H:%M', time.localtime(m * 60))}  {r:3d} | {w:3d} | {o:3d}")


if __name__ == "__main__":
    main()

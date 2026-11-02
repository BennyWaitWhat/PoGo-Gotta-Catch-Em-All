"""Teleport-hop scan: put the joystick on each point of HOPS.json in turn and move on as soon as the scanner has
banked the game's map reply for that spot. Every map reply (~every 5 s) holds every level-15 S2 cell that touches a
~709 m circle around the reported player position (nearest cell edge), so one reply per hop is the whole circle.

  python -I hop.py HOPS.json STOPFILE [FROM_INDEX]

Per hop: teleport (the FREE TELEPORT intent), then
  - joystick overlay process gone           -> stop at once, exit 2 (the real GPS would reach PoGo)
  - PoGo not in front                       -> pause until it is, then teleport to the same hop again
  - live fix not on the hop point (> 25 m)  -> someone else is steering the joystick: stop, exit 4
  - wait for the reply: a fort got last_seen after the hop either within 300 m of it, or within 1.2 km of it and more
    than 1.2 km from the previous hop (a reply still in flight for the previous hop never reaches past 1.16 km from
    it); or 2 map replies came in after the hop (an empty spot: water, fields)
  - 6 hops in a row without one map reply   -> the scanner or the game stopped: exit 3
  - STOPFILE exists                         -> stop, exit 5
One log line per hop; one JSON row per hop in HOPS.json + '.log.jsonl' (read by the coverage check).
"""
import json, math, os, re, sqlite3, subprocess, sys, time

DEV = "100.98.158.56:5555"
JOY = "com.theappninjas.fakegpsjoystick"
DB = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\AutoCatcher\system\map\pogo_wigle.db"
NEAR_M, STAT_M, FMT = 300.0, 1200.0, "%Y-%m-%d %H:%M:%S"
MAX_DWELL = float(os.environ.get("HOP_MAX_DWELL", "20"))     # the game sometimes pauses its map requests for 1-2 min
hops_file, stopfile = sys.argv[1], sys.argv[2]
start = int(sys.argv[3]) if len(sys.argv) > 3 else 0


def adb(c):
    return subprocess.run(["adb", "-s", DEV, "shell", c], capture_output=True, text=True, timeout=30).stdout


def fix():
    m = re.search(r"Location\[gps ([-0-9.]+),([-0-9.]+)", adb("dumpsys location | grep -m1 'last mock location'"))
    return (float(m[1]), float(m[2])) if m else None


def dist(a, b):
    return math.hypot((a[0] - b[0]) * 111320.0, (a[1] - b[1]) * 111320.0 * math.cos(math.radians(a[0])))


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def shell():
    return subprocess.Popen(["adb", "-s", DEV, "shell"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, text=True)


db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)


def q(sql, args=()):
    for _ in range(10):
        try:
            return db.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            time.sleep(0.3)
    return db.execute(sql, args).fetchall()


def around(p, r_m, t_str, col):
    dlat, dlng = r_m / 111320.0, r_m / (111320.0 * math.cos(math.radians(p[0])))
    rows = q(f"SELECT lat, lng, kind FROM forts WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? AND {col} >= ?",
             (p[0] - dlat, p[0] + dlat, p[1] - dlng, p[1] + dlng, t_str))
    return [r for r in rows if dist((r[0], r[1]), p) <= r_m]


t0 = time.time()
off = int(adb("date +%s").strip()) - (t0 + time.time()) / 2          # phone clock - PC clock (the bank uses the phone's)
H = [tuple(p) for p in json.load(open(hops_file))["hops"]]
logf = open(hops_file + ".log.jsonl", "a")
log(f"{len(H)} hops, starting at #{start + 1}; phone clock {off:+.1f} s vs PC")
sh, i, quiet, done, spent, paused, prev = shell(), start, 0, 0, 0.0, False, None
while i < len(H):
    if os.path.exists(stopfile):
        log(f"STOP: stop file; next hop #{i + 1}")
        sys.exit(5)
    p = H[i]
    r0 = q("SELECT COALESCE(MAX(rowid), 0) FROM replies")[0][0]
    t_hop = time.time()
    t_str = time.strftime(FMT, time.localtime(t_hop + off - 2))
    if sh.poll() is not None:
        sh = shell()
    sh.stdin.write(f"am start-foreground-service -a theappninjas.gpsjoystick.TELEPORT --ef lat {p[0]:.6f} --ef lng {p[1]:.6f}\n")
    sh.stdin.flush()
    if not adb(f"pidof {JOY}:overlay").strip():
        log("STOP: the joystick overlay process is gone -- the real GPS can reach PoGo")
        sys.exit(2)
    top = adb("dumpsys activity activities | grep -m1 topResumedActivity")
    if "com.nianticlabs.pokemongo/" not in top:
        if not paused:
            log(f"pause: PoGo is not in front ({top.strip()[-70:]}); waiting")
            paused = True
        time.sleep(3)
        continue
    if paused:
        log("resume: PoGo is back in front")
        paused = False
    f = None
    for _ in range(8):
        f = fix()
        if f and dist(f, p) <= 25:
            break
        time.sleep(0.5)
    if not f or dist(f, p) > 25:
        log(f"STOP: live fix {f} is not on hop #{i + 1} {p[0]:.6f},{p[1]:.6f} -- someone else is steering")
        sys.exit(4)
    how, n_rep = "timeout", 0
    while time.time() - t_hop < MAX_DWELL:
        n_rep = q("SELECT COUNT(*) FROM replies WHERE rowid > ? AND cells > 0", (r0,))[0][0]
        if n_rep >= 1 and (around(p, NEAR_M, t_str, "last_seen") or
                           (prev and any(dist((r[0], r[1]), prev) > STAT_M for r in around(p, STAT_M, t_str, "last_seen")))):
            how = "fort"
            break
        if n_rep >= 2:
            how = "replies"
            break
        time.sleep(0.4)
    dwell = time.time() - t_hop
    seen, new = around(p, STAT_M, t_str, "last_seen"), around(p, STAT_M, t_str, "first_seen")
    quiet = 0 if n_rep else quiet + 1
    done, spent = done + 1, spent + dwell
    left = (len(H) - i - 1) * spent / done / 60
    log(f"#{i + 1}/{len(H)} {p[0]:.5f},{p[1]:.5f} {how:7s} {dwell:4.1f} s, {n_rep} replies | within 1.2 km: "
        f"{len(seen)} seen, {sum(r[2] == 'stop' for r in new)} new stops + {sum(r[2] == 'gym' for r in new)} new gyms | ~{left:.0f} min left")
    logf.write(json.dumps({"i": i, "p": p, "t": time.strftime(FMT), "how": how, "dwell": round(dwell, 1), "replies": n_rep,
                           "seen": len(seen), "new": len(new)}) + "\n")
    logf.flush()
    if quiet >= 6:
        log("STOP: 6 hops in a row without a map reply -- the scanner or the game stopped")
        sys.exit(3)
    prev = p
    i += 1
log(f"DONE: {len(H)} hops" + (f"; last at {H[-1][0]:.6f},{H[-1][1]:.6f}" if H else ""))

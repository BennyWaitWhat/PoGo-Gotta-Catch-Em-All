"""Speed-cutoff run with a message trace. Game records only; GPS movement is labelled as mine.

  python tools/track_walk3.py MINUTES "0:walking,300:jogging,600:running"

* Hooks (read-only, like the catcher's): when each of these messages is SENT (WriteTo) or RECEIVED (MergeFrom),
  with a timestamp -- location/fitness reports out, inventory syncs in, buddy-walk claims, and every new
  PlayerStats.KmWalked value the moment it is parsed. This shows the interval and the trigger of each credit.
* Every 60 s: liveness read of BuddyObservedData (Walk-together km) and the egg incubators.
* Schedule: at each offset, tap that speed button on the joystick overlay and measure the speed.
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
OUT_MSGS = ["GetMapObjectsProto", "HoloFitnessReportProto", "PlayerLocationRpcProto", "GetHoloholoInventoryProto",
            "GetInventoryProto", "GetBuddyWalkedProto", "GetFitnessRewardsProto", "SoftSfidaLocationUpdateProto"]
IN_MSGS = ["GetMapObjectsOutProto", "GetHoloholoInventoryOutProto", "GetInventoryResponseProto", "InventoryDeltaProto",
           "GetBuddyWalkedOutProto", "GetFitnessRewardsOutProto", "PlayerStatsSnapshotsProto"]
JS = dl.JS.split("rpc.exports = {")[0] + r"""
var EV = [], LAST = {}, KMOFF = -1, KMTE = 0, SAMPLES = {};
function note(kind, cls, extra) {
  var now = Date.now(), key = kind + cls;
  if (LAST[key] && now - LAST[key] < 150) return;    /* one message can pass through several overloads */
  LAST[key] = now; EV.push({t: now, k: kind, c: cls, x: extra || null});
}
function hookMethods(kl, cls, names, kind, onLeave) {
  var n = 0, it = Memory.alloc(PS); it.writePointer(NULL);
  var getM = new NativeFunction(EX['il2cpp_class_get_methods'], 'pointer', ['pointer', 'pointer'], PROP);
  var mName = new NativeFunction(EX['il2cpp_method_get_name'], 'pointer', ['pointer'], PROP);
  var mArgs = new NativeFunction(EX['il2cpp_method_get_param_count'], 'uint32', ['pointer'], PROP);
  var m;
  while ((m = getM(kl, it)) && !m.isNull()) {
    var nm = cs(mName(m));
    if (names.indexOf(nm) < 0 || mArgs(m) !== 1) continue;
    var fp = m.readPointer(); if (fp.isNull()) continue;
    try {
      Interceptor.attach(fp, onLeave ? {onEnter: function (a) { this.self = a[0]; }, onLeave: function () { onLeave(this.self); }}
                                     : {onEnter: function () { note(kind, cls); }});
      n++;
    } catch (e) {}
  }
  return n;
}
rpc.exports = {
  install: function (outs, ins) {
    var got = {};
    outs.forEach(function (c) { var kl = findClass('holo-protos.dll', c); got['>' + c] = kl ? hookMethods(kl, c, ['WriteTo'], 'OUT') : 'no class'; });
    ins.forEach(function (c) { var kl = findClass('holo-protos.dll', c); got['<' + c] = kl ? hookMethods(kl, c, ['MergeFrom'], 'IN') : 'no class'; });
    var ps = findClass('holo-protos.dll', 'PlayerStatsProto');
    fieldsOf(ps).forEach(function (fd) { if (fd.name === 'KmWalked') { KMOFF = fd.off; KMTE = fd.te; } });
    got['<PlayerStatsProto'] = hookMethods(ps, 'PlayerStatsProto', ['MergeFrom'], 'IN', function (self) {
      try { var v = KMTE === 0x0d ? self.add(KMOFF).readDouble() : self.add(KMOFF).readFloat(); note('KM', 'PlayerStatsProto', v); } catch (e) {}
    });
    return got;
  },
  drain: function () { var e = EV; EV = []; return e; },
  snap: function () {
    var out = {};
    ['BuddyObservedData', 'EggIncubatorProto'].forEach(function (n) {
      var kl = findClass('holo-protos.dll', n); out[n] = kl ? instances(kl, 64).map(function (o) { return readObj(o, 2); }) : [];
    });
    return out;
  }
};
"""


def adb(cmd):
    return subprocess.run(["adb", "-s", DEV, "shell", cmd], capture_output=True, text=True,
                          env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout


def spot():
    m = re.search(r"Location\[gps ([-0-9.]+),([-0-9.]+) .*?vel=([0-9.]+)", adb("dumpsys location | grep -m1 'last mock location'"))
    return (float(m[1]), float(m[2]), float(m[3])) if m else None


def meters(a, b):
    r = 6371008.8
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl_ = math.radians(b[1] - a[1])
    return 2 * r * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl_ / 2) ** 2))


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    minutes = float(sys.argv[1])
    sched = []
    if len(sys.argv) > 2 and sys.argv[2]:
        for part in sys.argv[2].split(","):
            at, m = part.split(":")
            sched.append((float(at), m))
    if "Pixel" not in adb("getprop ro.product.model"):
        sys.exit("not the phone -- refusing")
    sess, pid = pg.get_session()
    sc = sess.create_script(JS)
    sc.load()
    print("hooks:", sc.exports_sync.install(OUT_MSGS, IN_MSGS), flush=True)
    t0 = time.time()
    tm = lambda ms: time.strftime("%H:%M:%S", time.localtime(ms / 1000)) + f".{int(ms % 1000):03d}"
    km_last, km_first, moved, last, gmo, next_snap, credits = None, None, 0.0, spot(), [], 0, []
    seg_start = time.time()
    try:
        while time.time() - t0 < minutes * 60:
            el = time.time() - t0
            while sched and el >= sched[0][0]:
                _, m = sched.pop(0)
                r = subprocess.run([sys.executable, os.path.join(HERE, "joystick_round.py"), "mode", m], capture_output=True, text=True)
                print(f"{time.strftime('%H:%M:%S')} === SPEED MODE -> {m}: {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()[-200:]}", flush=True)
                seg_start, moved = time.time(), 0.0
            for e in sc.exports_sync.drain():
                if e["k"] == "KM":
                    v = e["x"]
                    if km_last is None or abs(v - km_last) > 1e-6:
                        d = 0 if km_last is None else (v - km_last) * 1000
                        km_first = v if km_first is None else km_first
                        if km_last is not None:
                            credits.append((e["t"], d))
                        gap = f", {(e['t'] - credits[-2][0]) / 1000:.0f} s after the last credit" if len(credits) > 1 else ""
                        print(f"{tm(e['t'])} <- PlayerStats.KmWalked {v:.3f} (+{d:.0f} m{gap}) | moved (GPS) since mode switch {moved:.0f} m", flush=True)
                        km_last = v
                elif e["c"] == "GetMapObjectsProto":
                    gmo.append(e["t"])
                else:
                    print(f"{tm(e['t'])} {'->' if e['k'] == 'OUT' else '<-'} {e['c']}", flush=True)
            if time.time() >= next_snap:
                s = sc.exports_sync.snap()
                aff = max([f((b.get("TodayStatsShownHearts") or {}).get("BuddyAffectionKmInProgress", 0)) or 0
                           for b in s["BuddyObservedData"] if isinstance(b, dict)] or [0])
                eggs = sorted({(f(e.get("StartKmWalked")), f(e.get("TargetKmWalked"))) for e in s["EggIncubatorProto"]
                               if isinstance(e, dict) and e.get("PokemonId")})
                egg_txt = ", ".join(f"{(km_last or 0) - a:.2f}/{b - a:g}" for a, b in eggs if a is not None and b and km_last and b > km_last)
                gi = [round((b - a) / 1000, 1) for a, b in zip(gmo, gmo[1:])][-6:]
                p = spot()
                print(f"{time.strftime('%H:%M:%S')} records | eggs {egg_txt or '-'} | WalkTogether {aff:.3f} km | "
                      f"map requests last intervals (s) {gi} | label {p[2] * 3.6 if p else 0:.2f} km/h", flush=True)
                next_snap = time.time() + 60
            p = spot()
            if p and last and meters(last, p) < 200:
                moved += meters(last, p)
            last = p or last
            time.sleep(2)
    finally:
        sc.unload()
        sess.detach()
    print("done", flush=True)


if __name__ == "__main__":
    main()

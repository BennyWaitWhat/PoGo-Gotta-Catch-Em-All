"""Trace every method of the gym-battle flow classes (logs only), to find the calls that move the game along.

  python tools/gym_trace.py [MINUTES=6]
Each line: time, Class.method/argc, and for pointer args the IL2CPP class name of the object (when it is one).
Per-method throttle: a repeated call prints at most every 400 ms, with its running count.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402
import dump_game_limits as dl  # noqa: E402

CLASSES = [
    "Niantic.Holoholo.Gym.GymState", "Niantic.Holoholo.Gym.GymBattleLauncherState", "Niantic.Holoholo.Gym.GymBattleIntroState",
    "Niantic.Holoholo.Gym.Battle.GymBattleResultsState", "Niantic.Holoholo.Gym.Battle.GymBattleVictoryGuiController",
    "Niantic.Holoholo.Gym.Battle.GymBattleContinueGuiController", "Niantic.Holoholo.Gym.Battle.GymBattleDefeatGuiController",
    "Niantic.Holoholo.Gym.Approach.GymApproachState", "Niantic.Holoholo.Gym.Approach.GymApproachGuiController",
    "Niantic.Holoholo.Gym.GymBattlePrepUIController", "Niantic.Holoholo.Gym.BattlePrepUiBase", "Niantic.Holoholo.Gym.GymBattleState",
    "Niantic.Holoholo.Battle.BattleFrameObservableService", "Niantic.Holoholo.Gym.BattleResultsExit",
    "Niantic.Holoholo.Gym.Approach.GymApproachDetailsState",
]
SKIP = {".ctor", ".cctor", "Update", "get_BattleActive", "TryOrQueueAttack", "get_TimeRemaining", "UpdateBattleFrame"}

JS = dl.JS.split("rpc.exports = {")[0] + r"""
var NS = f('il2cpp_class_get_namespace', 'pointer', ['pointer']);
var GM = f('il2cpp_class_get_methods', 'pointer', ['pointer', 'pointer']);
var MN = f('il2cpp_method_get_name', 'pointer', ['pointer']);
var MC = f('il2cpp_method_get_param_count', 'uint32', ['pointer']);
function full(k) { var n = cs(NS(k)); return (n ? n + '.' : '') + cs(IL.className(k)); }
function what(p) {                           /* class name if p looks like a managed object */
  try { if (p.isNull()) return 'null'; if (p.compare(ptr('0x10000')) < 0) return p.toInt32();
    var k = p.readPointer(); if (k.isNull()) return String(p); var nm = cs(IL.className(k)); return nm ? nm : String(p); } catch (e) { return String(p); }
}
var LAST = {}, CNT = {};
rpc.exports = {
  install: function (classes, skip) {
    var want = {}, found = {}, n0 = 0, cnt = Memory.alloc(PS), sk = {};
    classes.forEach(function (c) { want[c] = 1; }); skip.forEach(function (s) { sk[s] = 1; });
    var arr = IL.asms(IL.domain(), cnt), n = cnt.readU32();
    for (var i = 0; i < n; i++) { var img = IL.asmImage(arr.add(i * PS).readPointer()), c = IL.classCount(img);
      for (var j = 0; j < c; j++) { var k = IL.classAt(img, j); if (!k.isNull()) { var nm = full(k); if (want[nm]) found[nm] = k; } } }
    var seen = {};
    Object.keys(found).forEach(function (cls) {
      var it = Memory.alloc(PS); it.writePointer(NULL); var m;
      while ((m = GM(found[cls], it)) && !m.isNull()) {
        var mn = cs(MN(m)), argc = MC(m), code = m.readPointer();
        if (sk[mn] || /^(get_|set_|add_|remove_)/.test(mn) || code.isNull() || seen[code]) continue; seen[code] = 1;
        (function (tag, argc) {
          try { Interceptor.attach(code, {onEnter: function (a) {
            var now = Date.now(); CNT[tag] = (CNT[tag] || 0) + 1;
            if (LAST[tag] && now - LAST[tag] < 400) return; LAST[tag] = now;
            var args = []; for (var q = 1; q <= argc && q <= 5; q++) args.push(what(a[q]));
            send({t: now, c: tag, n: CNT[tag], a: args, self: String(a[0])});
          }}); n0++; } catch (e) {}
        })(cls.split('.').pop() + '.' + mn + '/' + argc, argc);
      }
    });
    return {classes: Object.keys(found).length, hooked: n0};
  }
};
"""


def main():
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 6
    pg.wait_ready_to_attach(timeout_s=300, min_age_s=45)
    sess, pid = pg.get_session()
    sc = sess.create_script(JS)
    sc.on("message", lambda m, d: print(time.strftime("%H:%M:%S"), m["payload"]["c"], f"#{m['payload']['n']}",
                                        m["payload"]["a"], m["payload"]["self"], flush=True)
          if m.get("type") == "send" else print("JS", m, flush=True))
    sc.load()
    print(time.strftime("%H:%M:%S"), "attached", pid, sc.exports_sync.install(CLASSES, sorted(SKIP)), flush=True)
    t0 = time.time()
    try:
        while time.time() - t0 < minutes * 60:
            time.sleep(1)
    finally:
        try:
            sc.unload()
            sess.detach()
        except Exception:
            pass


if __name__ == "__main__":
    main()

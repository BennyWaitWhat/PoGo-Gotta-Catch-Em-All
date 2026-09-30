"""Passive watcher: which battle engine runs when you battle a gym? Logs calls only -- changes nothing.

Hooks (onEnter logging, no replacement) the old gym-battle path (Gym.GymBattleState, Battle.GymBattleRpcService,
Battle.GymBattleUI) and the VNext path (VNext.GymBattleUIVNext, VNext.BattleDirector). Each line printed is one
call, with repeated calls (e.g. one per attack) collapsed into a per-second count.

  python tools/battle_watch.py [MINUTES=10]
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402
import dump_game_limits as dl  # noqa: E402

WATCH = {
    "Niantic.Holoholo.Gym.GymBattleState": ["EnterState", "ExitState", "StartGymBattle"],
    "Niantic.Holoholo.Gym.GymBattleLauncherState": ["EnterState"],
    "Niantic.Holoholo.Battle.GymBattleRpcService": ["SendStartBattleRpc", "SendBattleUpdateRpc"],
    "Niantic.Holoholo.Battle.GymBattleUI": ["Initialize", "StartBattle"],
    "Niantic.Holoholo.VNext.GymBattleUIVNext": ["Initialize", "StartBattle"],
    "Niantic.Holoholo.VNext.BattleDirector": ["InitializeBattle", "TrySubmitPlayerAction"],
    "Niantic.Holoholo.Battle.BattleGestureHandler": ["OnPressed", "SetChargeAttackButtons", "bvyk", "bvyl", "bvym", "bvyn", "OnEnable", "OnDisable"],
}

JS = dl.JS.split("rpc.exports = {")[0] + r"""
var NS = f('il2cpp_class_get_namespace', 'pointer', ['pointer']);
var MFN = f('il2cpp_class_get_method_from_name', 'pointer', ['pointer', 'pointer', 'int']);
function full(k) { var n = cs(NS(k)); return (n ? n + '.' : '') + cs(IL.className(k)); }
var COUNT = {}, LAST = {}, STATE = null;
rpc.exports = {
  install: function (watch) {
    var want = {}, found = {}, cnt = Memory.alloc(PS), hooked = [];
    Object.keys(watch).forEach(function (k) { want[k] = 1; });
    var arr = IL.asms(IL.domain(), cnt), n = cnt.readU32();
    for (var i = 0; i < n; i++) {
      var img = IL.asmImage(arr.add(i * PS).readPointer()), c = IL.classCount(img);
      for (var j = 0; j < c; j++) { var k = IL.classAt(img, j); if (k.isNull()) continue; var nm = full(k); if (want[nm]) found[nm] = k; }
    }
    Object.keys(watch).forEach(function (cls) {
      var k = found[cls]; if (!k) { hooked.push(cls + ': class not found'); return; }
      watch[cls].forEach(function (mname) {
        var m = MFN(k, Memory.allocUtf8String(mname), -1);
        if (m.isNull()) { hooked.push(cls + '.' + mname + ': not found'); return; }
        var tag = cls.split('.').pop() + '.' + mname;
        Interceptor.attach(m.readPointer(), {onEnter: function (a) {
          var now = Date.now(); COUNT[tag] = (COUNT[tag] || 0) + 1;
          var extra = '';
          if (tag.indexOf('BattleGestureHandler') === 0) extra = ' args ' + a[1] + ' ' + a[2];
          if (tag === 'GymBattleState.StartGymBattle' || tag === 'GymBattleUI.StartBattle') {
            try {   /* the game's own auto-tap settings on the live gesture handler (read only) */
              var gs = STATE || a[0], h = gs.add(152).readPointer();
              if (!h.isNull()) extra = ' autoTapStartDelay=' + h.add(148).readFloat() + ' autoTapInterval=' + h.add(152).readFloat() + ' enableAutoChargeButton=' + h.add(156).readU8();
            } catch (e) { extra = ' read failed ' + e; }
          }
          if (tag === 'GymBattleState.EnterState' || tag === 'GymBattleState.StartGymBattle') STATE = a[0];
          var gesture = tag.indexOf('BattleGestureHandler') === 0;
          if (!LAST[tag] || now - LAST[tag] > (gesture ? 250 : 1000)) { send({t: now, call: tag + extra, n: COUNT[tag]}); LAST[tag] = now; }
        }});
        hooked.push(tag);
      });
    });
    return hooked;
  },
  counts: function () { return COUNT; }
};
"""


def main():
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 10
    pg.wait_ready_to_attach(timeout_s=300, min_age_s=45)
    sess, pid = pg.get_session()
    sc = sess.create_script(JS)
    sc.on("message", lambda m, d: print(f"{time.strftime('%H:%M:%S')} {m['payload']['call']} (total {m['payload']['n']})", flush=True)
          if m.get("type") == "send" else print("JS", m, flush=True))
    sc.load()
    print(f"{time.strftime('%H:%M:%S')} attached pid {pid}; hooks: {sc.exports_sync.install(WATCH)}", flush=True)
    t0 = time.time()
    try:
        while time.time() - t0 < minutes * 60:
            time.sleep(5)
    finally:
        try:
            print(f"{time.strftime('%H:%M:%S')} totals {sc.exports_sync.counts()}", flush=True)
            sc.unload()
            sess.detach()
        except Exception as e:
            print("detach:", e, flush=True)


if __name__ == "__main__":
    main()

"""unfreeze_game.py -- if PoGo is frozen by an abandoned GC stop-the-world, restart the world. Read-only otherwise.

WHY (2026-09-09, user: "You froze the game again, you really ought to find a way to stop doing that"). The two ANR
reports the system saved (00:09, 00:41) show every Unity thread parked in sigsuspend inside libil2cpp: a tool
stopped the IL2CPP GC world and never restarted it. The cause in the tool chain is fixed (pogo_il2cpp._bag_walk_core
no longer stops the world), but if it ever happens again this restarts the world instead of the user killing the game.

SAFETY: it only acts when UnityMain has been in sigsuspend for >= 3 s across three /proc probes. A real collection
pauses the world for milliseconds, so a world stopped that long was stopped by a tool and abandoned. Nothing else is
touched. Exit 0 = not frozen (nothing done) or rescued; 1 = frozen and the rescue failed.

Usage:  python unfreeze_game.py            # probe, rescue if frozen
        python unfreeze_game.py --probe    # probe only, never attach
"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg


def main():
    dev = pg._resolve_device()
    pid = pg._adb_pidof(dev) if dev else None
    if not pid:
        print('PoGo is not running -- nothing to rescue'); return 0
    w = pg._adb_unitymain_wchan(dev, pid)
    print('pid %s  UnityMain wchan=%s' % (pid, w or '?'))
    if not pg.game_world_frozen(pid, samples=3, gap_s=1.0):
        print('not frozen (UnityMain is not parked in sigsuspend) -- nothing done'); return 0
    if '--probe' in sys.argv:
        print('FROZEN: UnityMain in sigsuspend >= 3 s. Re-run without --probe to restart the GC world.'); return 1
    print('FROZEN: restarting the GC world through a fresh session...')
    sess, _ = pg.get_session(allow_cold=True)
    try:
        scr = pg.get_script_with_helpers(sess)
        try:
            print('  forceStartWorld ->', scr.exports_sync.force_start_world())
        finally:
            scr.unload()
    finally:
        sess.detach()
    time.sleep(1.5)
    w2 = pg._adb_unitymain_wchan(dev, pid)
    ok = 'sigsuspend' not in w2
    print('after rescue: UnityMain wchan=%s -> %s' % (w2 or '?', 'RUNNING' if ok else 'STILL FROZEN'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

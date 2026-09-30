"""TRUE server-side tag verification: force PoGo to refetch from the server, then reconcile.

WHY THIS EXISTS (2026-07-25): a sync reported "Transfer 480/480 OK / All tags in sync", but the
Transfer tag was EMPTY on the phone. Cause: reconcile_tags reads
`TaggingRpcService.GetCachedTagToPokemonBindingForIndex` -- the CLIENT CACHE. A tag write populates
that same cache, so the post-sync check can confirm a write that never reached the server. There is NO
server-fetch method on TaggingRpcService (method dump: everything is GetCached*/GetAllTags(cache) +
AddTagCacheUpdatedCallback), so the ONLY honest verification is: force-stop PoGo -> relaunch -> the
client refetches tags from the server -> reconcile. That is what this script does.

User rule: "always check my live phone. youve already proven unreliable with your own memory/db."

Usage:  python verify_tags_live.py            # restart PoGo + verify every tag (skips the restart
                                              #   if the user is ACTIVELY PLAYING -- see below)
        python verify_tags_live.py --no-restart  # reconcile only (cache read -- NOT proof)
        python verify_tags_live.py --force       # restart even mid-play (user asked for hard proof NOW)
Exit 0 = every tag matches after a genuine server refetch. Exit 1 = drift (a write did not persist).

USER RULE (2026-08-14): "Stop crashing the app everytime you do an audit." The restart is invisible
when the phone is idle (screen off / PoGo backgrounded) but kills the user's session mid-play. So:
screen interactive AND PoGo foregrounded => fall back to a cache reconcile, say so honestly, and let
the caller re-run later for server proof. Idle phone => full restart-verify as before.
"""
import json, os, subprocess, sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
os.chdir(ROOT)
import pogo_il2cpp as pg

DEV = pg.ADB_TARGET                  # env ADB_TARGET (the cloud bridge) or the phone's Tailscale address
PKG = 'com.nianticlabs.pokemongo'
ACT = PKG + '/com.nianticproject.holoholo.libholoholo.unity.UnityMainActivity'


def _adb(*args):
    return subprocess.run(['adb', '-s', DEV, 'shell'] + list(args), capture_output=True, text=True).stdout.strip()


def user_is_playing():
    """True iff the screen is interactive AND PoGo is the resumed (visible) activity.

    That combination = the user is in the game RIGHT NOW; a force-stop would eat their session.
    Screen off / dozing, or PoGo merely backgrounded, = a restart costs the user nothing.
    """
    wake = _adb('dumpsys', 'power')
    interactive = ('mWakefulness=Awake' in wake) or ('mScreenOn=true' in wake)
    if not interactive:
        return False
    top = _adb('dumpsys', 'activity', 'activities')
    for ln in top.splitlines():
        if 'topResumedActivity' in ln or 'ResumedActivity' in ln:
            return PKG in ln
    return False


def restart_pogo():
    # NEVER RESTART THE GAME (user 2026-09-25: "the cull should never restart the game. ever."). The auto-catcher
    # runs on it and Pokemod must be the one that launches it. Kept only so old callers fail loudly, not silently.
    raise RuntimeError('restart_pogo is disabled: the cull never restarts PoGo (user rule 2026-09-25)')
    print('force-stopping PoGo (forces a server tag refetch on relaunch)...')
    _adb('am', 'force-stop', PKG)
    time.sleep(3)
    _adb('input', 'keyevent', 'KEYCODE_WAKEUP')
    _adb('am', 'start', '-n', ACT)
    print('relaunched; waiting for attach-safety via ADB (no Frida probes -- they CRASH a loading app)...')
    try:
        pid = pg.wait_ready_to_attach(timeout_s=300)   # pure /proc polling; attaches nothing
    except Exception as e:
        print(f'  never became attach-safe: {e}')
        return False
    for attempt in range(6):
        try:
            sess, pid = pg.get_session()
            bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
            n = len(pg.walk_bag_protos(sess, bag))     # raises unless the walk is provably complete
            sess.detach()
            print(f'  ready: pid={pid}, complete bag walk ({n} mons)')
            return True
        except Exception as e:
            print(f'  waiting... ({str(e)[:60]})')
            time.sleep(9)
    return False


def main():
    argv = sys.argv[1:]
    cache_only = True          # ALWAYS (user 2026-09-25: "never restart the game. ever.") -- --force no longer restarts
    if not cache_only and '--force' not in argv and user_is_playing():
        print('[user is ACTIVELY PLAYING -- screen on + PoGo foregrounded]')
        print('skipping the force-restart (user rule 2026-08-14: no app kills mid-play);')
        print('falling back to a cache reconcile. Re-run when the phone is idle (or --force) for server proof.')
        cache_only = True
    if not cache_only:
        if not restart_pogo():
            print('FAIL: PoGo never became ready -- cannot verify')
            return 1
    else:
        print('[cache-only] reading the CLIENT CACHE -- this is NOT proof of server state')

    r = subprocess.run([sys.executable, os.path.join('system', 'scripts', 'reconcile_tags.py'), '--report'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    out = r.stdout or ''
    print(out[-2000:] if len(out) > 2000 else out)
    # NO-TABLE = NO PASS (2026-08-19): the reconcile subprocess crashed after a relaunch and produced
    # EMPTY stdout -- zero DRIFT lines -- so the scans below all came up clean and this script printed
    # "VERIFIED" without having compared a single tag. Same false-PASS class as the missing-tag case:
    # absence of evidence scanned as evidence of absence. Require the actual per-tag table + summary.
    if r.returncode != 0 or ('status' not in out or ('All tags in sync.' not in out and 'Drift detected.' not in out)):
        print('\n*** VERIFICATION FAILED -- reconcile produced no tag table (rc=%s). Nothing was compared. ***' % r.returncode)
        err = (r.stderr or '').strip()
        if err:
            print(err[-1200:])
        return 1
    # FAILURE MODES (all must be caught -- a missing tag produces NO 'DRIFT' row, which false-PASSED
    # the brand-new-account case on 2026-07-25: 10 tags absent from the server, verifier said OK):
    #   1. a per-tag row ending in DRIFT
    #   2. 'DB tags NOT on server: [...]'   <- tag never created / did not persist
    #   3. reconcile's own 'Drift detected.' summary line
    drift = [ln for ln in out.splitlines() if ln.strip().endswith('DRIFT')]
    missing = [ln for ln in out.splitlines() if 'NOT on server' in ln]
    summary = [ln for ln in out.splitlines() if ln.strip().lower().startswith('drift detected')]
    if drift or missing or summary:
        print('\n*** VERIFICATION FAILED -- the phone does NOT match the engine: ***')
        for ln in drift + missing + summary:
            print('   ', ln.strip())
        print('\nRe-run the sync, then run this script again. A tag that repeatedly fails to persist')
        print('is a real write failure (batch too large / server rejection), not a cache lag.')
        return 1
    if cache_only:
        # H06-4 (2026-09-29): cache_only is ALWAYS True since 2026-09-25, so "user was playing" / "re-run when idle" named
        # a reason and a remedy that no longer exist -- no run of this script can reach the server refetch any more.
        print('\n*** CACHE reconcile clean (no restart -- the cull never restarts PoGo, user rule 2026-09-25). ***')
        print('*** NOT server proof: nothing in the cull re-reads the tags from the server any more.        ***')
    else:
        print('\n*** VERIFIED against the live phone after a genuine server refetch: every tag persisted. ***')
    return 0


if __name__ == '__main__':
    sys.exit(main())

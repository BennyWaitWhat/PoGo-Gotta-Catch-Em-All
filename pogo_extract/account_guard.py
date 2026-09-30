"""ONE ACCOUNT PER DATA SET (user 2026-09-26: "make sure to keep oyebenny and florandez settings different").

Each trainer has its own pokemon.db, keep_config.json and history (ladder, report state, Stop-tag registry, walk
snapshots). The LIVE set sits in the usual paths; the others rest in accounts/<name>/. `active_account.txt` names
the trainer the live set belongs to.

  trainer_name(sess)  -> the logged-in trainer's name, read-only (PlayerService -> ClientPlayerProto.Name)
  check(sess)         -> raise SystemExit BEFORE any DB write when the phone's trainer is not the active one
                         (2026-09-26: a walk of a second account landed in the main DB). A failed READ only warns.
  python switch_account.py <name>  -- park the live set in accounts/<active>/, bring <name>'s back.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ACTIVE = os.path.join(HERE, 'active_account.txt')
# data-set name -> the trainer name the game shows, where they differ (2026-09-27: the main set is named after the login,
# 'oyebenny', while the game says 'BennyValentinC' -- the guard sent him to a set that does not exist)
TRAINERS = {'oyebenny': 'BennyValentinC'}

_JS = r'''
rpc.exports.readPtr = function (p, off) { return ptr(p).add(off).readPointer().toString(); };
rpc.exports.readStr = function (p) { var s = ptr(p); if (s.isNull()) return null; var n = s.add(0x10).readS32();
    return (n >= 0 && n < 200) ? s.add(0x14).readUtf16String(n) : null; };
'''


def active():
    try:
        return open(ACTIVE, encoding='utf-8').read().strip() or None
    except OSError:
        return None


def trainer_name(sess):
    """ClientPlayerProto.Name via PlayerService's PlayerInfo field (found by TYPE -- the service is obfuscated, the proto
    is not). Plain reads + one field enumeration; the PlayerService pick is the pipeline's cached, world-safe one."""
    import pogo_il2cpp as pg
    import read_medals as rm
    psvc = pg.pick_singleton(sess, 'Niantic.Holoholo', 'PlayerService')
    sc = pg.get_script_with_helpers(sess, rm._ENGINE + _JS)
    try:
        svc = sc.exports_sync.read_obj_fields(psvc)['fields']
        off = next(v['off'] for v in svc.values() if (v.get('type') or '').endswith('PlayerService.PlayerInfo'))
        pinfo = sc.exports_sync.read_ptr(psvc, off)
        noff = sc.exports_sync.read_obj_fields(pinfo)['fields']['Name']['off']
        return sc.exports_sync.read_str(sc.exports_sync.read_ptr(pinfo, noff))
    finally:
        sc.unload()


def check(sess, say=print):
    want = active()
    try:
        got = trainer_name(sess)
    except Exception as e:
        say('   [WARN] account guard: trainer name unreadable (%s) -- continuing as %s' % (e, want))
        return None
    # AN EMPTY READ IS A FAILED READ, NOT A MATCH (2026-09-29, H06-5). read_str returns None for a null pointer or a length
    # outside 0..200, and `want and got and ...` then skipped the comparison and printed "account: None" as if the
    # trainer had been checked -- the guard waved the walk through exactly when it could not see the account. Same
    # for a missing active_account.txt: nothing to compare with. Both now say so the way a failed read does.
    if not got:                                   # None / '' only: a garbage non-empty name still stops below (fail-closed)
        say('   [WARN] account guard: trainer name read back EMPTY (%r) -- the account was NOT checked; continuing as %s'
            % (got, want))
        return None
    if not want:
        say('   [WARN] account guard: active_account.txt is missing, empty or unreadable -- the phone is on %r but there is no '
            'data-set name to check it against; continuing (the account is NOT verified)' % got)
        return got
    if want and got and got.strip().lower() != TRAINERS.get(want, want).lower():
        _set = {v.lower(): k for k, v in TRAINERS.items()}.get(got.strip().lower(), got.strip().lower())
        raise SystemExit('ACCOUNT GUARD: the phone is logged in as %r but the live data set is %r. Nothing was written. '
                         'Run: python switch_account.py %s' % (got, want, _set))
    say('   account: %s' % got)
    return got

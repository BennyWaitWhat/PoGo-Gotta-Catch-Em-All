"""check_freshness.py -- fast bag-vs-DB freshness reporter.

Walks the LIVE PokemonBagImpl bag via Frida/IL2CPP and compares the set of
UIDs to the pokemon.db in_bag=1 rows.  Prints a concise freshness report:

    live bag size, DB in_bag size, new catches (live_only), gone (db_only),
    agreement %, DB file age, and a FRESH / RE-CRAWL NEEDED verdict.

Exit code 0 = fresh (zero drift), 1 = stale (drift detected).
Does NOT modify the DB -- read-only.

Usage:
    python system/scripts/check_freshness.py          # default pokemon.db
    python system/scripts/check_freshness.py other.db  # explicit path
"""
import os
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

# ---------------------------------------------------------------------------
# Resolve project root so we can import pogo_il2cpp regardless of cwd.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, '..', '..'))
sys.path.insert(0, _PROJECT_ROOT)

import pogo_il2cpp as pg  # noqa: E402


def _db_path_from_argv():
    """Return DB path: first CLI arg or <project_root>/pokemon.db."""
    if len(sys.argv) > 1:
        return sys.argv[1]
    return os.path.join(_PROJECT_ROOT, 'pokemon.db')


def _fmt_age(seconds):
    """Human-readable age string from seconds."""
    if seconds < 60:
        return f'{seconds:.0f}s'
    if seconds < 3600:
        return f'{seconds / 60:.1f}m'
    if seconds < 86400:
        return f'{seconds / 3600:.1f}h'
    return f'{seconds / 86400:.1f}d'


def main():
    db_file = _db_path_from_argv()
    if not os.path.isfile(db_file):
        print(f'ERROR: DB not found: {db_file}')
        return 2

    # -- DB read (fast, no Frida needed yet) --------------------------------
    conn = sqlite3.connect(f'file:{db_file}?mode=ro', uri=True)
    db_uids = {r[0] for r in conn.execute(
        "SELECT uid_hex FROM pokemon WHERE in_bag = 1"
    )}

    # -- DB file age --------------------------------------------------------
    db_mtime = os.path.getmtime(db_file)
    db_age_s = time.time() - db_mtime
    db_age_str = _fmt_age(db_age_s)

    # -- Live bag walk via Frida --------------------------------------------
    sess, pid = pg.get_session()
    print(f'Attached to PID {pid}')
    try:
        bag_addr = pg.pick_singleton(
            sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl'
        )
        live_map = pg.walk_bag_protos(sess, bag_addr)
        _graph = dict(getattr(sess, '_pogo_graph', None) or {})   # H03: the graph the walk above read, and its clock
    finally:
        sess.detach()

    # -- Convert decimal UIDs to 16-char hex --------------------------------
    live_uids = {f'{int(u) & 0xFFFFFFFFFFFFFFFF:016x}' for u in live_map}

    # -- Set comparison -----------------------------------------------------
    live_only = live_uids - db_uids    # new catches not in DB
    db_only   = db_uids - live_uids    # transferred since scan
    overlap   = live_uids & db_uids

    total_union = len(live_uids | db_uids)
    agreement = 100.0 * len(overlap) / max(1, total_union)

    # -- Report -------------------------------------------------------------
    print()
    print(f'Live bag size    : {len(live_uids)}')
    print(f'DB in_bag size   : {len(db_uids)}')
    print(f'DB file age      : {db_age_str} ({time.strftime("%Y-%m-%d %H:%M", time.localtime(db_mtime))})')
    print(f'New (live only)  : {len(live_only)}')
    print(f'Gone (DB only)   : {len(db_only)}')
    print(f'Agreement        : {agreement:.1f}%')
    print()

    # THE BAG WE COMPARED AGAINST MUST ITSELF BE LIVE (H03, 2026-09-29). A walk of the game's abandoned service graph
    # returns the same frozen uid set a frozen recrawl wrote -- this tool printed FRESH for exactly the state the
    # 05:06 / 05:09 / 05:11 culls were in. The graph's inventory age (phone clock) is printed with every verdict; past 5 min
    # it is flagged -- a quiet game is that old as often as a frozen one (review 2026-09-29: the catcher log shows 19 live
    # gaps > 5 min in 9,006 catches), so age alone never decides; the cull's walk tripwires judge a frozen graph (rc 8).
    try:
        _ts, _now = int(_graph.get('ts')), int(_graph.get('now'))
    except (TypeError, ValueError):
        _ts = _now = None
    print('Graph            : %s service graph(s); inventory of the walked graph updated %s before this read'
          % (_graph.get('bags') or '?', ('%.0f s' % ((_now - _ts) / 1000.0)) if (_ts and _now) else '? (unreadable)'))
    if _ts and _now and _now - _ts > 5 * 60 * 1000:
        print('  [WARN] that inventory is %.0f min old: a quiet game, or a frozen graph (then a re-crawl reads the same '
              'copy -- the cull stops itself with rc 8 when the catcher log proves it)' % ((_now - _ts) / 60000.0))
    if not live_only and not db_only:
        print('VERDICT: FRESH')
        conn.close()
        return 0

    print(f'VERDICT: RE-CRAWL NEEDED: '
          f'{len(live_only)} new, {len(db_only)} gone '
          f'-> run `python pogo_pipeline.py`')
    # Show a few samples so the user sees what drifted
    if live_only:
        sample = sorted(live_only)[:10]
        print(f'  sample new UIDs: {", ".join(sample)}')
    if db_only:
        rows = conn.execute(
            "SELECT uid_hex, species_name, cp FROM pokemon "
            "WHERE uid_hex IN ({}) LIMIT 10".format(
                ','.join('?' for _ in db_only)
            ),
            tuple(db_only),
        ).fetchall()
        if rows:
            print('  sample gone:')
            for uid, name, cp in rows:
                print(f'    {uid}  {name or "?"} CP{cp or "?"}')
    conn.close()
    return 1


if __name__ == '__main__':
    sys.exit(main())

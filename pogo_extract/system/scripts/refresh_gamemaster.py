"""refresh_gamemaster.py -- pull PvPoke's current game master, diff it, recompute every rank, and
REFUSE to leave a silently-changed pile behind.

WHY (user, 2026-09-08): "This should be checked often, at least once a month." pvpoke_gamemaster.json is
the base-stat source for EVERY PvP rank this project culls on, and it had gone 85 days without a
producer script. A species added or rebalanced upstream is simply missing/wrong here until refreshed.

WHAT IT DOES
  1. downloads https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/gamemaster.json
  2. diffs it against the local file: species added/removed, base-stat changes, movepool changes
  3. backs up the local file (pvpoke_gamemaster.json.bak-<date>) and installs the new one
  4. recomputes every rank via system/scripts/rank_cache.py (offline -- no phone)
  5. reports every in-bag row that CROSSED the READY_RANK (<=5) protection line in either direction,
     and every row whose ranks went NULL (an unresolvable species = the Mudbray failure class)
  6. exits 0 when nothing crossed; exits 2 when something did or went NULL -- so a caller (full_audit)
     stops BEFORE any sync and a human looks. It never touches the phone and never edits the pile.

  --check-only   : just report the file's age and whether it is older than MAX_AGE_DAYS (exit 3 if so)
  --force        : refresh even if the file is younger than MAX_AGE_DAYS
  --ack          : a human has reviewed the rows a refresh moved across the keep line -- clear the stop. Until then
                   EVERY run exits 2 (system/analysis/gamemaster_review_pending.json), whatever the file's age. For a
                   refresh that died between installing the new file and diffing it, --ack ROLLS IT BACK instead (the
                   backup keeps its old mtime, so the next run downloads and diffs again).

Rank changes are expected and fine (a rebalanced species re-ranks); a change that moves a mon ACROSS
the keep line is the only thing that matters, and the pile gate (keep_policy -> preflight) still stands
behind this script -- it is a tripwire, not the gate.
"""
import sys, os, json, shutil, sqlite3, subprocess, time, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
GM = os.path.join(ROOT, 'pvpoke_gamemaster.json')
DL_STAMP = GM + '.downloaded'                 # {'ts': epoch} of the last DOWNLOAD installed (H04-11)
DB = os.path.join(ROOT, 'pokemon.db')
URL = 'https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/gamemaster.json'
PM_URL = 'https://raw.githubusercontent.com/PokeMiners/game_masters/master/latest/latest.json'
PM = os.path.join(os.path.dirname(GM), 'gamemaster_pokeminers.json')   # the CLIENT game master: per-form evolvability, AE moves
# pvpoke's META rankings (2026-09-29): the top-N gate for Power Up / Unlock 2nd Move (granular_tags.meta_top). Same monthly
# clock as the game master; pvpoke re-cuts them at season and move changes.
RANK_URL = 'https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/rankings/all/overall/rankings-%d.json'
RANK_DIR = os.path.join(ROOT, 'system', 'analysis', 'pvpoke_rankings')
RANK_CAPS = (1500, 2500, 10000)
# THE STOP MUST OUTLIVE THE PASS THAT RAISED IT (2026-09-29, H04). Exit 2 ("keep decisions moved -- do NOT sync until
# reviewed") was re-derived from the file's AGE on the very next run: the refresh had just installed a fresh
# pvpoke_gamemaster.json, so the next full_audit printed "fresh enough -- nothing to do", exited 0 and recrawled + synced
# on the unreviewed ranks. The crossing is recorded here; every run exits 2 until a human clears it with --ack.
REVIEW = os.path.join(ROOT, 'system', 'analysis', 'gamemaster_review_pending.json')


def _write_review(rec):
    """Atomically (re)write the pending-review record; False when it could not be written."""
    try:
        with open(REVIEW + '.tmp', 'w', encoding='utf-8') as _f:
            json.dump(rec, _f, indent=1)
        os.replace(REVIEW + '.tmp', REVIEW)
        return True
    except OSError as _e:
        print('!! could not write %s (%s)' % (REVIEW, _e))
        return False


def _clear_review():
    try:
        os.remove(REVIEW)
    except FileNotFoundError:
        pass


def review_gate(argv):
    """None = no review pending (carry on); else the exit code. --ack clears a pending review (exit 0) -- or, for a
    refresh that died between install and diff ('in progress'), rolls the install back (R-B review)."""
    pend = None
    if os.path.exists(REVIEW):
        try:
            pend = json.load(open(REVIEW, encoding='utf-8'))
        except Exception as e:                  # unreadable is still pending: fail closed
            pend = {'since': '? (unreadable: %s)' % e}
        if not isinstance(pend, dict):          # a null / list record is still a pending file: fail closed (R-B review --
            pend = {'since': '? (malformed record: %r)' % (pend,)}   # 'null' passed the gate, '[]' crashed it with rc 1)
    _interrupted = pend is not None and pend.get('status') == 'in progress'
    if '--ack' in argv:
        if pend is None:
            print('--ack: no game-master review was pending')
            return 0
        if _interrupted:
            # nothing was diffed, so there is nothing to acknowledge: put the previous file back. copy2 keeps its OLD
            # mtime, so the next run downloads again, diffs it and records any crossing
            _bak = os.path.join(os.path.dirname(GM), pend.get('backup') or '?')
            if not os.path.exists(_bak):
                print('--ack: the interrupted refresh names no usable backup (%s) -- restore pvpoke_gamemaster.json by '
                      'hand, then delete %s' % (pend.get('backup'), REVIEW))
                return 2
            shutil.copy2(_bak, GM)
            print('--ack: the interrupted %s refresh was rolled back to %s; the next run refreshes and diffs again'
                  % (pend.get('since'), pend.get('backup')))
        _clear_review()
        print('game-master review acknowledged (pending since %s: %d crossed, %d NULL) -- culls may continue'
              % (pend.get('since'), len(pend.get('crossed') or []), len(pend.get('nulled') or [])))
        return 0
    if pend is None:
        return None
    if _interrupted:
        print('The %s refresh stopped after installing the new game master and BEFORE its rank changes were diffed '
              '(killed / timed out) -- nothing may sync on ranks nobody compared.' % pend.get('since'))
    else:
        for l in (pend.get('lines') or [])[:40]:
            print('   ' + l)
        print('The %s refresh moved keep decisions across the rank<=%d line; nothing may sync until a human has reviewed them.'
              % (pend.get('since'), READY_RANK))
    print('   rows: %s -- clear it (an interrupted refresh: roll it back) with: python system/scripts/refresh_gamemaster.py --ack'
          % os.path.relpath(REVIEW, ROOT))
    print('REVIEW PENDING since %s (%s): after review run refresh_gamemaster.py --ack'
          % (str(pend.get('since'))[:16], 'interrupted refresh' if _interrupted else '%d crossed, %d NULL' % (
              len(pend.get('crossed') or []), len(pend.get('nulled') or []))))
    return 2


def refresh_rankings(top_n=None):
    """Download the three ranking files; keep the old one on any doubt (fewer than 300 entries, no 'score'). Prints what
    moved in and out of the top-N -- the exact set the dust advice reads."""
    os.makedirs(RANK_DIR, exist_ok=True)
    if top_n is None:
        sys.path.insert(0, ROOT)
        import keep_config as _kc
        top_n = max(_kc.pvp('power_up_meta_top'), _kc.pvp('unlock_meta_top')) or 200
    for cap in RANK_CAPS:
        dst = os.path.join(RANK_DIR, 'rankings-%d.json' % cap)
        tmp = dst + '.download'
        try:
            with urllib.request.urlopen(RANK_URL % cap, timeout=60) as r, open(tmp, 'wb') as f:
                f.write(r.read())
            new = json.load(open(tmp, encoding='utf-8'))
            if not isinstance(new, list) or len(new) < 300 or 'score' not in new[0] or 'speciesId' not in new[0]:
                raise ValueError('unexpected shape (%s entries)' % (len(new) if isinstance(new, list) else '?'))
            top = lambda d: {x['speciesId'] for x in sorted(d, key=lambda x: -(x.get('score') or 0))[:top_n]}
            old = json.load(open(dst, encoding='utf-8')) if os.path.exists(dst) else []
            a, b = top(old), top(new)
            os.replace(tmp, dst)
            print('rankings-%d.json: %d entries | top-%d: +%d %s -%d %s' % (
                cap, len(new), top_n, len(b - a), sorted(b - a)[:10], len(a - b), sorted(a - b)[:10]))
        except Exception as e:
            print('rankings-%d.json: DOWNLOAD FAILED (%s) -- local file left untouched' % (cap, e))
            if os.path.exists(tmp):
                os.remove(tmp)


def refresh_pokeminers():
    """Same monthly clock as pvpoke's file. evolvable_forms.py re-derives its cache from the new mtime."""
    tmp = PM + '.download'
    try:
        with urllib.request.urlopen(PM_URL, timeout=120) as r, open(tmp, 'wb') as f:
            f.write(r.read())
        n = sum(1 for t in json.load(open(tmp, encoding='utf-8')) if 'pokemonSettings' in t.get('data', {}))
        if n < 1500:
            raise ValueError('only %d pokemonSettings -- refusing' % n)
        os.replace(tmp, PM)
        print('gamemaster_pokeminers.json refreshed (%d pokemonSettings)' % n)
    except Exception as e:
        print('PokeMiners download failed (%s) -- local client game master left untouched' % e)
        if os.path.exists(tmp):
            os.remove(tmp)
MAX_AGE_DAYS = 30
READY_RANK = 5


def age_days(path):
    """Days since the game master was DOWNLOADED (H04-11, 2026-09-29): the file's mtime moved with every local rewrite --
    reconcile_gamemaster.py edits it in place, a rollback's copy2 restores an old one -- so a manual reconcile restarted
    the 30-day clock without a download. The install writes DL_STAMP; mtime is the fallback before the first stamp."""
    if not os.path.exists(path):
        return 1e9
    if os.path.abspath(path) == os.path.abspath(GM) and os.path.exists(DL_STAMP):
        try:
            return (time.time() - float(json.load(open(DL_STAMP, encoding='utf-8'))['ts'])) / 86400.0
        except (OSError, ValueError, KeyError, TypeError):
            pass                                  # an unreadable stamp: the mtime, as before
    return (time.time() - os.path.getmtime(path)) / 86400.0


def _set_dl_stamp(raw):
    """raw = the stamp file's previous text (None = there was none): restore it exactly on a rollback."""
    try:
        if raw is None:
            if os.path.exists(DL_STAMP):
                os.remove(DL_STAMP)
        else:
            open(DL_STAMP, 'w', encoding='utf-8').write(raw)
    except OSError as e:
        print('!! could not restore %s (%s) -- the refresh clock may read wrong' % (os.path.basename(DL_STAMP), e))


def species(gm):
    return {p['speciesId']: p for p in (gm['pokemon'] if isinstance(gm, dict) and 'pokemon' in gm else gm)}


def ranks(con):
    return {r[0]: r[1:] for r in con.execute(
        'SELECT uid_hex, gl_rank, ul_rank, ll_rank FROM pokemon WHERE in_bag=1')}


def main(argv):
    age = age_days(GM)
    print('pvpoke_gamemaster.json age: %.1f days (limit %d)' % (age, MAX_AGE_DAYS))
    if '--check-only' in argv:
        return 3 if age > MAX_AGE_DAYS else 0
    _gate = review_gate(argv)                  # a pending review stops EVERY run until --ack, whatever the file's age
    if _gate is not None:
        return _gate
    if age <= MAX_AGE_DAYS and '--force' not in argv:
        print('fresh enough -- nothing to do (use --force to refresh anyway)')
        return 0

    refresh_pokeminers()                                    # client game master on the same clock (2026-09-16)
    refresh_rankings()                                      # pvpoke meta rankings on the same clock (2026-09-29)
    tmp = GM + '.download'
    try:
        with urllib.request.urlopen(URL, timeout=60) as r, open(tmp, 'wb') as f:
            f.write(r.read())
        new = json.load(open(tmp, encoding='utf-8'))
        N = species(new)
        if len(N) < 1000:
            raise ValueError('downloaded file has only %d species -- refusing' % len(N))
    except Exception as e:
        print('DOWNLOAD FAILED (%s) -- local file left untouched' % e)
        if os.path.exists(tmp):
            os.remove(tmp)
        return 1

    O = species(json.load(open(GM, encoding='utf-8'))) if os.path.exists(GM) else {}
    added = sorted(set(N) - set(O)); removed = sorted(set(O) - set(N))
    stat = [s for s in N if s in O and N[s]['baseStats'] != O[s]['baseStats']]
    print('species: %d -> %d | added %d | removed %d | base-stat changes %d'
          % (len(O), len(N), len(added), len(removed), len(stat)))
    for s in stat:
        print('   stats %-24s %s -> %s' % (s, tuple(O[s]['baseStats'].values()), tuple(N[s]['baseStats'].values())))
    if removed:
        print('   removed: %s' % ', '.join(removed[:12]))
        # a removed speciesId that an override still points at would NULL that mon's ranks
        ov = open(os.path.join(ROOT, 'form_overrides_complete.py'), encoding='utf-8').read()
        hit = [s for s in removed if ("'%s'" % s) in ov]
        if hit:
            print('   *** form_overrides_complete.py still maps to removed speciesId(s): %s -- fix before '
                  'refreshing, or those mons lose their rank ***' % hit)
            os.remove(tmp)
            return 2

    bak = GM + '.bak-' + time.strftime('%Y%m%d')
    shutil.copy2(GM, bak)
    # RECORD BEFORE INSTALL (R-B review): the record was written only at the very end, so a refresh killed or timed out
    # between this install and the diff (reconcile 900 s + rank_cache 1800 s budgets; full_audit's own timeout is 1800 s)
    # left a FRESH file and no record -> the next run said 'fresh enough', recrawled and synced on ranks nobody compared.
    # Replaced by the crossing record below, or cleared on REFRESH OK and on every restore.
    if not _write_review({'status': 'in progress', 'since': time.strftime('%Y-%m-%d %H:%M:%S'),
                          'backup': os.path.basename(bak)}):
        os.remove(tmp)
        print('NOT installed: the in-progress record could not be written -- local file left untouched')
        return 1
    _old_dl = open(DL_STAMP, encoding='utf-8').read() if os.path.exists(DL_STAMP) else None
    os.replace(tmp, GM)
    _set_dl_stamp(json.dumps({'ts': time.time(), 'at': time.strftime('%Y-%m-%d %H:%M:%S')}))   # H04-11: the download time
    print('installed; previous file kept as %s' % os.path.basename(bak))

    # A FRESH pvpoke FILE IS AN UNRECONCILED ONE (2026-09-20). pvpoke's gamemaster is missing evolution edges
    # the client's own game master has -- corsola_galarian -> cursola, zygarde -> zygarde_complete,
    # poltchageist -> sinistcha (which pvpoke files BACKWARDS), rockruff -> lycanroc_dusk (pvpoke's id is
    # misspelled 'lycranroc_dusk', so the stage was unrankable). _reachable() can only trim stages, never add
    # them, so a missing edge is a stage that is never scored -- the under-protection direction. Downloading a
    # new copy silently undoes every one of those fixes, so reconcile before the ranks are computed below.
    _rc = subprocess.run([sys.executable, os.path.join(ROOT, 'reconcile_gamemaster.py')],
                         capture_output=True, text=True, timeout=900)
    for _l in (_rc.stdout or _rc.stderr).strip().splitlines():
        print('   reconcile: %s' % _l)
    if _rc.returncode != 0:
        print('reconcile_gamemaster FAILED rc=%d -- restoring previous game master' % _rc.returncode)
        shutil.copy2(bak, GM)
        _set_dl_stamp(_old_dl)
        _clear_review()
        return 2

    con = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    before = ranks(con); con.close()
    r = subprocess.run([sys.executable, os.path.join(HERE, 'rank_cache.py')], capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        print('rank_cache FAILED rc=%d -- restoring previous game master' % r.returncode)
        shutil.copy2(bak, GM)
        _set_dl_stamp(_old_dl)
        _clear_review()
        return 1
    con = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    after = ranks(con)
    names = {u: n for u, n in con.execute('SELECT uid_hex, species_name FROM pokemon WHERE in_bag=1')}
    con.close()

    changed = [u for u in before if u in after and before[u] != after[u]]
    def prot(t):  # protected by rank = GL or UL rank <= READY_RANK
        return any(x is not None and x <= READY_RANK for x in t[:2])
    crossed = [u for u in changed if prot(before[u]) != prot(after[u])]
    nulled = [u for u in after if after[u][0] is None and after[u][1] is None
              and not (before.get(u, (None, None))[0] is None and before.get(u, (None, None))[1] is None)]
    print('ranks changed on %d row(s); crossed the rank<=%d line: %d; newly NULL: %d'
          % (len(changed), READY_RANK, len(crossed), len(nulled)))
    for u in crossed[:20]:
        print('   CROSSED %-14s gl %s->%s  ul %s->%s' % (names.get(u, u), before[u][0], after[u][0], before[u][1], after[u][1]))
    for u in nulled[:20]:
        print('   NULL    %-14s (species no longer resolves -- the Mudbray class; rule 15c keeps it, but fix the mapping)' % names.get(u, u))
    if crossed or nulled:
        # RECORDED, not just printed (H04): the next run finds a FRESH file and would otherwise exit 0 and sync.
        _lines = (['CROSSED %-14s %s gl %s->%s  ul %s->%s' % (names.get(u, u), u, before[u][0], after[u][0], before[u][1], after[u][1])
                   for u in crossed] + ['NULL    %-14s %s' % (names.get(u, u), u) for u in nulled])[:500]
        if not _write_review({'since': time.strftime('%Y-%m-%d %H:%M:%S'), 'crossed': crossed, 'nulled': nulled,
                              'backup': os.path.basename(bak), 'lines': _lines}):
            print('!! the crossing record could not be written; the in-progress record still stops every run (--ack then '
                  'rolls this refresh back and the next run diffs it again)')
        print('   rows: %s -- after review: python system/scripts/refresh_gamemaster.py --ack' % os.path.relpath(REVIEW, ROOT))
        print('REFRESH APPLIED BUT NEEDS A HUMAN: keep decisions moved; every run exits 2 until --ack (exit 2)')   # <= 110
        return 2
    _clear_review()
    print('REFRESH OK -- no keep decision moved.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

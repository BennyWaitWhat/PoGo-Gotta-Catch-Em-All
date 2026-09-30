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

THE CLIENT GAME MASTER (gamemaster_pokeminers.json), 2026-09-30: pokeminers_phase() runs on EVERY run -- it asks
PokeMiners' 13-byte latest/timestamp.txt, not the 30-day pvpoke clock. A NEW batch is downloaded, DIFFED and judged against
the bags (the active account's and every resting account's parked one: the file is shared) BEFORE it is installed
(gm_guard.assess reuses detect_legacy's pool functions, evolvable_forms, isTradable,
isTransferable and the rarity classes): if any in-bag keep verdict flips it is installed with a dated backup, the SAME
review record is written and the run exits 2 (--ack clears it); a candidate the engine cannot load is never installed.
The batch is stamped in gamemaster_pokeminers.json.meta (batch time, APK, sha256) for audit_invariants I2.7.
  --selftest     : offline proof of all of it on synthetic fixtures (touches nothing outside a temp dir)
An unknown flag stops the run with exit 2 and does NOTHING (like full_audit.py).
"""
import sys, os, json, shutil, sqlite3, subprocess, time, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
GM = os.path.join(ROOT, 'pvpoke_gamemaster.json')
DL_STAMP = GM + '.downloaded'                 # {'ts': epoch} of the last DOWNLOAD installed (H04-11)
DB = os.path.join(ROOT, 'pokemon.db')
URL = 'https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/gamemaster.json'
PM = os.path.join(os.path.dirname(GM), 'gamemaster_pokeminers.json')   # the CLIENT game master: per-form evolvability, AE moves
PM_META = PM + '.meta'      # gm_guard's stamp of the installed batch (DATA: tools/data_manifest.txt [inventory] must carry it)
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
            _dst = PM if pend.get('target') == 'pokeminers' else GM      # the record says WHICH file its backup belongs to
            _bak = os.path.join(os.path.dirname(_dst), pend.get('backup') or '?')
            if not os.path.exists(_bak):
                print('--ack: the interrupted refresh names no usable backup (%s) -- restore %s by '
                      'hand, then delete %s' % (pend.get('backup'), os.path.basename(_dst), REVIEW))
                return 2
            shutil.copy2(_bak, _dst)
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
        print(pend.get('headline') or
              'The %s refresh moved keep decisions across the rank<=%d line; nothing may sync until a human has reviewed them.'
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


_PM_NOTE = ['']         # the client-game-master half of the ONE line main() ends with: full_audit shows only a run's LAST line, cut at 110


def _pm_ident(m):
    return ('%s%s' % (m['batch_utc'][:10], (' APK %s' % m['apk']) if m.get('apk') else '')) if m else 'unstamped'


def _pm_engine_inputs():
    """(move_map, form enum) every client-GM verdict is judged with. Raises when unreadable (the caller STOPs)."""
    mm = json.load(open(os.path.join(ROOT, 'move_id_to_name.json'), encoding='utf-8'))
    en = {int(k): v for k, v in json.load(open(os.path.join(ROOT, 'form_enum.json'), encoding='utf-8')).items()}
    return mm, en


def _pm_stop(gg, res, reason, bak=None, old_meta=None, new_meta=None):
    """Write the SAME review record the pvpoke crossing writes (extra keys are ignored by review_gate / full_audit)."""
    crossed = sorted({f['uid'] for f in res.get('flips') or []})
    nulled = sorted(res.get('nulled') or [])
    lines = gg.review_lines(res, old_meta, new_meta, bak) if res.get('flips') or res.get('nulled') else [reason]
    shown = gg.review_lines(res, old_meta, new_meta, bak, with_digest=False) if res.get('flips') or res.get('nulled') else [reason]
    rec = {'since': time.strftime('%Y-%m-%d %H:%M:%S'), 'kind': 'client_gm', 'target': 'pokeminers', 'reason': reason,
           'headline': 'The %s client game master check stopped the pass: %s. Nothing may sync until a human has reviewed it.'
                       % (time.strftime('%Y-%m-%d'), reason),
           'crossed': crossed, 'nulled': nulled, 'backup': os.path.basename(bak) if bak else None, 'lines': lines[:500],
           'old': old_meta and {k: old_meta.get(k) for k in ('batch_utc', 'apk', 'sha256')},
           'new': new_meta and {k: new_meta.get(k) for k in ('batch_utc', 'apk', 'sha256')},
           'axes': res.get('axes') or {}, 'flips': (res.get('flips') or [])[:500]}
    return _write_review(rec), shown


def pokeminers_phase(argv, fetch=None, now=None, gm_path=None, meta_path=None, db_path=None):
    """THE CLIENT GAME MASTER GUARD (2026-09-30) -> (rc, tail). rc None = carry on, 2 = a review is pending (the record is
    written), 1 = a new batch could not be installed safely. tail = a new client game master is installed (or owes its
    reconcile + rank pass): main() must run the pvpoke half even though its own 30-day clock has not run out.
      1. ask upstream's 13-byte latest/timestamp.txt -- EVERY run, no throttle (a monthly clock would leave a new batch
         unreviewed for weeks; the question costs 13 bytes and a failure is a WARN, never a stop)
      2. same batch and an unaltered file -> nothing to download (only the check time is stamped); an OLDER upstream batch
         (a stale edge or a rollback) is never installed over a newer one
      3. else download, then assess() against the bag BEFORE anything is installed:
           SAME            identical bytes: adopt the stamp (the file was installed before gm_guard existed)
           UNREADABLE_NEW  never installed, the installed file stays, WARN
           STOP            the baseline / the bag / a verdict cannot be read: nothing installed, record, rc 2
           CLEAR           dated backup, atomic install (of exactly the bytes that were judged), stamp
           FLIPS           record FIRST, then backup + atomic install + stamp, rc 2 (--ack clears it, as for a rank crossing)"""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import gm_guard as gg
    gm_path, meta_path, db_path = gm_path or PM, meta_path or PM_META, db_path or DB
    fetch = fetch or gg.http_get
    now = time.time() if now is None else now
    meta = gg.read_meta(meta_path)
    state = gg.local_state(gm_path, meta)
    tail = bool(meta and meta.get('tail_pending'))
    try:
        up_ts = gg.parse_ts(fetch(gg.PM_TS_URL + '?cb=%d' % now, 15))
    except Exception as e:
        print('WARN pokeminers: cannot read upstream latest/timestamp.txt (%s) -- the client game master is left as it is' % e)
        _PM_NOTE[0] = 'pokeminers %s: NOT checked (upstream unreachable)' % _pm_ident(meta)
        return None, tail
    if state == 'ok' and up_ts < meta['batch_ts']:
        # NEVER A DOWNGRADE (2026-09-30): batches only move forward. An OLDER timestamp is a stale CDN edge or a rollback --
        # installing it would put the previous batch back and stop the pass twice (now, and again when the edge heals)
        print("WARN pokeminers: upstream's latest batch (%s UTC) is OLDER than the installed one (%s UTC) -- a stale edge or a "
              "rollback; nothing downloaded, the installed client game master stays" % (gg._utc(up_ts / 1000.0), meta.get('batch_utc', '?')))
        _PM_NOTE[0] = 'pokeminers %s: upstream is OLDER, kept' % _pm_ident(meta)
        return None, tail
    if state == 'ok' and meta['batch_ts'] == up_ts and '--force' not in argv:
        meta['checked_ts'], meta['checked_at'], meta['upstream_ts'] = int(now), gg._utc(now), up_ts
        meta.pop('rejected', None)                           # upstream's newest IS what is installed: nothing is rejected any more
        if meta.get('apk') is None:                          # the tree lookup is retried every run until it answers
            meta['apk'], meta['folder'] = gg.lookup_apk(up_ts, fetch)
        if not gg.write_meta(meta_path, meta):
            print('WARN pokeminers: could not update %s (read-only?) -- its check time stays old' % os.path.basename(meta_path))
        _PM_NOTE[0] = 'pokeminers %s = upstream latest' % _pm_ident(meta)
        print('pokeminers: batch %s (%s UTC) is upstream\'s latest -- nothing to download' % (_pm_ident(meta), meta['batch_utc']))
        return None, tail
    print('pokeminers: %s -- downloading batch %s UTC to judge it against the bag'
          % ({'no-file': 'no local file', 'no-meta': 'the installed file has no stamp yet',
              'sha-mismatch': 'the installed file is not the one its stamp describes'}.get(
                  state, 're-checking (--force)' if '--force' in argv and meta and meta['batch_ts'] == up_ts else 'a NEW batch upstream'),
             gg._utc(up_ts / 1000.0)))
    tmp = gm_path + '.download'

    def _drop():
        if os.path.exists(tmp):
            os.remove(tmp)
    try:
        body = fetch(gg.PM_JSON_URL + '?cb=%d' % now, 180)
        if gg.parse_ts(fetch(gg.PM_TS_URL + '?cb=%d' % (now + 1), 15)) != up_ts:
            raise ValueError('upstream published while it was downloading; retried next run')
        with open(tmp, 'wb') as f:
            f.write(body)
    except Exception as e:
        _drop()
        print('WARN pokeminers: download failed (%s) -- the client game master is left as it is' % e)
        _PM_NOTE[0] = 'pokeminers %s: download FAILED, kept' % _pm_ident(meta)
        return None, tail
    res = gg.assess(gm_path, tmp, lambda: gg.load_bag(db_path), lambda: _pm_engine_inputs()[0], lambda: _pm_engine_inputs()[1])
    v = res['verdict']
    for l in gg.digest_lines(res['diff']) if res['diff'] else []:
        print('   ' + l)
    if v == 'UNREADABLE_NEW':
        _drop()
        print('WARN pokeminers: batch %s UTC NOT installed -- %s; the installed client game master stays'
              % (gg._utc(up_ts / 1000.0), res['reason']))
        if meta and state == 'ok':       # remember WHY, so the offline audit (I2.7) can say it; the next good check clears it
            meta['rejected'] = {'batch_ts': up_ts, 'batch_utc': gg._utc(up_ts / 1000.0), 'at': gg._utc(now), 'reason': res['reason'][:300]}
            meta['checked_ts'], meta['checked_at'], meta['upstream_ts'] = int(now), gg._utc(now), up_ts
            gg.write_meta(meta_path, meta)
        _PM_NOTE[0] = 'pokeminers %s: new batch REJECTED, kept' % _pm_ident(meta)
        return None, tail
    if v == 'STOP':
        _drop()
        ok, lines = _pm_stop(gg, res, res['reason'])
        for l in lines[:40]:
            print('   ' + l)
        print('pokeminers: STOP -- %s (nothing installed); review record %s' % (res['reason'], 'written' if ok else 'NOT WRITTEN'))
        return 2, tail
    if v == 'SAME':
        _drop()
        if state == 'ok' and meta['batch_ts'] != up_ts:
            print('WARN pokeminers: the timestamp moved (%s -> %s) but the content did not -- a stale CDN edge or a re-stamp; '
                  'NOT adopted, asked again next run' % (meta['batch_ts'], up_ts))
            _PM_NOTE[0] = 'pokeminers %s: timestamp moved, content same (kept)' % _pm_ident(meta)
            return None, tail
        apk, folder = gg.lookup_apk(up_ts, fetch)
        # A file its stamp does not describe (sha-mismatch) may be a batch that was installed and killed before it was stamped:
        # the reconcile + rank pass it owed may never have run, so it is owed AGAIN (an extra pass is only slow; a missing one
        # leaves pvpoke's file drifted from the client game master)
        owed = bool(tail) or state == 'sha-mismatch'
        nm = gg.new_meta(up_ts, res['new']['sha256'], apk, folder, now, tail_pending=owed)
        if meta and state == 'ok':                           # --force on an unchanged file: keep its install time and a known APK
            for k in ('downloaded_ts', 'downloaded_at'):
                nm[k] = meta.get(k, nm[k])
            if nm['apk'] is None:                            # the tree API may be refused now; it is the same batch, so the same APK
                nm['apk'], nm['folder'] = meta.get('apk'), meta.get('folder')
        gg.write_meta(meta_path, nm)
        _PM_NOTE[0] = 'pokeminers %s adopted = upstream latest' % _pm_ident(nm)
        print('pokeminers: the installed file IS upstream batch %s -- stamped %s' % (_pm_ident(nm), os.path.basename(meta_path)))
        return None, owed
    # CLEAR or FLIPS: install with a dated, never-overwritten backup
    apk, folder = gg.lookup_apk(up_ts, fetch)
    nm = gg.new_meta(up_ts, res['new']['sha256'], apk, folder, now, tail_pending=True)
    bak = gg.next_backup_path(gm_path)
    try:
        shutil.copy2(gm_path, bak)
        if os.path.exists(meta_path):
            shutil.copy2(meta_path, meta_path + '.bak-' + os.path.basename(bak).split('.bak-', 1)[1])
    except OSError as e:
        _drop()
        print('WARN pokeminers: NOT installed -- the backup could not be written (%s); the installed file stays' % e)
        return 1, tail
    if v == 'FLIPS':
        ok, lines = _pm_stop(gg, res, res['reason'], bak, meta, nm)
        if not ok:
            _drop()
            print('WARN pokeminers: NOT installed -- the review record could not be written; the installed file stays')
            return 1, tail
    try:
        if gg.sha256_file(tmp) != res['new']['sha256']:      # a second refresh may have rewritten the download since it was judged
            raise OSError('the downloaded candidate changed after it was judged (a second refresh running?)')
        os.replace(tmp, gm_path)                             # atomic; the previous file is the backup above
    except OSError as e:
        _drop()
        if v == 'FLIPS':
            _clear_review()
        print('WARN pokeminers: NOT installed -- %s (the installed file stays)' % e)
        return 1, tail
    if not gg.write_meta(meta_path, nm):
        print('WARN pokeminers: installed, but %s could not be written -- the next run re-adopts it' % os.path.basename(meta_path))
    print('pokeminers: installed batch %s; previous file kept as %s' % (_pm_ident(nm), os.path.basename(bak)))
    _PM_NOTE[0] = 'pokeminers installed %s, %s' % (_pm_ident(nm), 'verdicts unchanged' if v == 'CLEAR' else 'REVIEW PENDING')
    if v == 'FLIPS':
        for l in lines[:40]:
            print('   ' + l)
        print('   rows: %s -- after review: python system/scripts/refresh_gamemaster.py --ack' % os.path.relpath(REVIEW, ROOT))
        print('pokeminers: %s -- REFRESH APPLIED BUT NEEDS A HUMAN (exit 2)' % res['reason'])
        return 2, True
    print('pokeminers: no in-bag keep verdict moves -- installed without a stop')
    return None, True


def _pm_tail_done():
    """The reconcile + rank pass an installed client game master owed has run (both exits below it stop or clear)."""
    try:
        import gm_guard as gg
        gg.clear_tail_pending(PM_META)
    except Exception:
        pass
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


FLAGS = ('--check-only', '--force', '--ack', '--selftest')


def main(argv):
    bad = [a for a in argv if a not in FLAGS]
    if bad:     # an unknown flag -- even --help -- must never fall through to a real download + install (full_audit.py's rule)
        print('flags: %s\nunknown: %s -- NOTHING was run' % (' '.join(FLAGS), ' '.join(bad)))
        return 2
    if '--selftest' in argv:                   # offline, synthetic fixtures, temp dir only -- BEFORE anything reads or downloads
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        import gm_guard
        return gm_guard.selftest(sys.modules[__name__])
    age = age_days(GM)
    print('pvpoke_gamemaster.json age: %.1f days (limit %d)' % (age, MAX_AGE_DAYS))
    if '--check-only' in argv:
        return 3 if age > MAX_AGE_DAYS else 0
    _gate = review_gate(argv)                  # a pending review stops EVERY run until --ack, whatever the file's age
    if _gate is not None:
        return _gate
    try:
        _pm_rc, _pm_tail = pokeminers_phase(argv)   # the CLIENT game master, on EVERY run and not the 30-day clock (2026-09-30)
    except Exception as _e:                    # the guard itself broke: it installs only as its LAST step, so the old file stands
        print('WARN pokeminers: the client game master check CRASHED (%s: %s) -- nothing was installed by it; fix '
              'gm_guard.py' % (type(_e).__name__, _e))
        return 1
    if _pm_rc:
        return _pm_rc
    if age <= MAX_AGE_DAYS and '--force' not in argv and not _pm_tail:
        print('fresh enough (pvpoke %.0f d old) | %s' % (age, _PM_NOTE[0]))      # the LAST line: full_audit echoes only this
        return 0
    if _pm_tail:
        print('pokeminers: a new client game master is in -- refreshing pvpoke too, so reconcile + ranks judge them together')
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
    _pm_tail_done()                            # the reconcile + rank pass a client-GM install owed has now run

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
    print('REFRESH OK -- no keep decision moved. | %s' % _PM_NOTE[0])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

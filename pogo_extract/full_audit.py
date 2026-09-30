"""ONE-COMMAND full audit: recrawl -> the audits IN PARALLEL -> hard gate -> sync -> verify.

    python full_audit.py              # full cycle
    python full_audit.py --no-sync    # audit only (read-only, never touches the phone's tags)
    python full_audit.py --skip-crawl # audit the CURRENT db (no recrawl)

Why this exists (user 2026-08-29 "There has to be a faster way"): the cycle used to be 5+ separate
round-trips with the audits run one after another. They are READ-ONLY sqlite scripts that share
nothing, so they run concurrently here; only the phone-bound steps (recrawl / sync / verify) stay
serial, because Frida is a single-attach resource and two attaches collide.

HARD GATE: the Transfer pile is the ONE irreversible output. If ANY audit fails, the sync does NOT run.
"""
import json, os, subprocess, sys, time, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__)); os.chdir(ROOT)
API = 'http://127.0.0.1:%d' % int(os.environ.get('DASH_PORT') or 8765)   # moves off a foreign listener, see ensure_dashboard
PY = sys.executable
t0 = time.time()
def el(): return '%5.1fs' % (time.time() - t0)
def say(s): print('[%s] %s' % (el(), s), flush=True)

def api(path, method='GET', body=None, timeout=30):
    req = urllib.request.Request(API + path, method=method,
                                 data=(json.dumps(body).encode() if body is not None else None),
                                 headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def _port_open(timeout=0.25):
    """Raw TCP probe of the dashboard port. A closed port is refused at once here, while an HTTP request to it costs
    ~2 s on Windows (the refused connect is retried) -- half of every cull's 4 s 'dashboard started'."""
    import socket
    try:
        socket.create_connection(('127.0.0.1', int(API.rsplit(':', 1)[1])), timeout=timeout).close()
        return True
    except OSError:
        return False

_DASH = {'proc': None}          # the dashboard THIS run started (None = it was already up, or never started)


def finish_step(rc):
    """THE LAST MILE, IN THE SAME COMMAND (2026-09-29, workflow review): after a full pass the two pages
    (gen_artifacts.py, gen_bag_pulse.py) were regenerated and the dashboard stopped by hand, three separate steps
    every cull. Now: pages on a clean pass (fail-soft, never the cull's rc), then the dashboard this run started is
    stopped on EVERY exit path -- pass, gate failure or crash -- unless --keep-dashboard. Publishing Bag Pulse stays
    a human/assistant step (it needs the artifact tool)."""
    argv = sys.argv[1:]
    if rc == 0 and '--audits-only' not in argv and '--no-sync' not in argv and '--no-pages' not in argv:
        for sc in ('gen_artifacts.py', 'gen_bag_pulse.py'):
            try:
                _p = subprocess.run([PY, sc], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
                _last = [l for l in (_p.stdout or '').splitlines() if l.strip()]
                say('%s: %s' % (sc[:-3], (_last[-1][:150] if _last else 'rc=%d' % _p.returncode) if _p.returncode == 0
                                else 'rc=%d %s' % (_p.returncode, ((_p.stderr or '').strip().splitlines() or ['?'])[-1][:150])))
            except Exception as _e:
                say('%s: skipped (%s)' % (sc[:-3], _e))
    if _DASH['proc'] is not None and '--keep-dashboard' not in argv:
        try:
            _DASH['proc'].terminate()
            say('dashboard stopped (started by this run)')
        except Exception as _e:
            say('dashboard: could not stop it (%s)' % _e)


def ensure_dashboard():
    global API
    if _port_open():
        try:
            api('/api/health', timeout=6); return 'up'
        except Exception:
            # SOMETHING ELSE HOLDS THE PORT (2026-09-26: another Claude session's `python -m http.server 8765` answered 404
            # on 127.0.0.1 and the cull died on "dashboard would not start"). Never fight it: take the next free port and
            # hand it to dashboard.py through DASH_PORT (it reads that already).
            base = int(API.rsplit(':', 1)[1])
            for p in range(base + 1, base + 11):
                API = 'http://127.0.0.1:%d' % p
                if not _port_open():
                    os.environ['DASH_PORT'] = str(p)
                    break
                try:
                    api('/api/health', timeout=3); return 'up on %d' % p     # our own dashboard, moved here earlier
                except Exception:
                    continue
            else:
                raise RuntimeError('ports %d-%d are all taken by something that is not the dashboard' % (base, base + 10))
    _DASH['proc'] = subprocess.Popen([PY, 'dashboard.py'], stdout=open('dashboard_run.log', 'w'), stderr=subprocess.STDOUT)
    deadline = time.time() + 60          # the CLOCK bounds the wait (the old loop was 15 x (2 s + ~2 s refusal) ~ 60 s)
    while time.time() < deadline:
        time.sleep(0.25)
        if not _port_open():
            continue
        try:
            api('/api/health', timeout=5); return 'started'
        except Exception:
            pass
    raise RuntimeError('dashboard would not start within 60 s')

def run_job(path, body=None, label=''):
    """POST a dashboard job and poll to completion. Returns (rc, log)."""
    api(path, 'POST', body if body is not None else {})
    while True:
        time.sleep(0.25)             # was 1 s: a finished job was noticed ~0.5 s late on average (speed study 2026-09-24)
        j = api('/api/job', timeout=10)
        if not j.get('running'):
            _log = j.get('log') or ''
            try:      # 2026-09-24: the job log lived only in the dashboard process -- a failed recrawl's last lines were
                #       lost the moment the dashboard was stopped. Keep every job's log on disk, one file per job name.
                open(os.path.join('system', 'analysis', 'last_job_%s.log' % path.strip('/').replace('/', '_')), 'w',
                     encoding='utf-8', errors='replace').write('rc=%s at %s\n%s' % (j.get('rc'), time.strftime('%Y-%m-%d %H:%M:%S'), _log))
            except Exception:
                pass
            return j.get('rc'), _log


# THE JOB LOG'S WARNINGS, IN THE CULL'S OWN OUTPUT (2026-09-29, H06-2). The walk and the sync are built FAIL-SOFT: a
# step that cannot read something keeps the previous file / the prior tag mirror / the old dex, skips the purge, or
# proceeds past a gate error -- and says so with a [WARN] / FAILED / KEEPING / skipped line in its job log. But this
# script printed only "recrawl ok" and the sync's 'apply_changes' / 'All tags in sync' lines, so every one of those
# lines died in a log file nobody opened (the live one on 2026-09-29 held an is_egg [WARN], a [live_graph] rebuild
# notice and keep_policy's "oracle export skipped" -- the last one failing every pass since 2026-09-20). A fail-soft
# step is only safe when someone hears it: echo them, every pass.
import re as _re
_JOB_WARN = _re.compile(
    r'\[WARN\]|\bWARN(?:ING|INGS)?\b|\bERROR\b|FAILED|\bfailed\b|\bthrew\b|COULD NOT|\bcould not\b|NOT written|not written|'
    r'not updated|unreadable|\bunread\b|unavailable|KEEPING|\bkeeping\b|left in place|disagrees|SKIPPED|skipped[:(]|'
    r'skipped \(|STALE|^!|\*\*\*|\[live_graph\]|\bdeferred\b|\bignored\b|IGNORED|account: None|UNREADABLE|NOT VERIFIED|'
    # R-B review: rc-0 fail-soft lines the list missed -- "Remote Trade NOT confirmed", sync_post_tags' "not verified",
    # sync_remote_trade's "partial apply -- the DB mirror was NOT rewritten", keep_policy's [GUARD] holds
    r'NOT confirmed|\bnot verified\b|NOT rewritten|partial apply|\[GUARD\]')
_JOB_WARN_ROUTINE = _re.compile(r'\bskipped \d+ (?:pid0|eggs)\b'      # every walk skips the egg / pid0 entries by design
                                r'|\(warm-up threw, ignored'           # the sacrificial first call of a fresh session
                                r'|^Remote Trade: same \d+ offers')    # the re-verify skip, already in the summary line
_JOB_TICK = _re.compile(r'^\[t\+\s*[\d.]+s\]\s*')                     # pogo_pipeline's timer prefix


def job_warnings(log):
    """Distinct warning lines of a dashboard job log, in order (timer prefix stripped)."""
    out, seen = [], set()
    for l in (log or '').splitlines():
        s = _JOB_TICK.sub('', l.strip()).strip()
        if s and _JOB_WARN.search(s) and not _JOB_WARN_ROUTINE.search(s) and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def echo_job_warnings(name, log, logfile, limit=100):
    """Print a job's warnings (or one line saying there were none -- silence must not be the only evidence)."""
    w = job_warnings(log)
    if not w:
        say('%s: no warnings in its log' % name)
        return w
    say('%s: %d WARNING line(s) in its log -- a step that kept going past a failure, or a game-state notice; read them before trusting this pass (full log %s):' % (name, len(w), logfile))
    for s in w[:limit]:
        say('  ! %s' % s[:220])
    if len(w) > limit:
        say('  ... %d more in %s' % (len(w) - limit, logfile))
    return w


def state():
    """Bag/pile counters for the progress line. Storage cap is best-effort.

    The cap read used to be a bare json.load(...)['max_pokemon_storage']. player_state.json is written
    by read_player_state.py, so it is absent on a fresh checkout and stale-or-missing whenever that
    step failed -- and a KeyError/FileNotFoundError here aborted the whole run with a traceback instead
    of a diagnosis. It aborts BEFORE run_audits and before any sync, so it was fail-closed and never
    unsafe; it was just unreadable. autocull_watch.py already degrades gracefully on the same file.
    NEVER hardcode a fallback capacity: a hardcoded 11150 was wrong by ~2x (real value 5700)."""
    import sqlite3
    con = sqlite3.connect('pokemon.db')
    try:
        q = lambda s: con.execute(s).fetchone()[0]
        try:
            cap = json.load(open('player_state.json'))['max_pokemon_storage']
        except Exception as e:
            cap = None
            say('capacity UNKNOWN (player_state.json: %s) -- run read_player_state.py' % e)
        # THIS WALK'S CAP, OR SAY WHOSE (2026-09-29, H06-6). The walk's cap read is fail-soft: on any error it keeps the
        # PREVIOUS player_state.json, which carries no timestamp -- so this line printed an old cap and a free count off by
        # every storage upgrade since, as this pass's (the cull skill quotes it: "Bag and free-slot counts come only from
        # this pass's walk"). Same freshness rule as the engine's candy / item budget (evolvable_forms._walk_fresh).
        cap_old = None
        if cap is not None:
            try:
                import evolvable_forms as _efx
                _wk = q('SELECT MAX(last_scanned) FROM pokemon WHERE in_bag=1')
                if _wk and not _efx._walk_fresh('player_state.json', 7200, _wk):
                    cap_old = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime('player_state.json')))
            except Exception as e:
                cap_old = 'unknown age (%s)' % e
        try:
            pile = len(open('system/analysis/tagsets/Transfer.txt').read().split())
        except FileNotFoundError:
            pile = None
        return dict(bag=q('SELECT COUNT(*) FROM pokemon WHERE in_bag=1'), cap=cap,
                    hundos=q('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND iv_total=45'),
                    nundos=q('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND iv_total=0'),
                    pile=pile, cap_old=cap_old)
    finally:
        con.close()

# audit name -> (script, the substring its OWN verdict line must contain when it passes)
def _read_by_walk(read_local, fmt):
    """Was a walk-output file written by the walk being judged? Its own read time (LOCAL, in `fmt`) against pokemon.db
    MAX(last_scanned), which the walk stamps BEFORE every in-walk read step. False = that fail-soft step left the
    PREVIOUS file in place; None = cannot tell. (2026-09-29, H04: 'read this pass' meant 'written under 45 min ago',
    so a failed read right after another pass was reported as this pass's, and the enum news of the previous scan was
    re-announced as this scan's.)"""
    try:
        import sqlite3 as _sq
        _c = _sq.connect('file:pokemon.db?mode=ro', uri=True)
        try:
            _ws = _c.execute('SELECT MAX(last_scanned) FROM pokemon WHERE in_bag=1').fetchone()[0]
        finally:
            _c.close()
        if not _ws or not read_local:
            return None
        _r = time.mktime(time.strptime(str(read_local)[:19], fmt))
        _w = time.mktime(time.strptime(str(_ws)[:19], '%Y-%m-%dT%H:%M:%S'))
        return _w - 5 <= _r <= _w + 900     # R-B review: a file much NEWER than the walk is another walk's / trainer's
    except Exception:
        return None


def game_news_step():
    """What the game added since the last scan, and whether the game itself updated (2026-09-23, user: "you're
    always falling behind on that"). Reads the recrawl's enum summary + the installed version. Never fails a cull."""
    _enum_fresh = None
    try:
        _p = os.path.join('system', 'analysis', 'enum_refresh.json')
        _s = json.load(open(_p, encoding='utf-8')) if os.path.exists(_p) else {}
        _lbl = {'Form': 'form', 'Costume': 'costume', 'LocationCard': 'card/background', 'HoloPokemonMove': 'move'}
        _bits, _bad = [], []
        for _k, _v in (_s.get('enums') or {}).items():
            if _v.get('status') != 'ok':
                _bad.append('%s %s' % (_lbl.get(_k, _k), _v.get('status')))
            elif _v.get('new'):
                _n = list(_v['new'].values())
                _bits.append('%d %s%s (%s%s)' % (len(_n), _lbl.get(_k, _k), '' if len(_n) == 1 else 's',
                                                 ', '.join(_n[:6]), ', ...' if len(_n) > 6 else ''))
        _enum_fresh = _read_by_walk(_s.get('ts'), '%Y-%m-%dT%H:%M:%S')
        if _enum_fresh is not True:     # False = the previous walk's summary; None = no summary / no ts (R-B review)
            say('new in the game: NOT CHECKED this scan -- %s' % (
                ("the in-walk enum refresh wrote no summary (the last one is from %s; its news and problems are not this "
                 "scan's)" % _s.get('ts')) if _enum_fresh is False else
                'no enum summary tied to this walk (%s)' % (_s.get('ts') or ('enum_refresh.json missing' if not _s else 'no ts'))))
        else:
            say('new in the game: %s' % ('; '.join(_bits) if _bits else 'no new forms, costumes, cards or moves'))
            if _bad:
                say('  enum refresh problems: %s' % '; '.join(_bad))
    except Exception as _e:
        say('new in the game: not checked (%s)' % _e)
    try:
        import pogo_il2cpp as _pg
        _o = subprocess.run(['adb', '-s', _pg.ADB_TARGET, 'shell', 'dumpsys package com.nianticlabs.pokemongo'],
                            capture_output=True, text=True, timeout=30).stdout
        _v = next((l.split('=', 1)[1].strip() for l in _o.splitlines() if 'versionName=' in l), None)
        _vp = os.path.join('system', 'analysis', 'game_version.json')
        _pdoc = json.load(open(_vp, encoding='utf-8')) if os.path.exists(_vp) else {}
        _prev = _pdoc.get('version')
        # Pokemod too (2026-09-24): the +178 XXL bonus and the on-screen showcase formula come from ITS agent, so an
        # update means size_line.showcase_points must be re-matched against a screen before an XXL change is trusted
        _o2 = subprocess.run(['adb', '-s', _pg.ADB_TARGET, 'shell', 'dumpsys package com.pokemod.app.public'],
                             capture_output=True, text=True, timeout=30).stdout
        _pm = next((l.split('=', 1)[1].strip() for l in _o2.splitlines() if 'versionName=' in l), None)
        if _v:
            if _prev and _prev != _v:
                say('GAME UPDATED %s -> %s: forms/costumes/cards/moves %s; offsets and the Pokemod map may need a check'
                    % (_prev, _v, 'were re-read this scan' if _enum_fresh is True else
                       'were NOT re-read this scan (no enum summary from this walk) -- recrawl before trusting new-form handling'))
            if _pm and _pdoc.get('pokemod') and _pdoc.get('pokemod') != _pm:
                say('POKEMOD UPDATED %s -> %s: re-verify size_line.showcase_points against a Pokemod screen before trusting '
                    'any XXL top-2 change (its showcaseScoreMath is where the +178 XXL bonus comes from)' % (_pdoc.get('pokemod'), _pm))
            json.dump({'version': _v, 'pokemod': _pm or _pdoc.get('pokemod'), 'seen': time.strftime('%Y-%m-%d %H:%M')},
                      open(_vp, 'w', encoding='utf-8'))
    except Exception as _e:
        say('game version: not read (%s)' % _e)


def walk_freshness_step():
    """THE WALK TRIPWIRES' VERDICT, EVERY PASS (H03, 2026-09-29). A frozen walk is complete and full-size, so the
    'rescanned N/N' line, the 11 audits and the sync's reconcile all agree with it -- the 05:06 / 05:09 / 05:11 passes
    printed "recrawl ok", 5661/5661 rescanned, ALL AUDITS PASS, "All tags in sync" and "VERIFY OK" over a graph the game
    had abandoned at 04:59:53. Two lines that do NOT re-read the walked objects:
      1. the pipeline's fingerprint verdict for this walk (walk_tripwires.check_graph / check_inventory): the inventory
         timestamp against the phone clock and the last pass, the lifetime counters, the catcher's own counter;
      2. the snapshot proof: a walk that missed catches a LATER walk shows already existed read a frozen bag -- it names
         every such pass (and so every "tagged / in sync / verified" line that was about stale objects). Offline, ~1 s.
    A STOP never reaches here (the recrawl exits 8). Never fails the cull on its own."""
    try:
        sys.path.insert(0, os.getcwd())
        import walk_tripwires as _wt
    except Exception as _e:
        say('walk freshness: NOT CHECKED (walk_tripwires unavailable: %s)' % _e)
        return
    try:
        import sqlite3 as _sq
        _c = _sq.connect('file:pokemon.db?mode=ro', uri=True)
        _walk = _c.execute("SELECT MAX(last_scanned) FROM pokemon WHERE in_bag=1").fetchone()[0]
        _c.close()
        fp = next((f for f in reversed(_wt.history()) if f.get('walk_iso') == _walk), None)
        if not fp:
            say('walk freshness: NOT RECORDED for the walk of %s -- nothing proves this walk read a live graph' % _walk)
        else:
            g = fp.get('graph') or {}
            age = (fp['phone_now_ms'] - g['ts']) / 1000.0 if fp.get('phone_now_ms') and g.get('ts') else None
            say('walk freshness: %s -- the inventory it read was updated %s before the walk; %s fresh catch(es) since the '
                'last pass%s' % (fp.get('verdict'), ('%.0f s' % age) if age is not None else '?',
                                 (fp.get('walk') or {}).get('new_since_prev'),
                                 ('; the game holds %d service graphs' % g['bags']) if (g.get('bags') or 0) > 1 else ''))
            for lv, code, msg in fp.get('findings') or []:
                if lv != 'INFO':
                    say('  ! %s: %s' % (code, msg))
    except Exception as _e:
        say('walk freshness: not checked (%s)' % _e)
    try:
        _seen_p = os.path.join('system', 'analysis', 'retro_frozen_seen.json')
        try:
            _seen = set(json.load(open(_seen_p, encoding='utf-8')))
        except Exception:
            _seen = set()
        found = _wt.retro_frozen(last_n=12)
        new = [f for f in found if f[0] not in _seen]
        for l in _wt.retro_lines(new):
            say('!! ' + l)
        say('frozen-walk proof (last 12 walks): %s' % (
            '%d NEW frozen walk(s) above' % len(new) if new else
            ('no new frozen walk (%d already reported)' % len(found)) if found else 'every walk saw every catch made before it'))
        json.dump(sorted(_seen | {f[0] for f in found}), open(_seen_p, 'w', encoding='utf-8'))
    except Exception as _e:
        say('frozen-walk proof: not run (%s)' % _e)


def showcase_change_step():
    """Did the showcase top-2 change since the previous pass? (user 2026-09-23: "needs to be check if anything
    changed"). Showcase.txt is rebuilt by every recrawl; this diffs it against the copy from the previous pass."""
    try:
        _cur_p = os.path.join('system', 'analysis', 'tagsets', 'XXL.txt')
        _prev_p = os.path.join('system', 'analysis', '_showcase_prev.txt')
        _cur = set(open(_cur_p).read().split()) if os.path.exists(_cur_p) else set()
        _prev = set(open(_prev_p).read().split()) if os.path.exists(_prev_p) else None
        if _prev is None:
            say('XXL showcase top-2: %d entries recorded (changes are reported from the next pass on)' % len(_cur))
        elif _cur == _prev:
            say('XXL showcase top-2: unchanged (%d entries)' % len(_cur))
        else:
            import sqlite3 as _sq
            _c = _sq.connect('file:pokemon.db?mode=ro', uri=True)
            def _nm(u):
                _r = _c.execute('SELECT species_name, iv_total, in_bag FROM pokemon WHERE uid_hex=?', (u,)).fetchone()
                return '%s %d%%%s' % (_r[0], round((_r[1] or 0) * 100 / 45), '' if _r[2] else ' (gone)') if _r else u[:8]
            _in = [_nm(u) for u in sorted(_cur - _prev)]
            _out = [_nm(u) for u in sorted(_prev - _cur)]
            _c.close()
            say('XXL showcase top-2 CHANGED: +%d (%s) -%d (%s)' % (len(_in), ', '.join(_in[:8]) + (' ...' if len(_in) > 8 else ''),
                                                              len(_out), ', '.join(_out[:8]) + (' ...' if len(_out) > 8 else '')))
        open(_prev_p, 'w').write('\n'.join(sorted(_cur)))
    except Exception as _e:
        say('showcase top-2: not checked (%s)' % _e)


def showcase_formula_step():
    """#5 EVERY PASS (user 2026-09-24: "5 should be done everytime"). The recrawl re-read the showcase formula's inputs
    from the GAME (showcase_gm_live.json: CONTEST_SETTINGS coefficients + flags, every bag stage's size bounds and
    pokedex numbers) and size_line now scores by them. This step says so in one line, and STOPS the pass (rc 7, before
    audits/sync) when the game's coefficients differ from what the engine assumes, the xxl adjustment is not the 1.0
    the flat +178 was matched under, or the CONTEST_SETTINGS shape (fields, flags, formula rows) changed since the
    previous pass -- every XXL winner would have to be re-ranked under a formula nobody has verified on a screen.
    Size-bound disagreements with the monthly file never stop anything: the live value wins and the XXL top-2 diff
    above shows the effect. A missing / stale live read is announced, never silently scored around."""
    try:
        sys.path.insert(0, os.getcwd())
        import size_line as _sl, keep_config as _kc, sqlite3 as _sq
        _p = os.path.join('system', 'analysis', 'showcase_gm_live.json')
        if not os.path.exists(_p):
            say('showcase formula: NO LIVE READ YET -- scoring from gamemaster_pokeminers.json (monthly dump); the recrawl step '
                'read_showcase_gm should write showcase_gm_live.json')
            return 0
        d = json.load(open(_p, encoding='utf-8'))
        _age = (time.time() - time.mktime(time.strptime(d['generated'], '%Y-%m-%d %H:%M:%S'))) / 60.0
        _this = _read_by_walk(d.get('generated'), '%Y-%m-%d %H:%M:%S')    # THE WALK decides "this pass", not 45 min (H04)
        _when = ('read this pass' if _this else
                 ('NOT READ THIS WALK -- the in-walk read failed; scored and compared on the read of %s (%.0f min ago)'
                  % (d['generated'], _age)) if _this is False else ('read %s, %.0f min ago' % (d['generated'], _age)))
        _ct = d.get('contest') or {}
        c = (_ct.get('coefficients') or [{}])[0]
        w = _kc.showcase_weights()
        want = (round(w['height'] * 1000), round(w['weight'] * 1000), round(w['iv'] * 1000))
        got = tuple(c.get(k) for k in ('heightCoefficient', 'weightCoefficient', 'ivCoefficient'))
        xadj = c.get('xxlAdjustmentFactor')
        shape = {'fields': _ct.get('fields'), 'scalars': _ct.get('scalars'), 'formulas': _ct.get('contestScoreFormulas'),
                 'coefficients': [{k: v for k, v in x.items() if k != 'scalars'} for x in (_ct.get('coefficients') or [])]}
        _pp = os.path.join('system', 'analysis', '_showcase_gm_prev.json')
        prev = json.load(open(_pp, encoding='utf-8')) if os.path.exists(_pp) else None
        changed = []
        if any(g is None for g in got) or tuple(round(g) for g in got) != want:
            changed.append('coefficients: game %s vs engine %s' % (got, want))
        if xadj is not None and abs(xadj - 1.0) > 1e-9:
            changed.append('xxlAdjustmentFactor %s (the flat +%d XXL bonus was matched on screen under 1.0)' % (xadj, w['xxl_bonus']))
        if prev is not None:
            for k in ('fields', 'scalars', 'formulas', 'coefficients'):
                if prev.get(k) != shape.get(k):
                    changed.append('CONTEST_SETTINGS %s changed: %s -> %s' % (k, json.dumps(prev.get(k))[:160], json.dumps(shape.get(k))[:160]))
        st = _sl.live_status()
        _c = _sq.connect('file:pokemon.db?mode=ro', uri=True); _c.row_factory = _sq.Row
        _xxl = [r for r in _c.execute('SELECT * FROM pokemon WHERE in_bag=1 AND pokemon_size_category=5')]
        _c.close()
        _unk = sum(1 for r in _xxl if _sl.showcase_points(r) is None)
        say('showcase formula: game says %s/%s/%s, xxl adj %s -> engine scores %d/%d/%d +%d XXL; live size bounds %s/%s stages%s; '
            '%d XXL mons scored, %d without a template (protected); %s'
            % (got[0], got[1], got[2], xadj, want[0], want[1], want[2], w['xxl_bonus'], d.get('with_size_settings'), d.get('pairs'),
               (' (%d numbers differ from the monthly file -> live wins)' % st['diff_total']) if st.get('diff_total') else ' (all agree with the monthly file)',
               len(_xxl) - _unk, _unk, _when))
        if d.get('errors'):
            say('  live read notes: %s' % json.dumps(d['errors'])[:200])
        if changed:
            say('!! SHOWCASE FORMULA CHANGED IN THE GAME: ' + ' | '.join(changed))
            say('!! stopping before audits/sync -- re-match size_line.showcase_points against a Pokemod screen, then refresh '
                'system/analysis/_showcase_gm_prev.json')
            return 7
        json.dump(shape, open(_pp, 'w', encoding='utf-8'), indent=1)
        return 0
    except Exception as _e:
        say('showcase formula: not checked (%s)' % _e)
        return 0


# ONE FRIDA CLIENT AT A TIME (AutoCatcher session, 2026-09-24): three PoGo deaths today came 54 s - 2.5 min after a cull
# attached while the on-phone catcher was attached to the same gadget. Handshake: write a PHONE-clock deadline to
# CATCHER_PAUSE; the catcher lets go of the gadget (:27047) within ~2 s and stays off until the deadline passes or we
# write 0. The deadline is a dead-man switch -- a cull that dies never leaves the catcher off for more than `secs`.
CATCHER_PAUSE = '/data/local/tmp/pogo_pause'
_catcher_paused = [False]
# OFF since 2026-09-24 ~23:10 (user, via the AutoCatcher session: run the cull and the catcher AT THE SAME TIME). The
# known freeze was JS running inside a stopped GC world while the catcher's JS held Frida's one JS lock; the shared
# liveness walk now runs in C (pogo_il2cpp LV_SRC, verified identical to the JS walk on the phone). Set True to go back
# to pausing the catcher around every phone phase (the handshake code below is kept for that).
CATCHER_PAUSE_ENABLED = False


def catcher_pause(secs=90, wait=True):
    """Arm (or re-arm) the pause before a phone phase; with `wait`, hold until the catcher has detached (max ~10 s)."""
    if not CATCHER_PAUSE_ENABLED:
        return False
    try:
        import pogo_il2cpp as _pg
        subprocess.run(['adb', '-s', _pg.ADB_TARGET, 'shell',
                        "su -c 'echo $(( $(date +%%s) + %d )) > %s'" % (secs, CATCHER_PAUSE)],
                       capture_output=True, text=True, timeout=15)
        _catcher_paused[0] = True
        if not wait:
            return True
        for _ in range(20):
            n = subprocess.run(['adb', '-s', _pg.ADB_TARGET, 'shell', "su -c 'ss -tn | grep -c :27047'"],
                               capture_output=True, text=True, timeout=15).stdout.strip()
            if n == '0':
                return True
            time.sleep(0.5)
        say('catcher pause: the catcher still holds the gadget after 10 s -- going ahead')
    except Exception as _e:
        say('catcher pause: skipped (%s)' % _e)
    return False


def catcher_resume():
    """Hand the gadget back (write 0). Silent no-op when this run never paused it."""
    if not _catcher_paused[0]:
        return
    try:
        import pogo_il2cpp as _pg
        subprocess.run(['adb', '-s', _pg.ADB_TARGET, 'shell', "su -c 'echo 0 > %s'" % CATCHER_PAUSE],
                       capture_output=True, text=True, timeout=15)
        _catcher_paused[0] = False
    except Exception as _e:
        say('catcher resume failed (%s) -- its deadline releases it anyway' % _e)


def report_step(verify_failed=False):
    """THE REPORT (user 2026-09-24: "Why does it take you so long to make the report? it shouldnt..."): what improved,
    why each pile mon is there, the safety check and which way to evolve -- written by cull_report.py from this pass's
    own files, printed verbatim after '=== REPORT ==='. Never fails the cull.
    verify_failed (R-B review): the report's lead line reads only the sync log, whose prune verify had passed -- after
    VERIFY *** FAILED *** it still said "Release the N ... (the game read back N ...)". CULL_VERIFY=FAILED stops that."""
    try:
        _env = dict(os.environ)
        _env.pop('CULL_VERIFY', None)
        if verify_failed:
            _env['CULL_VERIFY'] = 'FAILED'
        _p = subprocess.run([PY, 'cull_report.py'], capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=300, env=_env)
        print('=== REPORT ===')
        print('\n'.join(l for l in (_p.stdout or '').splitlines() if not l.startswith('[adventure_effect]')), flush=True)
        if _p.returncode:
            _err = [l for l in (_p.stderr or '').splitlines() if l.strip()]
            say('report: rc=%d %s' % (_p.returncode, (_err[-1] if _err else '')[:200]))
    except Exception as _e:
        say('report: skipped (%s)' % _e)


def post_tags_run(extra=()):
    """sync_post_tags.py [extra] -> (CompletedProcess, {section: lines}), its job log saved. extra=('--reconcile',
    '--retire') (2026-09-30, cull speed pick 2): the post-push reconcile report and retire ride the same session as
    Remote Trade and the tag order -- one attach instead of three. Raises only on a failure to run the process."""
    try:
        _p = subprocess.run([PY, 'sync_post_tags.py'] + list(extra), capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=900)
    except subprocess.TimeoutExpired as _t:
        _o = _t.stdout.decode('utf-8', 'replace') if isinstance(_t.stdout, bytes) else (_t.stdout or '')
        _te = _t.stderr.decode('utf-8', 'replace') if isinstance(_t.stderr, bytes) else (_t.stderr or '')
        _p = subprocess.CompletedProcess(_t.cmd, -9, _o + '\nREMOTE TRADE / EVOLVE FOR SIZE TIMED OUT after 900 s -- '
                                         'a push above may already have landed\n', _te)
    sec, cur = {'RECONCILE': [], 'RETIRE': [], 'REMOTE TRADE': [], 'TAG ORDER': []}, None
    for _l in (_p.stdout or '').splitlines():
        _m = _l.strip()
        if _m.startswith('=== ') and _m.endswith(' ===') and _m[4:-4] in sec:
            cur = _m[4:-4]
            continue
        if cur:
            sec[cur].append(_l)
    # H06-2 FOR THE LABEL STEP TOO (2026-09-29): sync_remote_trade / order_tags print their fail-soft lines under the
    # section markers ("game refusal list unreadable -- pushing unfiltered", "sweep skipped", "! EditTag failed")
    # and only the summary lines were echoed. Saved like a job log, then echoed (post_tags_say).
    # stdout AND stderr (R-B review): tag_ops logs through logging.basicConfig() -> stderr, so its "change(s) NOT
    # written" / "FAILED after 3 retries" never reached the scan, which then said "no warnings in its log"
    _plog = (_p.stdout or '') + (('\n--- stderr ---\n' + _p.stderr) if (_p.stderr or '').strip() else '')
    try:
        open(os.path.join('system', 'analysis', 'last_job_post_tags.log'), 'w', encoding='utf-8', errors='replace').write(
            'rc=%s at %s\n%s' % (_p.returncode, time.strftime('%Y-%m-%d %H:%M:%S'), _plog))
    except OSError as _we:
        say('remote trade / tag order: log not saved (%s)' % _we)
    return _p, sec


def post_tags_say(_p, sec):
    """Remote Trade + the tag order ran in ONE gated Frida session (sync_post_tags.py, speed study 2026-09-24): one
    attach, one write gate, one bag/svc pick; each tag still runs its own unchanged sync() -- fresh walk, read, push,
    verify. This prints what that step always printed: its two summary lines, the warnings scan of its saved log, and
    an rc line when it crashed after a push. Never fails the cull -- these are labels, not the pile."""
    try:
        _to = [l for l in (_p.stdout or '').splitlines() if 'TIMED OUT' in l]
        _rt = [l for l in (_p.stdout or '').splitlines() if l.startswith('Remote Trade: same')] + \
              [l for l in sec['REMOTE TRADE'] if l.startswith(('Remote Trade', 'apply_changes', 'already up to date', 'REMOTE TRADE'))][-2:] + _to
        _es = []
        say('remote trade: %s' % (' | '.join(_rt) if _rt else 'no output'))
        _or = [l for l in sec['TAG ORDER'] if l.startswith('TAG ORDER')]
        if _or:
            say('tag order: %s' % ' | '.join(l[len('TAG ORDER '):] for l in _or))
        _pl = os.path.join('system', 'analysis', 'last_job_post_tags.log')
        _plog = (_p.stdout or '') + (('\n--- stderr ---\n' + _p.stderr) if (_p.stderr or '').strip() else '')
        echo_job_warnings('post-push session (reconcile / retire / remote trade / tag order)'
                          if (sec.get('RECONCILE') or sec.get('RETIRE')) else 'remote trade / tag order', _plog, _pl)
        # A CRASH AFTER A PUSH MUST NOT READ LIKE A CLEAN PUSH (2026-09-23) -- same rc line the old steps printed.
        if _p.returncode and not any(' rc=' in l or 'TIMED OUT' in l or ' stopped' in l or ' failed' in l or ' skipped' in l
                                     or 'read-back' in l for l in _rt + _es + _or):
            _err = [l for l in (_p.stderr or '').splitlines() if l.strip()]
            say('remote trade / evolve for size: rc=%d -- %s' % (_p.returncode, (_err[-1] if _err else 'no stderr')[:200]))
    except Exception as _e:
        say('remote trade / evolve for size: skipped (%s)' % _e)


# SERVER PROOF ONLY WHEN THERE IS SOMETHING TO PROVE (speed study #6, user 2026-09-24: "ok fine"). When the phone is
# idle, verify_tags_live force-restarts PoGo to prove the tags persisted on the server (~110 s). A sync that wrote NO
# tag has nothing new to prove -- BUT a write made while he was playing had its proof DEFERRED to the next idle pass,
# so the restart is skipped only when this sync wrote nothing AND no earlier write is still waiting for its proof.
# The pending marker is set by any sync that writes, and cleared only by a verify that did the genuine server refetch.
PROOF_PENDING = os.path.join('system', 'analysis', 'server_proof_pending.json')

def _sync_changed_tags(log):
    """True when this sync wrote any tag: a nonzero per-tag delta ('-> remove N, add M'), prune's atomic apply line,
    or a tag it had to create. A log it cannot read -> True, so the restart proof runs exactly as before."""
    import re
    d = re.findall(r'-> remove (\d+), add (\d+)', log)
    if not d:
        return True
    return any(int(a) or int(b) for a, b in d) or '[atomic] applied' in log or 'NOT on server -> creating it' in log

def _proof_pending(changed):
    """Record a write that still needs its server proof; True while one is outstanding."""
    if changed and not os.path.exists(PROOF_PENDING):
        json.dump({'since': time.strftime('%Y-%m-%d %H:%M:%S')}, open(PROOF_PENDING, 'w'))
    return os.path.exists(PROOF_PENDING)


def _server_batches(log):
    """(confirmed, batches) summed over the sync log's 'SERVER: a/b batch(es) Success, r refused, n no answer' lines
    (prune_tags, H02-2 2026-09-29), or None when no write reported a server answer."""
    import re as _re2
    got = [tuple(int(x) for x in m) for m in _re2.findall(
        r'SERVER: (\d+)/(\d+) batch\(es\) Success, (\d+) refused, (\d+) no answer', log or '')]
    if not got:
        return None
    return sum(g[0] for g in got), sum(g[1] for g in got)


def _unproven_note(log=None):
    """NO SERVER PROOF RUNS ANY MORE (2026-09-29, H06-4). verify_tags_live.py is cache-only for good (user rule 2026-09-25:
    "the cull should never restart the game. ever." -- restart_pogo raises), so the marker above can never clear and the
    old "server proof deferred" promised a check that never comes. Every VERIFY line now says what it did check (the
    client tag cache) and since when the writes are unproven on the server."""
    _sb = _server_batches(log)
    if _sb and _sb[0] == _sb[1]:
        return 'the SERVER answered Success for every tag write this pass (%d batch(es))' % _sb[1]
    try:
        since = json.load(open(PROOF_PENDING, encoding='utf-8')).get('since')
    except (OSError, ValueError, AttributeError):
        since = None
    if _sb:
        return ('the SERVER confirmed only %d of %d batch(es) this pass -- see the SERVER line in the sync log'
                % _sb)
    return ('NOT server proof -- the cull never restarts PoGo, so no pass proves the writes reached the server'
            + ((' (unproven since %s)' % since) if since else ''))

def ladder_start():
    """Start the ladder report IN THE BACKGROUND right after the sync (speed study 2026-09-24): it makes no phone calls
    and reads only what the sync has already finalised (pokemon.db, policy_reasons.json, the tagsets, this pass's
    before_sync snapshot) -- nothing the Remote Trade / Evolve for Size steps write -- so it overlaps their ~30 s of
    phone time instead of adding its own ~2-6 s at the end. ladder_finish() prints its lines exactly as before."""
    try:
        # UTF-8 both ways (H05-12): ladder_report writes UTF-8, and text=True alone decoded it as cp1252 here ("Flabébé" ->
        # "FlabÃ©bÃ©" in the cull output) -- the same encoding report_step already passes for cull_report
        return subprocess.Popen([PY, 'ladder_report.py'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding='utf-8', errors='replace')
    except Exception as _e:
        say('ladder report: could not start (%s)' % _e)
        return None

def ladder_finish(p):
    if p is None:
        return
    try:
        _out, _err = p.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        p.kill()
        say('ladder report: timed out after 300 s')
        return
    # EVERY LINE (H05-12, 2026-09-29): [-8:] kept only the tail, so the ladder's own head -- "LADDER ... vs ...", the bag
    # line and "since the HH:MM walk: evolved / released / caught | pile = pushed out + fresh + leftover" (and its
    # frozen-walk alarm) -- never reached the cull output once the ladder grew past 8 lines, while "new trophies" at the
    # bottom did. Same rule as the report: "dont do this. always print it all out." (user 2026-09-26)
    for _l in (_out or _err).strip().splitlines():
        say(_l)
    if p.returncode:
        # A CRASH MUST NOT READ LIKE THE END OF THE REPORT (2026-09-29, H06-9): the rc was never looked at and stderr was
        # dropped whenever stdout had lines, so a ladder_report that died halfway printed its first lines as if done. The
        # history entry is written BEFORE the first print (ladder_report.py), so what a crash loses is the TAIL: BROKEN
        # PROMISES, NOT RELEASED for a day or more, new trophies -- whose absence would read as "none" (R-B review).
        _e = [l for l in (_err or '').splitlines() if l.strip()]
        say('ladder report: rc=%d -- %s -- the ladder above is INCOMPLETE (BROKEN PROMISES / NOT RELEASED / new trophies may '
            'be missing)' % (p.returncode, (_e[-1] if _e else 'no stderr')[:200]))


AUDITS = [('8-layer cull',    'audit_cull.py',            'ALL LAYERS PASS'),
          ('tag membership',  'audit_tags_membership.py', 'ALL TAG MEMBERSHIPS CORRECT'),
          ('evo comb-up',     '_evocheck.py',             'none of the tagged mons would improve'),
          ('law re-derive',   '_lawcheck.py',             'UNEXPLAINED: 0'),
          ('label law',       'audit_labels.py',          'ALL LABELS LAWFUL'),
          ('promises',        'audit_promises.py',        'ALL PROMISES HOLD'),
          ('game master',     'audit_gamemaster.py',      'GAME MASTER CONSISTENT'),
          ('rank tags',       'audit_rank_tags.py',       'EVERY RANK TAG CHECKS OUT'),
          # TAG TRUTH (2026-09-23, user: "most of those pokemon dont have the adventure effect at all ... look at each
          # pokemon that actually has it"). Every audit above re-derives a RULE; this one tests each tag's CLAIM on
          # each member's own live data (its moves, IVs, size, owner, CP) -- it caught 19 Adventure Effect members
          # without the move and 6 Legacy Moves members whose move the game rolls normally now.
          ('tag truth',       'audit_tag_truth.py',       'EVERY TAG IS TRUE'),
          # STRUCTURAL invariants (added 2026-09-02). The four above all check a RESULT -- is this
          # pile keeper-free, does this tag match its rule, can every piled mon be explained. They
          # are re-derivations, so they catch a wrong ANSWER and are structurally blind to a wrong
          # QUESTION: an axis one file caps and another keeps in full, a column read that nothing
          # writes, a stale enum that reclassifies a costume as plain. That is the class that has
          # been surfacing here one bug at a time (costume bucket, XXL, Dynamax, Gigantamax, shiny
          # displacement, Unown, shadow, rarity-skips-shiny; special_bg_id; form_enum). This one
          # asserts the MODEL instead of the membership. Read-only, ~2s, no device contact.
          ('structural inv.', 'audit_invariants.py',       'ALL STRUCTURAL INVARIANTS HOLD'),
          # LOST-KEEPER FIXTURES (added 2026-09-07). The five above all judge the CURRENT bag: this
          # pile, these tags, this law. None of them can speak for a mon that is no longer in the bag
          # -- and the 2026-09-07 forensic audit found 24 that a correct engine would have kept, 18 of
          # them released and unrecoverable (17 from the pre-2026-06-05 IV-magnitude era that also
          # killed the GL#1 Mareep; 1 a Mudbray whose species parsed as "pid749", ranked NULL, and was
          # read as "no PvP protection" instead of "unknown -> protect"). This gate re-inserts those 18
          # real spreads into a SANDBOX copy of the bag, runs the real keep_policy, and demands every
          # one come out KEEP *by a PvP axis* -- measured, not assumed: with the PvP rules removed, 8
          # of the 17 are still kept by an incidental evolve/variant_floor reason, so asserting KEEP
          # alone would false-pass on half of them. Read-only, sandboxed, no device contact, ~4s.
          ('pvp keepers',    'system/scripts/regress_pvp_keepers.py', 'ALL PVP KEEPER FIXTURES KEPT')]

def _pile_members():
    """sha256 of the pile's sorted, normalised uids -- preflight_transfer.pile_members_sha256's exact rule (X3)."""
    import hashlib
    p = os.path.join('system', 'analysis', 'tagsets', 'Transfer.txt')
    uids = open(p).read().split() if os.path.exists(p) else []
    return hashlib.sha256('\n'.join(sorted(format(int(u, 16), 'x') for u in uids)).encode()).hexdigest()

def run_audits():
    """All of them concurrently -- read-only sqlite, no shared state, no phone contact."""
    procs = [(nm, need, subprocess.Popen([PY, sc], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, encoding='utf-8', errors='replace'))
             for nm, sc, need in AUDITS]
    out = []
    for nm, need, p in procs:
        log = p.communicate()[0] or ''
        # BOTH conditions: exit 0 AND the script's own verdict line. Exit code alone has false-passed
        # before (a crashed subprocess printing nothing is not a pass).
        ok = (p.returncode == 0) and (need in log)
        out.append((nm, ok, log))
    return out

def audits_only():
    """Run just the audits IN PARALLEL and exit nonzero if any fails.

    This is the form the dashboard's /api/full_audit job uses: it becomes ONE job step, so the
    existing 'a step with rc!=0 aborts the job' machinery gives the keeper gate for free -- the
    sync steps that follow simply never run."""
    res = run_audits()
    for nm, ok, log in res:
        verdict = ([l for l in log.splitlines() if 'VERDICT' in l or 'UNEXPLAINED' in l] or ['(no verdict line)'])[-1]
        print('%-15s %s  %s' % (nm, 'PASS' if ok else '*** FAIL ***', verdict.strip()[:88]), flush=True)
    bad = [(nm, log) for nm, ok, log in res if not ok]
    for nm, log in bad:
        print('----- %s: failing lines -----' % nm)
        for l in log.splitlines():
            if any(k in l for k in ('FAIL', 'UNEXPLAINED', 'OVERLAP', '***', 'DRIFT')):
                print('   ', l.strip()[:130])
    if bad:
        print('AUDIT GATE FAILED -- the pile is NOT safe to sync (%s)' % ', '.join(nm for nm, _ in bad))
        return 1
    print('ALL %d AUDITS PASS -- pile is keeper-free' % len(AUDITS))
    return 0


XXL_TRIM = {'caps': {'xxl': 1, 'xxl_per_type': 5}, 'showcase_weights': {'min_points': 1050}}   # user: "Actually make the cut off 1050"
_TRIM_BAK = 'keep_config.json.pre_xxl_trim'


def xxl_trim_begin():
    """THE XXL TRIM (user 2026-09-29: "2, but 1,000" / "This is a one time thing, that will be done sometimes when i say,
    not every time"; cut-off "Actually make the cut off 1050"): for THIS run keep only the best 1 XXL per species + the
    best 5 per type, showcase points >= 1,050, so the other XXLs reach the pile. The everyday rule comes back when the run ends."""
    import shutil
    import keep_config
    shutil.copyfile(keep_config.PATH, _TRIM_BAK)
    cfg = json.load(open(keep_config.PATH, encoding='utf-8'))
    for k, v in XXL_TRIM.items():
        cfg.setdefault(k, {}).update(v)
    keep_config.write(cfg)
    open(_TRIM_SHA, 'w').write(_sha_file(keep_config.PATH))   # H10-7: restore only over THIS trimmed file
    say('XXL TRIM on for this run: best 1 XXL per species + best 5 per type, showcase points >= 1,050 (keep_config.json is restored at the end)')


_TRIM_SHA = _TRIM_BAK + '.sha256'          # sha256 of the TRIMMED keep_config.json the backup belongs to (H10-7)


def _sha_file(p):
    import hashlib
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def xxl_trim_end():
    """Restore keep_config.json from the trim's backup (also at the START of every pass: a trim run that was killed
    hard must not leave the trim on). ONLY over the trimmed file the backup was taken against (H10-7, 2026-09-29): a
    leftover backup restored over a keep_config.json edited since would silently revert those edits. False = the two
    disagree: nothing is restored and the pass must not run (the trim might still be on, and XXLs would reach the pile)."""
    if not os.path.exists(_TRIM_BAK):
        return True
    try:
        want = open(_TRIM_SHA).read().strip()
    except OSError:
        want = None
    if want is None or _sha_file('keep_config.json') != want:
        say('!! XXL TRIM backup %s is left over, but keep_config.json is %s -- NOT restored. Compare the two by hand, '
            'keep the right one as keep_config.json and delete %s, then re-run.'
            % (_TRIM_BAK, 'not the trimmed file it was taken against (edited since)' if want else
               'unverifiable (no %s)' % _TRIM_SHA, _TRIM_BAK))
        return False
    os.replace(_TRIM_BAK, 'keep_config.json')
    os.remove(_TRIM_SHA)
    say('XXL TRIM off: keep_config.json restored (everyday XXL rule)')
    return True


FLAGS = ('--audits-only', '--keep-dashboard', '--no-pages', '--no-sync', '--skip-crawl', '--xxl-trim')


def main():
    rc = 1
    bad = [a for a in sys.argv[1:] if a not in FLAGS]
    if bad:     # an unknown flag -- even --help -- must never fall through to a full phone cycle (2026-09-29: it did)
        print(__doc__)
        print('flags: %s\nunknown: %s -- NOTHING was run' % (' '.join(FLAGS), ' '.join(bad)))
        return 2
    _db = os.path.join(ROOT, 'pokemon.db')
    if not os.path.exists(_db) or os.path.getsize(_db) < 1_000_000:
        # a fresh cloud checkout has no data until `pull`; running on nothing would judge (and later push) an empty bag
        print('pokemon.db is missing or empty here -- run `python tools/pogo_data.py pull` from the repo root first. '
              'NOTHING was run.')
        return 2
    if not xxl_trim_end():                     # a killed trim run never leaves the trim on -- or a conflict stops here
        return 9
    if '--xxl-trim' in sys.argv[1:]:
        xxl_trim_begin()
    try:
        rc = _main()
        return rc
    finally:
        catcher_resume()                       # the catcher gets the gadget back on every exit path
        finish_step(rc)                        # pages on a clean pass, then the dashboard this run started goes down
        xxl_trim_end()                         # the trim is one run only


def _main():
    argv = sys.argv[1:]
    if '--audits-only' in argv:
        return audits_only()
    say('dashboard %s' % ensure_dashboard())
    # 2026-09-08 (user: game master "should be checked often, at least once a month"). The refresh
    # script self-skips when the file is under 30 days old, so this is free on normal runs. Exit 2 means
    # a rebalance moved a keep decision across the rank<=5 line -- STOP before anything reaches the
    # phone and let a human look. Exit 1 (download failed) leaves the old file in place and is not fatal.
    _review = os.path.join('system', 'analysis', 'gamemaster_review_pending.json')
    try:
        # UTF-8 (R-B review): the child writes UTF-8 and text=True alone decodes cp1252 here -- a byte cp1252 cannot map
        # kills the reader thread, stdout comes back None and the '+' below raised TypeError
        _gm = subprocess.run([PY, os.path.join('system', 'scripts', 'refresh_gamemaster.py')],
                             capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800)
    except subprocess.TimeoutExpired:
        say('gamemaster: refresh_gamemaster.py TIMED OUT after 1800 s -- a new game master may be installed with its rank '
            'changes never diffed; stopping before recrawl/sync (its review gate stops the next run too)')
        return 5
    _gm_line = ((_gm.stdout or '') + (_gm.stderr or '')).strip().splitlines()
    if _gm.returncode == 2 or os.path.exists(_review):
        # THE ROWS TO REVIEW, NOT ONLY THE LAST LINE (R-B review): "review the CROSSED/NULL rows above" pointed at rows this
        # step never printed, and the crossing run's last line was cut before its --ack command. A refresh that died after
        # installing the new file (rc 1, killed) leaves its pending record behind: that stops the pass as well.
        for _l in _gm_line:
            say('gamemaster: %s' % _l[:220])
        say('GAME MASTER REFRESH STOPPED THE PASS (rc %d) -- a keep decision moved across the rank<=5 line, or the refresh '
            'itself could not finish (the lines above say which). Stopping before recrawl/sync. Review pending: %s; when '
            'reviewed: python system/scripts/refresh_gamemaster.py --ack' % (_gm.returncode, 'YES' if os.path.exists(_review) else 'no'))
        return 5
    say('gamemaster: %s' % (_gm_line[-1][:110] if _gm_line else 'rc=%d' % _gm.returncode))
    _gw = job_warnings('\n'.join(_gm_line))
    if _gw:                                              # e.g. "rankings-1500.json: DOWNLOAD FAILED" above a final "REFRESH OK"
        echo_job_warnings('gamemaster', '\n'.join(_gm_line), '(this run only)')
    if '--skip-crawl' not in argv:
        catcher_pause()                        # one Frida client at a time: the catcher lets go first
        try:
            rc, log = run_job('/api/recrawl')
        finally:
            catcher_resume()                   # the walk is done -- the audits below are offline (AutoCatcher ask, 2026-09-24)
        _rlog = os.path.join('system', 'analysis', 'last_job_api_recrawl.log')
        if rc:
            echo_job_warnings('recrawl', log, _rlog)          # H06-2: what the walk skipped before it died
            print('\n'.join([l for l in log.splitlines() if l.strip()][-10:]))
            if rc == 8:                                       # H03: the walk tripwires stopped it -- not a crash
                say('FROZEN OR IMPOSSIBLE READ (rc 8) -- the walk tripwires stopped the pass before anything was judged; '
                    'nothing was synced and the pile on disk is the last live pass\'s'); return 8
            say('RECRAWL FAILED rc=%s -- aborting' % rc); return 2
        say('recrawl ok')
        echo_job_warnings('recrawl', log, _rlog)              # H06-2: every fail-soft step's WARN, in the cull output
        try:                                   # 2026-09-23: prove every mon was re-read THIS scan
            import sqlite3 as _sq
            _c = _sq.connect('file:pokemon.db?mode=ro', uri=True)
            _t = _c.execute("SELECT MAX(last_scanned) FROM pokemon WHERE in_bag=1").fetchone()[0]
            _n, _all, _loc, _bm, _bv, _cs = _c.execute(
                "SELECT SUM(last_scanned=?), COUNT(*), SUM(lat IS NOT NULL), SUM(bread_moves IS NOT NULL AND bread_moves != '[]'), "
                "SUM(COALESCE(fresh_bonus_atk,0)+COALESCE(fresh_bonus_def,0)+COALESCE(fresh_bonus_sta,0)>0), "
                "SUM(contest_end_ms IS NOT NULL AND contest_end_ms > ?) FROM pokemon WHERE in_bag=1",
                (_t, int(time.time() * 1000))).fetchone()
            _c.close()
            # NOT A TAUTOLOGY ANY MORE (H07 2026-09-29): in_bag=1 is set by the very walk that stamps last_scanned, so N/N
            # could not come out short (5661/5661 on each frozen-graph pass). The game's own count is the independent side.
            try:
                _gm = json.load(open(os.path.join('system', 'analysis', 'bag_count.json'), encoding='utf-8')).get('pokemon_only')
            except Exception:
                _gm = None
            say('rescanned %s/%s mons this scan, the game counts %s (location %s, Max-move levels %s, item-boosted IVs %s, '
                'in a showcase now %s)%s' % (_n, _all, _gm if _gm is not None else '?', _loc, _bm, _bv, _cs,
                                             '' if _gm == _all == _n else
                                             '  *** [WARN] pokemon.db is NOT the bag the game counts -- read the recrawl warnings'))
        except Exception as _e:
            say('rescan coverage: not checked (%s)' % _e)
        walk_freshness_step()                   # H03: the tripwires' verdict + the snapshot proof, every pass
        game_news_step()
        showcase_change_step()
        _rc7 = showcase_formula_step()          # 2026-09-24: #5 every pass -- a changed game formula stops the pass
        if _rc7:
            return _rc7
        # 2026-09-08: the recrawl just re-read the game's Adventure-Effect registry in-walk; turn it into a
        # species roster and refuse to continue if the game names a species nothing protects (exit 2).
        _ae = subprocess.run([PY, os.path.join('system', 'scripts', 'derive_ae_roster.py')],
                             capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
        _ae_line = ((_ae.stdout or '') + (_ae.stderr or '')).strip().splitlines()
        say('adventure effects: %s' % (_ae_line[-1][:110] if _ae_line else 'rc=%d' % _ae.returncode))
        if len(_ae_line) > 1 and job_warnings('\n'.join(_ae_line[:-1])):
            echo_job_warnings('adventure effects', '\n'.join(_ae_line[:-1]), '(this run only)')
        if _ae.returncode == 2:
            say('LIVE ADVENTURE-EFFECT SPECIES WITHOUT PROTECTION -- stopping before audits/sync; add the pid(s) to keep_config')
            return 6
    s = state()
    # THE GAME'S COUNT (user 2026-09-24: "Game shows 5743/5850"): eggs take storage too -- the walk writes them
    # -- the storage screen's number is the game's get_Count = Pokemon + eggs in incubators (the walk reads it)
    try:
        _bc = json.load(open(os.path.join('system', 'analysis', 'bag_count.json')))
        if not isinstance(_bc, dict):
            _bc = {}
    except Exception:
        _bc = {}
    # THIS WALK'S EGGS ONLY (R-B review, the H05-8 family -- this is the line the cull skill quotes): bag_count.json is
    # written right after the walk stamps last_scanned; an older (or another trainer's) file's eggs are not this bag's
    _bc_this = _read_by_walk(_bc.get('ts'), '%Y-%m-%d %H:%M:%S') is True and isinstance(_bc.get('eggs_incubated'), int)
    _inc = _bc['eggs_incubated'] if _bc_this else 0
    _used = s['bag'] + _inc
    cap_txt = (('%d (free %s%d)' % (s['cap'], '' if _bc_this else 'at most ', s['cap'] - _used)) if s['cap']
               else '? (capacity unknown)')
    if s.get('cap_old'):                       # H06-6: never an old cap passed off as this walk's
        cap_txt += ' [capacity NOT read this walk -- player_state.json is from %s; see the recrawl warnings]' % s['cap_old']
    say('bag %d%s/%s | hundos %d nundos %d | PILE %s'
        % (_used, (' (%d Pokemon + %d eggs in incubators)' % (s['bag'], _inc)) if _inc else
           ('' if _bc_this else ' (Pokemon only -- eggs in incubators not read by this walk)'), cap_txt, s['hundos'], s['nundos'],
           s['pile'] if s['pile'] is not None else '? (Transfer.txt missing)'))

    _audited = _pile_members()            # X3 (2026-09-24): the pile these audits judge -- the sync must push this one
    try:                                  # 2026-09-30, cull speed pick 1: the bytes these audits judge. Unchanged at the
        import granular_tags as _gtd      # sync -> it pushes them as they are (no second keep_policy + build_tagsets)
        _audited_files = _gtd.pushed_files_digest()
    except Exception:
        _audited_files = None             # no digest -> the sync re-runs them, as before
    res = run_audits()
    for nm, ok, log in res:
        verdict = ([l for l in log.splitlines() if 'VERDICT' in l or 'UNEXPLAINED' in l] or ['(no verdict line)'])[-1]
        say('%-15s %s  %s' % (nm, 'PASS' if ok else '*** FAIL ***', verdict.strip()[:88]))
    bad = [(nm, log) for nm, ok, log in res if not ok]
    if bad:
        for nm, log in bad:
            print('\n----- %s: failing lines -----' % nm)
            for l in log.splitlines():
                if any(k in l for k in ('FAIL', 'UNEXPLAINED', 'OVERLAP', '***', 'DRIFT')):
                    print('   ', l.strip()[:130])
        say('AUDIT GATE FAILED -- SYNC NOT RUN (pile is irreversible; fix first)'); return 1
    if '--no-sync' in argv:
        say('audits pass; --no-sync given, stopping before any phone write'); return 0

    catcher_pause()                            # phone again: the catcher lets go (~1 s)
    rc, log = run_job('/api/sync', {'dry': False, 'audited_pile_members': _audited, 'audited_tagsets': _audited_files,
                                    'reconcile': False})    # its reconcile rides the post-push session below (pick 2)
    # X4 (design review 2026-09-24): a write that still needs its server proof is recorded HERE, whatever the rc -- a
    # sync that failed after prune wrote some tags must not look proven on the next idle pass. Unreadable -> pending.
    _proof_pending(_sync_changed_tags(log))
    for l in log.splitlines():
        if 'apply_changes' in l or 'All tags in sync' in l or l.startswith('recompute: reusing'):
            say('  ' + l.strip()[:100])
    echo_job_warnings('sync', log, os.path.join('system', 'analysis', 'last_job_api_sync.log'))   # H06-2
    if rc:
        print('\n'.join([l for l in log.splitlines() if l.strip()][-8:]))
        say('SYNC FAILED rc=%s' % rc); return 3
    catcher_pause(wait=False)                  # re-arm (90 s) for retire / verify / Remote Trade / Evolve for Size / tag order

    # ONE POST-PUSH SESSION (2026-09-30, cull speed pick 2; user: "1,2, go"). The reconcile report that ended the sync job,
    # the retire step and Remote Trade + the tag order each attached on their own: 3 of the cull's 5 attaches, each a
    # crash roll and ~5-8 s. sync_post_tags.py --reconcile --retire runs them in ONE session, in the old order: the
    # reconcile first -- read-only, still a fresh session next to prune's (the independent check it exists for) -- and on
    # drift it stops before any label write (rc 3) -> SYNC FAILED here, exactly as a drifting reconcile inside the sync
    # job failed it. Then retire (fail-soft), Remote Trade, the tag order. The ladder starts first so it overlaps that
    # phone time; it already overlapped Remote Trade's DB mirror, the only thing this session writes that it reads.
    _lr = ladder_start()
    try:
        _post = post_tags_run(('--reconcile', '--retire'))
    except Exception as _pe:
        _post = (subprocess.CompletedProcess(['sync_post_tags.py'], 1, '', 'not run: %s' % _pe),
                 {'RECONCILE': [], 'RETIRE': [], 'REMOTE TRADE': [], 'TAG ORDER': []})
    _rec = '\n'.join(_post[1]['RECONCILE'])
    for l in _rec.splitlines():
        if 'All tags in sync' in l or 'Drift detected' in l:
            say('  ' + l.strip()[:100])
    if 'All tags in sync.' not in _rec:
        # the sync job's own failure path: its last lines, then SYNC FAILED rc 3 -- no report, no label write
        print('\n'.join([l for l in (_rec or ((_post[0].stdout or '') + '\n' + (_post[0].stderr or ''))).splitlines()
                         if l.strip()][-8:]))
        if _lr is not None:                    # the ladder started above: let it end (a kill could tear its history)
            try:
                _lr.communicate(timeout=300)
            except Exception:
                _lr.kill()
        say('SYNC FAILED rc=%s -- the post-push reconcile %s (log: system/analysis/last_job_post_tags.log)'
            % (_post[0].returncode, 'found drift' if 'Drift detected' in _rec else 'gave no verdict'))
        return 3
    catcher_pause(wait=False)                  # re-arm (90 s) for verify

    # RETIRED tag shells (2026-09-09): prune has just stripped their members; retire_tags deletes the empty shells one
    # at a time, up to its own --max, and stops at the first DeleteTag refusal (the game can cut a session off after
    # 1-3 deletions). FAIL-SOFT: never changes this run's rc. Since 2026-09-30 it runs inside the post-push session
    # above (every pass: its plan() does the grace bookkeeping, then deletes only a retired / due-empty shell that is
    # actually on the device). A census alarm right after the push ('Transfer 9 -> 0') was HIM releasing the pile in
    # those seconds, not collateral -- retire stops on it either way, which is the safe side.
    # THE REASON, NOT JUST THE TALLY (2026-09-23: "deleted 3 ... 7 left" was printed with no reason). retire_tags
    # prints a DeleteTag refusal, a collateral-census stop and its problem lines, a regained-member skip, a shell
    # that still holds members, or an uncleared DB mirror ABOVE its last line -- echo each of those, then the tally.
    _rl = [l for l in _post[1]['RETIRE'] if l.strip()]
    _rfail = [l for l in _rl if l.startswith('RETIRE failed')]
    _coll = False
    for _l in (_rl if _rfail else _rl[:-1]):
        _coll = _coll or 'COLLATERAL' in _l
        if _coll or any(k in _l for k in ('refused', 'regained', 'still holds', 'not cleared')):
            say('retire:   %s' % _l.strip()[:160])
    say('retire: %s' % ((_rfail[-1] if _rfail else _rl[-1]).strip()[:240] if _rl else 'no output'))

    if 'All tags in sync.' in _rec:
        try:
            sys.path.insert(0, os.getcwd())
            import verify_tags_live as _vtl
            _playing = _vtl.user_is_playing()
        except Exception:
            _playing = True
        # NEVER RESTART POGO UNDER THE CATCHER (user 2026-09-25: "without interrupting the catcher at all, cull"): the
        # server-proof restart kills the game the auto-catcher is attached to. A live catcher on the gadget (:27047)
        # counts as playing, so the proof stays deferred.
        if not _playing:
            try:
                import pogo_il2cpp as _pg
                _n = subprocess.run(['adb', '-s', _pg.ADB_TARGET, 'shell', "su -c 'ss -tn | grep -c :27047'"],
                                    capture_output=True, text=True, timeout=15).stdout.strip()
                if _n not in ('', '0'):
                    _playing = True
                    say('catcher attached on :27047 -> counted as playing (no second cache read)')
            except Exception:
                _playing = True                # cannot tell -> do not restart
        _pending = _proof_pending(_sync_changed_tags(log))
        if _playing or not _pending:
            # the post-push reconcile already proved the client cache equal; a second cache read adds an attach
            # and nothing else. The restart-based SERVER proof only happens when the phone is idle AND a write is
            # still waiting for it (this pass's, or one deferred while he was playing) -- and since 2026-09-25 it never
            # happens at all (verify_tags_live is cache-only; see _unproven_note).
            say('VERIFY OK (the client-cache reconcile after the push is clean; %s) -- %s'
                % ('user playing -> no second cache read' if _playing else 'no tag written -> no second cache read',
                   _unproven_note(log)))
            say('DONE -- %s tagged for Transfer' % state()['pile'])
            post_tags_say(*_post)              # Remote Trade + the tag order ran in the post-push session above
            catcher_resume()                   # last phone step done -- the reports are offline
            ladder_finish(_lr)
            report_step()
            return 0
    catcher_pause(wait=False)                  # verify is a cache reconcile only -- it never restarts PoGo (2026-09-25)
    v = subprocess.run([PY, 'verify_tags_live.py'], capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if v.returncode != 0:
        # CACHE LAG (2026-09-09): right after a large push the client's tag-binding cache can read 0 members
        # for the tags just rewritten, so the first reconcile reports DRIFT/rc=1 although prune's own fresh-walk
        # verify passed and a reconcile run a minute later is clean. One retry after 20 s before calling it a
        # failure -- a false VERIFY FAILED here makes the watcher report rc=4 "needs a look" for nothing.
        say('verify: first pass rc=%d -- waiting 20 s for the tag cache to settle, then retrying once' % v.returncode)
        time.sleep(20)
        v = subprocess.run([PY, 'verify_tags_live.py'], capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
    vout = v.stdout or ''
    if v.returncode == 0 and 'genuine server refetch' in vout and os.path.exists(PROOF_PENDING):
        os.remove(PROOF_PENDING)             # every write so far is server-proven
    for l in vout.splitlines():
        if any(k in l for k in ('  OK', 'DRIFT', 'All tags in sync', 'VERIFIED', 'CACHE reconcile',
                                'VERIFICATION FAILED', 'ACTIVELY PLAYING')):
            print('    ' + l.rstrip()[:110])
    say('VERIFY %s' % (('OK (a second client-cache reconcile, fresh attach: clean) -- %s' % _unproven_note(log))
                        if v.returncode == 0 else '*** FAILED ***'))
    say('DONE -- %s tagged for Transfer%s' % (state()['pile'], '' if v.returncode == 0 else ' (VERIFY FAILED)'))
    # THE FOREVER-FRIENDS TRADE WINDOW, REFRESHED EVERY CULL (user 2026-09-19: "make this a part of your cull every
    # time to update it"). Same session shape as the tag sync; never creates a tag, and a failure here never fails the
    # cull -- the pile is the irreversible output, a trade label is not.
    post_tags_say(*_post)                      # Remote Trade + the tag order ran in the post-push session above
    catcher_resume()                           # last phone step done -- the reports are offline
    ladder_finish(_lr)
    report_step(verify_failed=v.returncode != 0)
    return 0 if v.returncode == 0 else 4

if __name__ == '__main__':
    sys.exit(main())

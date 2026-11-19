"""CULL NOW button (AutoCatcher app 1.2; Benny 2026-11-05 "you do it"): one tap on the phone = one cull on this PC.

The app writes `requested <epoch> <HH:MM:SS>` to /data/local/tmp/pogo_cull.req (as root). This listener reads it over ADB
every 15 s. A NEW request (epoch above the last one handled, under 15 minutes old) runs ONE pass of the cull the /cull skill
runs (full_audit.py, then the data push), and writes one status line the app shows, /data/local/tmp/pogo_cull_status.txt:
    queued HH:MM ... | running since HH:MM | done HH:MM: release N in the Transfer tag | bag X/Y (Z free) | STOPPED HH:MM: why
Rules it keeps (CLAUDE.md hard rules): it only TAGS; one tap = one pass, never a retry; 3 minutes after the last pass; the game
up 2+ minutes with the gadget listening; it never pauses the catcher or restarts the game; it pushes the data after every
phone pass. The pass's === REPORT === is kept in system/analysis/cull_button_report.txt for Claude to relay; full_audit
regenerates Bag Pulse, but only a Claude session publishes it.
Since 2026-11-18 (Benny: "Does the cull button on the new autocatcher app work correcly and completly?"): a tap is made in
the AutoCatcher app, so the game is NOT on screen at the tap and the pass attaches to nothing but a game on screen -- the
listener waits 3 minutes for the game and says so; and "release N" is said only when the report's own first line says it
(a failed verify or an unconfirmed tag reads "do NOT release yet"), with the pass's warning-line count beside it.
ON THE PHONE SINCE 2026-11-18 (Benny: "the entire thing needs to run on the phone just like the gym mode."): this listener
runs in Termux from the repo clone ~/cull, started by ../tools/cull_phone.sh (Termux:Boot starts that), and the whole pass
runs on the phone with the PC off. ../tools/phone/adb stands in for adb there (root shell commands, local copies). While it
waits it reads the request file itself (no root call every 15 s); before a pass it takes main from GitHub (fast-forward
only; no network = the code it has); it refuses while the battery is under BATTERY_MIN % and not charging (the pass's CPU is
the phone's now) and while a cull from the PC is attached (the phone busy marker, PokemonInventory). The PC no longer runs a
listener: two would both see a tap.
Run on the phone:  bash ~/cull/tools/cull_phone.sh      Offline self-check:  python cull_button.py --selftest
"""
import datetime as dt
import json
import os
import re
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AN = os.path.join(HERE, 'system', 'analysis')
ADB = os.environ.get('ADB_TARGET') or '100.98.158.56:5555'
REQ, STATUS = '/data/local/tmp/pogo_cull.req', '/data/local/tmp/pogo_cull_status.txt'
# Which side this is: the Termux prefix exists only on the phone; POGO_ON_PHONE=1 / 0 says so outright (cull_phone.sh: 1).
ON_PHONE = os.environ.get('POGO_ON_PHONE', '1' if os.path.isdir('/data/data/com.termux/files/usr') else '0') == '1'
BUSY = '/data/local/tmp/pogo_desktop_busy'      # pogo_il2cpp's marker: "<name> <deadline epoch>" while a desktop tool is attached
BATTERY_MIN = 10            # % -- under it, and not charging, no pass starts on the phone (11-18 20:50: 3%, too hot to charge)
LOG = os.path.join(AN, 'cull_button.log')
# The listener's own memory of the last tap it handled. On the phone it sits OUTSIDE the data store (system/analysis/*.json
# travels with every pull): a pull must never hand it an older epoch, or one tap would run twice.
STATE = os.path.join(ROOT, '.cull_button_state.json') if ON_PHONE else os.path.join(AN, 'cull_button_state.json')
CULL_LOG, REPORT = os.path.join(AN, 'last_cull.log'), os.path.join(AN, 'cull_button_report.txt')
POLL_S, MAX_AGE_S, GAP_S, GAME_UP_S = 15, 15 * 60, 180, 120
SCREEN_WAIT_S = 180         # a tap is made in the AutoCatcher app: this long for him to be back in the game
GAME = 'com.nianticlabs.pokemongo'
SCREEN_CMD = ('dumpsys activity activities | grep -m1 -E "topResumedActivity|ResumedActivity"; '
              'dumpsys power | grep -m1 mWakefulness=')
MUTEX_PORT = 48766          # one listener at a time: the second one cannot bind and exits
# Children run under python.exe even when this listener runs under pythonw.exe: under pythonw the audits' process pools
# die (BrokenProcessPool), and the 11-05 01:23 tap stopped at "promises (no verdict line)". CREATE_NO_WINDOW keeps every
# child (adb, python, powershell) from flashing a console window on the PC.
PY = (os.path.join(os.path.dirname(sys.executable), 'python.exe') if sys.executable.lower().endswith('pythonw.exe')
      else sys.executable)
NOWIN = 0x08000000 if os.name == 'nt' else 0


def _run(args, **kw):
    return subprocess.run(args, creationflags=NOWIN, **kw)


def log(msg):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write('%s %s\n' % (dt.datetime.now().strftime('%m-%d %H:%M:%S'), msg))


def adb(cmd, timeout=25):
    try:
        p = _run(['adb', '-s', ADB, 'shell', cmd], capture_output=True, text=True, timeout=timeout)
        return p.stdout.replace('\r', '').strip() if p.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def status(msg):
    """One line for the app. The shell user owns /data/local/tmp, so it can (re)create the file; 644 = the app reads it."""
    msg = msg.replace("'", '').replace('\n', ' ')
    adb("echo '%s' > %s; chmod 644 %s" % (msg, STATUS, STATUS))
    log('status: ' + msg)


def hhmm(epoch=None):
    return time.strftime('%H:%M', time.localtime(epoch or time.time()))


def read_local(path):
    """A /data/local/tmp file Termux may read without root (the app's request is 666, the busy marker 666), else None."""
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return None


def read_req():
    """The app's request line. On the phone a plain read: no root call every 15 s (each one starts Magisk's helper)."""
    return (read_local(REQ) if ON_PHONE else None) or adb('cat %s 2>/dev/null' % REQ)


def parse_battery(text):
    """`dumpsys battery` -> (level %, charging?) or (None, None). status 2 = charging, 5 = full."""
    lv, st = re.search(r'^\s*level:\s*(\d+)', text or '', re.M), re.search(r'^\s*status:\s*(\d+)', text or '', re.M)
    return (int(lv.group(1)), st is not None and st.group(1) in ('2', '5')) if lv else (None, None)


def pc_attached(text, now):
    """The busy marker names the PC's cull (exactly PokemonInventory; the phone's own pass writes PokemonInventoryPhone) with
    a deadline still ahead: a cull from the PC is attached right now."""
    m = re.match(r'\s*(\S+)\s+(\d+)', text or '')
    return bool(m) and m.group(1) == 'PokemonInventory' and int(m.group(2)) > now


def code_update():
    """The phone runs main as it is on GitHub: fast-forward only, before each pass. -> the commit now, or None (no network,
    a local change: the code it has runs, and the log says why)."""
    try:
        p = _run(['git', '-C', ROOT, 'pull', '--ff-only', '-q'], capture_output=True, text=True, timeout=120)
        if p.returncode:
            log('code update failed (rc %s), running the code it has: %s' % (p.returncode, (p.stderr or p.stdout).strip()[-200:]))
    except (subprocess.TimeoutExpired, OSError) as e:
        log('code update failed (%r), running the code it has' % e)
    return _head()


def _head():
    try:
        return _run(['git', '-C', ROOT, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, timeout=30).stdout.strip() or None
    except (subprocess.TimeoutExpired, OSError):
        return None


def parse_req(text):
    """'requested <epoch> <HH:MM:SS>' -> epoch, else None."""
    m = re.match(r'requested\s+(\d{9,11})\b', (text or '').strip())
    return int(m.group(1)) if m else None


def parse_elapsed(s):
    """ps ELAPSED ([[dd-]hh:]mm:ss) -> seconds, else None."""
    m = re.fullmatch(r'(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)', (s or '').strip())
    if not m:
        return None
    d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + se


def on_screen(out):
    """Is Pokemon GO the app on screen, with the screen on? The two lines pogo_il2cpp._on_screen reads (that module needs
    frida; this listener does not). The pass attaches to nothing else: an attach to a game behind another app hung and the
    game died 37 s later (2026-11-16). A read that failed = not on screen."""
    m = re.search(r'ResumedActivity\S*\s*ActivityRecord\{\S+ \S+ ([\w.]+)/', out or '')
    return bool(m) and m.group(1) == GAME and 'mWakefulness=Awake' in out


def parse_cull(text, rc):
    """What one full_audit pass said -> ('done', line) or ('STOPPED', why). "Release" only when the REPORT's own first
    line says it (2026-11-18): that line knows a failed verify, an unconfirmed tag and a frozen walk, the DONE line does
    not -- and the release is the one thing he does by hand that cannot be undone."""
    for pat, why in ((r'GAME MASTER REFRESH STOPPED', 'a new game master moved a keep verdict -- ask Claude'),
                     (r'AUDIT GATE FAILED', 'an audit failed (nothing was tagged) -- ask Claude'),
                     (r'\[frozen\]|session is gone', 'the game session froze or went away -- ask Claude'),
                     (r'PoGo is not on screen', 'the game left the screen during the cull -- open it, stay in it, then tap again'),
                     (r'STOPPED', 'the walk stopped itself -- ask Claude')):
        if re.search(pat, text):
            return 'STOPPED', why
    done = re.search(r'DONE -- (\d+) tagged for Transfer', text)
    if rc != 0 or not done:
        return 'STOPPED', 'the cull ended with rc %s -- ask Claude' % rc
    rep = text.split('=== REPORT ===', 1)
    lead = next((l.strip() for l in rep[1].splitlines() if l.strip() and not l.startswith('[')), '') if len(rep) > 1 else ''
    rel = re.match(r'\*\*Release the (\d+) in the Transfer tag\.\*\*', lead)
    if rel:
        line = 'release %s in the Transfer tag' % rel.group(1)
    elif lead.startswith('**Nothing to release**'):
        line = 'nothing to release'
    else:
        return 'STOPPED', 'the cull ran, but its report does not say release -- do NOT release yet, ask Claude'
    bag = re.search(r'bag (\d+) \(\d+ Pokemon \+ \d+ eggs? in incubators\)/(\d+) \(free (\d+)\)', text)
    if bag:
        line += ' | bag %s/%s (%s free)' % bag.groups()
    warn = re.search(r'WARNING LINES THIS PASS: (\d+)', text)
    if warn and int(warn.group(1)):
        line += ' | %s warning line(s): read the report with Claude before you release' % warn.group(1)
    return 'done', line


def data_versions():
    """(phone, here) inventory versions from pogo_data status, else (None, None)."""
    try:
        out = _run([PY, os.path.join('tools', 'pogo_data.py'), 'status'], cwd=ROOT,
                             capture_output=True, text=True, timeout=120).stdout
    except (subprocess.TimeoutExpired, OSError):
        return None, None
    m = re.search(r'^inventory\s.*?phone v(\d+).*?here v(\d+)', out, re.M)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def data(cmd):
    p = _run([PY, os.path.join('tools', 'pogo_data.py')] + cmd, cwd=ROOT,
                       capture_output=True, text=True, timeout=900)
    log('pogo_data %s rc=%s %s' % (' '.join(cmd), p.returncode, (p.stdout.strip().splitlines() or [''])[-1][:160]))
    return p.returncode == 0


def cull_running():
    """Is a full_audit.py pass already running on this machine (a Claude session's cull, or anything else)?"""
    try:
        if os.name == 'nt':
            out = _run(['powershell', '-NoProfile', '-Command',
                                  "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | ForEach-Object CommandLine"],
                                 capture_output=True, text=True, timeout=30).stdout
        else:
            out = _run(['ps', '-eo', 'args'], capture_output=True, text=True, timeout=30).stdout
    except (subprocess.TimeoutExpired, OSError):
        return True                                       # unknown = assume busy: never risk two passes at once
    return 'full_audit.py' in out


def gap_left():
    """Seconds still to wait for "3 minutes after the last cull": this listener's own last pass (its log), or the last walk
    from anywhere (bag_count.json -- every data pull brings the PC's) -- a quick re-attach crashed the gadget before."""
    ts = [os.path.getmtime(p) for p in (CULL_LOG, os.path.join(AN, 'bag_count.json')) if os.path.exists(p)]
    return GAP_S - (time.time() - max(ts)) if ts else 0


def one_pass(req_epoch):
    """Everything one tap does; the last status line it writes is the answer."""
    if cull_running():
        status('STOPPED %s: a cull is already running -- tap again when it is done' % hhmm()); return
    if ON_PHONE:
        lv, charging = parse_battery(adb('dumpsys battery'))
        if lv is not None and lv < BATTERY_MIN and not charging:
            status('STOPPED %s: battery %d%% and not charging -- the cull runs on the phone, charge it first, then tap again'
                   % (hhmm(), lv)); return
        if pc_attached(read_local(BUSY) or adb('cat %s 2>/dev/null' % BUSY), int(time.time())):
            status('STOPPED %s: a cull from the PC is attached right now -- tap again in a few minutes' % hhmm()); return
        log('code: %s' % code_update())
    pv, hv = data_versions()
    if pv is None:
        status('STOPPED %s: could not read the data store versions -- ask Claude' % hhmm()); return
    if pv > hv and not data(['pull', '--group', 'inventory']):
        status('STOPPED %s: pulling the newer data failed -- ask Claude' % hhmm()); return
    if pv < hv and not data(['push', '--group', 'inventory']):
        status('STOPPED %s: pushing the data first failed -- ask Claude' % hhmm()); return
    wait = gap_left()
    if wait > 0:
        status('queued %s: starting at %s (3 minutes after the last cull)' % (hhmm(), hhmm(time.time() + wait)))
        time.sleep(wait)
    for _ in range(25):                                   # a starting game gets ~4 minutes before anyone attaches
        pid = adb('pidof com.nianticlabs.pokemongo')
        up = parse_elapsed(adb('ps -o ELAPSED= -p %s' % pid)) if pid else None
        if pid and up is not None and up >= GAME_UP_S:
            break
        status('queued %s: waiting for the game to finish starting' % hhmm())
        time.sleep(10)
    else:
        status('STOPPED %s: the game is not running -- open it and tap again' % hhmm()); return
    gadget = adb('grep -ci :69A7 /proc/net/tcp')
    if not gadget or not gadget.isdigit() or int(gadget) < 1:
        status('STOPPED %s: the game has no gadget listening -- ask Claude' % hhmm()); return
    until, told = time.time() + SCREEN_WAIT_S, False       # he tapped in the app: wait for him to be back in the game
    while not on_screen(adb(SCREEN_CMD)):
        if time.time() >= until:
            status('STOPPED %s: Pokemon GO was not on screen for 3 minutes (nothing ran) -- tap again, then open the game' % hhmm())
            return
        if not told:
            status('queued %s: open Pokemon GO and stay in it -- the cull starts when the game is on screen (it waits until %s)'
                   % (hhmm(), hhmm(until)))
            told = True
        time.sleep(5)                                     # each look is one root call on the phone
    start = time.time()
    status('running since %s' % hhmm(start))
    log('cull for the tap at %s (pid %s, game up %ss)' % (hhmm(req_epoch), pid, up))
    with open(CULL_LOG, 'w', encoding='utf-8', errors='replace') as f:
        rc = _run([PY, 'full_audit.py'], cwd=HERE, stdout=f, stderr=subprocess.STDOUT).returncode
    text = open(CULL_LOG, encoding='utf-8', errors='replace').read()
    kind, line = parse_cull(text, rc)
    rep = text.split('=== REPORT ===', 1)
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('cull from the phone button, tap %s, ran %s-%s, rc %s\n' % (hhmm(req_epoch), hhmm(start), hhmm(), rc))
        f.write('=== REPORT ===' + '\n'.join(l for l in rep[1].splitlines() if not l.startswith('[')) if len(rep) > 1 else '')
    pushed = data(['push', '--group', 'inventory'])          # ALWAYS after a phone pass, even when the gate failed
    status('%s %s: %s%s' % (kind, hhmm(), line, '' if pushed else ' (data push failed -- ask Claude)'))


def load_state(path=STATE, now=None):
    """The last tap handled. None yet (the first start on the phone): a tap older than 15 minutes is history, not a request
    -- the 11-05 tap still in the file must not come back as a STOPPED line."""
    try:
        with open(path) as f:
            return {'last_epoch': int(json.load(f)['last_epoch'])}
    except (OSError, ValueError, KeyError, TypeError):
        return {'last_epoch': int(now or time.time()) - MAX_AGE_S}


def main():
    if not ON_PHONE:
        print('cull_button: the Cull Now listener runs on the phone since 2026-11-18 (tools/cull_phone.sh), not here: '
              'two listeners would both see one tap'); return 2
    try:
        mutex = socket.socket(); mutex.bind(('127.0.0.1', MUTEX_PORT))
    except OSError:
        print('cull_button: another listener is already running'); return 3
    st, head = load_state(), _head()
    log('listener up on the phone (pid %s, code %s)' % (os.getpid(), head))
    status('ready %s: tap Cull Now, then go back to Pokemon GO -- the phone runs one cull' % hhmm())
    while True:
        try:
            ep = parse_req(read_req())
            if ep and ep > st['last_epoch']:
                st['last_epoch'] = ep
                json.dump(st, open(STATE, 'w'))                 # handled BEFORE the pass: one tap can never run twice
                if time.time() - ep > MAX_AGE_S:
                    status('STOPPED %s: that tap was from %s, too long ago -- tap again' % (hhmm(), hhmm(ep)))
                else:
                    one_pass(ep)
                    if _head() != head:                         # the pass took a newer main: the listener's own code too
                        log('the code moved (%s -> %s): the listener restarts' % (head, _head())); return 0
        except Exception as e:                                  # the listener stays up; the tap is already marked done
            log('error: %r' % e)
            try:
                status('STOPPED %s: the listener hit an error -- ask Claude' % hhmm())
            except Exception:
                pass
        time.sleep(POLL_S)


def selftest():
    assert parse_req('requested 1793857282 00:41:22\n') == 1793857282 and parse_req('') is None and parse_req('x') is None
    assert parse_elapsed('07:55') == 475 and parse_elapsed('01:02:03') == 3723 and parse_elapsed('2-00:00:01') == 172801
    assert parse_elapsed('') is None
    head = ('[ 94.1s] bag 5850 (5849 Pokemon + 1 eggs in incubators)/5850 (free 0) | PILE 182\n'
            '[121.4s] DONE -- 182 tagged for Transfer\n[122.0s] WARNING LINES THIS PASS: %d\n=== REPORT ===\n')
    ok = head % 0 + '**Release the 182 in the Transfer tag.** (the game read back 182 in the tag in the sync that started at 17:20)\n'
    assert parse_cull(ok, 0) == ('done', 'release 182 in the Transfer tag | bag 5850/5850 (0 free)')
    assert parse_cull(ok, 1)[0] == 'STOPPED'
    # "release" comes from the report's first line, never from the DONE line alone (2026-11-18)
    for lead in ('**Do not release yet -- the verify after the 17:20 sync FAILED.** 182 in the pile file; ...',
                 '**Do not release yet -- the Transfer tag was not confirmed for this walk.** 182 in the pile file, ...',
                 '**Do not release yet if you caught, hatched, evolved, released or powered up anything since 17:01** -- ...',
                 '', '[123.0s] a timing line is not the report'):
        got = parse_cull(head % 0 + lead + '\n', 0)
        assert got[0] == 'STOPPED' and 'do NOT release yet' in got[1], (lead, got)
    assert parse_cull(head % 0 + '[123.0s] late line\n**Release the 181 in the Transfer tag.** (the game ...)\n', 0)[1].startswith('release 181 ')
    assert parse_cull(head % 0 + '**Nothing to release** -- the pile is empty.\n', 0) == ('done', 'nothing to release | bag 5850/5850 (0 free)')
    assert parse_cull(head % 2 + ok.split('=== REPORT ===\n')[1], 0)[1].endswith('| 2 warning line(s): read the report with Claude before you release')
    assert parse_cull('STOPPED: PoGo is not on screen (com.x is on screen, PoGo is behind it) -- nothing was attached.\n', 2)[1].startswith('the game left the screen')
    # the game on screen: the two lines the pass itself reads; anything else, or a failed read, is not on screen
    g = '    topResumedActivity=ActivityRecord{197450920 u0 %s/com.nianticproject.holoholo.libholoholo.unity.UnityMainActivity t75}\n'
    assert on_screen(g % GAME + '  mWakefulness=Awake\n') and on_screen((g % GAME).replace('topResumedActivity=', 'ResumedActivity: ') + '  mWakefulness=Awake\n')
    assert not on_screen(g % 'com.benny.autocatcher' + '  mWakefulness=Awake\n'), 'a tap is made in the app: the game is behind it'
    assert not on_screen(g % GAME + '  mWakefulness=Asleep\n') and not on_screen('') and not on_screen(None)
    assert parse_cull('[ 41.7s] AUDIT GATE FAILED -- SYNC NOT RUN\n', 1) == ('STOPPED', 'an audit failed (nothing was tagged) -- ask Claude')
    assert parse_cull('GAME MASTER REFRESH STOPPED THE PASS (rc 5)\n', 5)[1].startswith('a new game master')
    # on the phone (2026-11-18): the battery line, the PC's attach, the first start
    bat = 'Current Battery Service state:\n  AC powered: true\n  status: %s\n  health: 2\n  level: %s\n  scale: 100\n'
    assert parse_battery(bat % (4, 3)) == (3, False), '11-18 20:50: 3%, plugged in, not charging (too hot)'
    assert parse_battery(bat % (2, 3)) == (3, True) and parse_battery(bat % (5, 100)) == (100, True)
    assert parse_battery('') == (None, None) and parse_battery(None) == (None, None)
    assert pc_attached('PokemonInventory 1793900300\n', 1793900000) and not pc_attached('PokemonInventory 1793900300', 1793900400)
    assert not pc_attached('PokemonInventoryPhone 1793900300', 1793900000), 'the phone pass\'s own marker never blocks a tap'
    assert not pc_attached('GymBattle 1793900300', 1793900000) and not pc_attached('', 0) and not pc_attached(None, 0)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'state.json')
        assert load_state(p, now=1793900000) == {'last_epoch': 1793900000 - MAX_AGE_S}, 'no state: an old tap is history'
        json.dump({'last_epoch': 1793859787}, open(p, 'w'))
        assert load_state(p) == {'last_epoch': 1793859787}
    print('cull_button selftest: OK')
    return 0


if __name__ == '__main__':
    args = sys.argv[1:]
    if args == ['--selftest']:
        sys.exit(selftest())
    if args:
        print(__doc__); sys.exit(2)
    sys.exit(main())

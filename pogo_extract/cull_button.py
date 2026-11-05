"""CULL NOW button (AutoCatcher app 1.2; Benny 2026-11-05 "you do it"): one tap on the phone = one cull on this PC.

The app writes `requested <epoch> <HH:MM:SS>` to /data/local/tmp/pogo_cull.req (as root). This listener reads it over ADB
every 15 s. A NEW request (epoch above the last one handled, under 15 minutes old) runs ONE pass of the cull the /cull skill
runs (full_audit.py, then the data push), and writes one status line the app shows, /data/local/tmp/pogo_cull_status.txt:
    queued HH:MM ... | running since HH:MM | done HH:MM: release N in the Transfer tag | bag X/Y (Z free) | STOPPED HH:MM: why
Rules it keeps (CLAUDE.md hard rules): it only TAGS; one tap = one pass, never a retry; 3 minutes after the last pass; the game
up 2+ minutes with the gadget listening; it never pauses the catcher or restarts the game; it pushes the data after every
phone pass. The pass's === REPORT === is kept in system/analysis/cull_button_report.txt for Claude to relay; full_audit
regenerates Bag Pulse, but only a Claude session publishes it.
Run in the background:  pythonw cull_button.py      Offline self-check:  python cull_button.py --selftest
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
STATE, LOG = os.path.join(AN, 'cull_button_state.json'), os.path.join(AN, 'cull_button.log')
CULL_LOG, REPORT = os.path.join(AN, 'last_cull.log'), os.path.join(AN, 'cull_button_report.txt')
POLL_S, MAX_AGE_S, GAP_S, GAME_UP_S = 15, 15 * 60, 180, 120
MUTEX_PORT = 48766          # one listener at a time: the second one cannot bind and exits


def log(msg):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write('%s %s\n' % (dt.datetime.now().strftime('%m-%d %H:%M:%S'), msg))


def adb(cmd, timeout=25):
    try:
        p = subprocess.run(['adb', '-s', ADB, 'shell', cmd], capture_output=True, text=True, timeout=timeout)
        return p.stdout.replace('\r', '').strip() if p.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def connected():
    try:
        out = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=15).stdout
        if re.search(r'^%s\s+device$' % re.escape(ADB), out.replace('\r', ''), re.M):
            return True
        subprocess.run(['adb', 'connect', ADB], capture_output=True, text=True, timeout=15)
        out = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=15).stdout
        return bool(re.search(r'^%s\s+device$' % re.escape(ADB), out.replace('\r', ''), re.M))
    except (subprocess.TimeoutExpired, OSError):
        return False


def status(msg):
    """One line for the app. The shell user owns /data/local/tmp, so it can (re)create the file; 644 = the app reads it."""
    msg = msg.replace("'", '').replace('\n', ' ')
    adb("echo '%s' > %s; chmod 644 %s" % (msg, STATUS, STATUS))
    log('status: ' + msg)


def hhmm(epoch=None):
    return time.strftime('%H:%M', time.localtime(epoch or time.time()))


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


def parse_cull(text, rc):
    """What one full_audit pass said -> ('done', line) or ('STOPPED', why)."""
    for pat, why in ((r'GAME MASTER REFRESH STOPPED', 'a new game master moved a keep verdict -- ask Claude'),
                     (r'AUDIT GATE FAILED', 'an audit failed (nothing was tagged) -- ask Claude'),
                     (r'\[frozen\]|session is gone', 'the game session froze or went away -- ask Claude'),
                     (r'STOPPED', 'the walk stopped itself -- ask Claude')):
        if re.search(pat, text):
            return 'STOPPED', why
    done = re.search(r'DONE -- (\d+) tagged for Transfer', text)
    if rc != 0 or not done:
        return 'STOPPED', 'the cull ended with rc %s -- ask Claude' % rc
    bag = re.search(r'bag (\d+) \(\d+ Pokemon \+ \d+ eggs? in incubators\)/(\d+) \(free (\d+)\)', text)
    line = 'release %s in the Transfer tag' % done.group(1)
    if bag:
        line += ' | bag %s/%s (%s free)' % bag.groups()
    return 'done', line


def data_versions():
    """(phone, here) inventory versions from pogo_data status, else (None, None)."""
    try:
        out = subprocess.run([sys.executable, os.path.join('tools', 'pogo_data.py'), 'status'], cwd=ROOT,
                             capture_output=True, text=True, timeout=120).stdout
    except (subprocess.TimeoutExpired, OSError):
        return None, None
    m = re.search(r'^inventory\s.*?phone v(\d+).*?here v(\d+)', out, re.M)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def data(cmd):
    p = subprocess.run([sys.executable, os.path.join('tools', 'pogo_data.py')] + cmd, cwd=ROOT,
                       capture_output=True, text=True, timeout=900)
    log('pogo_data %s rc=%s %s' % (' '.join(cmd), p.returncode, (p.stdout.strip().splitlines() or [''])[-1][:160]))
    return p.returncode == 0


def cull_running():
    """Is a full_audit.py pass already running on this machine (a Claude session's cull, or anything else)?"""
    try:
        if os.name == 'nt':
            out = subprocess.run(['powershell', '-NoProfile', '-Command',
                                  "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | ForEach-Object CommandLine"],
                                 capture_output=True, text=True, timeout=30).stdout
        else:
            out = subprocess.run(['ps', '-eo', 'args'], capture_output=True, text=True, timeout=30).stdout
    except (subprocess.TimeoutExpired, OSError):
        return True                                       # unknown = assume busy: never risk two passes at once
    return 'full_audit.py' in out


def one_pass(req_epoch):
    """Everything one tap does; the last status line it writes is the answer."""
    if cull_running():
        status('STOPPED %s: a cull is already running -- tap again when it is done' % hhmm()); return
    wait = GAP_S - (time.time() - os.path.getmtime(CULL_LOG)) if os.path.exists(CULL_LOG) else 0
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
    pv, hv = data_versions()
    if pv is None:
        status('STOPPED %s: could not read the data store versions -- ask Claude' % hhmm()); return
    if pv > hv and not data(['pull']):
        status('STOPPED %s: pulling the newer data failed -- ask Claude' % hhmm()); return
    if pv < hv and not data(['push', '--group', 'inventory']):
        status('STOPPED %s: pushing the data first failed -- ask Claude' % hhmm()); return
    start = time.time()
    status('running since %s' % hhmm(start))
    log('cull for the tap at %s (pid %s, game up %ss)' % (hhmm(req_epoch), pid, up))
    with open(CULL_LOG, 'w', encoding='utf-8', errors='replace') as f:
        rc = subprocess.run([sys.executable, 'full_audit.py'], cwd=HERE, stdout=f, stderr=subprocess.STDOUT).returncode
    text = open(CULL_LOG, encoding='utf-8', errors='replace').read()
    kind, line = parse_cull(text, rc)
    rep = text.split('=== REPORT ===', 1)
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('cull from the phone button, tap %s, ran %s-%s, rc %s\n' % (hhmm(req_epoch), hhmm(start), hhmm(), rc))
        f.write('=== REPORT ===' + '\n'.join(l for l in rep[1].splitlines() if not l.startswith('[')) if len(rep) > 1 else '')
    pushed = data(['push', '--group', 'inventory'])          # ALWAYS after a phone pass, even when the gate failed
    status('%s %s: %s%s' % (kind, hhmm(), line, '' if pushed else ' (data push failed -- ask Claude)'))


def main():
    try:
        mutex = socket.socket(); mutex.bind(('127.0.0.1', MUTEX_PORT))
    except OSError:
        print('cull_button: another listener is already running'); return 1
    st = json.load(open(STATE)) if os.path.exists(STATE) else {'last_epoch': 0}
    log('listener up (ADB %s, pid %s)' % (ADB, os.getpid()))
    if connected():
        status('ready %s: tap CULL NOW to run one cull on the PC' % hhmm())
    while True:
        try:
            if connected():
                now = int(adb('date +%s') or 0) or int(time.time())
                ep = parse_req(adb('cat %s 2>/dev/null' % REQ))
                if ep and ep > st['last_epoch']:
                    st['last_epoch'] = ep
                    json.dump(st, open(STATE, 'w'))             # handled BEFORE the pass: one tap can never run twice
                    if now - ep > MAX_AGE_S:
                        status('STOPPED %s: that tap was from %s, too long ago -- tap again' % (hhmm(), hhmm(ep)))
                    else:
                        one_pass(ep)
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
    ok = ('[ 94.1s] bag 5850 (5849 Pokemon + 1 eggs in incubators)/5850 (free 0) | PILE 182\n'
          '[121.4s] DONE -- 182 tagged for Transfer\n=== REPORT ===\n**Release the 182**\n')
    assert parse_cull(ok, 0) == ('done', 'release 182 in the Transfer tag | bag 5850/5850 (0 free)')
    assert parse_cull(ok, 1)[0] == 'STOPPED'
    assert parse_cull('[ 41.7s] AUDIT GATE FAILED -- SYNC NOT RUN\n', 1) == ('STOPPED', 'an audit failed (nothing was tagged) -- ask Claude')
    assert parse_cull('GAME MASTER REFRESH STOPPED THE PASS (rc 5)\n', 5)[1].startswith('a new game master')
    print('cull_button selftest: OK')
    return 0


if __name__ == '__main__':
    args = sys.argv[1:]
    if args == ['--selftest']:
        sys.exit(selftest())
    if args:
        print(__doc__); sys.exit(2)
    sys.exit(main())

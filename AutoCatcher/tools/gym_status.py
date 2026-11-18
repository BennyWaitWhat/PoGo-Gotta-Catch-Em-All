"""The Gym Battle switch's status line: where the gym runner stands, in plain words, from its own log.

The AutoCatcher app shows ONE line, /data/local/tmp/pogo_gym_status.txt ("HH:MM:SS text", at most ~90 characters). On the
phone, run_gym.sh (the switch's supervisor) writes it; while a runner is alive the text comes from here:

    python gym_status.py LOG          one line, no time in front:  watching for a gym you open | 14/20 in gyms
                                      battling Big Ben: 2 of 4 left / Gyarados 3643 placed at Big Ben (15/20 in gyms) /
                                      hands off Big Ben: a raid is on it / lost the game connection -- ...
    python gym_status.py --why LOG    why a runner that ENDED by itself ended (empty when its log does not say)
    python gym_status.py --selftest   offline check (CI runs it); also reads the real runner logs in gym_state/logs, if any

It reads the last 2,000 lines of the log (gym_run.py's say() lines: "HH:MM:SS text"). A result (placed, joined, emptied)
stays up for 90 s, then the wait shows again. Only the standard library: the supervisor starts it with `python -S`.
"""
import os
import re
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, 'gym_state', 'logs')
TEXT_MAX = 81               # the status text; with "HH:MM:SS " in front the line stays at 90 characters


def clean(text, limit=TEXT_MAX):
    """One status text a shell can take inside quotes: plain ASCII on one line, no quote, dollar, backtick or backslash,
    at most `limit` characters (an accent is dropped with its letter kept; another script is left out; an apostrophe goes
    without a gap: Paul's -> Pauls)."""
    s = unicodedata.normalize('NFKD', str(text)).replace("'", '').replace('\u2019', '')
    s = ''.join(c if (32 <= ord(c) < 127 and c not in '"$`\\') else ' ' for c in s if not unicodedata.combining(c))
    s = re.sub(r'\s+', ' ', s).strip()
    return s if len(s) <= limit else s[:limit - 3].rstrip() + '...'


def tail(path, n=2000, size=256 * 1024):
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - size))
            return f.read().decode('utf-8', 'replace').splitlines()[-n:]
    except OSError:
        return []


TS = re.compile(r'^(\d\d):(\d\d):(\d\d) ?(.*)$')
GID = r'([0-9a-f]{8})(?: \((.+?)\))?'
ANY = 'the gym you opened'      # a gym whose name the log has not said yet
WHY = ((r'you told the runner to skip', 'you told it to skip this gym'), (r'you started a battle', 'your own battle stays yours'),
       (r'a raid', 'a raid is on it'), (r'it is out of reach', 'too far away -- come closer'),
       (r'one of yours is already in', 'one of yours is already in it'), (r'all (\d+) of your gym slots', r'all \1 of your gym slots are in use'),
       (r'the game refused your Pokemon', 'it refused your Pokemon within the hour'),
       (r'(a|your) team.s deploy lockout', 'a deploy lockout is running -- it goes in when that ends'), (r'it is full', 'it is full'),
       (r'it is under attack', 'under attack -- it goes in when the attack is over'), (r'auto-place is off', 'auto-place is off'),
       (r'the gym screen has not said|the game.s map (has no record|does not show)', 'reading the gym'))
RESULTS = ((r'you placed a Pokemon \((\d+)/(\d+) in gyms now', 'your Pokemon placed at {g} ({0}/{1} in gyms)'),
           (r'you placed (.+?) (?:right after the lockout )?\((\d+)/(\d+) in gyms now', '{0} placed at {g} ({1}/{2} in gyms)'),
           (r'you joined [0-9a-f]{8}.*? with (.+?) (?:on a retry )?\((\d+)/(\d+) in gyms now', '{0} joined {g} ({1}/{2} in gyms)'),
           (r'SLIPPED IN: (.+?) is in ', '{0} slipped into {g}'),
           (r'EMPTY -- you already have (\d+) Pokemon in gyms \(cap (\d+)\)', '{g} emptied -- nothing placed: {0}/{1} gym slots in use'),
           (r'the red gym did not take it \((.+?)\)', '{g} did not take your Pokemon ({0})'),
           (r'another red player filled it first', 'another red player filled {g} first'),
           (r'could not join it', 'could not join {g}'), (r'could not join [0-9a-f]{8}', 'could not join {g}'),
           (r'a raid appeared on it', 'a raid appeared on {g} -- left it'),
           (r'skipping [0-9a-f]{8}.* for an hour \((.+?)\)', 'your Pokemon cannot go into {g} ({0})'),
           (r'no placement seen', '{g} is empty -- nothing was placed'), (r'gave up on [0-9a-f]{8}', 'gave up on {g}'))


def scan(lines):
    """The runner's log lines, oldest first -> the state they add up to (phase: boot / idle / take / hands / lost / nofix /
    stopping / ended)."""
    st = {'phase': 'boot', 'gym': None, 'kind': None, 'n0': None, 'n': None, 'note': None, 'res': None, 'res_t': None,
          'why': None, 'in': None, 'end': None, 'noroot': False}
    names = {}

    def label(gid, name=None):
        if name and not re.fullmatch(r'team \d', name):
            nm = clean(name, 30)
            if len(re.sub(r'[^A-Za-z0-9]', '', nm)) >= 3:
                names[gid] = nm
        return names.get(gid)

    def result(text, t):
        st['res'], st['res_t'], st['note'] = text, t, None

    for ln in lines:
        m = TS.match(ln.rstrip())
        if not m:
            if ln.startswith('Traceback (most recent call last)'):
                st['phase'], st['end'] = 'ended', 'the gym runner crashed -- ask Claude'
            continue
        t, msg = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)), m.group(4).strip()
        g = lambda: st['gym'] or ANY
        x = re.search(r'your Pokemon in gyms right now: (\d+)/(\d+)', msg) or re.search(r'\((\d+)/(\d+) in gyms now', msg)
        if x:
            st['in'] = '%s/%s' % x.groups()
        if msg.startswith('!! phone root shell'):            # on_phone.py: the phone gave the runner no root shell (Magisk)
            st['noroot'] = True
            continue
        if msg.startswith('attached pid'):
            st['noroot'] = False
        if msg.startswith('ON-OPEN mode ('):                 # the process just started: the attach comes next
            st.update(phase='boot', res=None, note=None)
            continue
        if re.search(r'COMMAND stop|stopped cleanly', msg):   # (first: a stop that came in while the game was away says both)
            st['phase'] = 'stopping'
            continue
        if re.search(r'lost the game connection|session failed', msg):
            st.update(phase='lost', note=None)
            continue
        if 'a party screen stayed open over a battle' in msg and msg.startswith('STOP'):
            st.update(phase='ended', end='the runner stopped itself: a party screen stayed open over a battle')
            continue
        if 'could not be read live -- not running' in msg:
            st.update(phase='ended', end='the runner cannot read this game version -- ask Claude')
            continue
        if 'minutes are up' in msg and 'ON-OPEN' in msg:
            st.update(phase='ended', end='the run reached its time limit -- starting again')
            continue
        if 'no GPS fix from the joystick' in msg:
            st['phase'] = 'nofix'
            continue
        if st['phase'] in ('boot', 'lost', 'nofix', 'ended'):   # any other line: the runner is attached and reading the game
            st['phase'] = 'idle'
        x = re.search(r'ON-OPEN: you have ' + GID + r' open(?: \(team \d\))? -- (.*)$', msg)
        if x:
            gid, rest = x.group(1), x.group(3)
            st['gym'] = label(gid, x.group(2))
            if rest.startswith(('hands off: ', 'not acting yet: ')):
                why = rest.split(': ', 1)[1]
                st.update(phase='hands', why=next((re.sub(p, r, re.search(p, why).group(0)) for p, r in WHY if re.search(p, why)),
                                                  why.split(' -- ')[0]))
            else:
                st.update(phase='take', n0=None, n=None, note=None, res=None, gid=gid,
                          kind='place' if 'EMPTY' in rest else 'join' if 'joining' in rest else 'drill')
            continue
        if msg.startswith('ON-OPEN: watching for'):
            st.update(phase='idle', note=None)
            continue
        if msg.startswith('ON-OPEN: done with'):
            if st['phase'] == 'take' and not st['res']:
                result('done with %s' % g(), t)
            st.update(phase='idle', note=None)
            continue
        x = re.search(r'ON-OPEN: team (\d) got into|team (\d) took it first', msg)
        if x:
            st.update(phase='take', kind='drill', n0=None, n=None, res=None, note='another team got in first -- battling it again')
            continue
        if re.search(r'ON-OPEN: .*(letting it go|the hold is off)', msg):
            result('you moved away from %s -- the runner let it go' % g(), t)
            continue
        if 'party screen: YOU pressed Battle' in msg and st['phase'] != 'take':
            st.update(phase='hands', why='your own battle stays yours')
            continue
        x = re.search(r'(?:WATCH|engaging) ' + GID + r'(?::| \(team| at)', msg)
        if x:                                                # a takeover's own lines (its first line may have scrolled away)
            if st['phase'] != 'take':
                st.update(phase='take', kind='drill', n0=None, n=None, note=None, res=None)
            st['gym'] = label(x.group(1), x.group(2)) or st['gym']
            w = re.search(r': (\d+) defender\(s\)', msg)
            if w:
                st['n'] = int(w.group(1))
                st['n0'] = max(st['n0'] or 0, st['n'])
                if st['n'] and st['note'] in ('empty -- placing', None):
                    st['note'] = None
            continue
        if st['phase'] != 'take':
            continue
        x = re.search(r'waiting out the cooldown at .* until (\d\d:\d\d:\d\d)', msg)
        if x:
            st['note'] = 'server cooldown -- next try %s' % x.group(1)
        elif 'COOLDOWN over' in msg or 'round start' in msg:
            st['note'] = None
        elif 'COOLDOWN sign' in msg:
            st['note'] = 'server cooldown -- asking again'
        elif re.search(r'deploy lockout \(', msg) or 'waiting out the deploy lockout' in msg:
            st['note'] = 'waiting out a deploy lockout'
        elif re.search(r'error 29 .*at [0-9a-f]{8}', msg):
            st['note'] = 'the battle was refused (29) -- trying again'
        elif 'you have another gym open' in msg:
            st['note'] = 'waiting: you have another gym open'
        elif 'you pressed Battle at' in msg:
            st['note'] = 'your own battle -- the drill goes on after it'
        elif re.search(r'gym [0-9a-f]{8}.* now team 0$', msg) and not st['res']:
            st['note'] = 'empty -- placing'
        elif 'Deploy is open, leave a Pokemon' in msg:
            st['note'] = 'Deploy is open -- leave a Pokemon'
        else:
            for pat, text in RESULTS:
                x = re.search(pat, msg)
                if x:
                    if not (st['res'] and ('placed at' in st['res'] or 'joined' in st['res'] or 'slipped' in st['res'])):
                        result(text.format(*x.groups(), g=g()), t)     # (a placement is never overwritten by a later, lesser line)
                    break
    return st


def status_from_log(lines, now_s=None):
    """The runner's log tail -> where things stand, in plain words, with no time in front. now_s = seconds since midnight
    on the log's own clock: a result stays up for 90 s, then the wait shows again."""
    st = scan(lines)
    ph, gym = st['phase'], st['gym'] or ANY
    if st['noroot'] and ph in ('boot', 'lost', 'nofix', 'idle'):
        return 'no root shell on the phone (Magisk) -- ask Claude'
    if ph == 'boot':
        return 'starting: attaching to the game'
    if ph == 'lost':
        return 'lost the game connection -- attaching again when the game is up'
    if ph == 'nofix':
        return 'no GPS fix from the joystick -- waiting for one'
    if ph == 'stopping':
        return 'stopping'
    if ph == 'ended':
        return st['end']
    if ph == 'hands':
        return 'hands off %s: %s' % (gym, st['why'])
    if ph == 'take':
        if st['res']:
            return st['res']
        if st['note']:
            return '%s: %s' % (gym, st['note'])
        if st['kind'] == 'place':
            return 'placing a Gyarados at %s' % gym
        if st['kind'] == 'join':
            return 'joining %s' % gym
        return 'battling %s' % gym + (': %d of %d left' % (st['n'], st['n0']) if st['n'] and st['n0'] else '')
    if st['res'] and st['res_t'] is not None and (now_s is None or (now_s - st['res_t']) % 86400 < 90):
        return st['res']
    return 'watching for a gym you open' + (' | %s in gyms' % st['in'] if st['in'] else '')


def end_reason(lines):
    """Why a runner that ended by itself ended, when its log says so (a crash, a game version it cannot read) -- else ''."""
    st = scan(lines)
    return st['end'] if st['phase'] == 'ended' and st['end'] else ''


# ------------------------------------------------------------------------------------------------ offline self-check
def selftest():
    assert clean('a  "b"\n$(rm -rf /) `x` \\ it\'s') == 'a b (rm -rf /) x its' and clean('St. Paul\u2019s Cathedral') == 'St. Pauls Cathedral'
    assert clean('Caf\u00e9 \u5927\u962a \u57ce Gym') == 'Cafe Gym' and len(clean('x' * 200)) == TEXT_MAX and clean('x' * 200).endswith('...')
    assert len('00:00:00 ' + clean('y' * 500)) == 90
    L = ['12:00:01   ON-OPEN mode (the AutoCatcher app\'s Gym Battle switch): the runner picks no gym ...']
    assert status_from_log([]) == status_from_log(L) == 'starting: attaching to the game' and end_reason(L) == ''
    L += ['12:00:07     state: MapExploreState', '12:00:08 attached pid 1392: 18 gyms on the game\'s map directory; live fort range 80 m -> engage inside 70 m',
          '12:00:09   your Pokemon in gyms right now: 14/20; shiny Gyarados ready to place (CP): 3643, 3640 (live bag)',
          '12:00:10   ON-OPEN: watching for a gym you open']
    assert status_from_log(L) == 'watching for a gym you open | 14/20 in gyms'
    H = L + ['12:01:00   ON-OPEN: you have 4c0a5889 open -- hands off: it is under attack and the server refuses a join during a battle -- the runner joins ...']
    assert status_from_log(H) == 'hands off the gym you opened: under attack -- it goes in when the attack is over'
    assert status_from_log(H + ['12:01:30   ON-OPEN: watching for a gym you open']) == 'watching for a gym you open | 14/20 in gyms'
    R = L + ['12:01:00   ON-OPEN: you have 4c0a5889 (Big Ben) open -- hands off: a raid (or its egg) is on it -- no gym battle, nothing placed']
    assert status_from_log(R) == 'hands off Big Ben: a raid is on it'
    D = L + ['12:02:00   ON-OPEN: you have ece8e13e open (team 1) -- taking it over: drilling it until it is empty, then a shiny Gyarados in',
             '12:02:00 engaging ece8e13e (team 1) at 23 m']
    assert status_from_log(D) == 'battling the gym you opened'
    D += ['12:02:01     WATCH ece8e13e (Big Ben): 4 defender(s), 9306 CP, server says NOT in battle [client: GymApproachState]', '12:02:05     round start 1',
          '12:02:20     WATCH ece8e13e (Big Ben): 3 defender(s), 7210 CP, server says IN BATTLE [client: battle]',
          '12:02:41     WATCH ece8e13e (Big Ben): 2 defender(s), 5210 CP, server says NOT in battle [client: battle]']
    assert status_from_log(D) == 'battling Big Ben: 2 of 4 left'
    C = D + ['12:02:50   COOLDOWN sign #1 (battle refused: error 29, 11 s after a 755 m jump) -- asking the server again at 12:02:58 (8 s crash guard)',
             '12:02:52   waiting out the cooldown at ece8e13e (Big Ben) until 12:02:58 -- then one check']
    assert status_from_log(C) == 'Big Ben: server cooldown -- next try 12:02:58'
    assert status_from_log(C + ['12:03:00     round start 1']) == 'battling Big Ben: 2 of 4 left'
    D += ['12:03:30     WATCH ece8e13e (Big Ben): 0 defender(s), 0 CP, server says NOT in battle [client: GymApproachState]']
    assert status_from_log(D) == 'battling Big Ben', 'no "0 of 4 left": the next line says it is empty'
    D += ['12:03:31   gym ece8e13e (Big Ben) now team 0']
    assert status_from_log(D) == 'Big Ben: empty -- placing'
    D += ['12:03:31     placing your shiny Gyarados (CP 3643) the instant the gym emptied -- the game\'s own deploy request',
          '12:03:32     confirmed: Gyarados 3643 is in ece8e13e (Big Ben) (317 ms after the request)',
          '12:03:32   you placed Gyarados 3643 (15/20 in gyms now) -- next gym']
    assert status_from_log(D) == 'Gyarados 3643 placed at Big Ben (15/20 in gyms)'
    D += ['12:03:33   GYM REPORT ece8e13e (Big Ben): arrival -> first battle 5 s | 4 battles, 7 rounds won in 84 s',
          '12:03:34   ON-OPEN: done with ece8e13e (Big Ben) -- watching for the next gym you open; the joystick gets nothing more from the runner']
    assert status_from_log(D, 12 * 3600 + 4 * 60) == 'Gyarados 3643 placed at Big Ben (15/20 in gyms)', 'a result stays up for 90 s'
    assert status_from_log(D, 12 * 3600 + 6 * 60) == 'watching for a gym you open | 15/20 in gyms'
    mid = [x for x in D if 'ON-OPEN: you have' not in x and 'engaging' not in x][:-5]
    assert status_from_log(mid) == 'Big Ben: empty -- placing', 'a drill whose first lines scrolled out of the tail is still read as a drill'
    for cut in range(len(D) + 1):                            # a window that starts anywhere never throws
        assert status_from_log(D[cut:], 12 * 3600 + 200)
    cap = L + ['12:05:00   ON-OPEN: you have 5fe2d063 (Clock Tower) open (team 3) -- taking it over: drilling it until it is empty; all 20 of your gym slots are in use: it gets emptied, nothing can be placed',
               '12:05:40   gym 5fe2d063 (Clock Tower) now team 0',
               '12:05:40   EMPTY -- you already have 20 Pokemon in gyms (cap 20): moving on; nothing of yours can go in (--on-open fills no gym by itself: open it again when one is home)']
    assert status_from_log(cap) == 'Clock Tower emptied -- nothing placed: 20/20 gym slots in use'
    J = L + ['12:06:00   ON-OPEN: you have 176bc7f2 (Courtyard Fountain Guardian) open (team 2) -- taking it over: your team\'s gym with a free slot, joining it (no battle)']
    assert status_from_log(J) == 'joining Courtyard Fountain Guardian'
    assert status_from_log(J + ['12:06:01   you placed Gyarados 3640 (16/20 in gyms now) -- next gym']) == 'Gyarados 3640 placed at Courtyard Fountain Guardian (16/20 in gyms)'
    E = L + ['12:07:00   ON-OPEN: you have 95ea321a open (team 0) -- taking it over: it is EMPTY, a shiny Gyarados goes in now']
    assert status_from_log(E) == 'placing a Gyarados at the gym you opened'
    assert status_from_log(E + ['12:07:02   you placed Gyarados 3640 (16/20 in gyms now) -- next gym']) == 'Gyarados 3640 placed at the gym you opened (16/20 in gyms)'
    assert status_from_log(L + ['12:08:00 lost the game connection (Detached: game connection lost) -- re-attaching in 3 s']).startswith('lost the game connection')
    assert status_from_log(L + ['12:08:00 session failed (RuntimeError: PoGo never became attach-safe in 300s (no pid yet)) -- retrying in 10 s']).startswith('lost the game connection')
    assert status_from_log(L + ['12:08:00 lost the game connection (x) -- re-attaching in 3 s', '12:09:10     state: MapExploreState']).startswith('watching')
    assert status_from_log(L + ['12:09:00   COMMAND stop: no battle in progress -- stopped cleanly; the tapper unloads and the session detaches now']) == 'stopping'
    for s in ('it came in before the runner ever attached -- not attaching; stopped', 'it came in while the runner waited for the game -- not attaching again; stopped',
              'it was asked before / while the game connection was down -- not attaching again; stopped'):
        assert status_from_log(L + ['12:08:00 lost the game connection (x) -- re-attaching in 3 s', '12:09:00   COMMAND stop: ' + s]) == 'stopping', s
    bad = ['12:00:01 attached pid 5, but these could not be read live -- not running: [\'x\']']
    assert status_from_log(bad) == end_reason(bad) == 'the runner cannot read this game version -- ask Claude'
    tb = L + ['Traceback (most recent call last):', '  File "gym_run.py", line 1, in <module>', 'ModuleNotFoundError: No module named \'frida\'']
    assert status_from_log(tb) == end_reason(tb) == 'the gym runner crashed -- ask Claude'
    nr = L[:1] + ['12:00:02   !! phone root shell: no answer to a device command (OSError: the shell closed) -- device commands return nothing until it is back']
    assert status_from_log(nr) == 'no root shell on the phone (Magisk) -- ask Claude'
    assert status_from_log(nr + ['12:05:02 session failed (RuntimeError: PoGo never became attach-safe in 300s (no pid yet)) -- retrying in 10 s']) \
        == 'no root shell on the phone (Magisk) -- ask Claude'
    assert status_from_log(nr + L[2:]) == 'watching for a gym you open | 14/20 in gyms', 'an attach after it clears the note'
    for txt in (status_from_log(D), status_from_log(cap), status_from_log(H), status_from_log(C), status_from_log(nr)):
        assert txt == clean(txt) and len(txt) <= TEXT_MAX, txt
    # --- real runner logs, when this machine has some: every prefix of every tail gives one clean line (never a throw)
    n_real = 0
    if os.path.isdir(LOGS):
        for name in sorted(os.listdir(LOGS))[-6:]:
            lines = tail(os.path.join(LOGS, name))
            for cut in range(0, len(lines) + 1, max(1, len(lines) // 150)):
                txt = clean(status_from_log(lines[:cut], 3 * 3600))
                assert txt and len(txt) <= TEXT_MAX and '\n' not in txt, (name, cut, txt)
                assert end_reason(lines[:cut]) is not None
                n_real += 1
    print('gym_status selftest: OK (%d status lines built from real runner logs on this machine)' % n_real)
    return 0


def main(argv):
    if argv == ['--selftest']:
        return selftest()
    if len(argv) == 2 and argv[0] == '--why':
        print(clean(end_reason(tail(argv[1]))))
        return 0
    if len(argv) != 1 or argv[0].startswith('-'):
        print(__doc__)
        return 2
    t = time.localtime()
    print(clean(status_from_log(tail(argv[0]), t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

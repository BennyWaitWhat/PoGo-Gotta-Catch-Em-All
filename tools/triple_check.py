#!/usr/bin/env python3
"""triple_check.py -- ONE command that proves the repo, the code, the secrets, the docs and the phone data store are in
order. Run it before you tell Benny anything is "done".

Benny, 2026-09-29: "Once done, triple check everything. Same for future posterity."

  python tools/triple_check.py             # repo + code + secrets (all history) + docs + data store (if the phone answers)
  python tools/triple_check.py --gate      # ... + the 11-audit gate (needs `python tools/pogo_data.py pull` first)
  python tools/triple_check.py --fresh     # all of it on a FRESH clone of origin/main + a data pull = what GitHub really holds

Read-only. It never touches the game (no Frida); the phone is only read (`sha256sum`, `cat`) over adb.
Exit 0 = no FAIL (WARNs are listed and worth reading); exit 1 = at least one FAIL.
"""
import argparse, os, re, shutil, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import pogo_data  # noqa: E402  (the data-store helpers: manifest, files_for, tracked, phone_meta)

PY = sys.executable
SECRET = re.compile(rb'AIza[0-9A-Za-z_\-]{30,}|tskey-(?:auth|client|api)-[0-9A-Za-z]{8,}|gh[pousr]_[0-9A-Za-z]{30,}'
                    rb'|xox[baprs]-[0-9A-Za-z-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}'
                    rb'|eyJ[A-Za-z0-9_\-]{15,}\.eyJ[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{10,}'
                    rb'|[A-Za-z0-9._%+\-]+@(?:gmail|bellsouth|yahoo|outlook|hotmail|icloud)\.[a-z]+')
SELFTESTS = [['tools/pogo_data.py', 'selftest'], ['pogo_extract/walk_tripwires.py', '--selftest'],
             ['pogo_extract/cull_report.py', '--selftest'], ['pogo_extract/independent_law.py'],
             ['pogo_extract/system/scripts/check_constant_drift.py']]
results = []


def say(level, area, msg):
    results.append(level)
    print('%-4s  %-9s %s' % (level, area, msg), flush=True)


def run(cmd, cwd=ROOT, timeout=900):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout)


def out(cmd, cwd=ROOT):
    return run(cmd, cwd).stdout.decode('utf-8', 'replace').strip()


# ---------------------------------------------------------------------------------------------------------------- repo
def check_repo():
    fetched = run(['git', 'fetch', '-q', 'origin']).returncode == 0
    dirty = [l for l in out(['git', 'status', '--porcelain']).splitlines() if l.strip()]
    if dirty:
        say('FAIL', 'repo', '%d uncommitted change(s) -- commit or discard them first: %s'
            % (len(dirty), '; '.join(l.strip() for l in dirty[:5])))
    else:
        say('PASS', 'repo', 'working tree clean')
    head = out(['git', 'rev-parse', '--short', 'HEAD'])
    main = out(['git', 'rev-parse', '--short', 'origin/main'])
    ahead = out(['git', 'rev-list', '--count', 'origin/main..HEAD']) or '?'
    behind = out(['git', 'rev-list', '--count', 'HEAD..origin/main']) or '?'
    if not fetched:
        say('WARN', 'repo', 'could not fetch origin -- ahead/behind are from the last fetch')
    if ahead == '0' and behind == '0':
        say('PASS', 'repo', 'HEAD %s == origin/main' % head)
    else:
        say('WARN', 'repo', 'HEAD %s vs origin/main %s: %s ahead, %s behind -- push/merge your branch, or pull'
            % (head, main, ahead, behind))
    extra = [b for b in out(['git', 'branch', '-r']).split() if b.startswith('origin/') and b not in ('origin/main', 'origin/HEAD')]
    if extra:
        say('WARN', 'repo', 'remote branches besides main (merged ones should be deleted): %s' % ', '.join(extra[:8]))
    if shutil.which('gh'):
        r = run(['gh', 'pr', 'list', '--state', 'open', '--json', 'number,title'])
        if r.returncode == 0:
            prs = r.stdout.decode().strip()
            if prs not in ('', '[]'):
                say('WARN', 'repo', 'open pull requests: %s' % prs[:300])
            else:
                say('PASS', 'repo', 'no open pull requests')


# ---------------------------------------------------------------------------------------------------------------- code
def check_code():
    files = [f for f in out(['git', 'ls-files', '*.py']).splitlines() if f]
    bad = []
    for f in files:
        try:
            compile(open(os.path.join(ROOT, f), 'rb').read(), f, 'exec')
        except (SyntaxError, ValueError) as e:
            bad.append('%s: %s' % (f, e))
    say('FAIL' if bad else 'PASS', 'code', '%d Python files compile%s' % (len(files), ('; broken: ' + '; '.join(bad[:3])) if bad else ''))
    bash = shutil.which('bash')
    if bash:
        sh = [f for f in out(['git', 'ls-files', '*.sh']).splitlines() if f]
        bad = [f for f in sh if run([bash, '-n', f]).returncode != 0]
        say('FAIL' if bad else 'PASS', 'code', '%d shell scripts parse%s' % (len(sh), ('; broken: ' + ', '.join(bad[:5])) if bad else ''))
    for t in SELFTESTS:
        r = run([PY] + t)
        say('PASS' if r.returncode == 0 else 'FAIL', 'code', '%s -> rc %d' % (' '.join(t), r.returncode))
    r = run([PY, 'full_audit.py', '--not-a-flag'], cwd=os.path.join(ROOT, 'pogo_extract'))
    say('PASS' if r.returncode == 2 else 'FAIL', 'guards', 'full_audit.py refuses an unknown flag (rc %d, want 2)' % r.returncode)


# ---------------------------------------------------------------------------------------------------------------- secrets
def check_secrets():
    paths = {}
    for line in out(['git', 'rev-list', '--objects', '--all']).splitlines():
        sha, _, path = line.partition(' ')
        if path:
            paths.setdefault(sha, path)
    p = subprocess.run(['git', 'cat-file', '--batch'], cwd=ROOT, input=('\n'.join(paths) + '\n').encode(), capture_output=True)
    data, i, blobs, hits, biggest = p.stdout, 0, 0, [], (0, '')
    while i < len(data):
        nl = data.index(b'\n', i)
        hdr, i = data[i:nl].split(), nl + 1
        if len(hdr) != 3:
            continue
        size = int(hdr[2])
        body, i = data[i:i + size], i + size + 1
        if hdr[1] != b'blob':
            continue
        blobs += 1
        path = paths.get(hdr[0].decode(), '?')
        biggest = max(biggest, (size, path))
        m = SECRET.search(body)
        if m and not path.endswith(('.github/workflows/ci.yml', 'tools/triple_check.py')):
            hits.append('%s (%s...)' % (path, m.group(0)[:12].decode('ascii', 'replace')))
    say('FAIL' if hits else 'PASS', 'secrets', '%d blobs in ALL history, %d key/token/email hits%s'
        % (blobs, len(hits), (': ' + '; '.join(hits[:5])) if hits else ''))
    say('PASS' if biggest[0] < 20e6 else 'WARN', 'secrets', 'largest blob ever committed: %.2f MB (%s)' % (biggest[0] / 1e6, biggest[1]))


# ---------------------------------------------------------------------------------------------------------------- docs
def check_docs():
    tracked = set(pogo_data.tracked(ROOT))
    dirs = set()
    for p in tracked:
        d = os.path.dirname(p)
        while d and d not in dirs:
            dirs.add(d)
            d = os.path.dirname(d)
    legacy = lambda p: p.startswith('pogo_extract/') and p not in ('pogo_extract/CLAUDE.md', 'pogo_extract/README.md') \
        and p.count('/') == 1
    broken, old, n = [], 0, 0
    for p in sorted(x for x in tracked if x.endswith('.md')):
        for m in re.finditer(r'\]\(([^)\s]+)\)', open(os.path.join(ROOT, p), encoding='utf-8', errors='replace').read()):
            t = m.group(1)
            if re.match(r'^(https?:|mailto:|#)', t):
                continue
            n += 1
            full = os.path.normpath(os.path.join(os.path.dirname(p), t.split('#')[0].replace('%20', ' '))).replace(os.sep, '/')
            if full not in tracked and full.rstrip('/') not in dirs:
                if legacy(p):
                    old += 1
                else:
                    broken.append('%s -> %s' % (p, t))
    say('FAIL' if broken else 'PASS', 'docs', '%d relative links, %d broken%s' % (n, len(broken), (': ' + '; '.join(broken[:5])) if broken else ''))
    if old:
        say('WARN', 'docs', '%d links in old pogo_extract research notes point at data kept out of git (expected)' % old)


# ---------------------------------------------------------------------------------------------------------------- data store
def check_data():
    dev = pogo_data.DEV
    if not shutil.which('adb') or out(['adb', '-s', dev, 'get-state']) != 'device':
        say('WARN', 'data', 'phone not reachable at %s -- data store NOT checked' % dev)
        return
    metas, held, groups = pogo_data.phone_meta(), pogo_data._held(), pogo_data.manifest()
    sums = out(['adb', '-s', dev, 'shell', 'cd %s && sha256sum *.tar.gz 2>/dev/null; ls -a | grep -c "\\.tmp$"' % pogo_data.PHONE_DIR]).splitlines()
    have = {l.split()[1][:-7]: l.split()[0] for l in sums if l.endswith('.tar.gz')}
    tmp = sums[-1].strip() if sums else '0'
    if tmp not in ('0', ''):
        say('WARN', 'data', '%s half-uploaded .tmp file(s) on the phone (an interrupted push)' % tmp)
    skip = pogo_data.tracked(ROOT)
    for g in sorted(groups):
        m = metas.get(g)
        if not m:
            say('WARN', 'data', '%-14s not on the phone yet' % g)
            continue
        ok = have.get(g) == m['sha256']
        say('PASS' if ok else 'FAIL', 'data', '%-14s v%s (%s by %s) sha256 %s'
            % (g, m['version'], m['at'], m.get('by'), 'matches its meta' if ok else 'DOES NOT MATCH its meta'))
        if held.get(g) not in (None, m['version']):
            say('WARN', 'data', '%-14s this checkout holds v%s, the phone v%s -- pull before working' % (g, held.get(g), m['version']))
        t0 = time.mktime(time.strptime(m['at'], '%Y-%m-%d %H:%M:%S'))
        newer = [f for f in pogo_data.files_for(g, groups, skip=skip) if os.path.getmtime(os.path.join(ROOT, f)) > t0 + 2]
        if newer and held.get(g) is not None:
            say('WARN', 'data', '%-14s %d local file(s) changed after the last push -- the owner should push: %s'
                % (g, len(newer), ', '.join(newer[:4])))


# ---------------------------------------------------------------------------------------------------------------- gate
def check_gate():
    db = os.path.join(ROOT, 'pogo_extract', 'pokemon.db')
    if not os.path.exists(db) or os.path.getsize(db) < 1_000_000:
        say('FAIL', 'gate', 'no pokemon.db here -- run `python tools/pogo_data.py pull` first')
        return
    r = run([PY, 'full_audit.py', '--audits-only'], cwd=os.path.join(ROOT, 'pogo_extract'), timeout=1800)
    last = [l for l in r.stdout.decode('utf-8', 'replace').splitlines() if l.strip()][-1:] or ['(no output)']
    say('PASS' if r.returncode == 0 else 'FAIL', 'gate', '11 audits rc %d: %s' % (r.returncode, last[0][:110]))


def fresh():
    url = out(['git', 'remote', 'get-url', 'origin'])
    with tempfile.TemporaryDirectory() as td:
        clone = os.path.join(td, 'repo')
        if run(['git', 'clone', '-q', url, clone]).returncode != 0:
            print('FAIL  fresh     could not clone %s' % url)
            return 1
        print('fresh clone of origin/main at %s' % out(['git', 'rev-parse', '--short', 'HEAD'], cwd=clone), flush=True)
        pull = run([PY, 'tools/pogo_data.py', 'pull'], cwd=clone, timeout=3600)
        print(pull.stdout.decode('utf-8', 'replace').strip(), flush=True)
        return subprocess.run([PY, 'tools/triple_check.py', '--gate'], cwd=clone).returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--gate', action='store_true', help='also run the 11-audit gate (needs a data pull first)')
    ap.add_argument('--fresh', action='store_true', help='run everything on a fresh clone of origin/main + a data pull')
    a = ap.parse_args()
    if a.fresh:
        return fresh()
    check_repo(); check_code(); check_secrets(); check_docs(); check_data()
    if a.gate:
        check_gate()
    fails, warns = results.count('FAIL'), results.count('WARN')
    print('\n%s -- %d PASS, %d WARN, %d FAIL' % ('ALL CLEAR' if not fails else 'NOT DONE', results.count('PASS'), warns, fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())

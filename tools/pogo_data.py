#!/usr/bin/env python3
"""pogo_data.py -- the PoGo DATA lives on the PHONE, not in git.

Why: cloud sessions start on a fresh VM, can push only their own git branch, and git LFS does not work there; the game
data (pokemon.db, snapshots, walk outputs, per-account sets, catcher studies, gym state) changes on every run, so git
would bloat by gigabytes. Every session that does phone work reaches the phone anyway, so the phone keeps the one copy:

    /data/local/tmp/pogo_data/<group>.tar.gz   one tarball per group (data_manifest.txt: inventory, catcher, gym, *-cold)
    /data/local/tmp/pogo_data/<group>.json     {"version", "at", "by", "sha256", "bytes", "files"}

Each group has its OWN version, so the Inventory, AutoCatcher and Gym sessions never block each other.

  python tools/pogo_data.py status                 # every group: phone version vs what this checkout holds
  python tools/pogo_data.py pull                   # every non-cold group (or --group G, repeatable)
  python tools/pogo_data.py push --group G         # REFUSED if the phone's G moved since this checkout pulled it
  python tools/pogo_data.py selftest               # offline: manifest, tar round trip, sqlite copy, guards

Guards: a pull never overwrites a local file that is NEWER than the phone's copy (--force to take the phone's anyway);
a push never overwrites a newer phone version (pull first, or --force); nothing git tracks is ever packed, so a pull
cannot roll code back; SQLite files are packed through the backup API (WAL-safe) and their stale -wal/-shm are removed
on pull. Device: $ADB_TARGET (the cloud hook sets 127.0.0.1:5555; the PC default is the phone's Tailscale address).
"""
import argparse, glob, hashlib, io, json, os, socket, sqlite3, subprocess, sys, tarfile, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, 'data_manifest.txt')
HELD = os.path.join(ROOT, '.pogo_data_held.json')          # {group: version this checkout holds}
PHONE_DIR = '/data/local/tmp/pogo_data'
DEV = os.environ.get('ADB_TARGET', '100.98.158.56:5555')


# ---------------------------------------------------------------------------------------------------------------- manifest
def manifest(path=MANIFEST):
    """{group: [(pattern, newest_n or None, exclude?)]}. Lines: "[group]", "pattern", "pattern | newest N", "!pattern"."""
    groups, cur = {}, None
    for raw in open(path, encoding='utf-8'):
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            cur = line[1:-1].strip()
            groups.setdefault(cur, [])
            continue
        if cur is None:
            raise SystemExit('data_manifest.txt: pattern before any [group]: %r' % line)
        pat, _, opt = line.partition('|')
        pat = pat.strip().replace('\\', '/')
        n = int(opt.split()[-1]) if opt.strip().startswith('newest') else None
        groups[cur].append((pat.lstrip('!'), n, pat.startswith('!')))
    return groups


def tracked(root=ROOT):
    """Paths git tracks here (never packed: a pull must not roll code back). Empty outside a git checkout."""
    try:
        out = subprocess.run(['git', '-C', root, 'ls-files', '-z'], capture_output=True, timeout=60).stdout
        return set(out.decode('utf-8', 'replace').split('\0')) - {''}
    except (OSError, subprocess.SubprocessError):
        return set()


def files_for(group, groups, root=ROOT, skip=frozenset()):
    """Repo-relative paths (forward slashes) the group matches now, in manifest order, minus "!" excludes and `skip`."""
    out, drop = [], set()
    for pat, n, excl in groups.get(group, []):
        hits = [p for p in glob.glob(os.path.join(root, pat), recursive=True) if os.path.isfile(p)]
        if n:
            hits = sorted(hits, key=os.path.getmtime, reverse=True)[:n]
        rel = [os.path.relpath(p, root).replace(os.sep, '/') for p in hits]
        (drop.update if excl else out.extend)(rel)
    seen, uniq = set(), []
    for p in out:
        if p not in seen and p not in drop and p not in skip and not p.endswith(('-wal', '-shm', '-journal')):
            seen.add(p)
            uniq.append(p)
    return uniq


def _sqlite_copy(src, dst):
    a, b = sqlite3.connect('file:%s?mode=ro' % src.replace('\\', '/'), uri=True), sqlite3.connect(dst)
    try:
        a.backup(b)
    finally:
        b.close(); a.close()


def build_tar(paths, root=ROOT):
    """(bytes, sha256) of a gzip tarball of the repo-relative paths. *.db goes through the SQLite backup API."""
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as td, tarfile.open(fileobj=buf, mode='w:gz', compresslevel=6) as tf:
        for rel in paths:
            src = os.path.join(root, rel)
            if rel.endswith('.db'):
                tmp = os.path.join(td, 'copy.db')
                if os.path.exists(tmp):
                    os.remove(tmp)
                _sqlite_copy(src, tmp)
                os.utime(tmp, (os.path.getmtime(src),) * 2)
                src = tmp
            tf.add(src, arcname=rel, recursive=False)
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def newer_here(data, root=ROOT):
    """Members whose local copy is NEWER than the packed one and differs in size (a pull would lose local work)."""
    out = []
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tf:
        for m in tf.getmembers():
            p = os.path.join(root, m.name)
            if m.isfile() and os.path.isfile(p) and os.path.getmtime(p) > m.mtime + 2 and os.path.getsize(p) != m.size:
                out.append(m.name)
    return out


def extract_tar(data, root=ROOT):
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tf:
        members = tf.getmembers()
        for m in members:
            if m.name.startswith('/') or '..' in m.name.split('/') or not (m.isfile() or m.isdir()):
                raise SystemExit('refusing tar member %r (outside the checkout or not a plain file)' % m.name)
        for m in members:
            if m.name.endswith('.db'):                       # a stale WAL replayed onto a replaced DB corrupts it
                for ext in ('-wal', '-shm', '-journal'):
                    p = os.path.join(root, m.name + ext)
                    if os.path.exists(p):
                        os.remove(p)
        if sys.version_info >= (3, 12):
            tf.extractall(root, filter='data')
        else:
            tf.extractall(root)
        return len(members)


# ---------------------------------------------------------------------------------------------------------------- phone
def adb(*args, timeout=900):
    r = subprocess.run(['adb', '-s', DEV] + list(args), capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise SystemExit('adb %s failed (rc %d): %s' % (' '.join(args[:2]), r.returncode,
                                                         (r.stderr or r.stdout).decode('utf-8', 'replace').strip()[:300]))
    return r.stdout


def phone_meta():
    """{group: meta} for every <group>.json on the phone."""
    out = adb('shell', 'for f in %s/*.json; do [ -f "$f" ] && { printf "%%s\\t" "$f"; tr -d "\\n" < "$f"; echo; }; done'
              % PHONE_DIR).decode('utf-8', 'replace')
    metas = {}
    for line in out.splitlines():
        path, _, body = line.partition('\t')
        if path.endswith('.json') and body.strip():
            try:
                metas[os.path.basename(path)[:-5]] = json.loads(body)
            except ValueError:
                raise SystemExit('unreadable meta on the phone: %s' % path)
    return metas


def phone_put(local_path, name):
    """adb push to a temp name, check its sha256 on the phone, then rename into place (readers never see half a file)."""
    adb('shell', 'mkdir -p %s' % PHONE_DIR)
    tmp = '%s/.%s.tmp' % (PHONE_DIR, name)
    adb('push', local_path, tmp)
    want = hashlib.sha256(open(local_path, 'rb').read()).hexdigest()
    got = adb('shell', 'sha256sum %s' % tmp).decode().split()[0]
    if got != want:
        raise SystemExit('upload of %s corrupted (sha %s != %s) -- nothing replaced' % (name, got[:12], want[:12]))
    adb('shell', 'mv -f %s %s/%s' % (tmp, PHONE_DIR, name))


def _held():
    try:
        return json.load(open(HELD))
    except (OSError, ValueError):
        return {}


def _hold(group, version):
    h = _held()
    h[group] = version
    json.dump(h, open(HELD, 'w'), indent=1, sort_keys=True)


# ---------------------------------------------------------------------------------------------------------------- commands
def cmd_status(_a):
    metas, held = phone_meta(), _held()
    for g in sorted(set(manifest()) | set(metas)):
        m = metas.get(g) or {}
        print('%-15s phone v%-4s %7s  %-19s by %-12s | here v%s' % (
            g, m.get('version', '-'), '%.1fMB' % (m['bytes'] / 1e6) if m else '-', m.get('at', ''), m.get('by', ''),
            held.get(g, '-')))
    return 0


def cmd_pull(a):
    metas = phone_meta()
    groups = a.group or sorted(g for g in metas if not g.endswith('-cold'))
    if not groups:
        raise SystemExit('no data on the phone yet (%s) -- seed it from the PC: push --group <g> --force' % PHONE_DIR)
    rc = 0
    for g in groups:
        m = metas.get(g)
        if not m:
            print('%s: not on the phone -- skipped' % g)
            continue
        if _held().get(g) == m['version'] and not a.force:
            print('%s: already at v%s' % (g, m['version']))
            continue
        with tempfile.TemporaryDirectory() as td:
            dst = os.path.join(td, g + '.tar.gz')
            t0 = time.time()
            adb('pull', '%s/%s.tar.gz' % (PHONE_DIR, g), dst)
            data = open(dst, 'rb').read()
        if hashlib.sha256(data).hexdigest() != m['sha256']:
            raise SystemExit('%s: the download does not match its meta sha -- nothing extracted (a push in flight? retry)' % g)
        lose = [] if a.force else newer_here(data)
        if lose:
            print('%s: REFUSED -- %d local file(s) are newer than the phone copy v%s (a pull would lose them): %s%s\n'
                  '   push them first (push --group %s), or pull --force to take the phone copy.'
                  % (g, len(lose), m['version'], ', '.join(lose[:5]), ' ...' if len(lose) > 5 else '', g))
            rc = 3
            continue
        n = extract_tar(data)
        _hold(g, m['version'])
        print('%s: v%s, %d files, %.1f MB in %.0f s' % (g, m['version'], n, len(data) / 1e6, time.time() - t0))
    return rc


def cmd_push(a):
    groups, metas, skip = manifest(), phone_meta(), tracked()
    for g in a.group:
        if g not in groups:
            raise SystemExit('no group %r in data_manifest.txt (have: %s)' % (g, ', '.join(sorted(groups))))
        m = metas.get(g) or {}
        if m and m.get('version') != _held().get(g) and not a.force:
            raise SystemExit('%s: REFUSED -- the phone holds v%s but this checkout holds v%s (another session pushed since).'
                             ' Pull it first, or --force if you are sure.' % (g, m.get('version'), _held().get(g)))
        paths = files_for(g, groups, skip=skip)
        if not paths:
            print('%s: no files match -- skipped' % g)
            continue
        t0 = time.time()
        data, sha = build_tar(paths)
        ver = int(m.get('version') or 0) + 1
        meta = {'version': ver, 'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'sha256': sha, 'bytes': len(data),
                'files': len(paths), 'by': os.environ.get('POGO_DATA_BY') or (
                    'cloud' if os.environ.get('CLAUDE_CODE_REMOTE') == 'true' else socket.gethostname())}
        with tempfile.TemporaryDirectory() as td:
            tp, mp = os.path.join(td, g + '.tar.gz'), os.path.join(td, g + '.json')
            open(tp, 'wb').write(data)
            json.dump(meta, open(mp, 'w'))
            phone_put(tp, g + '.tar.gz')                 # tarball first: a reader who sees the new meta finds its data
            phone_put(mp, g + '.json')
        _hold(g, ver)
        print('%s: v%d, %d files, %.1f MB pushed in %.0f s' % (g, ver, len(paths), len(data) / 1e6, time.time() - t0))
    return 0


def cmd_selftest(_a):
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, 'a', 'snaps'))
        for i in range(5):
            p = os.path.join(td, 'a', 'snaps', 's%d.gz' % i)
            open(p, 'wb').write(b'x' * (i + 1))
            os.utime(p, (1000 + i, 1000 + i))
        c = sqlite3.connect(os.path.join(td, 'a', 'db.db'))
        c.execute('pragma journal_mode=wal'); c.execute('create table t(x)'); c.execute('insert into t values (7)')
        c.commit()                                           # left OPEN: the row sits in the WAL, not the main file
        open(os.path.join(td, 'a', 'code.py'), 'w').write('print(1)')
        open(os.path.join(td, 'a', 'secret.xml'), 'w').write('k')
        m = os.path.join(td, 'm.txt')
        open(m, 'w').write('[hot]\na/db.db\na/*.py\na/*.xml\n!a/secret.xml\na/snaps/*.gz | newest 2  # latest two\n'
                           '[hot-cold]\na/snaps/*.gz\n')
        g = manifest(m)
        hot = files_for('hot', g, td, skip={'a/code.py'})
        assert hot == ['a/db.db', 'a/snaps/s4.gz', 'a/snaps/s3.gz'], hot
        assert len(files_for('hot-cold', g, td)) == 5
        data, _ = build_tar(hot, td)
        c.close()
        out = os.path.join(td, 'out')
        os.makedirs(os.path.join(out, 'a'))
        open(os.path.join(out, 'a', 'db.db-wal'), 'wb').write(b'stale')
        assert extract_tar(data, out) == 3
        assert not os.path.exists(os.path.join(out, 'a', 'db.db-wal'))
        r = sqlite3.connect(os.path.join(out, 'a', 'db.db'))
        assert r.execute('select x from t').fetchone() == (7,)
        r.close()
        p = os.path.join(out, 'a', 'snaps', 's4.gz')
        open(p, 'wb').write(b'local work, longer')           # newer AND different -> a pull must refuse
        assert newer_here(data, out) == ['a/snaps/s4.gz']
    print('pogo_data selftest: OK')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = ap.add_subparsers(dest='cmd', required=True)
    sp.add_parser('status')
    p = sp.add_parser('pull')
    p.add_argument('--group', action='append', help='repeatable; default: every non-cold group on the phone')
    p.add_argument('--force', action='store_true', help='take the phone copy even over newer local files')
    p = sp.add_parser('push')
    p.add_argument('--group', action='append', required=True, help='repeatable: inventory, catcher, gym, inventory-cold')
    p.add_argument('--force', action='store_true', help='push although the phone moved since this checkout pulled')
    sp.add_parser('selftest')
    a = ap.parse_args()
    return {'status': cmd_status, 'pull': cmd_pull, 'push': cmd_push, 'selftest': cmd_selftest}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())

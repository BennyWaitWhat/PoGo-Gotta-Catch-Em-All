"""full_audit.run_audits with POGO_AUDIT_JOBS (the cull on the phone, 2026-11-18): at most N audits at once, each of
HEAVY_AUDITS alone first, the results in AUDITS order, the same verdict rule (rc 0 AND the verdict line); unset = all at once.
Fake audits in a temp folder: no data, no phone."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import full_audit as f

FAKE = ("import os, sys, time\n"
        "n = os.path.basename(sys.argv[0])\n"
        "open(n + '.start', 'w').write(repr(time.time()))\n"
        "time.sleep(%s)\n"
        "open(n + '.end', 'w').write(repr(time.time()))\n"
        "print('VERDICT ' + n)\n"
        "sys.exit(%d)\n")
AUD = [('A', 'a.py', 'VERDICT a.py'), ('rank tags', 'audit_rank_tags.py', 'VERDICT audit_rank_tags.py'),
       ('B', 'b.py', 'VERDICT b.py'), ('C', 'c.py', 'NO SUCH LINE'), ('D', 'd.py', 'VERDICT d.py')]


def spans(d):
    return {sc: (float(open(os.path.join(d, sc + '.start')).read()), float(open(os.path.join(d, sc + '.end')).read()))
            for _nm, sc, _need in AUD}


def most_at_once(sp, only=None):
    pts = sorted([(s, 1) for k, (s, e) in sp.items() if only is None or k in only] +
                 [(e, -1) for k, (s, e) in sp.items() if only is None or k in only], key=lambda x: (x[0], x[1]))
    n = top = 0
    for _t, step in pts:
        n += step
        top = max(top, n)
    return top


old = os.getcwd()
for jobs in ('2', ''):
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            os.makedirs(os.path.join('system', 'analysis'))
            for _nm, sc, _need in AUD:
                open(sc, 'w').write(FAKE % ('0.6' if sc == 'audit_rank_tags.py' else '1.0', 1 if sc == 'd.py' else 0))
            f.AUDITS, f.PY = AUD, sys.executable
            os.environ['POGO_AUDIT_JOBS'] = jobs
            res = f.run_audits()
            assert [nm for nm, ok, log in res] == [nm for nm, sc, need in AUD], 'the results come back in AUDITS order'
            assert [ok for nm, ok, log in res] == [True, True, True, False, False], 'rc 0 AND the verdict line, both'
            sp = spans(d)
            if jobs:
                hs, he = sp['audit_rank_tags.py']
                assert all(e <= hs or s >= he for k, (s, e) in sp.items() if k != 'audit_rank_tags.py'), 'the heavy audit runs alone'
                assert most_at_once(sp) <= 2, 'POGO_AUDIT_JOBS=2: never more than 2 at once'
                assert most_at_once(sp, {'a.py', 'b.py', 'c.py', 'd.py'}) == 2, 'and the others do use 2 lanes'
            else:
                assert most_at_once(sp) == len(AUD), 'unset: all at once, as on the PC'
            assert os.path.exists(os.path.join('system', 'analysis', 'last_audit_audit_rank_tags.log')), 'every log is kept'
        finally:
            os.chdir(old)                                     # out of the folder before it is removed (Windows)
            os.environ.pop('POGO_AUDIT_JOBS', None)
print('test_audit_jobs OK')

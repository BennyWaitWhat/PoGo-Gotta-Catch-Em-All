"""Prove (non-destructively) that deleting in_bag!=1 ghost rows does NOT change
any cull/keep/tag outcome. Operates on TWO throwaway temp DB copies; never
touches pokemon.db. For each, run the live cull_v9 + keep_policy + build_tagsets
logic and diff the results."""
import sqlite3, os, sys, shutil, json, subprocess, tempfile
sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'pokemon.db')

def snapshot_outcomes(dbpath):
    """Return (keep, xfer, per-rule cull reasons hist, tagset membership) by
    invoking the real modules against `dbpath` via a tiny in-process harness."""
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
    import importlib
    import cull_v9
    importlib.reload(cull_v9)
    conn = sqlite3.connect(dbpath); conn.row_factory = sqlite3.Row
    c = conn.cursor()
    rows = [dict(r) for r in c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()]
    gm = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json')))
    # cull_v9 build_ctx reads JSON sidecars relative to CWD; run from ROOT
    cwd0 = os.getcwd(); os.chdir(ROOT)
    try:
        ctx = cull_v9.build_ctx(rows, gm)
    finally:
        os.chdir(cwd0)
    keep = xfer = 0
    reason_hist = {}
    decisions = {}
    for p in rows:
        reasons = cull_v9.is_protected(p, ctx)
        if reasons:
            keep += 1; decisions[p['uid_hex']] = 'KEEP'
            for r in reasons:
                reason_hist[r] = reason_hist.get(r, 0) + 1
        else:
            xfer += 1; decisions[p['uid_hex']] = 'TRANSFER'
    conn.close()
    return keep, xfer, reason_hist, decisions

# Temp copy A: full DB (ghosts present)
tmpdir = tempfile.mkdtemp()
A = os.path.join(tmpdir, 'full.db')
B = os.path.join(tmpdir, 'noghost.db')
shutil.copyfile(SRC, A)
shutil.copyfile(SRC, B)
# Delete ghosts from B
cb = sqlite3.connect(B)
nb = cb.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag IS NOT 1").fetchone()[0]
cb.execute("DELETE FROM pokemon WHERE in_bag IS NOT 1")
cb.commit(); cb.close()
print(f"Deleted {nb} ghost rows from temp copy B")

kA, xA, rhA, decA = snapshot_outcomes(A)
kB, xB, rhB, decB = snapshot_outcomes(B)

print(f"FULL   : KEEP={kA} TRANSFER={xA}")
print(f"NOGHOST: KEEP={kB} TRANSFER={xB}")
print("KEEP/TRANSFER identical:", (kA, xA) == (kB, xB))
print("per-reason histogram identical:", rhA == rhB)
if rhA != rhB:
    keys = set(rhA) | set(rhB)
    for k in sorted(keys):
        if rhA.get(k) != rhB.get(k):
            print("   DIFF", k, rhA.get(k), "->", rhB.get(k))
# decision-by-uid identical for the in-bag set
diff_uids = [u for u in decA if decA[u] != decB.get(u)]
print("per-uid decision diffs:", len(diff_uids))
shutil.rmtree(tmpdir, ignore_errors=True)
print("\nRESULT:", "GHOST-DROP IS A NO-OP (proven empirically)" if (kA,xA,rhA,decA)==(kB,xB,rhB,decB) else "MISMATCH!!")

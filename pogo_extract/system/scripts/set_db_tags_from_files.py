"""Mirror the DB auth_tag_names to exactly match the computed tagset files
(system/analysis/tagsets/*.txt). Each in_bag mon's auth_tag_names becomes the
';'-joined set of tags whose file contains it. DB-only, no device.

RUN THIS *AFTER* THE PUSH, NEVER BEFORE (order corrected 2026-09-02).
auth_tag_names is what the dashboard's /api/tagdiff calls "the phone's last-known tags", and this
script writes it straight from the FILES with no knowledge of whether the push succeeded. Run first
(as /api/sync used to), it made every sync -- successful or not -- report "already in sync" on the
next preview. The dashboard now runs it last, after prune_tags has verified the push, and because a
non-zero step aborts the job it does not run at all when the push failed. If you invoke it by hand,
do the same: prune_tags.py --atomic (rc 0) -> refresh_evolve_shiny.py -> this.

EVERY .txt HERE IS CONSUMED, INCLUDING FILES THIS ENGINE'S PUSH DOES NOT OWN.
prune_tags.PLAN covers 11 tags; Evolve_Shiny.txt is produced by refresh_evolve_shiny.py instead. So a
stale producer silently mirrors stale membership -- measured 2026-09-02, Evolve_Shiny.txt was 2 days
old with 1 uid while every other tagset was minutes old. Hence the staleness warning below: it cannot
fix the file, but it refuses to mirror one quietly.
"""
import sqlite3, os, time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DB = os.path.join(ROOT, 'pokemon.db')
TD = os.path.join(ROOT, 'system', 'analysis', 'tagsets')

STALE_WARN_S = 3600      # a tagset more than an hour behind the freshest one had a producer that didn't run


def tag_of(fn):
    """The tag NAME a tagset filename stands for -- the inverse of granular_tags.filename (only spaces <-> '_').
    ONE definition (2026-09-26): audit_invariants I8 calls it to prove every managed name, the dynamic
    'Stop at <stage>' ones included, reads back to itself (a name with a '_' would not)."""
    return fn[:-4].replace('_', ' ')        # 1_GL_Least_Bad.txt -> "1 GL Least Bad"


def _consumed():
    """Tagset files this script mirrors into auth_tag_names."""
    return [fn for fn in sorted(os.listdir(TD))
            # 6_Transfer.txt = keep_policy's internal pile; the server tag is Transfer.txt
            if fn.endswith('.txt') and not fn.startswith('_') and fn != '6_Transfer.txt']


def _warn_stale(files):
    """Report any consumed tagset whose producer clearly did not run this cycle. Informational: this
    script cannot regenerate someone else's file, but mirroring a stale one without saying so is how a
    2-day-old Evolve_Shiny.txt got staged as current."""
    mt = {}
    for fn in files:
        try:
            mt[fn] = os.path.getmtime(os.path.join(TD, fn))
        except OSError:
            continue
    if not mt:
        return
    newest = max(mt.values())
    stale = sorted((n, fn) for fn, n in mt.items() if newest - n > STALE_WARN_S)
    for age, fn in stale:
        print(f'  !! STALE {fn}: {(newest - age) / 3600:.1f}h older than the freshest tagset '
              f'({time.strftime("%b %d %H:%M", time.localtime(age))}) -- its producer did not run; '
              f'mirroring it as-is')


def main():
    files = _consumed()
    _warn_stale(files)
    uid_tags = defaultdict(list)
    for fn in files:
        tag = tag_of(fn)
        for uid in open(os.path.join(TD, fn)).read().split():
            uid_tags[uid.strip()].append(tag)
    c = sqlite3.connect(DB)
    inbag = [r[0] for r in c.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1")]
    changed = 0
    for uid in inbag:
        val = ';'.join(sorted(uid_tags.get(uid, [])))
        cur = c.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uid,)).fetchone()[0] or ''
        if cur != val:
            c.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?", (val, uid))
            changed += 1
    c.commit()
    # report per-tag DB counts now
    print(f"mirrored DB auth_tag_names from {len(files)} tag files; {changed} rows changed")
    for fn in files:
        tag = tag_of(fn)
        # ESCAPE so a tag name containing a LIKE wildcard counts itself, not everything
        # (engine tag names carry none today; this keeps the count honest if one ever does)
        pat = tag.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        n = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND "
                      "(';'||COALESCE(auth_tag_names,'')||';') LIKE ? ESCAPE '\\'",
                      (f'%;{pat};%',)).fetchone()[0]
        print(f"  {tag:<18} {n}")          # 18 = the longest managed name ('Stop at Whirlipede', 2026-09-26)
    c.close()


if __name__ == '__main__':
    main()

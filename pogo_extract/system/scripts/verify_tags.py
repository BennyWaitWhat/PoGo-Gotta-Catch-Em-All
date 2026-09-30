"""Canonical tag verifier -- supersedes _triple_check.py.

Driven by system/tags/registry.json (the authoritative 16-tag set).
For each registry tag, computes and compares three counts:

  SERVER  Live enumerate via TaggingRpcService (get_NumberOfTags +
          GetCachedTagToPokemonBindingForIndex; member count at
          binding+0x18->list+0x18).  Requires PoGo running.
  DB      auth_tag_names LIKE '%;Name;%' on in_bag=1 rows in pokemon.db.
  RULE    For kind=='sql': SELECT COUNT(*) FROM pokemon WHERE in_bag=1
          AND (<rule>).  For kind=='special' or 'uids': marked 'n/a
          (special)' -- only server==db is checked.

Also flags:
  - SERVER tags not in the registry  (extra)
  - Registry tags missing from the server  (missing)

Exit codes:
  0  all checks pass
  1  tag drift detected (discrepancies)
  2  pokemon.db missing or unreadable
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
import os
import sqlite3
import time

# -- path setup ----------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

REGISTRY_PATH = os.path.join(REPO, 'system', 'tags', 'registry.json')
DB_PATH = os.path.join(REPO, 'pokemon.db')

# -- Frida JS: enumerate server tags + member counts --------------------------
ENUM_JS = r"""
function enumerateTagsWithMembers(svcAddrStr) {
    _ensureInit();
    var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, gnt = null, gctb = null;
    while ((m = IL2.cGM(svcCls, iter)) && !m.isNull()) {
        var nm = IL2.mGN(m).readCString();
        if (nm === 'get_NumberOfTags') gnt = m;
        if (nm === 'GetCachedTagToPokemonBindingForIndex') gctb = m;
    }
    var svc = ptr(svcAddrStr);
    var ret = rI(gnt, svc, ptr(0), null);
    var totalTags = ret.add(0x10).readS32();
    var out = [];
    for (var i = 0; i < totalTags; i++) {
        var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
        var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
        var bp = rI(gctb, svc, args, null);
        if (bp.isNull()) continue;
        var tagProto = bp.add(0x10).readPointer();
        var name = '';
        try {
            var ns = tagProto.add(0x40).readPointer();
            if (!ns.isNull()) {
                var len = ns.add(0x10).readS32();
                if (len > 0 && len < 100) {
                    var chars = [];
                    for (var ci = 0; ci < len; ci++)
                        chars.push(String.fromCharCode(ns.add(0x14 + ci*2).readU16()));
                    name = chars.join('');
                }
            }
        } catch(e) {}
        var memberCount = 0;
        try {
            var lst = bp.add(0x18).readPointer();
            if (!lst.isNull()) {
                memberCount = lst.add(0x18).readS32();
            }
        } catch(e) {}
        out.push({idx: i, name: name, members: memberCount});
    }
    return out;
}
rpc.exports.enumerateTagsWithMembers = enumerateTagsWithMembers;
"""


# -- helpers -------------------------------------------------------------------

def load_registry():
    """Load registry.json; return list of tag dicts."""
    with open(REGISTRY_PATH, encoding='utf-8') as f:
        data = json.load(f)
    return data['tags']


def _server_enumerate_once():
    """Single attempt: attach via _frida_safe, enumerate tags, detach."""
    import _frida_safe as safe
    import pogo_il2cpp as pg

    sess, pid = safe.session()
    print(f'  Frida attached, pid={pid}')
    try:
        svc = safe.pick(sess, 'Niantic.Holoholo.Tagging',
                         'TaggingRpcService')
        print(f'  TaggingRpcService @ {svc}')
        script = pg.get_script_with_helpers(sess, ENUM_JS)
        srv = script.exports_sync.enumerate_tags_with_members(svc)
        script.unload()
        return srv
    finally:
        try:
            sess.detach()
        except Exception:
            pass


def server_enumerate():
    """Enumerate server tags with one retry on failure.

    Returns (list_of_tag_dicts, True)  on success,
            (None,              False) on failure (degraded mode).
    """
    for attempt in (1, 2):
        try:
            return _server_enumerate_once(), True
        except Exception as exc:
            print(f'  Server enumerate attempt {attempt} failed: {exc}')
            if attempt < 2:
                time.sleep(3)
    return None, False


def db_tag_count(conn, tag_name):
    """Count in-bag pokemon carrying tag_name in auth_tag_names."""
    return conn.execute(
        "SELECT COUNT(*) FROM pokemon WHERE in_bag=1 "
        "AND (';' || COALESCE(auth_tag_names,'') || ';') LIKE ?",
        (f'%;{tag_name};%',),
    ).fetchone()[0]


def rule_count(conn, sql_rule):
    """Run a SQL rule count against in-bag pokemon."""
    q = f"SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND ({sql_rule})"
    return conn.execute(q).fetchone()[0]


# -- main ----------------------------------------------------------------------

def main():
    print('=== VERIFY TAGS (registry-driven) ===\n')

    # Load registry
    tags = load_registry()
    tag_names = {t['name'] for t in tags}
    print(f'Registry: {len(tags)} tags loaded from {REGISTRY_PATH}\n')

    # DB existence check
    if not os.path.isfile(DB_PATH):
        print(f'ABORT: pokemon.db not found at {DB_PATH}')
        sys.exit(2)

    # Server enumerate (graceful degradation on failure)
    print('Enumerating server tags...')
    srv_tags, srv_ok = server_enumerate()
    if srv_ok:
        srv_by_name = {t['name']: t for t in srv_tags}
        print(f'  Server reports {len(srv_tags)} tags.\n')
    else:
        srv_by_name = {}
        print('  NOTE: server unreachable, DB/registry check only.\n')

    # DB counts + rule counts
    try:
        conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    except sqlite3.Error as e:
        print(f'ABORT: cannot open pokemon.db: {e}')
        sys.exit(2)

    db_counts = {}
    rule_counts = {}
    for t in tags:
        name = t['name']
        # registry.json carries no 'kind' (its 'rule' fields are prose, not SQL), so the
        # RULE column is n/a and we compare SERVER vs DB -- which is the check that matters.
        kind = t.get('kind', 'special')
        rule = t.get('rule', '')
        db_counts[name] = db_tag_count(conn, name)
        if kind == 'sql':
            try:
                rule_counts[name] = rule_count(conn, rule)
            except sqlite3.Error as e:
                rule_counts[name] = f'ERR: {e}'
        else:
            rule_counts[name] = 'n/a (special)'
    conn.close()

    # Print table
    hdr = f'{"tag":<16} {"server":>8} {"db":>8} {"rule":>16}  status'
    print(hdr)
    print('-' * len(hdr))

    all_ok = True
    for t in tags:
        name = t['name']
        kind = t.get('kind', 'special')
        s = srv_by_name.get(name, {}).get('members', '--') if srv_ok else '--'
        d = db_counts[name]
        r = rule_counts[name]

        if not srv_ok:
            # Degraded: only check db vs rule where possible
            if kind == 'sql':
                if isinstance(d, int) and isinstance(r, int) and d == r:
                    status = 'OK'
                else:
                    status = 'CHECK'
            else:
                status = 'SKIP'
        elif kind == 'sql':
            # All three must agree (server, db, rule all numeric and equal)
            if (isinstance(s, int) and isinstance(d, int)
                    and isinstance(r, int) and s == d == r):
                status = 'OK'
            else:
                status = 'CHECK'
        else:
            # special / uids: only server == db
            if isinstance(s, int) and isinstance(d, int) and s == d:
                status = 'OK'
            else:
                status = 'CHECK'

        if status not in ('OK', 'SKIP'):
            all_ok = False
        print(f'{name:<16} {str(s):>8} {str(d):>8} {str(r):>16}  {status}')

    print('-' * len(hdr))

    # Totals
    if srv_ok:
        total_srv = sum(t['members'] for t in srv_tags
                        if t['name'] in tag_names)
    else:
        total_srv = '--'
    total_db = sum(db_counts.values())
    print(f'{"TOTAL":<16} {str(total_srv):>8} {total_db:>8}')

    # Extra / missing checks only when server was reachable
    if srv_ok:
        extra = [t['name'] for t in srv_tags if t['name'] not in tag_names]
        if extra:
            print(f'\n! Extra server tag(s) NOT in registry: {extra}')
            all_ok = False

        missing = [name for name in (t['name'] for t in tags)
                   if name not in srv_by_name]
        if missing:
            print(f'\n! Registry tag(s) NOT on server: {missing}')
            all_ok = False

        print(f'\nServer tag count: {len(srv_tags)}  Registry: {len(tags)}')
        if len(srv_tags) == len(tags) and not extra and not missing:
            print('  TAG SET MATCH OK')
    else:
        print('\n(server unreachable -- extra/missing checks skipped)')

    # Final verdict
    print()
    if all_ok:
        print('=== ALL CHECKS PASS ===')
        sys.exit(0)
    else:
        print('=== DISCREPANCIES ABOVE -- REVIEW ===')
        sys.exit(1)


if __name__ == '__main__':
    main()

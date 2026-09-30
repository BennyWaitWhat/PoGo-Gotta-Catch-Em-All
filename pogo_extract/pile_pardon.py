"""ONE-TIME pardon: pull a class of mons OUT of the live Transfer tag without touching the engine.

User-ordered exception (2026-06-09 "keep my gmax and shinies for this one time"): untags the
matching pile members on the SERVER, rewrites Transfer.txt + 6_Transfer.txt, mirrors the DB --
the keep rules are NOT changed, so the NEXT recrawl/sync will re-derive and re-tag them.
That is the intended semantics of "this one time".

Usage:  python pile_pardon.py --shiny --gmax [--dmax] [--dry-run]
"""
import sys, os, json, sqlite3
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
os.chdir(ROOT)
import pogo_il2cpp as pg
import tag_ops
from reconcile_tags import ENUM_MEMBERS_JS

TD = os.path.join(ROOT, 'system', 'analysis', 'tagsets')
DRY = '--dry-run' in sys.argv
WANT_SHINY = '--shiny' in sys.argv
WANT_GMAX = '--gmax' in sys.argv
WANT_DMAX = '--dmax' in sys.argv
if not (WANT_SHINY or WANT_GMAX or WANT_DMAX):
    raise SystemExit('nothing selected: pass --shiny / --gmax / --dmax')

pile = [u for u in open(os.path.join(TD, 'Transfer.txt')).read().split() if u]
con = sqlite3.connect('pokemon.db'); con.row_factory = sqlite3.Row
rows = {r['uid_hex']: r for r in con.execute(
    'SELECT uid_hex, species_name, iv_total, fresh_shiny, is_shiny, fresh_bread_mode, cp '
    'FROM pokemon WHERE in_bag=1')}

def wants(r):
    # over-protect: EITHER shiny column counts (fresh_* is the live read, is_shiny the crawl col)
    if WANT_SHINY and (r['fresh_shiny'] or r['is_shiny']):
        return 'shiny'
    bm = r['fresh_bread_mode'] or 0
    if WANT_GMAX and bm == 2:
        return 'Gmax'
    if WANT_DMAX and bm == 1:
        return 'Dmax'
    return None

pardon, keep_piled, missing = {}, [], []
for u in pile:
    r = rows.get(u)
    if r is None:
        missing.append(u)          # not in bag anymore -- recrawl drift; leave alone
        continue
    w = wants(r)
    if w:
        pardon[u] = (w, r)
    else:
        keep_piled.append(u)

print(f'pile={len(pile)}  pardon={len(pardon)}  remain={len(keep_piled)}  not-in-bag={len(missing)}')
for u, (w, r) in sorted(pardon.items(), key=lambda kv: (kv[1][0], -(kv[1][1]['iv_total'] or 0))):
    print(f'  PARDON {w:<5} {r["species_name"]:<14} {round((r["iv_total"] or 0)/45*100):>3}%  cp{r["cp"]}')
if DRY:
    print('[dry-run] no writes'); raise SystemExit(0)
if not pardon:
    print('nothing to pardon'); raise SystemExit(0)

norm = lambda x: format(int(x, 16), 'x')
pardon_n = {norm(u) for u in pardon}

sess, pid = pg.get_session(); print(f'attached pid {pid}')
try:
    try:
        from ready_gate import ensure_ready_for_writes
        ensure_ready_for_writes(sess, pid)
    except Exception as e:
        print(f'[ready_gate] {e}')
    bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
    svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
    bag_map = pg.walk_bag_protos(sess, bag)
    hex_to_proto = {format(int(d), 'x'): pp for d, pp in bag_map.items()}
    proto_to_hex = {pp: uh for uh, pp in hex_to_proto.items()}
    en = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
    try:
        srv = {t['name']: t for t in en.exports_sync.enumerate_all_tag_members(svc)}
    finally:
        en.unload()
    members = srv.get('Transfer', {}).get('members', [])
    cur = {proto_to_hex[pp] for pp in members if pp in proto_to_hex}
    print(f'server Transfer={len(cur)}')
    if len(cur) < len(pile) // 2:
        raise SystemExit('server tag looks unloaded (bag not in memory?) -- retry once PoGo shows real tag counts')
    todo = sorted(pardon_n & cur)
    print(f'untagging {len(todo)} of {len(pardon_n)} (rest not on server tag)')
    bt = tag_ops._load_bulk_tag_script(sess)
    ok = 0
    try:
        tag_ops.ensure_ready(sess, svc, bt)
        tp = tag_ops.create_tag(bt, svc, 'Transfer', 6)   # returns the existing tag ptr
        for u in todo:
            lp = hex_to_proto.get(u)
            if not lp:
                continue
            try:
                if tag_ops.untag_one(bt, svc, lp, tp).get('ok'):
                    ok += 1
            except Exception as e:
                print(f'  untag {u}: {e}')
        print(f'untagged {ok}/{len(todo)}')
        en2 = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
        try:
            srv2 = {t['name']: t for t in en2.exports_sync.enumerate_all_tag_members(svc)}
        finally:
            en2.unload()
        after = {proto_to_hex[pp] for pp in srv2.get('Transfer', {}).get('members', []) if pp in proto_to_hex}
        leak = pardon_n & after
        print(f'server Transfer after={len(after)}  pardoned-still-tagged={len(leak)}')
        if leak:
            for u in sorted(leak):
                print('  STILL TAGGED:', u)
    finally:
        bt.unload()
finally:
    sess.detach()

# files + DB mirror so the dashboard/tagdiff agree until the next recrawl re-derives
remain_all = [u for u in pile if u not in pardon]
open(os.path.join(TD, 'Transfer.txt'), 'w').write('\n'.join(remain_all))
p6 = os.path.join(TD, '6_Transfer.txt')
if os.path.exists(p6):
    six = [u for u in open(p6).read().split() if u and u not in pardon]
    open(p6, 'w').write('\n'.join(six))
c = sqlite3.connect('pokemon.db')
for u in pardon:
    row = c.execute('SELECT auth_tag_names FROM pokemon WHERE uid_hex=?', (u,)).fetchone()
    if row is None:
        continue
    parts = [t for t in (row[0] or '').split(';') if t and t != 'Transfer']
    c.execute('UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?', (';'.join(sorted(parts)), u))
c.commit(); c.close()
print(f'files + DB mirrored: Transfer.txt now {len(remain_all)}')
print('NOTE: one-time edit -- the next Recrawl/Sync re-derives the pile and WILL re-tag these.')

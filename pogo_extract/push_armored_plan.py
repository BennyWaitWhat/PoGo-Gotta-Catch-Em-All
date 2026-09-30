"""push_armored_plan.py -- ONE-SHOT (2026-09-08): set four Armored Mewtwo label tags to EXACT membership.

User plan: "top 10 ML, top 10 UL, top 10 trade" + the rest tagged for hand release. Mewtwo is rarity keep-all,
so the engine never piles these; the release list is a plain, reversible LABEL, never the Transfer pile.

  Armored ML       (existing, colour 7)  -> 10 uids
  Armored UL       (existing, colour 0)  -> 10 uids
  Armored Trade    (NEW,      colour 3)  -> 10 uids
  Armored Release  (NEW,      colour 8)  -> 84 uids

Pattern copied from the proven retag_final.py: one gated Frida session, live bag walk, per-mon DELTA records
(TagsToAdd / TagsToRemove) so every unrelated tag a mon carries is preserved structurally, one batched
apply_changes, then a re-walk + re-enumerate verify (up to 3 attempts) that ALSO proves no other tag lost a
member. Files and the DB mirror are rewritten only after the phone verifies. Never releases anything.
PokemonTagColor is 0-8 (colour 9 returns ok=True and silently vanishes).
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
os.chdir(ROOT)
PLAN_JSON = os.environ.get('ARMORED_PLAN', os.path.join(
    r'C:\Users\Blanco\AppData\Local\Temp\claude\C--Users-Blanco-Desktop-Claude-Operations-Phone-Maintenance',
    r'9f2eff52-4f4a-4130-a61e-420ac1dd82ff', 'scratchpad', 'armored_plan.json'))
TD = os.path.join(ROOT, 'system', 'analysis', 'tagsets')
DRY = '--dry-run' in sys.argv
COLOUR = {'Armored ML': 7, 'Armored UL': 0, 'Armored Trade': 3, 'Armored Release': 8}
FILE = {'Armored ML': 'Armored_ML.txt', 'Armored UL': 'Armored_UL.txt',
        'Armored Trade': 'Armored_Trade.txt', 'Armored Release': 'Armored_Release.txt'}
for c in COLOUR.values():
    assert 0 <= c <= 8, 'PokemonTagColor must be 0-8'


def norm(u):
    return format(int(u, 16), 'x')


def main():
    plan = json.load(open(PLAN_JSON, encoding='utf-8'))
    WANT = {'Armored ML': {norm(u) for u in plan['ml']}, 'Armored UL': {norm(u) for u in plan['ul']},
            'Armored Trade': {norm(u) for u in plan['trade']}, 'Armored Release': {norm(u) for u in plan['release']}}
    allu = set().union(*WANT.values())
    for a in WANT:
        for b in WANT:
            if a < b and WANT[a] & WANT[b]:
                print('  note: %d uid(s) in both %s and %s (allowed for ML/UL overlap)' % (len(WANT[a] & WANT[b]), a, b))
    # release must never overlap a keep list
    assert not (WANT['Armored Release'] & (WANT['Armored ML'] | WANT['Armored UL'] | WANT['Armored Trade'])), 'release overlaps a keep list'
    print('plan: ' + ', '.join('%s=%d' % (k, len(v)) for k, v in WANT.items()) + ' | %d distinct mons' % len(allu))

    import sqlite3
    con = sqlite3.connect('file:%s?mode=ro' % os.path.join(ROOT, 'pokemon.db'), uri=True)
    inbag = {norm(r[0]) for r in con.execute('SELECT uid_hex FROM pokemon WHERE in_bag=1 AND pokemon_id=150 AND fresh_form=133')}
    con.close()
    missing = allu - inbag
    assert not missing, 'plan uids not in the DB bag: %s' % sorted(missing)[:5]
    assert allu == inbag, 'plan does not cover the whole Armored set: %d planned vs %d in bag' % (len(allu), len(inbag))
    if DRY:
        print('--dry-run: nothing written, no phone contact.'); return 0

    import pogo_il2cpp as pg, tag_ops
    from reconcile_tags import ENUM_MEMBERS_JS
    from ready_gate import ensure_ready_for_writes

    def enum_by_name(sess, svc):
        en = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
        try:
            return {t['name']: t for t in en.exports_sync.enumerate_all_tag_members(svc)}
        finally:
            en.unload()

    print('gating: waiting for an attach-safe PoGo (pure /proc polling)...')
    pg.wait_ready_to_attach(timeout_s=300)
    sess, pid = pg.get_session(); print('attached pid %d' % pid)
    ok = False
    try:
        ensure_ready_for_writes(sess, pid)
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        bm = pg.walk_bag_protos(sess, bag)
        h2p = {format(int(d), 'x'): pp for d, pp in bm.items()}
        p2h = {pp: uh for uh, pp in h2p.items()}
        print('bag-walk: %d live protos' % len(h2p))
        gone = allu - set(h2p)
        assert not gone, 'ABORT: %d planned uid(s) not in the LIVE bag (released since the walk?): %s' % (len(gone), sorted(gone)[:5])

        bt = tag_ops._load_bulk_tag_script(sess)
        try:
            tag_ops.ensure_ready(sess, svc, bt)
            pre_raw = enum_by_name(sess, svc)
            pre = {nm: {p2h[p] for p in i['members'] if p in p2h} for nm, i in pre_raw.items()}
            json.dump({k: sorted(v) for k, v in pre.items()}, open(os.path.join(ROOT, '_armored_plan_pre_tags.json'), 'w'), indent=0)
            print('PRE: %d server tags' % len(pre))
            tagproto = {}
            for name in WANT:
                if name in pre_raw:
                    tagproto[name] = pre_raw[name]['tagProto']; print('  %-16s exists, %d member(s)' % (name, len(pre[name])))
                else:
                    tagproto[name] = tag_ops.create_tag(bt, svc, name, COLOUR[name])
                    print('  %-16s CREATED colour %d' % (name, COLOUR[name])); pre[name] = set()
            # per-mon deltas over every Armored uid: add wanted names it lacks, remove our four names it should not have
            deltas = {}
            for u in allu:
                add = [n for n in WANT if u in WANT[n] and u not in pre.get(n, set())]
                rem = [n for n in WANT if u not in WANT[n] and u in pre.get(n, set())]
                if add or rem:
                    deltas[u] = {'add': add, 'remove': rem}
            print('change records: %d (adds %d, removes %d)' % (len(deltas), sum(len(d['add']) for d in deltas.values()), sum(len(d['remove']) for d in deltas.values())))
            changes = [{'proto': h2p[u], 'add': [tagproto[n] for n in ch['add']], 'remove': [tagproto[n] for n in ch['remove']]}
                       for u, ch in sorted(deltas.items())]
            if changes:
                try:
                    bt.exports_sync.bulk_apply_changes(svc, [])   # first-call NRE warm-up
                except Exception as e:
                    print('  (warm-up threw, ignored: %s)' % e)
                time.sleep(0.5)
                n = tag_ops.apply_changes(bt, svc, changes, batch=150)
                print('apply_changes -> %d/%d' % (n, len(changes)))
                if n != len(changes):
                    raise SystemExit('ABORT: partial apply -- files NOT rewritten.')
        finally:
            bt.unload()

        print('\n=== VERIFY (re-walk each attempt: tagging reallocates protos) ===')
        post = {}
        for attempt in range(3):
            time.sleep(5 if attempt == 0 else 7)
            bm2 = pg.walk_bag_protos(sess, bag)
            q2h = {pp: format(int(d), 'x') for d, pp in bm2.items()}
            post_raw = enum_by_name(sess, svc)
            post = {nm: {q2h[p] for p in i['members'] if p in q2h} for nm, i in post_raw.items()}
            ok = True
            for name, want in WANT.items():
                have = post.get(name)
                if have is None:
                    print('  %-16s MISSING FROM SERVER' % name); ok = False; continue
                extra, short = have - want, want - have
                print('  %-16s server=%d want=%d %s' % (name, len(have), len(want), 'OK' if not extra and not short else 'extra=%d short=%d' % (len(extra), len(short))))
                if extra or short: ok = False
            lost = {nm: len(s - post.get(nm, set())) for nm, s in pre.items() if nm not in WANT and (s - post.get(nm, set()))}
            print('  OTHER tags that lost members: %s' % (lost or 'NONE'))
            if lost: ok = False
            if ok: break
            print('  not yet equal -- retrying')
    finally:
        sess.detach()
    if not ok:
        raise SystemExit('VERIFY FAILED -- phone state differs from plan; files NOT rewritten. Re-run to converge.')

    # WANT/allu hold NORMALISED uids (leading zeros stripped); the DB and the tagset files use the
    # zero-padded canonical form -- map back before touching either (the earlier NoneType crash).
    con = sqlite3.connect(os.path.join(ROOT, 'pokemon.db'))
    try:
        canon = {norm(r[0]): r[0] for r in con.execute('SELECT uid_hex FROM pokemon WHERE in_bag=1')}
        for name, want in WANT.items():
            open(os.path.join(TD, FILE[name]), 'w', newline='\n').write('\n'.join(sorted(canon[u] for u in want)) + '\n')
        for u in allu:
            cu = canon[u]
            row = con.execute('SELECT auth_tag_names FROM pokemon WHERE uid_hex=?', (cu,)).fetchone()
            cur = [t for t in ((row[0] if row else '') or '').split(';') if t and t not in WANT]
            cur += [n for n in WANT if u in WANT[n]]
            con.execute('UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?', (';'.join(cur), cu))
        con.commit()
    finally:
        con.close()
    print('\nDONE: 4 tagset files written, DB mirror updated for %d mons. Verified on the phone.' % len(allu))
    return 0


if __name__ == '__main__':
    sys.exit(main())

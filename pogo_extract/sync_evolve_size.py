"""Keep an in-game "Evolve for Size" tag equal to the evolutions that would give a bigger showcase entry.

User 2026-09-19: "i just want to win showcases" -> "all 176 lets go."

MEMBERS: every XXL pre-evo whose evolved copy would out-score the best entry you already own at the target, under the
game's own showcase formula (height 800 / weight 150 / iv 50). See showcase_plan.py and size_line.py.

WHY ITS OWN TAG, not "Evolve Next": that label means the cull reserved an IV slot at the next stage. These are
reserved by SIZE and most would never earn an IV slot -- a 31% Magikarp is the clearest case. A tag must be true for
the mon on screen.

VERIFIED 2026-09-19 on 297 matched evolutions from the walk snapshots: the size badge carries through every time
(132/132 XXL stayed XXL, no badge of any kind changed), so membership is a fact about the badge. The evolved HEIGHT
-- which decides how much the entry improves -- matches the projection within 1% in 87% of cases, worst seen 25%.

  python sync_evolve_size.py [--dry-run]
"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
os.chdir(ROOT)
import showcase_plan, size_line

TAG = 'Evolve for Size'
COLOUR = 6                      # PokemonTagColor is 0-8
norm = lambda u: format(int(u, 16), 'x')

BINDING_JS = r"""
rpc.exports.specialBindings = function(svcAddrStr) {
    _ensureInit();
    var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var out = {};
    ['get_RemoteTradeTagBinding', 'get_FavoritesTagBinding'].forEach(function (want) {
        var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
        var m, g = null;
        while ((m = IL2.cGM(svcCls, it)) && !m.isNull()) {
            if (IL2.mGN(m).readCString() === want) { g = m; break; }
        }
        if (!g) return;
        try {
            var bp = rI(g, ptr(svcAddrStr), ptr(0), null);
            if (!bp.isNull()) out[want] = bp.add(0x10).readPointer().toString();
        } catch (e) {}
    });
    return out;
};
"""


def _own_stage_best():
    """uids that are a Best GL / Best UL copy (keep_policy rule 15d) whose USABLE winning stage is their OWN stage:
    never advised to evolve (user 2026-09-23) -- the same test as keep_policy's _own_pvp, audit_labels and
    refresh_evolve_shiny: pvp_iv_rule.usable_best over the stages keep_policy.pvp_later_stages says the copy can become
    (its CP there at its true level inside the cap). A Best copy with no usable stage reads as own-stage (the side
    that never consumes it). None if policy_reasons.json -- or the evolution graph -- is unavailable."""
    import json, sqlite3
    from pvp_iv_rule import pvid, usable_best, GL_CAP, UL_CAP
    try:
        pol = json.load(open(os.path.join('system', 'analysis', 'policy_reasons.json'), encoding='utf-8'))
        from keep_policy import build_evo_graph, pvp_later_stages
        gm = json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))
        graph = build_evo_graph(gm, {e['pid'] for e in json.load(open('pokedex_hundos_live.json'))['entries']},
                                with_all=True)
        BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
    except Exception:
        return None
    c = sqlite3.connect('file:pokemon.db?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    out = set()
    try:
        for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1'):
            rs = set(pol.get(r['uid_hex']) or ())
            own = pvid(r['species_name'], r['form'] or 0)
            if 'pvp_best_gl' in rs or 'pvp_best_ul' in rs:   # every Best wins as itself since 2026-10-29 (15d)
                out.add(norm(r['uid_hex']))
    finally:
        c.close()
    return out


def picks(pile=None):
    """An XXL pre-evo whose evolved copy would out-score the best entry you own at the target.

    The gate is the BADGE, not a projected z: 297 matched evolutions in the walk history kept their size badge every
    time (132/132 XXL), so an XXL that evolves is still an XXL. The projection only supplies the score."""
    rows = showcase_plan._rows()
    big = [e for e in showcase_plan.evolve_to_win(rows) if e['size'] == 5]
    held = _own_stage_best()
    if held is None:
        print('  (policy_reasons.json or the evolution graph unreadable -- Best GL/UL own-stage copies NOT filtered from %s)' % TAG)
    else:
        big = [e for e in big if norm(e['uid']) not in held]
    # A WINNER, AND KEPT (2026-09-24): the evolved copy must reach keep_config showcase_weights.min_points -- the user's
    # "actual winners" bar, the one the XXL keep uses -- and the copy must not be in the Transfer pile. The old bar
    # ("beats your best entry there") told him to evolve a 1030 Exeggcute and a 1008 Cubone the same cull had tagged
    # for release, and a 1113 Dusclops into a 1014 Dusknoir the next cull would drop.
    import keep_config
    _min = keep_config.showcase_weights()['min_points']
    try:                                       # `pile`: the pile THIS build is making (build_tagsets, 2026-09-26) --
        _pile = ({norm(u) for u in pile} if pile is not None   # the file on disk is still the previous build's there
                 else {norm(u) for u in open(os.path.join('system', 'analysis', 'tagsets', 'Transfer.txt')).read().split()})
    except OSError:
        _pile = set()
    big = [e for e in big if (e['score_after'] or 0) >= _min and norm(e['uid']) not in _pile]
    return {norm(e['uid']) for e in big}, big


def picks_for_tag():
    """The tag is RETIRED (2026-09-29): the picks are folded into Evolve Once / Twice by granular_tags.evolve_advice.
    Kept for old callers -- the same picks, nothing filtered."""
    return picks()

def sync(sess, bag, svc, want_all):
    """One Evolve for Size refresh inside an ATTACHED, write-GATED session whose bag/svc singletons are already picked
    (sync_post_tags.py shares one session with Remote Trade, speed study 2026-09-24). Its own fresh walk, tag
    enumeration, push, verify and DB mirror -- exactly the body main() always ran. Returns the rc main() returned."""
    import pogo_il2cpp as pg, tag_ops
    from reconcile_tags import ENUM_MEMBERS_JS
    if tag_ops.is_pile_tag(TAG):
        raise SystemExit('REFUSING: %r is the release pile.' % TAG)
    h2p = {format(int(d), 'x'): pp for d, pp in pg.walk_bag_protos(sess, bag).items()}
    p2h = {pp: uh for uh, pp in h2p.items()}
    want = {u for u in want_all if u in h2p}
    _dbc = __import__('sqlite3').connect('file:pokemon.db?mode=ro', uri=True)
    _db_uid = {format(int(u, 16), 'x'): u for (u,) in _dbc.execute('SELECT uid_hex FROM pokemon WHERE in_bag=1')}
    _dbc.close()

    def listed():
        en = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
        try:
            return en.exports_sync.enumerate_all_tag_members(svc)
        finally:
            en.unload()

    # IDENTIFY BY PROTO, NEVER BY NAME, and never collide with a special binding (2026-09-19: a name-keyed lookup
    # missed the Remote Trade binding and created a duplicate tag).
    sc = pg.get_script_with_helpers(sess, BINDING_JS)
    try:
        special = set((sc.exports_sync.special_bindings(svc) or {}).values())
    finally:
        sc.unload()
    mine = [t for t in listed() if t['name'] == TAG and t['tagProto'] not in special]
    if len(mine) > 1:
        raise SystemExit('ABORT: %d tags already named %r -- merge them first.' % (len(mine), TAG))
    if mine:
        proto = mine[0]['tagProto']
        cur = {p2h[p] for p in (mine[0].get('members') or []) if p in p2h}
        print('%s exists with %d member(s)' % (TAG, len(cur)))
    else:
        bt0 = tag_ops._load_bulk_tag_script(sess)
        try:
            tag_ops.ensure_ready(sess, svc, bt0)
            proto = tag_ops.create_tag(bt0, svc, TAG, COLOUR)
        finally:
            bt0.unload()
        cur = set(); print('%s CREATED (colour %d)' % (TAG, COLOUR))

    add, rem = want - cur, cur - want
    print('+%d -%d (already right %d)' % (len(add), len(rem), len(want & cur)))
    if not add and not rem:
        print('already up to date.'); return 0
    changes = ([{'proto': h2p[u], 'add': [proto], 'remove': []} for u in sorted(add)] +
               [{'proto': h2p[u], 'add': [], 'remove': [proto]} for u in sorted(rem) if u in h2p])
    bt = tag_ops._load_bulk_tag_script(sess)
    try:
        tag_ops.ensure_ready(sess, svc, bt)
        try:
            bt.exports_sync.bulk_apply_changes(svc, [])
        except Exception as e:
            print('  (warm-up threw, ignored: %s)' % e)
        time.sleep(0.5)
        n = tag_ops.apply_changes(bt, svc, changes, batch=150)
        print('apply_changes -> %d/%d' % (n, len(changes)))
        if n != len(changes):
            print('partial apply -- the DB mirror was NOT rewritten.'); return 1
    finally:
        bt.unload()
    for attempt in range(4):
        # CHECK FIRST, THEN WAIT (speed study 2026-09-24, Stage 2): checks at ~0 / 4 / 10 / 16 s -- the last lands where the old
        # third check did, and a write that has already settled is confirmed 4 s sooner (prune works this way since 2026-09-12).
        if attempt:
            time.sleep(4 if attempt == 1 else 6)
        q2h = {pp: format(int(d), 'x') for d, pp in pg.walk_bag_protos(sess, bag).items()}   # protos move on a tag write
        got = set()
        for t in listed():
            if t['tagProto'] == proto:
                got = {q2h[p] for p in (t.get('members') or []) if p in q2h}
        print('  verify %d: %d member(s) (want %d)' % (attempt + 1, len(got), len(want)))
        if got == want:
            # DB spelling, not the normalised one: _mirror_db matches uid_hex exactly and a stripped
            # leading zero silently updates no row (that is why a 153-member push mirrored 141).
            tag_ops._mirror_db(TAG, sorted(_db_uid.get(u, u) for u in want))
            print('%s is up to date: %d pick(s).' % (TAG, len(want)))
            return 0
    # SAY IT WITH THE TAG NAME (review 2026-09-24): the old 'client cache lag' line matched none of the prefixes the cull
    # summary keeps, so an accepted-but-unconfirmed write read as a clean push. Remote Trade fixed the same hole.
    print('%s NOT confirmed: %d missing, %d extra (client cache lag, or a write that did not land) -- the next cull '
          'settles it.' % (TAG, len(want - got), len(got - want)))
    return 0


def main():
    raise SystemExit("'Evolve for Size' is RETIRED (2026-09-29): its picks are Evolve Once / Twice members via granular_tags.evolve_advice; nothing to push from here.")
    want_all, big = picks_for_tag()
    free = sum(1 for e in big if not e['is_my_best_there'])
    print('%s: %d pick(s) (%d of them do not cost your best entry at their own stage)' % (TAG, len(want_all), free))
    if '--dry-run' in sys.argv:
        print('--dry-run: no phone contact.'); return 0

    import pogo_il2cpp as pg, tag_ops
    from reconcile_tags import ENUM_MEMBERS_JS
    from ready_gate import ensure_ready_for_writes

    if tag_ops.is_pile_tag(TAG):
        raise SystemExit('REFUSING: %r is the release pile.' % TAG)
    pg.wait_ready_to_attach(timeout_s=300)
    sess, pid = pg.get_session()
    try:
        ensure_ready_for_writes(sess, pid)
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        return sync(sess, bag, svc, want_all)
    finally:
        sess.detach()


if __name__ == '__main__':
    sys.exit(main())

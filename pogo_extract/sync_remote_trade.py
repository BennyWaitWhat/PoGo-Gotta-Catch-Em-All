"""Keep the GAME's "Remote Trade" tag (Visible to Forever Friends) equal to the current shiny offers, every cull.

User 2026-09-19: "now make this a part of your cull every time to update it."

The tag is NOT in the numbered tag list -- TaggingRpcService hands it out as its own binding, like Favorites, via
`get_RemoteTradeTagBinding` (binding+0x10 = tagProto, binding+0x18 = List<PokemonProto*>). Members are written with
the ordinary SetPokemonTags path, so this is the same proven write the tag sync uses.

  python sync_remote_trade.py            # one gated session: read binding, apply the delta, verify, mirror the DB
  python sync_remote_trade.py --dry-run  # compute and print the delta, no phone contact

NEVER creates a tag: if the binding is missing (feature locked), it says so and exits 0 -- a cull must not fail over
a trade label, and a create would make the duplicate that had to be cleaned up on 2026-09-19.
"""
import sys, os, json, time, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
os.chdir(ROOT)
import remote_trade_picks

TAG = 'Remote Trade'
norm = lambda u: format(int(u, 16), 'x')
# WHAT THE LAST sync() PROVED (2026-09-29, H04). sync() returns 0 for a verified tag but ALSO for "binding unavailable"
# and "NOT confirmed: N missing, M extra" (a trade label must never fail a cull), and sync_post_tags wrote its
# remote_trade_verified.json on ANY rc 0 -- so an unconfirmed push let the next culls SKIP the Remote Trade re-verify for
# RT_REVERIFY_H hours while the phone could still be offering an old set. verified is True only when the read-back
# of the tag equals the offers.
LAST = {'verified': False, 'outcome': 'not run'}

BINDING_JS = r"""
rpc.exports.remoteTradeBinding = function(svcAddrStr) {
    _ensureInit();
    var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
    var m, g = null;
    while ((m = IL2.cGM(svcCls, it)) && !m.isNull()) {
        if (IL2.mGN(m).readCString() === 'get_RemoteTradeTagBinding') { g = m; break; }
    }
    if (!g) return {err: 'no get_RemoteTradeTagBinding'};
    var bp = rI(g, ptr(svcAddrStr), ptr(0), null);
    if (bp.isNull()) return {err: 'binding is null (feature locked?)'};
    var out = {tagProto: bp.add(0x10).readPointer().toString(), members: []};
    try {
        var lst = bp.add(0x18).readPointer();
        if (!lst.isNull()) {
            var cnt = lst.add(0x18).readS32();
            var items = lst.add(0x10).readPointer();
            for (var j = 0; j < cnt; j++) {
                var el = items.add(0x20 + j * 8).readPointer();
                if (!el.isNull()) out.members.push(el.toString());
            }
        }
    } catch (e) { out.err = e.toString(); }
    return out;
};
"""

# THE GAME'S OWN VERDICT on who may go on Remote Trade (2026-09-22). RemoteTradeRpcService keeps it:
# Dictionary<ulong, TradeExclusionProto.ExclusionReason> (get_NonRemoteTradablePokemon) + HashSet<ulong>
# (get_TimeLockedPokemon), found by field TYPE, filled on demand by UpdateNonRemoteTradablePokemon -- the refresh
# its own Remote Trade screen runs. One refused mon sinks the whole SetPokemonTags request: 3 Deoxys (mythicals are
# never remote-tradable, though the game master calls Deoxys tradable) blocked every push 2026-09-19 -> 09-22.
# Live list: mythicals, shadows (reported as the same reason code 1), already traded, fusion components, buddy.
REFUSALS_JS = r"""
var RT = null;
function _rt() {
    if (RT) return RT;
    _ensureInit();
    var e = {};
    Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function (s) {
        if (s.name.indexOf('il2cpp_') === 0) e[s.name] = s.address;
    });
    function b(n, r, a) { return new NativeFunction(e[n], r, a); }
    RT = {oc: b('il2cpp_object_get_class', 'pointer', ['pointer']),
          flds: b('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']),
          fnm: b('il2cpp_field_get_name', 'pointer', ['pointer']),
          foff: b('il2cpp_field_get_offset', 'size_t', ['pointer']),
          ftyp: b('il2cpp_field_get_type', 'pointer', ['pointer']),
          fflg: b('il2cpp_field_get_flags', 'int', ['pointer']),
          fsget: b('il2cpp_field_static_get_value', 'void', ['pointer', 'pointer']),
          elem: b('il2cpp_class_get_element_class', 'pointer', ['pointer']),
          vsz: b('il2cpp_class_value_size', 'int', ['pointer', 'pointer']),
          cft: b('il2cpp_class_from_type', 'pointer', ['pointer']),
          tnm: b('il2cpp_type_get_name', 'pointer', ['pointer'])};
    return RT;
}
function _s(p) { return (p && !p.isNull()) ? p.readCString() : ''; }
function _fields(k) {
    var y = _rt(), it = Memory.alloc(8), f, o = {};
    it.writePointer(ptr(0));
    while ((f = y.flds(k, it)) && !f.isNull())
        o[_s(y.fnm(f))] = {off: Number(y.foff(f)), type: y.ftyp(f), f: f, stat: (y.fflg(f) & 0x10) !== 0};
    return o;
}
function _pick(o, ns) { for (var i = 0; i < ns.length; i++) if (o[ns[i]]) return o[ns[i]]; return null; }
// Dictionary<ulong,enum> / HashSet<ulong>, layouts from il2cpp metadata. The stride is the element STRUCT's value
// size: il2cpp_class_array_element_size says 8 for these shared generic arrays and misread 2 of every 3 entries.
function _coll(p, dict) {
    var y = _rt(), F = _fields(y.oc(p)), out = {keys: [], vals: [], names: {}};
    var arrF = dict ? _pick(F, ['_entries', 'entries']) : _pick(F, ['_entries', '_slots', 'm_slots']);
    var nF = _pick(F, ['_lastIndex', 'm_lastIndex']) || _pick(F, ['_count', 'count', 'm_count']);
    var freeF = _pick(F, ['_freeCount', 'freeCount']);
    var arr = p.add(arrF.off).readPointer();
    if (arr.isNull()) return out;
    var n = p.add(nF.off).readS32(), free = freeF ? p.add(freeF.off).readS32() : -1;
    var ec = y.elem(y.oc(arr)), E = _fields(ec), esz = y.vsz(ec, Memory.alloc(4));
    var hF = _pick(E, ['hashCode', 'HashCode']), xF = _pick(E, ['next', 'Next']);
    var kF = dict ? _pick(E, ['key', 'Key']) : _pick(E, ['value', 'Value']), vF = dict ? _pick(E, ['value', 'Value']) : null;
    var newStyle = hF ? /UInt32/.test(_s(y.tnm(hF.type))) : true;
    function at(i, fd) { return arr.add(0x20 + i * esz + fd.off - 0x10); }
    for (var i = 0; i < n; i++) {
        if (free !== 0) {                    // freed slots: next < -1 (new style) / hashCode -1 (old style)
            if (newStyle) { if (xF && at(i, xF).readS32() < -1) continue; }
            else if (hF && at(i, hF).readS32() < 0) continue;
        }
        out.keys.push(at(i, kF).readU64().toString());
        if (vF) out.vals.push(at(i, vF).readS32());
    }
    if (vF) {
        var EN = _fields(y.cft(vF.type));
        Object.keys(EN).forEach(function (nm) {
            if (!EN[nm].stat) return;
            var buf = Memory.alloc(8); buf.writeU64(0); y.fsget(EN[nm].f, buf); out.names[buf.readS32()] = nm;
        });
    }
    return out;
}
rpc.exports.update = function (svcAddr) {
    var svc = ptr(svcAddr), k = _rt().oc(svc);
    class_init(k);
    var m = cMN(k, 'UpdateNonRemoteTradablePokemon', 0);
    if (!m || m.isNull()) return {err: 'UpdateNonRemoteTradablePokemon not found'};
    var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
    rI(m, svc, ptr(0), exc);
    return exc.readPointer().isNull() ? {ok: true} : {err: 'managed exception'};
};
rpc.exports.read = function (svcAddr) {
    var svc = ptr(svcAddr), y = _rt(), F = _fields(y.oc(svc)), out = {excl: [], locked: []};
    Object.keys(F).forEach(function (nm) {
        var f = F[nm]; if (f.stat) return;
        var t = _s(y.tnm(f.type)), p = svc.add(f.off).readPointer();
        if (p.isNull()) return;
        if (/Dictionary.*UInt64.*ExclusionReason/.test(t)) {
            var d = _coll(p, true);
            for (var i = 0; i < d.keys.length; i++) out.excl.push([d.keys[i], d.names[d.vals[i]] || String(d.vals[i])]);
        } else if (/HashSet.*UInt64/.test(t)) out.locked = _coll(p, false).keys;
    });
    return out;
};
"""


def game_refusals(sess, pg):
    """{normalised uid: the game's reason} for every mon the game will NOT put on Remote Trade; {} if unreadable
    (then the push goes out unfiltered and a refusal shows up as 'NOT confirmed')."""
    try:
        rts = pg.pick_singleton(sess, 'Niantic.Holoholo.RemoteTrade', 'RemoteTradeRpcService')
        sc = pg.get_script_with_helpers(sess, REFUSALS_JS)
        try:
            for _ in range(2):              # the first managed call in a fresh game session can throw once
                if not sc.exports_sync.update(rts).get('err'):
                    break
            r, last = {}, None
            for _ in range(12):             # the reply lands within ~1s; stop once two reads agree
                time.sleep(0.5)
                r = sc.exports_sync.read(rts)
                n = (len(r.get('excl') or []), len(r.get('locked') or []))
                if n == last and sum(n):
                    break
                last = n
        finally:
            sc.unload()
    except Exception as e:
        print('  (game refusal list unreadable: %s -- pushing unfiltered)' % e)
        return {}
    out = {norm(format(int(k), 'x')): why for k, why in (r.get('excl') or [])}
    for k in (r.get('locked') or []):
        out.setdefault(norm(format(int(k), 'x')), 'UntradableCatchCooldown')
    return out


def sync(sess, bag, svc, want_all):
    """One Remote Trade refresh inside an ATTACHED, write-GATED session whose bag/svc singletons are already picked
    (sync_post_tags.py shares one session with Evolve for Size, speed study 2026-09-24). Its own fresh walk, binding
    read, push, verify and DB mirror -- exactly the body main() always ran. Returns the rc main() returned.
    LAST['verified'] says whether the tag was PROVEN equal to the offers (rc 0 alone does not say it)."""
    LAST.clear(); LAST.update(verified=False, outcome='started')
    import pogo_il2cpp as pg, tag_ops
    bm = pg.walk_bag_protos(sess, bag)
    h2p = {format(int(d), 'x'): pp for d, pp in bm.items()}
    p2h = {pp: uh for uh, pp in h2p.items()}
    want = {u for u in want_all if u in h2p}
    _dbc = __import__('sqlite3').connect('file:pokemon.db?mode=ro', uri=True)
    _rows = _dbc.execute('SELECT uid_hex, species_name FROM pokemon WHERE in_bag=1').fetchall()
    _dbc.close()
    _db_uid = {format(int(u, 16), 'x'): u for u, _ in _rows}
    _name = {format(int(u, 16), 'x'): n for u, n in _rows}
    refused = game_refusals(sess, pg)
    gone = {u: refused[u] for u in want if u in refused}
    want -= set(gone)
    _top = collections.Counter('%s (%s)' % (_name.get(u, '?'), why) for u, why in gone.items()).most_common(4)
    note = (' -- game refuses %d: %s' % (len(gone), ', '.join('%s x%d' % kv for kv in _top))) if gone else ''
    print('game refusal list: %d mon(s); %d of the offers refused%s' % (len(refused), len(gone), note))

    def binding():
        sc = pg.get_script_with_helpers(sess, BINDING_JS)
        try:
            return sc.exports_sync.remote_trade_binding(svc)
        finally:
            sc.unload()

    b = binding()
    if b.get('err') or not b.get('tagProto'):
        LAST['outcome'] = 'binding unavailable'
        print('Remote Trade binding unavailable (%s) -- skipped, nothing written.' % b.get('err')); return 0
    proto = b['tagProto']
    # A LISTED MEMBER THAT DOES NOT RESOLVE IS NOT "OFF THE TAG" (2026-09-23). The 18:52, 18:59 and 19:38 culls each
    # ran this straight after retire_tags (19:38 deleted no shell, so DeleteTag itself is not proven to be the
    # trigger) and pushed +456/+457 -0 -- EVERY offer, so no current member
    # resolved against the walk and no removal was sent: 9 mons that had left the offer set (reconstructed offline:
    # 7 bumped into the Transfer pile, a Goldeen now one of its variant's best 2, a shiny Rapidash past the species
    # cap) stayed visible to Forever Friends while the verify said "9 extra". Re-walk and re-read first ...
    for _try in range(2):
        unres = [p for p in (b.get('members') or []) if p not in p2h]
        if not unres:
            break
        print('  binding lists %d member(s), %d do not resolve against the bag walk -- re-walking (%d/2)'
              % (len(b['members']), len(unres), _try + 1))
        time.sleep(4)
        h2p = {format(int(d), 'x'): pp for d, pp in pg.walk_bag_protos(sess, bag).items()}
        p2h = {pp: uh for uh, pp in h2p.items()}
        # a mon evolved/released/traded since the first walk has no proto in this walk and is no longer an offer;
        # without this, h2p[u] below raises KeyError for it and the run dies before any write (he evolves and
        # releases while culls run)
        want = {u for u in want if u in h2p}
        b = binding()
        if b.get('err') or not b.get('tagProto'):
            LAST['outcome'] = 'binding unavailable on re-read'
            print('Remote Trade binding unavailable on re-read (%s) -- skipped, nothing written.' % b.get('err')); return 0
        proto = b['tagProto']
    listed = len(b.get('members') or [])
    cur = {p2h[p] for p in (b.get('members') or []) if p in p2h}
    blind = listed - len(cur)
    # A REFUSED MON ALREADY ON THE TAG IS FROZEN (2026-09-26): the game refuses ANY Remote Trade write on it -- a REMOVAL
    # too -- and one refused mon sinks the whole SetPokemonTags request, adds included. A gym-deployed Gyarados kept a
    # Tauros and a Swampert off the tag for two culls while every verify said "2 missing, 2 extra". Leave it where it is
    # (it comes off the pass after it leaves the gym / stops being the buddy) and judge the tag without it.
    frozen = {u for u in cur if u in refused}
    add, rem = want - cur, (cur - want) - frozen
    if frozen:
        print('  left as they are -- the game refuses Remote Trade writes on them now: %s' % ', '.join(
            '%s (%s)' % (_name.get(u, '?'), refused[u]) for u in sorted(frozen)))
    print('%s: %d on the tag%s | +%d -%d' % (TAG, len(cur), (' (%d listed, %d UNRESOLVED -- their removals cannot '
          'be computed from this read)' % (listed, blind)) if blind else '', len(add), len(rem)))
    if not add and not rem and not blind:
        LAST.update(verified=True, outcome='already up to date')
        print('already up to date%s.' % note); return 0

    def push(chg):
        bt = tag_ops._load_bulk_tag_script(sess)
        try:
            tag_ops.ensure_ready(sess, svc, bt)
            try:
                bt.exports_sync.bulk_apply_changes(svc, [])
            except Exception as e:
                print('  (warm-up threw, ignored: %s)' % e)
            time.sleep(0.5)
            return tag_ops.apply_changes(bt, svc, chg, batch=150)
        finally:
            bt.unload()

    def verify(label):
        got = set()
        for attempt in range(4):
            # CHECK FIRST, THEN WAIT (speed study 2026-09-24, Stage 2): checks at ~0 / 4 / 10 / 16 s -- the last lands where the old
            # third check did, and a write that has already settled is confirmed 4 s sooner (prune works this way since 2026-09-12).
            if attempt:
                time.sleep(4 if attempt == 1 else 6)
            # RE-WALK: tagging reallocates the PokemonProto pointers, so the map from the first walk no longer
            # resolves the members and the tag reads unchanged (2026-09-19).
            _q2h = {pp: format(int(d), 'x') for d, pp in pg.walk_bag_protos(sess, bag).items()}
            lst = binding().get('members') or []
            got = ({_q2h.get(p) for p in lst} - {None}) - frozen     # frozen members stay on the tag by design
            k = sum(1 for p in lst if p not in _q2h)       # the same silent drop, made visible in the log
            LAST['unresolved'] = k                          # R-B review: members the read-back could not name prove nothing
            print('  verify%s %d: %d member(s) (want %d)%s' % (label, attempt + 1, len(got), len(want),
                  (' -- %d listed did not resolve' % k) if k else ''))
            if got == want:
                break
        return got

    changes = ([{'proto': h2p[u], 'add': [proto], 'remove': []} for u in sorted(add)] +
               [{'proto': h2p[u], 'add': [], 'remove': [proto]} for u in sorted(rem) if u in h2p])
    if changes:
        n = push(changes)
        print('apply_changes -> %d/%d' % (n, len(changes)))
        if n != len(changes):
            LAST['outcome'] = 'partial apply'
            print('partial apply -- the DB mirror was NOT rewritten.'); return 1
    got = verify('')
    swept = sorted(got - want)
    unseen = [u for u in swept if u not in rem]      # no removal was ever sent: the first read could not see them
    if swept:
        # ... and sweep what it could not see. `unseen` are REAL members, not lag: the fresh walk above just
        # resolved them and the delta never carried their removal (anything else in `swept` is a removal already
        # sent that still shows; re-sending it is idempotent). A removal only takes a mon OFF the trade offer -- it
        # cannot reach the Transfer pile. Fresh walk + fresh tag proto, never the pre-push one: a tag write
        # reallocates the protos, and a stale pointer handed to SetPokemonTags throws (tag_ops note 6).
        _h2p = {format(int(d), 'x'): pp for d, pp in pg.walk_bag_protos(sess, bag).items()}
        _tp = binding().get('tagProto')
        if _tp and _tp != '0x0':
            fix = [{'proto': _h2p[u], 'add': [], 'remove': [_tp]} for u in swept if u in _h2p and u not in refused]
            n2 = push(fix) if fix else 0
            print('apply_changes (sweep: %d member(s) the first read could not see, %d removal(s) re-sent) -> %d/%d -- %s'
                  % (len(unseen), len(swept) - len(unseen), n2, len(fix), ', '.join(
                      '%s %d' % kv for kv in collections.Counter(_name.get(u, '?') for u in swept).most_common(6))))
            got = verify(' after sweep')
        else:
            print('  sweep skipped: the binding returned no tag proto on re-read -- nothing removed')
    if got == want:
        # DB spelling, not the normalised one: _mirror_db matches uid_hex exactly and a stripped
        # leading zero silently updates no row (that is why a 153-member push mirrored 141).
        tag_ops._mirror_db(TAG, sorted(_db_uid.get(u, u) for u in want))
        if frozen:
            note += '; %d left on it until the game allows a write (%s)' % (len(frozen), ', '.join(
                '%s: %s' % (_name.get(u, '?'), refused[u]) for u in sorted(frozen)))
        print('%s is up to date: %d offer(s)%s%s.' % (TAG, len(want), note, (
            '; swept %d member(s) the first read could not see (it resolved %d of %d listed)%s'
            % (len(unseen), len(cur), listed, (', re-sent %d removal(s)' % (len(swept) - len(unseen)))
               if len(swept) > len(unseen) else '')) if swept else ''))
        _k = LAST.get('unresolved') or 0            # 'already up to date' needs blind == 0; the pushed path needs k == 0
        LAST.update(verified=not _k, outcome='pushed and verified' if not _k else
                    'pushed; %d listed member(s) did not resolve on the read-back' % _k)
        return 0
    # NOT "cache lag": from 2026-09-19 23:37 a refused mon sank every push for three days behind that line, and
    # full_audit's summary never showed it. Say it plainly, starting with the tag name so the summary does.
    miss, extra = want - got, got - want
    top = collections.Counter(_name.get(u, '?') for u in miss).most_common(5)
    topx = collections.Counter(_name.get(u, '?') for u in extra).most_common(5)
    print('Remote Trade NOT confirmed: %d offer(s) missing, %d extra -- missing incl. %s; extra incl. %s'
          % (len(miss), len(extra), ', '.join('%s %d' % kv for kv in top) or 'none',
             ', '.join('%s %d' % kv for kv in topx) or 'none'))
    LAST['outcome'] = 'NOT confirmed (%d missing, %d extra)' % (len(miss), len(extra))
    return 0


def main():
    want_all, stats = remote_trade_picks.compute()
    want_all = {norm(u) for u in want_all}
    print('Remote Trade offers computed: %d  (%s)' % (len(want_all), ', '.join('%s %d' % kv for kv in sorted(stats.items()))))
    if '--dry-run' in sys.argv:
        print('--dry-run: no phone contact.'); return 0

    import pogo_il2cpp as pg, tag_ops
    from ready_gate import ensure_ready_for_writes

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

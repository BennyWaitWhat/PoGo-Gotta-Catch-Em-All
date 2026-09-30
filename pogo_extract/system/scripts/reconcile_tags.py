"""Reconcile the CLIENT TAG CACHE with pokemon.db auth_tag_names.

READ THIS FIRST -- WHAT "server" MEANT HERE WAS WRONG (corrected 2026-09-02).
The member sets below do NOT come from the server. They come from
`GetCachedTagToPokemonBindingForIndex`, i.e. the PoGo client's in-memory CACHE. A tag write that
reached the client but never persisted server-side looks perfectly in-sync here. That is not
hypothetical: it is how a 480-member Transfer tag silently vanished on 2026-07-25, and why
verify_tags_live.py exists (it RESTARTS PoGo so the client refetches from the server, then calls this
script). Treat a clean run here as "the client agrees with the DB", never as server proof.

For each tag (or a named subset), computes:
  - CACHED member set: UIDs derived from the TaggingRpcService binding's cached
    PokemonProto* member list, reverse-mapped to UIDs via a full bag-walk.
  - DB member set: UIDs with the tag name present in auth_tag_names.

Reports per tag: in_both, cache_only, db_only.

MANAGED vs UNTRACKED TAGS (2026-09-02): only the tags this engine owns (prune_tags.PLAN + "Evolve
Shiny") count toward the drift verdict. The user's own in-game tags are listed separately as
informational and never set the exit code, are never touched by --fix-server, and never print the
word DRIFT. Before this, ONE personal tag produced cache=N / db=0 -> DRIFT -> verify_tags_live.py
returned 1, i.e. a guaranteed false FAIL on the only gate that reads real device state -- exactly the
way to train an operator into ignoring it. If prune_tags.PLAN cannot be imported the allowlist is
disabled and EVERY tag is judged, so a broken import can never hide real drift.

Modes:
  --report       (default) Read-only diff table. Exit 1 if a MANAGED tag has drifted.
  --fix-db       Make DB match the CLIENT CACHE (no device writes). See the caveat above.
  --fix-server   Make the device match DB: bulk_tag_many for db_only
                 (using LIVE bag-walk protos, never stale cached ones)
                 and bulk_untag_one for cache_only.
  --tags T1,T2   Restrict to a comma-separated tag subset.

Requires PoGo running + Frida reachable. DB path: pokemon.db next to
pogo_il2cpp.py (repo root).
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import argparse
import os
import sqlite3
import time

# -- path setup: repo root is two levels up from system/scripts/ ---------------
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, REPO)

import pogo_il2cpp as pg

DB_PATH = os.path.join(REPO, 'pokemon.db')
BULK_TAG_JS = os.path.join(REPO, 'bulk_tag.js')

# --------------------------------------------------------------------------- #
#  Frida JS: enumerate every tag's name + member proto pointers on the server  #
# --------------------------------------------------------------------------- #
ENUM_MEMBERS_JS = r"""
function enumerateAllTagMembers(svcAddrStr) {
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
        if (bp.isNull()) {
            // H06-11 (2026-09-29): skipped in silence before -- a tag that could not be read simply vanished, and a vanished
            // release-pile tag with an empty want list verified "OK" while it still held members on the phone.
            out.push({idx: i, name: null, tagProto: '0x0', tagId: '', bindingAddr: '0x0', members: [], memberUids: [],
                      unreadable: 'null binding for tag index ' + i});
            continue;
        }
        var tagProto = bp.add(0x10).readPointer();
        // Name (UTF-16 at tagProto+0x40)
        var name = '', unreadable = '';
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
        } catch(e) { unreadable = 'name: ' + e; }
        // Member proto pointers: binding+0x18 -> List; items@+0x10; count@+0x18;
        // element j at items+0x20+j*8 is a PokemonProto*.
        var members = [];
        // memberUids[j] = the uid INSIDE members[j] (PokemonProto.id_ @0x20, UInt64; proto_layout.json, and equal to
        // uid_hex on all 5,775 stored protos 2026-09-26), '' if unreadable. A binding can keep an OLDER proto object
        // of the same mon after a write reallocates it: the pointer then misses the bag walk, the uid does not.
        var memberUids = [];
        try {
            var lst = bp.add(0x18).readPointer();
            if (!lst.isNull()) {
                var cnt = lst.add(0x18).readS32();
                var items = lst.add(0x10).readPointer();
                for (var j = 0; j < cnt; j++) {
                    var el = items.add(0x20 + j * 8).readPointer();
                    members.push(el.toString());
                    var mu = '';
                    try { if (!el.isNull()) mu = el.add(0x20).readU64().toString(); } catch(e2) {}
                    memberUids.push(mu);
                }
            }
        } catch(e) { unreadable = (unreadable ? unreadable + '; ' : '') + 'members (after ' + members.length + '): ' + e; }
        var tagId = '';
        try { tagId = tagProto.add(0x38).readU64().toString(); } catch(e) {}
        out.push({idx: i, name: name, tagProto: tagProto.toString(), tagId: tagId,
                  bindingAddr: bp.toString(), members: members, memberUids: memberUids, unreadable: unreadable});
    }
    return out;
}
rpc.exports.enumerateAllTagMembers = enumerateAllTagMembers;
// pokemonTagIds_ of LIVE protos (PokemonProto+0x180, RepeatedField<UInt64>: array_@0x10, count_@0x18, items @array+0x20+8i
// -- the layout pogo_pipeline reads breadMoves_ with on every walk). The server's own record of the mon's tags; null =
// unreadable. Plain memory reads, no managed call. (2026-09-26, stale-binding confirmation)
rpc.exports.liveTagIds = function (ptrs) {
    var out = {};
    for (var i = 0; i < ptrs.length; i++) {
        var ids = null;
        try {
            var rf = ptr(ptrs[i]).add(0x180).readPointer();
            ids = [];
            if (!rf.isNull()) {
                var arr = rf.add(0x10).readPointer(), n = rf.add(0x18).readS32();
                if (!arr.isNull() && n > 0 && n < 200)
                    for (var j = 0; j < n; j++) ids.push(arr.add(0x20 + j * 8).readU64().toString());
            }
        } catch (e) { ids = null; }
        out[ptrs[i]] = ids;
    }
    return out;
};
"""


# --------------------------------------------------------------------------- #
#  DB helpers                                                                  #
# --------------------------------------------------------------------------- #
def _like_escape(s):
    r"""Escape LIKE wildcards so a tag NAME is matched literally.

    tag_name comes from the device (`tag_info['name']`) -- text the user typed in-game. Unescaped, a
    tag containing % or _ over-matches auth_tag_names: db_uids inflates, db_only inflates, and under
    --fix-server that drives real bulk_tag writes onto mons that never carried the tag. The engine's
    own 12 names contain no wildcards, so this only ever mattered for user-created tags -- which is
    precisely the set this script had no allowlist for."""
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def db_members_for_tag(conn, tag_name):
    """Return set of uid_hex for in-bag pokemon carrying `tag_name`."""
    rows = conn.execute(
        "SELECT uid_hex FROM pokemon WHERE in_bag=1 "
        "AND (';' || COALESCE(auth_tag_names,'') || ';') LIKE ? ESCAPE '\\'",
        (f'%;{_like_escape(tag_name)};%',)
    ).fetchall()
    return {r[0] for r in rows}


def managed_tag_names():
    """Tag names THIS ENGINE owns. Returns None to mean "no allowlist -- judge everything".

    Source of truth is prune_tags.PLAN (the push plan) plus 'Evolve Shiny', which refresh_evolve_shiny
    owns. Imported lazily: prune_tags imports ENUM_MEMBERS_JS from this module, so a module-level
    import here would be circular.

    FAIL-CLOSED BY DESIGN: if the import fails we return None and every tag is judged, as before. An
    allowlist that came up short would DEMOTE real drift on a managed tag to "informational", which is
    the one outcome worse than a false failure."""
    cwd = os.getcwd()          # prune_tags does os.chdir(ROOT) at import; don't let a lookup move us
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import prune_tags
        return set(prune_tags.PLAN) 
    except Exception as e:
        print(f'  [managed-set] could not import prune_tags.PLAN ({e}) -- judging EVERY server tag '
              f'(fail-closed: real drift is never hidden)')
        return None
    finally:
        try:
            os.chdir(cwd)
        except Exception:
            pass


def db_add_tag(conn, uid_hex, tag_name):
    """Append tag_name to auth_tag_names for uid_hex (idempotent)."""
    row = conn.execute(
        "SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uid_hex,)
    ).fetchone()
    if row is None:
        return
    tags = [t for t in (row[0] or '').split(';') if t]
    if tag_name not in tags:
        tags.append(tag_name)
        conn.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
                     (';'.join(tags), uid_hex))


def db_remove_tag(conn, uid_hex, tag_name):
    """Remove tag_name from auth_tag_names for uid_hex (idempotent)."""
    row = conn.execute(
        "SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uid_hex,)
    ).fetchone()
    if row is None:
        return
    tags = [t for t in (row[0] or '').split(';') if t]
    if tag_name in tags:
        tags.remove(tag_name)
        conn.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
                     (';'.join(tags) if tags else None, uid_hex))


# --------------------------------------------------------------------------- #
#  UID conversion                                                              #
# --------------------------------------------------------------------------- #
def stale_members(sess, tags, live_hex_of, hex_to_proto):
    """STALE BINDINGS (2026-09-26). A tag write reallocates the mon's proto and the binding can keep the OLD object: its
    pointer then misses the bag walk although the mon is still in the bag. Returns {tag idx: (stale, confirmed)}:
      stale     -- live uids the binding points at through an older proto (PokemonProto.id_ @0x20 == uid_hex on all
                   5,775 stored protos). Enough to call a mon an EXTRA: surfacing it can only lead to a removal.
      confirmed -- the subset whose LIVE proto's pokemonTagIds_ also lists this tag's id -- the only proof an ADD landed.
                   Unconfirmed entries stay short / db_only, so a write the game dropped is still re-added and reported
                   (review 2026-09-26: counting the stale object alone hid exactly that case).
    `tags`: enumerate_all_tag_members records; `live_hex_of(dec_uid)` -> this script's uid key or None (not live)."""
    out, need = {}, {}
    for t in tags:
        _mu = t.get('memberUids') or []
        st = set()
        for j, pp in enumerate(t.get('members') or []):
            if j < len(_mu) and _mu[j]:
                uh = live_hex_of(_mu[j])
                if uh and hex_to_proto.get(uh) != pp:
                    st.add(uh)
        out[t.get('idx', t['name'])] = (st, set())
        for uh in st:
            need.setdefault(hex_to_proto[uh], set())
    if not need:
        return out
    try:
        sc = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
        try:
            ids = sc.exports_sync.live_tag_ids(list(need))
        finally:
            sc.unload()
    except Exception as _e:        # fail CLOSED: nothing confirmed -> unconfirmed members stay short / re-added
        print(f'  (stale-binding confirmation skipped: {_e})')
        return out
    for t in tags:
        st, conf = out[t.get('idx', t['name'])]
        for uh in st:
            live = ids.get(hex_to_proto[uh])
            if live and t.get('tagId') and t['tagId'] in live:
                conf.add(uh)
    return out


def uid_hex_to_dec(uid_hex):
    """'0x01234ABCD' or '01234ABCD' -> decimal string."""
    return str(int(uid_hex, 16))


def uid_dec_to_hex(uid_dec):
    """Decimal string -> lowercase hex without 0x prefix (matches DB uid_hex)."""
    return format(int(uid_dec), 'x')


# --------------------------------------------------------------------------- #
#  Reverse-map: proto pointer -> uid_hex via bag-walk                          #
# --------------------------------------------------------------------------- #
def build_proto_to_uidhex(bag_walk_map, all_uid_hexes):
    """bag_walk_map: {uid_dec_str: proto_ptr_str}.
    all_uid_hexes: iterable of hex UIDs from DB.
    Returns {proto_ptr_str: uid_hex_str}.
    """
    dec_to_hex = {}
    for uh in all_uid_hexes:
        dec_to_hex[uid_hex_to_dec(uh)] = uh
    result = {}
    for uid_dec, proto_ptr in bag_walk_map.items():
        uh = dec_to_hex.get(uid_dec)
        if uh:
            result[proto_ptr] = uh
    return result


# --------------------------------------------------------------------------- #
#  Main logic                                                                  #
# --------------------------------------------------------------------------- #
def run(args, sess=None, pid=None):
    """sess / pid (2026-09-30, cull speed pick 2): sync_post_tags.py --reconcile passes its own post-push session, so
    the report, Remote Trade, the tag order and retire share ONE attach. That session is still a fresh one next to
    prune's (the independence this report exists for); it is left attached for its owner. None -> attach here."""
    # -- DB setup --------------------------------------------------------------
    conn = sqlite3.connect(DB_PATH)
    all_uid_hexes = {r[0] for r in conn.execute(
        "SELECT uid_hex FROM pokemon WHERE in_bag=1"
    )}
    print(f'DB: {len(all_uid_hexes)} in-bag pokemon')

    # -- Frida attach ----------------------------------------------------------
    own = sess is None
    if own:
        sess, pid = pg.get_session()
    print(f'Frida attached, pid={pid}' + ('' if own else ' (shared post-push session)'))
    try:
        bag_addr = pg.pick_singleton(
            sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc_addr = pg.pick_singleton(
            sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        print(f'BagImpl @ {bag_addr}')
        print(f'TaggingRpcService @ {svc_addr}')

        # Full bag-walk: {uid_dec_str: proto_ptr_str}
        bag_map = pg.walk_bag_protos(sess, bag_addr)
        print(f'Bag-walk returned {len(bag_map)} entries')

        # Reverse map: proto_ptr -> uid_hex
        proto_to_hex = build_proto_to_uidhex(bag_map, all_uid_hexes)
        # Forward map for fix-server: uid_hex -> fresh proto_ptr
        hex_to_proto = {v: k for k, v in proto_to_hex.items()}
        dec_to_live_hex = {uid_hex_to_dec(uh): uh for uh in proto_to_hex.values()}   # stale-binding fallback (2026-09-26)

        # Enumerate server tags + member proto pointers
        enum_script = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
        srv_tags = enum_script.exports_sync.enumerate_all_tag_members(svc_addr)
        enum_script.unload()
        _stale = stale_members(sess, srv_tags, dec_to_live_hex.get, hex_to_proto)
        print(f'Server reports {len(srv_tags)} tags\n')

        # Optional filter
        tag_filter = None
        if args.tags:
            tag_filter = set(t.strip() for t in args.tags.split(','))

        # -- Per-tag reconciliation -------------------------------------------
        # column says "cached", not "server": these members come from
        # GetCachedTagToPokemonBindingForIndex (the client cache), not from the server.
        header = (f'{"Tag":<18} {"cached":>7} {"db":>7} {"both":>7} '
                  f'{"cch_only":>8} {"db_only":>8}  status')
        print(header)
        print('-' * len(header))

        managed = managed_tag_names()      # None => no allowlist, judge everything (fail-closed)
        untracked = []
        unverified = []                    # H06-11: advisory managed tags whose member list could not be read this pass
        srv_names = set()
        diffs_found = False
        pile_unreadable = False            # R-B review: an unreadable pile tag fails EVERY mode, --fix-* included
        # Is the PILE tag readable BY NAME in this enumeration? (R-B review) With it proven readable, a nameless / null binding
        # is some other tag -- advisory, so one odd binding cannot fail every sync forever. Without it, any nameless binding
        # could BE the pile and fails the verdict (fail closed).
        _tops = __import__('tag_ops')
        _pile_seen = any(t.get('name') and not t.get('unreadable') and _tops.is_pile_tag(t['name']) for t in srv_tags)
        # Load bulk_tag.js only if --fix-server (lazy)
        bt_script = None
        if args.fix_server:
            bt_script = sess.create_script(
                open(BULK_TAG_JS, encoding='utf-8').read())
            bt_script.on('message', lambda m, d: None)
            bt_script.load()
            bt_script.exports_sync.init_status()

        for tag_info in srv_tags:
            name = tag_info['name']
            srv_names.add(name)
            # UNREADABLE IS NOT EMPTY (2026-09-29, H06-11). A tag whose binding, name or member list could not be read used
            # to be skipped / nameless / short with no flag, and the table below judged the partial read -- an empty pile
            # plus an unreadable Transfer tag printed "All tags in sync." while the phone's tag still held members. The
            # PILE tag, or a tag whose NAME is unknown (it could be the pile), fails the verdict; an advisory managed tag is
            # listed as NOT VERIFIED this pass (labels, like prune's deferrals); a personal tag is noted.
            # a NAMELESS binding is unknown too, thrown or not (R-B review): a null name pointer or a length outside 1..99
            # reads back '' with no exception, and was then filed below as a personal tag -- the pile never judged
            _unr = tag_info.get('unreadable') or ('' if name else 'name read back empty')
            if _unr and (not tag_filter or not name or name in tag_filter):
                _who = name or ('tag #%s (name unknown)' % tag_info.get('idx'))
                _pile = bool(name and _tops.is_pile_tag(name)) or (not name and not _pile_seen)
                if _pile or managed is None or not name or name in managed:
                    print(f'{_who:<18} {"?":>7} {"?":>7} {"?":>7} {"?":>8} {"?":>8}  UNREADABLE -- {_unr}'
                          + ('' if _pile else '  (advisory: NOT VERIFIED this pass)'))
                    if _pile:
                        diffs_found = pile_unreadable = True
                    else:
                        unverified.append(_who)
                else:
                    untracked.append((name + ' (UNREADABLE)', len(tag_info['members'])))
                continue
            if tag_filter and name not in tag_filter:
                continue
            if managed is not None and name not in managed:
                # A personal in-game tag. Report it, never judge it, never write to it. Deliberately
                # prints no 'DRIFT' token: verify_tags_live.py fails on any line ending in DRIFT, so
                # emitting one here would hard-fail every sync for a tag the engine does not manage.
                untracked.append((name, len(tag_info['members'])))
                continue

            # Cached member set (uid_hex) via reverse-map
            srv_proto_ptrs = tag_info['members']
            srv_uids = set()
            unmapped = 0
            _mu = tag_info.get('memberUids') or []
            for j, pp in enumerate(srv_proto_ptrs):
                uh = proto_to_hex.get(pp)
                if uh:
                    srv_uids.add(uh)
                elif not (j < len(_mu) and _mu[j] and dec_to_live_hex.get(_mu[j])):
                    unmapped += 1           # not even the uid it carries is in the bag: transferred / unreadable
            # STALE BINDINGS (stale_members): an older proto of a live mon. It counts as a member for server_only (an
            # extra -- only ever leads to a removal) and for db_only only when the live proto confirms the tag.
            _st, _conf = _stale.get(tag_info.get('idx', name), (set(), set()))
            srv_uids_conf = srv_uids | _conf
            srv_uids = srv_uids | _st
            if _st:
                print(f'  [{name}] {len(_st)} member(s) bound to an older proto of a live mon -- mapped by uid, '
                      f'{len(_conf)} confirmed by the live tag list')
            if unmapped:
                print(f'  [{name}] WARNING: {unmapped} cached member proto(s) '
                      f'not in live bag (transferred / stale cache)')

            # DB member set
            db_uids = db_members_for_tag(conn, name)

            in_both = srv_uids & db_uids
            server_only = srv_uids - db_uids
            # GHOST BINDINGS (2026-09-26): server_only only through an UNCONFIRMED stale binding = the mon's own tag list
            # lacks the tag. Noise on an advisory tag; still drift on the release pile.
            _ghost = server_only & (srv_uids - srv_uids_conf)
            if _ghost and not __import__('tag_ops').is_pile_tag(name):
                print(f'  [{name}] {len(_ghost)} stale binding(s) the live tag list does not confirm -- ignored')
                server_only = server_only - _ghost
            # a DB member the user RELEASED since the mirror was written is not on the device and cannot be
            # tagged -- not drift (2026-09-12: 40 pile mons released mid-sync failed every pass). Same rule as
            # prune_tags' verify. The next recrawl marks them departed.
            db_only = (db_uids - srv_uids_conf) & set(proto_to_hex.values())
            # HATCHLINGS: isEgg_ stays 1 on a fresh hatch for a day or two and the game silently ignores tag
            # writes on it, so the mirror carries the tag before the device does. Deferred, not drift (same rule
            # as prune_tags' verify; 2026-09-13 Squirtle 75%, three passes in a row).
            _hatch = set()
            if db_only or server_only:
                try:
                    _c3 = sqlite3.connect('file:pokemon.db?mode=ro', uri=True)
                    _hatch = {u for u in (db_only | server_only) if (_c3.execute('SELECT is_egg FROM pokemon WHERE uid_hex=?', (u,)).fetchone() or [0])[0] == 1}
                    _c3.close()
                except Exception as _he:
                    print(f'  (hatchling check skipped: {_he})')
                db_only = db_only - _hatch; server_only = server_only - _hatch

            ok = (not server_only and not db_only)
            status = 'OK' if ok else 'DRIFT'
            if not ok:
                diffs_found = True
            print(f'{name:<18} {len(srv_uids):>7} {len(db_uids):>7} '
                  f'{len(in_both):>7} {len(server_only):>8} '
                  f'{len(db_only):>8}  {status}')
            if _hatch:
                print(f'    deferred     {len(_hatch)} hatchling(s) still flagged isEgg (tag write ignored until it clears): {", ".join(sorted(_hatch))}')

            # Detailed drift lines
            if not ok and (args.fix_db or args.fix_server or args.verbose):
                for uh in sorted(server_only):
                    print(f'    server_only  {uh}')
                for uh in sorted(db_only):
                    print(f'    db_only      {uh}')

            # -- --fix-db: make DB match server --------------------------------
            if args.fix_db and not ok:
                for uh in server_only:
                    db_add_tag(conn, uh, name)
                for uh in db_only:
                    db_remove_tag(conn, uh, name)
                conn.commit()
                print(f'    -> DB fixed: +{len(server_only)} '
                      f'-{len(db_only)}')

            # -- --fix-server: make server match DB ----------------------------
            # THE PILE HAS ONE ROUTE (design review 2026-09-24, X1): preflight_transfer -> prune_tags --atomic, behind
            # the pre-flight stamp. --fix-server used to bulk_tag_many straight onto the Transfer tag -- no stamp, no
            # gate -- and untag from it. It refuses the pile tag before any write; everything else is unchanged.
            if args.fix_server and not ok and __import__('tag_ops').is_pile_tag(name):
                print(f'    -> REFUSED: {name!r} is the release pile -- only prune_tags --atomic (behind the '
                      f'pre-flight stamp) may write it; nothing written')
            elif args.fix_server and not ok:
                tag_proto_str = tag_info['tagProto']

                # Tag the db_only onto server (using LIVE bag-walk protos)
                if db_only:
                    live_protos = []
                    for uh in db_only:
                        lp = hex_to_proto.get(uh)
                        if lp:
                            live_protos.append(lp)
                        else:
                            print(f'    ! {uh}: no live proto in bag '
                                  f'(cannot server-add)')
                    if live_protos:
                        r = bt_script.exports_sync.bulk_tag_many(
                            svc_addr, tag_proto_str, live_protos)
                        ok_tag = r.get('ok', False)
                        built = r.get('built', 0)
                        print(f'    -> server bulk_tag_many: ok={ok_tag}, '
                              f'built={built}/{len(live_protos)}')
                        if not ok_tag:
                            print(f'       err: {r.get("err")}')

                # Untag the server_only from server.
                # SAFETY: additive-only by default. Stripping server members
                # because DB lacks them is the exact path that wiped "1 GL IV"
                # (143 members) when the DB was momentarily stale from a failed
                # rename mirror. Require explicit --allow-untag, and refuse to
                # strip the majority of a tag without --force-mass.
                if server_only and not args.allow_untag:
                    print(f'    -> SKIP untag of {len(server_only)} server '
                          f'member(s) (additive-only; pass --allow-untag to '
                          f'remove). Server-only usually means DB is stale, '
                          f'not that the tag is wrong.')
                elif server_only and len(server_only) > 0.5 * max(len(srv_uids), 1) \
                        and not args.force_mass:
                    print(f'    -> REFUSE untag: would strip {len(server_only)}/'
                          f'{len(srv_uids)} members (>50%). This looks like DB '
                          f'staleness, not drift. Pass --force-mass to override.')
                elif server_only:
                    untag_ok = 0
                    for uh in server_only:
                        # Use live proto from bag-walk if available,
                        # fall back to the binding's stale proto for untag
                        # (untag just needs the right identity, not freshness).
                        lp = hex_to_proto.get(uh)
                        if not lp:
                            # try stale proto from binding member list
                            for pp in srv_proto_ptrs:
                                if proto_to_hex.get(pp) == uh:
                                    lp = pp
                                    break
                        if not lp:
                            print(f'    ! {uh}: no proto found for untag')
                            continue
                        r = None
                        for attempt in range(3):
                            r = bt_script.exports_sync.bulk_untag_one(
                                svc_addr, lp, tag_proto_str)
                            if r.get('ok'):
                                break
                            time.sleep(0.5)
                        if r and r.get('ok'):
                            untag_ok += 1
                        else:
                            print(f'    ! untag {uh}: {r}')
                    print(f'    -> server untag: {untag_ok}/{len(server_only)}')

        # Check for tags in DB but not on server
        if not tag_filter:
            db_all_tags = set()
            rows = conn.execute(
                "SELECT DISTINCT auth_tag_names FROM pokemon "
                "WHERE in_bag=1 AND auth_tag_names IS NOT NULL "
                "AND auth_tag_names != ''"
            ).fetchall()
            for r in rows:
                for t in r[0].split(';'):
                    t = t.strip()
                    if t:
                        db_all_tags.add(t)
            db_not_server = db_all_tags - srv_names
            if managed is not None:
                # Only MANAGED tags count. This line is one of verify_tags_live.py's three failure
                # needles (it exists to catch the brand-new-account case: 10 engine tags absent from the
                # server while every per-tag row looked fine). A personal tag left in auth_tag_names by
                # an old --fix-db must not trip that. Narrowing it makes the needle sharper, not weaker.
                untracked_in_db = sorted(db_not_server - managed)
                db_not_server &= managed
                if untracked_in_db:
                    print(f'\nUntracked DB tags not on the device (informational): {untracked_in_db}')
            if db_not_server:
                print(f'\nDB tags NOT on server: {sorted(db_not_server)}')
                diffs_found = True

        if bt_script:
            bt_script.unload()

        if untracked:
            print('\nUntracked (informational -- your own in-game tags; the engine neither manages '
                  'nor touches these, and they do not affect the verdict):')
            for nm, n in sorted(untracked):
                print(f'  {nm:<18} {n:>7} cached member(s)')

        if unverified:
            print('\nNOT VERIFIED this pass (member list unreadable, advisory tags): %s' % sorted(unverified))
        print()
        # no remedy is named: nothing in the cull re-reads tags from the server any more (verify_tags_live is cache-only,
        # PoGo is never restarted -- user rule 2026-09-25; R-B review, the H06-4 family)
        print('[CLIENT CACHE -- not server proof; nothing in the cull re-reads the tags from the server]')
        if pile_unreadable:
            print('Drift detected.' + (' (an UNREADABLE pile / nameless tag -- nothing was fixed for it)'
                                       if (args.fix_db or args.fix_server) else ''))
        elif diffs_found:
            print('Drift detected.' if not (args.fix_db or args.fix_server)
                  else 'Fixes applied above.')
        else:
            # the advisory tags not verified this pass ride on the verdict line itself, the one full_audit echoes
            print('All tags in sync.' + ((' (%d advisory tag(s) NOT VERIFIED this pass: %s)' % (len(unverified), sorted(unverified)))
                                         if unverified else ''))
        # EXIT CODE (2026-09-02). run()'s result was computed and then thrown away by main(), and
        # `grep -n 'sys.exit'` found nothing in this file -- so /api/sync's final step could print
        # "Drift detected." and the job still reported done. Only MANAGED tags reach diffs_found, so a
        # personal in-game tag can no longer hard-fail a sync (that is why the allowlist had to land
        # first). --fix-* runs report 0 when the fixes were applied.
        return 1 if (pile_unreadable or (diffs_found and not (args.fix_db or args.fix_server))) else 0

    finally:
        if own:
            sess.detach()
        conn.close()


def main():
    p = argparse.ArgumentParser(
        description='Reconcile the PoGo CLIENT TAG CACHE with pokemon.db auth_tag_names. '
                    'Not server proof -- and nothing re-reads the server: PoGo is never restarted (user rule 2026-09-25).')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--report', action='store_true', default=True,
                      help='Read-only diff table (default). Exit 1 if a MANAGED tag has drifted.')
    mode.add_argument('--fix-db', action='store_true',
                      help='Make DB match the CLIENT CACHE (no device writes). NOTE: the cache is not '
                           'the server -- this can record a tag write that never persisted.')
    mode.add_argument('--fix-server', action='store_true',
                      help='Make the device match DB (tags/untags on device)')
    p.add_argument('--tags', type=str, default=None,
                   help='Comma-separated tag names to reconcile')
    p.add_argument('--verbose', '-v', action='store_true',
                   help='Show individual drift UIDs even in report mode')
    p.add_argument('--allow-untag', action='store_true',
                   help='Permit --fix-server to REMOVE server members that are '
                        'absent from DB. OFF by default: --fix-server is '
                        'additive-only (it only ADDS db_only members). Untag is '
                        'the path that stripped "1 GL IV" when DB was stale.')
    p.add_argument('--force-mass', action='store_true',
                   help='Override the mass-strip guard (allow untagging >50%% of '
                        "a tag's members). Almost never what you want.")
    args = p.parse_args()
    return run(args)


if __name__ == '__main__':
    sys.exit(main())

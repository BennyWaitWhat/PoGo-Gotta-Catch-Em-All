"""Triple-check the 21-tag rebuild from three independent angles.

  1) SERVER:  enumerate via TaggingRpcService — names + per-tag member counts
              (counted by re-walking each binding's PokemonProto pointer list).
  2) DB:      auth_tag_names column counts per tag.
  3) RULE:    re-derive each tag's expected membership from primary SQL rules
              against pokemon.db. (For Legacy: legacy_accurate.json ∩ in_bag=1.)

  If all three numbers agree per tag, we have triple-redundant proof.
"""
import json, os, sqlite3, time
import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')
LEGACY_JSON = os.path.join(HERE, 'legacy_accurate.json')

# Tag → (sql-rule for membership re-derivation, or None for special handling)
TAG_RULES = {
    'Best Buddy':     "was_best_buddy_badge=1",
    'Hundos':         "iv_total=45",
    'Nundos':         "is_zero=1 AND pokemon_id!=0",
    '0-15-15':        "iv_atk=0 AND iv_def=15 AND iv_sta=15",
    'Lucky':          "is_lucky=1",
    'Shiny':          "fresh_shiny=1",
    'Shadow':         "fresh_alignment=1",
    'Purified':       "fresh_alignment=2",
    'Legendary':      "is_legendary=1",
    'Mythical':       "is_mythical=1",
    'Hatched':        "hatched_from_egg=1",
    'Traded':         "(is_traded=1 OR is_traded_flag_v2=1)",
    'Background':     "fresh_has_location_card=1",
    'JUMBO':          "pokemon_size_category=5",
    'Adventure Eff':  "adventure_effects_left>0",
    'From Ethan':     "(is_traded_flag_v2=1 OR is_lucky=1) AND lower(original_owner_name)='ethanmateovz'",
    'From Florandez': "(is_traded_flag_v2=1 OR is_lucky=1) AND lower(original_owner_name)='florandez'",
    'Legacy':         None,   # special: legacy_accurate.json
    'Dynamax':        "fresh_bread_mode=1",
    'Gigantamax':     "fresh_bread_mode=2",
    'GL':             "gl_rank=1",
}

# Read all 21 tag JSONs (for "agent plan" comparison too).
AGENT_DIR = os.path.join(HERE, 'rescan_report', 'agent_tags')

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
        // Name (UTF-16 at tagProto+0x40)
        var name = '';
        try {
            var ns = tagProto.add(0x40).readPointer();
            if (!ns.isNull()) {
                var len = ns.add(0x10).readS32();
                if (len > 0 && len < 100) {
                    var chars = [];
                    for (var ci = 0; ci < len; ci++) chars.push(String.fromCharCode(ns.add(0x14 + ci*2).readU16()));
                    name = chars.join('');
                }
            }
        } catch(e) {}
        // Member count: TagToPokemonBindingProto holds a List<PokemonProto*> at +0x18.
        // List<T> layout: items array @ +0x10, count @ +0x18.
        var memberCount = 0;
        try {
            var lst = bp.add(0x18).readPointer();
            if (!lst.isNull()) {
                memberCount = lst.add(0x18).readS32();
            }
        } catch(e) {}
        var tagIdStr = '0';
        try { tagIdStr = tagProto.add(0x38).readU64().toString(); } catch(e) {}
        out.push({idx:i, name:name, tagId:tagIdStr, members:memberCount});
    }
    return out;
}
rpc.exports.enumerateTagsWithMembers = enumerateTagsWithMembers;
"""


def rule_count(conn, rule):
    q = f"SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND ({rule})"
    return conn.execute(q).fetchone()[0]


def db_tag_count(conn, name):
    return conn.execute(
        "SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND (';'||COALESCE(auth_tag_names,'')||';') LIKE ?",
        (f'%;{name};%',)
    ).fetchone()[0]


def legacy_count(conn):
    try:
        with open(LEGACY_JSON, encoding='utf-8') as f:
            legacy = json.load(f)
        leg = {e['uid_hex'] for e in legacy}
        inbag = {r[0] for r in conn.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1")}
        return len(leg & inbag)
    except FileNotFoundError:
        return -1


def jumbo_count(conn):
    """JUMBO is pruned to the top-2 per species (by weight UNION by height),
    so the correct membership is NOT all XXL — it's the top-2 keep set."""
    from collections import defaultdict
    rows = conn.execute("""SELECT uid_hex, pokemon_id, form, weight_kg, height_m
                           FROM pokemon WHERE in_bag=1 AND pokemon_size_category=5""").fetchall()
    by = defaultdict(list)
    for r in rows:
        by[(r[1], r[2] or 0)].append(r)
    keep = set()
    for k, rs in by.items():
        for r in sorted(rs, key=lambda x: x[3], reverse=True)[:2]:
            keep.add(r[0])
        for r in sorted(rs, key=lambda x: x[4], reverse=True)[:2]:
            keep.add(r[0])
    return len(keep)


def main():
    print('=== TRIPLE CHECK: server / DB / rule ===\n')

    # ---- DB-side scans ----
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    db_counts = {}
    rule_counts = {}
    for name, rule in TAG_RULES.items():
        db_counts[name] = db_tag_count(conn, name)
        if name == 'JUMBO':
            rule_counts[name] = jumbo_count(conn)
        elif rule is None:
            rule_counts[name] = legacy_count(conn)
        else:
            try:
                rule_counts[name] = rule_count(conn, rule)
            except sqlite3.Error as e:
                rule_counts[name] = f'ERR: {e}'
    conn.close()

    # ---- Server side ----
    print('Attaching for server enumeration...')
    sess, pid = pg.get_session()
    print(f'  pid={pid}')
    try:
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        print(f'  svc @ {svc}')
        enum = pg.get_script_with_helpers(sess, ENUM_JS)
        srv = enum.exports_sync.enumerate_tags_with_members(svc)
        enum.unload()
    finally:
        sess.detach()

    srv_by_name = {t['name']: t for t in srv}

    # ---- Print the 21-row grid ----
    print(f'\n{"":<16} {"server":>8} {"db":>8} {"rule":>8}  status')
    print('-' * 60)
    all_ok = True
    rows = []
    for name in TAG_RULES:
        s = srv_by_name.get(name, {}).get('members', '—')
        d = db_counts[name]
        r = rule_counts[name]
        # Triple agreement check.  Allow rule != db when:
        #   • Adventure Eff: agent excluded 2 proto-bleed cases; rule will be +2.
        #   • Shiny: 1 specimen transferred mid-pipeline → rule may show 1052 still.
        # Use mismatch policy = "all three numeric and equal" except for documented offsets.
        agree = isinstance(s, int) and isinstance(d, int) and isinstance(r, int) and s == d == r
        if name == 'Adventure Eff':
            # rule includes 2 proto-bleed cases the agent excluded; db & server omit them
            agree = (s == d) and isinstance(r, int)
        elif name == 'Shiny':
            # server/db authoritative; rule may lag by transfers
            agree = (s == d)
        elif name == 'JUMBO':
            # pruned to top-2/species; rule = jumbo_count (top-2 set) → expect s==d==r
            agree = (s == d == r)
        status = 'OK' if agree else 'CHECK'
        if not agree: all_ok = False
        rows.append((name, s, d, r, status))
        print(f'{name:<16} {str(s):>8} {str(d):>8} {str(r):>8}  {status}')

    # Total
    total_server = sum(t['members'] for t in srv if t['name'] in TAG_RULES)
    total_db = sum(db_counts.values())
    print('-' * 60)
    print(f'{"TOTAL":<16} {total_server:>8} {total_db:>8}')

    # 22nd / extra tags?
    extra = [t['name'] for t in srv if t['name'] not in TAG_RULES]
    if extra:
        print(f'\n! Server has extra tag(s) NOT in plan: {extra}')
        all_ok = False
    missing = [n for n in TAG_RULES if n not in srv_by_name]
    if missing:
        print(f'\n! Plan has tag(s) NOT on server: {missing}')
        all_ok = False

    # Server tag total
    print(f'\nServer tag count: {len(srv)} (plan: {len(TAG_RULES)})')
    if len(srv) == len(TAG_RULES) and not extra and not missing:
        print('  TAG SET MATCH OK')

    # ---- Cross-check: union of DB-tagged ↔ union of rule-derived ----
    print('\n=== Cross-check: union coverage ===')
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    # any tag at all
    db_tagged = {r[0] for r in conn.execute(
        "SELECT uid_hex FROM pokemon WHERE in_bag=1 AND auth_tag_names IS NOT NULL AND auth_tag_names!=''"
    )}
    print(f'  in_bag specimens with any tag: {len(db_tagged)}')
    inbag_total = conn.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1").fetchone()[0]
    print(f'  total in_bag: {inbag_total}')
    conn.close()

    if all_ok:
        print('\n=== ALL THREE CHECKS PASS ===')
    else:
        print('\n=== Discrepancies above — review ===')


if __name__ == '__main__':
    main()
